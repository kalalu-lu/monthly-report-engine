"""
出稿评测（Stage B 的验收环节）

和 chart_rec / copy 的评测思路一致：**不看"我觉得挺好"，只看能验的指标**。

七组检查：
  C 版面约束   —— 调用 layout.check_plan 独立复算几何（越界/重叠/顺序/同排/同页/长宽比）
  O 内容溢出   —— 按字号与列宽重算每块需要多高，超出槽位就报（文字被裁是版面的头号事故）
  G 图表适配   —— 每张图的实际 SVG 宽高比必须等于它的版面槽位（图被拉伸=读图失真）
  T 标题孤行   —— 章节标题不能是某页最后一行
  N 数字回查   —— 把 HTML 正文里的每个数字拿去和事实包比对，查不到出处就报
  P PDF 质检   —— 页数是否等于版面计划、是否 A4、字体是否内嵌
  R 可复现     —— 同一份 DSL 再解一次，版面计划必须逐字节相同

另外给出**基线对比**：同样的块，用"填不下就翻页"的贪心排版会得到什么结果。
这是本项目一贯的评估口径——任何"更好"都要有对照组。

运行：python tools/eval_report.py 2025-10
产物：outputs/eval_<月份>.json / .md
"""
from __future__ import annotations

import html as html_lib
import json
import re
import sys
from pathlib import Path

_BOOT = Path(__file__).resolve().parents[1]
if str(_BOOT) not in sys.path:
    sys.path.insert(0, str(_BOOT))

from src import narrative as copymod  # noqa: E402
from src import dsl, layout, paths, render_pdf  # noqa: E402

ROOT = paths.app_root()
OUT = ROOT / "outputs"
CHARTS = OUT / "charts"

DATE_PAT = [
    re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月"),
    re.compile(r"\d{4}-\d{2}(-\d{2})?"),
    re.compile(r"\b(19|20)\d{2}\b"),
    re.compile(r"\d{1,2}\s*月"),
]


# --------------------------------------------------------------------- 文本
def html_text(html: str) -> str:
    """取出正文（不含 SVG）：图表里的坐标刻度是渲染器按数值范围生成的，不属于事实陈述。"""
    body = re.sub(r"<style.*?</style>", " ", html, flags=re.S)
    body = re.sub(r"<svg.*?</svg>", " ", body, flags=re.S)
    body = re.sub(r"<[^>]+>", " ", body)
    body = html_lib.unescape(body)
    return re.sub(r"[ \t\u3000]+", " ", body).strip()


def strip_dates(text: str) -> str:
    for p in DATE_PAT:
        text = p.sub(" ", text)
    return text


# --------------------------------------------------------------------- 内容高度
def required_height(b: dsl.Block, w: float) -> float | None:
    """按字号与可用宽度重算这个块"需要"多高；None 表示固定设计块（标题/图/章节条）。"""
    c = b.content or {}
    if b.kind == "text":
        paras = c.get("paras") or ([b.title] if b.title else [])
        lines = sum(len(dsl.wrap_lines(p, w - 1.0, 9.6)) for p in paras)
        return round(lines * 9.6 * 1.75 * dsl.PT_TO_MM + 1.8 * max(0, len(paras) - 1) + 1.0, 1)
    if b.kind == "callout":
        body = str(c.get("body", ""))
        size = 10.0 if not c.get("small") else 9.0
        lines = len(dsl.wrap_lines(body, w - 8.4, size))
        h = 3.0 + 4.6 + 1.6 + lines * size * 1.72 * dsl.PT_TO_MM + 3.0
        bullets = c.get("bullets") or []
        if bullets:
            h += sum(len(dsl.wrap_lines(x, w - 12.0, 9.0)) for x in bullets) * 9.0 * 1.72 * dsl.PT_TO_MM
        return round(h, 1)
    if b.kind == "table":
        cols = c.get("columns") or []
        rows = c.get("rows") or []
        if not cols:
            return None
        hs = dsl.measure_table_height(cols, rows, w)
        return round(sum(hs) + 1.0, 1)
    if b.kind == "kpi":
        return 26.0
    if b.kind == "footer":
        text = " ".join(c.get("lines") or [])
        return round(len(dsl.wrap_lines(text, w, 7.6)) * 7.6 * 1.62 * dsl.PT_TO_MM + 1.0, 1)
    return None


