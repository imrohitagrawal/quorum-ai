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

    The reopen body itself is exercised directly by the last two tests in
    this file; here we only care whether the trigger decided to spawn one.
    """

    started: list[str] = []

    def __init__(self, *, target: Any, daemon: bool, name: str) -> None:
        self._target = target
        self.name = name
        self.daemon = daemon

    def start(self) -> None:
        _FakeThread.started.append(self.name)


@pytest.fixture(autouse=True)
def _clean_reconnect_state() -> Any:
    """Reset both cooldown stamps and the recorded thread starts.

    Autouse because the cooldown timestamps are module globals: a test that
    triggers a reconnect would otherwise suppress the next test's trigger
    for a full 60-second window, making these order-dependent.
    """
    store_reconnect._reset_for_tests()
    _FakeThread.started = []
    yield
    store_reconnect._reset_for_tests()
    _FakeThread.started = []


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
