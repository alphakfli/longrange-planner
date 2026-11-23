@echo off
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
echo Building the static site ...
%PY% scripts\build_site.py
if errorlevel 1 (
  echo Build failed. Run install_windows.bat first.
  pause
  exit /b 1
)
echo Opening http://localhost:8000 - the first load takes 20 to 40 seconds.
start "" http://localhost:8000
%PY% -m http.server 8000 -d site
