"""In-memory brute-force protection for POST /auth/login.

Each key (username, client IP) may fail `max_failures` times within `window_seconds`;
then it is locked until the oldest of those failures leaves the window. In-memory is
enough for one API process; the state resets on restart.
"""

import threading
import time
from collections import deque
from collections.abc import Callable

# Above this many tracked keys, keys without recent failures are dropped.
_MAX_KEYS = 10_000


class LoginLimiter:
    def __init__(
        self,
        max_failures: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_failures
        self._window = window_seconds
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()  # sync routes run in a thread pool

    def _recent(self, key: str, now: float) -> deque[float]:
        failures = self._failures.get(key, deque())
        while failures and failures[0] <= now - self._window:
            failures.popleft()
        return failures

    def retry_after(self, *keys: str) -> float:
        """Seconds until a login attempt is allowed for all `keys`; 0 = allowed now."""
        with self._lock:
            now = self._clock()
            wait = 0.0
            for key in keys:
                failures = self._recent(key, now)
                if len(failures) >= self._max:
                    wait = max(wait, failures[-self._max] + self._window - now)
            return wait

    def failure(self, *keys: str) -> None:
        with self._lock:
            now = self._clock()
            if len(self._failures) >= _MAX_KEYS:
                self._failures = {k: q for k, q in self._failures.items() if self._recent(k, now)}
            for key in keys:
                failures = self._recent(key, now)
                failures.append(now)
                self._failures[key] = failures

    def success(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)
