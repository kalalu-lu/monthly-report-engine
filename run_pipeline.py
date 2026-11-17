"""
端到端流水线（Stage A）：raw → 校验 → 指标 → 差异分解 → 异常检测 → FactPack

运行：python run_pipeline.py            # 默认报告 2025-10
      python run_pipeline.py 2025-09   # 指定月份
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

_BOOT = Path(__file__).resolve().parent
if str(_BOOT) not in sys.path:
    sys.path.insert(0, str(_BOOT))

from src import detect, factpack, ingest, metrics, paths, variance  # noqa: E402

ROOT = paths.app_root()
RAW = paths.res_root() / "data" / "raw"
CLEAN = ROOT / "data" / "clean"
REF = ROOT / "data" / "ref"
OUT = ROOT / "outputs"
LOGS = OUT / "logs"


def main(month: str = "2025-10") -> dict:
    for d in (CLEAN, REF, OUT, LOGS):
        d.mkdir(parents=True, exist_ok=True)

    print("=" * 68)
    print(f"『月报引擎』Stage A 流水线    报告期：{month}")
    print("=" * 68)

    # ---- 1. 读取 + 校验 ----
    raw = ingest.load_raw(RAW)
    print(f"[1/6] 读取原始数据：明细 {len(raw['sales'])} 行，预算 {len(raw['budget'])} 行")
    clean, quarantine = ingest.validate(raw["sales"], raw["dim_store"], raw["dim_category"])
    print(f"      校验通过 {len(clean)} 行，拦截 {len(quarantine)} 行")
    for rid, cnt in quarantine["rule_id"].value_counts().items():
        print(f"        {rid:6s} {ingest.RULES[rid]}：{cnt} 行")
    quarantine.to_csv(LOGS / "quarantine.csv", index=False, encoding="utf-8-sig")

    missing = ingest.check_expense_coverage(clean, raw["expenses"])
    print(f"      V07 费用覆盖缺失：{len(missing)} 个门店-月")

    # 校验摘要进事实包：报告里的"数据可信度"段落要能回查到这里
    rules_hit = sorted({r for ids in quarantine["rule_id"] for r in ids.split("/") if r})
    validation = {
        "rows_in": int(len(raw["sales"])),
        "rows_clean": int(len(clean)),
        "rows_quarantined": int(len(quarantine)),
        "rules_hit": rules_hit,
        "rules_total": len(ingest.RULES),
        "expense_gap_pairs": int(len(missing)),
        "by_rule": {r: int((quarantine["rule_id"].str.split("/").map(lambda xs: r in xs)).sum())
                    for r in rules_hit},
    }

    # ---- 2. 事实表 ----
    print("[2/6] 构建事实表 …")
    fact = metrics.build_fact(clean, raw["dim_store"])
    fact.to_csv(CLEAN / "fact_table.csv", index=False, encoding="utf-8-sig")
    print(f"      事实表 {len(fact)} 行 × {fact.shape[1]} 列 → data/clean/fact_table.csv")

    # ---- 3. 月度指标 ----
    print("[3/6] 计算 26 项指标 …")
    series = metrics.monthly_series(fact, raw["budget"], raw["dim_store"], raw["expenses"])
    series.to_csv(OUT / "metrics_monthly.csv", encoding="utf-8-sig")
    kpis = metrics.kpi_snapshot(series, month)
    print(f"      KPI 快照 {len(kpis)} 项，月度序列 {len(series)} 期")
    rev = next(k["value"] for k in kpis if k["key"] == "revenue")
    gm = next(k["value"] for k in kpis if k["key"] == "gross_margin")
    br = next(k["value"] for k in kpis if k["key"] == "budget_rate")
    print(f"      营业收入 {rev:,.2f} 元 ｜ 毛利率 {gm}% ｜ 预算完成率 {br}%")

    # ---- 4. 差异分解 ----
    print("[4/6] 预算差异分解 …")
    act = fact[fact["month"] == month]
    bud = raw["budget"][raw["budget"]["month"] == month]
    var = variance.decompose(act, bud)
    rv = var["revenue"]
    print(f"      营收差异 {rv['total']:,.2f} 元（{rv['rate_pct']}%）")
    print(f"        量差 {rv['qty_effect']:,.2f} ｜ 价差 {rv['price_effect']:,.2f} ｜ 混合差 {rv['mix_effect']:,.2f}")
    print(f"        配平：{'✓ 通过' if rv['balanced'] else '✗ 失败'}（误差 {rv['balance_error']:.2e}）")
    gv = var["gross_profit"]
    print(f"      毛利差异 {gv['total']:,.2f} 元")
    print(f"        量差 {gv['qty_effect']:,.2f} ｜ 价差 {gv['price_effect']:,.2f} ｜ 成本差 {gv['cost_effect']:,.2f}")
    print(f"        配平：{'✓ 通过' if gv['balanced'] else '✗ 失败'}（误差 {gv['balance_error']:.2e}）")

    # ---- 5. 异常检测 ----
    print("[5/6] 异常检测 …")
    rules = detect.load_rules(REF / "rules.json")
    if not (REF / "rules.json").exists():
        (REF / "rules.json").write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
        print("      已生成默认规则文件 data/ref/rules.json")
    flags = detect.detect_all(fact, series, raw["budget"], raw["dim_store"], month, rules)
    lv = pd.Series([f["level"] for f in flags]).value_counts().to_dict() if flags else {}
    print(f"      命中 {len(flags)} 条：{lv}")
    for f in flags:
        print(f"        [{f['level']}] {f['id']} {f['title']}")

    # ---- 6. FactPack ----
    print("[6/6] 组装 FactPack …")
    fp = factpack.build(
        month=month, series=series, kpis=kpis, variance=var, flags=flags,
        stores=metrics.store_ranking(fact, raw["budget"], month),
        categories=metrics.category_mix(fact, month),
        validation=validation,
    )
    path = factpack.dump(fp, OUT / f"factpack_{month}.json")
    nums = factpack.flatten_numbers(fp)
    print(f"      已写入 {path.relative_to(ROOT)}（{len(nums)} 个可回查数字）")
    print("=" * 68)
    print("Stage A 完成。下一步：图表推荐 → 版面规划 → 文案生成 → 渲染。")
    return fp


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "2025-10"
    main(m)
