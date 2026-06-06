"""对外 3 表输入的摄取与适配（plan.md 4.0，需求 D3）。

对外契约：客户 customers / 商品 products / 行为日志 behavior 三张表。
本模块负责：
  1) 校验 + 规整（列名支持中文/英文别名、类型转换）；
  2) 适配成引擎内部既有的 orders + coupons 两张表（loader 契约，plan.md 4.1/4.2）；
  3) 从客户属性 + 行为漏斗派生 extra_features（并入特征矩阵）。

「券」这一维通过行为日志里的 行为类型=领券/用券 承载（ADR 9.6）：
  领券 = treatment（发券），领券后下单 = outcome，用券 → 核销率特征。
没有领券/用券事件时，coupons 为空 → 无法估计 uplift（上层会报错提示）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd

from .loader import DataValidationError

# ---- 列名别名（中文/英文 → 规范英文名）----
CUSTOMER_ALIASES = {
    "uid": "uid", "user_id": "uid", "用户id": "uid", "客户id": "uid",
    "age": "age", "年龄": "age",
    "gender": "gender", "性别": "gender",
    "city": "city", "城市": "city",
    "register_date": "register_date", "注册日期": "register_date", "注册时间": "register_date",
}
PRODUCT_ALIASES = {
    "item_id": "item_id", "product_id": "item_id", "商品id": "item_id", "商品": "item_id",
    "price": "price", "价格": "price", "单价": "price",
    "category": "category", "品类": "category", "类目": "category",
}
BEHAVIOR_ALIASES = {
    "uid": "uid", "user_id": "uid", "用户id": "uid", "客户id": "uid",
    "behavior_type": "behavior_type", "行为类型": "behavior_type", "行为": "behavior_type",
    "item_id": "item_id", "product_id": "item_id", "商品id": "item_id", "商品": "item_id",
    "behavior_time": "behavior_time", "行为时间": "behavior_time", "时间": "behavior_time",
    "coupon_value": "coupon_value", "券面额": "coupon_value", "面额": "coupon_value",
    "coupon_id": "coupon_id", "券id": "coupon_id",
    "amount": "amount", "金额": "amount", "订单金额": "amount",
}

# ---- 行为类型枚举（中文/英文 → 规范）----
BEHAVIOR_KINDS = {
    "浏览": "view", "view": "view", "browse": "view",
    "加购": "cart", "cart": "cart", "addcart": "cart", "add_cart": "cart",
    "下单": "order", "order": "order", "purchase": "order", "buy": "order",
    "领券": "receive_coupon", "receive_coupon": "receive_coupon", "receive": "receive_coupon",
    "用券": "use_coupon", "use_coupon": "use_coupon", "use": "use_coupon", "redeem": "use_coupon",
}

CUSTOMER_REQUIRED = ["uid"]
PRODUCT_REQUIRED = ["item_id", "price"]
BEHAVIOR_REQUIRED = ["uid", "behavior_type", "behavior_time"]


@dataclass
class InternalData:
    """3 表适配后的内部数据：可直接喂给现有 pipeline。"""
    orders: pd.DataFrame        # 内部订单表契约
    coupons: pd.DataFrame       # 内部优惠券表契约
    extra_features: pd.DataFrame  # 客户/行为派生特征（index=uid）


def _rename(df: pd.DataFrame, aliases: Dict[str, str]) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    mapping = {c: aliases[c.lower()] for c in df.columns if c.lower() in aliases}
    return df.rename(columns=mapping)


def _require(df: pd.DataFrame, required: List[str], name: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise DataValidationError(
            f"{name} 缺少必填列: {missing}；当前列: {list(df.columns)}"
        )


def load_customers(source) -> pd.DataFrame:
    df = source.copy() if isinstance(source, pd.DataFrame) else pd.read_csv(source)
    df = _rename(df, CUSTOMER_ALIASES)
    _require(df, CUSTOMER_REQUIRED, "customers")
    df["uid"] = df["uid"].astype(str)
    if "age" in df.columns:
        df["age"] = pd.to_numeric(df["age"], errors="coerce")
    if "register_date" in df.columns:
        df["register_date"] = pd.to_datetime(df["register_date"], errors="coerce")
    return df.drop_duplicates(subset=["uid"]).reset_index(drop=True)


def load_products(source) -> pd.DataFrame:
    df = source.copy() if isinstance(source, pd.DataFrame) else pd.read_csv(source)
    df = _rename(df, PRODUCT_ALIASES)
    _require(df, PRODUCT_REQUIRED, "products")
    df["item_id"] = df["item_id"].astype(str)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    if "category" not in df.columns:
        df["category"] = "未知"
    df["category"] = df["category"].fillna("未知").astype(str)
    df = df.dropna(subset=["price"])
    df = df[df["price"] > 0]
    return df.drop_duplicates(subset=["item_id"]).reset_index(drop=True)


def load_behavior(source) -> pd.DataFrame:
    df = source.copy() if isinstance(source, pd.DataFrame) else pd.read_csv(source)
    df = _rename(df, BEHAVIOR_ALIASES)
    _require(df, BEHAVIOR_REQUIRED, "behavior")
    df["uid"] = df["uid"].astype(str)
    df["behavior_time"] = pd.to_datetime(df["behavior_time"], errors="coerce")
    df["kind"] = (
        df["behavior_type"].astype(str).str.strip().str.lower().map(BEHAVIOR_KINDS)
    )
    unknown = df.loc[df["kind"].isna(), "behavior_type"].unique()
    if len(unknown):
        raise DataValidationError(
            f"behavior 出现无法识别的行为类型: {list(unknown)[:5]}；"
            f"支持：浏览/加购/下单/领券/用券（或 view/cart/order/receive_coupon/use_coupon）"
        )
    if "item_id" in df.columns:
        df["item_id"] = df["item_id"].astype("string")
    else:
        df["item_id"] = pd.Series(pd.NA, index=df.index, dtype="string")
    if "coupon_value" in df.columns:
        df["coupon_value"] = pd.to_numeric(df["coupon_value"], errors="coerce")
    else:
        df["coupon_value"] = np.nan
    if "coupon_id" in df.columns:
        df["coupon_id"] = df["coupon_id"].astype("string")
    else:
        df["coupon_id"] = pd.Series(pd.NA, index=df.index, dtype="string")
    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    else:
        df["amount"] = np.nan
    df = df.dropna(subset=["behavior_time"]).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# 适配：3 表 → 内部 orders + coupons + extra_features
# ---------------------------------------------------------------------------
def _build_orders(behavior: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    ord_b = behavior[behavior["kind"] == "order"].copy()
    if ord_b.empty:
        return pd.DataFrame(columns=["user_id", "order_id", "order_time", "amount", "category"])
    price_map = products.set_index("item_id")["price"]
    cat_map = products.set_index("item_id")["category"]
    item = ord_b["item_id"].astype(object)
    ord_b["amount"] = ord_b["amount"].fillna(item.map(price_map))
    ord_b["category"] = item.map(cat_map).fillna("未知")
    ord_b = ord_b.dropna(subset=["amount"])
    ord_b = ord_b[ord_b["amount"] > 0]
    ord_b = ord_b.sort_values("behavior_time").reset_index(drop=True)
    ord_b["order_id"] = "o_" + ord_b.index.astype(str)
    return pd.DataFrame({
        "user_id": ord_b["uid"].astype(str),
        "order_id": ord_b["order_id"],
        "order_time": ord_b["behavior_time"],
        "amount": ord_b["amount"].astype(float),
        "category": ord_b["category"].astype(str),
    })


def _build_coupons(behavior: pd.DataFrame) -> pd.DataFrame:
    recv = behavior[behavior["kind"] == "receive_coupon"].copy()
    use = behavior[behavior["kind"] == "use_coupon"].copy()
    cols = ["user_id", "coupon_id", "coupon_value", "receive_time", "use_time", "used"]
    if recv.empty:
        return pd.DataFrame(columns=cols)

    recv = recv.sort_values("behavior_time").reset_index(drop=True)
    # 缺 coupon_id 时自动生成
    gen_ids = "cg_" + recv.index.astype(str)
    recv["coupon_id"] = recv["coupon_id"].astype(object)
    recv.loc[recv["coupon_id"].isna(), "coupon_id"] = gen_ids[recv["coupon_id"].isna()]
    recv["coupon_value"] = recv["coupon_value"].fillna(0.0)

    coupons = pd.DataFrame({
        "user_id": recv["uid"].astype(str),
        "coupon_id": recv["coupon_id"].astype(str),
        "coupon_value": recv["coupon_value"].astype(float),
        "receive_time": recv["behavior_time"],
        "use_time": pd.NaT,
        "used": 0,
    }).reset_index(drop=True)

    # ---- 配对用券 ----
    by_id = {cid: i for i, cid in enumerate(coupons["coupon_id"])}
    # 每个用户未核销券（按领券时间）索引，供近似配对
    user_pool: Dict[str, List[int]] = {}
    for i, row in coupons.iterrows():
        user_pool.setdefault(row["user_id"], []).append(i)

    for _, u in use.sort_values("behavior_time").iterrows():
        cid = u["coupon_id"]
        idx = None
        if pd.notna(cid) and str(cid) in by_id:
            idx = by_id[str(cid)]
        else:
            # 近似：该用户最早一张「领券时间<=用券时间」且未核销的券
            for cand in user_pool.get(str(u["uid"]), []):
                if coupons.at[cand, "used"] == 0 and coupons.at[cand, "receive_time"] <= u["behavior_time"]:
                    idx = cand
                    break
        if idx is not None and coupons.at[idx, "used"] == 0:
            coupons.at[idx, "used"] = 1
            coupons.at[idx, "use_time"] = u["behavior_time"]
    return coupons[cols]


def _build_extra_features(
    customers: pd.DataFrame, products: pd.DataFrame, behavior: pd.DataFrame
) -> pd.DataFrame:
    ref = behavior["behavior_time"].max()
    users = pd.Index(behavior["uid"].unique(), name="uid")
    feat = pd.DataFrame(index=users)

    # ---- 客户属性 ----
    c = customers.set_index("uid")
    if "age" in c.columns:
        feat["x_age"] = c["age"]
    if "gender" in c.columns:
        g = c["gender"].astype(str).str.strip().str.lower()
        feat["x_is_male"] = g.isin(["男", "m", "male", "1"]).astype(float)
    if "register_date" in c.columns:
        feat["x_tenure_days"] = (ref - c["register_date"]).dt.total_seconds() / 86400.0

    # ---- 行为漏斗 ----
    b = behavior
    feat["x_n_view"] = b[b["kind"] == "view"].groupby("uid").size()
    feat["x_n_cart"] = b[b["kind"] == "cart"].groupby("uid").size()
    recent = b[(b["kind"] == "view") & ((ref - b["behavior_time"]).dt.days <= 30)]
    feat["x_n_view_30"] = recent.groupby("uid").size()
    feat = feat.fillna(0.0)
    feat["x_cart_rate"] = feat["x_n_cart"] / feat["x_n_view"].clip(lower=1)

    # ---- 交互商品均价（价格敏感度代理）----
    inter = b[b["kind"].isin(["view", "cart", "order"])].copy()
    price_map = products.set_index("item_id")["price"]
    inter["price"] = inter["item_id"].astype(object).map(price_map)
    feat["x_avg_interact_price"] = inter.groupby("uid")["price"].mean()

    return feat.fillna(0.0)


def to_internal(
    customers, products, behavior
) -> InternalData:
    """把对外 3 表适配成内部 orders + coupons + extra_features。"""
    cust = load_customers(customers)
    prod = load_products(products)
    beh = load_behavior(behavior)
    orders = _build_orders(beh, prod)
    coupons = _build_coupons(beh)
    extra = _build_extra_features(cust, prod, beh)
    return InternalData(orders=orders, coupons=coupons, extra_features=extra)
