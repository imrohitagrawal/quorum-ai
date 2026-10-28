"""W114 item 1: the contract of ``tests.exact_clock.Clock``, a replacement for
``time.monotonic`` whose readings subtract exactly.

The defect it fixes (plan, measured 2026-10-28): a frozen clock stepped by
59.9, 0.05 and 0.05 from a start of 8133 reads 59.99999999999818 s later,
not 60.0, so a ">= 60 s" window test failed or passed depending on where the
real clock read when the test started, not on which machine ran it.

The interface (plan, revision 3):

* ``Clock(monkeypatch, *, frozen=False, start=None, real=None)`` patches
  ``time.monotonic`` with itself; ``clock()`` reads.
* The start is ``float(math.ceil(start if given else real()))``: a whole
  second, never earlier than the value it was made from.
* Frozen: ``clock.set(seconds)`` sets the reading to start + seconds
  (absolute, never a sum) and refuses a ``seconds`` that is not a multiple
  of 2**-20; ``advance`` is refused.
* Moving: start + the real elapsed time rounded DOWN to a multiple of 2**-20
  + an offset; ``clock.advance(seconds)`` adds to the offset and refuses a
  ``seconds`` that is not a multiple of 2**-20; ``set`` is refused.
* Any reading at or above 2**33 is refused.

"Refused" means it raises; the plan does not name the exception type, so
these tests accept ``ValueError``, ``RuntimeError`` or ``AssertionError``
(never ``AttributeError``, so a missing method does not count as a refusal).
"""

from __future__ import annotations

import time

import pytest
from tests.exact_clock import Clock

REFUSED = (ValueError, RuntimeError, AssertionError)
GRID = 2**-20

#: Found by a search over [1e3, 2e6] at test-writing time and pinned: adding
#: 60.0 to it and taking it away again gives 59.999999999999886, and its
#: fraction is under 0.5, so rounding to the NEAREST second would go down.
FLOAT_START = 1008.3038611573548


class FakeReal:
    """A stand-in for the real ``time.monotonic``: it returns ``now``, however
    many times it is called."""

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize("start", [8133, 8134, 167123, 2**31])
def test_frozen_readings_set_60_apart_subtract_to_exactly_60(
    monkeypatch: pytest.MonkeyPatch, start: int
) -> None:
    """Frozen at a whole-second start, ``set`` is absolute: 59.5 then
    60.0 - 2**-20 stay below start + 60.0; ``set(60.0)`` reads exactly start + 60.0 (also
    through the patched ``time.monotonic``); the difference to ``set(0.0)``
    is exactly 60.0, in both orders. Red when: ``set`` adds to the reading
    instead of replacing it, or the clock is not what ``time.monotonic``
    calls."""
    clock = Clock(monkeypatch, frozen=True, start=start)
    zero = clock()
    assert zero == float(start)
    clock.set(59.5)
    clock.set(60.0 - GRID)
    assert clock() < start + 60.0
    clock.set(60.0)
    sixty = clock()
    assert sixty == start + 60.0
    assert time.monotonic() == start + 60.0
    assert sixty - zero == 60.0
    clock.set(0.0)
    assert sixty - clock() == 60.0


def test_a_float_start_is_rounded_up_to_a_whole_second(monkeypatch: pytest.MonkeyPatch) -> None:
    """A start of ``FLOAT_START`` (where ``(x + 60.0) - x`` is not 60.0; the
    first assertion proves it) reads 1009.0, never earlier than the start,
    and readings set 60.0 apart differ by exactly 60.0. Red when: the start
    is not rounded (the difference is 59.999999999999886), or rounded to the
    nearest second instead of up (it reads 1008.0, before the start)."""
    assert (FLOAT_START + 60.0) - FLOAT_START != 60.0, "partner: this start breaks raw sums"
    clock = Clock(monkeypatch, frozen=True, start=FLOAT_START)
    clock.set(60.0)
    sixty = clock()
    clock.set(0.0)
    zero = clock()
    assert sixty - zero == 60.0
    assert zero >= FLOAT_START
    assert zero == 1009.0


