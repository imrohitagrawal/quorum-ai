"""Issue #123 — a recovered volume must not need a process restart.

Before this, ``configure_feedback_store`` / ``configure_run_history_store``
ran exactly once at import, so a single transient lock at boot disabled the
per-account 24h spend cap for the whole process lifetime.

Every test here drives the real ``store_reconnect`` functions. The reopen
work itself is spawned on a background thread by design (the issue's own
constraint: a failed reopen costs SQLite's 5-second default lock-open
timeout, which must never be paid by a user's request), so the tests inject
a fake ``threading.Thread`` and assert on WHETHER a reopen was scheduled
rather than sleeping on a real one.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from product_app import store_reconnect
from product_app.config import settings


class _FakeThread:
    """Records that a reopen was SCHEDULED, without running it.

    Records both the thread NAME (what most tests below assert on) and the
    actual TARGET callable it was constructed with (what
    ``test_the_trigger_is_wired_to_the_right_reopen_function`` asserts on —
    without that, every "schedules a reopen" test here would pass identically
    even if the trigger were wired to the wrong body, or a no-op).
    """

    started: list[str] = []
    targets: dict[str, Any] = {}

    def __init__(self, *, target: Any, daemon: bool, name: str) -> None:
        self._target = target
        self.name = name
        self.daemon = daemon

    def start(self) -> None:
        _FakeThread.started.append(self.name)
        _FakeThread.targets[self.name] = self._target


class _RaisingOnStartThread:
    """A thread double whose construction succeeds but ``.start()`` raises —
    the real-world shape of thread-count exhaustion."""

    def __init__(self, *, target: Any, daemon: bool, name: str) -> None:
        pass

    def start(self) -> None:
        raise RuntimeError("can't start new thread (simulated exhaustion)")


@pytest.fixture(autouse=True)
def _clean_reconnect_state() -> Any:
    """Reset both cooldown stamps and the recorded thread starts.

    Autouse because the cooldown timestamps are module globals: a test that
    triggers a reconnect would otherwise suppress the next test's trigger
    for a full 60-second window, making these order-dependent.
    """
    store_reconnect._reset_for_tests()
    _FakeThread.started = []
    _FakeThread.targets = {}
    yield
    store_reconnect._reset_for_tests()
    _FakeThread.started = []
    _FakeThread.targets = {}


# --------------------------------------------------------------------------
# feedback store
# --------------------------------------------------------------------------


def test_a_healthy_feedback_store_schedules_no_reopen() -> None:
    """The no-false-fire partner. Without this, a mechanism that reopened on
    EVERY call would satisfy every "does it reopen" test below while
    hammering a healthy database.

    Turns red if: the ``write_health() == "failing"`` / ``is None`` condition
    is dropped and the reopen becomes unconditional.
    """

    class _HealthyStore:
        def write_health(self) -> str:
            return "ok"

    with (
        patch("product_app.feedback_store.get_store", return_value=_HealthyStore()),
        patch("product_app.store_reconnect.threading.Thread", _FakeThread),
    ):
        store_reconnect.maybe_reconnect_feedback_store()

    assert _FakeThread.started == []


def test_an_unverified_feedback_store_schedules_no_reopen() -> None:
    """``"unverified"`` means "this store has attempted no write yet" — the
    ordinary state of a cold process that has served only reads. It is NOT a
    fault, and reopening on it would fire on every quiet boot.

    Turns red if: the condition widens from ``== "failing"`` to
    ``!= "ok"``.
    """

    class _UnverifiedStore:
        def write_health(self) -> str:
            return "unverified"

    with (
        patch("product_app.feedback_store.get_store", return_value=_UnverifiedStore()),
        patch("product_app.store_reconnect.threading.Thread", _FakeThread),
    ):
        store_reconnect.maybe_reconnect_feedback_store()

    assert _FakeThread.started == []


def test_a_store_without_a_write_health_method_is_left_alone() -> None:
    """A REGRESSION test, not a hypothetical. The first version of this
    module called ``store.write_health()`` unconditionally, and the singleton
    holds whatever any caller passed to ``configure()`` — several existing
    tests install a narrow duck-typed double implementing only the method
    under test. That raised ``AttributeError`` on the REQUEST PATH, caught by
    ``tests/unit/test_cost_rail_units.py`` the first time this ran against
    the full suite (three failures), not by reasoning about it beforehand.

    Turns red if: the ``callable(...)`` guard is dropped and the call becomes
    unconditional again.
    """

    class _StoreWithoutWriteHealth:
        """Exactly the shape of the doubles in test_cost_rail_units.py."""

    with (
        patch("product_app.feedback_store.get_store", return_value=_StoreWithoutWriteHealth()),
        patch("product_app.store_reconnect.threading.Thread", _FakeThread),
    ):
        store_reconnect.maybe_reconnect_feedback_store()

    assert _FakeThread.started == []


def test_a_failing_feedback_store_schedules_a_reopen() -> None:
    """The #109 shape this is built on: a store that OPENED fine but can no
    longer write. A reopen keyed on ``get_store() is None`` would never fire
    for it — which is exactly why the issue says to key on write health.

    Turns red if: the write-health branch is removed and only absence
    triggers a reopen.
    """

    class _FailingStore:
        def write_health(self) -> str:
            return "failing"

    with (
        patch("product_app.feedback_store.get_store", return_value=_FailingStore()),
        patch("product_app.store_reconnect.threading.Thread", _FakeThread),
    ):
        store_reconnect.maybe_reconnect_feedback_store()

    assert _FakeThread.started == ["feedback-store-reconnect"]


def test_an_absent_feedback_store_schedules_a_reopen() -> None:
    """The boot-lock shape: ``configure`` never ran, so there is no store."""
    with (
        patch("product_app.feedback_store.get_store", return_value=None),
        patch("product_app.store_reconnect.threading.Thread", _FakeThread),
    ):
        store_reconnect.maybe_reconnect_feedback_store()

    assert _FakeThread.started == ["feedback-store-reconnect"]


def test_the_cooldown_suppresses_a_second_attempt_in_the_same_window() -> None:
    """A sustained outage must not spawn a reopen thread per request — that
    is the DoS the issue explicitly warns about (``/status`` is
    unauthenticated, so an anonymous caller could otherwise drive repeated
    5-second lock-opens).

    Turns red if: the monotonic cooldown check is removed.
    """
    clock = iter([100.0, 100.0 + settings.store_reconnect_cooldown_seconds - 1.0])

    with (
        patch("product_app.feedback_store.get_store", return_value=None),
        patch("product_app.store_reconnect.threading.Thread", _FakeThread),
    ):
        store_reconnect.maybe_reconnect_feedback_store(monotonic=lambda: next(clock))
        store_reconnect.maybe_reconnect_feedback_store(monotonic=lambda: next(clock))

    assert _FakeThread.started == ["feedback-store-reconnect"], (
        "a second attempt inside the cooldown window was not suppressed"
    )


def test_a_second_attempt_after_the_cooldown_is_allowed() -> None:
    """The positive partner to the cooldown test: without this, a cooldown
    that suppressed EVERYTHING forever would still pass the test above, and
    a store that came back would never be reopened.

    Turns red if: the cooldown never expires (e.g. the stamp is set once and
    never compared against elapsed time).
    """
    clock = iter([100.0, 100.0 + settings.store_reconnect_cooldown_seconds + 1.0])

    with (
        patch("product_app.feedback_store.get_store", return_value=None),
        patch("product_app.store_reconnect.threading.Thread", _FakeThread),
    ):
        store_reconnect.maybe_reconnect_feedback_store(monotonic=lambda: next(clock))
        store_reconnect.maybe_reconnect_feedback_store(monotonic=lambda: next(clock))

    assert _FakeThread.started == [
        "feedback-store-reconnect",
        "feedback-store-reconnect",
    ]


def test_the_off_switch_suppresses_every_reopen(monkeypatch: pytest.MonkeyPatch) -> None:
    """The explicit off switch the issue requires, so the tests that pin the
    DEGRADED path (and any operator who wants the old behaviour) can turn
    the mechanism off outright.

    Turns red if: the ``settings.store_reconnect_enabled`` guard is removed.
    """
    monkeypatch.setattr(settings, "store_reconnect_enabled", False)

    with (
        patch("product_app.feedback_store.get_store", return_value=None),
        patch("product_app.store_reconnect.threading.Thread", _FakeThread),
    ):
        store_reconnect.maybe_reconnect_feedback_store()
        store_reconnect.maybe_reconnect_run_history_store()

    assert _FakeThread.started == []


def test_the_trigger_is_wired_to_the_right_reopen_function() -> None:
    """Adversarial review (#123): every "schedules a reopen" test above only
    checks the thread NAME, so the trigger could be wired to the WRONG body
    (swapped with the run-history reopen, or a no-op) and every one of them
    would still pass. Assert on the actual callable the thread was
    constructed with.

    Turns red if: the ``target=`` argument at either call site is changed to
    anything other than the matching ``_reopen_*`` function.
    """
    with (
        patch("product_app.feedback_store.get_store", return_value=None),
        patch("product_app.run_history_store.get_store", return_value=None),
        patch("product_app.store_reconnect.threading.Thread", _FakeThread),
    ):
        store_reconnect.maybe_reconnect_feedback_store()
        store_reconnect.maybe_reconnect_run_history_store()

    assert _FakeThread.targets["feedback-store-reconnect"] is store_reconnect._reopen_feedback_store
    assert (
        _FakeThread.targets["run-history-store-reconnect"]
        is store_reconnect._reopen_run_history_store
    )


def test_a_thread_creation_failure_does_not_break_the_caller() -> None:
    """Adversarial review (#123): the real-world shape of thread-count
    exhaustion is ``Thread(...).start()`` raising. Before this test existed,
    that exception propagated straight out of ``maybe_reconnect_*`` — and
    since these are called from ``CostEstimationService.estimate()`` with no
    surrounding try/except, it would have turned "best-effort background
    reconnect" into a 500 on ``POST /v1/query-runs/estimate``, recurring once
    per cooldown window for as long as the exhaustion persisted.

    Turns red if: the try/except around ``.start()`` in ``_spawn`` is removed.
    """
    with (
        patch("product_app.feedback_store.get_store", return_value=None),
        patch("product_app.run_history_store.get_store", return_value=None),
        patch("product_app.store_reconnect.threading.Thread", _RaisingOnStartThread),
    ):
        # Must not raise.
        store_reconnect.maybe_reconnect_feedback_store()
        store_reconnect.maybe_reconnect_run_history_store()


# --------------------------------------------------------------------------
# run history store — deliberately a NARROWER trigger
# --------------------------------------------------------------------------


def test_an_absent_run_history_store_schedules_a_reopen() -> None:
    with (
        patch("product_app.run_history_store.get_store", return_value=None),
        patch("product_app.store_reconnect.threading.Thread", _FakeThread),
    ):
        store_reconnect.maybe_reconnect_run_history_store()

    assert _FakeThread.started == ["run-history-store-reconnect"]


def test_a_present_run_history_store_schedules_no_reopen() -> None:
    """``RunHistoryStore`` has no ``write_health()`` — nothing in this
    codebase ever built one for it, and #109's signal is FeedbackStore-only.
    So its trigger is absence alone, and a present store is left alone even
    if it is silently failing to write.

    This is a KNOWN, DELIBERATE narrowing, stated rather than hidden: closing
    it means porting the monotonic write-health stamps onto
    ``RunHistoryStore`` first, which is its own change.

    Turns red if: someone "helpfully" makes this call ``write_health()`` on a
    store that does not have one (an AttributeError at runtime, on the
    request path).
    """
    with (
        patch("product_app.run_history_store.get_store", return_value=object()),
        patch("product_app.store_reconnect.threading.Thread", _FakeThread),
    ):
        store_reconnect.maybe_reconnect_run_history_store()

    assert _FakeThread.started == []


# --------------------------------------------------------------------------
# the reopen bodies themselves
# --------------------------------------------------------------------------


def test_a_failed_reopen_leaves_the_previous_store_installed() -> None:
    """A reopen that raises must not clear the singleton — that would turn a
    transient failure into a permanent one, the exact bug being fixed.

    Turns red if: ``configure(...)`` is called before/regardless of whether
    ``from_env()`` succeeded.
    """
    configured: list[Any] = []

    with (
        patch(
            "product_app.feedback_store.FeedbackStore.from_env",
            side_effect=OSError("still locked"),
        ),
        patch("product_app.feedback_store.configure", side_effect=configured.append),
    ):
        store_reconnect._reopen_feedback_store()

    assert configured == [], "a failed reopen must not call configure() at all"


def test_a_successful_reopen_installs_the_new_store() -> None:
    """The positive partner: without it, a ``_reopen`` that did nothing at
    all would satisfy the failure test above.
    """
    sentinel = object()
    configured: list[Any] = []

    with (
        patch("product_app.feedback_store.FeedbackStore.from_env", return_value=sentinel),
        patch("product_app.feedback_store.configure", side_effect=configured.append),
    ):
        store_reconnect._reopen_feedback_store()

    assert configured == [sentinel]


def test_a_failed_feedback_reopen_sets_the_flag() -> None:
    """Issue #122's own signal: ``costs.py`` gates its BLOCK policy on this
    flag, not on staleness alone. If a failed reopen didn't set it, #122's
    fail-closed path would never fire even after a genuinely failed
    reconnect attempt."""
    store_reconnect._reset_for_tests()
    with patch(
        "product_app.feedback_store.FeedbackStore.from_env",
        side_effect=OSError("still locked"),
    ):
        store_reconnect._reopen_feedback_store()

    assert store_reconnect.feedback_reopen_tried_without_recovery() is True


def test_a_reopen_that_merely_OPENS_does_not_clear_the_flag() -> None:
    """The defect adversarial review found, at unit scale.

    ``FeedbackStore.from_env()`` on an existing, already-migrated database
    attempts ZERO writes, so it returns successfully even against a
    still-read-only volume. Treating that as "recovered" latched the flag to
    ``False`` on a reopen that fixed nothing, and #122's BLOCK then never
    fired for the very fault shape it exists to fix.

    The double reports ``"unverified"`` because that is what a real reopened
    handle reports on a still-broken volume — it has attempted no write yet.
    A signal-less stand-in would be the wrong shape here: absence of a signal
    reads as trustworthy by design, so the test would pass for the wrong
    reason.

    Turns red if: ``_reopen_feedback_store`` clears the flag on a
    non-raising open.
    """
    store_reconnect._reset_for_tests()

    class _FreshlyOpenedUnprovenStore:
        def write_health(self) -> str:
            return "unverified"

        def lost_billed_writes(self) -> int:
            return 0

    with (
        patch(
            "product_app.feedback_store.FeedbackStore.from_env",
            return_value=_FreshlyOpenedUnprovenStore(),
        ),
        patch("product_app.feedback_store.configure"),
    ):
        store_reconnect._reopen_feedback_store()

    assert store_reconnect.feedback_reopen_tried_without_recovery() is True, (
        "an open that wrote nothing is not evidence the store recovered"
    )


def test_a_landed_write_clears_the_flag() -> None:
    """The positive partner: the fail-closed policy MUST stand down once the
    store demonstrably writes again, or a one-off fault blocks an account
    forever. Only ``write_health() == "ok"`` counts as that evidence."""
    store_reconnect._reset_for_tests()
    store_reconnect._feedback_reopen_tried_without_recovery = True

    class _RecoveredStore:
        def write_health(self) -> str:
            return "ok"

    with (
        patch("product_app.feedback_store.get_store", return_value=_RecoveredStore()),
        patch("product_app.store_reconnect.threading.Thread", _FakeThread),
    ):
        store_reconnect.maybe_reconnect_feedback_store()

    assert store_reconnect.feedback_reopen_tried_without_recovery() is False


def test_a_freshly_reopened_unverified_store_does_not_clear_the_flag() -> None:
    """``"unverified"`` is neither stale nor recovered — and it is exactly
    what a reopen onto a still-broken volume leaves behind. Reading "not
    stale" as "recovered" here is what made the defect above survive.

    Turns red if: the clear condition widens from ``== "ok"`` to
    ``!= "failing"``.
    """
    store_reconnect._reset_for_tests()
    store_reconnect._feedback_reopen_tried_without_recovery = True

    class _UnverifiedStore:
        def write_health(self) -> str:
            return "unverified"

    with (
        patch("product_app.feedback_store.get_store", return_value=_UnverifiedStore()),
        patch("product_app.store_reconnect.threading.Thread", _FakeThread),
    ):
        store_reconnect.maybe_reconnect_feedback_store()

    assert store_reconnect.feedback_reopen_tried_without_recovery() is True


def test_a_landed_write_does_not_clear_the_flag_if_a_billed_charge_was_lost() -> None:
    """``write_health`` is NOT the money signal — its own docstring says so.

    The defect (adversarial review, round 2): the store is shared by every
    recorder, so a landed TELEMETRY write re-stamps ``"ok"`` over a lost
    charge. Keying recovery on health alone let one such reading stand the
    guard down; measured, ten priced requests then went through with
    ``daily_spend_for`` never consulted, because the store was ``"failing"``
    again by the time the cap looked. A whole cooldown window of unmetered
    spend, per flap.

    Turns red if: ``feedback_ledger_is_trustworthy`` drops the
    ``lost_billed_writes() == 0`` conjunct.
    """
    store_reconnect._reset_for_tests()
    store_reconnect._feedback_reopen_tried_without_recovery = True

    class _WroteButLostACharge:
        def write_health(self) -> str:
            return "ok"

        def lost_billed_writes(self) -> int:
            return 1

    with (
        patch("product_app.feedback_store.get_store", return_value=_WroteButLostACharge()),
        patch("product_app.store_reconnect.threading.Thread", _FakeThread),
    ):
        store_reconnect.maybe_reconnect_feedback_store()

    assert store_reconnect.feedback_reopen_tried_without_recovery() is True, (
        "a landed telemetry write must not stand the money guard down while "
        "a billed charge has been lost on this handle"
    )


def test_a_clean_handle_that_landed_a_write_does_clear_the_flag() -> None:
    """The positive partner for the test above. Without it, a predicate that
    always returned False would satisfy the loss case and block forever.

    ``lost_billed_writes`` is per-instance, so the fresh handle every reopen
    installs starts at zero — this is the ordinary recovery path, not an
    exotic one.
    """
    store_reconnect._reset_for_tests()
    store_reconnect._feedback_reopen_tried_without_recovery = True

    class _CleanRecoveredStore:
        def write_health(self) -> str:
            return "ok"

        def lost_billed_writes(self) -> int:
            return 0

    with (
        patch("product_app.feedback_store.get_store", return_value=_CleanRecoveredStore()),
        patch("product_app.store_reconnect.threading.Thread", _FakeThread),
    ):
        store_reconnect.maybe_reconnect_feedback_store()

    assert store_reconnect.feedback_reopen_tried_without_recovery() is False


def test_a_reopen_whose_new_handle_is_already_writable_does_not_arm_the_block() -> None:
    """The flag is set from the ATTEMPT'S OUTCOME, not from its start.

    A reopen that lands on a healthy volume produces a handle that has
    already written (schema/migration), so there is nothing to fail closed
    about. Arming here would refuse traffic on a store that just proved
    itself.

    Turns red if: the flag is set unconditionally at the top of
    ``_reopen_feedback_store`` (which is what shipped in round 1's fix and
    made the first sighting of staleness block).
    """
    store_reconnect._reset_for_tests()

    class _AlreadyWritingStore:
        def write_health(self) -> str:
            return "ok"

        def lost_billed_writes(self) -> int:
            return 0

    with (
        patch(
            "product_app.feedback_store.FeedbackStore.from_env",
            return_value=_AlreadyWritingStore(),
        ),
        patch("product_app.feedback_store.configure"),
    ):
        store_reconnect._reopen_feedback_store()

    assert store_reconnect.feedback_reopen_tried_without_recovery() is False


def test_a_write_health_that_raises_is_treated_as_stale_not_as_a_crash() -> None:
    """Adversarial review (#122): the ``callable(...)`` guard only covered a
    MISSING method. A ``write_health`` that EXISTS and raises propagated
    straight out of ``estimate()`` — the request path for
    ``POST /v1/query-runs/estimate`` — which is the bare-500-with-no-error-
    envelope outcome #122 says must never ship as the fix. Reproduced by
    execution before this guard existed, and the first raiser was this
    module's own trigger, one frame before ``costs.py`` ever looked.

    A store that blows up when asked its own health is not a healthy store,
    so it reads as stale rather than as a clean bill of health.

    Turns red if: the ``try/except`` in ``feedback_ledger_is_stale`` is
    dropped (the call then raises out of this test).
    """

    class _ExplodingStore:
        def write_health(self) -> str:
            raise RuntimeError("simulated write_health explosion")

    assert store_reconnect.feedback_ledger_is_stale(_ExplodingStore()) is True
    assert store_reconnect.feedback_ledger_is_trustworthy(_ExplodingStore()) is False


def test_a_store_with_no_write_health_signal_is_neither_stale_nor_distrusted() -> None:
    """The distinction the two predicates rest on. A narrow duck-typed double
    (or any implementation predating #109) has no signal at all — that is an
    ABSENCE of evidence, not evidence of a fault. So it reads as neither
    stale nor untrustworthy: nothing ever suggested it was broken, and
    refusing traffic over a store type that simply never carried the signal
    would be a wrongful block.

    Production-unreachable either way — only ``FeedbackStore`` is ever passed
    to ``configure()`` in ``src/`` — so this pins the contract for test
    doubles rather than a live code path.
    """

    class _NoSignalStore:
        pass

    assert store_reconnect.feedback_ledger_is_stale(_NoSignalStore()) is False
    assert store_reconnect.feedback_ledger_is_trustworthy(_NoSignalStore()) is True


def test_a_failed_run_history_reopen_leaves_the_previous_store_installed() -> None:
    """Same contract as the feedback store's failure path, on the sibling
    reopen body — the two are separate functions, so one being right proves
    nothing about the other.
    """
    configured: list[Any] = []

    with (
        patch(
            "product_app.run_history_store.RunHistoryStore.from_env",
            side_effect=OSError("still locked"),
        ),
        patch("product_app.run_history_store.configure", side_effect=configured.append),
    ):
        store_reconnect._reopen_run_history_store()

    assert configured == [], "a failed reopen must not call configure() at all"


def test_a_successful_run_history_reopen_installs_the_new_store() -> None:
    """Positive partner for the sibling reopen body."""
    sentinel = object()
    configured: list[Any] = []

    with (
        patch("product_app.run_history_store.RunHistoryStore.from_env", return_value=sentinel),
        patch("product_app.run_history_store.configure", side_effect=configured.append),
    ):
        store_reconnect._reopen_run_history_store()

    assert configured == [sentinel]


# --------------------------------------------------------------------------
# the actual call site — CostEstimationService.estimate()
# --------------------------------------------------------------------------


def test_estimate_actually_calls_both_reconnect_triggers() -> None:
    """Review finding: every test above drives ``store_reconnect`` directly,
    so none of them would notice if ``CostEstimationService.estimate()`` —
    the real call site, the one place this is supposed to run on every
    request — stopped calling it at all.

    Turns red if: either call is removed from ``estimate()``.
    """
    from uuid import uuid4

    from product_app.costs import cost_estimation_service
    from product_app.model_slots import ModelSlot

    slots = [
        ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini", search=True),
        ModelSlot(slot_number=2, model_id="anthropic/claude-haiku-4.5", search=True),
        ModelSlot(slot_number=3, model_id="google/gemini-2.5-flash", search=True),
        ModelSlot(slot_number=4, model_id="nvidia/nemotron-3-nano-30b-a3b", search=True),
    ]

    with (
        patch("product_app.store_reconnect.maybe_reconnect_feedback_store") as feedback_call,
        patch("product_app.store_reconnect.maybe_reconnect_run_history_store") as run_history_call,
    ):
        cost_estimation_service.estimate(
            query_text="a real question", model_slots=slots, account_id=uuid4()
        )

    feedback_call.assert_called_once_with()
    run_history_call.assert_called_once_with()
