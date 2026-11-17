"""
统一路径解析：让同一套代码在「源码运行」和「打包成 exe 运行」两种形态下都正确。

两种目录：
  app_root()  可写目录 —— 输出、日志、.env 放这里。
              源码运行时是项目根目录；exe 运行时是 exe 所在目录。
  res_root()  只读资源目录 —— 提示词、内置示例数据、图标放这里。
              源码运行时与 app_root 相同；exe 运行时是 PyInstaller 的解压目录（临时、只读）。

约定：一切"写"走 app_root()，一切"读的静态资源"走 res_root()。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ENV_APP_ROOT = "MRE_APP_ROOT"


def app_root() -> Path:
    env = os.environ.get(ENV_APP_ROOT)
    if env:
        return Path(env).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def res_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass).resolve()
    return app_root()


def ensure_dirs() -> Path:
    root = app_root()
    for sub in ("outputs", "outputs/logs", "outputs/llm", "outputs/charts", "data/clean", "data/ref"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root
