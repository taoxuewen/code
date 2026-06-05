"""模型层 + 分配层测试。"""
from __future__ import annotations

import pandas as pd

from coupon_engine.allocation.budget import allocate_budget
from coupon_engine.allocation.surprise import draw, surprise_weights


def test_model_learns_heterogeneity(model, training, synth, config):
    """模型应学到：persuadable 的 uplift 明显高于 sleeping_dog。"""
    up = model.predict_best_value(training.X, config.coupon_values)
    seg = synth.truth.set_index("user_id")["segment"]
    j = up.join(seg).dropna(subset=["segment"])
    by_seg = j.groupby("segment")["best_uplift"].mean()
    assert by_seg["persuadable"] > by_seg["sleeping_dog"]
    assert by_seg["persuadable"] > by_seg["lost_cause"]


def test_uplift_by_value_shape(model, training, config):
    up = model.predict_uplift_by_value(training.X, config.coupon_values)
    assert list(up.columns) == [float(v) for v in config.coupon_values]
    assert len(up) == len(training.X)


def test_budget_respects_constraint(model, training, config):
    up = model.predict_uplift_by_value(training.X, config.coupon_values)
    alloc = allocate_budget(up, config)
    assert alloc.total_cost <= config.total_budget + 1e-6
    assert alloc.n_selected == int(alloc.table["selected"].sum())
    # 选中的都是正 uplift
    sel = alloc.table[alloc.table["selected"]]
    assert (sel["exp_uplift"] > 0).all()


def test_surprise_weights_floor_and_sum(model, training, config):
    up = model.predict_uplift_by_value(training.X, config.coupon_values)
    w = surprise_weights(up, config)
    # 每行和为 1
    assert (w.sum(axis=1).round(6) == 1.0).all()
    # 每个面额都 >= 保底权重（人人有机会抽到大额）
    assert (w >= config.surprise_floor_weight - 1e-9).all().all()


def test_draw_in_values(model, training, config):
    up = model.predict_uplift_by_value(training.X, config.coupon_values)
    w = surprise_weights(up, config)
    d = draw(w, seed=config.random_seed)
    assert set(d.unique()) <= set(config.coupon_values)
