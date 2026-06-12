"""Exponential-moving-average throughput tracker for progress callbacks."""

import time

_EMA_ALPHA = 0.3


class SpeedTracker:
    """Tracks bytes/sec from periodic (timestamp, bytes-done) samples.

    The first sample reports the average rate since the tracker was created
    (so fast/small transfers still show a speed); later samples blend the
    instantaneous rate into an exponential moving average.
    """

    def __init__(self) -> None:
        self._start = time.monotonic()
        self._prev_bytes: int | None = None
        self._prev_time: float | None = None
        self.speed = 0.0

    def update(self, bytes_done: int) -> float:
        now = time.monotonic()
        if self._prev_bytes is None or self._prev_time is None:
            elapsed = now - self._start
            if elapsed > 0:
                self.speed = bytes_done / elapsed
        else:
            elapsed = now - self._prev_time
            if elapsed > 0:
                instant = (bytes_done - self._prev_bytes) / elapsed
                self.speed = _EMA_ALPHA * instant + (1 - _EMA_ALPHA) * self.speed
        self._prev_bytes = bytes_done
        self._prev_time = now
        return self.speed
