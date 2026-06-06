"""3 表输入（客户/商品/行为日志）的摄取、适配与推荐测试（需求 D3）。"""
from __future__ import annotations

import pandas as pd
import pytest

from coupon_engine.config import Config
from coupon_engine.data.ingest import DataValidationError, to_internal
from coupon_engine.data.synth_tables import generate_tables
from coupon_engine.pipeline import recommend_from_tables


@pytest.fixture(scope="module")
def tables():
    return generate_tables(n_users=800, n_products=80, seed=7)


def test_generate_tables_schema(tables):
    assert {"uid", "age", "gender", "register_date"} <= set(tables.customers.columns)
    assert {"item_id", "price", "category"} <= set(tables.products.columns)
    assert {"uid", "behavior_type", "item_id", "behavior_time"} <= set(tables.behavior.columns)
    kinds = set(tables.behavior["behavior_type"].unique())
    # 必须包含领券/用券（uplift 的 treatment 维），以及基础行为
    assert {"浏览", "下单", "领券", "用券"} <= kinds


def test_to_internal_adapter(tables):
    di = to_internal(tables.customers, tables.products, tables.behavior)
    # 下单 → orders；领券/用券 → coupons
    assert len(di.orders) > 0 and len(di.coupons) > 0
    assert {"user_id", "order_id", "order_time", "amount"} <= set(di.orders.columns)
    assert (di.orders["amount"] > 0).all()
    assert {"user_id", "coupon_id", "coupon_value", "receive_time", "used"} <= set(di.coupons.columns)
    # 至少有一部分券被核销（用券事件配对成功）
    assert di.coupons["used"].sum() > 0
    # 派生了客户/行为特征
    assert {"x_age", "x_is_male", "x_n_view", "x_cart_rate"} <= set(di.extra_features.columns)


def test_recommend_from_tables(tables):
    config = Config.from_overrides(total_budget=15000)
    r = recommend_from_tables(tables.customers, tables.products, tables.behavior, config)
    assert list(r.table.columns) == [
        "客户ID", "推荐券面额", "是否发放", "最优面额", "预期增量购买概率", "预期成本",
    ]
    assert r.summary["建议发券人数"] >= 0
    # 预算约束生效
    assert r.summary["预期券成本"] <= config.total_budget + 1e-6


def test_chinese_column_aliases():
    """中文列名应被识别并跑通。"""
    customers = pd.DataFrame({"uid": ["u1", "u2"], "年龄": [25, 40], "性别": ["男", "女"]})
    products = pd.DataFrame({"商品ID": ["p1"], "价格": [50.0], "品类": ["美妆"]})
    behavior = pd.DataFrame({
        "uid": ["u1", "u1", "u2", "u1", "u2"],
        "行为类型": ["浏览", "领券", "领券", "下单", "用券"],
        "商品ID": ["p1", None, None, "p1", None],
        "行为时间": ["2026-05-01", "2026-05-02", "2026-05-02", "2026-05-10", "2026-05-11"],
        "券面额": [None, 10, 10, None, 10],
    })
    di = to_internal(customers, products, behavior)
    assert len(di.orders) == 1            # 一条下单
    assert len(di.coupons) == 2           # 两张领券
    assert di.coupons["used"].sum() == 1  # 一次用券被配对


def test_no_coupon_raises():
    """没有领券/用券 → 无法估计 uplift，应报错。"""
    customers = pd.DataFrame({"uid": ["u1", "u2"]})
    products = pd.DataFrame({"item_id": ["p1"], "price": [10.0]})
    behavior = pd.DataFrame({
        "uid": ["u1", "u2"],
        "behavior_type": ["下单", "浏览"],
        "item_id": ["p1", "p1"],
        "behavior_time": ["2026-05-01", "2026-05-02"],
    })
    with pytest.raises(DataValidationError):
        recommend_from_tables(customers, products, behavior)
