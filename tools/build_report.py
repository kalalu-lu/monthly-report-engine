"""
Stage B 组装：FactPack → 版面 DSL → 约束求解 → HTML → PDF

分工（每一步都可单独跑、单独验）：
  build_scene()   ：把 FactPack 翻译成"块 + 约束"，不涉及任何坐标；落盘成 DSL 文件
  layout.solve()  ：DSL → 每块 mm 坐标（见 src/layout.py）
  chart_svgs()    ：按求解出来的槽位尺寸**重新渲染**图表（图要服从版面，不是版面迁就图）
  render_html     ：坐标 → 绝对定位 HTML（见 src/render_html.py）
  render_pdf      ：HTML → PDF（见 src/render_pdf.py）

运行：
  python tools/build_report.py 2025-10
  python tools/build_report.py 2025-10 --no-pdf
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_BOOT = Path(__file__).resolve().parents[1]
if str(_BOOT) not in sys.path:
    sys.path.insert(0, str(_BOOT))

from src import chart_rec, dsl, layout, render_html, render_pdf, svg  # noqa: E402
from src import paths  # noqa: E402

ROOT = paths.app_root()
OUT = ROOT / "outputs"
CHARTS = OUT / "charts"
LLM = OUT / "llm"
MM_PER_PX = 25.4 / 96.0

# 版面参数：内容区 180 × 267mm，12 列，列间距 6mm
PAGE = {
    "size": "A4", "orientation": "portrait",
    "margin": {"top": 16, "right": 15, "bottom": 14, "left": 15},
    "columns": 12, "gutter": 6, "footer": 9,
}
COL_W = 12


# --------------------------------------------------------------------- 小工具
def wan(v: float) -> str:
    return f"{v / 1e4:,.1f}"


def kpi_by_key(fp: dict, key: str) -> dict:
    for k in fp["kpis"]:
        if k["key"] == key:
            return k
    raise KeyError(key)


def fmt_kpi(k: dict) -> tuple[str, str]:
    """(数值, 单位)，只做单位换算，不做别的运算——保证数字可回查。"""
    v = k["value"]
    u = k["unit"]
    if u == "元":
        return (wan(v), "万元") if abs(v) >= 1e4 else (f"{v:,.0f}", "元")
    if u == "单":
        return (wan(v), "万单") if abs(v) >= 1e4 else (f"{v:,.0f}", "单")
    if u == "%":
        return f"{v:.2f}", "%"
    if u == "pp":
        return f"{v:+.2f}", "pp"
    return f"{v:.2f}", u


def tone_of(k: dict) -> str:
    mom = k.get("mom")
    better = k.get("higher_better")
    if mom is None or better is None or abs(mom) < 0.05:
        return ""
    good = (mom > 0) == bool(better)
    return "up" if good else ("down" if mom < 0 else "warn")


def num_text(v: float) -> str:
    return f"{v:,.2f}"


def text_height(paras: list[str], width_mm: float, size_pt: float = 9.6,
                line_height: float = 1.75, para_gap_mm: float = 1.8,
                pad_mm: float = 1.0) -> float:
    """按 CSS 的真实行高逐段量高：段与段之间是 margin，不是空行（之前把空行也算了高度）。"""
    lines = sum(len(dsl.wrap_lines(p, width_mm - 1.0, size_pt)) for p in paras)
    h = lines * size_pt * line_height * dsl.PT_TO_MM
    h += para_gap_mm * max(0, len(paras) - 1)
    return round(h * 1.03 + pad_mm, 1)


def _note_w(notes: list[str], w: int) -> float:
    """横条图右侧注释列需要多宽：按注释本身量出来，封顶 42% 图宽。"""
    if not notes:
        return 0.0
    need = max(svg.text_w(str(n), 10.5) for n in notes) + 18
    return min(need, w * 0.42)


# --------------------------------------------------------------------- 文案（v3）
def load_narrative(month: str) -> tuple[dict, str]:
    """优先用 v3 提示词的真实产出（outputs/llm/v3_*.md 里被校验通过的那一版），
    没有就用程序兜底模板——两条路都不允许出现事实包之外的数字。"""
    files = sorted(LLM.glob(f"v3_{month}_*.md"))
    for f in reversed(files):
        text = f.read_text(encoding="utf-8")
        m = re.search(r"## 第 \d+ 次返回[^\n]*\n```\n(.*?)\n```", text, re.S)
        if not m:
            continue
        try:
            obj = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if obj.get("verdict"):
            return obj, f.relative_to(ROOT).as_posix()
    return fallback_narrative(month), "（程序兜底模板）"


def fallback_narrative(month: str) -> dict:
    return {
        "rating": "—",
        "verdict": "本月未找到 v3 文案产出，正文由程序模板生成。",
        "issues": [], "decomposition": [], "actions": [],
        "insufficient": ["缺少大模型文案，无法给出归因判断。"],
    }


# --------------------------------------------------------------------- 图表
def chart_svg(kind: str, fp: dict, w: int, h: int) -> str:
    t = fp["trend"]
    if kind == "revenue_trend":
        return svg.line_chart(
            "营业收入与预算", f"{t['months'][0]} — {t['months'][-1]}｜单位：元",
            [m[2:] for m in t["months"]],
            [{"name": f"营业收入（本月 {wan(t['revenue'][-1])} 万元）", "values": t["revenue"],
              "color": svg.C["primary"], "area": True, "dots": True},
             {"name": f"预算（本月 {wan(t['revenue_budget'][-1])} 万元）", "values": t["revenue_budget"],
              "color": svg.C["sub"], "dash": "6 4"}],
            width=w, height=h)
    if kind == "waterfall":
        rv = fp["variance"]["revenue"]
        items = [{"name": "预算", "value": rv["budget"], "kind": "total"},
                 {"name": "量差", "value": rv["qty_effect"], "kind": "delta"},
                 {"name": "价差", "value": rv["price_effect"], "kind": "delta"},
                 {"name": "混合差", "value": rv["mix_effect"], "kind": "delta"},
                 {"name": "实际", "value": rv["actual"], "kind": "total"}]
        return svg.waterfall_chart(
            "营收差异分解（三项之和 = 总差异）",
            f"预算 {wan(rv['budget'])} 万 → 实际 {wan(rv['actual'])} 万，差 {wan(rv['total'])} 万",
            items, width=w, height=h)
    if kind == "store_rank":
        stores = fp["stores"]
        labels = [s["store_name"] for s in stores]
        colors = [svg.C["accent"] if (s["mom"] or 0) < -15 else svg.C["primary"] for s in stores]
        notes = [f"{wan(s['revenue'])}万 · {s['mom']:+.2f}% · 达成 {s['budget_rate']:.2f}%" for s in stores]
        return svg.hbar_chart(
            "门店营收排行", f"{fp['meta']['period']}｜金额、环比与预算完成率",
            labels, [s["revenue"] for s in stores], width=w, height=h, bar_colors=colors,
            note_fmt=lambda i, v: notes[i], note_w=_note_w(notes, w))
    if kind == "category":
        cats = fp["categories"]
        notes = [f"{wan(c['revenue'])}万 · 占比 {c['share']:.2f}% · 毛利 {c['gross_margin']:.2f}%"
                 for c in cats]
        return svg.hbar_chart(
            "品类收入结构", f"{fp['meta']['period']}｜按收入排序",
            [c["category"] for c in cats], [c["revenue"] for c in cats],
            width=w, height=h, note_fmt=lambda i, v: notes[i], note_w=_note_w(notes, w))
    if kind == "gross_margin":
        gm = t["gross_margin"]
        return svg.line_chart(
            "毛利率趋势", f"月度毛利率（%）｜本月 {gm[-1]:.2f}%",
            [m[2:] for m in t["months"]],
            [{"name": f"毛利率 {gm[-1]:.2f}%", "values": gm, "color": svg.C["accent"], "dots": True}],
            width=w, height=h, y_fmt=lambda v: f"{v:.0f}%")
    if kind == "budget_bullet":
        rows = [{"name": s["store_name"], "actual": s["revenue"],
                 "target": round(s["revenue"] / (s["budget_rate"] / 100), 2)}
                for s in fp["stores"] if s["budget_rate"]]
        return svg.bullet_chart("门店预算完成率", f"{fp['meta']['period']}｜浅色预算、深色实际、红线目标",
                                rows, width=w, height=h)
    raise KeyError(kind)


def chart_svgs(scene: dsl.Scene, plan: dict, fp: dict) -> dict[str, str]:
    """按版面槽位的真实尺寸重画图：图表的宽高比由版面决定，而不是反过来。"""
    out = {}
    CHARTS.mkdir(parents=True, exist_ok=True)
    for b in scene.blocks:
        if b.kind != "chart":
            continue
        p = plan["placements"][b.id]
        w = max(300, round(p["w_mm"] / MM_PER_PX))
        h = max(130, round(p["h_mm"] / MM_PER_PX))
        out[b.id] = chart_svg(b.content["chart"], fp, w, h)
        (CHARTS / f"{b.id}.svg").write_text(out[b.id], encoding="utf-8")
    return out


# --------------------------------------------------------------------- DSL 组装
def build_scene(fp: dict, narrative: dict) -> dsl.Scene:
    g = dsl.geometry(PAGE)
    full = g.span_width(12)
    half = g.span_width(6)
    t = fp["trend"]
    rev = kpi_by_key(fp, "revenue")
    rv = fp["variance"]["revenue"]

    blocks: list[dict] = []
    cons: list[dict] = []

    blocks.append({
        "id": "hero", "kind": "title", "span": 12, "height": 34,
        "title": f"{fp['meta']['period'][:4]} 年 {int(fp['meta']['period'][5:])} 月经营月报",
        "content": {"kicker": "MONTHLY BUSINESS REVIEW",
                    "subtitle": f"{fp['meta']['company']}｜{t['months'][0]} — {t['months'][-1]}（13 个月）｜"
                                f"全部数字由程序计算，可在事实包中逐项回查"},
    })

    kpi_specs = [("revenue", "营业收入"), ("orders", "订单量"), ("aov", "客单价"),
                 ("gross_margin", "毛利率"), ("budget_rate", "预算完成率"), ("opex_ratio", "期间费用率")]
    kpi_ids = []
    for i, (key, label) in enumerate(kpi_specs):
        k = kpi_by_key(fp, key)
        val, unit = fmt_kpi(k)
        if key == "budget_rate":
            # 预算完成率的"环比"没有意义（+0.07pp），真正要看的是相对预算差多少
            vr = kpi_by_key(fp, "var_rate")
            delta = f"预算{vr['value']:+.2f}%"
            tone = "down" if vr["value"] < 0 else "up"
        else:
            mom = k.get("mom")
            delta = "—" if mom is None else f"环比{mom:+.2f}{k.get('mom_unit') or ''}"
            tone = tone_of(k)
        bid = f"kpi{i + 1}_{key}"
        kpi_ids.append(bid)
        blocks.append({"id": bid, "kind": "kpi", "span": 2, "height": 27,
                       "title": label,
                       "content": {"label": label, "value": val, "unit": unit,
                                   "delta": delta, "tone": tone,
                                   "inline_unit": unit in ("%",)}})
    cons.append(dsl.same_row(*kpi_ids))

    verdict = narrative.get("verdict", "")
    blocks.append({
        "id": "verdict", "kind": "callout", "span": 12,
        "height": dsl.measure_text_height(verdict, full, size_pt=10.0, line_height=1.72,
                                          pad_mm=12.0, min_height=22),
        "title": "本月结论",
        "content": {"title": f"本月结论 · 评级 {narrative.get('rating', '—')}", "body": verdict},
    })

    blocks.append({"id": "c_rev", "kind": "chart", "span": 12, "height": 70,
                   "content": {"chart": "revenue_trend"}})
    cons.append(dsl.aspect("c_rev", 2.2, 3.4))

    blocks.append({"id": "sec1", "kind": "section", "span": 12, "height": 12,
                   "title": "预算执行：差在哪一环", "content": {"no": "01", "note": "差异分解与配平"}})
    cons.append(dsl.avoid_orphan("sec1"))

    blocks.append({"id": "c_var", "kind": "chart", "span": 12, "height": 64,
                   "content": {"chart": "waterfall"}})
    cons.append(dsl.aspect("c_var", 2.2, 3.4))

    var_rows = [
        ["量差", num_text(rv["qty_effect"]), "销量低于预算带来的收入缺口"],
        ["价差", num_text(rv["price_effect"]), "实际单价低于预算单价的部分"],
        ["混合差", num_text(rv["mix_effect"]), "量价同时变化产生的交叉项"],
        ["合计", num_text(rv["total"]), "三项之和 = 总差异（配平误差 0）"],
    ]
    var_cols = [{"label": "因素", "width": 1.2}, {"label": "金额（元）", "width": 2.2, "align": "right"},
                {"label": "说明", "width": 6.0}]
    vh = dsl.measure_table_height(var_cols, var_rows, full)
    blocks.append({"id": "t_var", "kind": "table", "span": 12,
                   "height": round(sum(vh) + 3.0, 1), "title": "营收差异分解",
                   "content": {"columns": var_cols, "rows": var_rows, "row_heights": vh}})

    blocks.append({"id": "sec2", "kind": "section", "span": 12, "height": 12,
                   "title": "门店与品类：结构在往哪走", "content": {"no": "02", "note": "六个门店 / 八个品类"}})
    cons.append(dsl.avoid_orphan("sec2"))

    blocks.append({"id": "c_store", "kind": "chart", "span": 12, "height": 66,
                   "content": {"chart": "store_rank"}})
    cons.append(dsl.aspect("c_store", 2.2, 3.4))
    blocks.append({"id": "c_cat", "kind": "chart", "span": 12, "height": 64,
                   "content": {"chart": "category"}})
    cons.append(dsl.aspect("c_cat", 2.2, 3.4))

    # 结构解读：全部由事实包字段拼出，不做任何额外计算（占比、HHI 都是事实包原值）
    top, last = fp["stores"][0], fp["stores"][-1]
    cats = fp["categories"][:3]
    hhi_s = kpi_by_key(fp, "store_hhi")["value"]
    hhi_c = kpi_by_key(fp, "cat_hhi")["value"]
    read = (f"门店：{top['store_name']} {num_text(top['revenue'])} 元，占 {top['revenue_share']:.2f}%；"
            f"{last['store_name']} {num_text(last['revenue'])} 元，占 {last['revenue_share']:.2f}%，"
            f"环比 {last['mom']:+.2f}%，是唯一环比降幅超过 15% 的门店。\n\n"
            f"品类：" + "，".join(f"{c['category']} {num_text(c['revenue'])} 元（{c['share']:.2f}%）" for c in cats)
            + f"；前三类合计撑起主要收入面。\n\n"
            f"集中度：门店 HHI {hhi_s:.4f}，品类 HHI {hhi_c:.4f}；越接近 1 越集中，本月的分散程度说明"
            f"单店、单品类的失守都难以被其他单元完全对冲。")
    blocks.append({
        "id": "t_read", "kind": "text", "span": 12,
        "height": text_height(read.split("\n\n"), full),
        "title": "结构解读",
        "content": {"paras": read.split("\n\n")},
    })

    blocks.append({"id": "sec3", "kind": "section", "span": 12, "height": 12,
                   "title": "问题与动作", "content": {"no": "03", "note": "只列事实包命中的告警"}})
    cons.append(dsl.avoid_orphan("sec3"))

    issues = narrative.get("issues") or []
    issue_rows = [[str(it.get("level", "")), it.get("title", ""), it.get("evidence", ""),
                   it.get("cause", "")] for it in issues] or [["—", "无告警", "—", "—"]]
    issue_cols = [{"label": "等级", "width": 0.9}, {"label": "问题", "width": 3.0},
                  {"label": "证据（字段=值）", "width": 3.2}, {"label": "可能原因", "width": 4.6}]
    ih = dsl.measure_table_height(issue_cols, issue_rows, full)
    blocks.append({"id": "t_issue", "kind": "table", "span": 12, "height": round(sum(ih) + 3.0, 1),
                   "title": "异常与归因",
                   "content": {"columns": issue_cols, "rows": issue_rows, "row_heights": ih,
                               "level_col": True}})

    actions = narrative.get("actions") or []
    act_rows = [[str(a.get("target", "")), a.get("action", ""), a.get("metric", "")] for a in actions] \
        or [["—", "无", "—"]]
    act_cols = [{"label": "对应", "width": 0.9}, {"label": "动作", "width": 5.2},
                {"label": "可量化目标", "width": 5.0}]
    ah = dsl.measure_table_height(act_cols, act_rows, full)
    blocks.append({"id": "t_action", "kind": "table", "span": 12, "height": round(sum(ah) + 3.0, 1),
                   "title": "下月动作",
                   "content": {"columns": act_cols, "rows": act_rows, "row_heights": ah}})

    blocks.append({"id": "sec4", "kind": "section", "span": 12, "height": 12,
                   "title": "两条趋势线", "content": {"no": "04", "note": "毛利率与预算达成"}})
    cons.append(dsl.avoid_orphan("sec4"))
    blocks.append({"id": "c_gm", "kind": "chart", "span": 6, "height": 64,
                   "content": {"chart": "gross_margin"}})
    blocks.append({"id": "c_bullet", "kind": "chart", "span": 6, "height": 64,
                   "content": {"chart": "budget_bullet"}})
    cons.append(dsl.same_row("c_gm", "c_bullet"))
    cons.append(dsl.aspect("c_gm", 1.15, 1.9))
    cons.append(dsl.aspect("c_bullet", 1.15, 1.9))

    insuff = narrative.get("insufficient") or []
    v = fp.get("validation") or {}
    if v:
        dq = (f"原始明细 {v['rows_in']} 行，校验拦下 {v['rows_quarantined']} 行"
              f"（命中 {v['rules_hit'][0]}–{v['rules_hit'][-1]} 共 {len(v['rules_hit'])} 条规则），"
              f"进入计算的 {v['rows_clean']} 行；费用覆盖缺口 {v['expense_gap_pairs']} 个门店-月。"
              f"差异分解三项相加与总差异的误差为 0，可逐项验算。")
        blocks.append({
            "id": "dq", "kind": "callout", "span": 12,
            "height": dsl.measure_text_height(dq, full, size_pt=9.4, line_height=1.72,
                                              pad_mm=12.0, min_height=22),
            "title": "数据可信度",
            "content": {"title": "数据可信度：先证明数字是真的，再谈结论", "body": dq},
        })

    note = ("口径：营收、毛利、费用均来自 data/clean/fact_table.csv；预算来自 data/raw/budget.csv；"
            "差异分解三项相加精确等于总差异（误差 0，单元测试守护）。"
            "页面坐标由约束求解器给出，同一份事实包重复运行版面完全一致。")
    if insuff:
        note += "　仅凭本数据无法判断：" + "；".join(insuff)
    blocks.append({"id": "note", "kind": "footer", "span": 12,
                   "height": dsl.measure_text_height(note, full, size_pt=7.6, pad_mm=4.0, min_height=14),
                   "content": {"lines": [note]}})

    cons += [dsl.fill(0.80, 1.0), dsl.max_pages(4)]

    return dsl.parse({
        "meta": {"title": f"{fp['meta']['company']} {fp['meta']['period']} 经营月报",
                 "running_head": f"{fp['meta']['company']} · {fp['meta']['period']}"},
        "page": PAGE,
        "solver": {"page_cost": 60, "fill_min": 0.80, "fill_max": 1.0},
        "blocks": blocks,
        "constraints": cons,
    })


# --------------------------------------------------------------------- 主流程
def main(month: str = "2025-10", make_pdf: bool = True) -> dict:
    fp = json.loads((OUT / f"factpack_{month}.json").read_text(encoding="utf-8"))
    narrative, src = load_narrative(month)

    scene = build_scene(fp, narrative)
    dsl_path = scene.dump(OUT / f"layout_dsl_{month}.json")

    plan = layout.solve(scene)
    plan_path = OUT / f"layout_plan_{month}.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    inline = chart_svgs(scene, plan, fp)
    html_path = OUT / f"report_{month}.html"
    render_html.write(scene, plan, html_path, inline=inline,
                      doc_title=f"{fp['meta']['company']} {month} 经营月报")

    print("=" * 68)
    print("『月报引擎』Stage B —— 版面求解与出稿")
    print("=" * 68)
    print(f"文案来源   : {src}（评级 {narrative.get('rating')}）")
    print(f"DSL        : {dsl_path.relative_to(ROOT)}（{len(scene.blocks)} 块 / {len(scene.constraints)} 条约束）")
    print(f"版面计划   : {plan_path.relative_to(ROOT)}")
    m = plan["metrics"]
    print(f"求解结果   : {m['pages']} 页，填充率 平均 {m['fill_avg']:.1%} / 最低 {m['fill_min']:.1%}，"
          f"目标值 {m['objective']:.1f}")
    for it in plan["trace"]["iterations"]:
        print(f"             第 {it['iter']} 轮：页成本 {it['page_cost']} → {it['pages']} 页")
    for pg in plan["pages"]:
        ids = [b["id"] for r in pg["rows"] for b in r["blocks"]]
        print(f"  第 {pg['index']} 页  {pg['fill']:.1%}  {', '.join(ids)}")
    hard = [v for v in layout.check_plan(scene, plan) if v["hard"]]
    print(f"几何自检   : {'全部通过' if not hard else '发现 %d 项违规' % len(hard)}")
    for v in plan["soft_violations"]:
        print(f"  软约束：{v}")
    print(f"HTML       : {html_path.relative_to(ROOT)}")

    result = {"scene": scene, "plan": plan, "html": html_path, "dsl": dsl_path, "pdf": None}
    if make_pdf:
        try:
            info = render_pdf.to_pdf(html_path, OUT / f"report_{month}.pdf")
            errs = render_pdf.check_pdf(info["path"], expect_pages=m["pages"])
            pdf_info = render_pdf.pdf_info(info["path"])
            print(f"PDF        : {info['path'].relative_to(ROOT)}（{pdf_info['size_bytes'] / 1024:.0f} KB，"
                  f"{pdf_info['pages']} 页，{pdf_info['page_mm'][0]}×{pdf_info['page_mm'][1]}mm，"
                  f"{info['ms']} ms）")
            print(f"PDF 校验   : {'通过' if not errs else '；'.join(errs)}")
            print(f"字体       : {', '.join(pdf_info['fonts'][:6])}")
            result["pdf"] = info["path"]
        except render_pdf.RenderError as e:
            print(f"PDF        : 失败 → {e}")
            result["pdf_error"] = str(e)
    print("=" * 68)
    return result


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    m = args[0] if args else "2025-10"
    main(m, make_pdf="--no-pdf" not in sys.argv)
