"""A/B 实验模拟 + 显著性检验（plan.md 5.6 / 方案 10.2-10.4）。

四组（方案 10.2）：
  A 纯对照(不发券) / B 随机发券 / C 规则发券 / D Uplift 智能发券(惊喜券)
分流：hash(user_id) 稳定映射（方案 10.6 User ID Hash），用户只进一个组。

模拟逻辑：用合成数据的地面真值响应 synth.purchase_prob 计算各组反事实结果，
从而**证明** D > C > B、并量化增量 GMV / ROI / 节约率。
（真实落地时这里换成「观测到的真实实验数据」，口径相同。）
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np
import pandas as pd
from scipy import stats

from ..allocation.budget import allocate_budget
from ..allocation.surprise import draw, surprise_weights
from ..config import Config, DEFAULT_CONFIG
from ..data.synth import SEGMENTS, purchase_prob
from ..models.base import UpliftModel


def _hash_frac(user_id: str) -> float:
    h = hashlib.md5(user_id.encode("utf-8")).hexdigest()
    return (int(h[:8], 16) % 10_000) / 10_000.0


def assign_groups(user_ids, group_ratios: Dict[str, float]) -> pd.Series:
    """按 hash 把用户稳定分到各组。"""
    names = list(group_ratios)
    edges = np.cumsum([group_ratios[n] for n in names])
    edges = edges / edges[-1]
    out = {}
    for uid in user_ids:
        f = _hash_frac(str(uid))
        idx = int(np.searchsorted(edges, f, side="right"))
        out[uid] = names[min(idx, len(names) - 1)]
    return pd.Series(out, name="group")


@dataclass
class ExperimentResult:
    per_user: pd.DataFrame              # 每用户的分组/发券/结果
    group_metrics: pd.DataFrame         # 每组聚合指标
    comparisons: pd.DataFrame           # 各组 vs A 的增量
    saving_rate_vs_random: float        # D 相比 B 的券成本节约率
    significance: Dict[str, dict] = field(default_factory=dict)


def _simulate_outcomes(
    df: pd.DataFrame, segments: pd.Series, rng: np.random.Generator
) -> pd.DataFrame:
    """给定每用户 (treated, value)，用地面真值模拟购买/GMV/核销/成本。"""
    segs = segments.reindex(df.index)
    avg_amt = segs.map(lambda s: SEGMENTS[s]["avg_amount"]).astype(float)
    probs = np.array([
        purchase_prob(seg, bool(t), float(v))
        for seg, t, v in zip(segs, df["treated"], df["value"])
    ])
    purchased = rng.random(len(df)) < probs
    gmv = np.where(
        purchased,
        np.maximum(1.0, rng.normal(avg_amt.values, avg_amt.values * 0.3)),
        0.0,
    )
    # 券核销：发了券且购买则按 70% 概率核销，成本=面额
    redeemed = purchased & (df["treated"].values) & (rng.random(len(df)) < 0.7)
    cost = np.where(redeemed, df["value"].values, 0.0)
    return df.assign(purchased=purchased.astype(int), gmv=gmv,
                     redeemed=redeemed.astype(int), coupon_cost=cost)


def simulate_experiment(
    features: pd.DataFrame,
    truth_segments: pd.Series,
    model: UpliftModel,
    config: Config = DEFAULT_CONFIG,
    seed: int | None = None,
) -> ExperimentResult:
    """运行 A/B/C/D 模拟实验。features 与 truth_segments 需按 user_id 对齐。"""
    seed = config.random_seed if seed is None else seed
    rng = np.random.default_rng(seed)

    users = features.index.intersection(truth_segments.index)
    feats = features.loc[users]
    segs = truth_segments.loc[users]
    groups = assign_groups(users, config.group_ratios)

    # 每用户的 (treated, value) 由其组的策略决定
    treated = pd.Series(0, index=users)
    value = pd.Series(0.0, index=users)

    # B 组：随机面额
    mask_b = groups == "B"
    treated[mask_b] = 1
    value[mask_b] = rng.choice(config.coupon_values, size=int(mask_b.sum()))

    # C 组：规则——近 rule_inactive_days 天未消费则发固定面额
    mask_c = groups == "C"
    inactive = feats["recency_order_days"] > config.rule_inactive_days
    give_c = mask_c & inactive
    treated[give_c] = 1
    value[give_c] = config.rule_coupon_value

    # D 组：Uplift 智能发券（预算约束 + 惊喜券抽奖）
    mask_d = groups == "D"
    d_users = users[mask_d]
    if len(d_users):
        uplift_d = model.predict_uplift_by_value(feats.loc[d_users], config.coupon_values)
        d_budget = config.total_budget * config.group_ratios["D"]
        d_cfg = Config.from_overrides(
            **{**config.__dict__, "total_budget": d_budget}
        )
        alloc = allocate_budget(uplift_d, d_cfg)
        selected = alloc.table["selected"]
        sel_users = selected[selected].index
        if len(sel_users):
            weights = surprise_weights(uplift_d.loc[sel_users], config)
            drawn = draw(weights, seed=seed)
            treated[sel_users] = 1
            value[sel_users] = drawn

    per_user = pd.DataFrame({"group": groups, "treated": treated, "value": value})
    per_user = _simulate_outcomes(per_user, segs, rng)

    # ---- 各组聚合指标（方案 10.3）----
    rows = []
    for g, sub in per_user.groupby("group"):
        n = len(sub)
        n_treated = int(sub["treated"].sum())
        n_purchased = int(sub["purchased"].sum())
        n_redeemed = int(sub["redeemed"].sum())
        cost = float(sub["coupon_cost"].sum())
        gmv = float(sub["gmv"].sum())
        rows.append(dict(
            group=g, n_users=n, n_coupons=n_treated, n_purchased=n_purchased,
            conversion_rate=n_purchased / n,
            n_redeemed=n_redeemed,
            redemption_rate=(n_redeemed / n_treated) if n_treated else 0.0,
            coupon_cost=cost, cost_per_user=cost / n,
            gmv=gmv, gmv_per_user=gmv / n,
        ))
    group_metrics = pd.DataFrame(rows).set_index("group").sort_index()

    # ---- 各组 vs A 的增量（方案 10.3）----
    base = group_metrics.loc["A", "gmv_per_user"]
    comp_rows = []
    sig: Dict[str, dict] = {}
    gmv_a = per_user.loc[per_user["group"] == "A", "gmv"].values
    for g in group_metrics.index:
        m = group_metrics.loc[g]
        inc_per_user = m["gmv_per_user"] - base
        inc_total = inc_per_user * m["n_users"]
        roi = inc_total / m["coupon_cost"] if m["coupon_cost"] > 0 else np.nan
        comp_rows.append(dict(
            group=g,
            incremental_gmv_per_user=inc_per_user,
            incremental_gmv_total=inc_total,
            incremental_roi=roi,
        ))
        if g != "A":
            gmv_g = per_user.loc[per_user["group"] == g, "gmv"].values
            t, p = stats.ttest_ind(gmv_g, gmv_a, equal_var=False)
            sig[g] = {"t_stat": float(t), "p_value": float(p),
                      "significant_5pct": bool(p < 0.05)}
    comparisons = pd.DataFrame(comp_rows).set_index("group").sort_index()

    # ---- D 相比 B 的券成本节约率（方案 10.3）----
    cpu_b = group_metrics.loc["B", "cost_per_user"] if "B" in group_metrics.index else np.nan
    cpu_d = group_metrics.loc["D", "cost_per_user"] if "D" in group_metrics.index else np.nan
    saving = (cpu_b - cpu_d) / cpu_b if cpu_b and not np.isnan(cpu_b) else np.nan

    return ExperimentResult(
        per_user=per_user, group_metrics=group_metrics, comparisons=comparisons,
        saving_rate_vs_random=float(saving), significance=sig,
    )
