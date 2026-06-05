"""全局预算约束下的发券分配（plan.md 5.5 / 方案 3.4 双层优化 Layer 2）。

输入：每用户×每面额 uplift、总预算 B、预期核销率、面额表。
约束：Σ(面额 × 预期核销率) ≤ B   （只统计实际发出的券）
目标：最大化 Σ uplift

初版实现：贪心——把所有正 uplift 的 (用户, 面额) 作为候选，按
「性价比 = uplift / 预期成本」降序选取，每个用户至多发一张券，直到预算耗尽。
简单、可解释、可跑通；精确解（LP, scipy.optimize.linprog）见 plan.md 第 8 节升级项。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import Config, DEFAULT_CONFIG


@dataclass
class AllocationResult:
    table: pd.DataFrame    # index=user_id; cols: selected, assigned_value, exp_uplift, exp_cost
    total_cost: float
    total_uplift: float
    n_selected: int
    budget: float

    def summary(self) -> dict:
        return {
            "budget": round(self.budget, 2),
            "total_cost": round(self.total_cost, 2),
            "budget_used_pct": round(100 * self.total_cost / self.budget, 1) if self.budget else 0.0,
            "n_selected": self.n_selected,
            "total_expected_uplift": round(self.total_uplift, 2),
        }


def allocate_budget(
    uplift_by_value: pd.DataFrame, config: Config = DEFAULT_CONFIG
) -> AllocationResult:
    values = [float(v) for v in uplift_by_value.columns]
    budget = config.total_budget

    # 构造候选 (user, value, uplift, cost)，只保留正 uplift
    candidates = []
    for v in values:
        cost = config.cost_per_award(v)
        col = uplift_by_value[v]
        for uid, up in col.items():
            if up > 0:
                candidates.append((up / cost, uid, v, float(up), cost))
    candidates.sort(key=lambda t: t[0], reverse=True)  # 按性价比降序

    assigned: dict[str, tuple[float, float, float]] = {}  # uid -> (value, uplift, cost)
    spent = 0.0
    for _eff, uid, v, up, cost in candidates:
        if uid in assigned:
            continue
        if spent + cost > budget:
            continue
        assigned[uid] = (v, up, cost)
        spent += cost

    rows = []
    for uid in uplift_by_value.index:
        if uid in assigned:
            v, up, cost = assigned[uid]
            rows.append((uid, True, v, up, cost))
        else:
            rows.append((uid, False, 0.0, 0.0, 0.0))
    table = pd.DataFrame(
        rows, columns=["user_id", "selected", "assigned_value", "exp_uplift", "exp_cost"]
    ).set_index("user_id")

    return AllocationResult(
        table=table,
        total_cost=spent,
        total_uplift=float(table["exp_uplift"].sum()),
        n_selected=int(table["selected"].sum()),
        budget=budget,
    )
