"""Two-Model（双模型）Uplift（plan.md 5.4）。

思路（方案 3.5 选型表 Baseline）：
  - 对照模型 control_model：用对照组样本训练 P(buy | X)（不发券）
  - 处理模型 treat_model  ：用处理组样本训练 P(buy | X, coupon_value)（发券，券面额作为特征）
  - uplift(X, v) = treat_model.predict(X, v) - control_model.predict(X)

把券面额作为处理模型的输入特征，从而支持「每个面额各算一次 uplift」。
简单、稳、无重依赖；后续可在 registry 注册 DragonNet 升级。
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier

from .base import UpliftModel

VALUE_COL = "_coupon_value"


class _ConstClassifier:
    """退化分类器：训练样本只有单一类别时使用，恒定返回该概率。"""

    def __init__(self, prob: float):
        self.prob = float(prob)

    def predict_proba(self, X):
        n = len(X)
        return np.column_stack([np.full(n, 1 - self.prob), np.full(n, self.prob)])


def _fit_classifier(X: pd.DataFrame, y: pd.Series, seed: int):
    if y.nunique() < 2:
        return _ConstClassifier(prob=float(y.mean()) if len(y) else 0.0)
    clf = GradientBoostingClassifier(random_state=seed)
    clf.fit(X.values, y.values)
    return clf


def _proba1(clf, X: pd.DataFrame) -> np.ndarray:
    return clf.predict_proba(X.values)[:, 1]


class TwoModelUplift(UpliftModel):
    name = "two_model"

    def __init__(self, random_seed: int = 42):
        self.random_seed = random_seed
        self.control_model = None
        self.treat_model = None
        self.feature_cols: List[str] = []

    def fit(
        self,
        X: pd.DataFrame,
        treatment: pd.Series,
        outcome: pd.Series,
        treat_value: Optional[pd.Series] = None,
    ) -> "TwoModelUplift":
        self.feature_cols = list(X.columns)
        treatment = treatment.reindex(X.index)
        outcome = outcome.reindex(X.index)

        is_treat = treatment == 1
        is_control = treatment == 0

        # 对照模型：仅特征
        self.control_model = _fit_classifier(
            X[is_control], outcome[is_control], self.random_seed
        )

        # 处理模型：特征 + 券面额
        Xt = X[is_treat].copy()
        if treat_value is not None:
            Xt[VALUE_COL] = treat_value.reindex(X.index)[is_treat].values
        else:
            Xt[VALUE_COL] = 0.0
        self.treat_model = _fit_classifier(Xt, outcome[is_treat], self.random_seed)
        return self

    def predict_uplift_by_value(
        self, X: pd.DataFrame, values: List[float]
    ) -> pd.DataFrame:
        if self.control_model is None or self.treat_model is None:
            raise RuntimeError("模型尚未 fit")
        X = X[self.feature_cols]
        p_control = _proba1(self.control_model, X)
        cols = {}
        for v in values:
            Xv = X.copy()
            Xv[VALUE_COL] = float(v)
            p_treat = _proba1(self.treat_model, Xv)
            cols[float(v)] = p_treat - p_control
        return pd.DataFrame(cols, index=X.index)
