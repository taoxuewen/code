"""RFM + 券行为 特征工程（plan.md 5.3）。

只用订单表 + 优惠券表，算出方案 2.7 节列的 10-20 个特征。
所有特征都「截至切点 cutoff(T0)」计算，严格只用 T0 之前的数据，避免泄漏。

对外：
  - feature_matrix(orders, coupons, cutoff, config) -> 特征 DataFrame（index=user_id）
  - make_training_frame(orders, coupons, config) -> TrainingFrame（特征 + treatment + outcome）

标注口径（MVP 简化，见 plan.md 4.3）：
  - cutoff(T0) = 最近一次发券时间 coupons.receive_time.max()
  - treatment  = 用户在 T0 收到券（receive_time >= T0）
  - outcome    = 用户在 T0 之后产生购买（order_time > T0）
  - 特征       = 仅用 T0 之前的订单与券
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import numpy as np
import pandas as pd

from ..config import Config, DEFAULT_CONFIG
from ..data.synth import CATEGORIES

LARGE_RECENCY = 999.0  # 从未发生时的占位天数


@dataclass
class TrainingFrame:
    X: pd.DataFrame              # 特征矩阵（index=user_id）
    treatment: pd.Series        # 0/1
    outcome: pd.Series          # 0/1
    treat_value: pd.Series      # 处理组用户收到的券面额（对照组为 0）
    feature_cols: List[str]
    cutoff: datetime


def _infer_cutoff(coupons: pd.DataFrame, orders: pd.DataFrame) -> datetime:
    """T0 = 最近一次发券时间；没有券则退化为最近一次下单时间。"""
    if len(coupons) and coupons["receive_time"].notna().any():
        return coupons["receive_time"].max()
    return orders["order_time"].max()


def feature_matrix(
    orders: pd.DataFrame,
    coupons: pd.DataFrame,
    cutoff: datetime,
    config: Config = DEFAULT_CONFIG,
) -> pd.DataFrame:
    """计算截至 cutoff 的用户特征。index 为全体用户（订单∪券里出现过的）。"""
    users = pd.Index(
        pd.concat([orders["user_id"], coupons["user_id"]]).unique(), name="user_id"
    )
    feat = pd.DataFrame(index=users)

    o = orders[orders["order_time"] < cutoff].copy()
    c = coupons[coupons["receive_time"] < cutoff].copy()
    o["age_days"] = (cutoff - o["order_time"]).dt.total_seconds() / 86400.0
    c["age_days"] = (cutoff - c["receive_time"]).dt.total_seconds() / 86400.0

    # ---- Recency ----
    feat["recency_order_days"] = o.groupby("user_id")["age_days"].min()
    feat["recency_coupon_days"] = c.groupby("user_id")["age_days"].min()

    # ---- Frequency / Monetary（按窗口）----
    for w in config.feature_windows:
        ow = o[o["age_days"] <= w]
        cw = c[c["age_days"] <= w]
        feat[f"freq_order_{w}"] = ow.groupby("user_id")["order_id"].count()
        feat[f"monetary_{w}"] = ow.groupby("user_id")["amount"].sum()
        feat[f"freq_coupon_{w}"] = cw.groupby("user_id")["coupon_id"].count()
        feat[f"freq_use_{w}"] = cw.groupby("user_id")["used"].sum()

    # ---- Monetary 汇总 ----
    g = o.groupby("user_id")["amount"]
    feat["avg_order_value"] = g.mean()
    feat["max_order_value"] = g.max()
    feat["min_order_value"] = g.min()
    feat["total_orders"] = o.groupby("user_id")["order_id"].count()

    # ---- 券行为 ----
    cg = c.groupby("user_id")
    received = cg["coupon_id"].count()
    used = cg["used"].sum()
    feat["hist_redemption_rate"] = (used / received).replace([np.inf, -np.inf], np.nan)
    feat["avg_coupon_value"] = cg["coupon_value"].mean()

    # ---- 用户属性 ----
    feat["tenure_days"] = o.groupby("user_id")["age_days"].max()  # 首单距今≈注册天数

    # ---- 品类偏好（近 90 天购买占比 one-hot）----
    recent = o[o["age_days"] <= 90]
    if len(recent):
        cat_counts = (
            recent.groupby(["user_id", "category"])["order_id"].count().unstack(fill_value=0)
        )
        cat_share = cat_counts.div(cat_counts.sum(axis=1), axis=0)
        for cat in CATEGORIES:
            feat[f"cat_{cat}"] = cat_share[cat] if cat in cat_share.columns else 0.0

    # ---- 缺失填充 ----
    feat["recency_order_days"] = feat["recency_order_days"].fillna(LARGE_RECENCY)
    feat["recency_coupon_days"] = feat["recency_coupon_days"].fillna(LARGE_RECENCY)
    feat["hist_redemption_rate"] = feat["hist_redemption_rate"].fillna(0.0)
    feat = feat.fillna(0.0)
    return feat


def make_training_frame(
    orders: pd.DataFrame,
    coupons: pd.DataFrame,
    config: Config = DEFAULT_CONFIG,
    cutoff: Optional[datetime] = None,
    extra_features: Optional[pd.DataFrame] = None,
) -> TrainingFrame:
    """从两张表派生训练样本（特征 + treatment + outcome）。

    extra_features：可选的额外用户级特征（index=user_id），D3 用来并入
    客户属性 + 行为漏斗特征；按 X.index 对齐、缺失补 0。
    """
    cutoff = cutoff or _infer_cutoff(coupons, orders)
    X = feature_matrix(orders, coupons, cutoff, config)
    if extra_features is not None and len(extra_features.columns):
        extra = extra_features.reindex(X.index).fillna(0.0)
        extra = extra[[c for c in extra.columns if c not in X.columns]]
        X = X.join(extra)

    treat_coupons = coupons[coupons["receive_time"] >= cutoff]
    treated_users = set(treat_coupons["user_id"])
    bought_users = set(orders.loc[orders["order_time"] > cutoff, "user_id"])
    # 处理组用户收到的券面额（多张取均值）
    value_by_user = treat_coupons.groupby("user_id")["coupon_value"].mean()

    treatment = pd.Series(
        [1 if u in treated_users else 0 for u in X.index], index=X.index, name="treatment"
    )
    outcome = pd.Series(
        [1 if u in bought_users else 0 for u in X.index], index=X.index, name="outcome"
    )
    treat_value = value_by_user.reindex(X.index).fillna(0.0)
    treat_value.name = "treat_value"
    feature_cols = list(X.columns)
    return TrainingFrame(
        X=X, treatment=treatment, outcome=outcome, treat_value=treat_value,
        feature_cols=feature_cols, cutoff=cutoff,
    )
