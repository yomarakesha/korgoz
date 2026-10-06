import pytest

from app.core.metrics import RateMeter


def test_rate_from_steady_ticks() -> None:
    meter = RateMeter()
    for i in range(20):
        meter.tick(i * 0.1)
    assert meter.rate == pytest.approx(10.0)


def test_near_simultaneous_ticks_do_not_explode() -> None:
    meter = RateMeter()
    for t in (0.0, 0.1, 0.1001, 0.2, 0.3):
        meter.tick(t)
    assert meter.rate < 15


def test_no_rate_before_two_ticks() -> None:
    meter = RateMeter()
    meter.tick(1.0)
    assert meter.rate == 0.0
