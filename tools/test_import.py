"""
端到端验证：企业拿模板填数 → 导入 → 出月报，这条路径走不走得通。

运行：python tools/test_import.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

import run_pipeline  # noqa: E402
from src import template  # noqa: E402


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="mre_import_"))
    print(f"临时目录：{tmp}")
    xlsx = tmp / "模板.xlsx"
    template.write_template(xlsx)
    print(f"[1] 模板已生成：{xlsx.name}（sheet：{pd.ExcelFile(xlsx).sheet_names}）")

    raw = tmp / "raw"
    raw.mkdir(parents=True)
    book = pd.ExcelFile(xlsx)
    for name in ("sales", "budget", "expenses", "dim_store", "dim_category"):
        pd.read_excel(book, sheet_name=name, dtype=str).to_csv(
            raw / f"{name}.csv", index=False, encoding="utf-8-sig")
    print(f"[2] 已从 Excel 拆成 5 张 CSV")

    sales = pd.read_csv(raw / "sales.csv", encoding="utf-8-sig")
    print(f"[3] 模板示例数据：{len(sales)} 行，月份 {sorted(sales['month'].unique())}")

    run_pipeline.RAW = raw
    try:
        fp = run_pipeline.main("2025-10")
        print(f"[4] 流水线通过：KPI {len(fp['kpis'])} 项，告警 {len(fp['anomalies'])} 条")
        verdict = next((k for k in fp["kpis"] if k["key"] == "revenue"), None)
        print(f"    营业收入 = {verdict['value']:,.2f}")
        print("\n[结果] 模板数据可以走通 Stage A。")
        print("       但模板只有 3 行示例，同比/趋势类指标会是空的——")
        print("       这是数据量问题，不是程序问题；正式使用至少填 13 个月。")
        return 0
    except Exception as e:  # noqa: BLE001
        import traceback
        print("\n[失败] 模板数据未能走通 Stage A：")
        traceback.print_exc()
        print(f"\n错误摘要：{type(e).__name__}: {e}")
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
