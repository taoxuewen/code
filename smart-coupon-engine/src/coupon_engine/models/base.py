"""Uplift 模型抽象基类（plan.md 5.4）。

统一接口，便于后续插拔更强的模型（DragonNet/EFIN，见 plan.md 第 8 节）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

import numpy as np
import pandas as pd


class UpliftModel(ABC):
    """所有 uplift 模型的统一接口。

    约定：把「发多少券」建模为对每个候选面额各算一次 uplift（plan.md 9.4）。
    """

    name: str = "base"

    @abstractmethod
    def fit(
        self,
        X: pd.DataFrame,
        treatment: pd.Series,
        outcome: pd.Series,
        treat_value: Optional[pd.Series] = None,
    ) -> "UpliftModel":
        ...

    @abstractmethod
    def predict_uplift_by_value(
        self, X: pd.DataFrame, values: List[float]
    ) -> pd.DataFrame:
        """返回 DataFrame：index=X.index，每个候选面额一列，值为该面额的 uplift。"""
        ...

    def predict_best_value(
        self, X: pd.DataFrame, values: List[float]
    ) -> pd.DataFrame:
        """便捷方法：每个用户 uplift 最高的面额及其 uplift。"""
        up = self.predict_uplift_by_value(X, values)
        best = up.idxmax(axis=1)
        return pd.DataFrame(
            {"best_value": best.astype(float), "best_uplift": up.max(axis=1)},
            index=X.index,
        )
