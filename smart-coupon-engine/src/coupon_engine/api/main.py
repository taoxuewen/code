"""在线推理 API（plan.md 5.10）。

加载离线训练好的模型（model.joblib），对外提供：
  GET  /health     健康检查
  GET  /info       模型信息
  POST /score      传用户特征 → 返回各面额 uplift + 最优面额
  POST /allocate   传用户特征 → 返回惊喜券奖池权重 + 抽中面额

启动： uvicorn coupon_engine.api.main:app --reload
"""
from __future__ import annotations

import base64
import io
import os
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..allocation.surprise import draw, surprise_weights
from ..config import DEFAULT_CONFIG, Config
from ..models.base import UpliftModel

app = FastAPI(title="智能发券引擎 API", version="0.1.0")

WEB_DIR = Path(__file__).resolve().parents[3] / "web"

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


# ============================================================================
# 对客 Web（plan.md 5.10 / 5.12，需求 D2）
#   上传数据 → 内存现训现算 → 回传每客户推荐券面额（CSV + Excel）
#   全程不落盘、不持久化，第一版无需任何云存储。
# ============================================================================
PREVIEW_ROWS = 50


def _result_payload(result, config: Config) -> dict:
    """把推荐结果打包成前端要的 JSON：汇总 + 预览 + 完整 CSV/xlsx。"""
    table = result.table
    csv_text = table.to_csv(index=False)
    buf = io.BytesIO()
    table.to_excel(buf, index=False)  # 需要 openpyxl
    xlsx_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return {
        "ok": True,
        "summary": result.summary,
        "evaluation": result.evaluation,
        "coupon_values": config.coupon_values,
        "columns": list(table.columns),
        "preview": table.head(PREVIEW_ROWS).to_dict(orient="records"),
        "n_rows": int(len(table)),
        "result_csv": csv_text,
        "result_xlsx_b64": xlsx_b64,
    }


def _read_csv_upload(file: UploadFile, label: str) -> pd.DataFrame:
    try:
        raw = file.file.read()
        return pd.read_csv(io.BytesIO(raw))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"{label} 读取失败：{exc}")


@app.post("/api/recommend")
def recommend(
    customers: UploadFile = File(..., description="客户基础属性 CSV"),
    products: UploadFile = File(..., description="商品基础属性 CSV"),
    behavior: UploadFile = File(..., description="行为日志 CSV（含领券/用券）"),
    budget: Optional[float] = Form(None, description="本轮发券总预算（元），缺省用默认"),
) -> dict:
    """对客主路径（D3 三表输入）：上传 客户/商品/行为日志 → 返回每客户推荐券面额。"""
    from ..data.loader import DataValidationError
    from ..pipeline import recommend_from_tables

    customers_df = _read_csv_upload(customers, "客户属性")
    products_df = _read_csv_upload(products, "商品属性")
    behavior_df = _read_csv_upload(behavior, "行为日志")
    config = Config.from_overrides(total_budget=budget) if budget else DEFAULT_CONFIG
    try:
        result = recommend_from_tables(customers_df, products_df, behavior_df, config)
    except DataValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"计算失败：{exc}")
    return _result_payload(result, config)


@app.get("/api/demo")
def demo(n_users: int = 4000, budget: Optional[float] = None) -> dict:
    """给没有数据的访客：即时合成 3 表跑通，体验完整结果。

    默认 4000 用户：小样本下 uplift 评估方差大、易翻负，4000 起评估更稳定可信。
    """
    from ..data.synth_tables import generate_tables
    from ..pipeline import recommend_from_tables

    config = Config.from_overrides(total_budget=budget) if budget else DEFAULT_CONFIG
    t = generate_tables(n_users=max(100, min(n_users, 8000)),
                        coupon_values=config.coupon_values)
    result = recommend_from_tables(t.customers, t.products, t.behavior, config)
    payload = _result_payload(result, config)
    payload["demo"] = True
    return payload


# 静态前端：挂在最后，"/" 直接出对客页面（web/ 不存在时跳过，不影响 API）。
if WEB_DIR.exists():
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(WEB_DIR / "index.html"))

    app.mount("/", StaticFiles(directory=str(WEB_DIR)), name="web")
