"""订单 / 优惠券 CSV 的加载与校验。

数据契约见 plan.md 第 4 节。对外只暴露 load_orders / load_coupons，
返回规整后的 DataFrame（类型已转换、缺失已处理）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

import pandas as pd

PathLike = Union[str, Path]

ORDER_REQUIRED = ["user_id", "order_id", "order_time", "amount"]
COUPON_REQUIRED = ["user_id", "coupon_id", "coupon_value", "receive_time"]


class DataValidationError(ValueError):
    """CSV 不满足数据契约时抛出。"""


def _check_columns(df: pd.DataFrame, required: list[str], name: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise DataValidationError(
            f"{name} 缺少必填列: {missing}；当前列: {list(df.columns)}"
        )


def load_orders(source: PathLike | pd.DataFrame) -> pd.DataFrame:
    """加载订单表。source 可为 CSV 路径或已有 DataFrame。"""
    df = source.copy() if isinstance(source, pd.DataFrame) else pd.read_csv(source)
    _check_columns(df, ORDER_REQUIRED, "orders")

    df["user_id"] = df["user_id"].astype(str)
    df["order_id"] = df["order_id"].astype(str)
    df["order_time"] = pd.to_datetime(df["order_time"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    if "category" not in df.columns:
        df["category"] = "未知"
    df["category"] = df["category"].fillna("未知").astype(str)

    before = len(df)
    df = df.dropna(subset=["order_time", "amount"])
    df = df[df["amount"] > 0]
    dropped = before - len(df)
    if dropped:
        # 不静默吞掉，留痕便于排查（debug.md 思路）
        print(f"[loader] orders: 丢弃 {dropped} 行（时间/金额无效）")
    return df.reset_index(drop=True)


def load_coupons(source: PathLike | pd.DataFrame) -> pd.DataFrame:
    """加载优惠券表。used 缺失时由 use_time 是否非空推断。"""
    df = source.copy() if isinstance(source, pd.DataFrame) else pd.read_csv(source)
    _check_columns(df, COUPON_REQUIRED, "coupons")

    df["user_id"] = df["user_id"].astype(str)
    df["coupon_id"] = df["coupon_id"].astype(str)
    df["coupon_value"] = pd.to_numeric(df["coupon_value"], errors="coerce")
    df["receive_time"] = pd.to_datetime(df["receive_time"], errors="coerce")
    if "use_time" in df.columns:
        df["use_time"] = pd.to_datetime(df["use_time"], errors="coerce")
    else:
        df["use_time"] = pd.NaT

    if "used" in df.columns:
        df["used"] = pd.to_numeric(df["used"], errors="coerce").fillna(0).astype(int)
    else:
        df["used"] = df["use_time"].notna().astype(int)
    # used 与 use_time 一致性兜底
    df.loc[df["use_time"].notna(), "used"] = 1

    before = len(df)
    df = df.dropna(subset=["receive_time", "coupon_value"])
    df = df[df["coupon_value"] > 0]
    dropped = before - len(df)
    if dropped:
        print(f"[loader] coupons: 丢弃 {dropped} 行（时间/面额无效）")
    return df.reset_index(drop=True)
