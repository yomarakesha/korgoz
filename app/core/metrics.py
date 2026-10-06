"""Lightweight runtime metrics."""


class RateMeter:
    """Events per second, smoothed.

    Averages the *interval* between events and inverts it. Averaging 1/interval
    directly would explode whenever two events arrive almost together.
    """

    def __init__(self, smoothing: float = 0.1) -> None:
        self._smoothing = smoothing
        self._last: float | None = None
        self._avg_interval: float | None = None

    def tick(self, now: float) -> None:
        if self._last is not None:
            interval = now - self._last
            if self._avg_interval is None:
                self._avg_interval = interval
            else:
                self._avg_interval += self._smoothing * (interval - self._avg_interval)
        self._last = now

    @property
    def rate(self) -> float:
        if not self._avg_interval:
            return 0.0
        return 1.0 / self._avg_interval
