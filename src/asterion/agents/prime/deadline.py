"""Trusted, non-renewing admission bound in wall and monotonic clock domains."""
from __future__ import annotations

import math
from threading import RLock
import time


class TaskDeadline:
    """Expire permanently when either absolute clock reaches its deadline.

    This object grants no execution or cleanup authority. Its owner supplies
    both origins; a continuation must reuse the object rather than renew it.
    """

    def __init__(self, *, deadline_monotonic: float, deadline_epoch: float,
                 monotonic_clock=None, wall_clock=None):
        if any(type(value) not in (int, float) or not math.isfinite(value)
               for value in (deadline_monotonic, deadline_epoch)):
            raise ValueError('task deadline unavailable')
        self._deadline_monotonic = float(deadline_monotonic)
        self._deadline_epoch = float(deadline_epoch)
        self._monotonic_clock = time.monotonic if monotonic_clock is None else monotonic_clock
        self._wall_clock = time.time if wall_clock is None else wall_clock
        if not callable(self._monotonic_clock) or not callable(self._wall_clock):
            raise ValueError('task deadline unavailable')
        self._expired = False
        self._lock = RLock()

    @property
    def deadline_monotonic(self) -> float:
        return self._deadline_monotonic

    @property
    def deadline_epoch(self) -> float:
        return self._deadline_epoch

    def snapshot(self) -> dict:
        """Sample both clocks once; observing never renews a sticky deadline."""
        with self._lock:
            try:
                readings = (self._monotonic_clock(), self._wall_clock())
                available = all(type(value) in (int, float) and math.isfinite(value)
                                for value in readings)
            except Exception:
                readings, available = (None, None), False
            remaining = 0.0
            if not available:
                self._expired = True
            elif not self._expired:
                remaining = max(0.0, min(self._deadline_monotonic - readings[0],
                                         self._deadline_epoch - readings[1]))
                self._expired = remaining == 0.0
            return {'status': 'available' if available else 'unavailable',
                    'sampled_at_monotonic': float(readings[0]) if available else None,
                    'sampled_at_epoch': float(readings[1]) if available else None,
                    'deadline_monotonic': self._deadline_monotonic,
                    'deadline_epoch': self._deadline_epoch,
                    'remaining_seconds': remaining}

    def remaining_seconds(self) -> float:
        return self.snapshot()['remaining_seconds']

    def expired(self) -> bool:
        return self.remaining_seconds() == 0.0
