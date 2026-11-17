"""
指标体系（Stage A 第二步）

26 项指标，分 6 组：规模 / 盈利 / 运营 / 结构 / 现金 / 预算。
对外接口：
  build_fact(clean, stores, expenses)   -> 明细事实表（含 revenue/cost/gross）
  monthly_series(fact, budget)          -> 月度序列（26 列指标 + 中间量）
  kpi_snapshot(series, month)           -> 该月 KPI 快照（含环比/同比/预算完成率）
  store_ranking(fact, budget, month)    -> 门店排行
  category_mix(fact, budget, month)     -> 品类结构
"""
from __future__ import annotations

import pandas as pd

# key, 名称, 单位, 类型(money/count/ratio/index), 越大越好(True/False/None), 环比口径(pct/pp/-)
KPI_CATALOG = [
    ("revenue",             "营业收入",       "元",      "money", True,  "pct"),
    ("revenue_mom",         "营收环比",       "%",       "ratio", True,  "-"),
    ("revenue_yoy",         "营收同比",       "%",       "ratio", True,  "-"),
    ("orders",              "订单量",         "单",      "count", True,  "pct"),
    ("aov",                 "客单价",         "元/单",   "money", True,  "pct"),
    ("gross",               "毛利额",         "元",      "money", True,  "pct"),
    ("gross_margin",        "毛利率",         "%",       "ratio", True,  "pp"),
    ("gross_margin_mom",    "毛利率环比变动", "pp",      "ratio", True,  "-"),
    ("opex",                "期间费用",       "元",      "money", False, "pct"),
    ("opex_ratio",          "期间费用率",     "%",       "ratio", False, "pp"),
    ("op_profit",           "经营利润",       "元",      "money", True,  "pct"),
    ("op_margin",           "经营利润率",     "%",       "ratio", True,  "pp"),
    ("member_ratio",        "会员订单占比",   "%",       "ratio", True,  "pp"),
    ("new_ratio",           "新客订单占比",   "%",       "ratio", None,  "pp"),
    ("price_per_item",      "件单价",         "元/件",   "money", True,  "pct"),
    ("sales_per_sqm",       "坪效",           "元/㎡/月", "money", True,  "pct"),
    ("sales_per_staff",     "人效",           "元/人/月", "money", True,  "pct"),
    ("cash_ratio",          "收现率",         "%",       "ratio", True,  "pp"),
    ("cat_top1_share",      "品类Top1占比",   "%",       "ratio", None,  "pp"),
    ("cat_hhi",             "品类集中度HHI",  "-",       "index", None,  "pct"),
    ("store_top1_share",    "门店Top1占比",   "%",       "ratio", None,  "pp"),
    ("store_hhi",           "门店集中度HHI",  "-",       "index", None,  "pct"),
    ("budget_revenue",      "预算收入",       "元",      "money", None,  "pct"),
    ("budget_rate",         "预算完成率",     "%",       "ratio", True,  "pp"),
    ("var_amt",             "预算差异额",     "元",      "money", True,  "-"),
    ("var_rate",            "预算差异率",     "%",       "ratio", True,  "-"),
]


def build_fact(clean: pd.DataFrame, stores: pd.DataFrame) -> pd.DataFrame:
    """明细事实表。注意：期间费用是"门店-月"粒度，不能在这里并到"品类"粒度上，
    否则按品类行求和会重复 8 倍（这个坑踩过一次，见 tools/check_opex.py）。"""
    f = clean.copy()
    f["revenue"] = f["qty"] * f["unit_price"]
    f["cost"] = f["qty"] * f["unit_cost"]
    f["gross"] = f["revenue"] - f["cost"]

    st = stores[["store_id", "store_name", "area_sqm", "staff_count"]].copy()
    st["area_sqm"] = pd.to_numeric(st["area_sqm"])
    st["staff_count"] = pd.to_numeric(st["staff_count"])
    return f.merge(st, on="store_id", how="left")


def _share_stats(fact: pd.DataFrame, key: str) -> tuple[pd.Series, pd.Series]:
    p = fact.groupby(["month", key])["revenue"].sum().reset_index()
    p["share"] = p["revenue"] / p.groupby("month")["revenue"].transform("sum")
    top1 = p.groupby("month")["share"].max()
    hhi = p.assign(sq=p["share"] ** 2).groupby("month")["sq"].sum()
    return top1, hhi


