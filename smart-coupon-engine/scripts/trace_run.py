"""全链路调试追踪：把示例数据从输入→输出的每一步中间结果打成一份详细日志。

用途：想看「一次本地调试，整个中间流程长啥样」时跑它，产出可读的 trace 文件。
特别详细地展示 **Uplift 模型调用的内部**（对照概率、各面额处理概率、uplift=两者之差）。

用法：
    python scripts/trace_run.py                # 默认写到 sample_run_trace.md
    python scripts/trace_run.py 800 out.md     # 自定义用户数与输出文件
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# 允许直接运行（无需 pip install -e .）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd

from coupon_engine.allocation.budget import allocate_budget
from coupon_engine.allocation.surprise import draw, surprise_weights
from coupon_engine.config import Config
from coupon_engine.data.ingest import to_internal
from coupon_engine.data.synth_tables import generate_tables
from coupon_engine.features.rfm import make_training_frame
from coupon_engine.models.registry import get_model
from coupon_engine.models.two_model import VALUE_COL, _proba1

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 50)

_BUF: list[str] = []


def log(line: str = "") -> None:
    _BUF.append(line)


def section(title: str) -> None:
    log("\n" + "=" * 78)
    log(f"## {title}")
    log("=" * 78)


def df_block(df: pd.DataFrame, rows: int = 6, note: str = "") -> None:
    log("```")
    if note:
        log(f"# {note}")
    log(df.head(rows).to_string())
    log("```")


def main() -> None:
    n_users = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else \
        Path(__file__).resolve().parents[1] / "sample_run_trace.md"

    config = Config.from_overrides(total_budget=20000)

    log(f"# 智能发券引擎 · 全链路调试追踪（sample run trace）")
    log(f"> 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}　|　用户数：{n_users}　|　随机种子：{config.random_seed}")
    log("> 本文件由 `scripts/trace_run.py` 自动生成，展示示例数据从输入到输出的全部中间步骤。")

    # ---- 0. 配置 ----
    section("0. 本次运行配置（config.py）")
    log("```")
    log(f"券面额档位 coupon_values   = {config.coupon_values}")
    log(f"总预算     total_budget     = {config.total_budget}")
    log(f"预期核销率 expected_redemption_rate = {config.expected_redemption_rate}")
    log(f"惊喜券保底 surprise_floor_weight     = {config.surprise_floor_weight}")
    log(f"模型       model_name       = {config.model_name}")
    log(f"一次发某面额券的期望成本 cost_per_award(v) = v * {config.expected_redemption_rate}")
    log("```")

    # ---- 1. 输入：3 张原始表 ----
    section("1. 输入数据：客户 / 商品 / 行为日志（对外 3 表）")
    t = generate_tables(n_users=n_users, n_products=60,
                        coupon_values=config.coupon_values, seed=config.random_seed)
    log(f"\n**① customers 客户表**　形状={t.customers.shape}")
    df_block(t.customers)
    log(f"\n**② products 商品表**　形状={t.products.shape}")
    df_block(t.products)
    log(f"\n**③ behavior 行为日志**　形状={t.behavior.shape}")
    log("```")
    log("# 行为类型分布：")
    log(t.behavior["behavior_type"].value_counts().to_string())
    log("```")
    df_block(t.behavior, rows=8, note="行为日志样例（含 领券/用券 承载 treatment 维）")

    # ---- 2. 适配：3 表 → 内部 orders/coupons + extra_features ----
    section("2. 适配层 ingest.to_internal：3 表 → 内部 2 表 + 派生特征")
    di = to_internal(t.customers, t.products, t.behavior)
    log(f"\n下单 → **orders**　形状={di.orders.shape}（金额取自商品价格）")
    df_block(di.orders)
    log(f"\n领券/用券 → **coupons**　形状={di.coupons.shape}　核销率={di.coupons['used'].mean():.3f}")
    df_block(di.coupons)
    log(f"\n客户属性+行为漏斗 → **extra_features**　形状={di.extra_features.shape}")
    df_block(di.extra_features)

    # ---- 3. 特征工程 + 打标 ----
    section("3. 特征工程 make_training_frame：RFM + 券行为 + 额外特征，并打 treatment/outcome 标签")
    tf = make_training_frame(di.orders, di.coupons, config, extra_features=di.extra_features)
    log(f"\n切点 cutoff(T0) = {tf.cutoff}")
    log(f"特征矩阵 X 形状 = {tf.X.shape}（{len(tf.feature_cols)} 个特征）")
    log("```")
    log("# 全部特征列：")
    for i in range(0, len(tf.feature_cols), 4):
        log("  " + ", ".join(tf.feature_cols[i:i + 4]))
    log("```")
    n = len(tf.X)
    n_treat = int((tf.treatment == 1).sum())
    n_out = int((tf.outcome == 1).sum())
    ate = tf.outcome[tf.treatment == 1].mean() - tf.outcome[tf.treatment == 0].mean()
    log("```")
    log(f"# 标签分布")
    log(f"样本数            : {n}")
    log(f"treatment=1(领券) : {n_treat}  ({n_treat/n:.1%})")
    log(f"outcome=1(后续购买): {n_out}  ({n_out/n:.1%})")
    log(f"朴素 ATE = P(buy|领券) - P(buy|未领券) = {ate:+.4f}  （>0 说明发券整体有正效应）")
    log("```")
    df_block(tf.X, note="特征矩阵样例（前几列）")

    # ---- 4. 训练 Uplift 模型 ----
    section("4. 训练 Uplift 模型（Two-Model：对照模型 + 处理模型）")
    model = get_model(config.model_name, random_seed=config.random_seed)
    model.fit(tf.X, tf.treatment, tf.outcome, tf.treat_value)
    log("```")
    log(f"模型类型      : {type(model).__name__}（name='{model.name}'）")
    log(f"对照模型 control_model : 用 treatment=0 的 {(tf.treatment==0).sum()} 个样本训练 P(buy | X)")
    log(f"处理模型 treat_model   : 用 treatment=1 的 {(tf.treatment==1).sum()} 个样本训练 P(buy | X, 券面额)")
    log(f"  （券面额作为处理模型的额外输入特征列 '{VALUE_COL}'）")
    log(f"两个底层分类器：{type(model.control_model).__name__} / {type(model.treat_model).__name__}")
    log("```")

    # ---- 5. 模型调用内部（最关键）：挑典型用户全程展示 ----
    section("5. 【核心】Uplift 模型调用内部：对照概率 / 各面额处理概率 / uplift=差值")
    truth = t.truth.set_index("uid")["segment"].reindex(tf.X.index)
    # 每个象限挑一个在样本里的代表用户
    sample_uids = []
    for seg in ["persuadable", "sure_thing", "sleeping_dog", "lost_cause"]:
        cand = truth[truth == seg].index
        if len(cand):
            sample_uids.append((seg, cand[0]))
    Xs = tf.X.loc[[u for _, u in sample_uids]]

    p_control = _proba1(model.control_model, Xs[model.feature_cols])
    log("\n对每个候选面额 v：把 X 加一列『券面额=v』喂给处理模型得到 P(buy|发v元券)，")
    log("再减去对照模型的 P(buy|不发券)，差值就是该用户在该面额下的 **uplift**。\n")
    for idx, (seg, uid) in enumerate(sample_uids):
        log(f"### 用户 {uid}　（真实象限：{seg}）")
        log("```")
        log(f"对照模型 P(buy | 不发券) = {p_control[idx]:.4f}")
        log(f"{'面额(元)':>8} | {'P(buy|发券)':>12} | {'uplift=差值':>12}")
        log("-" * 38)
        row = tf.X.loc[[uid]]
        for v in config.coupon_values:
            Xv = row[model.feature_cols].copy()
            Xv[VALUE_COL] = float(v)
            p_treat = float(_proba1(model.treat_model, Xv)[0])
            log(f"{v:>8.0f} | {p_treat:>12.4f} | {p_treat - p_control[idx]:>+12.4f}")
        log("```")

    # ---- 6. 全量 uplift 矩阵 ----
    section("6. 全量预测：每用户 × 每面额 的 uplift 矩阵")
    uplift = model.predict_uplift_by_value(tf.X, config.coupon_values)
    log(f"\nuplift 矩阵形状 = {uplift.shape}（行=用户，列=面额）")
    df_block(uplift)
    log("```")
    log("# 各面额的平均 uplift（全体用户）：")
    log(uplift.mean().round(4).to_string())
    log("\n# 按真实象限分组的平均 uplift（验证模型学到异质性）：")
    by_seg = uplift.groupby(truth.values).mean().round(4)
    log(by_seg.to_string())
    log("```")
    log("> 预期：persuadable（可说服）uplift 最高、sleeping_dog（睡狗）应为负——发券反而打扰。")

    # ---- 7. 每用户最优面额 ----
    section("7. 每用户最优面额 predict_best_value")
    best = model.predict_best_value(tf.X, config.coupon_values)
    df_block(best)
    log("```")
    log("# 最优面额分布（不考虑预算时，每人 uplift 最大的面额）：")
    log(best["best_value"].value_counts().sort_index().to_string())
    log("```")

    # ---- 8. 预算约束分配 ----
    section("8. 预算约束分配 allocate_budget（贪心：按 uplift/成本 性价比选人）")
    alloc = allocate_budget(uplift, config)
    s = alloc.summary()
    log("```")
    log(f"总预算        : ¥{s['budget']:,.0f}")
    log(f"已用预算      : ¥{s['total_cost']:,.0f}  ({s['budget_used_pct']}%)")
    log(f"选中发券人数  : {s['n_selected']} / {len(uplift)}")
    log(f"预期总增量    : {s['total_expected_uplift']}")
    log("```")
    df_block(alloc.table, note="分配结果（selected=是否发, assigned_value=发的面额）")

    # ---- 9. 惊喜券权重 + 抽奖 ----
    section("9. 惊喜券 surprise_weights + draw（uplift→奖池权重，保底人人有机会抽大额）")
    weights = surprise_weights(uplift, config)
    drawn = draw(weights, seed=config.random_seed)
    log("\n挑同样几个用户看其奖池权重（每面额中奖概率，每行和=1，每档≥保底）：")
    df_block(weights.loc[[u for _, u in sample_uids]], rows=len(sample_uids))
    log("```")
    log("# 这几个用户实际抽中的面额：")
    log(drawn.loc[[u for _, u in sample_uids]].to_string())
    log("```")

    # ---- 10. 最终输出表 ----
    section("10. 最终输出：每客户推荐券面额表（对客交付物）")
    a = alloc.table.reindex(tf.X.index)
    out = pd.DataFrame({
        "客户ID": list(tf.X.index),
        "推荐券面额": a["assigned_value"].to_numpy(),
        "是否发放": a["selected"].map({True: "是", False: "否"}).to_numpy(),
        "最优面额": best["best_value"].to_numpy(),
        "预期增量购买概率": a["exp_uplift"].round(4).to_numpy(),
        "预期成本": a["exp_cost"].round(2).to_numpy(),
    })
    sent = out[out["是否发放"] == "是"]
    df_block(out.sort_values("预期增量购买概率", ascending=False), rows=10,
             note="推荐结果（按预期增量降序，前 10 行）")
    log("```")
    log(f"# 汇总")
    log(f"客户总数      : {len(out)}")
    log(f"建议发券人数  : {len(sent)}  ({len(sent)/len(out):.1%})")
    log(f"预期券成本    : ¥{alloc.total_cost:,.0f} / 预算 ¥{config.total_budget:,.0f}")
    log("# 面额分布（建议发券的客户）：")
    log(sent["推荐券面额"].value_counts().sort_index().to_string())
    log("```")

    # ---- 11. 模型评估（留出测试集）----
    section("11. Uplift 模型评估（30% 留出测试集，Qini / AUUC / 分位 uplift）")
    from coupon_engine.pipeline import _holdout_evaluation

    ev = _holdout_evaluation(tf, config)
    if not ev.get("可用"):
        log(f"\n{ev.get('说明', '不可用')}")
    else:
        log("```")
        log(f"测试集样本   : {ev['样本']}")
        log(f"Qini 系数    : {ev['Qini系数']}   （>0 优于随机发券）")
        log(f"AUUC         : {ev['AUUC']}")
        log(f"整体实际uplift: {ev['整体实际uplift']}")
        log(f"Top档实际uplift: {ev['Top档实际uplift']}  → 提升倍数 {ev['提升倍数']}×")
        log(f"对照模型 AUC : {ev['对照模型AUC']}　处理模型 AUC : {ev['处理模型AUC']}")
        log("")
        log("# 分位 uplift 表（按预测 uplift 降序分 10 档，理想从上到下递减）：")
        log(f"{'分位':>6} | {'人数':>5} | {'预测uplift':>10} | {'实际uplift':>10}")
        log("-" * 44)
        for r in ev["分位表"]:
            au = r["实际uplift"]
            log(f"{r['分位']:>6} | {r['人数']:>5} | {r['预测uplift']:>+10.4f} | "
                f"{(f'{au:+.4f}' if au is not None else 'NA'):>10}")
        log("```")
        log("> 解读：Top 档真实 uplift 明显高于整体平均、且高分档 > 低分档，说明模型确实把券排给了更该发的人。")

    section("✅ 全链路结束：输入 3 表 → 适配 → 特征/打标 → Uplift 模型 → 模型评估 → 预算分配 → 惊喜券 → 输出表")

    out_path.write_text("\n".join(_BUF), encoding="utf-8")
    print(f"已生成全链路追踪日志：{out_path}")
    print(f"  共 {len(_BUF)} 行；用户数 {n_users}")


if __name__ == "__main__":
    main()
