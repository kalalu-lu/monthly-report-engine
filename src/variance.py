"""
预算差异分解（Stage A 第三步）

核心要求：分解项相加必须精确等于总差异（"配平"）。这是外行也能验算的专业性证据。

营收差异（三项，精确配平）：
    量差   = Σ (q1 - q0) * p0
    价差   = Σ (p1 - p0) * q0
    混合差 = Σ (p1 - p0) * (q1 - q0)
    ΔR = 量差 + 价差 + 混合差

毛利差异（三项，精确配平）：
    量差   = Σ (q1 - q0) * (p0 - c0)
    价差   = Σ (p1 - p0) * q1
    成本差 = -Σ (c1 - c0) * q1
    ΔM = 量差 + 价差 + 成本差
"""
from __future__ import annotations

import pandas as pd

TOL = 1e-6


def _side(df: pd.DataFrame, qcol: str, pcol: str, ccol: str) -> pd.DataFrame:
    q = pd.to_numeric(df[qcol], errors="coerce").fillna(0.0)
    p = pd.to_numeric(df[pcol], errors="coerce").fillna(0.0)
    c = pd.to_numeric(df[ccol], errors="coerce").fillna(0.0)
    part = pd.DataFrame({
        "category": df["category"].values,
        "qty": q.values,
        "revenue": (q * p).values,
        "cost": (q * c).values,
    })
    return part.groupby("category")[["qty", "revenue", "cost"]].sum()


def decompose(act: pd.DataFrame, bud: pd.DataFrame) -> dict:
    """act / bud 为同一期间明细行；预算侧使用 budget_qty / budget_price / budget_unit_cost。"""
    a = _side(act, "qty", "unit_price", "unit_cost")
    b = _side(bud, "budget_qty", "budget_price", "budget_unit_cost")

    m = a.join(b, how="outer", lsuffix="_a", rsuffix="_b").fillna(0.0)
    m["p1"] = (m["revenue_a"] / m["qty_a"].replace(0, pd.NA)).fillna(0.0)
    m["p0"] = (m["revenue_b"] / m["qty_b"].replace(0, pd.NA)).fillna(0.0)
    m["c1"] = (m["cost_a"] / m["qty_a"].replace(0, pd.NA)).fillna(0.0)
    m["c0"] = (m["cost_b"] / m["qty_b"].replace(0, pd.NA)).fillna(0.0)

    dq = m["qty_a"] - m["qty_b"]
    dp = m["p1"] - m["p0"]
    dc = m["c1"] - m["c0"]

    rev_qty = float((dq * m["p0"]).sum())
    rev_price = float((dp * m["qty_b"]).sum())
    rev_mix = float((dp * dq).sum())
    rev_total = float(m["revenue_a"].sum() - m["revenue_b"].sum())

    gp_a = float(m["revenue_a"].sum() - m["cost_a"].sum())
    gp_b = float(m["revenue_b"].sum() - m["cost_b"].sum())
    gp_total = gp_a - gp_b
    gp_qty = float((dq * (m["p0"] - m["c0"])).sum())
    gp_price = float((dp * m["qty_a"]).sum())
    gp_cost = float((-dc * m["qty_a"]).sum())

    budget_rev = float(m["revenue_b"].sum())
    by_cat = []
    for cat, r in m.iterrows():
        by_cat.append({
            "category": cat,
            "revenue_actual": round(float(r["revenue_a"]), 2),
            "revenue_budget": round(float(r["revenue_b"]), 2),
            "revenue_total": round(float(r["revenue_a"] - r["revenue_b"]), 2),
            "revenue_qty": round(float((r["qty_a"] - r["qty_b"]) * r["p0"]), 2),
            "revenue_price": round(float((r["p1"] - r["p0"]) * r["qty_b"]), 2),
            "revenue_mix": round(float((r["p1"] - r["p0"]) * (r["qty_a"] - r["qty_b"])), 2),
        })
    by_cat.sort(key=lambda x: abs(x["revenue_total"]), reverse=True)

    rev_err = rev_total - (rev_qty + rev_price + rev_mix)
    gp_err = gp_total - (gp_qty + gp_price + gp_cost)
    return {
        "revenue": {
            "actual": round(float(m["revenue_a"].sum()), 2),
            "budget": round(budget_rev, 2),
            "total": round(rev_total, 2),
            "rate_pct": round(rev_total / budget_rev * 100, 2) if budget_rev else None,
            "qty_effect": round(rev_qty, 2),
            "price_effect": round(rev_price, 2),
            "mix_effect": round(rev_mix, 2),
            "balance_error": round(rev_err, 8),
            "balanced": bool(abs(rev_err) < TOL * max(1.0, abs(rev_total))),
        },
        "gross_profit": {
            "actual": round(gp_a, 2),
            "budget": round(gp_b, 2),
            "total": round(gp_total, 2),
            "qty_effect": round(gp_qty, 2),
            "price_effect": round(gp_price, 2),
            "cost_effect": round(gp_cost, 2),
            "balance_error": round(gp_err, 8),
            "balanced": bool(abs(gp_err) < TOL * max(1.0, abs(gp_total))),
        },
        "by_category": by_cat[:10],
    }
