"""In-memory brute-force protection for password checks.

Each key may be used `limit` times within `window_seconds`; then it is locked until the
oldest of those attempts leaves the window. An attempt is counted *before* the password
is checked (atomically with the lock check), so parallel requests cannot slip past the
limit; a successful login then forgets the attempts of its key.

In-memory is enough for one API process; the state resets on restart.
"""

import threading
import time
from collections import deque
from collections.abc import Callable, Mapping

# Above this many tracked keys, keys without recent attempts are dropped.
_MAX_KEYS = 10_000


class LoginLimiter:
    def __init__(self, window_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._window = window_seconds
        self._clock = clock
        self._attempts: dict[str, deque[float]] = {}
        self._lock = threading.Lock()  # sync routes run in a thread pool

    def _recent(self, key: str, now: float) -> deque[float]:
        attempts = self._attempts.get(key, deque())
        while attempts and attempts[0] <= now - self._window:
            attempts.popleft()
        return attempts

    def attempt(self, limits: Mapping[str, int]) -> float:
        """Register one attempt for every key -> its limit.

        Returns 0 if allowed (the attempt is counted), else the seconds until it would be
        allowed (nothing is counted).
        """
        with self._lock:
            now = self._clock()
            wait = 0.0
            for key, limit in limits.items():
                attempts = self._recent(key, now)
                if len(attempts) >= limit:
                    wait = max(wait, attempts[-limit] + self._window - now)
            if wait > 0:
                return wait
            if len(self._attempts) >= _MAX_KEYS:
                self._attempts = {k: q for k, q in self._attempts.items() if self._recent(k, now)}
            for key in limits:
                attempts = self._recent(key, now)
                attempts.append(now)
                self._attempts[key] = attempts
            return 0.0

    def success(self, key: str) -> None:
        """Forget the attempts of `key` (call it only for keys tied to the account)."""
        with self._lock:
            self._attempts.pop(key, None)
