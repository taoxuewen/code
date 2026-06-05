"""实验层 + 端到端 pipeline 测试。"""
from __future__ import annotations

from coupon_engine.experiment.abtest import assign_groups, simulate_experiment
from coupon_engine.llm.copywriter import CopyWriter
from coupon_engine.pipeline import run_pipeline


def test_assign_groups_stable_and_proportional(config):
    ids = [f"u{i:05d}" for i in range(4000)]
    g1 = assign_groups(ids, config.group_ratios)
    g2 = assign_groups(ids, config.group_ratios)
    assert (g1 == g2).all()  # 稳定
    frac_d = (g1 == "D").mean()
    assert abs(frac_d - config.group_ratios["D"]) < 0.05  # 比例近似


def test_experiment_smart_beats_random(model, training, synth, config):
    seg = synth.truth.set_index("user_id")["segment"]
    res = simulate_experiment(training.X, seg, model, config)
    gm = res.group_metrics
    # 四组齐全
    assert set(gm.index) == {"A", "B", "C", "D"}
    # D 组增量 GMV 总量最高
    inc = res.comparisons["incremental_gmv_total"]
    assert inc["D"] >= inc["B"]
    # D 组相比随机发券有正的成本节约
    assert res.saving_rate_vs_random > 0


def test_llm_mock_fallback_always_works():
    """未启用 LLM 时应返回非空模板文案，保证流程不阻塞。"""
    cw = CopyWriter()  # 默认 llm_enabled=False
    assert not cw.active
    copy = cw.generate_coupon_copy(20)
    assert isinstance(copy, str) and len(copy) > 0
    expl = cw.explain_strategy({"D": {"incremental_gmv_total": 1000, "incremental_roi": 1.5},
                                "saving_rate_vs_random": 0.2})
    assert "增量" in expl


def test_pipeline_end_to_end(synth, config):
    res = run_pipeline(synth.orders, synth.coupons, config,
                       truth_segments=synth.truth.set_index("user_id")["segment"])
    assert res.experiment is not None
    assert "# 智能发券引擎" in res.report
    assert len(res.drawn_value) == len(res.training.X)
