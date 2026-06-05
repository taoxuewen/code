"""全局配置。

所有可调参数集中在这里（dataclass + 默认值），可被环境变量 / API 覆盖。
详见 plan.md 5.1 节。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from typing import Dict, List


def _env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    # ---- 优惠券面额档位（元）----
    coupon_values: List[float] = field(default_factory=lambda: [5.0, 10.0, 20.0, 50.0])

    # ---- 预算与人群 ----
    total_budget: float = 60000.0           # 本轮发券总预算（元）
    expected_redemption_rate: float = 0.5   # 预期核销率（用于成本估算）

    # ---- A/B 分组比例（方案 10.2）----
    group_ratios: Dict[str, float] = field(
        default_factory=lambda: {"A": 0.30, "B": 0.20, "C": 0.15, "D": 0.35}
    )

    # ---- 惊喜券（方案 3.4）----
    # 每个面额保留的最低中奖权重，保证「人人有机会抽到大额」，规避杀熟感。
    surprise_floor_weight: float = 0.05
    # 把 uplift 转权重时的温度（越大越接近均匀，越小越集中到高 uplift 面额）
    surprise_temperature: float = 1.0

    # ---- 时间窗口（天）----
    feature_windows: List[int] = field(default_factory=lambda: [30, 60, 90])
    observation_days: int = 30   # 观察期：是否发券 / 行为统计
    conversion_days: int = 14    # 转化期：发券后是否购买

    # ---- 规则发券对照组（C 组）----
    rule_inactive_days: int = 30   # 「近 N 天未消费」阈值
    rule_coupon_value: float = 10.0

    # ---- 模型 ----
    model_name: str = "two_model"
    random_seed: int = 42

    # ---- LLM ----
    llm_enabled: bool = field(default_factory=lambda: _env_bool("LLM_ENABLED", False))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "claude-opus-4-8"))
    llm_base_url: str = field(default_factory=lambda: os.getenv("ANTHROPIC_BASE_URL", ""))

    def cost_per_award(self, value: float) -> float:
        """一次「发出某面额券」的期望成本 = 面额 × 预期核销率。"""
        return value * self.expected_redemption_rate

    @classmethod
    def from_overrides(cls, **overrides) -> "Config":
        """用关键字覆盖默认值，未知键忽略。"""
        valid = {f.name for f in fields(cls)}
        clean = {k: v for k, v in overrides.items() if k in valid and v is not None}
        return cls(**clean)


# 模块级默认配置，便于直接 import 使用
DEFAULT_CONFIG = Config()
