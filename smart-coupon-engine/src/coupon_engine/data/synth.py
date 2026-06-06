"""合成数据生成器 + 地面真值响应函数。

为什么需要它（plan.md 9.2 决策）：
- 95% 商家只有订单表+优惠券表，初版要在没有真实数据时也能跑通、能 demo。
- 合成数据必须植入**真实可被模型学到的 uplift 结构**，否则模型学不到东西、
  A/B 看不出差异，demo 没有说服力。

设计：每个用户属于 Uplift 四象限之一（方案 3.5），象限决定：
  1) 自然购买概率（base）
  2) 对券面额的真实增量响应（uplift，随面额边际递减）
  3) 历史行为特征（订单频率/近度/金额、历史核销率）——让特征与象限相关，可学习

时间线（单一实验切点 T0）：
  - 特征期  : order_time / receive_time < T0  → 用于算 RFM 特征
  - 处理(treatment): 在 T0 给约一半用户发券（随机面额）→ 历史随机实验，便于无偏建模
  - 结果(outcome) : (T0, T0+conversion_days] 内是否购买

ground-truth 响应函数 `purchase_prob` 同时被 experiment/abtest.py 复用，
用于在 A/B 模拟中计算各策略下的反事实结果。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

# ---- Uplift 四象限定义 ----
# base       : 不发券时的自然购买概率
# u_max      : 券面额无穷大时的最大增量（可为负=Sleeping Dog）
# value_scale: 边际递减尺度，uplift(v) = u_max * (1 - exp(-v/value_scale))
# share      : 人群占比
# n_orders   : 特征期订单数的泊松均值
# recency    : 最近一单距 T0 天数的均值（越大越流失）
# avg_amount : 客单价均值
# redeem     : 历史券核销率均值
SEGMENTS: Dict[str, Dict[str, float]] = {
    "sure_thing":   dict(base=0.55, u_max=0.03,  value_scale=12, share=0.20,
                         n_orders=8.0, recency=10,  avg_amount=120, redeem=0.15),
    "persuadable":  dict(base=0.08, u_max=0.22,  value_scale=12, share=0.35,
                         n_orders=2.0, recency=55,  avg_amount=70,  redeem=0.55),
    "lost_cause":   dict(base=0.02, u_max=0.01,  value_scale=12, share=0.25,
                         n_orders=0.6, recency=130, avg_amount=50,  redeem=0.10),
    "sleeping_dog": dict(base=0.40, u_max=-0.08, value_scale=12, share=0.20,
                         n_orders=6.0, recency=14,  avg_amount=90,  redeem=0.20),
}

CATEGORIES = ["美妆", "食品", "服饰", "数码", "家居"]


def segment_uplift(segment: str, coupon_value: float) -> float:
    """某象限在某面额下的真实增量（地面真值）。"""
    s = SEGMENTS[segment]
    return s["u_max"] * (1.0 - np.exp(-coupon_value / s["value_scale"]))


def purchase_prob(segment: str, treated: bool, coupon_value: float = 0.0) -> float:
    """地面真值购买概率。treated=False 时为自然概率；True 时叠加 uplift。

    同时供合成数据生成与 A/B 反事实模拟使用，保证两边口径一致。
    """
    s = SEGMENTS[segment]
    p = s["base"] + (segment_uplift(segment, coupon_value) if treated else 0.0)
    return float(np.clip(p, 0.001, 0.999))


@dataclass
class SyntheticData:
    orders: pd.DataFrame
    coupons: pd.DataFrame
    cutoff: datetime
    truth: pd.DataFrame  # user_id -> segment（仅用于评估/调试，真实场景不可得）


def generate(
    n_users: int = 5000,
    coupon_values: List[float] | None = None,
    conversion_days: int = 14,
    reference_date: datetime | None = None,
    seed: int = 42,
) -> SyntheticData:
    """生成合成的订单表 + 优惠券表。

    返回 SyntheticData：orders/coupons 为对外的两张 CSV 等价结构；
    cutoff(T0) 与 truth(象限) 仅用于内部评估。
    """
    rng = np.random.default_rng(seed)
    coupon_values = coupon_values or [5.0, 10.0, 20.0, 50.0]
    now = reference_date or datetime(2026, 6, 5)
    cutoff = now - timedelta(days=conversion_days)  # T0：发券决策点

    seg_names = list(SEGMENTS.keys())
    seg_probs = np.array([SEGMENTS[s]["share"] for s in seg_names])
    seg_probs = seg_probs / seg_probs.sum()
    user_segments = rng.choice(seg_names, size=n_users, p=seg_probs)

    order_rows: List[dict] = []
    coupon_rows: List[dict] = []
    coupon_seq = 0

    for i in range(n_users):
        uid = f"u{i:06d}"
        seg = user_segments[i]
        s = SEGMENTS[seg]

        # ---- 特征期订单（T0 之前）----
        n_ord = rng.poisson(s["n_orders"])
        last_gap = max(1.0, rng.normal(s["recency"], s["recency"] * 0.4))
        for j in range(n_ord):
            # 最近一单在 last_gap 天前，其余更早，散布在 180 天窗口内
            gap = last_gap + rng.exponential(30) if j > 0 else last_gap
            ts = cutoff - timedelta(days=float(min(gap, 179)))
            amount = max(1.0, rng.normal(s["avg_amount"], s["avg_amount"] * 0.3))
            order_rows.append(dict(
                user_id=uid, order_id=f"o{i:06d}_{j}", order_time=ts,
                amount=round(amount, 2), category=rng.choice(CATEGORIES),
            ))

        # ---- 历史券（特征期，用于核销率特征）----
        n_hist_coupon = rng.poisson(2.0)
        for k in range(n_hist_coupon):
            cv = float(rng.choice(coupon_values))
            r_ts = cutoff - timedelta(days=float(rng.uniform(20, 170)))
            used = rng.random() < s["redeem"]
            u_ts = r_ts + timedelta(days=float(rng.uniform(1, 10))) if used else pd.NaT
            coupon_seq += 1
            coupon_rows.append(dict(
                user_id=uid, coupon_id=f"c{coupon_seq:07d}", coupon_value=cv,
                receive_time=r_ts, use_time=u_ts, used=int(used),
            ))

        # ---- T0 处理：随机一半用户发券（随机面额）----
        treated = rng.random() < 0.5
        treat_value = float(rng.choice(coupon_values)) if treated else 0.0
        if treated:
            coupon_seq += 1
            t_ts = cutoff  # 所有处理券都在 T0 发放
            # 该券是否被核销：购买且核销率相关（简化：买了就有较高概率核销）
            coupon_rows.append(dict(
                user_id=uid, coupon_id=f"c{coupon_seq:07d}", coupon_value=treat_value,
                receive_time=t_ts, use_time=pd.NaT, used=0,  # 先占位，购买后回填
            ))

        # ---- outcome：T0 之后是否购买 ----
        p = purchase_prob(seg, treated, treat_value)
        bought = rng.random() < p
        if bought:
            o_ts = cutoff + timedelta(days=float(rng.uniform(0.1, conversion_days)))
            amount = max(1.0, rng.normal(s["avg_amount"], s["avg_amount"] * 0.3))
            order_rows.append(dict(
                user_id=uid, order_id=f"o{i:06d}_buy", order_time=o_ts,
                amount=round(amount, 2), category=rng.choice(CATEGORIES),
            ))
            # 若发了券且购买，则按核销率回填该处理券为已核销
            if treated and rng.random() < 0.7:
                coupon_rows[-1]["use_time"] = o_ts
                coupon_rows[-1]["used"] = 1

    orders = pd.DataFrame(order_rows)
    coupons = pd.DataFrame(coupon_rows)
    truth = pd.DataFrame({"user_id": [f"u{i:06d}" for i in range(n_users)],
                          "segment": user_segments})

    # 打乱行顺序，更像真实导出
    orders = orders.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    coupons = coupons.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    return SyntheticData(orders=orders, coupons=coupons, cutoff=cutoff, truth=truth)
