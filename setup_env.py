#!/usr/bin/env python3
"""
Cross-platform setup script for Donut Intel Platform.
Works on macOS and Windows.
Usage: python setup_env.py

For macOS auto-start (LaunchAgent), use setup_macos.sh instead.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
VENV = ROOT / '.venv'
BIN = VENV / ('Scripts' if sys.platform == 'win32' else 'bin')


def run(cmd: list) -> None:
    print(f'  $ {" ".join(str(c) for c in cmd)}')
    subprocess.run(cmd, check=True, cwd=ROOT)


def step(n: int, total: int, label: str) -> None:
    print(f'\n[{n}/{total}] {label}')


def create_dirs() -> None:
    for d in ('data', 'logs', 'exports', 'certs'):
        (ROOT / d).mkdir(exist_ok=True)


# Supported Python range: dependencies ship pre-built wheels for 3.11–3.13.
PY_MIN = (3, 11)
PY_MAX_EXCLUSIVE = (3, 14)


def _venv_python_ok() -> bool:
    """True if the existing venv's Python is in the supported range."""
    exe = BIN / 'python.exe' if sys.platform == 'win32' else BIN / 'python'
    if not exe.exists():
        return False
    try:
        out = subprocess.run(
            [str(exe), '-c',
             'import sys; print(".".join(map(str, sys.version_info[:2])))'],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        major, minor = (int(x) for x in out.split('.')[:2])
        return PY_MIN <= (major, minor) < PY_MAX_EXCLUSIVE
    except Exception:
        return False


def create_venv() -> None:
    if VENV.exists():
        if _venv_python_ok():
            print('  Virtual environment already exists — skipping.')
            return
        # The venv was built with an unsupported Python (e.g. 3.14, which
        # several dependencies don't have pre-built packages for yet).
        # Delete it and rebuild with the current interpreter.
        print('  Existing virtual environment uses an unsupported Python — recreating it.')
        import shutil
        shutil.rmtree(VENV, ignore_errors=True)
    run([sys.executable, '-m', 'venv', str(VENV)])


def install_deps() -> None:
    # NOTE: on Windows, "pip.exe install --upgrade pip" refuses to modify
    # itself — it must go through "python -m pip".
    run([str(BIN / 'python'), '-m', 'pip', 'install', '--upgrade', 'pip'])
    run([str(BIN / 'python'), '-m', 'pip', 'install', '-r', 'requirements.txt'])


def install_playwright() -> None:
    run([str(BIN / 'python'), '-m', 'playwright', 'install', 'chromium', 'firefox'])


def generate_certs() -> None:
    cert = ROOT / 'certs' / 'cert.pem'
    key = ROOT / 'certs' / 'key.pem'
    if cert.exists() and key.exists():
        print('  Certificates already exist — skipping.')
        return
    run([str(BIN / 'python'), str(ROOT / 'generate_certs.py')])


def create_desktop_shortcut() -> None:
    """Windows only: put a 'Donut Intel' shortcut on the user's Desktop.

    Uses PowerShell + WScript.Shell (built into every Windows machine).
    Resolves the real Desktop folder, so it also works when Desktop is
    redirected to OneDrive.
    """
    if sys.platform != 'win32':
        return
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        "$desktop = [Environment]::GetFolderPath('Desktop'); "
        f"$sc = $ws.CreateShortcut((Join-Path $desktop 'Donut Intel.lnk')); "
        f"$sc.TargetPath = '{ROOT / 'start.bat'}'; "
        f"$sc.WorkingDirectory = '{ROOT}'; "
        "$sc.Description = 'Start the Donut Intel app'; "
        "$sc.Save()"
    )
    subprocess.run(
        ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps],
        check=True,
    )
    print('  Desktop shortcut created: Donut Intel.lnk')


def main() -> None:
    print('Donut Intel Platform — Setup')
    print('=' * 40)

    total = 6
    step(1, total, 'Creating project directories')
    create_dirs()

    step(2, total, 'Creating virtual environment')
    create_venv()

    step(3, total, 'Installing Python dependencies')
    install_deps()

    step(4, total, 'Installing Playwright browser engines')
    install_playwright()

    step(5, total, 'Generating TLS certificates')
    generate_certs()

    step(6, total, 'Creating desktop shortcut')
    try:
        create_desktop_shortcut()
    except Exception as exc:
        # A missing shortcut should never fail the whole setup.
        print(f'  [WARN] Could not create desktop shortcut: {exc}')

    print('\nSetup complete!')
    print('  Start:  python start.py')
    print('  Stop:   python stop.py')
    if sys.platform != 'win32':
        print('  Or use: ./start.sh / ./stop.sh')


if __name__ == '__main__':
    main()
