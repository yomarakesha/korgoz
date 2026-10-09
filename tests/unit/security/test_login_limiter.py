import threading

from app.security.login_limiter import LoginLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_locks_after_limit_until_window_passes() -> None:
    clock = Clock()
    limiter = LoginLimiter(window_seconds=60, clock=clock)
    for _ in range(3):
        assert limiter.attempt({"bob": 3}) == 0
        clock.now += 1
    # Attempts at t=1000, 1001, 1002; now t=1003: free again at t=1060.
    assert limiter.attempt({"bob": 3}) == 57
    assert limiter.attempt({"alice": 3}) == 0  # other keys are not affected
    clock.now += 57
    assert limiter.attempt({"bob": 3}) == 0


def test_blocked_attempt_is_not_counted_and_any_key_blocks() -> None:
    limiter = LoginLimiter(window_seconds=60, clock=Clock())
    assert limiter.attempt({"pair": 5, "ip": 1}) == 0
    assert limiter.attempt({"other-pair": 5, "ip": 1}) > 0
    assert limiter.attempt({"other-pair": 5}) == 0  # the rejected try left no trace
    limiter.success("ip")
    assert limiter.attempt({"pair": 5, "ip": 1}) == 0


def test_parallel_attempts_cannot_exceed_the_limit() -> None:
    limiter = LoginLimiter(window_seconds=60)
    allowed: list[bool] = []
    barrier = threading.Barrier(20)

    def worker() -> None:
        barrier.wait()
        allowed.append(limiter.attempt({"bob": 5}) == 0)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert allowed.count(True) == 5
