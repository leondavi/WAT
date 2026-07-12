"""Tiny polling helper shared by wait/assert actions.

Kept separate so the assertion and navigation modules do not depend on Playwright's
``expect`` — that keeps their logic unit-testable against a fake page.
"""

from __future__ import annotations

import time
from typing import Callable


def poll_until(predicate: Callable[[], bool], timeout_ms: int, interval_s: float = 0.1) -> bool:
    """Call *predicate* repeatedly until it returns True or *timeout_ms* elapses."""
    deadline = time.monotonic() + timeout_ms / 1000.0
    while True:
        try:
            if predicate():
                return True
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval_s)
