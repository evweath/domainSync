@echo off
REM ============================================================
REM  Donut Intel - First-Time Setup (Windows)
REM  Double-click this file ONE TIME to install everything.
REM ============================================================
title Donut Intel - Setup
cd /d "%~dp0"

echo ============================================================
echo    Donut Intel - First-Time Setup
echo ============================================================
echo.

REM --- Make sure Python is installed and on the PATH ---
python --version >nul 2>&1
if errorlevel 1 (
  echo [PROBLEM] Python was not found on this computer.
  echo.
  echo Please install Python 3.11 or 3.12 first:
  echo     https://www.python.org/downloads/windows/
  echo.
  echo IMPORTANT: during the install, check the box that says
  echo     "Add python.exe to PATH"
  echo Then run this setup.bat again.
  echo.
  pause
  exit /b 1
)

echo Found Python:
python --version
echo.
echo This will download and install everything the app needs.
echo It can take 5 to 15 minutes. Please keep this window open.
echo.
pause

python setup_env.py
if errorlevel 1 (
  echo.
  echo [PROBLEM] Setup did not finish. Scroll up to read the message in red.
  echo See the Troubleshooting section of the user guide for help.
  echo.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo    Setup finished!
echo    Next step: double-click  start.bat  to run the app.
echo ============================================================
echo.
pause
