@echo off
setlocal
cd /d "%~dp0"
echo Push LongRange Planner to GitHub (alphakfli/longrange-planner)
echo.
where git >nul 2>&1
if errorlevel 1 (
  echo Git is not installed. Install it from https://git-scm.com/download/win
  echo then run this file again.
  pause
  exit /b 1
)
rem Check for secrets, personal data and real company names before anything leaves this PC
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY ( where py >nul 2>&1 && set "PY=py -3" )
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if defined PY (
  %PY% scripts\check_sensitive.py
  if errorlevel 1 (
    echo.
    echo Push stopped: fix the items above first, or send this message to Claude.
    pause
    exit /b 1
  )
)
git config --global --add safe.directory "%CD:\=/%" >nul 2>&1
rem Commit any changes first
git add -A
git diff --cached --quiet
if errorlevel 1 (
  set "MSG=Add order management, planning data health, supply review and IBP export (0.3.0)"
  set /p "MSG=Commit message (press Enter to use the default): "
  call git commit -m "%%MSG%%"
)
git remote get-url origin >nul 2>&1
if errorlevel 1 (
  git remote add origin https://github.com/alphakfli/longrange-planner.git
) else (
  git remote set-url origin https://github.com/alphakfli/longrange-planner.git
)
echo A browser window may open to sign in to GitHub. Sign in, then come back here.
git push -u origin main
if errorlevel 1 (
  echo.
  echo The push did not finish. Copy the message above and send it to Claude.
  pause
  exit /b 1
)
echo.
echo Done. Your code is on https://github.com/alphakfli/longrange-planner
pause
