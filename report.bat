@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

rem 优先用随包运行时，其次 py 启动器，最后 PATH 里的 python
set "PY=%~dp0python\python.exe"
if not exist "%PY%" (
  for %%p in (python.exe) do if exist "%%~$PATH:p" set "PY=%%~$PATH:p"
)

if not exist "%PY%" (
  echo [ERROR] 找不到 python.exe。
  echo         请安装 Python 3.11/3.12，或使用 Releases 里的便携版。
  pause
  exit /b 1
)

set "MONTH=%~1"
if "%MONTH%"=="" set "MONTH=2025-10"

echo [Interpreter] %PY%
echo [Month] %MONTH%
echo.
echo ==== 1/2 出稿：DSL -^> 约束求解 -^> HTML -^> PDF ====
"%PY%" tools\build_report.py %MONTH%
if errorlevel 1 goto :fail
echo.
echo ==== 2/2 评测：约束 / 溢出 / 数字回查 / PDF 质检 ====
"%PY%" tools\eval_report.py %MONTH%
if errorlevel 1 goto :fail
echo.
pause
exit /b 0

:fail
echo.
echo [ERROR] 出稿或评测失败，详见上方输出。
pause
exit /b 1
