@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "MRE_APP_ROOT=%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

rem 优先用随包携带的运行时（便携版），其次用系统 PATH 里的 pythonw
set "PYW=%~dp0python\pythonw.exe"
if not exist "%PYW%" (
  for %%p in (pythonw.exe) do if exist "%%~$PATH:p" set "PYW=%%~$PATH:p"
)

if not exist "%PYW%" (
  echo [ERROR] 找不到 pythonw.exe。
  echo         请安装 Python 3.11/3.12，或使用 Releases 里的便携版。
  pause
  exit /b 1
)

start "" "%PYW%" "%~dp0app_main.py"