# --------------------------------------------------------------------- 主评测
def evaluate(month: str = "2025-10") -> dict:
    fp = json.loads((OUT / f"factpack_{month}.json").read_text(encoding="utf-8"))
    scene = dsl.load(OUT / f"layout_dsl_{month}.json")
    plan = json.loads((OUT / f"layout_plan_{month}.json").read_text(encoding="utf-8"))
    html_path = OUT / f"report_{month}.html"
    pdf_path = OUT / f"report_{month}.pdf"
    html = html_path.read_text(encoding="utf-8")
    geom = dsl.geometry(scene.page)

    checks: list[dict] = []

    def add(cid: str, name: str, level: str, passed: bool, detail: str = "") -> None:
        checks.append({"id": cid, "name": name, "level": level,
                       "passed": bool(passed), "detail": detail})

    # ---- C 版面约束 ----
    vio = layout.check_plan(scene, plan)
    hard = [v for v in vio if v["hard"]]
    soft = [v for v in vio if not v["hard"]]
    add("C1", "几何合法（不越界/不重叠/顺序不乱）", "hard", not hard,
        "；".join(f"{v['constraint']}:{v['detail']}" for v in hard[:6]) or "全部通过")
    kinds = {}
    for v in hard:
        kinds[v["constraint"]] = kinds.get(v["constraint"], 0) + 1
    inv = {}
    for c in scene.constraints:
        inv[c["type"]] = inv.get(c["type"], 0) + 1
    add("C2", "约束清单（DSL 声明了多少条、各是什么）", "info", True,
        "、".join(f"{k}×{v}" for k, v in sorted(inv.items())) + f"；共 {len(scene.constraints)} 条")
    add("C3", "填充率不低于下限", "soft",
        all(p["fill"] >= scene.solver["fill_min"] - 1e-6 for p in plan["pages"]),
        "；".join(v["detail"] for v in soft) or "全部达标")

    # ---- G 图表槽位 ----
    chart_blocks = [b for b in scene.blocks if b.kind == "chart"]
    bad_ratio, missing = [], []
    for b in chart_blocks:
        p = plan["placements"][b.id]
        f = CHARTS / f"{b.id}.svg"
        if not f.exists():
            missing.append(b.id)
            continue
        head = f.read_text(encoding="utf-8")[:400]
        mw = re.search(r'width="(\d+)"', head)
        mh = re.search(r'height="(\d+)"', head)
        if not (mw and mh):
            missing.append(b.id)
            continue
        svg_ratio = int(mw.group(1)) / int(mh.group(1))
        slot_ratio = p["w_mm"] / p["h_mm"]
        if abs(svg_ratio - slot_ratio) / slot_ratio > 0.02:
            bad_ratio.append(f"{b.id}: SVG {svg_ratio:.3f} vs 槽位 {slot_ratio:.3f}")
    add("G1", "图表按槽位尺寸重绘（无拉伸变形）", "hard", not bad_ratio and not missing,
        "；".join(bad_ratio + [f"缺图：{m}" for m in missing]) or f"{len(chart_blocks)} 张图全部匹配")

    ratios = [plan["placements"][b.id]["w_mm"] / plan["placements"][b.id]["h_mm"]
              for b in chart_blocks]
    add("G2", "图表长宽比区间", "info", True,
        f"min {min(ratios):.2f} / max {max(ratios):.2f}（可读区间 1.1–3.4）")

    # ---- O 内容溢出 ----
    overflow = []
    for b in scene.blocks:
        p = plan["placements"][b.id]
        need = required_height(b, p["w_mm"])
        if need is not None and need > p["h_mm"] + 1.0:
            overflow.append(f"{b.id} 需要 {need:.1f}mm / 只有 {p['h_mm']:.1f}mm")
    add("O1", "文字与表格不溢出槽位", "hard", not overflow,
        "；".join(overflow) or "全部装得下（余量 ≥ 1mm）")

    # ---- T 标题孤行 ----
    orphan = []
    for c in scene.constraints_of("avoid_orphan"):
        bid = c["block"]
        p = plan["placements"][bid]
        page = next(pg for pg in plan["pages"] if pg["index"] == p["page"])
        last_row = page["rows"][-1]
        if any(x["id"] == bid for x in last_row["blocks"]):
            orphan.append(bid)
    add("T1", "章节标题不落页底", "hard", not orphan,
        "；".join(orphan) or "所有章节标题后面都有正文")

    # ---- N 数字回查 ----
    text = strip_dates(html_text(html))
    raw_set, wan_set = copymod.number_sets(fp)
    ungrounded = copymod.check_numbers(text, raw_set, wan_set)
    n_tokens = len([m for m in copymod.NUM_TOKEN.finditer(text)
                    if abs(float(m.group(1).replace(",", ""))) > 31 or m.group(2)])
    ctx = []
    for tok in ungrounded[:6]:
        i = text.find(tok)
        ctx.append(f"{tok} … {text[max(0, i - 18):i + len(tok) + 12]}")
    add("N1", "正文数字都能在事实包里查到出处", "hard", not ungrounded,
        f"{len(ungrounded)} 个可疑：" + "；".join(ctx) if ungrounded
        else f"{n_tokens} 个实体数字全部可回查")

    # ---- P PDF 质检 ----
    errs = render_pdf.check_pdf(pdf_path, expect_pages=len(plan["pages"]))
    info = {}
    try:
        info = render_pdf.pdf_info(pdf_path)
    except render_pdf.RenderError as e:
        errs.append(str(e))
    add("P1", "PDF 页数 = 版面计划页数", "hard",
        not any("页数" in e for e in errs), f"{info.get('pages')} 页 / 计划 {len(plan['pages'])} 页")
    add("P2", "PDF 纸张为 A4", "hard", not any("纸张" in e for e in errs),
        str(info.get("page_mm")))
    add("P3", "字体已内嵌", "hard", not any("字体" in e for e in errs),
        f"{info.get('embedded_font_files')} 个字体文件；{', '.join(info.get('fonts', [])[:4])}")
    add("P4", "PDF 非空白", "hard", not any("空白" in e for e in errs),
        f"{info.get('size_bytes', 0) / 1024:.0f} KB")

    # ---- H HTML 结构 ----
    n_pages = html.count('<div class="page"')
    n_blocks = html.count('class="blk ')
    add("H1", "HTML 页数 = 版面计划页数", "hard", n_pages == len(plan["pages"]),
        f"{n_pages} / {len(plan['pages'])}")
    add("H2", "HTML 块数 = DSL 块数", "hard", n_blocks == len(scene.blocks),
        f"{n_blocks} / {len(scene.blocks)}")

    # ---- R 可复现 ----
    again = layout.solve(scene)
    same = json.dumps(again, ensure_ascii=False, sort_keys=True) == \
        json.dumps(plan, ensure_ascii=False, sort_keys=True)
    add("R1", "同一份 DSL 再解一次，结果完全一致", "hard", same,
        "逐字节相同" if same else "两次求解结果不同（求解器不够确定）")

    # ---- 基线对比 ----
    greedy = layout.solve_greedy(scene)
    g_hard = [v for v in layout.check_plan(scene, greedy) if v["hard"]]
    baseline = {
        "solver": {"pages": plan["metrics"]["pages"], "fill_avg": plan["metrics"]["fill_avg"],
                   "fill_min": plan["metrics"]["fill_min"], "fill_std": plan["metrics"]["fill_std"],
                   "objective": plan["metrics"]["objective"]},
        "greedy": {"pages": greedy["metrics"]["pages"], "fill_avg": greedy["metrics"]["fill_avg"],
                   "fill_min": greedy["metrics"]["fill_min"], "fill_std": greedy["metrics"]["fill_std"],
                   "objective": greedy["metrics"]["objective"]},
        "greedy_hard_violations": len(g_hard),
    }

    hard_total = [c for c in checks if c["level"] == "hard"]
    passed = [c for c in hard_total if c["passed"]]
    result = {
        "month": month,
        "checks": checks,
        "hard_total": len(hard_total),
        "hard_passed": len(passed),
        "all_passed": len(passed) == len(hard_total),
        "metrics": plan["metrics"],
        "baseline": baseline,
        "pages": [{"index": p["index"], "fill": p["fill"],
                   "blocks": [b["id"] for r in p["rows"] for b in r["blocks"]]}
                  for p in plan["pages"]],
        "ungrounded": ungrounded,
        "pdf": {k: (str(v) if isinstance(v, Path) else v) for k, v in info.items()},
    }
    return result


