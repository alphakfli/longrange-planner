@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
echo Opening LongRange Planner in your browser. Close this window to stop it.
streamlit run app\streamlit_app.py
pause
