"""端到端编排（plan.md 5.9）。

把数据 → 特征 → 模型 → 分配 → 惊喜券 → A/B → 报告 串成一条流程。
既供 CLI(scripts/run_pipeline.py) 调用，也供 Streamlit 面板调用。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import joblib
import numpy as np
import pandas as pd

from .allocation.budget import AllocationResult, allocate_budget
from .allocation.surprise import draw, surprise_weights
from .config import Config, DEFAULT_CONFIG
from .data.loader import load_coupons, load_orders
from .experiment.abtest import ExperimentResult, simulate_experiment
from .features.rfm import TrainingFrame, make_training_frame
from .llm.copywriter import CopyWriter
from .models.base import UpliftModel
from .models.registry import get_model
from .report.builder import build_report


@dataclass
class PipelineResult:
    training: TrainingFrame
    model: UpliftModel
    uplift_by_value: pd.DataFrame
    allocation: AllocationResult
    surprise: pd.DataFrame          # 每用户每面额中奖概率
    drawn_value: pd.Series          # 每用户抽中的面额
    experiment: Optional[ExperimentResult]
    report: str


def train_model(tf: TrainingFrame, config: Config = DEFAULT_CONFIG) -> UpliftModel:
    model = get_model(config.model_name, random_seed=config.random_seed)
    model.fit(tf.X, tf.treatment, tf.outcome, tf.treat_value)
    return model


def run_pipeline(
    orders: pd.DataFrame,
    coupons: pd.DataFrame,
    config: Config = DEFAULT_CONFIG,
    truth_segments: Optional[pd.Series] = None,
) -> PipelineResult:
    """跑完整流程。truth_segments 存在时执行 A/B 模拟（合成数据 demo 场景）。"""
    orders = load_orders(orders)
    coupons = load_coupons(coupons)

    tf = make_training_frame(orders, coupons, config)
    model = train_model(tf, config)

    uplift = model.predict_uplift_by_value(tf.X, config.coupon_values)
    alloc = allocate_budget(uplift, config)

    weights = surprise_weights(uplift, config)
    drawn = draw(weights, seed=config.random_seed)

    exp = None
    if truth_segments is not None:
        exp = simulate_experiment(tf.X, truth_segments, model, config)

    cw = CopyWriter(config)
    report = build_report(exp, alloc, cw) if exp is not None else _alloc_only_report(alloc, cw)

    return PipelineResult(
        training=tf, model=model, uplift_by_value=uplift, allocation=alloc,
        surprise=weights, drawn_value=drawn, experiment=exp, report=report,
    )


@dataclass
class RecommendResult:
    """对客 Web 的结果：每客户推荐券面额表 + 汇总指标（供 /api/recommend）。"""
    table: pd.DataFrame   # 中文列，一客户一行
    summary: dict
    evaluation: Optional[dict] = None  # uplift 模型评估指标（D6），样本不足时为不可用


def _holdout_evaluation(tf: TrainingFrame, config: Config) -> Optional[dict]:
    """留出集评估 uplift 模型（D6）：拆 train/test，train 上拟合一个评估专用模型，
    在 test 上用观测 treatment/outcome 算 Qini/AUUC/分位 uplift。不影响对客模型。"""
    from .models.evaluate import MIN_EVAL_SAMPLES, evaluate_uplift

    n = len(tf.X)
    if n < MIN_EVAL_SAMPLES:
        return {"可用": False, "说明": f"样本不足（{n} < {MIN_EVAL_SAMPLES}），跳过模型评估。"}
    try:
        from sklearn.model_selection import train_test_split

        idx = np.arange(n)
        strat = tf.treatment.to_numpy() if tf.treatment.nunique() == 2 else None
        tr, te = train_test_split(idx, test_size=0.3, random_state=config.random_seed,
                                  stratify=strat)
        Xtr, Xte = tf.X.iloc[tr], tf.X.iloc[te]
        eval_model = train_model(
            TrainingFrame(
                X=Xtr, treatment=tf.treatment.iloc[tr], outcome=tf.outcome.iloc[tr],
                treat_value=tf.treat_value.iloc[tr], feature_cols=tf.feature_cols,
                cutoff=tf.cutoff,
            ),
            config,
        )
        return evaluate_uplift(
            eval_model, Xte, tf.treatment.iloc[te], tf.outcome.iloc[te],
            tf.treat_value.iloc[te], config,
        )
    except Exception as exc:  # noqa: BLE001
        return {"可用": False, "说明": f"评估出错：{exc}"}


def build_recommendations(
    orders: pd.DataFrame,
    coupons: pd.DataFrame,
    config: Config = DEFAULT_CONFIG,
    extra_features: Optional[pd.DataFrame] = None,
    evaluate: bool = True,
) -> RecommendResult:
    """对客主路径：在「上传数据」上现训现算，产出每客户推荐券面额表。

    复用 特征→模型→预算分配，不做 A/B 模拟（对客不需要、也没有真值）。
    extra_features：可选额外特征（D3 客户属性 + 行为漏斗），并入特征矩阵。
    evaluate：是否额外做留出集 uplift 模型评估（D6），结果放进 RecommendResult.evaluation。
    输出列（中文，面向商家）：
      客户ID / 推荐券面额 / 是否发放 / 最优面额 / 预期增量购买概率 / 预期成本
    """
    orders = load_orders(orders)
    coupons = load_coupons(coupons)
    if coupons.empty:
        from .data.loader import DataValidationError
        raise DataValidationError(
            "没有任何「领券/用券」记录，无法估计 uplift（需要发券对照）。"
            "请在行为日志中包含『领券』『用券』行为。"
        )

    tf = make_training_frame(orders, coupons, config, extra_features=extra_features)

    evaluation = _holdout_evaluation(tf, config) if evaluate else None

    model = train_model(tf, config)

    uplift = model.predict_uplift_by_value(tf.X, config.coupon_values)
    alloc = allocate_budget(uplift, config)
    best = model.predict_best_value(tf.X, config.coupon_values)

    a = alloc.table.reindex(tf.X.index)
    table = pd.DataFrame({
        "客户ID": list(tf.X.index),
        "推荐券面额": a["assigned_value"].to_numpy(),
        "是否发放": a["selected"].map({True: "是", False: "否"}).to_numpy(),
        "最优面额": best["best_value"].to_numpy(),
        "预期增量购买概率": a["exp_uplift"].round(4).to_numpy(),
        "预期成本": a["exp_cost"].round(2).to_numpy(),
    })
    # 把"建议发券、增量高"的客户排到前面，方便商家一眼看重点
    table = table.sort_values(
        ["是否发放", "预期增量购买概率"], ascending=[True, False]
    ).reset_index(drop=True)
    # "是"在前（中文 ascending 下"否">"是"，故反转）
    table = pd.concat([
        table[table["是否发放"] == "是"],
        table[table["是否发放"] == "否"],
    ]).reset_index(drop=True)

    sent = table[table["是否发放"] == "是"]
    value_dist = (
        sent["推荐券面额"].value_counts().sort_index()
        .rename_axis("面额").reset_index(name="人数")
        .to_dict(orient="records")
    )
    n = len(table)
    summary = {
        "客户总数": int(n),
        "建议发券人数": int(len(sent)),
        "发券占比": round(100 * len(sent) / n, 1) if n else 0.0,
        "总预算": round(config.total_budget, 2),
        "预期券成本": round(alloc.total_cost, 2),
        "预算使用率": round(100 * alloc.total_cost / config.total_budget, 1)
        if config.total_budget else 0.0,
        "预期总增量(购买概率求和)": round(alloc.total_uplift, 2),
        "面额分布": value_dist,
    }
    return RecommendResult(table=table, summary=summary, evaluation=evaluation)


def recommend_from_tables(
    customers: pd.DataFrame,
    products: pd.DataFrame,
    behavior: pd.DataFrame,
    config: Config = DEFAULT_CONFIG,
) -> RecommendResult:
    """对客主路径（D3 三表输入）：客户/商品/行为日志 → 适配 → 推荐券面额。"""
    from .data.ingest import to_internal

    data = to_internal(customers, products, behavior)
    return build_recommendations(
        data.orders, data.coupons, config, extra_features=data.extra_features
    )


def _alloc_only_report(alloc: AllocationResult, cw: CopyWriter) -> str:
    s = alloc.summary()
    return (
        "# 智能发券引擎 · 分配报告\n\n"
        f"- 预算：¥{s['budget']:,.0f}，已用 ¥{s['total_cost']:,.0f}（{s['budget_used_pct']}%）\n"
        f"- 选中发券用户：{s['n_selected']:,} 人\n"
        f"- 预期总增量（uplift 求和）：{s['total_expected_uplift']:.1f}\n\n"
        "> 无真值标签，未做 A/B 模拟。真实落地时由观测实验数据补充效果评估。\n"
    )


# ---- 模型持久化（供在线推理 API）----
def save_model(model: UpliftModel, path: str) -> None:
    joblib.dump(model, path)


def load_model(path: str) -> UpliftModel:
    return joblib.load(path)


def run_from_sample(config: Config = DEFAULT_CONFIG) -> PipelineResult:
    """便捷入口：用 data/sample 跑全流程（含 A/B 模拟）。"""
    from pathlib import Path

    base = Path(__file__).resolve().parents[2] / "data" / "sample"
    orders = load_orders(str(base / "orders.csv"))
    coupons = load_coupons(str(base / "coupons.csv"))
    truth = None
    truth_path = base / "_truth_segments.csv"
    if truth_path.exists():
        truth = pd.read_csv(truth_path).set_index("user_id")["segment"]
    return run_pipeline(orders, coupons, config, truth_segments=truth)
