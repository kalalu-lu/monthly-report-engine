"""
打包「便携版」（绿色包）——不产生任何 .exe，绕过 SmartScreen / SAC 对未签名程序的拦截。

做法：把 Python 运行时 + 本程序 + 依赖库一起放进一个文件夹，附带 run.bat。
用户解压后双击 run.bat 即可，无需安装 Python 或任何库。

为什么能绕开：包里执行的是 pythonw.exe，而它带有有效的数字签名；
我们自己的代码都是 .py，不涉及新建可执行文件。

用法：
    python tools/make_portable.py --python-dir "<运行时目录>" [--out "<输出目录>"]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_NAME = "便携版_月报引擎_v1.0"

# 项目里不进包的东西
SKIP_DIRS = {"__pycache__", ".venv", "build", "dist", ".git", "data/imports",
             "outputs/qa", "tests", "docs"}
SKIP_SUFFIX = {".exe", ".pyc", ".zip", ".spec"}
SKIP_FILES = {"月报引擎.exe", ".env", ".gitignore", "report.bat",
              "打包exe.bat", "启动月报引擎.vbs"}
SKIP_PREFIX = ("截图",)

# 运行时里可以省掉的东西（不影响本程序）
RUNTIME_SKIP = [
    "Lib/test", "Lib/idlelib", "Lib/turtledemo", "Lib/ensurepip",
    "site-packages/pip", "site-packages/setuptools", "site-packages/pkg_resources",
    "site-packages/PyInstaller", "site-packages/_pyinstaller_hooks_contrib",
    "site-packages/pyinstaller_hooks_contrib", "site-packages/altgraph",
    "site-packages/pefile.py", "site-packages/pefile", "site-packages/pywin32_ctypes",
    "site-packages/pyi_splash", "site-packages/pyi_splash_tk",
]

RUN_BAT = r"""@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"
set "PYDIR=%HERE%\python"
if not exist "%PYDIR%\pythonw.exe" (
  echo [ERROR] python runtime not found: %PYDIR%
  pause
  exit /b 1
)

rem Chromium cannot be launched by a python.exe living under a non-ASCII path
rem (it hangs forever with no error). If the bundle sits in such a path,
rem copy the runtime once to %LOCALAPPDATA% and launch from there.
for /f "usebackq delims=" %%r in (`powershell -NoProfile -Command "$p='%HERE%'; if ((($p.ToCharArray()) | Where-Object {[int]$_ -gt 127}).Count -gt 0) {'NO'} else {'YES'}"`) do set "ASCIIPATH=%%r"

if /i "!ASCIIPATH!"=="NO" (
  set "PYDIR=%LOCALAPPDATA%\MonthlyReport\py"
  if not exist "!PYDIR!\pythonw.exe" (
    echo Bundle path contains non-ASCII characters.
    echo Copying Python runtime to !PYDIR!  ^(one time only, about 130 MB^) ...
    robocopy "%HERE%\python" "!PYDIR!" /E /NFL /NDL /NJH /NJS /NP >nul
    echo Done.
  )
)

set "MRE_APP_ROOT=%HERE%\"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
start "" "!PYDIR!\pythonw.exe" "%HERE%\app_main.py"
"""

RUN_CONSOLE_BAT = r"""@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "MRE_APP_ROOT=%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
"%~dp0python\python.exe" "%~dp0app_main.py"
echo.
pause
"""

SET_KEY_BAT = r"""@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
echo ============================================================
echo   DeepSeek API Key  (optional)
echo ============================================================
echo Paste your key below (starts with sk-), then press Enter.
echo Leave empty and just press Enter to skip.
echo.
set "KEY="
set /p KEY=Key: 
if not defined KEY (
  echo.
  echo [SKIPPED] No key entered. The app still works without it.
  pause
  exit /b 0
)
set "KEY=%KEY: =%"
> ".env" (
  echo # local config - DO NOT COMMIT
  echo DEEPSEEK_API_KEY=%KEY%
  echo DEEPSEEK_MODEL=deepseek-chat
  echo DEEPSEEK_BASE_URL=https://api.deepseek.com
)
echo.
echo [OK] Saved to %~dp0.env
echo.
"%~dp0python\python.exe" tools\check_env.py
echo.
pause
"""

README = """月报引擎 便携版 v1.0
==================================================
经营月报自动生成系统 —— 选数据、点生成、出 PDF 月报。

