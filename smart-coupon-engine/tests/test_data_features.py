"""数据层 + 特征层测试。"""
from __future__ import annotations

import pandas as pd

from coupon_engine.data.loader import (DataValidationError, load_coupons,
                                       load_orders)
from coupon_engine.data.synth import purchase_prob, segment_uplift


def test_synth_schema(synth):
    for col in ["user_id", "order_id", "order_time", "amount"]:
        assert col in synth.orders.columns
    for col in ["user_id", "coupon_id", "coupon_value", "receive_time", "used"]:
        assert col in synth.coupons.columns
    assert len(synth.orders) > 0 and len(synth.coupons) > 0


def test_loader_validates_missing_columns():
    bad = pd.DataFrame({"user_id": ["a"]})
    try:
        load_orders(bad)
        assert False, "应抛 DataValidationError"
    except DataValidationError:
        pass


def test_loader_roundtrip(synth):
    o = load_orders(synth.orders)
    c = load_coupons(synth.coupons)
    assert o["amount"].gt(0).all()
    assert set(c["used"].unique()) <= {0, 1}


def test_ground_truth_uplift_signs():
    # persuadable 正、sleeping_dog 负（四象限正确性）
    assert segment_uplift("persuadable", 20) > 0
    assert segment_uplift("sleeping_dog", 20) < 0
    # 边际递减：面额越大 uplift 越大但增速放缓
    assert segment_uplift("persuadable", 50) > segment_uplift("persuadable", 10)


def test_purchase_prob_bounds():
    p = purchase_prob("lost_cause", True, 50)
    assert 0.0 <= p <= 1.0


def test_training_frame(training):
    assert len(training.X) == len(training.treatment) == len(training.outcome)
    assert set(training.treatment.unique()) <= {0, 1}
    assert set(training.outcome.unique()) <= {0, 1}
    # 应存在正的平均处理效应（合成数据植入了真实 uplift）
    ate = (training.outcome[training.treatment == 1].mean()
           - training.outcome[training.treatment == 0].mean())
    assert ate > 0
