"""
异常检测（Stage A 第四步）

8 条规则，阈值外置在 data/ref/rules.json，可调可复现：
  R01 营收环比降幅超过阈值 + 同比为负   （公司级）
  R02 单店营收环比降幅超过阈值 + 同比为负（门店级）
  R03 单店连续 3 个月同比下滑
  R04 毛利率环比变动超过阈值            （±pp）
  R05 品类单位成本环比涨幅超过阈值       （原料涨价信号）
  R06 预算完成率低于阈值
  R07 收现率低于阈值
  R08 新店营收占比过高                  （结构性风险，低级别）

设计说明：v1 只用环比（MoM）判断，会把季节性回落误报成经营恶化；
v2 为 R01/R02 增加"同比同时为负"的确认条件，R03 由"环比链"改为"同比链"。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

DEFAULT_RULES = {
    "R01": {"name": "营收环比降幅", "threshold": 0.08, "level": "中", "unit": "ratio"},
    "R02": {"name": "单店营收环比降幅", "threshold": 0.10, "level": "高", "unit": "ratio"},
    "R03": {"name": "单店连续三月同比下滑", "threshold": 0.05, "level": "高", "unit": "ratio"},
    "R04": {"name": "毛利率环比变动", "threshold": 0.02, "level": "中", "unit": "pp"},
    "R05": {"name": "品类单位成本涨幅", "threshold": 0.10, "level": "高", "unit": "ratio"},
    "R06": {"name": "预算完成率下限", "threshold": 0.95, "level": "高", "unit": "ratio"},
    "R07": {"name": "收现率下限", "threshold": 0.95, "level": "中", "unit": "ratio"},
    "R08": {"name": "新店营收占比上限", "threshold": 0.15, "level": "低", "unit": "ratio"},
}


def load_rules(path: str | Path | None) -> dict:
    p = Path(path) if path else None
    if p and p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return DEFAULT_RULES


def _pct(x: float) -> float:
    if x is None or pd.isna(x):
        return None
    return round(float(x) * 100, 2)


def detect_all(fact: pd.DataFrame, series: pd.DataFrame, budget: pd.DataFrame,
               stores: pd.DataFrame, month: str, rules: dict) -> list[dict]:
    months = list(series.index)
    i = months.index(month)
    flags: list[dict] = []

    st = fact.groupby(["month", "store_id"])["revenue"].sum().unstack("store_id").sort_index()
    st_mom = st.pct_change()
    st_yoy = st.pct_change(12)

    # ---- R01 公司级环比 + 同比确认 ----
    mom = series.loc[month, "revenue_mom"]
    yoy_v = series.loc[month, "revenue_yoy"]
    if pd.notna(mom) and mom < -rules["R01"]["threshold"] and pd.notna(yoy_v) and yoy_v < -0.02:
        prev_rev = series.iloc[i - 1]["revenue"]
        flags.append({
            "id": "R01", "level": rules["R01"]["level"],
            "title": "公司营收环比下滑且同比转负",
            "evidence": {"revenue": round(float(series.loc[month, "revenue"]), 2),
                         "prev_revenue": round(float(prev_rev), 2),
                         "mom_pct": _pct(mom), "yoy_pct": _pct(yoy_v)},
            "impact_amt": round(float(series.loc[month, "revenue"] - prev_rev), 2),
            "source_field": "revenue_mom+revenue_yoy",
            "rule": f"环比 < -{_pct(rules['R01']['threshold'])}% 且同比 < -2%",
        })

    # ---- R02 单店环比 + 同比确认 ----
    if i > 0:
        for sid in st.columns:
            cur = st.loc[month, sid]
            prev = st.loc[months[i - 1], sid]
            mom_s = st_mom.loc[month, sid] if sid in st_mom.columns else float("nan")
            yoy_s = st_yoy.loc[month, sid] if sid in st_yoy.columns else float("nan")
            if (pd.notna(prev) and prev > 0 and pd.notna(mom_s)
                    and mom_s < -rules["R02"]["threshold"]
                    and pd.notna(yoy_s) and yoy_s < -0.02):
                name = stores.loc[stores["store_id"] == sid, "store_name"].iloc[0]
                flags.append({
                    "id": "R02", "level": rules["R02"]["level"],
                    "title": f"{name}营收环比大幅下滑",
                    "evidence": {"store_id": sid, "store_name": name,
                                 "revenue": round(float(cur), 2),
                                 "prev_revenue": round(float(prev), 2),
                                 "mom_pct": _pct(mom_s), "yoy_pct": _pct(yoy_s)},
                    "impact_amt": round(float(cur - prev), 2),
                    "source_field": "store_revenue_mom",
                    "rule": f"环比 < -{_pct(rules['R02']['threshold'])}% 且同比为负",
                })

    # ---- R03 连续三个月同比下滑 ----
    if i >= 2:
        last3 = months[i - 2:i + 1]
        for sid in st.columns:
            yv = [st_yoy.loc[m, sid] if sid in st_yoy.columns else float("nan") for m in last3]
            if any(pd.isna(x) for x in yv):
                continue
            if all(x < -rules["R03"]["threshold"] for x in yv):
                name = stores.loc[stores["store_id"] == sid, "store_name"].iloc[0]
                flags.append({
                    "id": "R03", "level": rules["R03"]["level"],
                    "title": f"{name}连续三个月同比下滑",
                    "evidence": {"store_id": sid, "store_name": name, "months": last3,
                                 "yoy_pct": [_pct(x) for x in yv],
                                 "revenue": round(float(st.loc[month, sid]), 2)},
                    "impact_amt": round(float(st.loc[last3[2], sid] - st.loc[last3[0], sid]), 2),
                    "source_field": "store_revenue_yoy_trend",
                    "rule": f"连续 3 个月同比降幅 > {_pct(rules['R03']['threshold'])}%",
                })

    # ---- R04 毛利率环比 ----
    gm_mom = series.loc[month, "gross_margin_mom"]
    if pd.notna(gm_mom) and abs(gm_mom) > rules["R04"]["threshold"]:
        flags.append({
            "id": "R04", "level": rules["R04"]["level"],
            "title": "毛利率环比异常变动",
            "evidence": {"gross_margin": _pct(series.loc[month, "gross_margin"]),
                         "prev_gross_margin": _pct(series.iloc[i - 1]["gross_margin"]),
                         "change_pp": round(float(gm_mom) * 100, 2)},
            "impact_amt": round(float(gm_mom) * float(series.loc[month, "revenue"]), 2),
            "source_field": "gross_margin_diff",
            "rule": f"毛利率变动 |Δ| > {rules['R04']['threshold'] * 100:.1f}pp",
        })

    # ---- R05 品类单位成本 ----
    tmp = fact.assign(_cost=pd.to_numeric(fact["qty"]) * pd.to_numeric(fact["unit_cost"]),
                      _qty=pd.to_numeric(fact["qty"]))
    cm = tmp.groupby(["month", "category"])[["_cost", "_qty"]].sum()
    cm["_unit"] = cm["_cost"] / cm["_qty"]
    cm = cm["_unit"].unstack("category").sort_index()
    if i > 0:
        for cat in cm.columns:
            cur, prev = cm.loc[month, cat], cm.loc[months[i - 1], cat]
            if pd.notna(prev) and prev > 0 and (cur / prev - 1) > rules["R05"]["threshold"]:
                flags.append({
                    "id": "R05", "level": rules["R05"]["level"],
                    "title": f"{cat}单位成本明显上涨",
                    "evidence": {"category": cat, "unit_cost": round(float(cur), 2),
                                 "prev_unit_cost": round(float(prev), 2),
                                 "change_pct": _pct(cur / prev - 1)},
                    "impact_amt": round(float(cur - prev) * float(fact[fact["month"] == month]["qty"].sum() / 8), 2),
                    "source_field": "category_unit_cost",
                    "rule": f"单品类成本涨幅 > {_pct(rules['R05']['threshold'])}%",
                })

    # ---- R06 预算完成率 ----
    br = series.loc[month, "budget_rate"]
    if pd.notna(br) and br < rules["R06"]["threshold"]:
        flags.append({
            "id": "R06", "level": rules["R06"]["level"],
            "title": "预算完成率未达标",
            "evidence": {"budget_rate": _pct(br),
                         "revenue": round(float(series.loc[month, "revenue"]), 2),
                         "budget_revenue": round(float(series.loc[month, "budget_revenue"]), 2)},
            "impact_amt": round(float(series.loc[month, "var_amt"]), 2),
            "source_field": "budget_rate",
            "rule": f"预算完成率 < {_pct(rules['R06']['threshold'])}%",
        })

    # ---- R07 收现率 ----
    cr = series.loc[month, "cash_ratio"]
    if pd.notna(cr) and cr < rules["R07"]["threshold"]:
        flags.append({
            "id": "R07", "level": rules["R07"]["level"],
            "title": "收现率偏低",
            "evidence": {"cash_ratio": _pct(cr),
                         "cash_in": round(float(series.loc[month, "cash_in"]), 2),
                         "revenue": round(float(series.loc[month, "revenue"]), 2)},
            "impact_amt": round(float(series.loc[month, "cash_in"] - series.loc[month, "revenue"]), 2),
            "source_field": "cash_ratio",
            "rule": f"收现率 < {_pct(rules['R07']['threshold'])}%",
        })

    # ---- R08 新店占比 ----
    open_month = dict(zip(stores["store_id"], stores["open_month"]))
    new_stores = [s for s, om in open_month.items() if om >= "2024-01" and om <= month]
    if new_stores:
        cur_df = fact[fact["month"] == month]
        share = cur_df[cur_df["store_id"].isin(new_stores)]["revenue"].sum() / cur_df["revenue"].sum()
        if share > rules["R08"]["threshold"]:
            flags.append({
                "id": "R08", "level": rules["R08"]["level"],
                "title": "新店营收占比偏高",
                "evidence": {"new_stores": new_stores, "share_pct": _pct(share)},
                "impact_amt": None,
                "source_field": "new_store_share",
                "rule": f"新店占比 > {_pct(rules['R08']['threshold'])}%",
            })

    order = {"高": 0, "中": 1, "低": 2}
    flags.sort(key=lambda x: (order.get(x["level"], 3), -(abs(x["impact_amt"] or 0))))
    for n, f in enumerate(flags, 1):
        f["no"] = n
    return flags
