"""合成「客户 / 商品 / 行为日志」3 表（plan.md 4.0，需求 D3）。

复用 synth.py 的四象限 uplift 地面真值（SEGMENTS / purchase_prob），
保证 3 表里也植入「可被模型学到的真实增量」，demo 才有说服力。

时间线（与 synth.py 一致，单一切点 T0）：
  - 特征期：浏览/加购/下单/历史领券用券 在 T0 之前
  - 处理 ：约一半用户在 T0『领券』（随机面额）
  - 结果 ：(T0, T0+conversion_days] 内是否『下单』
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List

import numpy as np
import pandas as pd

from .synth import CATEGORIES, SEGMENTS, purchase_prob

GENDERS = ["男", "女"]


@dataclass
class SyntheticTables:
    customers: pd.DataFrame
    products: pd.DataFrame
    behavior: pd.DataFrame
    truth: pd.DataFrame  # uid -> segment（仅评估用）


def generate_tables(
    n_users: int = 3000,
    n_products: int = 200,
    coupon_values: List[float] | None = None,
    conversion_days: int = 14,
    reference_date: datetime | None = None,
    seed: int = 42,
) -> SyntheticTables:
    rng = np.random.default_rng(seed)
    coupon_values = coupon_values or [5.0, 10.0, 20.0, 50.0]
    now = reference_date or datetime(2026, 6, 5)
    cutoff = now - timedelta(days=conversion_days)  # T0

    # ---- 商品目录 ----
    prod_rows = []
    for p in range(n_products):
        price = round(float(max(5.0, rng.lognormal(mean=4.0, sigma=0.6))), 2)  # ~¥55 中位
        prod_rows.append(dict(
            item_id=f"p{p:05d}", price=price, category=rng.choice(CATEGORIES),
        ))
    products = pd.DataFrame(prod_rows)
    item_ids = products["item_id"].to_numpy()

    seg_names = list(SEGMENTS.keys())
    seg_probs = np.array([SEGMENTS[s]["share"] for s in seg_names])
    seg_probs = seg_probs / seg_probs.sum()
    user_segments = rng.choice(seg_names, size=n_users, p=seg_probs)

    cust_rows, beh_rows = [], []
    coupon_seq = 0

    def pick_item() -> str:
        return str(item_ids[rng.integers(0, n_products)])

    for i in range(n_users):
        uid = f"u{i:06d}"
        seg = user_segments[i]
        s = SEGMENTS[seg]

        # ---- 客户属性（与象限弱相关，便于学到一点信号）----
        age_base = {"sure_thing": 38, "persuadable": 28, "lost_cause": 45, "sleeping_dog": 35}[seg]
        age = int(np.clip(rng.normal(age_base, 8), 18, 70))
        gender = str(rng.choice(GENDERS))
        register_days = int(max(s["recency"], rng.normal(s["recency"] * 3 + 60, 60)))
        cust_rows.append(dict(
            uid=uid, age=age, gender=gender, city=str(rng.choice(["北京", "上海", "广州", "成都", "杭州"])),
            register_date=(cutoff - timedelta(days=register_days)).date().isoformat(),
        ))

        # ---- 特征期：浏览/加购/下单 ----
        n_ord = rng.poisson(s["n_orders"])
        n_view = rng.poisson(max(2.0, s["n_orders"] * 2.5))
        n_cart = rng.poisson(max(0.5, s["n_orders"] * 0.8))
        last_gap = max(1.0, rng.normal(s["recency"], s["recency"] * 0.4))

        for j in range(n_view):
            ts = cutoff - timedelta(days=float(min(rng.uniform(0, 175), 175)))
            beh_rows.append(dict(uid=uid, behavior_type="浏览", item_id=pick_item(), behavior_time=ts))
        for j in range(n_cart):
            ts = cutoff - timedelta(days=float(min(rng.uniform(0, 170), 170)))
            beh_rows.append(dict(uid=uid, behavior_type="加购", item_id=pick_item(), behavior_time=ts))
        for j in range(n_ord):
            gap = last_gap + rng.exponential(30) if j > 0 else last_gap
            ts = cutoff - timedelta(days=float(min(gap, 179)))
            beh_rows.append(dict(uid=uid, behavior_type="下单", item_id=pick_item(), behavior_time=ts))

        # ---- 历史领券/用券（特征期，喂核销率特征）----
        for k in range(rng.poisson(2.0)):
            cv = float(rng.choice(coupon_values))
            r_ts = cutoff - timedelta(days=float(rng.uniform(20, 170)))
            coupon_seq += 1
            cid = f"c{coupon_seq:07d}"
            beh_rows.append(dict(uid=uid, behavior_type="领券", item_id=None,
                                 behavior_time=r_ts, coupon_value=cv, coupon_id=cid))
            if rng.random() < s["redeem"]:
                u_ts = r_ts + timedelta(days=float(rng.uniform(1, 10)))
                beh_rows.append(dict(uid=uid, behavior_type="用券", item_id=None,
                                     behavior_time=u_ts, coupon_value=cv, coupon_id=cid))

        # ---- T0 处理：约一半用户领券 ----
        treated = rng.random() < 0.5
        treat_value = float(rng.choice(coupon_values)) if treated else 0.0
        treat_cid = None
        if treated:
            coupon_seq += 1
            treat_cid = f"c{coupon_seq:07d}"
            beh_rows.append(dict(uid=uid, behavior_type="领券", item_id=None,
                                 behavior_time=cutoff, coupon_value=treat_value, coupon_id=treat_cid))

        # ---- outcome：T0 之后是否下单 ----
        p = purchase_prob(seg, treated, treat_value)
        if rng.random() < p:
            o_ts = cutoff + timedelta(days=float(rng.uniform(0.1, conversion_days)))
            beh_rows.append(dict(uid=uid, behavior_type="下单", item_id=pick_item(), behavior_time=o_ts))
            if treated and rng.random() < 0.7:  # 买了且核销
                beh_rows.append(dict(uid=uid, behavior_type="用券", item_id=None,
                                     behavior_time=o_ts, coupon_value=treat_value, coupon_id=treat_cid))

    customers = pd.DataFrame(cust_rows)
    behavior = pd.DataFrame(beh_rows)
    # 补齐可选列、打乱顺序更像真实导出
    for col in ["coupon_value", "coupon_id"]:
        if col not in behavior.columns:
            behavior[col] = None
    behavior = behavior[["uid", "behavior_type", "item_id", "behavior_time", "coupon_value", "coupon_id"]]
    behavior = behavior.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    truth = pd.DataFrame({"uid": [f"u{i:06d}" for i in range(n_users)], "segment": user_segments})
    return SyntheticTables(customers=customers, products=products, behavior=behavior, truth=truth)
