"""
DeepSeek 客户端（纯标准库 urllib，不依赖 requests / openai SDK）

为什么不用官方 SDK：本机 Python 3.15 装 pandas 时 C 扩展被系统应用控制策略拦截，
为降低风险，Stage B 的所有外部调用都用标准库实现，零第三方依赖。

接口：
  load_env()            -> 读取 .env（或环境变量）里的 key
  is_available()        -> 是否配置了 key
  chat(messages, ...)   -> 返回 {content, usage, latency_ms, model}
  MOCK                  -> 未配置 key 时返回占位文案，保证流水线仍可跑通
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from src import paths

PROJECT_ROOT = paths.app_root()
ENV_FILE = PROJECT_ROOT / ".env"

DEFAULTS = {
    "DEEPSEEK_API_KEY": "",
    "DEEPSEEK_MODEL": "deepseek-chat",
    "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
}


def _parse_env_file(path: Path) -> dict:
    data = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        data[k.strip()] = v
    return data


def load_env() -> dict:
    env = dict(DEFAULTS)
    env.update(_parse_env_file(ENV_FILE))
    for k in DEFAULTS:
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def is_available() -> bool:
    return bool(load_env()["DEEPSEEK_API_KEY"].strip())


def chat(messages: list[dict], temperature: float = 0.3, max_tokens: int = 1200,
         timeout: int = 90, retries: int = 2) -> dict:
    """调用 chat/completions，返回统一结构。未配置 key 时返回 mock 结果。"""
    env = load_env()
    key = env["DEEPSEEK_API_KEY"].strip()
    if not key:
        return {
            "content": "[MOCK] 未配置 DEEPSEEK_API_KEY，这里是占位输出。",
            "usage": {}, "latency_ms": 0, "model": "mock", "mock": True,
        }

    url = env["DEEPSEEK_BASE_URL"].rstrip("/") + "/chat/completions"
    body = json.dumps({
        "model": env["DEEPSEEK_MODEL"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }, ensure_ascii=False).encode("utf-8")

    last_err = None
    for attempt in range(retries + 1):
        t0 = time.time()
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return {
                "content": data["choices"][0]["message"]["content"],
                "usage": data.get("usage", {}),
                "latency_ms": int((time.time() - t0) * 1000),
                "model": data.get("model", env["DEEPSEEK_MODEL"]),
                "mock": False,
            }
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:400]
            last_err = f"HTTP {e.code}: {detail}"
            if e.code in (401, 403):
                break
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"DeepSeek 调用失败（重试 {retries} 次）：{last_err}")