# --------------------------------------------------------------------- 输出
def to_markdown(r: dict) -> str:
    m = r["metrics"]
    b = r["baseline"]
    lines = [
        f"# 出稿评测 · {r['month']}",
        "",
        f"**结论：硬性检查 {r['hard_passed']}/{r['hard_total']} 通过"
        f"{'（全部通过）' if r['all_passed'] else '（有不通过项）'}**",
        "",
        f"- 版面：{m['pages']} 页，填充率 平均 {m['fill_avg']:.1%} / 最低 {m['fill_min']:.1%} / "
        f"波动 {m['fill_std']:.1%}",
        f"- 求解目标值：{m['objective']:.1f}（越小越好）",
        "",
        "## 检查明细",
        "",
        "| 编号 | 检查项 | 级别 | 结果 | 说明 |",
        "|---|---|---|---|---|",
    ]
    for c in r["checks"]:
        mark = "✅" if c["passed"] else ("❌" if c["level"] == "hard" else "⚠️")
        if c["level"] == "info":
            mark = "ℹ️"
        detail = c["detail"].replace("|", "/")
        lines.append(f"| {c['id']} | {c['name']} | {c['level']} | {mark} | {detail} |")

    lines += [
        "",
        "## 约束求解 vs 贪心装箱（同一组块）",
        "",
        "| 指标 | 约束求解（DP） | 贪心装箱 | 差异 |",
        "|---|---|---|---|",
        f"| 页数 | {b['solver']['pages']} | {b['greedy']['pages']} | "
        f"{b['solver']['pages'] - b['greedy']['pages']:+d} |",
        f"| 平均填充率 | {b['solver']['fill_avg']:.1%} | {b['greedy']['fill_avg']:.1%} | "
        f"{(b['solver']['fill_avg'] - b['greedy']['fill_avg']) * 100:+.1f}pp |",
        f"| 最低填充率 | {b['solver']['fill_min']:.1%} | {b['greedy']['fill_min']:.1%} | "
        f"{(b['solver']['fill_min'] - b['greedy']['fill_min']) * 100:+.1f}pp |",
        f"| 填充率波动 σ | {b['solver']['fill_std']:.1%} | {b['greedy']['fill_std']:.1%} | "
        f"{(b['solver']['fill_std'] - b['greedy']['fill_std']) * 100:+.1f}pp |",
        f"| 目标值 | {b['solver']['objective']:.1f} | {b['greedy']['objective']:.1f} | "
        f"{b['solver']['objective'] - b['greedy']['objective']:+.1f} |",
        f"| 硬约束违规 | 0 | {b['greedy_hard_violations']} | |",
        "",
        "## 页面构成",
        "",
        "| 页 | 填充率 | 块 |",
        "|---|---|---|",
    ]
    for p in r["pages"]:
        lines.append(f"| {p['index']} | {p['fill']:.1%} | {', '.join(p['blocks'])} |")
    lines += ["", f"> 数字回查：{len(r['ungrounded'])} 个数字查不到出处。" if r["ungrounded"]
              else "> 数字回查：正文全部数字均可在事实包中找到同值字段。", ""]
    return "\n".join(lines)


