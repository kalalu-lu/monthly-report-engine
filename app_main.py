"""
打包入口（PyInstaller 用）

源码运行时它等价于 `python -m src.gui`；打包后它负责：
  1. 把"可写根目录"指向 exe 所在目录（输出、日志、.env 都在那儿，用户看得见）
  2. 建好必要目录
  3. 拉起图形界面
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def bootstrap() -> None:
    # 控制台是 GBK 时，日志里的 ✓ / ✗ 等符号会直接抛 UnicodeEncodeError。
    # 入口处统一把标准流改成 UTF-8，避免整程序因为一个字符崩掉。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    if getattr(sys, "frozen", False):
        os.environ.setdefault("MRE_APP_ROOT", str(Path(sys.executable).resolve().parent))
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    tools = here / "tools"
    if tools.exists() and str(tools) not in sys.path:
        sys.path.append(str(tools))


def main() -> None:
    bootstrap()
    from src import paths

    paths.ensure_dirs()
    from src.gui import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
