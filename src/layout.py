"""
版面约束求解（Stage B 第二步）

输入：dsl.Scene（块的顺序、尺寸、列跨度 + 一组约束）
输出：layout plan（每页每块的 mm 坐标 + 每页填充率 + 软约束违背清单）

算法（两段式，都是确定性的）：

  1) 行装箱：按文档顺序把块放进"行"。同一行的块列宽之和 ≤ columns；
     声明了 same_row 的块必须先并成一个不可拆的原子（atom）。
     行高 = 行内块的最大高度（整个行一起拉伸，避免高低错落）。

  2) 分页：把"块序列切分成若干连续页"看成一个最短路问题——
        dp[j] = min{ dp[i] + cost(页 i..j-1) }，其中页可行 ⟺ 行高之和 ≤ 内容区高度
     页的代价 = 固定页成本 + 填充率偏离惩罚 + 孤行惩罚。
     对 n 个原子做 O(n²) 枚举 + O(n) 装箱，n≈30 时毫秒级，且**全局最优**——
     这一点很关键：贪心"装满就翻页"在最后会留下一页只用 30% 的碎页，
     而 DP 会提前把内容摊匀（例如把最后一页的两张图提到前页）。评测里有对比。

约束的处理分两类：
  硬约束（违反即该页不可行）：不跨页组、break_before、块高度不超页、max_pages
  软约束（违反计入代价）：填充率区间、章节标题孤行、末行过矮
  几何约束（不改分页，只校验）：长宽比、同行等高

check_plan() 独立于求解器重新验算一遍几何，供评测脚本和单元测试使用——
"求解器说自己对"不算证据，得由不看求解器的代码验。
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from src import dsl

EPS = 0.4  # mm 容差


class LayoutError(RuntimeError):
    """无解或求解失败。"""


# --------------------------------------------------------------------- 原子
@dataclass
class Atom:
    """不可再拆的最小排版单元：要么是单个块，要么是被 same_row 绑在一起的一组块。"""
    blocks: list[dsl.Block]
    start: int           # 首块在 scene.blocks 里的下标
    end: int             # 末块下标 + 1

    @property
    def span(self) -> int:
        return sum(b.span for b in self.blocks)

    @property
    def height(self) -> float:
        return max(b.height for b in self.blocks)

    @property
    def break_before(self) -> bool:
        return any(b.break_before for b in self.blocks)

    @property
    def ids(self) -> list[str]:
        return [b.id for b in self.blocks]


def build_atoms(scene: dsl.Scene) -> list[Atom]:
    parent = list(range(len(scene.blocks)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for c in scene.constraints_of("same_row"):
        idx = [scene.index(bid) for bid in c["blocks"]]
        for k in idx[1:]:
            union(idx[0], k)

    groups: dict[int, list[int]] = {}
    for i in range(len(scene.blocks)):
        groups.setdefault(find(i), []).append(i)

    atoms: list[Atom] = []
    for root in sorted(groups, key=lambda r: groups[r][0]):
        idxs = sorted(groups[root])
        if idxs != list(range(idxs[0], idxs[-1] + 1)):
            raise LayoutError(f"same_row 的块不连续：{[scene.blocks[i].id for i in idxs]}")
        atoms.append(Atom(blocks=[scene.blocks[i] for i in idxs],
                          start=idxs[0], end=idxs[-1] + 1))
    return atoms


# --------------------------------------------------------------------- 行装箱
@dataclass
class Row:
    atoms: list[Atom]
    height: float
    span: int

    @property
    def blocks(self) -> list[dsl.Block]:
        return [b for a in self.atoms for b in a.blocks]


def pack_rows(atoms: list[Atom], i: int, j: int, columns: int) -> list[Row]:
    """把 atoms[i:j] 依次放进若干行。多块原子独占一行（它是被 same_row 绑定的整体）。"""
    rows: list[Row] = []
    cur: Row | None = None
    for k in range(i, j):
        a = atoms[k]
        if cur is not None and len(a.blocks) == 1 and len(cur.atoms) >= 1 \
                and cur.span + a.span <= columns and len(cur.atoms[0].blocks) == 1:
            cur.atoms.append(a)
            cur.span += a.span
            cur.height = max(cur.height, a.height)
        else:
            cur = Row(atoms=[a], height=a.height, span=a.span)
            rows.append(cur)
    return rows


# --------------------------------------------------------------------- 分页代价
def estimate_cost(scene: dsl.Scene, rows: list[Row], used: float, geom: dsl.Geometry,
                  page_cost: float) -> tuple[float, list[str]]:
    """一页的代价（越小越好）＋ 该页命中的软约束说明。"""
    s = scene.solver
    cost = page_cost
    notes: list[str] = []
    fill_ratio = used / geom.content_h

    if fill_ratio < s["fill_min"]:
        cost += (s["fill_min"] - fill_ratio) * s["underfill_weight"]
        notes.append(f"填充率 {fill_ratio:.0%} 低于下限 {s['fill_min']:.0%}")
    if fill_ratio > s["fill_max"]:
        cost += (fill_ratio - s["fill_max"]) * s["overflow_weight"]
        notes.append(f"填充率 {fill_ratio:.0%} 超过上限 {s['fill_max']:.0%}")

    orphan = {c["block"] for c in scene.constraints_of("avoid_orphan")}
    hit = [b.id for b in rows[-1].blocks if b.id in orphan]
    if hit:
        cost += s["orphan_weight"]
        notes.append("章节标题落在页底：" + "、".join(hit))
    return cost, notes


# --------------------------------------------------------------------- 主求解
def solve(scene: dsl.Scene, max_iter: int = 8) -> dict:
    """求解版面，返回 layout plan（dict）。无解抛 LayoutError。"""
    geom = dsl.geometry(scene.page)
    atoms = build_atoms(scene)
    n = len(atoms)
    for a in atoms:
        if a.height > geom.content_h + EPS:
            raise LayoutError(f"块 {a.ids} 高度 {a.height:.1f}mm 超过可用页面高度 {geom.content_h:.1f}mm")
        if a.span > geom.columns:
            raise LayoutError(f"块 {a.ids} 列跨度 {a.span} 超过页宽 {geom.columns} 列")

    # keep_together：页边界不能落在这组块内部
    page_groups: list[set[int]] = []
    for c in scene.constraints_of("keep_together"):
        page_groups.append({scene.index(bid) for bid in c["blocks"]})

    cache: dict[tuple[int, int], tuple[list[Row], float] | None] = {}

    def page(i: int, j: int) -> tuple[list[Row], float] | None:
        key = (i, j)
        if key in cache:
            return cache[key]
        rows = pack_rows(atoms, i, j, geom.columns)
        used = sum(r.height for r in rows)
        ok = used <= geom.content_h + EPS
        # break_before 的块必须在页首
        if ok:
            for k in range(i, j):
                if atoms[k].break_before and k != i:
                    ok = False
                    break
        # keep_together 组不能跨页
        if ok:
            lo, hi = atoms[i].start, atoms[j - 1].end
            for g in page_groups:
                if any(lo < g0 < hi for g0 in g if g0 < lo or g0 >= hi):
                    ok = False
                    break
        out = (rows, used) if ok else None
        cache[key] = out
        return out

    page_cost = float(scene.solver["page_cost"])
    mp = scene.solver.get("max_pages")
    iterations: list[dict] = []
    bounds: list[tuple[int, int]] = []
    obj = 0.0
    for it in range(max_iter):
        cache.clear()
        INF = float("inf")
        dp = [INF] * (n + 1)
        prev = [-1] * (n + 1)
        dp[0] = 0.0
        for j in range(1, n + 1):
            for i in range(j):
                if dp[i] == INF:
                    continue
                p = page(i, j)
                if p is None:
                    continue
                rows, used = p
                c, _ = estimate_cost(scene, rows, used, geom, page_cost)
                if dp[i] + c < dp[j] - 1e-9:
                    dp[j] = dp[i] + c
                    prev[j] = i
        if dp[n] == INF:
            raise LayoutError(
                "无可行分页：请检查块高度（单块不得高于内容区）、break_before 或 keep_together 约束"
                f"（内容区高 {geom.content_h:.1f}mm，共 {n} 个排版单元）")

        bounds = []
        j = n
        while j > 0:
            i = prev[j]
            bounds.append((i, j))
            j = i
        bounds.reverse()
        obj = dp[n]
        iterations.append({"iter": it + 1, "page_cost": round(page_cost, 1),
                           "pages": len(bounds), "objective": round(obj, 2),
                           "max_pages": mp})
        if mp is None or len(bounds) <= mp:
            break
        # 页数超限：抬高每页固定成本，逼求解器压页（页数做不到上限时会保留最后一轮的解）
        page_cost *= 2.2

    return _materialize(scene, geom, atoms, bounds, obj, page_cost, iterations)


def _materialize(scene: dsl.Scene, geom: dsl.Geometry, atoms: list[Atom],
                 bounds: list[tuple[int, int]], objective: float, page_cost: float,
                 iterations: list[dict]) -> dict:
    pages: list[dict] = []
    placements: dict[str, dict] = {}
    for pno, (i, j) in enumerate(bounds, 1):
        rows = pack_rows(atoms, i, j, geom.columns)
        y = geom.margin["top"]
        rows_out = []
        for row in rows:
            x = geom.margin["left"]
            blocks_out = []
            for atom in row.atoms:
                for b in atom.blocks:
                    w = geom.span_width(b.span)
                    h = row.height if b.stretch else b.height
                    rec = {"id": b.id, "kind": b.kind, "span": b.span,
                           "x_mm": round(x, 2), "y_mm": round(y, 2),
                           "w_mm": round(w, 2), "h_mm": round(h, 2),
                           "page": pno}
                    placements[b.id] = rec
                    blocks_out.append(rec)
                    x += w + geom.gutter
            rows_out.append({"y_mm": round(y, 2), "h_mm": round(row.height, 2),
                             "blocks": blocks_out})
            y += row.height
        used = sum(r["h_mm"] for r in rows_out)
        pages.append({"index": pno, "used_mm": round(used, 2),
                      "fill": round(used / geom.content_h, 4),
                      "rows": rows_out})

    fills = [p["fill"] for p in pages]
    metrics = {
        "pages": len(pages),
        "fill_avg": round(sum(fills) / len(fills), 4),
        "fill_min": round(min(fills), 4),
        "fill_max": round(max(fills), 4),
        "fill_std": round(statistics.pstdev(fills), 4) if len(fills) > 1 else 0.0,
        "objective": round(objective, 2),
        "page_cost": round(page_cost, 1),
        "content_h": round(geom.content_h, 2),
    }

    soft: list[str] = []
    for p in pages:
        notes = _page_notes(scene, p, geom)
        soft.extend(f"第 {p['index']} 页：{n}" for n in notes)

    return {
        "schema": "layout-plan/1",
        "geometry": geom.to_dict(),
        "pages": pages,
        "placements": placements,
        "metrics": metrics,
        "soft_violations": soft,
        "trace": {"atoms": len(atoms), "iterations": iterations},
    }


def _page_notes(scene: dsl.Scene, page: dict, geom: dsl.Geometry) -> list[str]:
    """页面级软约束说明（与代价函数同口径，但单独算一遍，便于解释）。"""
    s = scene.solver
    notes = []
    fill_ratio = page["fill"]
    if fill_ratio < s["fill_min"]:
        notes.append(f"填充率 {fill_ratio:.0%} 低于下限 {s['fill_min']:.0%}")
    orphan = {c["block"] for c in scene.constraints_of("avoid_orphan")}
    last = page["rows"][-1]["blocks"] if page["rows"] else []
    hit = [b["id"] for b in last if b["id"] in orphan]
    if hit:
        notes.append("章节标题落在页底：" + "、".join(hit))
    return notes


# --------------------------------------------------------------------- 基线（评测用）
def solve_greedy(scene: dsl.Scene) -> dict:
    """基线：按顺序一块块往下填，填不下就翻页（不做全局权衡）。

    这是"没有求解器"时的自然写法，评测里拿它当对照组：
    页数相同，但最后一页往往只剩一两块，填充率很难看。
    """
    geom = dsl.geometry(scene.page)
    atoms = build_atoms(scene)
    n = len(atoms)

    pages: list[list[int]] = []
    cur: list[int] = []
    for k in range(n):
        trial = cur + [k]
        used = sum(r.height for r in pack_rows(atoms, trial[0], k + 1, geom.columns))
        if used <= geom.content_h + EPS and not (atoms[k].break_before and cur):
            cur = trial
        else:
            pages.append(cur)
            cur = [k]
    if cur:
        pages.append(cur)
    bounds = [(p[0], p[-1] + 1) for p in pages]

    # 与 solve 共用产物格式：这里用一次完整代价评估
    out = _materialize(scene, geom, atoms, bounds, 0.0, float(scene.solver["page_cost"]), [])
    obj = 0.0
    for pg in out["pages"]:
        rows = [Row(atoms=[], height=r["h_mm"], span=0) for r in pg["rows"]]
        c, _ = estimate_cost(scene, rows, pg["used_mm"], geom, float(scene.solver["page_cost"]))
        obj += c
    out["metrics"]["objective"] = round(obj, 2)
    return out


# --------------------------------------------------------------------- 独立校验
def check_plan(scene: dsl.Scene, plan: dict) -> list[dict]:
    """不依赖求解器内部状态，重新验算版面。返回违规列表。

    每条：{"constraint": 类型, "hard": bool, "detail": str}
    """
    geom = dsl.geometry(scene.page)
    out: list[dict] = []
    places: dict[str, dict] = plan["placements"]

    # 1. 覆盖
    expect = {b.id for b in scene.blocks}
    got = set(places)
    if expect - got:
        out.append({"constraint": "覆盖", "hard": True,
                    "detail": "未排布的块：" + "、".join(sorted(expect - got))})
    if got - expect:
        out.append({"constraint": "覆盖", "hard": True,
                    "detail": "多出的块：" + "、".join(sorted(got - expect))})

    left, top = geom.margin["left"], geom.margin["top"]
    right = left + geom.content_w
    bottom = top + geom.content_h
    for bid, p in places.items():
        if p["x_mm"] < left - EPS or p["y_mm"] < top - EPS:
            out.append({"constraint": "越界", "hard": True, "detail": f"{bid} 左上角超出内容区"})
        if p["x_mm"] + p["w_mm"] > right + EPS:
            out.append({"constraint": "越界", "hard": True,
                        "detail": f"{bid} 右边界 {p['x_mm'] + p['w_mm']:.1f} > {right:.1f}mm"})
        if p["y_mm"] + p["h_mm"] > bottom + EPS:
            out.append({"constraint": "越界", "hard": True,
                        "detail": f"{bid} 下边界 {p['y_mm'] + p['h_mm']:.1f} > {bottom:.1f}mm"})

    # 2. 页内重叠
    by_page: dict[int, list[dict]] = {}
    for p in places.values():
        by_page.setdefault(p["page"], []).append(p)
    for pno, ps in by_page.items():
        ps = sorted(ps, key=lambda q: (q["y_mm"], q["x_mm"]))
        for a in range(len(ps)):
            for b in range(a + 1, len(ps)):
                p1, p2 = ps[a], ps[b]
                ox = min(p1["x_mm"] + p1["w_mm"], p2["x_mm"] + p2["w_mm"]) - max(p1["x_mm"], p2["x_mm"])
                oy = min(p1["y_mm"] + p1["h_mm"], p2["y_mm"] + p2["h_mm"]) - max(p1["y_mm"], p2["y_mm"])
                if ox > EPS and oy > EPS:
                    out.append({"constraint": "重叠", "hard": True,
                                "detail": f"第 {pno} 页 {p1['id']} 与 {p2['id']} 重叠 "
                                          f"({ox:.1f}×{oy:.1f}mm)"})

    # 3. 阅读顺序：按（页、y、x）排序后下标必须单调递增
    order = sorted(places.values(), key=lambda q: (q["page"], round(q["y_mm"], 1), q["x_mm"]))
    idxs = [scene.index(p["id"]) for p in order]
    if idxs != sorted(idxs):
        out.append({"constraint": "阅读顺序", "hard": True, "detail": "块的先后顺序被求解器打乱"})

    # 4. same_row
    for c in scene.constraints_of("same_row"):
        ps = [places[bid] for bid in c["blocks"] if bid in places]
        if not ps:
            continue
        if len({p["page"] for p in ps}) > 1:
            out.append({"constraint": "same_row", "hard": True,
                        "detail": f"{c['blocks']} 被拆到不同页"})
            continue
        if len({round(p["y_mm"], 1) for p in ps}) > 1:
            out.append({"constraint": "same_row", "hard": True,
                        "detail": f"{c['blocks']} 不在同一水平线"})
        if len({round(p["h_mm"], 1) for p in ps}) > 1:
            out.append({"constraint": "same_row", "hard": True,
                        "detail": f"{c['blocks']} 行高不一致"})
        span = sum(scene.block(bid).span for bid in c["blocks"])
        if span > geom.columns:
            out.append({"constraint": "same_row", "hard": True,
                        "detail": f"{c['blocks']} 列宽合计 {span} 超过 {geom.columns}"})

    # 5. keep_together
    for c in scene.constraints_of("keep_together"):
        ps = [places[bid] for bid in c["blocks"] if bid in places]
        if ps and len({p["page"] for p in ps}) > 1:
            out.append({"constraint": "keep_together", "hard": True,
                        "detail": f"{c['blocks']} 被拆到 {sorted({p['page'] for p in ps})} 页"})

    # 6. aspect
    for c in scene.constraints_of("aspect"):
        p = places.get(c["block"])
        if not p:
            continue
        ratio = p["w_mm"] / max(1e-6, p["h_mm"])
        if not (c.get("min", 0) - 1e-6 <= ratio <= c.get("max", 99) + 1e-6):
            out.append({"constraint": "aspect", "hard": True,
                        "detail": f"{c['block']} 长宽比 {ratio:.2f} 不在 "
                                  f"[{c.get('min')}, {c.get('max')}]"})

    # 7. break_before
    for b in scene.blocks:
        if b.break_before and b.id in places:
            p = places[b.id]
            if abs(p["y_mm"] - top) > 1.0:
                out.append({"constraint": "break_before", "hard": True,
                            "detail": f"{b.id} 要求另起一页，实际在第 {p['page']} 页中部"})

    # 8. 填充率 / 页数（软）
    for pg in plan["pages"]:
        if pg["fill"] < scene.solver["fill_min"] - 1e-6:
            out.append({"constraint": "fill", "hard": False,
                        "detail": f"第 {pg['index']} 页填充率 {pg['fill']:.1%} "
                                  f"< {scene.solver['fill_min']:.0%}"})
    mp = scene.solver.get("max_pages")
    if mp and len(plan["pages"]) > mp:
        out.append({"constraint": "max_pages", "hard": True,
                    "detail": f"页数 {len(plan['pages'])} 超过上限 {mp}"})
    return out
