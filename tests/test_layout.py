"""
版面 DSL 与约束求解的单元测试（python tests/test_layout.py，不依赖 pytest）

覆盖：
  1. DSL 结构校验：重复 id / 列越界 / 约束引用不存在的块 / keep_together 不连续
  2. 求解结果几何合法：不越界、不重叠、顺序不乱（由 check_plan 独立验算）
  3. same_row / keep_together / break_before 三条硬约束真的被满足
  4. 最优性：小场景上与"枚举所有分页方案"的暴力解对比，目标值必须一致
  5. 确定性：同一输入两次求解结果逐字节相同
  6. 对照组：贪心装箱的目标值不优于 DP
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import dsl, layout  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail and not cond else ""))


def blk(bid: str, h: float, span: int = 12, kind: str = "chart", **kw) -> dict:
    d = {"id": bid, "kind": kind, "span": span, "height": h}
    d.update(kw)
    return d


def scene(blocks: list[dict], constraints: list[dict] | None = None,
          page: dict | None = None) -> dsl.Scene:
    return dsl.parse({
        "meta": {"title": "测试版面"},
        "page": page or {"size": "A4", "margin": {"top": 16, "right": 15, "bottom": 14, "left": 15},
                         "columns": 12, "gutter": 6},
        "blocks": blocks,
        "constraints": constraints or [],
    })


# ------------------------------------------------------------------ 1. DSL 校验
def test_dsl_validation() -> None:
    print("\n[1] DSL 结构校验")
    bad_cases = {
        "重复 id": [blk("a", 30), blk("a", 30)],
        "span 越界": [blk("a", 30, span=13)],
        "高度超页": [blk("a", 400)],
    }
    for name, blocks in bad_cases.items():
        try:
            scene(blocks)
            check(f"拦截：{name}", False, "没有报错")
        except dsl.SceneError as e:
            check(f"拦截：{name}", True)

    try:
        scene([blk("a", 30)], [{"type": "same_row", "blocks": ["a", "ghost"]}])
        check("拦截：约束引用不存在的块", False, "没有报错")
    except dsl.SceneError:
        check("拦截：约束引用不存在的块", True)

    try:
        scene([blk("a", 30), blk("b", 30), blk("c", 30)],
              [{"type": "keep_together", "blocks": ["a", "c"]}])
        check("拦截：keep_together 块不连续", False, "没有报错")
    except dsl.SceneError:
        check("拦截：keep_together 块不连续", True)

    s = scene([blk("a", 30, kind="chart", span=6), blk("b", 20, kind="text")])
    g = dsl.geometry(s.page)
    check("几何：A4 内容区宽 180mm", abs(g.content_w - 180) < 1e-6, f"{g.content_w}")
    check("几何：单列宽 (180-66)/12 = 9.5mm", abs(g.col_w - 9.5) < 1e-6, f"{g.col_w}")
    check("几何：6 列块宽 87mm", abs(g.span_width(6) - 87.0) < 1e-6, f"{g.span_width(6)}")


# ------------------------------------------------------------------ 2. 几何合法
def test_plan_geometry() -> None:
    print("\n[2] 求解结果几何合法")
    s = scene([blk(f"b{i}", 40) for i in range(8)])
    plan = layout.solve(s)
    v = layout.check_plan(s, plan)
    hard = [x for x in v if x["hard"]]
    check("无硬约束违规", not hard, json.dumps(hard, ensure_ascii=False)[:300])
    check("所有块都排上了", len(plan["placements"]) == 8)
    used = sum(p["h_mm"] for pg in plan["pages"] for p in pg["rows"])
    check("页面不超内容区高", all(pg["used_mm"] <= plan["geometry"]["content_h"] + 0.4
                             for pg in plan["pages"]))
    check("填充率 <= 1", all(pg["fill"] <= 1.0001 for pg in plan["pages"]))


def test_same_row() -> None:
    print("\n[3] same_row：6 个 KPI 卡并排成一行")
    kpis = [blk(f"k{i}", 26, span=2, kind="kpi") for i in range(6)]
    s = scene(kpis, [dsl.same_row(*[b["id"] for b in kpis])])
    plan = layout.solve(s)
    ys = {plan["placements"][b["id"]]["y_mm"] for b in kpis}
    hs = {plan["placements"][b["id"]]["h_mm"] for b in kpis}
    xs = [plan["placements"][b["id"]]["x_mm"] for b in kpis]
    check("同一水平线", len(ys) == 1, str(ys))
    check("行高一致", len(hs) == 1, str(hs))
    check("横向依次排开", xs == sorted(xs) and len(set(xs)) == 6)
    check("首块左边距 = 15mm", abs(min(xs) - 15) < 1e-6, str(min(xs)))
    check("总跨度正好 12 列", sum(b["span"] for b in kpis) == 12)


def test_keep_together() -> None:
    print("\n[4] keep_together：图与图注不拆页")
    blocks = [blk("c1", 120), blk("c2", 120), blk("t1", 30, kind="text"), blk("t2", 30, kind="text")]
    s = scene(blocks, [dsl.keep_together("c2", "t1")])
    plan = layout.solve(s)
    check("c2 与 t1 同页", plan["placements"]["c2"]["page"] == plan["placements"]["t1"]["page"],
          f"{plan['placements']['c2']['page']} vs {plan['placements']['t1']['page']}")
    check("check_plan 无硬违规",
          not [x for x in layout.check_plan(s, plan) if x["hard"]])


def test_break_before() -> None:
    print("\n[5] break_before：新章节强制另起一页")
    blocks = [blk("a", 100), blk("b", 100), blk("sec", 12, kind="section", break_before=True)]
    s = scene(blocks)
    plan = layout.solve(s)
    p = plan["placements"]["sec"]
    check("章节在页首", abs(p["y_mm"] - plan["geometry"]["margin"]["top"]) < 1.0,
          f"y={p['y_mm']}")
    check("章节不是第 1 页", p["page"] >= 2, str(p["page"]))


# ------------------------------------------------------------------ 6. 最优性
def brute_force_objective(s: dsl.Scene) -> float:
    atoms = layout.build_atoms(s)
    geom = dsl.geometry(s.page)
    n = len(atoms)
    best = None
    for mask in range(1 << max(0, n - 1)):
        cuts = [0] + [i + 1 for i in range(n - 1) if mask >> i & 1] + [n]
        total = 0.0
        ok = True
        for i, j in zip(cuts, cuts[1:]):
            rows = layout.pack_rows(atoms, i, j, geom.columns)
            used = sum(r.height for r in rows)
            if used > geom.content_h + layout.EPS:
                ok = False
                break
            c, _ = layout.estimate_cost(s, rows, used, geom, s.solver["page_cost"])
            total += c
        if ok and (best is None or total < best - 1e-9):
            best = total
    return best


def test_optimality() -> None:
    print("\n[6] 最优性：与暴力枚举对比（小场景）")
    s = scene([blk("a", 90), blk("b", 90), blk("c", 60), blk("d", 60), blk("e", 40)])
    plan = layout.solve(s)
    bf = brute_force_objective(s)
    check("DP 目标值 = 暴力最优值", abs(plan["metrics"]["objective"] - bf) < 0.01,
          f"DP {plan['metrics']['objective']} vs 暴力 {bf}")

    s2 = scene([blk(f"b{i}", 70) for i in range(7)])
    plan2 = layout.solve(s2)
    bf2 = brute_force_objective(s2)
    check("7 块场景同样最优", abs(plan2["metrics"]["objective"] - bf2) < 0.01,
          f"DP {plan2['metrics']['objective']} vs 暴力 {bf2}")


def test_determinism() -> None:
    print("\n[7] 确定性")
    s = scene([blk(f"b{i}", 35 + (i % 3) * 20) for i in range(9)])
    a = json.dumps(layout.solve(s), ensure_ascii=False, sort_keys=True)
    b = json.dumps(layout.solve(s), ensure_ascii=False, sort_keys=True)
    check("两次求解逐字节一致", a == b)


def test_greedy_worse() -> None:
    print("\n[8] 对照组：贪心装箱不优于 DP")
    s = scene([blk("a", 100), blk("b", 100), blk("c", 55), blk("d", 55)])
    dp_plan = layout.solve(s)
    gr_plan = layout.solve_greedy(s)
    check("DP 目标值不高于贪心",
          dp_plan["metrics"]["objective"] <= gr_plan["metrics"]["objective"] + 1e-6,
          f"DP {dp_plan['metrics']['objective']} vs 贪心 {gr_plan['metrics']['objective']}")
    check("贪心同样几何合法",
          not [x for x in layout.check_plan(s, gr_plan) if x["hard"]])


def test_errors() -> None:
    print("\n[9] 异常场景")
    try:
        scene([blk("huge", 280), blk("b", 30)])
        check("块高于内容区被 DSL 拦下", False, "居然通过了校验")
    except dsl.SceneError:
        check("块高于内容区被 DSL 拦下", True)

    # 求解器自身的兜底：绕过 DSL 校验直接构造超高的 Scene
    raw = scene([blk("b", 30)])
    from src.dsl import Block, Scene
    raw.blocks.insert(0, Block(id="huge", kind="chart", span=12, height=400.0))
    try:
        layout.solve(raw)
        check("求解器兜底拒绝超高块", False, "居然排下了")
    except layout.LayoutError:
        check("求解器兜底拒绝超高块", True)

    # 单块正好等于内容区高度 → 应能独占一页，且不与后续块重叠
    s2 = scene([blk("full", 267.0 - 1e-9), blk("b", 10)])
    plan = layout.solve(s2)
    check("满页块可单独成页", plan["metrics"]["pages"] == 2, str(plan["metrics"]["pages"]))


def test_dsl_roundtrip(tmp: Path) -> None:
    print("\n[10] DSL 落盘 / 读回")
    s = scene([blk("a", 40), blk("b", 30, kind="text")])
    p = s.dump(tmp / "layout_dsl_test.json")
    s2 = dsl.load(p)
    check("读回块数一致", len(s2.blocks) == len(s.blocks))
    check("读回约束一致", s2.constraints == s.constraints)
    check("读回页面参数一致", s2.page == s.page)


if __name__ == "__main__":
    print("=" * 60)
    print("版面 DSL / 约束求解 单元测试")
    print("=" * 60)
    tmp = ROOT / "outputs" / "tests"
    tmp.mkdir(parents=True, exist_ok=True)
    test_dsl_validation()
    test_plan_geometry()
    test_same_row()
    test_keep_together()
    test_break_before()
    test_optimality()
    test_determinism()
    test_greedy_worse()
    test_errors()
    test_dsl_roundtrip(tmp)
    print("\n" + "=" * 60)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + "、".join(FAIL))
        sys.exit(1)
    print("全部通过 ✓")
