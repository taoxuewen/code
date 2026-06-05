"""端到端编排（plan.md 5.9）。

把数据 → 特征 → 模型 → 分配 → 惊喜券 → A/B → 报告 串成一条流程。
既供 CLI(scripts/run_pipeline.py) 调用，也供 Streamlit 面板调用。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import joblib
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
