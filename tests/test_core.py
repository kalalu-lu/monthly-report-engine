"""
核心逻辑单元测试（不依赖 pytest，直接 python tests/test_core.py）

覆盖三点：
  1. 差异分解必须精确配平（手工算例 + 真实数据）
  2. 指标快照必须是 26 项且关键字段齐全
  3. 数据校验必须拦得住注入的脏数据
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import ingest, metrics, variance  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail and not cond else ""))


def test_decompose_by_hand() -> None:
    print("\n[1] 差异分解 · 手工算例")
    act = pd.DataFrame({"category": ["A", "B"], "qty": [120, 80],
                        "unit_price": [10.0, 20.0], "unit_cost": [4.0, 9.0]})
    bud = pd.DataFrame({"category": ["A", "B"], "budget_qty": [100, 100],
                        "budget_price": [9.0, 21.0], "budget_unit_cost": [4.0, 8.0]})
    r = variance.decompose(act, bud)
    rv, gv = r["revenue"], r["gross_profit"]

    check("营收差异 = -200", abs(rv["total"] + 200) < 1e-6, str(rv["total"]))
    check("营收量差 = -240", abs(rv["qty_effect"] + 240) < 1e-6, str(rv["qty_effect"]))
    check("营收价差 = 0", abs(rv["price_effect"]) < 1e-6, str(rv["price_effect"]))
    check("营收混合差 = 40", abs(rv["mix_effect"] - 40) < 1e-6, str(rv["mix_effect"]))
    check("营收三项配平", rv["balanced"], str(rv["balance_error"]))

    check("毛利差异 = -200", abs(gv["total"] + 200) < 1e-6, str(gv["total"]))
    check("毛利量差 = -160", abs(gv["qty_effect"] + 160) < 1e-6, str(gv["qty_effect"]))
    check("毛利价差 = 40", abs(gv["price_effect"] - 40) < 1e-6, str(gv["price_effect"]))
    check("毛利成本差 = -80", abs(gv["cost_effect"] + 80) < 1e-6, str(gv["cost_effect"]))
    check("毛利三项配平", gv["balanced"], str(gv["balance_error"]))


def test_decompose_partial_category() -> None:
    print("\n[2] 差异分解 · 品类只在一侧（新品类 / 停售）")
    act = pd.DataFrame({"category": ["A", "NEW"], "qty": [100, 30],
                        "unit_price": [10.0, 5.0], "unit_cost": [4.0, 2.0]})
    bud = pd.DataFrame({"category": ["A", "OLD"], "budget_qty": [100, 40],
                        "budget_price": [10.0, 6.0], "budget_unit_cost": [4.0, 3.0]})
    r = variance.decompose(act, bud)
    check("营收配平（含单侧品类）", r["revenue"]["balanced"], str(r["revenue"]["balance_error"]))
    check("毛利配平（含单侧品类）", r["gross_profit"]["balanced"], str(r["gross_profit"]["balance_error"]))
    check("总差异 = -90", abs(r["revenue"]["total"] + 90) < 1e-6, str(r["revenue"]["total"]))


def test_real_pipeline() -> None:
    raw_dir = ROOT / "data" / "raw"
    if not (raw_dir / "sales.csv").exists():
        print("\n[3] 跳过：data/raw 不存在，请先运行 python tools/gen_data.py")
        return
    print("\n[3] 真实数据 · 校验与指标")
    raw = ingest.load_raw(raw_dir)
    clean, quarantine = ingest.validate(raw["sales"], raw["dim_store"], raw["dim_category"])
    check("拦截到脏数据（>=5 行）", len(quarantine) >= 5, f"{len(quarantine)} 行")
    ids = set(quarantine["rule_id"].str.split("/").sum())
    for rid in ("V01", "V02", "V03", "V04", "V05", "V06"):
        check(f"命中规则 {rid} {ingest.RULES[rid]}", rid in ids, str(sorted(ids)))

    fact = metrics.build_fact(clean, raw["dim_store"])
    series = metrics.monthly_series(fact, raw["budget"], raw["dim_store"], raw["expenses"])
    month = "2025-10"
    kpis = metrics.kpi_snapshot(series, month)
    check("KPI 数量 = 26", len(kpis) == 26, f"{len(kpis)} 项")
    keys = {k["key"] for k in kpis}
    check("含毛利率", "gross_margin" in keys)
    check("含预算完成率", "budget_rate" in keys)

    act = fact[fact["month"] == month]
    bud = raw["budget"][raw["budget"]["month"] == month]
    r = variance.decompose(act, bud)
    check("真实数据营收配平", r["revenue"]["balanced"], str(r["revenue"]["balance_error"]))
    check("真实数据毛利配平", r["gross_profit"]["balanced"], str(r["gross_profit"]["balance_error"]))
    check("毛利率在合理区间 (0,1)", 0 < series.loc[month, "gross_margin"] < 1,
          str(series.loc[month, "gross_margin"]))

    # 回归测试：期间费用曾因"门店-月"并到"品类"粒度而重复 8 倍
    ex = raw["expenses"].copy()
    for c in ("rent", "labor", "marketing", "other"):
        ex[c] = pd.to_numeric(ex[c])
    real_opex = ex.loc[ex["month"] == month, ["rent", "labor", "marketing", "other"]].sum().sum()
    check("期间费用无重复加总", abs(float(series.loc[month, "opex"]) - real_opex) < 1e-6,
          f"系统 {series.loc[month, 'opex']:.2f} vs 实际 {real_opex:.2f}")
    check("费用率在合理区间 (0,1)", 0 < series.loc[month, "opex_ratio"] < 1,
          str(series.loc[month, "opex_ratio"]))


if __name__ == "__main__":
    print("=" * 60)
    print("核心逻辑单元测试")
    print("=" * 60)
    test_decompose_by_hand()
    test_decompose_partial_category()
    test_real_pipeline()
    print("\n" + "=" * 60)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + "、".join(FAIL))
        sys.exit(1)
    print("全部通过 ✓")
