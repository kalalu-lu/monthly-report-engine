"""
HTML 出稿（Stage B 第四步之一）

版面求解器给的是**毫米级绝对坐标**，所以 HTML 这里不做"流式排版"，只做一件事：
把每个块放到 plan 指定的位置（position: absolute + mm 单位），并给一套打印样式。
这样浏览器就不再有"自己决定怎么断页"的权力——断页已经由求解器算好了，
HTML 与 PDF 的版面才有可能一致（这也是后面 PDF 页数能校验的前提）。

视觉规范（"咨询报告"风格）：
  · 字号阶梯 23 / 12.5 / 10 / 9.2 / 8.4 / 7.6 pt，只用这六档，不随手加字号
  · 只有三种强调色：主色 navy、警示 red、提示 amber；其余全用灰阶
  · 数字一律 tabular-nums 右对齐；正文左对齐、行高 1.72
  · 卡片/表格/提示框统一 1.2mm 圆角、0.5pt 描边，避免"贴上去"的感觉
  · 页脚固定：左侧跑马灯 + 右侧页码，一条 0.5pt 细线隔开

约定：
  - 一页 = 一个 .page div，尺寸严格等于纸张，page-break-after: always
  - 图表由调用方以 inline HTML/SVG 传入（图要按版面槽位尺寸重新渲染）
  - 页眉页脚由渲染器统一画，不占内容区，因此不影响求解结果
"""
from __future__ import annotations

import html as _html
from pathlib import Path

from src import dsl

PT = dsl.PT_TO_MM


def esc(s) -> str:
    return _html.escape(str(s), quote=True)


def _mm(v: float) -> str:
    return f"{v:.2f}mm"


def _style(place: dict) -> str:
    return (f"left:{_mm(place['x_mm'])};top:{_mm(place['y_mm'])};"
            f"width:{_mm(place['w_mm'])};height:{_mm(place['h_mm'])}")


