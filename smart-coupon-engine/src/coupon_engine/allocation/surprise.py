"""惊喜券：把 uplift 分数转成抽奖奖池权重（plan.md 5.5 / 方案 3.4 核心设计）。

核心产品护栏：个性化在后台（uplift 决定权重），用户在前端感知的是「运气」。
- uplift 越高的面额 → 抽中权重越高
- 但每个面额都保留最低权重 surprise_floor_weight → 人人有机会抽到大额，
  规避「大数据杀熟」的公关风险（这是产品级护栏，不是可选项）。

对外：
  - surprise_weights(uplift_by_value, config) -> 每用户每面额的中奖概率（每行和=1）
  - draw(weights, seed) -> 每用户抽样一次的中奖面额（模拟「拆红包」）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Config, DEFAULT_CONFIG


def surprise_weights(
    uplift_by_value: pd.DataFrame, config: Config = DEFAULT_CONFIG
) -> pd.DataFrame:
    """uplift → 奖池权重（softmax + 保底）。返回每行和为 1 的概率分布。"""
    values = list(uplift_by_value.columns)
    k = len(values)
    floor = config.surprise_floor_weight
    if k * floor >= 1.0:
        raise ValueError(
            f"surprise_floor_weight={floor} × 面额数={k} 必须 < 1（否则无法满足保底）"
        )

    u = uplift_by_value.to_numpy(dtype=float)
    u = np.clip(u, 0.0, None)  # 负 uplift 不增加权重，但仍享保底
    # 数值稳定 softmax
    z = u / max(config.surprise_temperature, 1e-6)
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    soft = e / e.sum(axis=1, keepdims=True)
    # 保底混合：每个面额至少 floor，其余按 softmax 分配
    w = floor + (1.0 - k * floor) * soft
    return pd.DataFrame(w, index=uplift_by_value.index, columns=values)


def draw(weights: pd.DataFrame, seed: int = 42) -> pd.Series:
    """按权重为每个用户抽一次券面额（模拟拆红包）。"""
    rng = np.random.default_rng(seed)
    values = np.array([float(v) for v in weights.columns])
    w = weights.to_numpy(dtype=float)
    w = w / w.sum(axis=1, keepdims=True)
    drawn = [rng.choice(values, p=w[i]) for i in range(len(weights))]
    return pd.Series(drawn, index=weights.index, name="drawn_value")
