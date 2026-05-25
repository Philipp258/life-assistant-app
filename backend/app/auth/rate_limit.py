"""Per-IP rate limit for login attempts.

Single uvicorn worker by design (`deploy/life-assistant.service` runs without
`--workers`, and the rest of the runtime is process-local), so an in-memory
sliding-window counter is enough. State is lost on restart — acceptable; the
attacker doesn't get to restart the server.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock

MAX_FAILURES = 20
WINDOW_SECONDS = 900
LOCKOUT_SECONDS = 900

_lock = Lock()
_failures: dict[str, deque[float]] = {}
_locked_until: dict[str, float] = {}

# Tests monkeypatch this to control the clock without sleeping.
_now = time.monotonic


def check_locked(ip: str) -> int | None:
    """Return seconds remaining on the lock for `ip`, or None if not locked."""
    with _lock:
        until = _locked_until.get(ip)
        if until is None:
            return None
        remaining = until - _now()
        if remaining <= 0:
            del _locked_until[ip]
            _failures.pop(ip, None)
            return None
        return int(remaining) + 1


def register_failure(ip: str) -> None:
    with _lock:
        now = _now()
        cutoff = now - WINDOW_SECONDS
        dq = _failures.setdefault(ip, deque())
        while dq and dq[0] < cutoff:
            dq.popleft()
        dq.append(now)
        if len(dq) >= MAX_FAILURES:
            _locked_until[ip] = now + LOCKOUT_SECONDS
            dq.clear()


def register_success(ip: str) -> None:
    with _lock:
        _failures.pop(ip, None)
        _locked_until.pop(ip, None)


def _reset_for_tests() -> None:
    with _lock:
        _failures.clear()
        _locked_until.clear()
