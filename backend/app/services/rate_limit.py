"""Minimal in-process rate limiting.

Scope check: this exists to stop one client hammering a shared free GPU quota,
not to be a security control. A single instance holds the counters in memory --
no Redis, because the deployment is a single process and adding one would be
infrastructure the requirements do not justify.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    """Fixed-window-per-key limiter using a deque of timestamps."""

    def __init__(self, *, max_requests: int, window_seconds: int) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        cutoff = now - self._window
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= self._max:
                return False

            bucket.append(now)

            # Opportunistic cleanup so idle keys do not leak memory.
            if len(self._hits) > 1024:
                for k in [k for k, v in self._hits.items() if not v or v[-1] < cutoff]:
                    self._hits.pop(k, None)
            return True

    def retry_after(self, key: str) -> int:
        with self._lock:
            bucket = self._hits.get(key)
            if not bucket:
                return 0
            return max(0, int(self._window - (time.time() - bucket[0])) + 1)
