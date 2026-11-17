"""
SVG 图表渲染器（零依赖，纯手写）

为什么自己写：本机 Python 装 pandas 时 C 扩展被系统应用控制策略拦截，
matplotlib 同样有风险；手写 SVG 的好处是——不依赖任何绘图库、中文不需要额外字体配置、
矢量图放大不虚、每个像素都可控。

支持：折线（含预算对比）、纵向/横向条形、环形占比、瀑布图（差异分解）、子弹图。
所有函数返回完整的 <svg> 字符串，可直接内联进 HTML。
"""
from __future__ import annotations

import math

FONT = "'Microsoft YaHei UI','Microsoft YaHei','PingFang SC','Segoe UI',sans-serif"

C = {
    "ink": "#14181d",
    "sub": "#7c8798",
    "grid": "#eef1f4",
    "axis": "#c9d0d9",
    "primary": "#1f4e79",
    "primary_light": "#dce9f5",
    "accent": "#c0392b",
    "accent_light": "#f6dcd8",
    "green": "#2e7d5b",
    "amber": "#c98a16",
    "bg": "#ffffff",
    "panel": "#f7f8fa",
}


def esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def text_w(s: str, size: float) -> float:
    """粗估文字宽度：CJK 按 1em，其他按 0.55em。"""
    w = 0.0
    for ch in str(s):
        w += size * (1.0 if ord(ch) > 127 else 0.55)
    return w


def fmt_wan(v: float) -> str:
    if abs(v) >= 1e8:
        return f"{v / 1e8:.2f}亿"
    if abs(v) >= 1e4:
        return f"{v / 1e4:.0f}万"
    return f"{v:.0f}"


def fmt_money(v: float) -> str:
    return f"{v:,.0f}"


def nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi == lo:
        hi = lo + 1
    span = hi - lo
    raw = span / max(1, n)
    mag = 10 ** (len(str(int(abs(raw)))) - 1) if raw >= 1 else 1
    for m in (1, 2, 2.5, 5, 10):
        step = mag * m
        if span / step <= n + 1:
            break
    start = (lo // step) * step
    ticks = []
    v = start
    while v <= hi + step * 0.5:
        if v >= lo - step * 0.5:
            ticks.append(round(v, 10))
        v += step
    return ticks


class Scale:
    def __init__(self, d0: float, d1: float, r0: float, r1: float):
        self.d0, self.d1, self.r0, self.r1 = d0, d1, r0, r1

    def __call__(self, v: float) -> float:
        if self.d1 == self.d0:
            return (self.r0 + self.r1) / 2
        return self.r0 + (v - self.d0) / (self.d1 - self.d0) * (self.r1 - self.r0)


def _open(w: int, h: int) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="{FONT}">',
        f'<rect width="{w}" height="{h}" fill="{C["bg"]}"/>',
    ]


def _title(parts: list[str], title: str, subtitle: str, w: int) -> None:
    parts.append(f'<text x="0" y="16" font-size="14.5" font-weight="700" fill="{C["ink"]}" letter-spacing="-.01em">{esc(title)}</text>')
    if subtitle:
        parts.append(f'<text x="0" y="34" font-size="11.5" fill="{C["sub"]}">{esc(subtitle)}</text>')


