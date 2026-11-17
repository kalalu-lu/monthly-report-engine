"""
生成『月报引擎』演示数据（纯标准库，不依赖 pandas）

输出到 data/raw/：
  dim_store.csv     门店维度（面积、人数、开业时间）
  dim_category.csv  品类维度（基准价、成本率、季节性类型）
  sales.csv         经营明细：月 × 门店 × 品类
  budget.csv        预算（同粒度）
  expenses.csv      门店月度期间费用

故事设定（供后续异常检测验证）：
  1. 茶饮/冰淇淋强季节性（夏高冬低）
  2. S05 亦庄新店 2025-03 开业（此前无数据）
  3. 2025-06 外卖促销：茶饮/咖啡 降价 12%、销量 +35%
  4. S02 五道口店 2025-08/09/10 连续三月销量下滑（0.90 → 0.80 → 0.72）
  5. 烘焙品类 2025-09 起单位成本上涨 18%（原料涨价）
  6. 末尾注入 7 条脏数据，用于验证数据校验环节

运行：python tools/gen_data.py
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

SEED = 20261116
rng = random.Random(SEED)

MONTHS = [f"{y}-{m:02d}" for y in (2024, 2025) for m in range(1, 13)]

# store_id, 门店名, 城市, 面积㎡, 开业月, 员工数
STORES = [
    ("S01", "中关村店", "北京", 180, "2019-05", 12),
    ("S02", "五道口店", "北京", 120, "2020-09", 9),
    ("S03", "望京店", "北京", 150, "2021-06", 10),
    ("S04", "三里屯店", "北京", 90, "2022-04", 8),
    ("S05", "亦庄新店", "北京", 110, "2025-03", 7),
    ("S06", "回龙观店", "北京", 140, "2023-08", 9),
]

# 品类, 日均基准量, 基准单价, 成本率, 季节性类型
CATEGORIES = [
    ("现制茶饮", 120, 18.0, 0.32, "summer"),
    ("咖啡", 60, 22.0, 0.28, "flat"),
    ("烘焙", 45, 15.0, 0.40, "flat"),
    ("轻食", 40, 28.0, 0.45, "flat"),
    ("周边零售", 12, 35.0, 0.50, "q4"),
    ("冰淇淋", 30, 12.0, 0.30, "summer_strong"),
    ("果切", 35, 16.0, 0.48, "summer"),
    ("套餐", 25, 32.0, 0.55, "flat"),
]

SEASON = {
    "summer": [0.70, 0.72, 0.85, 1.00, 1.15, 1.30, 1.45, 1.40, 1.15, 0.95, 0.80, 0.72],
    "summer_strong": [0.35, 0.40, 0.60, 0.90, 1.30, 1.70, 1.90, 1.80, 1.30, 0.70, 0.45, 0.35],
    "flat": [1.00, 0.98, 1.02, 1.00, 0.99, 1.01, 1.00, 1.02, 1.00, 1.03, 1.02, 1.05],
    "q4": [0.80, 0.85, 0.90, 0.95, 0.95, 1.00, 0.95, 1.00, 1.05, 1.00, 1.10, 1.35],
}

STORE_PRICE_FACTOR = {"S01": 1.00, "S02": 0.98, "S03": 1.00, "S04": 1.08, "S05": 0.95, "S06": 0.97}


def noise(lo: float = 0.92, hi: float = 1.08) -> float:
    return rng.uniform(lo, hi)


def month_index(ym: str) -> int:
    y, m = int(ym[:4]), int(ym[5:7])
    return (y - 2024) * 12 + (m - 1)


def qty_story(store_id: str, ym: str, cat: str) -> float:
    if store_id == "S02" and ym in ("2025-08", "2025-09", "2025-10"):
        return {"2025-08": 0.90, "2025-09": 0.80, "2025-10": 0.72}[ym]
    if ym == "2025-06" and cat in ("现制茶饮", "咖啡"):
        return 1.35
    return 1.0


def price_story(ym: str, cat: str) -> float:
    if ym == "2025-06" and cat in ("现制茶饮", "咖啡"):
        return 0.88
    return 1.0


def cost_story(ym: str, cat: str) -> float:
    # 现制茶饮（主力品类）2025-10 起原料涨价 18%
    if cat == "现制茶饮" and ym >= "2025-10":
        return 1.18
    return 1.0


def store_scale(area: int, staff: int) -> float:
    return (area / 150.0) ** 0.6 * (staff / 9.0) ** 0.4


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  {path.name:18s} {len(rows):5d} 行")


def main() -> None:
    # ---------- 维度表 ----------
    write_csv(RAW / "dim_store.csv", ["store_id", "store_name", "city", "area_sqm", "open_month", "staff_count"],
              [list(s) for s in STORES])
    write_csv(RAW / "dim_category.csv", ["category", "base_daily_qty", "base_price", "cost_ratio", "season_type"],
              [list(c) for c in CATEGORIES])

    # ---------- 明细 + 预算 ----------
    sales: list[list] = []
    budget: list[list] = []
    for ym in MONTHS:
        mi = month_index(ym)
        m_no = int(ym[5:7]) - 1
        for store_id, _name, _city, area, open_month, staff in STORES:
            if ym < open_month:
                continue
            scale = store_scale(area, staff)
            for cat, base_qty, base_price, cost_ratio, season_type in CATEGORIES:
                sf = SEASON[season_type][m_no]
                qty = base_qty * 30 * scale * sf * noise()
                qty = qty * qty_story(store_id, ym, cat)
                qty = max(1, int(round(qty)))

                drift = 1 + 0.015 * (mi / 12)
                price = base_price * STORE_PRICE_FACTOR[store_id] * drift * price_story(ym, cat) * noise(0.98, 1.02)
                price = round(price, 2)
                cost = base_price * cost_ratio * drift * cost_story(ym, cat) * noise(0.97, 1.03)
                cost = round(cost, 2)

                revenue = round(qty * price, 2)
                orders = max(1, int(round(qty / 1.8)))
                member = int(round(orders * rng.uniform(0.40, 0.52)))
                newc = int(round(orders * rng.uniform(0.18, 0.26)))
                cash_in = round(revenue * rng.uniform(0.93, 1.01), 2)

                sales.append([ym, store_id, cat, qty, price, cost, orders, member, newc, cash_in, revenue])

                # 预算：多数店定 1.03~1.12 倍，S02 在出问题的三个月定得更高（1.15），制造预算缺口
                if store_id == "S02" and ym in ("2025-08", "2025-09", "2025-10"):
                    bf = 1.15
                else:
                    bf = rng.uniform(1.03, 1.12)
                budget.append([ym, store_id, cat,
                               max(1, int(round(qty * bf))),
                               round(price * rng.uniform(0.99, 1.02), 2),
                               round(cost * rng.uniform(0.98, 1.01), 2)])

    # ---------- 期间费用 ----------
    expenses: list[list] = []
    rev_by_store_month: dict[tuple[str, str], float] = {}
    for r in sales:
        key = (r[0], r[1])
        rev_by_store_month[key] = rev_by_store_month.get(key, 0.0) + r[10]
    for (ym, store_id), rev in sorted(rev_by_store_month.items()):
        area = next(s[3] for s in STORES if s[0] == store_id)
        staff = next(s[5] for s in STORES if s[0] == store_id)
        rent = round(area * rng.uniform(110, 135), 2)
        labor = round(staff * rng.uniform(7200, 7800), 2)
        marketing = round(rev * rng.uniform(0.020, 0.045) + (8000 if ym == "2025-06" else 0), 2)
        other = round(rev * rng.uniform(0.025, 0.035), 2)
        expenses.append([ym, store_id, rent, labor, marketing, other])

    # ---------- 注入脏数据（验证数据校验环节） ----------
    dirty: list[list] = []
    picks = rng.sample(range(len(sales)), 2)
    for i in picks:                                   # 单价被误当成分（×100）
        row = list(sales[i])
        row[4] = round(row[4] * 100, 2)
        dirty.append(row)
    row = list(sales[100]); row[3] = -abs(row[3]); row[10] = round(row[3] * row[4], 2)   # 数量为负
    dirty.append(row)
    row = list(sales[200]); row[2] = ""                                                  # 品类为空
    dirty.append(row)
    dirty.append(list(sales[300]))                                                       # 完全重复
    row = list(sales[400]); row[10] = round(row[10] + 500, 2)                            # 金额被手工改过
    dirty.append(row)
    row = list(sales[500]); row[0] = "2025-13"                                           # 期间非法
    dirty.append(row)

    sales_all = sales + dirty
    write_csv(RAW / "sales.csv",
              ["month", "store_id", "category", "qty", "unit_price", "unit_cost",
               "orders", "member_orders", "new_customers", "cash_in", "revenue"], sales_all)
    write_csv(RAW / "budget.csv",
              ["month", "store_id", "category", "budget_qty", "budget_price", "budget_unit_cost"], budget)
    write_csv(RAW / "expenses.csv",
              ["month", "store_id", "rent", "labor", "marketing", "other"], expenses)

    print(f"\n完成：干净明细 {len(sales)} 行，注入脏数据 {len(dirty)} 行，预算 {len(budget)} 行，费用 {len(expenses)} 行")


if __name__ == "__main__":
    main()
