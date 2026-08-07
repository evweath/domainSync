@echo off
REM ============================================================
REM  Donut Intel - First-Time Setup (Windows)
REM  Double-click this file ONE TIME.
REM
REM  This script is fully automatic. On a brand-new Windows
REM  computer it will:
REM    1. Find Python, or download and install it for you
REM       (and add it to the PATH system variable)
REM    2. Install all the software the app needs
REM    3. Download the browser engines the app uses
REM    4. Create security certificates (if missing)
REM    5. Put a "Donut Intel" shortcut on your Desktop
REM
REM  You do NOT need to install anything by hand first.
REM  You only need an internet connection.
REM ============================================================
title Donut Intel - Setup
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM ------------------------------------------------------------
REM  Safety check: this script must NOT run from inside the ZIP
REM  file's temporary preview folder. If it does, anything it
REM  installs would be deleted when the window closes.
REM ------------------------------------------------------------
echo %~dp0 | findstr /I /C:"\Temp\" >nul
if not errorlevel 1 (
  echo ============================================================
  echo    STOP - the ZIP file has not been extracted yet
  echo ============================================================
  echo.
  echo It looks like you double-clicked setup.bat from INSIDE the
  echo ZIP file. That cannot work - Windows would delete everything
  echo the setup installs.
  echo.
  echo Please do this first:
  echo    1. Close this window.
  echo    2. Right-click DonutIntel-Windows.zip
  echo    3. Choose "Extract All..." and extract to  C:\
  echo    4. Open the new  C:\DonutIntel  folder
  echo    5. Double-click setup.bat there.
  echo.
  pause
  exit /b 1
)

echo ============================================================
echo    Donut Intel - First-Time Setup
echo ============================================================
echo.
echo This will install everything the app needs.
echo It can take 10 to 20 minutes on a new computer.
echo Please keep this window open.
echo.

REM ------------------------------------------------------------
REM  Step 1: Find a real Python (3.11 or newer).
REM  Note: a fresh Windows PC often has a FAKE "python" command
REM  (a Microsoft Store stub in the WindowsApps folder). We skip
REM  that stub on purpose.
REM ------------------------------------------------------------
set "PYEXE="

REM --- Try the Python launcher first (only exists with a real install) ---
REM     Accept only Python 3.11-3.13: several app dependencies do not have
REM     pre-built packages for 3.14+ yet, so we install 3.12 in that case.
py -3 -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)" >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
)

REM --- Try python on PATH, skipping the Microsoft Store stub ---
if not defined PYEXE (
  for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PYEXE (
      echo %%P | findstr /I /C:"WindowsApps" >nul
      if errorlevel 1 (
        "%%P" -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)" >nul 2>&1
        if not errorlevel 1 set "PYEXE=%%P"
      )
    )
  )
)

REM --- Try the standard per-user install location ---
if not defined PYEXE (
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  )
)

REM ------------------------------------------------------------
REM  Step 2: If no Python was found, download and install it
REM  automatically (per-user, added to PATH).
REM ------------------------------------------------------------
if not defined PYEXE (
  echo A suitable Python ^(version 3.11 to 3.13^) was not found.
  echo Downloading and installing Python 3.12 automatically...
  echo ^(If you have a newer Python like 3.14, it will be left alone.^)
  echo.

  set "PYVER=3.12.10"
  if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
    set "INSTALLER=python-!PYVER!-arm64.exe"
  ) else if /i "%PROCESSOR_ARCHITECTURE%"=="AMD64" (
    set "INSTALLER=python-!PYVER!-amd64.exe"
  ) else (
    echo [PROBLEM] This app requires 64-bit Windows.
    pause
    exit /b 1
  )
  set "PYURL=https://www.python.org/ftp/python/!PYVER!/!INSTALLER!"
  set "OUTFILE=%TEMP%\!INSTALLER!"

  echo Downloading !PYURL!
  powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '!PYURL!' -OutFile '!OUTFILE!' -UseBasicParsing"
  if errorlevel 1 (
    echo.
    echo [PROBLEM] Could not download Python. Check your internet
    echo connection, then double-click setup.bat again.
    pause
    exit /b 1
  )

  echo Installing Python ^(this takes a few minutes^)...
  start "" /wait "!OUTFILE!" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1 AssociateFiles=0 Shortcuts=0
  if errorlevel 1 (
    echo.
    echo [PROBLEM] The Python installer did not finish correctly.
    echo Try right-clicking setup.bat and choosing "Run as administrator".
    pause
    exit /b 1
  )
  del "!OUTFILE!" >nul 2>&1

  set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  if not exist "!PYEXE!" (
    echo.
    echo [PROBLEM] Python was installed but could not be found at
    echo   !PYEXE!
    echo Please restart the computer, then double-click setup.bat again.
    pause
    exit /b 1
  )
  echo Python installed successfully and added to PATH.
  echo.
)

echo Using Python: %PYEXE%
"%PYEXE%" --version
echo.

REM ------------------------------------------------------------
REM  Step 3: Run the app's own setup (virtual environment,
REM  dependencies, browser engines, certificates, desktop shortcut)
REM ------------------------------------------------------------
"%PYEXE%" setup_env.py
if errorlevel 1 (
  echo.
  echo [PROBLEM] Setup did not finish. Scroll up to read the message above.
  echo You can safely double-click setup.bat again to retry.
  echo.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo    Setup finished!
echo.
echo    A "Donut Intel" shortcut is now on your Desktop.
echo    Double-click it (or start.bat) to run the app.
echo ============================================================
echo.
pause
