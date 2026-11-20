@echo off
setlocal
cd /d "%~dp0"
echo LongRange Planner - setup
echo.
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo Python is not installed.
  echo Install Python 3.10 or newer from https://www.python.org/downloads/
  echo During setup, tick "Add python.exe to PATH". Then run this file again.
  pause
  exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo Python 3.10 or newer is needed. Install it from https://www.python.org/downloads/
  pause
  exit /b 1
)
if not exist ".venv\Scripts\activate.bat" (
  echo Creating a virtual environment in .venv ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Could not create the virtual environment.
    pause
    exit /b 1
  )
)
call ".venv\Scripts\activate.bat"
echo Installing packages. This takes a few minutes the first time ...
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
if errorlevel 1 (
  echo Package install failed. Check your internet connection and run this file again.
  pause
  exit /b 1
)
echo.
echo Running tests ...
python -m pytest -q
echo.
echo Setup complete. Double-click run_planner.bat to open the dashboard.
pause
