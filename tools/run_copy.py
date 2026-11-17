"""
三代提示词对比实验（Stage B 第三步的评测）

跑 v1 / v2 / v3，逐项统计：
  字数、耗时、token、越界数字数、禁用词数、是否通过校验、尝试次数

运行：python tools/run_copy.py 2025-10
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import narrative as copymod  # noqa: E402


def main(month: str = "2025-10") -> None:
    fp = json.loads((ROOT / "outputs" / f"factpack_{month}.json").read_text(encoding="utf-8"))
    print("=" * 78)
    print(f"提示词三代对比实验    报告期：{month}")
    print("=" * 78)

    rows = []
    for v in ("v1", "v2", "v3"):
        r = copymod.generate(v, fp, month)
        last = r["log"][-1]
        rows.append({
            "版本": v,
            "尝试": r["attempts"],
            "字数": last["chars"],
            "耗时ms": last["latency_ms"],
            "输出token": last["usage"].get("completion_tokens", "-"),
            "越界数字": len(last["ungrounded"]),
            "禁用词": len(last["banned"]),
            "通过": "是" if r["passed"] else "否",
        })
        print(f"\n--- {v} ---")
        print(f"尝试 {r['attempts']} 次，{last['chars']} 字，{last['latency_ms']} ms，"
              f"输出 token {last['usage'].get('completion_tokens','-')}，"
              f"通过={'是' if r['passed'] else '否'}")
        if last["ungrounded"]:
            print(f"  越界数字 {len(last['ungrounded'])} 个：{'、'.join(last['ungrounded'][:8])}")
        if last["banned"]:
            print(f"  禁用词：{'、'.join(last['banned'])}")
        if last["problems"]:
            for p in last["problems"][:3]:
                print(f"  问题：{p[:120]}")
        print(f"  存档：{r['path'].relative_to(ROOT)}")

    print("\n" + "=" * 78)
    print(f"{'版本':<6}{'尝试':<6}{'字数':<8}{'耗时ms':<10}{'输出token':<12}{'越界数字':<10}{'禁用词':<8}{'通过':<6}")
    for r in rows:
        print(f"{r['版本']:<6}{r['尝试']:<6}{r['字数']:<8}{r['耗时ms']:<10}"
              f"{str(r['输出token']):<12}{r['越界数字']:<10}{r['禁用词']:<8}{r['通过']:<6}")

    lines = [f"提示词三代对比    报告期：{month}", "",
             f"{'版本':<6}{'尝试':<6}{'字数':<8}{'耗时ms':<10}{'输出token':<12}{'越界数字':<10}{'禁用词':<8}{'通过':<6}"]
    for r in rows:
        lines.append(f"{r['版本']:<6}{r['尝试']:<6}{r['字数']:<8}{r['耗时ms']:<10}"
                     f"{str(r['输出token']):<12}{r['越界数字']:<10}{r['禁用词']:<8}{r['通过']:<6}")
    (ROOT / "outputs/logs").mkdir(parents=True, exist_ok=True)
    (ROOT / "outputs/logs/copy_compare.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n已保存：outputs/logs/copy_compare.txt")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2025-10")
