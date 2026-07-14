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

REM --- Free the port so the app can always start ---
REM     Automatically kill anything already listening on %PORT% (e.g. a
REM     leftover server from a previous run). No prompts, no questions.
call :free_port %PORT%

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
exit /b 0

REM ============================================================
REM  :free_port  <port>
REM  Kill every process currently LISTENING on the given TCP port
REM  so this app can bind it. Runs silently and never prompts.
REM ============================================================
:free_port
setlocal
set "TARGET=%~1"
if "%TARGET%"=="" goto :free_port_done
REM Find PIDs holding the port (IPv4 + IPv6, only LISTENING sockets).
for /f "tokens=5" %%a in ('netstat -ano -p tcp ^| findstr /R /C:":%TARGET% .*LISTENING"') do (
  if not "%%a"=="0" (
    echo Freeing port %TARGET% ^(stopping process %%a^)...
    taskkill /F /PID %%a >nul 2>&1
  )
)
:free_port_done
endlocal
exit /b 0