def line_chart(title: str, subtitle: str, labels: list[str], series: list[dict],
               width: int = 720, height: int = 300, y_fmt=fmt_wan,
               value_suffix: str = "") -> str:
    """series: [{'name','values','color','dash'}...]"""
    w, h = width, height
    ml, mr, mt, mb = 62, 20, 80, 38
    vals = [v for s in series for v in s["values"] if v is not None]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.12 or abs(hi) * 0.1 or 1
    y = Scale(lo - pad, hi + pad, h - mb, mt)
    xs = Scale(0, len(labels) - 1, ml + 10, w - mr)
    parts = _open(w, h)
    _title(parts, title, subtitle, w)

    # 图例（放在副标题下方单独一行，避免与标题区重叠）
    lx = 0
    for s in series:
        dash = ' stroke-dasharray="5 3"' if s.get("dash") else ""
        parts.append(f'<line x1="{lx}" y1="{mt - 22}" x2="{lx + 16}" y2="{mt - 22}" '
                     f'stroke="{s.get("color", C["primary"])}" stroke-width="2.4"{dash}/>')
        parts.append(f'<text x="{lx + 21}" y="{mt - 18}" font-size="11" fill="{C["sub"]}">{esc(s["name"])}</text>')
        lx += 24 + text_w(s["name"], 11) + 20

    for t in nice_ticks(lo - pad, hi + pad, 5):
        yy = y(t)
        parts.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{w - mr}" y2="{yy:.1f}" stroke="{C["grid"]}" stroke-width="1"/>')
        parts.append(f'<text x="{ml - 8}" y="{yy + 4:.1f}" text-anchor="end" font-size="10.5" fill="{C["sub"]}">{esc(y_fmt(t))}</text>')

    step = max(1, math.ceil(len(labels) * (max(text_w(str(l), 10.5) for l in labels) + 9)
                            / max(1.0, (w - mr) - (ml + 10))))
    for i, lab in enumerate(labels):
        if i % step and i != len(labels) - 1:
            continue
        parts.append(f'<text x="{xs(i):.1f}" y="{h - mb + 17}" text-anchor="middle" font-size="10.5" fill="{C["sub"]}">{esc(lab)}</text>')

    for s in series:
        pts = " ".join(f"{xs(i):.1f},{y(v):.1f}" for i, v in enumerate(s["values"]) if v is not None)
        dash = f' stroke-dasharray="{s["dash"]}"' if s.get("dash") else ""
        if s.get("area"):
            first = next(i for i, v in enumerate(s["values"]) if v is not None)
            last = len(s["values"]) - 1 - next(i for i, v in enumerate(reversed(s["values"])) if v is not None)
            parts.append(
                f'<path d="M {xs(first):.1f},{h - mb} L {pts.replace(" ", " L ")} L {xs(last):.1f},{h - mb} Z" '
                f'fill="{s.get("color", C["primary"])}" opacity="0.10"/>')
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{s.get("color", C["primary"])}" '
                     f'stroke-width="{s.get("width", 2.4)}" stroke-linejoin="round" stroke-linecap="round"{dash}/>')
        if s.get("dots"):
            for i, v in enumerate(s["values"]):
                if v is not None:
                    parts.append(f'<circle cx="{xs(i):.1f}" cy="{y(v):.1f}" r="3" fill="{s.get("color", C["primary"])}"/>')

    parts.append("</svg>")
    return "".join(parts)


