"""Streamlit 交互面板（plan.md 5.11）。

上传 orders.csv + coupons.csv → 跑 pipeline → 展示周报 / uplift 分布 / 四组对比
→ 下载预测结果。无数据时一键用样例数据。

启动： streamlit run app/dashboard.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
import streamlit as st

from coupon_engine.config import Config
from coupon_engine.data.loader import load_coupons, load_orders
from coupon_engine.pipeline import run_from_sample, run_pipeline

st.set_page_config(page_title="智能发券引擎", page_icon="🎁", layout="wide")
st.title("🎁 智能发券引擎 · 极简版")
st.caption("用 Uplift 模型算清楚「该不该发券、发多少券」，用惊喜券规避杀熟，用 A/B 证明省了多少钱。")

# ---- 侧边栏：参数 ----
with st.sidebar:
    st.header("参数")
    budget = st.number_input("总预算（元）", value=60000, step=5000)
    redemption = st.slider("预期核销率", 0.1, 1.0, 0.5, 0.05)
    floor = st.slider("惊喜券保底权重", 0.0, 0.2, 0.05, 0.01)
    st.markdown("---")
    use_sample = st.button("🎲 用样例数据跑一遍", use_container_width=True)

cfg = Config.from_overrides(
    total_budget=float(budget),
    expected_redemption_rate=float(redemption),
    surprise_floor_weight=float(floor),
)

# ---- 数据输入 ----
col1, col2 = st.columns(2)
orders_file = col1.file_uploader("订单表 orders.csv", type="csv")
coupons_file = col2.file_uploader("优惠券表 coupons.csv", type="csv")

result = None
if use_sample:
    sample = Path(__file__).resolve().parents[1] / "data" / "sample" / "orders.csv"
    if not sample.exists():
        st.error("样例数据不存在，请先运行： python scripts/gen_sample_data.py")
    else:
        with st.spinner("用样例数据跑全流程…"):
            result = run_from_sample(cfg)
elif orders_file and coupons_file:
    with st.spinner("处理上传的数据…"):
        orders = load_orders(pd.read_csv(orders_file))
        coupons = load_coupons(pd.read_csv(coupons_file))
        result = run_pipeline(orders, coupons, cfg, truth_segments=None)

# ---- 展示 ----
if result is not None:
    st.markdown("---")
    st.markdown(result.report)

    if result.experiment is not None:
        st.subheader("四组 GMV 对比")
        st.bar_chart(result.experiment.group_metrics["gmv"])

    st.subheader("各面额平均 Uplift")
    st.bar_chart(result.uplift_by_value.mean())

    st.subheader("惊喜券抽中面额分布")
    st.bar_chart(result.drawn_value.value_counts().sort_index())

    # 下载预测结果
    out = result.allocation.table.copy()
    out["drawn_value"] = result.drawn_value
    st.download_button(
        "⬇️ 下载发券决策结果 CSV",
        out.reset_index().to_csv(index=False).encode("utf-8-sig"),
        file_name="coupon_decision.csv",
        mime="text/csv",
    )
else:
    st.info("上传订单表 + 优惠券表，或点击侧边栏「用样例数据跑一遍」。")
