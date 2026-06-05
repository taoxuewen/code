FROM python:3.11-slim

WORKDIR /app

# 先装依赖，利用缓存
COPY requirements.txt pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e .

COPY . .

# 构建时生成样例数据并训练一个模型，保证容器内开箱即用
RUN python scripts/gen_sample_data.py 3000 && python scripts/run_pipeline.py >/dev/null 2>&1 || true

EXPOSE 8000 8501

# 默认起 API；docker-compose 里覆盖 command 起面板
CMD ["uvicorn", "coupon_engine.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
