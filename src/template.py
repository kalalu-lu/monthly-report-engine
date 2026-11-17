"""
数据模板生成

企业客户拿到的第一样东西应该是这个：一个填好了表头和示例行的 Excel，
按 sheet 名对应系统的五张输入表。填完直接拖进客户端就能出月报。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

SHEETS: dict[str, tuple[list[str], list[list]]] = {
    "sales": (
        ["month", "store_id", "category", "qty", "unit_price", "unit_cost",
         "orders", "member_orders", "new_customers", "cash_in", "revenue"],
        [
            ["2025-10", "S01", "现制茶饮", 4520, 18.60, 6.94, 2511, 1180, 520, 83000.0, 84072.00],
            ["2025-10", "S01", "咖啡", 2210, 23.10, 6.52, 1300, 610, 260, 48000.0, 51051.00],
            ["2025-10", "S02", "烘焙", 1180, 15.40, 6.10, 700, 300, 150, 17000.0, 18172.00],
        ],
    ),
    "budget": (
        ["month", "store_id", "category", "budget_qty", "budget_price", "budget_unit_cost"],
        [
            ["2025-10", "S01", "现制茶饮", 4950, 18.40, 6.90],
            ["2025-10", "S01", "咖啡", 2300, 23.00, 6.50],
            ["2025-10", "S02", "烘焙", 1250, 15.50, 6.05],
        ],
    ),
    "expenses": (
        ["month", "store_id", "rent", "labor", "marketing", "other"],
        [
            ["2025-10", "S01", 21600.0, 92000.0, 9300.0, 8200.0],
            ["2025-10", "S02", 14400.0, 68000.0, 6100.0, 5400.0],
        ],
    ),
    "dim_store": (
        ["store_id", "store_name", "city", "area_sqm", "open_month", "staff_count"],
        [
            ["S01", "中关村店", "北京", 180, "2019-05", 12],
            ["S02", "五道口店", "北京", 120, "2020-09", 9],
        ],
    ),
    "dim_category": (
        ["category", "base_daily_qty", "base_price", "cost_ratio", "season_type"],
        [
            ["现制茶饮", 120, 18.0, 0.32, "summer"],
            ["咖啡", 60, 22.0, 0.28, "flat"],
        ],
    ),
}

NOTES = [
    ["月报引擎 · 数据模板使用说明"],
    [""],
    ["一、五张表的对应关系"],
    ["  sales         经营明细，一行 = 一个门店在一个月卖的一个品类"],
    ["  budget        预算，粒度和 sales 一致"],
    ["  expenses      期间费用，一行 = 一个门店一个月（不要按品类拆）"],
    ["  dim_store     门店档案：面积、开业月、员工数"],
    ["  dim_category  品类档案：基准价、成本率、季节性类型"],
    [""],
    ["二、必填与取值范围"],
    ["  month         文本，格式 YYYY-MM，例如 2025-10"],
    ["  store_id      与 dim_store 里的 store_id 一致"],
    ["  category      与 dim_category 里的 category 一致"],
    ["  qty           正整数"],
    ["  unit_price    单价，单位元"],
    ["  unit_cost     单位成本，单位元，必须小于 unit_price，否则毛利率为负"],
    ["  revenue       金额，应等于 qty × unit_price（系统会用这个公式校验，偏差超 0.1% 会被拦下）"],
    ["  orders        订单数；member_orders 会员订单数；new_customers 新客数，都不得超过 orders"],
    ["  cash_in       实收现金，一般略低于 revenue（差额即未收现部分）"],
    [""],
    ["三、季节性类型 season_type 可填"],
    ["  summer        夏高冬低（茶饮、果切）"],
    ["  summer_strong 夏季极强（冰淇淋）"],
    ["  flat          全年平稳（咖啡、烘焙、轻食）"],
    ["  q4            年末走高（周边零售）"],
    [""],
    ["四、导入后系统会自动做的检查"],
    ["  V01 期间格式        V02 门店/品类未登记      V03 数量非正"],
    ["  V04 单价异常（疑似单位错误）  V05 金额与数量×单价不符"],
    ["  V06 重复记录        V07 门店-月缺费用记录"],
    ["被拦下的行不会进入计算，会单独列在 outputs/logs/quarantine.csv 里。"],
    [""],
    ["五、最少需要多少数据"],
    ["  建议至少 13 个月（要做同比就得有去年同月），门店 ≥ 2 家，品类 ≥ 3 个。"],
    ["  只有 1 个月也能出报告，但同比、趋势类指标会显示为空。"],
]


def write_template(path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(p, engine="openpyxl") as writer:
        pd.DataFrame(NOTES).to_excel(writer, sheet_name="使用说明", index=False, header=False)
        for name, (cols, rows) in SHEETS.items():
            pd.DataFrame(rows, columns=cols).to_excel(writer, sheet_name=name, index=False)

        wb = writer.book
        ws = wb["使用说明"]
        ws.column_dimensions["A"].width = 96
        for name, (cols, _rows) in SHEETS.items():
            s = wb[name]
            for i, c in enumerate(cols, start=1):
                s.column_dimensions[s.cell(row=1, column=i).column_letter].width = max(12, len(c) + 2)
            s.freeze_panes = "A2"
    return p


if __name__ == "__main__":
    out = write_template(Path(__file__).resolve().parents[1] / "02_数据模板.xlsx")
    print(f"已生成模板：{out}")
