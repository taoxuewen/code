"""Uplift 模型评估指标测试（需求 D6）。"""
from __future__ import annotations

import numpy as np
import pytest

from coupon_engine.config import Config
from coupon_engine.data.synth_tables import generate_tables
from coupon_engine.models.evaluate import qini_auuc, uplift_by_quantile
from coupon_engine.pipeline import recommend_from_tables


def _toy_case(n=400):
    """构造一个『高分=真有效』的玩具数据：好排序应得正 Qini。"""
    score = np.linspace(1.0, 0.0, n)
    treatment = np.tile([1, 0], n // 2)
    outcome = np.array([
        (1 if (treatment[i] == 1 and score[i] > 0.5) else 0) for i in range(n)
    ])
    return score, treatment, outcome


def test_qini_positive_for_good_ranking():
    score, t, y = _toy_case()
    qini_coeff, auuc = qini_auuc(score, t, y)
    assert qini_coeff > 0      # 比随机好
    assert auuc > 0


def test_qini_near_zero_for_random_ranking():
    score, t, y = _toy_case()
    rng = np.random.default_rng(0)
    shuffled = rng.permutation(score)          # 打乱预测分 → 排序失效
    qini_coeff, _ = qini_auuc(shuffled, t, y)
    good, _ = qini_auuc(score, t, y)
    assert good > qini_coeff                    # 好排序优于乱排序


def test_quantile_table_shape_and_fields():
    score, t, y = _toy_case()
    rows = uplift_by_quantile(score, t, y, q=10)
    assert len(rows) == 10
    for r in rows:
        assert {"分位", "人数", "预测uplift", "实际uplift"} <= set(r)
    # 第一档（高分）真实 uplift 应高于最后一档
    assert rows[0]["实际uplift"] >= rows[-1]["实际uplift"]


def test_evaluation_attached_and_available():
    t = generate_tables(n_users=2500, n_products=100, seed=11)
    r = recommend_from_tables(t.customers, t.products, t.behavior,
                              Config.from_overrides(total_budget=30000))
    e = r.evaluation
    assert e is not None and e["可用"] is True
    assert {"Qini系数", "AUUC", "分位表", "样本", "提升倍数"} <= set(e)
    assert len(e["分位表"]) == 10
    assert 0.0 <= (e["对照模型AUC"] or 0) <= 1.0


def test_evaluation_unavailable_on_tiny_data():
    """样本太少时评估应优雅地标记为不可用，而非报错。"""
    t = generate_tables(n_users=120, n_products=30, seed=3)
    r = recommend_from_tables(t.customers, t.products, t.behavior)
    assert r.evaluation is not None
    assert r.evaluation["可用"] is False
