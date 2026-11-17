"""
版面 DSL（声明式）

一句话：**DSL 只描述"有什么、多大、占几列、哪些约束必须成立"，不描述"放在第几页第几行"。**
位置由 layout.py 的约束求解器算出来。

为什么不用 HTML/CSS 直接排：CSS 的排版结果是浏览器的黑箱，页断点由引擎决定，
既不可复现也不可解释；而作业要求"版面规划"是一个能讲清楚、能验收的环节。
所以这里先把版面抽象成带尺寸的块（block），把排版要求写成约束（constraint），
再由求解器给出坐标——同样的输入永远给出同样的版面，而且每个约束都能单独验证。

DSL 结构（JSON 友好，见 outputs/layout_*.json）：

    {
      "version": "1.0",
      "meta":   {"title": "...", "month": "2025-10"},
      "page":   {"size": "A4", "orientation": "portrait",
                 "margin": {"top": 16, "right": 15, "bottom": 14, "left": 15},
                 "columns": 12, "gutter": 6, "footer": 9},
      "solver": {"page_cost": 55, "fill_min": 0.78, "fill_max": 1.0,
                 "underfill_weight": 1400, "orphan_weight": 260},
      "blocks": [
        {"id": "cover", "kind": "title", "span": 12, "height": 24,
         "title": "…", "content": {...}},
        …
      ],
      "constraints": [
        {"type": "same_row",      "blocks": ["kpi1", "kpi2", …]},
        {"type": "keep_together", "blocks": ["t_head", "t_rows"], "mode": "page"},
        {"type": "avoid_orphan",  "block": "sec2"},
        {"type": "aspect",        "block": "chart1", "min": 1.6, "max": 3.4},
        {"type": "fill",          "min": 0.78, "max": 1.0},
        {"type": "max_pages",     "value": 3}
      ]
    }

块高度用毫米（mm），由调用方给出；文本块可以用 measure_text_height() 按
"宽度 + 字号 + 行高"估出来，避免写死高度导致溢出。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

PT_TO_MM = 25.4 / 72.0

# 纸张（mm）
PAGE_SIZES = {
    "A4": (210.0, 297.0),
    "A4_LANDSCAPE": (297.0, 210.0),
    "LETTER": (215.9, 279.4),
}

# 块类型默认高度（mm）——只是缺省值，DSL 里写了就以 DSL 为准
KIND_DEFAULT_HEIGHT = {
    "title": 22.0,
    "subtitle": 9.0,
    "section": 11.0,
    "kpi": 26.0,
    "chart": 64.0,
    "table": 40.0,
    "text": 24.0,
    "callout": 26.0,
    "footer": 10.0,
    "spacer": 6.0,
}

KINDS = set(KIND_DEFAULT_HEIGHT)

# 约束类型
CONSTRAINT_TYPES = {
    "same_row",      # 这些块必须同一行（横向并排，行高取最大值）
    "keep_together", # 这些块必须同一页（mode=page）——目前只支持 page
    "avoid_orphan",  # 这个块不能是某页的最后一行（典型：章节标题掉页底）
    "aspect",        # 块的长宽比必须落在区间内（图表被压扁会读不出来）
    "fill",          # 每页填充率区间（版面的软目标）
    "max_pages",     # 总页数上限
}

DEFAULT_THEME = {
    "ink": "#1a1a1a",
    "sub": "#6b7280",
    "rule": "#d6dbe1",
    "primary": "#1f4e79",
    "primary_light": "#dce9f5",
    "accent": "#c0392b",
    "amber": "#c98a16",
    "green": "#2e7d5b",
    "panel": "#f7f8fa",
    "font": "'Microsoft YaHei UI','Microsoft YaHei','PingFang SC','Segoe UI',sans-serif",
}


class SceneError(ValueError):
    """DSL 结构非法。消息里一次列出全部问题，便于一次改完。"""


# --------------------------------------------------------------------- 文本度量
def char_em(ch: str) -> float:
    """粗略字宽：中日韩全角按 1em，其余按 0.55em。与 svg.text_w 同一口径。"""
    return 1.0 if ord(ch) > 0x2E7F else 0.55


def text_width_mm(s: str, size_pt: float) -> float:
    return sum(char_em(c) for c in str(s)) * size_pt * PT_TO_MM


def wrap_lines(text: str, width_mm: float, size_pt: float) -> list[str]:
    """按字宽折行（中文按字断，英文按词尽量不拆）。"""
    out: list[str] = []
    for para in str(text).split("\n"):
        if not para:
            out.append("")
            continue
        line, w = "", 0.0
        limit = max(1.0, width_mm)
        for ch in para:
            cw = char_em(ch) * size_pt * PT_TO_MM
            if w + cw > limit and line:
                out.append(line)
                line, w = ch, cw
            else:
                line += ch
                w += cw
        if line:
            out.append(line)
    return out or [""]


def measure_text_height(text: str, width_mm: float, size_pt: float = 10.5,
                        line_height: float = 1.62, pad_mm: float = 5.0,
                        min_height: float = 10.0) -> float:
    """估算一段文字在给定宽度下的高度（mm），含上下内边距。"""
    lines = wrap_lines(text, max(1.0, width_mm - 4.0), size_pt)
    h = len(lines) * size_pt * line_height * PT_TO_MM + pad_mm
    return round(max(min_height, h), 1)


def measure_table_height(columns: list[dict], rows: list[list[str]],
                         total_w_mm: float, size_pt: float = 8.6,
                         line_height: float = 1.45, pad_mm: float = 2.6,
                         header_pt: float = 8.4) -> list[float]:
    """估算表格每行高度（mm）：表头 + 每个数据行。宽度按 columns[].width 的相对比例切分。"""
    weights = [float(c.get("width", 1)) for c in columns] or [1.0]
    total_w = sum(weights)
    widths = [total_w_mm * w / total_w for w in weights]
    heights = []
    header = [str(c.get("label", "")) for c in columns]
    hl = max(len(wrap_lines(cell, widths[i] - 2.0, header_pt)) for i, cell in enumerate(header))
    heights.append(round(hl * header_pt * line_height * PT_TO_MM + pad_mm, 1))
    for row in rows:
        cells = [str(row[i]) if i < len(row) else "" for i in range(len(columns))]
        nl = max(len(wrap_lines(c, widths[i] - 2.0, size_pt)) for i, c in enumerate(cells))
        heights.append(round(nl * size_pt * line_height * PT_TO_MM + pad_mm, 1))
    return heights


# --------------------------------------------------------------------- 页面几何
@dataclass(frozen=True)
class Geometry:
    page_w: float
    page_h: float
    margin: dict
    columns: int
    gutter: float
    footer: float

    @property
    def content_w(self) -> float:
        return self.page_w - self.margin["left"] - self.margin["right"]

    @property
    def content_h(self) -> float:
        return self.page_h - self.margin["top"] - self.margin["bottom"]

    @property
    def col_w(self) -> float:
        return (self.content_w - self.gutter * (self.columns - 1)) / self.columns

    def span_width(self, span: int) -> float:
        return span * self.col_w + (span - 1) * self.gutter

    def col_x(self, col: int) -> float:
        """第 col 列（0 起）的左边界，相对内容区。"""
        return col * (self.col_w + self.gutter)

    def to_dict(self) -> dict:
        return {
            "page_w": round(self.page_w, 2), "page_h": round(self.page_h, 2),
            "margin": self.margin, "columns": self.columns, "gutter": self.gutter,
            "footer": self.footer,
            "content_w": round(self.content_w, 2), "content_h": round(self.content_h, 2),
            "col_w": round(self.col_w, 3),
        }


def geometry(page: dict) -> Geometry:
    size = str(page.get("size", "A4")).upper()
    if size not in PAGE_SIZES:
        raise SceneError(f"page.size 非法：{page.get('size')!r}，可选 {sorted(PAGE_SIZES)}")
    w, h = PAGE_SIZES[size]
    if str(page.get("orientation", "portrait")).lower() in ("landscape", "横向"):
        w, h = h, w
    m = page.get("margin") or {}
    margin = {
        "top": float(m.get("top", 16.0)),
        "right": float(m.get("right", 15.0)),
        "bottom": float(m.get("bottom", 14.0)),
        "left": float(m.get("left", 15.0)),
    }
    columns = int(page.get("columns", 12))
    g = Geometry(page_w=w, page_h=h, margin=margin, columns=columns,
                 gutter=float(page.get("gutter", 6.0)), footer=float(page.get("footer", 9.0)))
    if g.content_w <= 0 or g.content_h <= 0:
        raise SceneError("页边距过大，内容区没有可用面积")
    if columns < 1 or g.col_w <= 0:
        raise SceneError(f"columns/gutter 组合不可用：columns={columns}, gutter={g.gutter}")
    return g


# --------------------------------------------------------------------- 数据模型
@dataclass
class Block:
    id: str
    kind: str
    span: int = 12
    height: float = 40.0
    title: str = ""
    content: dict = field(default_factory=dict)
    stretch: bool = True
    break_before: bool = False
    tags: list[str] = field(default_factory=list)
    priority: int = 50

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "span": self.span,
            "height": round(self.height, 2), "title": self.title,
            "stretch": self.stretch, "break_before": self.break_before,
            "tags": list(self.tags), "priority": self.priority,
            "content": self.content,
        }


@dataclass
class Scene:
    blocks: list[Block]
    constraints: list[dict]
    page: dict
    theme: dict
    meta: dict
    solver: dict

    # -- 便捷访问 --
    def block(self, bid: str) -> Block:
        for b in self.blocks:
            if b.id == bid:
                return b
        raise KeyError(bid)

    def index(self, bid: str) -> int:
        for i, b in enumerate(self.blocks):
            if b.id == bid:
                return i
        raise KeyError(bid)

    def by_kind(self, kind: str) -> list[Block]:
        return [b for b in self.blocks if b.kind == kind]

    def constraints_of(self, ctype: str) -> list[dict]:
        return [c for c in self.constraints if c["type"] == ctype]

    def to_dict(self) -> dict:
        return {
            "version": "1.0",
            "meta": self.meta,
            "page": self.page,
            "solver": self.solver,
            "theme": self.theme,
            "blocks": [b.to_dict() for b in self.blocks],
            "constraints": self.constraints,
        }

    def dump(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return p


# --------------------------------------------------------------------- 构造 / 校验
def _norm_block(raw: dict, idx: int, columns: int) -> Block:
    bid = str(raw.get("id") or f"blk{idx + 1}")
    kind = str(raw.get("kind", "text"))
    height = raw.get("height", KIND_DEFAULT_HEIGHT.get(kind, 20.0))
    return Block(
        id=bid,
        kind=kind,
        span=int(raw.get("span", columns)),
        height=float(height),
        title=str(raw.get("title", "")),
        content=raw.get("content") or {},
        stretch=bool(raw.get("stretch", True)),
        break_before=bool(raw.get("break_before", False)),
        tags=list(raw.get("tags") or []),
        priority=int(raw.get("priority", 50)),
    )


def validate(doc: dict) -> list[str]:
    """结构校验：只查"DSL 本身是否合法"，不查排版效果。返回问题列表。"""
    errs: list[str] = []
    if not isinstance(doc, dict):
        return ["DSL 顶层必须是对象"]
    page = doc.get("page")
    if not isinstance(page, dict):
        return ["缺少 page 对象"]
    try:
        geom = geometry(page)
    except SceneError as e:
        return [str(e)]

    raw_blocks = doc.get("blocks")
    if not isinstance(raw_blocks, list) or not raw_blocks:
        return ["blocks 必须是非空数组"]
    seen: set[str] = set()
    for i, b in enumerate(raw_blocks):
        if not isinstance(b, dict):
            errs.append(f"blocks[{i}] 不是对象")
            continue
        bid = b.get("id")
        if not bid:
            errs.append(f"blocks[{i}] 缺少 id")
            continue
        if bid in seen:
            errs.append(f"块 id 重复：{bid}")
        seen.add(bid)
        if b.get("kind") not in KINDS:
            errs.append(f"{bid}: kind 非法 {b.get('kind')!r}，可选 {sorted(KINDS)}")
        span = b.get("span", geom.columns)
        if not isinstance(span, int) or not 1 <= span <= geom.columns:
            errs.append(f"{bid}: span 必须是 1..{geom.columns} 的整数，实际 {span!r}")
        h = b.get("height", KIND_DEFAULT_HEIGHT.get(b.get("kind", ""), 20.0))
        try:
            if float(h) <= 0:
                errs.append(f"{bid}: height 必须为正数")
            elif float(h) > geom.content_h:
                errs.append(f"{bid}: height {h} 超过整页可用高度 {geom.content_h:.1f}")
        except (TypeError, ValueError):
            errs.append(f"{bid}: height 不是数字 {h!r}")

    cs = doc.get("constraints") or []
    if not isinstance(cs, list):
        errs.append("constraints 必须是数组")
        cs = []
    for i, c in enumerate(cs):
        if not isinstance(c, dict) or c.get("type") not in CONSTRAINT_TYPES:
            errs.append(f"constraints[{i}] 类型非法：{c!r}")
            continue
        if c["type"] in ("same_row", "keep_together"):
            ids = c.get("blocks") or []
            if len(ids) < 2:
                errs.append(f"constraints[{i}] {c['type']} 至少需要 2 个块")
            for bid in ids:
                if bid not in seen:
                    errs.append(f"constraints[{i}] 引用了不存在的块 {bid!r}")
        elif c["type"] == "avoid_orphan":
            if c.get("block") not in seen:
                errs.append(f"constraints[{i}] 引用了不存在的块 {c.get('block')!r}")
        elif c["type"] == "aspect":
            if c.get("block") not in seen:
                errs.append(f"constraints[{i}] 引用了不存在的块 {c.get('block')!r}")
            lo, hi = c.get("min", 0.0), c.get("max", 99.0)
            if lo > hi:
                errs.append(f"constraints[{i}] aspect 的 min > max")
        elif c["type"] == "fill":
            lo, hi = c.get("min", 0.0), c.get("max", 1.0)
            if not 0 <= lo <= hi <= 1.5:
                errs.append(f"constraints[{i}] fill 区间非法：[{lo}, {hi}]")
        elif c["type"] == "max_pages":
            if not isinstance(c.get("value"), int) or c["value"] < 1:
                errs.append(f"constraints[{i}] max_pages 需要正整数")

    # 同组约束的块必须连续（分页按文档顺序切，跨页组会被切碎）
    for c in cs:
        if c.get("type") == "keep_together":
            idxs = sorted(seen_index(raw_blocks, bid) for bid in c["blocks"])
            if idxs and idxs != list(range(idxs[0], idxs[-1] + 1)):
                errs.append(f"keep_together 的块在文档顺序上不连续：{c['blocks']}")
        if c.get("type") == "same_row":
            idxs = sorted(seen_index(raw_blocks, bid) for bid in c["blocks"])
            if idxs and idxs != list(range(idxs[0], idxs[-1] + 1)):
                errs.append(f"same_row 的块在文档顺序上不连续：{c['blocks']}")
    return errs


def seen_index(raw_blocks: list, bid: str) -> int:
    for i, b in enumerate(raw_blocks):
        if isinstance(b, dict) and b.get("id") == bid:
            return i
    return 10 ** 6


def parse(doc: dict) -> Scene:
    """校验并归一化成一个 Scene。结构有问题直接抛 SceneError（一次报全部问题）。"""
    errs = validate(doc)
    if errs:
        raise SceneError("版面 DSL 校验失败：\n- " + "\n- ".join(errs))

    geom = geometry(doc["page"])
    blocks = [_norm_block(b, i, geom.columns) for i, b in enumerate(doc["blocks"])]

    solver = {
        "page_cost": 55.0,
        "fill_min": 0.78,
        "fill_max": 1.0,
        "underfill_weight": 1400.0,
        "overflow_weight": 3000.0,
        "orphan_weight": 260.0,
        "tolerance_mm": 0.4,
        "max_pages": None,
    }
    solver.update(doc.get("solver") or {})
    for c in doc.get("constraints") or []:
        if c["type"] == "fill":
            solver["fill_min"] = float(c.get("min", solver["fill_min"]))
            solver["fill_max"] = float(c.get("max", solver["fill_max"]))
        elif c["type"] == "max_pages":
            solver["max_pages"] = int(c["value"])

    theme = dict(DEFAULT_THEME)
    theme.update(doc.get("theme") or {})
    return Scene(blocks=blocks, constraints=list(doc.get("constraints") or []),
                 page=dict(doc["page"]), theme=theme,
                 meta=dict(doc.get("meta") or {}), solver=solver)


def load(path: str | Path) -> Scene:
    return parse(json.loads(Path(path).read_text(encoding="utf-8")))


# --------------------------------------------------------------------- 常用约束助手
def same_row(*ids: str) -> dict:
    return {"type": "same_row", "blocks": list(ids)}


def keep_together(*ids: str, mode: str = "page") -> dict:
    return {"type": "keep_together", "blocks": list(ids), "mode": mode}


def avoid_orphan(bid: str) -> dict:
    return {"type": "avoid_orphan", "block": bid}


def aspect(bid: str, lo: float, hi: float) -> dict:
    return {"type": "aspect", "block": bid, "min": lo, "max": hi}


def fill(lo: float = 0.78, hi: float = 1.0) -> dict:
    return {"type": "fill", "min": lo, "max": hi}


def max_pages(n: int) -> dict:
    return {"type": "max_pages", "value": n}