def test_without_a_start_the_real_reading_is_rounded_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ``start``: a frozen clock made while the real clock reads 8133.3
    reads 8134.0. Red when: the start is the raw real reading, or comes from
    somewhere other than ``real``."""
    clock = Clock(monkeypatch, frozen=True, real=FakeReal(8133.3))
    assert clock() == 8134.0


def test_frozen_advance_is_refused_and_moves_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Frozen, ``advance(60.0)`` raises and the reading does not change.
    Partner: ``set`` on the same clock works. Red when: frozen ``advance``
    is allowed (a test could step the clock again and creep short)."""
    clock = Clock(monkeypatch, frozen=True, start=8133)
    clock.set(10.0)
    with pytest.raises(REFUSED):
        clock.advance(60.0)
    assert clock() == 8143.0


def test_moving_readings_are_rounded_down_to_the_grid_and_advance_is_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Moving, with a fake real clock at 8133.4: the start is 8134.0. The
    real clock moves to 8133.5 (elapsed 0.1000000000003638) and
    ``advance(60.0)`` runs: the reading is exactly 8194.0 + 104857 * 2**-20
    (0.1 rounded down to the grid), so the difference is exactly 60.0 +
    104857 * 2**-20. Red when: the elapsed time is not rounded to the grid,
    is rounded up instead of down, or ``advance`` does not add exactly."""
    real = FakeReal(8133.4)
    clock = Clock(monkeypatch, real=real)
    before = clock()
    assert before == 8134.0
    real.now = 8133.5
    clock.advance(60.0)
    after = clock()
    assert after == 8194.0 + 104857 * GRID
    assert after - before == 60.0 + 104857 * GRID


def test_moving_advance_off_the_grid_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Moving, ``advance(0.05)`` raises (0.05 is not a multiple of 2**-20)
    and the reading does not change; partner: ``advance(2**-20)`` and
    ``advance(0.5)`` are accepted and add exactly. Red when: the grid check
    is removed, or it refuses a value that IS on the grid."""
    clock = Clock(monkeypatch, real=FakeReal(8133.0))
    assert clock() == 8133.0
    with pytest.raises(REFUSED):
        clock.advance(0.05)
    assert clock() == 8133.0
    clock.advance(GRID)
    clock.advance(0.5)
    assert clock() == 8133.5 + GRID


def test_moving_set_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Moving, ``set(60.0)`` raises and the reading does not change. Red
    when: ``set`` is allowed on a moving clock (it would overwrite the real
    elapsed time)."""
    clock = Clock(monkeypatch, real=FakeReal(8133.0))
    with pytest.raises(REFUSED):
        clock.set(60.0)
    assert clock() == 8133.0


def test_the_default_real_clock_is_the_unpatched_monotonic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``real``: the clock reads the real ``time.monotonic`` as it was
    before the patch. Its reading is not before a real reading taken just
    before it was made, is on the grid, and does not go back. Red when: the
    default ``real`` is the patched ``time.monotonic`` (it would call itself)
    or readings are not on the grid."""
    real_before = time.monotonic()
    clock = Clock(monkeypatch)
    first = clock()
    second = clock()
    assert first >= real_before
    assert second >= first
    assert (first / GRID).is_integer()


@pytest.mark.parametrize("frozen", [True, False], ids=["frozen", "moving"])
def test_a_reading_at_or_above_2_to_the_33_is_refused(
    monkeypatch: pytest.MonkeyPatch, frozen: bool
) -> None:
    """From a start of 2**33 - 1, a reading 0.5 s later is allowed (partner:
    the bound is not hit by the start itself), a reading 1.0 s later (exactly
    2**33) raises, and so does one 2.0 s later. From 2**33 up, a multiple of
    2**-20 can need more than 53 bits, so a reading is no longer sure to be
    exact. Red when: only the start is checked, or the bound is ``>``
    instead of ``>=``."""
    start = 2**33 - 1
    clock = Clock(monkeypatch, frozen=frozen, start=start, real=FakeReal(5.0))
    assert clock() == float(start)
    moved = 0.0
    for seconds, allowed in ((0.5, True), (1.0, False), (2.0, False)):
        if frozen:
            clock.set(seconds)
        else:
            clock.advance(seconds - moved)
            moved = seconds
        if allowed:
            assert clock() == start + seconds
        else:
            with pytest.raises(REFUSED):
                clock()


