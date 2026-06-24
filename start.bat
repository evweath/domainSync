@echo off
REM ============================================================
REM  Donut Intel - Start the App (Windows)
REM  Double-click to turn the app on. Keep this window open.
REM ============================================================
title Donut Intel - Server (keep this window open)
cd /d "%~dp0"

REM --- Make sure Python is installed ---
python --version >nul 2>&1
if errorlevel 1 (
  echo [PROBLEM] Python was not found. Please run setup.bat first.
  pause
  exit /b 1
)

REM --- Make sure setup has been run ---
if not exist ".venv" (
  echo [PROBLEM] The app is not set up yet.
  echo Please double-click  setup.bat  first.
  pause
  exit /b 1
)

REM --- Read the web address (port) from the settings file (uses the app's
REM     private Python, which has the needed packages) ---
set "PORT=8800"
for /f "delims=" %%P in ('.venv\Scripts\python -c "import yaml;print(yaml.safe_load(open('config/settings.yaml'))['app']['port'])" 2^>nul') do set "PORT=%%P"

echo Starting Donut Intel...
echo.
echo    Open this address in your web browser:
echo        https://localhost:%PORT%
echo.
echo    To STOP the app: press Ctrl+C, or just close this window.
echo.

REM --- Open the browser automatically a few seconds after the server boots ---
start "" /min cmd /c "timeout /t 6 >nul & start https://localhost:%PORT%/"

REM --- Run the server with the app's private Python (it has uvicorn, etc.) ---
.venv\Scripts\python start.py
pause