【怎么用】
1. 解压本压缩包到任意目录（建议路径不带空格，例如 D:\\月报引擎）
2. 双击 run.bat
3. 界面里：选数据源 → 选报告期 → 点「生成月报」
4. 生成的 PDF 在 outputs\\ 下，程序会自动打开

【不用装 Python】
包里自带 Python 运行时（python\\ 目录）和全部依赖库，
解压即可运行，不需要安装任何东西，也不会写入注册表。

【想用自己的数据】
1. 界面里点「下载数据模板（Excel）」
2. 按 5 个 sheet 填数（sales / budget / expenses / dim_store / dim_category）
3. 把 5 张表放进同一个文件夹，界面里选它，再选月份，点生成

【想接大模型】
默认会用大模型写结论与建议，需要填 API 密钥：
  双击 set_key.bat，粘贴密钥回车即可（约 0.02 元/次）
不填也能用：会复用上次已校验通过的文案，或退回程序模板。

【出问题了】
双击 run_console.bat，窗口里会保留完整报错信息。
也可以看 outputs\\logs\\ 下的日志与拦截清单。

【目录说明】
  run.bat            启动界面（无控制台窗口）
  run_console.bat    启动界面（保留控制台，排错用）
  set_key.bat        配置 API 密钥
  python\\            内置 Python 运行时（3.12）
  src\\ tools\\        程序代码
  prompts\\           提示词模板
  data\\raw\\         内置示例数据（6 门店 × 8 品类 × 24 个月）
  assets\\            图标
  outputs\\           生成结果（PDF / HTML / 图表 / 日志）
  示例月报_2025-10.pdf  已经生成好的一份成品，可先看效果

【许可】
仅用于教学与内部演示；内置示例数据由脚本生成，不含任何真实企业数据。
"""


def copy_runtime(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in {"Scripts", "include", "libs"} and item.is_dir():
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(item, target)
    for rel in RUNTIME_SKIP:
        p = dst / rel
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()


def copy_app(dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in ROOT.iterdir():
        rel = item.name
        if rel in SKIP_DIRS or rel in SKIP_FILES or item.suffix in SKIP_SUFFIX:
            continue
        if rel.startswith(SKIP_PREFIX) or item.name.startswith("~$"):
            continue
        target = dst / item.name
        if item.is_dir():
            if item.name == "outputs":
                (target / "logs").mkdir(parents=True, exist_ok=True)
                (target / "llm").mkdir(parents=True, exist_ok=True)
                (target / "charts").mkdir(parents=True, exist_ok=True)
                continue
            shutil.copytree(item, target, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.exe"))
        else:
            shutil.copy2(item, target)

    # 附一份成品，用户先看效果
    sample = ROOT / "outputs" / "report_2025-10.pdf"
    if sample.exists():
        shutil.copy2(sample, dst / "示例月报_2025-10.pdf")


def write_texts(dst: Path) -> None:
    # .bat 必须是 ASCII 内容，否则 cmd 会按 ANSI 解析导致乱码
    (dst / "run.bat").write_text(RUN_BAT, encoding="ascii", newline="\r\n")
    (dst / "run_console.bat").write_text(RUN_CONSOLE_BAT, encoding="ascii", newline="\r\n")
    (dst / "set_key.bat").write_text(SET_KEY_BAT, encoding="ascii", newline="\r\n")
    (dst / "使用说明.txt").write_text(README, encoding="utf-8-sig", newline="\r\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python-dir", required=True, help="内置运行时的目录")
    ap.add_argument("--out", default=str(ROOT.parent / "便携版构建"))
    ap.add_argument("--no-runtime", action="store_true", help="只装程序，不复制运行时（调试用）")
    args = ap.parse_args()

    py = Path(args.python_dir)
    if not (py / "python.exe").exists():
        print(f"[错误] 不是有效的 Python 运行时目录：{py}")
        return 1

    out_root = Path(args.out)
    bundle = out_root / BUNDLE_NAME
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)

    print(f"[1/3] 复制程序到 {bundle.name} …")
    copy_app(bundle)
    if not args.no_runtime:
        print("[2/3] 复制 Python 运行时（约 130 MB）…")
        copy_runtime(py, bundle / "python")
    else:
        print("[2/3] 跳过运行时")

    print("[3/3] 写启动脚本与说明 …")
    write_texts(bundle)

    total = sum(f.stat().st_size for f in bundle.rglob("*") if f.is_file())
    print(f"\n完成：{bundle}")
    print(f"体积：{total / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
