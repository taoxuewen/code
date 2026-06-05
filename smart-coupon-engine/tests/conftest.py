"""pytest 公共 fixtures：一份小规模合成数据 + 训练好的模型。"""
from __future__ import annotations

import pandas as pd
import pytest

from coupon_engine.config import Config
from coupon_engine.data.synth import generate
from coupon_engine.features.rfm import make_training_frame
from coupon_engine.models.registry import get_model


@pytest.fixture(scope="session")
def config() -> Config:
    return Config(total_budget=30000.0)


@pytest.fixture(scope="session")
def synth(config):
    return generate(n_users=2000, coupon_values=config.coupon_values,
                    conversion_days=config.conversion_days, seed=config.random_seed)


@pytest.fixture(scope="session")
def training(synth, config):
    return make_training_frame(synth.orders, synth.coupons, config)


@pytest.fixture(scope="session")
def model(training, config):
    m = get_model(config.model_name, random_seed=config.random_seed)
    m.fit(training.X, training.treatment, training.outcome, training.treat_value)
    return m
