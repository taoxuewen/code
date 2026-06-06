"""Uplift 模型评估（plan.md 5.4 / 需求 D6）。

难点：uplift 没有「真实标签」可直接比对（每个用户只能观测到「发券」或「不发券」
之一的结果）。所以用**因果评估**指标，在有观测 treatment+outcome 的测试集上衡量
「模型把券排给对的人」的能力：

  - 分位 uplift 表：按预测 uplift 降序分 N 档，看每档「处理组购买率 − 对照组购买率」
    的真实 uplift。好模型应**单调递减**（高分档真实 uplift 高）。最直观。
  - Qini 曲线 / Qini 系数 / AUUC：把上面的累计版本画成曲线并积分，得到单一分数，
    越大越好（>0 即优于随机发券）。
  - 子模型 AUC：对照模型 / 处理模型各自的判别力（辅助）。

排序分数用 `predict_best_value().best_uplift`（每用户的最大潜在 uplift），与分配逻辑一致。
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from ..config import Config, DEFAULT_CONFIG
from .base import UpliftModel
from .two_model import VALUE_COL, _proba1

MIN_EVAL_SAMPLES = 200  # 少于此样本量评估不稳，跳过


def qini_curve(score, treatment, outcome):
    """返回 (x, qini)：x=按预测分降序的累计人群比例，qini=累计增量响应曲线。"""
    d = pd.DataFrame({
        "s": np.asarray(score, dtype=float),
        "t": np.asarray(treatment, dtype=int),
        "y": np.asarray(outcome, dtype=int),
    }).sort_values("s", ascending=False, kind="mergesort").reset_index(drop=True)
    n = len(d)
    is_t = (d["t"] == 1).to_numpy()
    is_c = (d["t"] == 0).to_numpy()
    cum_nt = np.cumsum(is_t)
    cum_nc = np.cumsum(is_c)
    cum_yt = np.cumsum(d["y"].to_numpy() * is_t)
    cum_yc = np.cumsum(d["y"].to_numpy() * is_c)
    ratio = np.divide(cum_nt, cum_nc, out=np.zeros(n, dtype=float), where=cum_nc > 0)
    qini = cum_yt - cum_yc * ratio
    x = np.concatenate([[0.0], np.arange(1, n + 1) / n])
    qini = np.concatenate([[0.0], qini])
    return x, qini


def _trapz(y, x) -> float:
    """梯形积分（手写，兼容 numpy 1.x/2.x，避免 np.trapz 被移除的问题）。"""
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    return float(np.sum((x[1:] - x[:-1]) * (y[1:] + y[:-1]) / 2.0))


def qini_auuc(score, treatment, outcome):
    """返回 (qini系数, AUUC)；均按人数归一化，越大越好，>0 优于随机。"""
    x, q = qini_curve(score, treatment, outcome)
    n = len(score)
    qn = q / max(n, 1)            # 归一化到「人均累计增量响应」
    auuc = _trapz(qn, x)           # 曲线下面积
    random_area = qn[-1] / 2.0     # 随机发券对应的对角线下面积
    qini_coeff = auuc - random_area
    return qini_coeff, auuc


def uplift_by_quantile(score, treatment, outcome, q: int = 10) -> List[dict]:
    """按预测 uplift 降序均分 q 档，算每档真实 uplift（处理组购买率−对照组购买率）。"""
    d = pd.DataFrame({
        "s": np.asarray(score, dtype=float),
        "t": np.asarray(treatment, dtype=int),
        "y": np.asarray(outcome, dtype=int),
    }).sort_values("s", ascending=False, kind="mergesort").reset_index(drop=True)
    rows = []
    for i, g in enumerate(np.array_split(np.arange(len(d)), q)):
        chunk = d.iloc[g]
        t = chunk[chunk["t"] == 1]
        c = chunk[chunk["t"] == 0]
        resp_t = float(t["y"].mean()) if len(t) else None
        resp_c = float(c["y"].mean()) if len(c) else None
        uplift = (resp_t - resp_c) if (resp_t is not None and resp_c is not None) else None
        rows.append({
            "分位": f"第{i+1}档",
            "人数": int(len(chunk)),
            "预测uplift": round(float(chunk["s"].mean()), 4),
            "实际uplift": round(uplift, 4) if uplift is not None else None,
        })
    return rows


def _submodel_aucs(model: UpliftModel, X, treatment, outcome, treat_value) -> dict:
    """对照/处理子模型在测试集上的 AUC（判别力辅助指标）。"""
    out = {"对照模型AUC": None, "处理模型AUC": None}
    try:
        from sklearn.metrics import roc_auc_score
    except Exception:
        return out
    feats = model.feature_cols
    t = np.asarray(treatment, dtype=int)
    y = np.asarray(outcome, dtype=int)
    Xc = X[t == 0]
    if len(Xc) and len(np.unique(y[t == 0])) == 2:
        p = _proba1(model.control_model, Xc[feats])
        out["对照模型AUC"] = round(float(roc_auc_score(y[t == 0], p)), 4)
    Xt = X[t == 1].copy()
    if len(Xt) and len(np.unique(y[t == 1])) == 2:
        Xt = Xt[feats].copy()
        tv = np.asarray(treat_value)[t == 1] if treat_value is not None else 0.0
        Xt[VALUE_COL] = tv
        p = _proba1(model.treat_model, Xt)
        out["处理模型AUC"] = round(float(roc_auc_score(y[t == 1], p)), 4)
    return out


def evaluate_uplift(
    model: UpliftModel,
    X: pd.DataFrame,
    treatment: pd.Series,
    outcome: pd.Series,
    treat_value: Optional[pd.Series] = None,
    config: Config = DEFAULT_CONFIG,
    quantiles: int = 10,
) -> dict:
    """在测试集上评估 uplift 模型，返回可直接展示的指标字典。"""
    t = np.asarray(treatment, dtype=int)
    y = np.asarray(outcome, dtype=int)
    n = len(X)
    n_t, n_c = int((t == 1).sum()), int((t == 0).sum())

    if n < MIN_EVAL_SAMPLES or n_t == 0 or n_c == 0:
        return {"可用": False,
                "说明": f"测试样本不足（共{n}，处理组{n_t}，对照组{n_c}），跳过评估。"}

    score = model.predict_best_value(X, config.coupon_values)["best_uplift"].to_numpy()
    qini_coeff, auuc = qini_auuc(score, t, y)
    deciles = uplift_by_quantile(score, t, y, q=quantiles)

    resp_t_all = float(y[t == 1].mean())
    resp_c_all = float(y[t == 0].mean())
    overall = resp_t_all - resp_c_all
    top = deciles[0]["实际uplift"]
    lift = (top / overall) if (top is not None and overall not in (0, None)) else None

    x, q = qini_curve(score, t, y)
    # Qini 曲线降采样到 ~20 点，方便前端画图
    step = max(1, len(x) // 20)
    curve = {"x": [round(float(v), 4) for v in x[::step]] + [round(float(x[-1]), 4)],
             "y": [round(float(v / n), 5) for v in q[::step]] + [round(float(q[-1] / n), 5)]}

    metrics = {
        "可用": True,
        "样本": {"测试集": n, "处理组": n_t, "对照组": n_c},
        "Qini系数": round(qini_coeff, 5),
        "AUUC": round(auuc, 5),
        "整体实际uplift": round(overall, 4),
        "Top档实际uplift": top,
        "提升倍数": round(lift, 2) if lift is not None else None,
        "分位表": deciles,
        "qini曲线": curve,
    }
    metrics.update(_submodel_aucs(model, X, t, y, treat_value))
    return metrics
