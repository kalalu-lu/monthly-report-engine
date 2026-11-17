"""
Stage B 组装：FactPack → 图表推荐 → SVG → （下一步）版面 → 文案 → 出稿

当前版本先打通"推荐 + 渲染"两段，产出 outputs/charts/*.svg 与一份预览 HTML。

运行：python tools/build_charts.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import chart_rec, svg  # noqa: E402

OUT = ROOT / "outputs"
CHARTS = OUT / "charts"


def load_factpack(month: str) -> dict:
    return json.loads((OUT / f"factpack_{month}.json").read_text(encoding="utf-8"))


def btn(v: float) -> str:
    return f"{v / 1e4:.1f}万"


def build(fp: dict) -> list[dict]:
    CHARTS.mkdir(parents=True, exist_ok=True)
    t = fp["trend"]
    recs = []

    # ---- 1. 营收 vs 预算（时间序列）----
    r = chart_rec.recommend(chart_rec.profile(len(t["months"]), "trend", "target", has_target=True))
    svg1 = svg.line_chart(
        "营业收入与预算对比", f"{t['months'][0]} — {t['months'][-1]}｜单位：元",
        [m[2:] for m in t["months"]],
        [{"name": f"营业收入（末月 {btn(t['revenue'][-1])}）", "values": t["revenue"],
          "color": svg.C["primary"], "area": True, "dots": True},
         {"name": f"预算（末月 {btn(t['revenue_budget'][-1])}）", "values": t["revenue_budget"],
          "color": svg.C["sub"], "dash": "6 4"}])
    recs.append({"slot": "营收趋势", "rec": r, "file": "01_revenue_trend.svg", "svg": svg1})

    # ---- 2. 门店排行（类别对比）----
    stores = fp["stores"]
    labels = [s["store_name"] for s in stores]
    vals = [s["revenue"] for s in stores]
    # 只把"真正异常"的门店标红（环比跌幅超过 15%），季节性回落不标红
    colors = [svg.C["accent"] if (s["mom"] or 0) < -15 else svg.C["primary"] for s in stores]
    r = chart_rec.recommend(chart_rec.profile(len(stores), "category", "ranking",
                                              label_max_chars=max(len(x) for x in labels)))
    svg2 = svg.hbar_chart(
        "门店营收排行", f"{fp['meta']['period']}｜金额与环比", labels, vals,
        bar_colors=colors,
        note_fmt=lambda i, v: f"{btn(v)}  环比 {stores[i]['mom']:+.1f}%")
    recs.append({"slot": "门店排行", "rec": r, "file": "02_store_ranking.svg", "svg": svg2})

    # ---- 3. 品类结构（类别对比；同类目按收入排序，右侧带占比与毛利）----
    cats = fp["categories"]
    r = chart_rec.recommend(chart_rec.profile(len(cats), "category", "ranking"))
    svg3 = svg.hbar_chart(
        "品类收入结构", f"{fp['meta']['period']}｜按收入排序，右侧为占比与毛利率",
        [c["category"] for c in cats], [c["revenue"] for c in cats],
        note_fmt=lambda i, v: f"{btn(v)}  占比 {cats[i]['share']:.1f}%  毛利 {cats[i]['gross_margin']:.1f}%")
    recs.append({"slot": "品类结构", "rec": r, "file": "03_category_mix.svg", "svg": svg3})

    # ---- 4. 差异分解（瀑布）----
    rv = fp["variance"]["revenue"]
    items = [{"name": "预算收入", "value": rv["budget"], "kind": "total"},
             {"name": "量差", "value": rv["qty_effect"], "kind": "delta"},
             {"name": "价差", "value": rv["price_effect"], "kind": "delta"},
             {"name": "混合差", "value": rv["mix_effect"], "kind": "delta"},
             {"name": "实际收入", "value": rv["actual"], "kind": "total"}]
    r = chart_rec.recommend(chart_rec.profile(len(items), "decompose", "variance"))
    svg4 = svg.waterfall_chart("营收差异分解", "预算 → 量差 → 价差 → 混合差 → 实际（三项之和精确等于总差异）", items)
    recs.append({"slot": "差异分解", "rec": r, "file": "04_variance_waterfall.svg", "svg": svg4})

    # ---- 5. 门店预算完成率（目标对比）----
    rows = [{"name": s["store_name"], "actual": s["revenue"],
             "target": round(s["revenue"] / (s["budget_rate"] / 100), 2)}
            for s in stores if s["budget_rate"]]
    r = chart_rec.recommend(chart_rec.profile(len(rows), "target", "target", has_target=True))
    svg5 = svg.bullet_chart("门店预算完成率", f"{fp['meta']['period']}｜浅色为预算、深色为实际、红线为目标",
                            rows)
    recs.append({"slot": "预算完成率", "rec": r, "file": "05_budget_bullet.svg", "svg": svg5})

    # ---- 6. 毛利率趋势 ----
    gm = t["gross_margin"]
    gm_delta = gm[-1] - gm[-2]
    r = chart_rec.recommend(chart_rec.profile(len(t["months"]), "trend", "trend"))
    svg6 = svg.line_chart("毛利率趋势", f"月度毛利率（%）｜环比 {gm_delta:+.2f}pp",
                          [m[2:] for m in t["months"]],
                          [{"name": f"毛利率（末月 {t['gross_margin'][-1]:.2f}%）",
                            "values": t["gross_margin"], "color": svg.C["accent"], "dots": True}],
                          y_fmt=lambda v: f"{v:.0f}%")
    recs.append({"slot": "毛利率趋势", "rec": r, "file": "06_gross_margin.svg", "svg": svg6})

    for x in recs:
        (CHARTS / x["file"]).write_text(x["svg"], encoding="utf-8")
    return recs


def build_preview(fp: dict, recs: list[dict]) -> Path:
    meta = fp["meta"]
    blocks = []
    for x in recs:
        blocks.append(f"""
    <section class="card">
      <div class="rec"><b>推荐：{x['rec']['name']}</b> · {x['rec']['score']} 分
        <span class="why">{x['rec']['reason']}</span></div>
      {x['svg']}
    </section>""")
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{meta['company']} {meta['period']} 图表预览</title>
<style>
  body{{margin:0;padding:28px 34px;background:#eef1f4;font-family:{svg.FONT};color:{svg.C['ink']}}}
  h1{{font-size:20px;margin:0 0 4px}} .sub{{color:{svg.C['sub']};font-size:12.5px;margin-bottom:20px}}
  .card{{background:#fff;border-radius:8px;padding:14px 16px 8px;margin-bottom:16px;
         box-shadow:0 1px 3px rgba(0,0,0,.08);max-width:760px}}
  .rec{{font-size:11.5px;color:{svg.C['sub']};margin-bottom:6px;line-height:1.6}}
  .rec b{{color:{svg.C['primary']}}} .why{{display:block;color:#8a8f98}}
  svg{{display:block}}
</style></head><body>
  <h1>{meta['company']} · {meta['period']} 月报图表预览</h1>
  <div class="sub">共 {len(recs)} 张图 ｜ 全部由手写 SVG 渲染器生成 ｜ 数据源 {meta['generated_at']}</div>
  {''.join(blocks)}
</body></html>"""
    p = OUT / "preview_charts.html"
    p.write_text(html, encoding="utf-8")
    return p


if __name__ == "__main__":
    month = sys.argv[1] if len(sys.argv) > 1 else "2025-10"
    fp = load_factpack(month)
    recs = build(fp)
    p = build_preview(fp, recs)
    print("=" * 60)
    print("图表生成完成")
    print("=" * 60)
    for x in recs:
        print(f"{x['file']:28s} {x['rec']['name']:6s} {x['rec']['score']:6.2f} 分")
    print(f"\n预览页：{p}")
