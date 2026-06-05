"""在线推理 API（plan.md 5.10）。

加载离线训练好的模型（model.joblib），对外提供：
  GET  /health     健康检查
  GET  /info       模型信息
  POST /score      传用户特征 → 返回各面额 uplift + 最优面额
  POST /allocate   传用户特征 → 返回惊喜券奖池权重 + 抽中面额

启动： uvicorn coupon_engine.api.main:app --reload
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ..allocation.surprise import draw, surprise_weights
from ..config import DEFAULT_CONFIG, Config
from ..models.base import UpliftModel

app = FastAPI(title="智能发券引擎 API", version="0.1.0")

_MODEL: Optional[UpliftModel] = None
_CONFIG: Config = DEFAULT_CONFIG


def _model_path() -> Path:
    env = os.getenv("MODEL_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "model.joblib"


def get_model() -> UpliftModel:
    global _MODEL
    if _MODEL is None:
        import joblib

        path = _model_path()
        if not path.exists():
            raise HTTPException(
                status_code=503,
                detail=f"模型未就绪：{path} 不存在。请先运行 scripts/run_pipeline.py 训练。",
            )
        _MODEL = joblib.load(path)
    return _MODEL


class ScoreRequest(BaseModel):
    users: List[Dict[str, float]] = Field(..., description="每个用户的特征字典列表")
    values: Optional[List[float]] = Field(None, description="候选券面额，缺省用配置")


def _features_frame(users: List[Dict[str, float]], model: UpliftModel) -> pd.DataFrame:
    """把特征字典列表对齐成模型需要的列（缺失补 0）。"""
    df = pd.DataFrame(users)
    for col in model.feature_cols:
        if col not in df.columns:
            df[col] = 0.0
    return df[model.feature_cols].fillna(0.0)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model_loaded": _model_path().exists()}


@app.get("/info")
def info() -> dict:
    model = get_model()
    return {
        "model": getattr(model, "name", "unknown"),
        "n_features": len(model.feature_cols),
        "feature_cols": model.feature_cols,
        "coupon_values": _CONFIG.coupon_values,
    }


@app.post("/score")
def score(req: ScoreRequest) -> dict:
    model = get_model()
    values = req.values or _CONFIG.coupon_values
    X = _features_frame(req.users, model)
    uplift = model.predict_uplift_by_value(X, values)
    best = model.predict_best_value(X, values)
    return {
        "uplift_by_value": uplift.reset_index(drop=True).to_dict(orient="records"),
        "best": best.reset_index(drop=True).to_dict(orient="records"),
    }


@app.post("/allocate")
def allocate(req: ScoreRequest) -> dict:
    model = get_model()
    values = req.values or _CONFIG.coupon_values
    X = _features_frame(req.users, model)
    uplift = model.predict_uplift_by_value(X, values)
    weights = surprise_weights(uplift, _CONFIG)
    drawn = draw(weights, seed=_CONFIG.random_seed)
    return {
        "surprise_weights": weights.reset_index(drop=True).to_dict(orient="records"),
        "drawn_value": drawn.reset_index(drop=True).tolist(),
    }