def bar_chart(title: str, subtitle: str, labels: list[str], values: list[float],
              width: int = 720, height: int = 300, colors: list[str] | None = None,
              y_fmt=fmt_wan, value_fmt=None, target_line: float | None = None,
              target_label: str = "") -> str:
    w, h = width, height
    ml, mr, mt, mb = 58, 16, 56, 40
    hi = max(max(values), target_line or 0)
    lo = min(0, min(values))
    y = Scale(lo, hi * 1.12 or 1, h - mb, mt)
    parts = _open(w, h)
    _title(parts, title, subtitle, w)

    for t in nice_ticks(lo, hi * 1.12, 5):
        yy = y(t)
        parts.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{w - mr}" y2="{yy:.1f}" stroke="{C["grid"]}"/>')
        parts.append(f'<text x="{ml - 8}" y="{yy + 4:.1f}" text-anchor="end" font-size="10.5" fill="{C["sub"]}">{esc(y_fmt(t))}</text>')

    n = len(values)
    slot = (w - mr - ml) / max(1, n)
    bw = min(46, slot * 0.56)
    for i, v in enumerate(values):
        cx = ml + slot * (i + 0.5)
        y0, y1 = y(0), y(v)
        fill = (colors[i] if colors else C["primary"])
        parts.append(f'<rect x="{cx - bw / 2:.1f}" y="{min(y0, y1):.1f}" width="{bw:.1f}" '
                     f'height="{abs(y1 - y0):.1f}" rx="3" fill="{fill}"/>')
        lab = value_fmt(v) if value_fmt else y_fmt(v)
        parts.append(f'<text x="{cx:.1f}" y="{min(y0, y1) - 6:.1f}" text-anchor="middle" font-size="10.5" '
                     f'font-weight="600" fill="{C["ink"]}">{esc(lab)}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{h - mb + 16}" text-anchor="middle" font-size="10.5" fill="{C["sub"]}">{esc(labels[i])}</text>')

    if target_line is not None:
        yy = y(target_line)
        parts.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{w - mr}" y2="{yy:.1f}" stroke="{C["accent"]}" '
                     f'stroke-width="1.6" stroke-dasharray="6 4"/>')
        if target_label:
            parts.append(f'<text x="{w - mr}" y="{yy - 6:.1f}" text-anchor="end" font-size="11" '
                         f'fill="{C["accent"]}">{esc(target_label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def hbar_chart(title: str, subtitle: str, labels: list[str], values: list[float],
               width: int = 720, height: int = 320, bar_colors: list[str] | None = None,
               note_fmt=None, x_fmt=fmt_wan, vmax: float | None = None,
               note_w: float = 0.0) -> str:
    """note_w > 0 时，右侧留出固定宽度的注释列，注释左对齐、不会随条形长度漂移或出界。"""
    w, h = width, height
    ml, mr, mt, mb = 78, (16 if note_w else 96), 56, 26
    vmax = vmax or (max(values) * 1.15 or 1)
    plot_right = w - mr - note_w
    x = Scale(0, vmax, ml, plot_right)
    n = len(values)
    slot = (h - mt - mb) / max(1, n)
    bh = min(26, slot * 0.62)
    parts = _open(w, h)
    _title(parts, title, subtitle, w)

    for t in nice_ticks(0, vmax, 4):
        xx = x(t)
        parts.append(f'<line x1="{xx:.1f}" y1="{mt}" x2="{xx:.1f}" y2="{h - mb}" stroke="{C["grid"]}"/>')
        parts.append(f'<text x="{xx:.1f}" y="{h - mb + 15}" text-anchor="middle" font-size="10" fill="{C["sub"]}">{esc(x_fmt(t))}</text>')

    for i, v in enumerate(values):
        cy = mt + slot * (i + 0.5)
        parts.append(f'<rect x="{ml}" y="{cy - bh / 2:.1f}" width="{max(1, x(v) - ml):.1f}" '
                     f'height="{bh:.1f}" rx="3" fill="{(bar_colors[i] if bar_colors else C["primary"])}"/>')
        parts.append(f'<text x="{ml - 10}" y="{cy + 4:.1f}" text-anchor="end" font-size="11.5" fill="{C["ink"]}">{esc(labels[i])}</text>')
        note = note_fmt(i, v) if note_fmt else x_fmt(v)
        nx = plot_right + 10 if note_w else x(v) + 8
        parts.append(f'<text x="{nx:.1f}" y="{cy + 4:.1f}" font-size="10.5" fill="{C["sub"]}">{esc(note)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def donut_chart(title: str, subtitle: str, labels: list[str], values: list[float],
                width: int = 420, height: int = 300, colors: list[str] | None = None) -> str:
    import math
    w, h = width, height
    parts = _open(w, h)
    _title(parts, title, subtitle, w)
    cx, cy, r_out, r_in = 108, (h + 40) / 2, 82, 48
    total = sum(values) or 1
    palette = colors or ["#1f4e79", "#2e75b6", "#5b9bd5", "#9dc3e6", "#c9a227", "#7f8c8d", "#b0b7bf", "#d9dee3"]
    a0 = -90.0
    for i, v in enumerate(values):
        ang = v / total * 360
        a1 = a0 + ang
        large = 1 if ang > 180 else 0
        p0 = (cx + r_out * math.cos(math.radians(a0)), cy + r_out * math.sin(math.radians(a0)))
        p1 = (cx + r_out * math.cos(math.radians(a1)), cy + r_out * math.sin(math.radians(a1)))
        q1 = (cx + r_in * math.cos(math.radians(a1)), cy + r_in * math.sin(math.radians(a1)))
        q0 = (cx + r_in * math.cos(math.radians(a0)), cy + r_in * math.sin(math.radians(a0)))
        d = (f"M {p0[0]:.2f},{p0[1]:.2f} A {r_out},{r_out} 0 {large} 1 {p1[0]:.2f},{p1[1]:.2f} "
             f"L {q1[0]:.2f},{q1[1]:.2f} A {r_in},{r_in} 0 {large} 0 {q0[0]:.2f},{q0[1]:.2f} Z")
        parts.append(f'<path d="{d}" fill="{palette[i % len(palette)]}" stroke="#fff" stroke-width="1.5"/>')
        a0 = a1

    parts.append(f'<text x="{cx}" y="{cy - 4}" text-anchor="middle" font-size="10.5" fill="{C["sub"]}">合计</text>')
    parts.append(f'<text x="{cx}" y="{cy + 14}" text-anchor="middle" font-size="14" font-weight="600" fill="{C["ink"]}">{esc(fmt_wan(total))}</text>')

    ly = 74
    for i, lab in enumerate(labels):
        pct = values[i] / total * 100
        parts.append(f'<rect x="{218}" y="{ly - 8}" width="9" height="9" rx="2" fill="{palette[i % len(palette)]}"/>')
        parts.append(f'<text x="{233}" y="{ly}" font-size="11" fill="{C["ink"]}">{esc(lab)}</text>')
        parts.append(f'<text x="{w - 12}" y="{ly}" text-anchor="end" font-size="11" fill="{C["sub"]}">{pct:.1f}%</text>')
        ly += 24
    parts.append("</svg>")
    return "".join(parts)


