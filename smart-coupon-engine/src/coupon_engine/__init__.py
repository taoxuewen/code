"""智能发券引擎（极简版 MVP）。

核心闭环：CSV → RFM 特征 → Uplift 模型 → 预算约束分配 + 惊喜券
        → A/B 模拟与显著性检验 → LLM 文案 → 周报。

详见 plan.md。
"""

__version__ = "0.1.0"
