"""周报生成（plan.md 5.8 / 方案 10.5 样式）。

把实验指标 + 分配结果 + LLM 策略解释，汇总成「能在周会上汇报」的 markdown 周报。
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from ..allocation.budget import AllocationResult
from ..experiment.abtest import ExperimentResult
from ..llm.copywriter import CopyWriter

GROUP_LABEL = {
    "A": "A 纯对照（不发券）",
    "B": "B 随机发券",
    "C": "C 规则发券",
    "D": "D 智能发券（Uplift+惊喜券）",
}


def build_report(
    exp: ExperimentResult,
    alloc: Optional[AllocationResult] = None,
    copywriter: Optional[CopyWriter] = None,
) -> str:
    gm = exp.group_metrics
    cmp = exp.comparisons
    d = cmp.loc["D"] if "D" in cmp.index else None

    # 给 LLM 的指标摘要
    metrics_for_llm = {
        "D": {
            "incremental_gmv_total": float(d["incremental_gmv_total"]) if d is not None else 0.0,
            "incremental_roi": float(d["incremental_roi"]) if d is not None else 0.0,
        },
        "saving_rate_vs_random": exp.saving_rate_vs_random,
    }
    cw = copywriter or CopyWriter()
    insight = cw.explain_strategy(metrics_for_llm)

    lines = []
    lines.append("# 智能发券引擎 · 周报\n")
    lines.append(f"> 文案/解释来源：{'真实 LLM' if cw.active else '模板（未启用 LLM）'}\n")

    # 概览（以 D 组为主）
    if "D" in gm.index:
        d_m = gm.loc["D"]
        lines.append("## 📊 本周概览（智能发券 D 组）\n")
        lines.append(f"- 实验用户：{int(d_m['n_users']):,} 人")
        lines.append(f"- 发放券数：{int(d_m['n_coupons']):,} 张")
        lines.append(f"- 核销券数：{int(d_m['n_redeemed']):,} 张（核销率 {d_m['redemption_rate']*100:.0f}%）")
        lines.append(f"- 券成本：¥{d_m['coupon_cost']:,.0f}\n")

    # 增量 GMV / ROI
    if d is not None:
        sig = exp.significance.get("D", {})
        star = "（统计显著 ✅）" if sig.get("significant_5pct") else "（未达显著 ⚠️）"
        lines.append("## 💰 增量效果（vs 不发券 A 组）\n")
        lines.append(f"- 增量 GMV：¥{d['incremental_gmv_total']:,.0f} {star}")
        lines.append(f"- 人均增量 GMV：¥{d['incremental_gmv_per_user']:.2f}")
        lines.append(f"- 增量 ROI：{d['incremental_roi']:.2f} → 每 1 元券成本带来 ¥{d['incremental_roi']:.2f} 增量")
        lines.append(f"- 相比随机发券（B），券成本节约 {exp.saving_rate_vs_random*100:.0f}%\n")

    # 四组对比表
    lines.append("## 📈 四组对比\n")
    tbl = gm.join(cmp[["incremental_gmv_total", "incremental_roi"]])
    header = "| 组 | 人数 | 发券 | 转化率 | 核销率 | 券成本 | GMV | 增量GMV | 增量ROI | 显著 |"
    sep = "|---|---|---|---|---|---|---|---|---|---|"
    lines.append(header)
    lines.append(sep)
    for g in tbl.index:
        r = tbl.loc[g]
        sig = exp.significance.get(g, {})
        sig_mark = "—" if g == "A" else ("✅" if sig.get("significant_5pct") else "✗")
        lines.append(
            f"| {GROUP_LABEL.get(g, g)} | {int(r['n_users']):,} | {int(r['n_coupons']):,} | "
            f"{r['conversion_rate']*100:.1f}% | {r['redemption_rate']*100:.0f}% | "
            f"¥{r['coupon_cost']:,.0f} | ¥{r['gmv']:,.0f} | "
            f"¥{r['incremental_gmv_total']:,.0f} | "
            f"{'—' if pd.isna(r['incremental_roi']) else format(r['incremental_roi'],'.2f')} | {sig_mark} |"
        )
    lines.append("")

    # 预算分配
    if alloc is not None:
        s = alloc.summary()
        lines.append("## 🎯 预算分配（全量）\n")
        lines.append(f"- 预算：¥{s['budget']:,.0f}，已用 ¥{s['total_cost']:,.0f}（{s['budget_used_pct']}%）")
        lines.append(f"- 选中发券用户：{s['n_selected']:,} 人")
        lines.append(f"- 预期总增量（uplift 求和）：{s['total_expected_uplift']:.1f}\n")

    # LLM 洞察
    lines.append("## 💡 本周洞察\n")
    lines.append(insight + "\n")

    return "\n".join(lines)
