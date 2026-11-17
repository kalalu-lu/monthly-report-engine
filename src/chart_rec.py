"""
图表推荐（Stage B 第一步）

不是 if-else 直出，而是三步：
  1. 候选生成：按数据形状（时间序列 / 类别对比 / 部分与整体 / 差异分解 / 目标对比）筛出可用的图表类型
  2. 多目标打分：数据-通道匹配（40）+ 可读性（25）+ 信息密度（20）+ 叙事契合（15）+ 制表惯例（≤12）
  3. 输出 Top-1 + 理由文本（理由会印进报告，说明"为什么选这张图"）

打分依据：图形感知的编码效率层级 —— 位置 > 长度 > 角度 > 面积 > 色相。
参见 Cleveland & McGill (1984) 关于图形感知精度的经典结论。

一个明确的取舍：**本系统不自动推荐饼图/环形图**。部分与整体的关系用长度编码的堆叠条
表达同样清楚且可比较，而角度编码的饼图在类别接近时无法分辨大小。
"""
from __future__ import annotations

ENCODING = {"position": 40, "length": 32, "angle": 24, "area": 16, "hue": 8}

# 主视觉通道 / 适用形状 / 类别上限 / 密度基准 / 各叙事角色契合度 / 中文名
SPECS = {
    "line": {"channel": "position", "shapes": {"trend"}, "max_cat": 24, "density": 15,
             "roles": {"trend": 1.00, "target": 0.55, "ranking": 0.30}, "name": "折线图"},
    "area": {"channel": "area", "shapes": {"trend"}, "max_cat": 12, "density": 10,
             "roles": {"trend": 0.75, "target": 0.30, "ranking": 0.20}, "name": "面积图"},
    "bar": {"channel": "length", "shapes": {"category"}, "max_cat": 12, "density": 16,
            "roles": {"trend": 0.60, "ranking": 0.90, "target": 0.50}, "name": "柱状图"},
    "hbar": {"channel": "length", "shapes": {"category"}, "max_cat": 20, "density": 17,
             "roles": {"trend": 0.25, "ranking": 1.00, "target": 0.45}, "name": "条形图"},
    "stacked": {"channel": "length", "shapes": {"part_whole"}, "max_cat": 8, "density": 14,
                "roles": {"mix": 1.00, "trend": 0.50, "ranking": 0.35}, "name": "堆叠条"},
    "waterfall": {"channel": "length", "shapes": {"decompose"}, "max_cat": 8, "density": 19,
                  "roles": {"variance": 1.00, "trend": 0.10, "ranking": 0.30}, "name": "瀑布图"},
    "bullet": {"channel": "length", "shapes": {"target"}, "max_cat": 8, "density": 15,
               "roles": {"target": 1.00, "ranking": 0.55, "trend": 0.20}, "name": "子弹图"},
}

# 形状-图表 的制表惯例加成（形状比叙事角色更决定图表选择）
SHAPE_BONUS = {
    "trend": {"line": 10, "area": 5},
    "category": {"hbar": 10, "bar": 6},
    "part_whole": {"stacked": 8},
    "decompose": {"waterfall": 12},
    "target": {"bullet": 12},
}


def profile(n_cat: int, shape: str, role: str, label_max_chars: int = 4,
            has_target: bool = False) -> dict:
    """shape ∈ trend / category / part_whole / decompose / target"""
    return {"n_cat": n_cat, "shape": shape, "role": role,
            "label_max_chars": label_max_chars, "has_target": has_target}


def _readability(spec: dict, f: dict) -> float:
    s = 25.0
    if f["n_cat"] > spec["max_cat"]:
        s *= spec["max_cat"] / f["n_cat"]          # 类别过多直接惩罚
    if f["label_max_chars"] > 6 and spec["name"] == "柱状图":
        s -= 6                                     # 长标签配竖柱会挤在一起
    return max(0.0, round(s, 2))


def _density(spec: dict, f: dict) -> float:
    base = spec["density"] * 20 / 19
    if f["n_cat"] < 3:
        base *= 0.6                                # 只有一两个类别时信息量太低
    return round(min(20.0, base), 2)


def _role(spec: dict, f: dict) -> float:
    return round(15.0 * spec["roles"].get(f["role"], 0.2), 2)


