"""In-memory ring buffer of recent log lines plus WebSocket fan-out.

A `LogTailHandler` is attached to the root logger so every formatted log
record is appended to a deque. A background coroutine polls a revision
counter and broadcasts the tail (last N lines) to connected WebSockets
whenever new lines arrive.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Awaitable, Callable, List

_MAX_LINES = 200
_BUFFER: "deque[str]" = deque(maxlen=_MAX_LINES)
_revision = 0


class LogTailHandler(logging.Handler):
    """Captures formatted log records into an in-memory ring buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        global _revision
        try:
            line = self.format(record)
            _BUFFER.append(line)
            _revision += 1
        except Exception:
            self.handleError(record)


def install_log_tail_handler(formatter: logging.Formatter, level: int = logging.INFO) -> None:
    """Attach the tail handler to the root logger (idempotent)."""
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, LogTailHandler):
            return
    handler = LogTailHandler(level=level)
    handler.setFormatter(formatter)
    root.addHandler(handler)


def get_recent_lines(n: int = 8) -> List[str]:
    if n >= len(_BUFFER):
        return list(_BUFFER)
    return list(_BUFFER)[-n:]


def current_revision() -> int:
    return _revision


async def watch_and_broadcast(
    broadcast: Callable[[dict], Awaitable[None]],
    interval: float = 0.5,
    lines_per_push: int = 8,
) -> None:
    """Poll the buffer; when new lines arrive, push a snapshot."""
    last_rev = -1
    while True:
        try:
            rev = current_revision()
            if rev != last_rev:
                last_rev = rev
                await broadcast({"event": "log_tail", "lines": get_recent_lines(lines_per_push)})
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(interval)
