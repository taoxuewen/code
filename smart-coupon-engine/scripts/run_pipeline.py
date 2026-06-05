"""CLI：端到端跑全流程，打印周报并保存模型。

用法：
  python scripts/run_pipeline.py                  # 用 data/sample
  python scripts/run_pipeline.py orders.csv coupons.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from coupon_engine.config import DEFAULT_CONFIG
from coupon_engine.data.loader import load_coupons, load_orders
from coupon_engine.pipeline import run_from_sample, run_pipeline, save_model


def main() -> None:
    cfg = DEFAULT_CONFIG
    if len(sys.argv) >= 3:
        orders = load_orders(sys.argv[1])
        coupons = load_coupons(sys.argv[2])
        result = run_pipeline(orders, coupons, cfg, truth_segments=None)
    else:
        sample = Path(__file__).resolve().parents[1] / "data" / "sample" / "orders.csv"
        if not sample.exists():
            print("未找到样例数据，请先运行: python scripts/gen_sample_data.py")
            sys.exit(1)
        result = run_from_sample(cfg)

    print(result.report)

    out = Path(__file__).resolve().parents[1] / "model.joblib"
    save_model(result.model, str(out))
    print(f"\n[已保存模型] {out}")


if __name__ == "__main__":
    main()