def recommend(f: dict) -> dict:
    """返回 {'chosen','name','score','reason','ranking'}"""
    cands = []
    for key, spec in SPECS.items():
        if f["shape"] not in spec["shapes"]:
            continue
        if key == "bullet" and not f["has_target"]:
            continue
        channel = ENCODING[spec["channel"]]
        read = _readability(spec, f)
        dens = _density(spec, f)
        role = _role(spec, f)
        bonus = SHAPE_BONUS.get(f["shape"], {}).get(key, 0)
        total = round(channel + read + dens + role + bonus, 2)
        cands.append({"chart": key, "name": spec["name"], "total": total,
                      "detail": {"数据-通道": channel, "可读性": read, "信息密度": dens,
                                 "叙事契合": role, "制表惯例": bonus}})

    if not cands:
        return {"chosen": "bar", "name": "柱状图", "score": 0,
                "reason": "无匹配候选，回退为柱状图", "ranking": []}

    cands.sort(key=lambda x: -x["total"])
    top = cands[0]
    ch = SPECS[top["chart"]]["channel"]
    reason = (f"选{top['name']}（{top['total']} 分）：{f['n_cat']} 个类别、"
              f"形状为 {f['shape']}，{ch} 通道编码效率最高（{ENCODING[ch]}/40），"
              f"可读性 {top['detail']['可读性']}/25、叙事契合 {top['detail']['叙事契合']}/15")
    if len(cands) > 1:
        second = cands[1]
        reason += f"；次选{second['name']}（{second['total']} 分），差距主要在制表惯例与叙事契合"
    return {"chosen": top["chart"], "name": top["name"], "score": top["total"],
            "reason": reason, "ranking": cands}


# ---------------------------------------------------------------- 评测基准
# 30 组标准数据形状 + 制图惯例下的最优图表（验证规则与惯例是否一致）
BENCHMARK = [
    ("trend", 13, "trend", False, "line"),
    ("trend", 24, "trend", False, "line"),
    ("trend", 6, "trend", False, "line"),
    ("trend", 13, "target", True, "line"),
    ("trend", 36, "trend", False, "line"),
    ("trend", 12, "ranking", False, "line"),
    ("category", 6, "ranking", False, "hbar"),
    ("category", 12, "ranking", False, "hbar"),
    ("category", 3, "ranking", False, "hbar"),
    ("category", 20, "ranking", False, "hbar"),
    ("category", 2, "ranking", False, "hbar"),
    ("category", 7, "ranking", False, "hbar"),
    ("category", 16, "ranking", False, "hbar"),
    ("category", 5, "target", True, "bar"),
    ("category", 8, "target", True, "bar"),
    ("category", 9, "trend", False, "bar"),
    ("part_whole", 3, "mix", False, "stacked"),
    ("part_whole", 4, "mix", False, "stacked"),
    ("part_whole", 5, "mix", False, "stacked"),
    ("part_whole", 6, "mix", False, "stacked"),
    ("part_whole", 7, "mix", False, "stacked"),
    ("part_whole", 8, "mix", False, "stacked"),
    ("part_whole", 12, "mix", False, "stacked"),
    ("decompose", 4, "variance", False, "waterfall"),
    ("decompose", 5, "variance", False, "waterfall"),
    ("decompose", 7, "variance", False, "waterfall"),
    ("target", 4, "target", True, "bullet"),
    ("target", 6, "target", True, "bullet"),
    ("target", 8, "target", True, "bullet"),
    ("target", 7, "ranking", True, "bullet"),
]


def run_benchmark() -> dict:
    hit1 = hit3 = 0
    misses = []
    for shape, n, role, has_t, expect in BENCHMARK:
        r = recommend(profile(n, shape, role, has_target=has_t))
        names = [c["chart"] for c in r["ranking"]]
        if names and names[0] == expect:
            hit1 += 1
        else:
            misses.append({"shape": shape, "n": n, "role": role,
                           "expect": expect, "got": names[:3]})
        if expect in names[:3]:
            hit3 += 1
    total = len(BENCHMARK)
    return {"total": total, "top1": hit1, "top3": hit3,
            "top1_rate": round(hit1 / total * 100, 2),
            "top3_rate": round(hit3 / total * 100, 2), "misses": misses}


if __name__ == "__main__":
    rep = run_benchmark()
    print("=" * 56)
    print("图表推荐基准")
    print("=" * 56)
    print(f"样本数     : {rep['total']}")
    print(f"Top-1 命中 : {rep['top1']}/{rep['total']} = {rep['top1_rate']}%")
    print(f"Top-3 召回 : {rep['top3']}/{rep['total']} = {rep['top3_rate']}%")
    for m in rep["misses"]:
        print("  未命中:", m)
    print("\n示例理由：")
    print(" ", recommend(profile(6, "category", "ranking"))["reason"])
