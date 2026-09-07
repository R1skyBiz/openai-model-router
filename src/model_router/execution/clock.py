"""Injected system and deterministic clocks for bounded execution."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import RLock
import time


def _milliseconds(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("milliseconds must be a nonnegative integer")
    return value


class MockClock:
    """A deterministic clock whose sleeps advance logical time immediately."""

    def __init__(self, initial: datetime) -> None:
        if initial.utcoffset() is None:
            raise ValueError("initial time must be timezone-aware")
        self._now = initial
        self._lock = RLock()
        self.sleep_calls: list[int] = []
        self.sleeps = self.sleep_calls

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def advance(self, milliseconds: int) -> None:
        amount = _milliseconds(milliseconds)
        with self._lock:
            self._now += timedelta(milliseconds=amount)

    def sleep(self, milliseconds: int) -> None:
        amount = _milliseconds(milliseconds)
        with self._lock:
            self.sleep_calls.append(amount)
            self._now += timedelta(milliseconds=amount)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def sleep(self, milliseconds: int) -> None:
        time.sleep(_milliseconds(milliseconds) / 1000)


__all__ = ["MockClock", "SystemClock"]