# --------------------------------------------------------------------- CSS
def css(scene: dsl.Scene) -> str:
    t = scene.theme
    g = dsl.geometry(scene.page)
    return f"""
@page {{ size: {g.page_w}mm {g.page_h}mm; margin: 0; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: #fff; }}
body {{
  font-family: {t['font']}; color: {t['ink']};
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
  font-variant-numeric: tabular-nums; font-feature-settings: "tnum" 1;
  text-rendering: geometricPrecision;
}}
.page {{
  position: relative; width: {g.page_w}mm; height: {g.page_h}mm;
  overflow: hidden; background: #fff;
  page-break-after: always; break-after: page;
}}
.page:last-of-type {{ page-break-after: auto; break-after: auto; }}
.blk {{ position: absolute; overflow: hidden; }}

/* ================= 页面家具（不占内容区，由渲染器画） ================= */
.brand {{ position: absolute; background: {t['primary']}; }}
.brand-dot {{ position: absolute; background: {t['accent']}; border-radius: 50%; }}
.foot-rule {{ position: absolute; height: 0; border-top: 0.5pt solid #e3e7ec; }}
.foot-text {{ position: absolute; font-size: 7.4pt; color: {t['sub']}; letter-spacing: .02em; }}
.foot-page {{ position: absolute; font-size: 7.4pt; color: {t['primary']};
  font-weight: 700; letter-spacing: .06em; }}

/* ================= 封面标题 ================= */
.kicker {{ font-size: 8pt; letter-spacing: .24em; color: {t['sub']};
  font-weight: 600; margin-bottom: 2.6mm; }}
h1 {{ font-size: 23pt; line-height: 1.2; margin: 0; letter-spacing: -.015em;
  font-weight: 700; color: #101418; }}
.title .sub {{ font-size: 9pt; color: {t['sub']}; margin-top: 2.4mm; line-height: 1.66; }}
.title .bar {{ position: absolute; left: 0; bottom: 0; width: 24mm; height: 1.3mm;
  background: {t['primary']}; }}
.title .bar::after {{ content: ""; position: absolute; right: -4.5mm; top: 0;
  width: 3mm; height: 1.3mm; background: {t['accent']}; }}

/* ================= 章节标题 ================= */
.section {{ display: flex; align-items: center; gap: 2.6mm;
  border-bottom: 0.5pt solid #e3e7ec; padding-bottom: 2.2mm; }}
.section .no {{ flex: none; display: inline-block; min-width: 6.2mm; height: 6.2mm;
  line-height: 6.2mm; text-align: center; background: {t['primary']}; color: #fff;
  font-size: 8.4pt; font-weight: 700; border-radius: 1.1mm; letter-spacing: .02em; }}
.section .t {{ font-size: 12.5pt; font-weight: 700; flex: none; white-space: nowrap;
  color: #14181d; letter-spacing: -.005em; }}
.section .note {{ font-size: 8pt; color: {t['sub']}; margin-left: auto;
  white-space: nowrap; overflow: hidden; letter-spacing: .02em; }}

/* ================= KPI 卡 ================= */
.kpi {{ background: #f7f9fb; border: 0.5pt solid #e6ebf1; border-radius: 1.4mm;
  padding: 2.4mm 2.8mm 2.2mm; }}
.kpi::before {{ content: ""; position: absolute; left: 0; top: 2.4mm; bottom: 2.4mm;
  width: 1.6mm; background: {t['primary']}; border-radius: 0 1mm 1mm 0; }}
.kpi .lab {{ font-size: 7.8pt; color: {t['sub']}; letter-spacing: .04em;
  padding-left: 2.4mm; }}
.kpi .val {{ font-size: 14.6pt; font-weight: 700; line-height: 1.14; margin-top: .6mm;
  padding-left: 2.4mm; color: #12161b; letter-spacing: -.02em; white-space: nowrap; }}
.kpi .u, .kpi .u-in {{ display: block; font-size: 7.1pt; font-weight: 500;
  color: {t['sub']}; margin: .5mm 0 0 2.4mm; letter-spacing: .02em; white-space: nowrap; }}
.kpi .delta {{ display: inline-block; font-size: 6.9pt; margin-top: 1.1mm;
  margin-left: 2.4mm; padding: .28mm 1.1mm; border-radius: .9mm; white-space: nowrap;
  background: #eef1f5; color: {t['sub']}; letter-spacing: 0; }}
.kpi .delta.up {{ background: #e8f3ee; color: {t['green']}; }}
.kpi .delta.down {{ background: #fbecea; color: {t['accent']}; }}
.kpi .delta.warn {{ background: #fbf3e2; color: {t['amber']}; }}
.kpi .delta.up::before {{ content: "▲ "; font-size: 6pt; }}
.kpi .delta.down::before {{ content: "▼ "; font-size: 6pt; }}
.kpi .delta.warn::before {{ content: "● "; font-size: 5.4pt; }}

/* ================= 图表 ================= */
.chart svg {{ display: block; width: 100%; height: 100%; }}
.chart .cap {{ position: absolute; left: 0; bottom: 0; font-size: 7.4pt; color: {t['sub']}; }}

/* ================= 结论 / 提示框 ================= */
.callout {{ background: #f7f9fb; border: 0.5pt solid #e6ebf1;
  border-left: 2.6pt solid {t['primary']}; border-radius: 1.2mm;
  padding: 3mm 4mm 3mm 4.2mm; }}
.callout .ct {{ font-size: 8pt; font-weight: 700; color: {t['primary']};
  letter-spacing: .14em; margin-bottom: 1.8mm; }}
.callout .ct::before {{ content: ""; display: inline-block; width: 1.5mm; height: 1.5mm;
  background: {t['primary']}; margin-right: 1.6mm; vertical-align: .1mm; }}
.callout .cb {{ font-size: 9.8pt; line-height: 1.72; color: #1b2128; }}
.callout .items {{ margin: 1.6mm 0 0; padding-left: 4.2mm; }}
.callout .items li {{ font-size: 8.8pt; line-height: 1.7; margin-bottom: .6mm; }}
.callout.high {{ border-left-color: {t['accent']}; }}
.callout.high .ct {{ color: {t['accent']}; }}
.callout.high .ct::before {{ background: {t['accent']}; }}

/* ================= 正文 ================= */
.text {{ font-size: 9.4pt; line-height: 1.74; color: #1f242b; }}
.text p {{ margin: 0 0 1.7mm; }}
.text p:last-child {{ margin-bottom: 0; }}

/* ================= 表格 ================= */
table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
thead th {{ font-size: 7.8pt; font-weight: 700; color: #4a5b6b; text-align: left;
  background: #eef3f8; padding: 1.3mm 2mm; letter-spacing: .04em;
  border-bottom: 0.7pt solid #cfdae6; }}
tbody td {{ font-size: 8.3pt; line-height: 1.45; padding: 1.15mm 2mm;
  vertical-align: top; border-bottom: 0.4pt solid #eceff3; word-break: break-word;
  color: #232a31; }}
tbody tr:nth-child(even) td {{ background: #fafbfc; }}
tbody tr:last-child td {{ border-bottom: none; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.lv {{ display: inline-block; font-weight: 700; font-size: 7.4pt; line-height: 1.5;
  padding: .2mm 1.4mm; border-radius: .9mm; letter-spacing: .04em; }}
.lv.high {{ color: #fff; background: {t['accent']}; }}
.lv.mid {{ color: #6b4a06; background: #f7e3bd; }}
.lv.low {{ color: #4b5563; background: #e8ebef; }}

/* ================= 尾注 ================= */
.footer-note {{ font-size: 7.4pt; color: {t['sub']}; line-height: 1.62; }}
.blk.footer {{ font-size: 7.4pt; color: {t['sub']}; line-height: 1.62; }}
"""