def monthly_series(fact: pd.DataFrame, budget: pd.DataFrame,
                   stores: pd.DataFrame, expenses: pd.DataFrame) -> pd.DataFrame:
    g = fact.groupby("month").agg(
        revenue=("revenue", "sum"), cost=("cost", "sum"), gross=("gross", "sum"),
        qty=("qty", "sum"), orders=("orders", "sum"),
        member_orders=("member_orders", "sum"), new_customers=("new_customers", "sum"),
        cash_in=("cash_in", "sum"),
    )

    # 期间费用：门店-月粒度，先聚到月，绝不能按品类行加总
    ex = expenses.copy()
    for c in ("rent", "labor", "marketing", "other"):
        ex[c] = pd.to_numeric(ex[c])
    ex["opex"] = ex[["rent", "labor", "marketing", "other"]].sum(axis=1)
    g["opex"] = ex.groupby("month")["opex"].sum()

    # 面积 / 人数：取当月实际有经营的门店去重求和（新店未开业不计）
    area_map = dict(zip(stores["store_id"], pd.to_numeric(stores["area_sqm"])))
    staff_map = dict(zip(stores["store_id"], pd.to_numeric(stores["staff_count"])))
    active = fact.groupby("month")["store_id"].apply(lambda s: sorted(set(s)))
    g["area"] = [float(sum(area_map[x] for x in active.loc[m])) for m in g.index]
    g["staff"] = [float(sum(staff_map[x] for x in active.loc[m])) for m in g.index]

    b = budget.copy()
    b["budget_revenue"] = pd.to_numeric(b["budget_qty"]) * pd.to_numeric(b["budget_price"])
    g["budget_revenue"] = b.groupby("month")["budget_revenue"].sum()

    ct, ch = _share_stats(fact, "category")
    st, sh = _share_stats(fact, "store_id")
    g["cat_top1_share"] = ct
    g["cat_hhi"] = ch
    g["store_top1_share"] = st
    g["store_hhi"] = sh

    s = g.sort_index()
    s["aov"] = s["revenue"] / s["orders"]
    s["price_per_item"] = s["revenue"] / s["qty"]
    s["gross_margin"] = s["gross"] / s["revenue"]
    s["opex_ratio"] = s["opex"] / s["revenue"]
    s["op_profit"] = s["gross"] - s["opex"]
    s["op_margin"] = s["op_profit"] / s["revenue"]
    s["member_ratio"] = s["member_orders"] / s["orders"]
    s["new_ratio"] = s["new_customers"] / s["orders"]
    s["sales_per_sqm"] = s["revenue"] / s["area"]
    s["sales_per_staff"] = s["revenue"] / s["staff"]
    s["cash_ratio"] = s["cash_in"] / s["revenue"]
    s["budget_rate"] = s["revenue"] / s["budget_revenue"]
    s["var_amt"] = s["revenue"] - s["budget_revenue"]
    s["var_rate"] = s["var_amt"] / s["budget_revenue"]
    s["revenue_mom"] = s["revenue"].pct_change()
    s["revenue_yoy"] = s["revenue"].pct_change(12)
    s["gross_margin_mom"] = s["gross_margin"].diff()
    return s


def _scale(key: str, unit: str, v: float) -> float:
    if v is None or pd.isna(v):
        return float("nan")
    if unit == "pp":
        return round(v * 100, 2)
    if unit == "%":
        return round(v * 100, 2)
    if unit == "-":
        return round(v, 4)
    return round(v, 2)


def kpi_snapshot(series: pd.DataFrame, month: str) -> list[dict]:
    idx = list(series.index)
    i = idx.index(month)
    out = []
    for key, name, unit, kind, better, mom_type in KPI_CATALOG:
        v = _scale(key, unit, series.loc[month, key])
        mom = yoy = None
        if i > 0:
            prev = _scale(key, unit, series.iloc[i - 1][key])
            if mom_type == "pct" and prev not in (0, float("nan")) and pd.notna(prev):
                mom = round((v / prev - 1) * 100, 2)
            elif mom_type == "pp":
                mom = round(v - prev, 2)
        if i >= 12:
            py = _scale(key, unit, series.iloc[i - 12][key])
            if mom_type == "pct" and py not in (0, float("nan")) and pd.notna(py):
                yoy = round((v / py - 1) * 100, 2)
            elif mom_type == "pp":
                yoy = round(v - py, 2)
        out.append({
            "key": key, "name": name, "unit": unit, "value": v,
            "mom": mom, "mom_unit": "%" if mom_type == "pct" else ("pp" if mom_type == "pp" else None),
            "yoy": yoy, "higher_better": better,
        })
    return out


def store_ranking(fact: pd.DataFrame, budget: pd.DataFrame, month: str) -> list[dict]:
    cur = fact[fact["month"] == month]
    keys = sorted(fact["month"].unique())
    i = keys.index(month)
    prev_month = keys[i - 1] if i > 0 else None
    prev = fact[fact["month"] == prev_month] if prev_month else cur.iloc[0:0]

    g = cur.groupby(["store_id", "store_name"]).agg(
        revenue=("revenue", "sum"), gross=("gross", "sum"), orders=("orders", "sum")).reset_index()
    pg = prev.groupby("store_id")["revenue"].sum().rename("prev_revenue")

    b = budget[budget["month"] == month].copy()
    b["budget_revenue"] = pd.to_numeric(b["budget_qty"]) * pd.to_numeric(b["budget_price"])
    bg = b.groupby("store_id")["budget_revenue"].sum()

    g = g.merge(pg, on="store_id", how="left")
    g["budget_revenue"] = g["store_id"].map(bg)
    g["mom"] = (g["revenue"] / g["prev_revenue"] - 1) * 100
    g["budget_rate"] = g["revenue"] / g["budget_revenue"] * 100
    g["gross_margin"] = g["gross"] / g["revenue"] * 100
    g = g.sort_values("revenue", ascending=False)
    rows = []
    for _, r in g.iterrows():
        rows.append({
            "store_id": r["store_id"], "store_name": r["store_name"],
            "revenue": round(r["revenue"], 2),
            "revenue_share": round(r["revenue"] / g["revenue"].sum() * 100, 2),
            "mom": None if pd.isna(r["mom"]) else round(r["mom"], 2),
            "gross_margin": round(r["gross_margin"], 2),
            "budget_rate": None if pd.isna(r["budget_rate"]) else round(r["budget_rate"], 2),
        })
    return rows


def category_mix(fact: pd.DataFrame, month: str) -> list[dict]:
    cur = fact[fact["month"] == month]
    g = cur.groupby("category").agg(revenue=("revenue", "sum"), gross=("gross", "sum")).reset_index()
    g["share"] = g["revenue"] / g["revenue"].sum() * 100
    g["gross_margin"] = g["gross"] / g["revenue"] * 100
    g = g.sort_values("revenue", ascending=False)
    return [{
        "category": r["category"],
        "revenue": round(r["revenue"], 2),
        "share": round(r["share"], 2),
        "gross_margin": round(r["gross_margin"], 2),
    } for _, r in g.iterrows()]
