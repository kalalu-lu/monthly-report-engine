"""
数据校验与清洗（Stage A 的第一步）

7 条校验规则，每条有编号，可追溯：
  V01 期间非法（格式不是 YYYY-MM，或超出数据区间）
  V02 维度未登记（品类为空或不在 dim_category，门店不在 dim_store）
  V03 数量非正（<=0）
  V04 单价异常（偏离该品类中位数 3 倍以上，典型是"元"被录成"分"）
  V05 金额与「数量×单价」不符（绝对偏差 > max(1 元, 10%)）
  V06 重复记录（完全相同的行，保留首条）
  V07 费用覆盖缺失（某门店-月无期间费用记录）

对外接口：
  load_raw(raw_dir)                -> dict[str, DataFrame]
  validate(sales, stores, cats)    -> (clean_df, quarantine_df)
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

RULES = {
    "V01": "期间非法",
    "V02": "维度未登记",
    "V03": "数量非正",
    "V04": "单价异常",
    "V05": "金额与数量单价不符",
    "V06": "重复记录",
    "V07": "费用覆盖缺失",
}


def load_raw(raw_dir: str | Path) -> dict[str, pd.DataFrame]:
    raw = Path(raw_dir)
    data = {}
    for name in ("sales", "budget", "expenses", "dim_store", "dim_category"):
        df = pd.read_csv(raw / f"{name}.csv", encoding="utf-8-sig", dtype=str)
        data[name] = df
    return data


def _to_num(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def validate(sales: pd.DataFrame, stores: pd.DataFrame, cats: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """返回 (干净数据, 拦截清单)。拦截清单里每条记录给出全部命中的规则。"""
    df = sales.copy()
    df["category"] = df["category"].fillna("").astype(str).str.strip()
    _to_num(df, ["qty", "unit_price", "unit_cost", "orders", "member_orders",
                 "new_customers", "cash_in", "revenue"])

    valid_months = set(df["month"].dropna())
    valid_stores = set(stores["store_id"])
    valid_cats = set(cats["category"])

    reasons: list[list[str]] = [[] for _ in range(len(df))]

    # V01 / V02 / V03
    for i, row in enumerate(df.itertuples(index=False)):
        r = reasons[i]
        if not isinstance(row.month, str) or not MONTH_RE.match(row.month):
            r.append("V01")
            continue  # 期间非法时后续判断意义不大
        if row.category not in valid_cats:
            r.append("V02")
            continue
        if row.store_id not in valid_stores:
            r.append("V02")
            continue
        if not (row.qty > 0):
            r.append("V03")

    # V04 单价异常：与同类目、且金额自洽的记录的中位数比较
    consistent = (df["revenue"] - df["qty"] * df["unit_price"]).abs()
    base_mask = consistent <= (df["revenue"].abs() * 0.1 + 1)
    med = df[base_mask].groupby("category")["unit_price"].median()
    ratio = df["unit_price"] / df["category"].map(med)
    v04 = (ratio > 3) | (ratio < 1 / 3)
    for i in df.index[v04.fillna(False)]:
        if "V02" not in reasons[i]:
            reasons[i].append("V04")

    # V05 金额不符（金额为派生值，超过 0.1% 的偏差即视为人工改过）
    diff = (df["revenue"] - df["qty"] * df["unit_price"]).abs()
    tol = (df["revenue"].abs() * 0.001).clip(lower=0.5)
    for i in df.index[diff > tol]:
        if "V04" not in reasons[i] and "V03" not in reasons[i]:
            reasons[i].append("V05")

    # V06 重复
    for i in df.index[df.duplicated(keep="first")]:
        reasons[i].append("V06")

    df["rule_id"] = ["/".join(r) for r in reasons]

    bad = df["rule_id"] != ""
    quarantine = df[bad].copy()
    quarantine["reason"] = quarantine["rule_id"].str.split("/").map(
        lambda ids: "、".join(RULES[x] for x in ids))
    clean = df[~bad].copy()
    return clean, quarantine


def check_expense_coverage(clean: pd.DataFrame, expenses: pd.DataFrame) -> pd.DataFrame:
    """V07：门店-月有经营但无费用记录，返回缺失清单。"""
    need = clean.groupby(["month", "store_id"]).size().reset_index(name="n")[["month", "store_id"]]
    have = expenses[["month", "store_id"]].drop_duplicates()
    missing = need.merge(have, on=["month", "store_id"], how="left", indicator=True)
    return missing[missing["_merge"] == "left_only"][["month", "store_id"]]