def test_frozen_set_off_the_grid_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Frozen from 1000, ``set(0.1)`` raises ``ValueError`` (0.1 is not a
    multiple of 2**-20) and the reading does not change. Without the check,
    ``set(0.1)`` and ``set(60.1)`` read 59.999999999999886 apart. Partner:
    ``set(60.0 - 2**-20)`` and ``set(0.5)`` are accepted and read start plus
    that value exactly. Red when: ``set`` has no grid check, or the check
    refuses a value that IS on the grid."""
    clock = Clock(monkeypatch, frozen=True, start=1000)
    with pytest.raises(ValueError):
        clock.set(0.1)
    assert clock() == 1000.0
    clock.set(60.0 - GRID)
    assert clock() == 1000.0 + (60.0 - GRID)
    assert clock() - 1000.0 == 60.0 - GRID
    clock.set(0.5)
    assert clock() == 1000.5


def test_a_start_at_2_to_the_33_is_refused_when_the_clock_is_made(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Clock(monkeypatch, frozen=True, start=2**33)`` raises ``ValueError``
    as it is made, before any reading (2**33 - 1 is accepted: see the test
    above). Red when: the start is not checked when the clock is made."""
    with pytest.raises(ValueError):
        Clock(monkeypatch, frozen=True, start=2**33)


def test_a_start_a_time_or_a_step_below_0_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A start of -1, -0.5 or -GRID, a frozen ``set(-GRID)`` and a moving
    ``advance(-GRID)`` each raise ValueError, and leave the reading as it
    was; partners: a start of 0, ``set(0.0)`` and ``advance(0.0)`` are
    accepted and read exactly 0.0. Below 0 the parts of a reading can
    cancel and a sum can round (from 0, readings at 2**33 - 2**-20 and
    -2 * 2**-20 subtract to 8589934592.0, one grid step off). Red when: any
    of the three checks for a value below 0 is removed, or the start is
    checked after it is rounded up (-0.5 would become 0)."""
    with pytest.raises(ValueError):
        Clock(monkeypatch, frozen=True, start=-1)
    for below in (-0.5, -GRID):  # rounding up would make each of these 0
        with pytest.raises(ValueError):
            Clock(monkeypatch, frozen=True, start=below)
    frozen = Clock(monkeypatch, frozen=True, start=0)
    frozen.set(0.0)
    assert frozen() == 0.0
    with pytest.raises(ValueError):
        frozen.set(-GRID)
    assert frozen() == 0.0
    moving = Clock(monkeypatch, start=0, real=FakeReal(5.0))
    moving.advance(0.0)
    assert moving() == 0.0
    with pytest.raises(ValueError):
        moving.advance(-GRID)
    assert moving() == 0.0


def test_a_step_that_takes_the_offset_to_2_to_the_33_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On a moving clock from 0, ``advance(2**33 - GRID)`` is accepted, then
    ``advance(GRID)`` (an offset of exactly 2**33) raises and moves nothing,
    and so does ``advance(2**40)`` on a fresh clock. Without the check, steps
    of 2**40, GRID and back would lose the GRID (the offset reads 0.0, not
    2**-20). Red when: ``advance`` does not check the offset, or checks it
    with ``>`` instead of ``>=``."""
    clock = Clock(monkeypatch, start=0, real=FakeReal(5.0))
    clock.advance(2**33 - GRID)
    assert clock() == 2**33 - GRID
    with pytest.raises(ValueError):
        clock.advance(GRID)
    assert clock() == 2**33 - GRID
    fresh = Clock(monkeypatch, start=0, real=FakeReal(5.0))
    with pytest.raises(ValueError):
        fresh.advance(2.0**40)
    assert fresh() == 0.0