# --------------------------------------------------------------------- 块渲染
def _kpi(b: dsl.Block, c: dict) -> str:
    tone = str(c.get("tone", ""))
    u_cls = "u-in" if c.get("inline_unit") else "u"
    return (f'<div class="lab">{esc(c.get("label", b.title))}</div>'
            f'<div class="val">{esc(c.get("value", ""))}'
            f'<span class="{u_cls}">{esc(c.get("unit", ""))}</span></div>'
            f'<div class="delta {esc(tone)}">{esc(c.get("delta", ""))}</div>')


LEVEL_CLASS = {"高": "high", "中": "mid", "低": "low"}


def _table(b: dsl.Block, c: dict) -> str:
    cols = c.get("columns") or []
    rows = c.get("rows") or []
    weights = [float(x.get("width", 1)) for x in cols] or [1.0]
    total = sum(weights)
    colgroup = "".join(f'<col style="width:{w / total * 100:.2f}%">' for w in weights)
    head = "".join(
        f'<th class="{"num" if x.get("align") == "right" else ""}">{esc(x.get("label", ""))}</th>'
        for x in cols)
    heights = c.get("row_heights") or []
    body = []
    for i, row in enumerate(rows):
        cells = []
        for j, x in enumerate(cols):
            v = row[j] if j < len(row) else ""
            cls = "num" if x.get("align") == "right" else ""
            content = esc(v)
            if j == 0 and c.get("level_col"):
                content = f'<span class="lv {LEVEL_CLASS.get(str(v), "")}">{esc(v)}</span>'
                cls = ""
            cells.append(f'<td class="{cls}">{content}</td>')
        style = f' style="height:{heights[i + 1]:.2f}mm"' if i + 1 < len(heights) else ""
        body.append(f"<tr{style}>{''.join(cells)}</tr>")
    return (f'<table><colgroup>{colgroup}</colgroup><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


def _footer(b: dsl.Block, c: dict) -> str:
    return " ".join(f'<div>{esc(x)}</div>' for x in (c.get("lines") or []))


def _callout(b: dsl.Block, c: dict) -> str:
    items = "".join(f"<li>{esc(x)}</li>" for x in (c.get("bullets") or []))
    ul = f'<ul class="items">{items}</ul>' if items else ""
    body = esc(c.get("body", ""))
    return (f'<div class="ct">{esc(c.get("title", b.title))}</div>'
            f'<div class="cb">{body}</div>{ul}')


def block_inner(b: dsl.Block, c: dict, inline: dict[str, str]) -> str:
    kind = b.kind
    if kind == "title":
        return (f'<div class="kicker">{esc(c.get("kicker", ""))}</div>'
                f"<h1>{esc(b.title)}</h1>"
                f'<div class="sub">{esc(c.get("subtitle", ""))}</div>'
                f'<div class="bar"></div>')
    if kind == "subtitle":
        return f'<div class="sub" style="font-size:9pt;color:inherit">{esc(b.title)}</div>'
    if kind == "section":
        return (f'<div class="no">{esc(c.get("no", ""))}</div>'
                f'<div class="t">{esc(b.title)}</div>'
                f'<div class="note">{esc(c.get("note", ""))}</div>')
    if kind == "kpi":
        return _kpi(b, c)
    if kind == "chart":
        return inline.get(b.id, "")
    if kind == "table":
        return _table(b, c)
    if kind == "callout":
        return _callout(b, c)
    if kind == "text":
        paras = c.get("paras") or ([b.title] if b.title else [])
        return "".join(f"<p>{esc(p)}</p>" for p in paras)
    if kind == "footer":
        return _footer(b, c)
    return ""


# --------------------------------------------------------------------- 页面
def _page_furniture(scene: dsl.Scene, page_no: int, total: int) -> str:
    g = dsl.geometry(scene.page)
    t = scene.theme
    left = g.margin["left"]
    y_rule = g.page_h - g.margin["bottom"] + 3.2
    head = scene.meta.get("running_head", "")
    page_txt = f"{page_no:02d} / {total:02d}"
    foot = (
        f'<div class="foot-rule" style="left:{_mm(left)};top:{_mm(y_rule)};'
        f'width:{_mm(g.content_w)}"></div>'
        f'<div class="foot-text" style="left:{_mm(left)};top:{_mm(y_rule + 1.5)}">'
        f'{esc(head)}</div>'
        f'<div class="foot-page" style="right:{_mm(g.margin["right"])};'
        f'top:{_mm(y_rule + 1.4)}">{esc(page_txt)}</div>'
    )
    return foot


def render(scene: dsl.Scene, plan: dict, inline: dict[str, str] | None = None,
           doc_title: str | None = None) -> str:
    inline = inline or {}
    total = len(plan["pages"])
    title = doc_title or scene.meta.get("title") or "经营月报"
    by_page: dict[int, list[dsl.Block]] = {}
    for b in scene.blocks:
        p = plan["placements"].get(b.id)
        if p:
            by_page.setdefault(p["page"], []).append(b)

    pages_html = []
    for pg in plan["pages"]:
        n = pg["index"]
        blocks = sorted(by_page.get(n, []), key=lambda b: (plan["placements"][b.id]["y_mm"],
                                                           plan["placements"][b.id]["x_mm"]))
        inner = []
        for b in blocks:
            p = plan["placements"][b.id]
            body = block_inner(b, b.content, inline)
            if not body:
                continue
            inner.append(f'<div class="blk {b.kind}" data-id="{esc(b.id)}" '
                         f'style="{_style(p)}">{body}</div>')
        pages_html.append(
            f'<div class="page" data-page="{n}">\n  ' + "\n  ".join(inner)
            + "\n  " + _page_furniture(scene, n, total) + "\n</div>")

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{esc(title)}</title>
<style>{css(scene)}</style>
</head>
<body>
{chr(10).join(pages_html)}
</body>
</html>
"""


def write(scene: dsl.Scene, plan: dict, path: str | Path,
          inline: dict[str, str] | None = None, doc_title: str | None = None) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render(scene, plan, inline, doc_title), encoding="utf-8")
    return p
