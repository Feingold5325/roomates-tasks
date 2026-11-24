@echo off
REM Double-click this file to open the roommates system in the browser.
REM Keep this window open while using the system. Close it to stop.
cd /d "%~dp0"
echo Starting the roommates system... the browser will open in a few seconds.
echo Keep this window open while you use the system. Close it to stop.
REM Open the browser after a short delay (the server needs a few seconds to start)
start "" cmd /c "timeout /t 6 /nobreak >nul & start http://localhost:8501"
python -m streamlit run app.py
if errorlevel 1 (
  echo.
  echo Something went wrong. Make sure Python is installed and run:
  echo     python -m pip install -r requirements.txt
  pause
)
