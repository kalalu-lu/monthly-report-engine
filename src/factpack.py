"""
事实包（FactPack）组装

FactPack 是 Stage A 的唯一出口，也是 Stage B（图表推荐 / 版面规划 / 文案生成）的唯一输入。
设计原则：**Stage B 不再回头读原始数据**，所有数字都能在 FactPack 里找到出处，从而支持"数字回查"。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def build(month: str, series: pd.DataFrame, kpis: list[dict], variance: dict,
          flags: list[dict], stores: list[dict], categories: list[dict],
          company: str = "示例连锁茶饮（6 门店）",
          validation: dict | None = None) -> dict:
    months = [m for m in series.index if m <= month][-13:]
    return {
        "meta": {
            "company": company,
            "period": month,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "currency": "CNY",
            "units": {"money": "元", "ratio": "%"},
            "note": "所有数值由程序计算，大模型不得自行推算或补充。",
        },
        "kpis": kpis,
        "variance": variance,
        "anomalies": flags,
        "stores": stores,
        "categories": categories,
        # 数据可信度：校验拦下了多少、命中哪些规则。报告里的"数据质量"段落就读这里，
        # 因此它必须和指标一样属于事实包——否则那一段就成了没有出处的数字。
        "validation": validation or {},
        "trend": {
            "months": months,
            "revenue": [round(float(series.loc[m, "revenue"]), 2) for m in months],
            "revenue_budget": [round(float(series.loc[m, "budget_revenue"]), 2) for m in months],
            "gross_margin": [round(float(series.loc[m, "gross_margin"]) * 100, 2) for m in months],
            "budget_rate": [round(float(series.loc[m, "budget_rate"]) * 100, 2) for m in months],
        },
    }


def dump(factpack: dict, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_jsonable(factpack), ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _jsonable(obj):
    """把 numpy / pandas 标量转成原生 Python 类型，保证 JSON 可序列化。"""
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (bool,)):
        return obj
    if hasattr(obj, "item"):
        try:
            return _jsonable(obj.item())
        except (ValueError, AttributeError):
            pass
    if isinstance(obj, float):
        return None if obj != obj else obj  # NaN → null
    return obj


def flatten_numbers(obj, out: set[str] | None = None) -> set[str]:
    """把 FactPack 中出现的所有数字收集成一个集合，供文案生成阶段的"数字回查"使用。"""
    if out is None:
        out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("meta",):
                continue
            flatten_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            flatten_numbers(v, out)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        f = float(obj)
        out.add(f"{abs(f):.2f}")
        out.add(f"{abs(f):.1f}")
        out.add(f"{abs(f):.0f}")
        out.add(f"{abs(f):g}")
    elif isinstance(obj, str):
        for s in NUM_RE.findall(obj):
            try:
                f = float(s)
            except ValueError:
                continue
            out.add(f"{abs(f):.2f}")
            out.add(f"{abs(f):g}")
    return out
