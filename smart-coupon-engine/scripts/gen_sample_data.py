"""生成样例 CSV 到 data/sample/，供 demo 与测试使用。

用法： python scripts/gen_sample_data.py [n_users]
"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许直接 python scripts/xxx.py 运行（无需先 pip install -e .）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from coupon_engine.config import DEFAULT_CONFIG
from coupon_engine.data.synth import generate
from coupon_engine.data.synth_tables import generate_tables


def main() -> None:
    n_users = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    out_dir = Path(__file__).resolve().parents[1] / "data" / "sample"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- 内部 2 表（orders/coupons）：供 CLI / 旧流程 / 测试 ----
    data = generate(
        n_users=n_users,
        coupon_values=DEFAULT_CONFIG.coupon_values,
        conversion_days=DEFAULT_CONFIG.conversion_days,
        seed=DEFAULT_CONFIG.random_seed,
    )
    data.orders.to_csv(out_dir / "orders.csv", index=False)
    data.coupons.to_csv(out_dir / "coupons.csv", index=False)
    data.truth.to_csv(out_dir / "_truth_segments.csv", index=False)

    # ---- 对外 3 表（客户/商品/行为日志，D3）：供网站上传演示 ----
    tables = generate_tables(
        n_users=n_users,
        coupon_values=DEFAULT_CONFIG.coupon_values,
        conversion_days=DEFAULT_CONFIG.conversion_days,
        seed=DEFAULT_CONFIG.random_seed,
    )
    tables.customers.to_csv(out_dir / "customers.csv", index=False)
    tables.products.to_csv(out_dir / "products.csv", index=False)
    tables.behavior.to_csv(out_dir / "behavior.csv", index=False)

    print(f"已生成样例数据到 {out_dir}")
    print("  [内部2表]")
    print(f"    orders.csv   : {len(data.orders):>7} 行")
    print(f"    coupons.csv  : {len(data.coupons):>7} 行")
    print("  [对外3表 / 网站上传]")
    print(f"    customers.csv: {len(tables.customers):>7} 行")
    print(f"    products.csv : {len(tables.products):>7} 行")
    print(f"    behavior.csv : {len(tables.behavior):>7} 行")
    print(f"  用户数     : {n_users}")
    print(f"  切点 T0    : {data.cutoff.date()}")


if __name__ == "__main__":
    main()
