"""核对：期间费用是否被重复加总"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

ex = pd.read_csv(ROOT / "data/raw/expenses.csv", encoding="utf-8-sig")
ex["opex"] = ex[["rent", "labor", "marketing", "other"]].sum(axis=1)
real = ex[ex["month"] == "2025-10"]["opex"].sum()

fp = json.loads((ROOT / "outputs/factpack_2025-10.json").read_text(encoding="utf-8"))
opex = next(k for k in fp["kpis"] if k["key"] == "opex")

print(f"单月真实期间费用 : {real:,.2f} 元")
print(f"系统算出的期间费用: {opex['value']:,.2f} 元")
print(f"倍数             : {opex['value'] / real:.2f}")
print(f"品类数           : {ex[ex['month'] == '2025-10'].shape[0]} 门店-月  ×  8 品类 = 8 倍")
