"""The spend-cap decision, enumerated as a table rather than read as a boolean.

WHY THIS FILE EXISTS. A ~40-line predicate had **five defects found across four
review passes**, and none were in the predicates themselves -- all were wiring.
One was an absorbing state: a recovered store could never become trustworthy (a
monotonic loss counter never resets) and could never be replaced (the reopen was
gated on a staleness that recovery had just cleared), so every priced request
was refused until a process restart.

Each fix I wrote added a *term* to a boolean expression instead of a *row* to a
table. That is why fixing one revealed the next. A reviewer built the table in
one pass and found the absorbing cell immediately.

So: enumerate the space, assert the outcome of every cell, and assert that no
cell is a dead end. ``itertools.product`` is exhaustive at this size, which
strictly beats random search.

WHAT THIS FILE DOES NOT COVER, stated because the gap is easy to miss. The
reachability test calls the SAME predicate production uses, so it proves the
predicate algebra has no dead ends -- it cannot notice production wiring a
DIFFERENT predicate. Re-implementing the condition here instead would let the
model drift from the system, which is worse. Whether the right predicate is
wired is asserted by
``tests/integration/test_stale_ledger_block_on_a_real_volume.py``, against a
real SQLite fault; that test is what goes red if the trigger regresses. The two
are complementary and neither is sufficient alone.

Track record so far: this file found a live absorbing state --
``("ok", lost=1, tried=False)`` -- in code committed hours before it, which
three review passes and a full suite had not.
"""

from __future__ import annotations

import itertools

import pytest
from tests.helpers import unreachable_recoveries

from product_app.store_reconnect import (
    feedback_ledger_is_stale,
    feedback_ledger_is_trustworthy,
    feedback_ledger_may_be_metered,
)

#: Every store shape the singleton can actually hold.
_HEALTHS = ("ok", "failing", "unverified", "raises", "no-signal")
_LOSSES = (0, 1)


def _store(health: str, lost: int) -> object | None:
    if health == "none":
        return None

    class _Store:
        def write_health(self) -> str:
            if health == "raises":
                raise RuntimeError("simulated")
            return health

        def lost_billed_writes(self) -> int:
            return lost

    class _NoSignal:
        """Predates the #109 signal entirely."""

    return _NoSignal() if health == "no-signal" else _Store()


@pytest.mark.parametrize(("health", "lost"), list(itertools.product(_HEALTHS, _LOSSES)))
def test_every_store_shape_has_a_defined_outcome(health: str, lost: int) -> None:
    """No cell may be accidental. Each of the three predicates answers, and the
    two that decide money agree with the documented contract."""
    store = _store(health, lost)
    stale = feedback_ledger_is_stale(store)
    trustworthy = feedback_ledger_is_trustworthy(store)
    metered = feedback_ledger_may_be_metered(store)

    # A no-signal store cannot be judged by signals it never had.
    if health == "no-signal":
        assert (stale, trustworthy, metered) == (False, True, True)
        return

    # Positive evidence of a fault -> never metered, never trusted.
    if health in ("failing", "raises"):
        assert stale is True
        assert trustworthy is False
        assert metered is False
        return

    # "ok"/"unverified" with a lost charge: the ledger is INCOMPLETE. This is
    # the cell that leaked $0.3180 against a $0.20 cap before the fix.
    if lost > 0:
        assert metered is False, "a ledger missing billed rows must never be metered"
        assert trustworthy is False
        return

    # Clean and healthy, or clean and merely cold.
    assert metered is True, "a clean ledger must be metered -- a cold store is not a fault"
    assert trustworthy is (health == "ok")


def test_a_none_store_is_never_metered_and_never_trusted() -> None:
    assert feedback_ledger_may_be_metered(None) is False
    assert feedback_ledger_is_trustworthy(None) is False
    assert feedback_ledger_is_stale(None) is True


def test_no_reachable_state_refuses_traffic_forever() -> None:
    """THE INVARIANT THAT WOULD HAVE CAUGHT THE ABSORBING-STATE BUG.

    States are ``(health, lost, reopen_tried)``. Real events:

    * a reopen installs a FRESH handle -- ``lost`` resets to 0 because the
      counter is per-instance, and the new handle starts ``unverified``;
    * a write lands -> ``ok``; a billed write is lost -> ``failing`` and
      ``lost`` climbs; the operator fixes the volume -> writes land again.

    ``healthy`` is any state the cap meters from. Every state must be able to
    reach one.

    Turns red if: the reopen trigger goes back to firing only on staleness, so
    a recovered-but-poisoned handle is never replaced.
    """
    State = tuple[str, int, bool]
    states: list[State] = [
        (h, lost, tried)
        for h in ("ok", "failing", "unverified")
        for lost in (0, 1)
        for tried in (False, True)
    ]
    transitions: dict[State, set[State]] = {}
    for state in states:
        health, lost, tried = state
        nxt: set[State] = set()
        # BENIGN EVENTS ONLY. This is the whole subtlety, and my first version
        # of this test got it wrong: I also modelled "a billed write is lost"
        # as an available edge, so every dead end could "escape" by suffering a
        # NEW FAULT and the mutation below passed. Reaching a healthy state by
        # breaking further is not recovery. The question is whether a system
        # whose fault is OVER can get back on its own.
        #
        # So: the operator has fixed the volume. Writes land. The only moves
        # are (a) a write landing, and (b) a reopen the app decides to make.
        store = _store(health, lost)
        # Mirrors the production trigger, and deliberately by CALLING the same
        # predicate rather than restating its logic -- a re-implemented
        # condition is how a state table drifts from the system it claims to
        # model.
        if not feedback_ledger_may_be_metered(store):
            # A fresh handle: the loss counter is per-instance, so it resets,
            # and the new handle has attempted no write yet.
            nxt.add(("unverified", 0, True))
        nxt.add(("ok", lost, tried))  # a write lands on the current handle
        transitions[state] = nxt

    healthy = {s for s in states if feedback_ledger_may_be_metered(_store(s[0], s[1]))}
    assert healthy, "precondition: some state must be meterable, or this proves nothing"

    stuck = unreachable_recoveries(transitions, healthy)
    assert not stuck, f"states that can never return to metering: {stuck}"
