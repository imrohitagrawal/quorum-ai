"""W114 item 1: a test stand-in for ``time.monotonic`` whose readings subtract
exactly.

Why it exists: a frozen float clock stepped by 59.9, then 0.05, then 0.05 does
not always land 60 seconds after its start. From a start of 167123 it lands
59.999999999970896 seconds later (measured 2026-10-28), so a test that expects
a 60-second window to have passed failed or passed depending on where the real
clock read when the test started (on this Mac, the time since it last started
up), not on which machine ran it.

This clock keeps every reading on a grid of 2**-20 seconds, starting from a
whole second, and refuses a start, a time or a step below 0 and any reading
at or above 2**33. Every part of a reading (the start, the time or offset,
the real elapsed time) is then a whole number of grid steps from 0 up to
2**33, so adding them is exact. Below that bound a
reading is a whole number of grid steps that needs at most 53 bits, so it is
an exact float, and the DIFFERENCE of two readings is exact too: two readings
set 60.0 apart differ by exactly 60.0. A sum of two readings is not sure to
be exact (it can pass 2**33).

* Frozen: ``set(seconds)`` puts the reading at start + seconds and is refused
  off the grid (60.0 is on it, 0.1 is not). It replaces the reading, never
  adds to it, so steps cannot pile up rounding. ``advance`` is refused.
* Moving: the real elapsed time, rounded down to the grid, plus an offset.
  ``advance(seconds)`` adds to the offset and is refused off the grid (60.0 is
  on it, 0.05 is not). ``set`` is refused.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable

import pytest

#: Every reading is a whole multiple of this many seconds.
GRID = 2.0**-20
#: Readings at or above this are refused: past it, a multiple of ``GRID`` can
#: need more than 53 bits, so a reading, and the difference of two, is no
#: longer sure to be exact.
LIMIT = 2.0**33


class Clock:
    """``time.monotonic`` replaced, for one test, by a clock on an exact grid."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        frozen: bool = False,
        start: float | None = None,
        real: Callable[[], float] | None = None,
    ) -> None:
        # Taken before the patch below, so the default never calls itself.
        self._real = real if real is not None else time.monotonic
        self._real_at_start = self._real()
        # Rounded UP, so the clock never reads earlier than the value it was
        # made from (a real reading taken before the patch, say).
        # Checked before rounding, so a start of -0.5 is refused, not made 0.
        given = self._real_at_start if start is None else start
        if not given >= 0:
            raise ValueError(f"start {given} is below 0")
        self._start = float(math.ceil(given))
        if self._start >= LIMIT:
            raise ValueError(f"start {self._start} is at or above 2**33")
        self._frozen = frozen
        self._set_to = 0.0
        self._offset = 0.0
        monkeypatch.setattr(time, "monotonic", self)

    def __call__(self) -> float:
        if self._frozen:
            reading = self._start + self._set_to
        else:
            steps = math.floor((self._real() - self._real_at_start) / GRID)
            reading = self._start + steps * GRID + self._offset
        if reading >= LIMIT:
            raise ValueError(f"reading {reading} is at or above 2**33")
        return reading

    def set(self, seconds: float) -> None:
        """Frozen only: read ``seconds`` after the start from now on;
        ``seconds`` is a multiple of ``GRID``."""
        if not self._frozen:
            raise RuntimeError("set() is for a frozen clock; a moving clock uses advance()")
        if seconds < 0:
            raise ValueError(
                f"{seconds} is before the start; a monotonic clock never reads earlier"
            )
        if not (seconds / GRID).is_integer():
            raise ValueError(f"{seconds} is not a multiple of 2**-20, so the reading may round")
        self._set_to = seconds

    def advance(self, seconds: float) -> None:
        """Moving only: move every later reading on by ``seconds``, a multiple
        of ``GRID``."""
        if self._frozen:
            raise RuntimeError("advance() is for a moving clock; a frozen clock uses set()")
        if seconds < 0:
            raise ValueError(f"{seconds} moves back; a monotonic clock never does")
        if not (seconds / GRID).is_integer():
            raise ValueError(f"{seconds} is not a multiple of 2**-20, so the sum may round")
        # Both sides are grid multiples below 2**33, so this difference is exact.
        if seconds >= LIMIT - self._offset:
            raise ValueError(f"an offset of {self._offset} + {seconds} reaches 2**33")
        self._offset += seconds
