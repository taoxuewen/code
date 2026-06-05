"""模型注册表 / 工厂（plan.md 5.4）。

初版注册 two_model；后续接 DragonNet（方案实测最优 +35%）只需在此登记，
不改动调用方。
"""
from __future__ import annotations

from typing import Callable, Dict

from .base import UpliftModel
from .two_model import TwoModelUplift

_REGISTRY: Dict[str, Callable[..., UpliftModel]] = {
    "two_model": TwoModelUplift,
    # "dragonnet": DragonNetUplift,   # TODO 阶段二：需 torch
}


def get_model(name: str = "two_model", **kwargs) -> UpliftModel:
    if name not in _REGISTRY:
        raise KeyError(f"未知模型 '{name}'，可选: {list(_REGISTRY)}")
    return _REGISTRY[name](**kwargs)


def available_models() -> list[str]:
    return list(_REGISTRY)
