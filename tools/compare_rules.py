"""
异常规则消融实验：v1（只看环比） vs v2（引入同比确认）

这是给报告 3.2 用的对照证据：
  v1 把茶饮的季节性回落误判为经营恶化，6 家门店全线报警；
  v2 要求"同比同时为负"才报警，误报清零，只留下真正出问题的五道口店。

运行：python tools/compare_rules.py
输出：终端打印 + outputs/logs/rules_compare.txt
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MONTH = "2025-10"


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    fact = pd.read_csv(ROOT / "data/clean/fact_table.csv", encoding="utf-8-sig")
    stores = pd.read_csv(ROOT / "data/raw/dim_store.csv", encoding="utf-8-sig")
    return fact, stores


def matrices(fact: pd.DataFrame):
    rev = fact.groupby(["month", "store_id"])["revenue"].sum().unstack("store_id").sort_index()
    return rev, rev.pct_change(), rev.pct_change(12)


def rules_v1(rev, mom, yoy, name_of, month):
    """v1：只看环比。R01 公司环比 / R02 单店环比 / R03 单店连续三月下滑"""
    out = []
    months = list(rev.index)
    i = months.index(month)
    total = rev.sum(axis=1)
    if total.pct_change().loc[month] < -0.08:
        out.append(("R01", "公司营收环比下滑", "环比 %.2f%%" % (total.pct_change().loc[month] * 100)))
    for sid in rev.columns:
        m = mom.loc[month, sid]
        if pd.notna(m) and m < -0.10:
            out.append(("R02", f"{name_of[sid]}环比下滑", "环比 %.2f%%" % (m * 100)))
    if i >= 2:
        last3 = months[i - 2:i + 1]
        for sid in rev.columns:
            v = [rev.loc[x, sid] for x in last3]
            if any(pd.isna(x) for x in v):
                continue
            if v[0] > v[1] > v[2] and (v[2] / v[0] - 1) < -0.05:
                out.append(("R03", f"{name_of[sid]}连续三月下滑",
                            "累计 %.2f%%" % ((v[2] / v[0] - 1) * 100)))
    return out


def rules_v2(rev, mom, yoy, name_of, month):
    """v2：环比 + 同比确认；R03 改为同比链"""
    out = []
    months = list(rev.index)
    i = months.index(month)
    total = rev.sum(axis=1)
    if total.pct_change().loc[month] < -0.08 and total.pct_change(12).loc[month] < -0.02:
        out.append(("R01", "公司营收环比下滑且同比转负", "环比 %.2f%%" % (total.pct_change().loc[month] * 100)))
    for sid in rev.columns:
        m, y = mom.loc[month, sid], yoy.loc[month, sid]
        if pd.notna(m) and pd.notna(y) and m < -0.10 and y < -0.02:
            out.append(("R02", f"{name_of[sid]}环比大幅下滑",
                        "环比 %.2f%% / 同比 %.2f%%" % (m * 100, y * 100)))
    if i >= 2:
        last3 = months[i - 2:i + 1]
        for sid in rev.columns:
            yv = [yoy.loc[x, sid] for x in last3]
            if any(pd.isna(x) for x in yv):
                continue
            if all(x < -0.05 for x in yv):
                out.append(("R03", f"{name_of[sid]}连续三月同比下滑",
                            "同比 " + " / ".join("%.1f%%" % (x * 100) for x in yv)))
    return out


def main() -> None:
    fact, stores = load()
    name_of = dict(zip(stores["store_id"], stores["store_name"]))
    rev, mom, yoy = matrices(fact)

    v1 = rules_v1(rev, mom, yoy, name_of, MONTH)
    v2 = rules_v2(rev, mom, yoy, name_of, MONTH)

    # 人为注入的真实问题：只有五道口店在 8/9/10 月连续下滑
    truth = "五道口店"

    def hit(flags):
        return sum(1 for f in flags if truth in f[1])

    lines = []
    lines.append("=" * 72)
    lines.append(f"异常规则消融实验    报告期：{MONTH}")
    lines.append("=" * 72)
    for tag, flags, desc in (("v1 只看环比", v1, "R01 环比 / R02 环比 / R03 环比链"),
                             ("v2 环比+同比确认", v2, "R02 加同比为负 / R03 改同比链")):
        lines.append("")
        lines.append(f"--- {tag}（{desc}）---")
        lines.append(f"命中 {len(flags)} 条：")
        for rid, title, detail in flags:
            lines.append(f"   [{rid}] {title}   （{detail}）")
        lines.append(f"其中指向真实问题（{truth}）的：{hit(flags)} 条；"
                     f"其余 {len(flags) - hit(flags)} 条为误报")

    lines.append("")
    lines.append("=" * 72)
    lines.append(f"{'规则版本':<18}{'报警数':<8}{'命中真实问题':<14}{'误报数':<8}{'误报率':<10}")
    for tag, flags in (("v1 只看环比", v1), ("v2 环比+同比确认", v2)):
        h = hit(flags)
        miss = len(flags) - h
        rate = f"{miss / len(flags) * 100:.0f}%" if flags else "-"
        lines.append(f"{tag:<18}{len(flags):<8}{h:<14}{miss:<8}{rate:<10}")
    lines.append("=" * 72)

    text = "\n".join(lines)
    print(text)
    (ROOT / "outputs/logs").mkdir(parents=True, exist_ok=True)
    (ROOT / "outputs/logs/rules_compare.txt").write_text(text, encoding="utf-8")
    print("\n已保存：outputs/logs/rules_compare.txt")


if __name__ == "__main__":
    main()