def waterfall_chart(title: str, subtitle: str, items: list[dict],
                    width: int = 720, height: int = 320, y_fmt=fmt_wan) -> str:
    """items: [{'name','value','kind'}]，kind ∈ total | delta"""
    w, h = width, height
    ml, mr, mt, mb = 66, 16, 56, 40
    running = 0.0
    bars = []
    for it in items:
        if it["kind"] == "total":
            bars.append((it["name"], 0.0, it["value"], it["kind"]))
            running = it["value"]
        else:
            start = running
            running += it["value"]
            bars.append((it["name"], start, running, it["kind"]))
    lo = min(0, min(min(a, b) for _, a, b, _ in bars))
    hi = max(max(a, b) for _, a, b, _ in bars)
    y = Scale(lo * 1.1, hi * 1.12, h - mb, mt)
    parts = _open(w, h)
    _title(parts, title, subtitle, w)

    for t in nice_ticks(lo * 1.1, hi * 1.12, 5):
        yy = y(t)
        parts.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{w - mr}" y2="{yy:.1f}" stroke="{C["grid"]}"/>')
        parts.append(f'<text x="{ml - 8}" y="{yy + 4:.1f}" text-anchor="end" font-size="10.5" fill="{C["sub"]}">{esc(y_fmt(t))}</text>')

    slot = (w - mr - ml) / len(bars)
    bw = min(64, slot * 0.52)
    for i, (name, a, b, kind) in enumerate(bars):
        cx = ml + slot * (i + 0.5)
        y0, y1 = y(a), y(b)
        if kind == "total":
            fill, lab = C["primary"], f"{b / 1e4:,.1f}万"
        else:
            fill = C["accent"] if b < a else C["green"]
            lab = ("+" if b > a else "−") + f"{abs(b - a) / 1e4:.2f}万"
        parts.append(f'<rect x="{cx - bw / 2:.1f}" y="{min(y0, y1):.1f}" width="{bw:.1f}" '
                     f'height="{max(2, abs(y1 - y0)):.1f}" rx="3" fill="{fill}"/>')
        parts.append(f'<text x="{cx:.1f}" y="{min(y0, y1) - 7:.1f}" text-anchor="middle" font-size="10.5" '
                     f'font-weight="600" fill="{C["ink"]}">{esc(lab)}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{h - mb + 16}" text-anchor="middle" font-size="10.5" fill="{C["sub"]}">{esc(name)}</text>')
        if i < len(bars) - 1:
            yn = y(b)
            parts.append(f'<line x1="{cx + bw / 2:.1f}" y1="{yn:.1f}" x2="{cx + slot - bw / 2:.1f}" y2="{yn:.1f}" '
                         f'stroke="{C["axis"]}" stroke-width="1" stroke-dasharray="3 3"/>')
    parts.append("</svg>")
    return "".join(parts)


