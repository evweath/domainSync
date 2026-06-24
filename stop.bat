@echo off
REM ============================================================
REM  Donut Intel - Stop the App (Windows)
REM  Double-click to turn the app off.
REM ============================================================
title Donut Intel - Stop
cd /d "%~dp0"

REM Use the app's private Python (it has the packages stop.py needs)
if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python stop.py
) else (
  python stop.py
)
echo.
pause
