#!/usr/bin/env python3
"""
Cross-platform server stop script.
Works on macOS and Windows. Uses psutil to find and terminate server processes.
Usage: python stop.py
"""
import sys

try:
    import psutil
except ImportError:
    print('psutil not installed. Run: pip install -r requirements.txt')
    sys.exit(1)

_PATTERNS = [
    'uvicorn backend.app:app',
    'chrome-headless-shell',
    # Playwright node driver (path separator differs by platform)
    'playwright/driver/node',
    'playwright\\driver\\node',
]


def main() -> None:
    killed = 0
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.cmdline())
            if any(p in cmdline for p in _PATTERNS):
                proc.kill()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if killed:
        print(f'Stopped {killed} process(es).')
    else:
        print('No running instance found.')


if __name__ == '__main__':
    main()
