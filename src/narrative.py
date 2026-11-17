"""
文案生成（Stage B 第三步）

三代提示词的对比实验：
  v1 自由发挥：给数据 + "帮我写份报告"                      → 基准线（问题最多）
  v2 加约束  ：禁止计算 + 事实包 + 引用标注 + 固定四段        → 大幅改善，但仍有越界
  v3 可验证  ：JSON Schema + 字段白名单 + 数字回查 + 自动重试  → 结构与事实双合规

v3 的"四道闸"：
  1. json.loads        —— 解析失败则把报错原文回传重试
  2. Schema 校验       —— 必填字段 / 枚举值 / 字数上限
  3. 数字回查          —— 抽出输出中每个数字，逐个到 FactPack 数字索引里比对
  4. 禁用词检查        —— "显著""大幅""持续向好"这类空话直接打回

每次调用都把原始输出落到 outputs/llm/，便于事后核对与截屏。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

_BOOT = Path(__file__).resolve().parents[1]
if str(_BOOT) not in sys.path:
    sys.path.insert(0, str(_BOOT))

from src import factpack as fpmod  # noqa: E402
from src import llm, paths  # noqa: E402

ROOT = paths.app_root()
PROMPTS = paths.res_root() / "prompts"
OUT = ROOT / "outputs" / "llm"

BANNED = ["显著", "大幅", "持续向好", "赋能", "全面提升", "极大", "巨大"]
RATING_ENUM = {"A", "B", "C", "D"}
LEVEL_ENUM = {"高", "中", "低"}

NUM_TOKEN = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s*(万|亿|%)?")


def load_prompt(version: str) -> tuple[str, str]:
    raw = (PROMPTS / f"{version}.md").read_text(encoding="utf-8")
    sys_part = raw.split("===SYSTEM===")[1].split("===USER===")[0].strip()
    user_part = raw.split("===USER===")[1].strip()
    return sys_part, user_part


def compact_facts(fp: dict) -> str:
    """v1 用的"裸数据"：只给关键数字，不给结构、不给约束。"""
    lines = [f"公司：{fp['meta']['company']}", f"期间：{fp['meta']['period']}", "", "主要指标："]
    for k in fp["kpis"]:
        lines.append(f"  {k['name']}：{k['value']} {k['unit']}")
    lines.append("")
    lines.append("门店收入：")
    for s in fp["stores"]:
        lines.append(f"  {s['store_name']}：{s['revenue']} 元，环比 {s['mom']}%，预算完成率 {s['budget_rate']}%")
    lines.append("")
    lines.append("预算差异：")
    rv = fp["variance"]["revenue"]
    lines.append(f"  实际 {rv['actual']} 元，预算 {rv['budget']} 元，差异 {rv['total']} 元")
    lines.append(f"  量差 {rv['qty_effect']}，价差 {rv['price_effect']}，混合差 {rv['mix_effect']}")
    return "\n".join(lines)


def number_sets(fp: dict) -> tuple[set[str], set[str]]:
    """返回 (元级数字集合, 万元级数字集合)，都带多种精度以便宽容匹配。"""
    raw_nums = fpmod.flatten_numbers(fp)
    raw = set(raw_nums)
    wan = set()
    for s in list(raw_nums):
        try:
            v = float(s)
        except ValueError:
            continue
        raw.add(f"{v:.3f}")
        wan.add(f"{v / 1e4:.1f}")
        wan.add(f"{v / 1e4:.2f}")
    return raw, wan


def check_numbers(text: str, raw: set[str], wan: set[str]) -> list[str]:
    """抽出文本中的数字，逐个比对；返回"查不到出处"的数字列表。"""
    bad = []
    for m in NUM_TOKEN.finditer(text):
        tok, unit = m.group(1), (m.group(2) or "")
        try:
            v = float(tok.replace(",", ""))
        except ValueError:
            continue
        if abs(v) <= 31 and not unit:          # 天数、条数、序号这类小整数不算
            continue
        a = abs(v)
        pool = wan if unit in ("万", "亿") else raw
        cands = {f"{a:.2f}", f"{a:.1f}", f"{a:.0f}", f"{a:g}"}
        if pool is wan and unit == "亿":
            cands = {f"{a * 1e4 / 1e4:.1f}"}
        if not (cands & pool):
            bad.append(f"{tok}{unit}")
    return bad


def check_banned(text: str) -> list[str]:
    return [w for w in BANNED if w in text]


def validate_v3(obj: dict) -> list[str]:
    errs = []
    if obj.get("rating") not in RATING_ENUM:
        errs.append("rating 必须是 A/B/C/D")
    if not isinstance(obj.get("verdict"), str) or not obj["verdict"].strip():
        errs.append("verdict 缺失")
    elif len(obj["verdict"]) > 80:
        errs.append(f"verdict 超过 80 字（{len(obj['verdict'])}）")
    for i, it in enumerate(obj.get("issues", [])):
        if it.get("level") not in LEVEL_ENUM:
            errs.append(f"issues[{i}].level 非法")
        if not it.get("evidence"):
            errs.append(f"issues[{i}].evidence 缺失")
    if not isinstance(obj.get("decomposition"), list) or not obj["decomposition"]:
        errs.append("decomposition 缺失")
    if not isinstance(obj.get("actions"), list) or len(obj["actions"]) < 1:
        errs.append("actions 至少 1 条")
    if not isinstance(obj.get("insufficient"), list) or not obj["insufficient"]:
        errs.append("insufficient 至少 1 条")
    return errs


def generate(version: str, fp: dict, month: str, max_retry: int = 3) -> dict:
    sys_p, user_t = load_prompt(version)
    facts = compact_facts(fp) if version == "v1" else json.dumps(fp, ensure_ascii=False, indent=2)
    user = user_t.replace("{data}", facts).replace("{factpack}", facts)

    raw_set, wan_set = number_sets(fp)
    messages = [{"role": "system", "content": sys_p}, {"role": "user", "content": user}]
    log = []
    final = None
    final_text = ""
    for attempt in range(max_retry):
        r = llm.chat(messages, temperature=0.7 if version == "v1" else 0.3,
                     max_tokens=2400 if version == "v1" else (2000 if version == "v3" else 1500))
        text = r["content"]
        final_text = text
        bad_nums = check_numbers(text, raw_set, wan_set)
        banned = check_banned(text)
        rec = {"attempt": attempt + 1, "latency_ms": r["latency_ms"], "usage": r["usage"],
               "chars": len(text), "mock": r.get("mock", False),
               "ungrounded": bad_nums, "banned": banned, "text": text}
        problems = []
        if version == "v3":
            obj = None
            try:
                body = text.strip()
                if body.startswith("```"):
                    body = re.sub(r"^```[a-zA-Z]*\n?", "", body)
                    body = re.sub(r"\n?```\s*$", "", body)
                obj = json.loads(body)
            except Exception as e:  # noqa: BLE001
                problems.append(f"输出不是合法 JSON：{type(e).__name__}: {e}")
            if obj is not None:
                problems += validate_v3(obj)
                final = obj
        if bad_nums:
            problems.append("以下数字在事实包中查不到出处：" + "、".join(bad_nums[:10]))
        if banned:
            problems.append("出现禁用词：" + "、".join(banned))
        rec["problems"] = problems
        log.append(rec)

        if not problems:
            break
        messages = messages[:2] + [
            {"role": "assistant", "content": text[:1500]},
            {"role": "user", "content": "上面的输出有这些问题，请只输出修正后的完整答案：\n- "
                                        + "\n- ".join(problems[:8])},
        ]

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%H%M%S")
    path = OUT / f"{version}_{month}_{stamp}.md"
    lines = [f"# prompt {version} · {month} · {stamp}", "",
             f"- 尝试次数：{len(log)}",
             f"- 最终是否通过：{'是' if not log[-1]['problems'] else '否'}",
             f"- 耗时：{log[-1]['latency_ms']} ms",
             f"- token：{log[-1]['usage']}",
             "", "## 系统提示词", "```", sys_p, "```",
             "", "## 用户提示词", "```", user[:5000], "```"]
    for rec in log:
        lines += ["", f"## 第 {rec['attempt']} 次返回（{rec['chars']} 字）", "```", rec["text"], "```"]
        if rec["problems"]:
            lines += ["", "**校验未通过：**", ""] + [f"- {p}" for p in rec["problems"]]
    path.write_text("\n".join(lines), encoding="utf-8")

    return {"version": version, "log": log, "final": final, "text": final_text,
            "path": path, "passed": not log[-1]["problems"], "attempts": len(log)}