def bullet_chart(title: str, subtitle: str, rows: list[dict],
                 width: int = 720, height: int = 260, x_fmt=fmt_wan) -> str:
    """rows: [{'name','actual','target'}]"""
    w, h = width, height
    ml, mr, mt, mb = 90, 90, 56, 26
    vmax = max(max(r["actual"], r["target"]) for r in rows) * 1.12
    x = Scale(0, vmax, ml, w - mr)
    slot = (h - mt - mb) / len(rows)
    bh = min(20, slot * 0.5)
    parts = _open(w, h)
    _title(parts, title, subtitle, w)
    for t in nice_ticks(0, vmax, 4):
        xx = x(t)
        parts.append(f'<line x1="{xx:.1f}" y1="{mt}" x2="{xx:.1f}" y2="{h - mb}" stroke="{C["grid"]}"/>')
        parts.append(f'<text x="{xx:.1f}" y="{h - mb + 15}" text-anchor="middle" font-size="10" fill="{C["sub"]}">{esc(x_fmt(t))}</text>')
    for i, r in enumerate(rows):
        cy = mt + slot * (i + 0.5)
        parts.append(f'<rect x="{ml}" y="{cy - bh / 2:.1f}" width="{x(r["target"]) - ml:.1f}" height="{bh:.1f}" '
                     f'rx="2" fill="{C["primary_light"]}"/>')
        over = r["actual"] >= r["target"]
        parts.append(f'<rect x="{ml}" y="{cy - bh / 4:.1f}" width="{x(r["actual"]) - ml:.1f}" height="{bh / 2:.1f}" '
                     f'rx="1.5" fill="{C["primary"] if over else C["amber"]}"/>')
        parts.append(f'<line x1="{x(r["target"]):.1f}" y1="{cy - bh / 2 - 3:.1f}" x2="{x(r["target"]):.1f}" '
                     f'y2="{cy + bh / 2 + 3:.1f}" stroke="{C["accent"]}" stroke-width="2"/>')
        parts.append(f'<text x="{ml - 10}" y="{cy + 4:.1f}" text-anchor="end" font-size="11.5" fill="{C["ink"]}">{esc(r["name"])}</text>')
        pct = r["actual"] / r["target"] * 100 if r["target"] else 0
        # 百分比统一放在右侧固定列，避免与目标线/条形末端重叠
        parts.append(f'<text x="{w - mr + 8}" y="{cy + 4:.1f}" font-size="11" '
                     f'font-weight="600" fill="{C["primary"] if over else C["amber"]}">{pct:.2f}%</text>')
    parts.append("</svg>")
    return "".join(parts)
