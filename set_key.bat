@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set "PY=%~dp0python\python.exe"
if not exist "%PY%" (
  for %%p in (python.exe) do if exist "%%~$PATH:p" set "PY=%%~$PATH:p"
)
if not exist "%PY%" (
  echo [ERROR] 找不到 python.exe，请先安装 Python 3.11/3.12。
  pause
  exit /b 1
)

echo ============================================================
echo   DeepSeek API Key Setup (optional)
echo ============================================================
echo Paste your key below (it starts with sk-), then press Enter.
echo Leave empty and press Enter to skip - the app still works
echo without a key (it reuses the last verified wording).
echo.
set "KEY="
set /p KEY=Key: 

if not defined KEY (
  echo.
  echo [SKIPPED] No key entered.
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
"%PY%" tools\check_env.py
echo.
pause