def main(month: str = "2025-10") -> dict:
    r = evaluate(month)
    md = to_markdown(r)
    (OUT / f"eval_{month}.md").write_text(md, encoding="utf-8")
    (OUT / f"eval_{month}.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print("=" * 74)
    print(f"出稿评测 · {month}")
    print("=" * 74)
    for c in r["checks"]:
        mark = "PASS" if c["passed"] else ("FAIL" if c["level"] == "hard" else "WARN")
        if c["level"] == "info":
            mark = "INFO"
        print(f"  [{mark}] {c['id']:3s} {c['name']}")
        if not c["passed"] or c["level"] == "info":
            print(f"          {c['detail'][:150]}")
    m = r["metrics"]
    b = r["baseline"]
    print("-" * 74)
    print(f"版面   : {m['pages']} 页｜填充率 平均 {m['fill_avg']:.1%} 最低 {m['fill_min']:.1%} "
          f"σ {m['fill_std']:.1%}")
    print(f"对照   : 贪心装箱 {b['greedy']['pages']} 页｜最低填充 {b['greedy']['fill_min']:.1%}｜"
          f"目标值 {b['greedy']['objective']:.1f} vs 求解器 {m['objective']:.1f}")
    print(f"硬性   : {r['hard_passed']}/{r['hard_total']} 通过")
    print(f"报告   : outputs/eval_{month}.md")
    return r


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0] if args else "2025-10")
