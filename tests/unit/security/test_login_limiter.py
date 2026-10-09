from app.security.login_limiter import LoginLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_locks_after_max_failures_until_window_passes() -> None:
    clock = Clock()
    limiter = LoginLimiter(max_failures=3, window_seconds=60, clock=clock)
    for _ in range(2):
        limiter.failure("user:bob")
        clock.now += 1
    assert limiter.retry_after("user:bob") == 0
    limiter.failure("user:bob")  # third failure at t=1002, first one was at t=1000
    assert limiter.retry_after("user:bob") == 58
    assert limiter.retry_after("user:alice") == 0  # other keys are not affected
    clock.now += 58
    assert limiter.retry_after("user:bob") == 0


def test_any_locked_key_blocks_and_success_resets() -> None:
    limiter = LoginLimiter(max_failures=1, window_seconds=60, clock=Clock())
    limiter.failure("ip:1.2.3.4")
    assert limiter.retry_after("user:new", "ip:1.2.3.4") > 0
    limiter.success("ip:1.2.3.4")
    assert limiter.retry_after("user:new", "ip:1.2.3.4") == 0
