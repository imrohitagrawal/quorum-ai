"""Background reconnect for the two durable SQLite sinks (issue #123).

``feedback_store`` and ``run_history_store`` each open their sink exactly
once, at import time in ``main.py``. A transient lock at boot — or a volume
that goes read-only mid-life — used to disable the per-account 24h spend cap
(and run-history persistence) for the entire process lifetime, with no way
back short of a restart.

Built on top of the write-health signal ``feedback_store.FeedbackStore``
already carries (issue #109), not on ``get_store() is None``: a store that
opened successfully but can no longer WRITE (the read-only-volume-under-an-
already-open-handle shape #109 measured) would never trigger a reopen keyed
on absence alone. ``run_history_store.RunHistoryStore`` carries no equivalent
signal — nothing in this codebase has ever built one for it — so its trigger
is deliberately narrower: ``get_store() is None`` only, which still covers
the loud, documented boot-lock case.

Triggered from the request thread (the next ``estimate`` call, per the
issue's own suggested shape) but the actual reopen work — a fresh
``FeedbackStore.from_env()`` / ``RunHistoryStore.from_env()`` call, which can
block for SQLite's default 5-second lock-open timeout — always runs on a
background thread, so a user's request is never the one that pays that cost.
A monotonic cooldown (``settings.store_reconnect_cooldown_seconds``) keeps a
sustained outage from spawning a new attempt thread on every single request;
an unauthenticated caller hammering the endpoint during an outage still costs
at most one reopen attempt per cooldown window, not one per request.

``configure()`` on both modules deliberately does not close the store it
displaces (pinned by
``tests/test_store_lifecycle.py::test_configure_does_not_close_the_displaced_store``),
so calling it here to install a freshly-reopened store is exactly as safe as
any other call site already relies on it being.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from product_app.config import settings

_log = logging.getLogger(__name__)

#: Guards the two cooldown timestamps below so two racing request threads
#: cannot both decide they are the one that gets to spawn a reopen attempt.
_lock = threading.Lock()
_feedback_last_attempt_at: float | None = None
_run_history_last_attempt_at: float | None = None


def _reset_for_tests() -> None:
    """Clear both cooldown timestamps. Test-only — a real process never needs
    to forget it just tried."""
    global _feedback_last_attempt_at, _run_history_last_attempt_at
    with _lock:
        _feedback_last_attempt_at = None
        _run_history_last_attempt_at = None


def _spawn(target: Callable[[], None], *, name: str) -> None:
    """Start a background reopen, never letting thread creation itself
    become a request failure.

    Adversarial review (#123): ``threading.Thread(...).start()`` can raise
    (real thread-count exhaustion under a container's process limits), and
    the caller is ``CostEstimationService.estimate()`` — the request path
    for ``POST /v1/query-runs/estimate`` — with no surrounding try/except.
    An uncaught exception here would turn "best-effort background
    reconnect" into a 500 on that endpoint, recurring once per cooldown
    window for as long as thread exhaustion persists — worse than doing
    nothing at all, and the opposite of what "off the request thread" is
    supposed to buy.
    """
    try:
        threading.Thread(target=target, daemon=True, name=name).start()
    except Exception as exc:  # noqa: BLE001 - must never break the caller's request
        _log.error("store_reconnect: could not start reopen thread %r: %s", name, exc)


def _reopen_feedback_store() -> None:
    from product_app.feedback_store import FeedbackStore
    from product_app.feedback_store import configure as configure_feedback_store

    try:
        store = FeedbackStore.from_env()
    except Exception as exc:  # noqa: BLE001 - best-effort background reopen
        _log.error(
            "store_reconnect: feedback store reopen attempt failed — the "
            "per-account 24h daily spend cap is still NOT being enforced: %s",
            exc,
        )
        return
    configure_feedback_store(store)
    _log.info("store_reconnect: feedback store reopened — the daily spend cap is enforced again")


def _reopen_run_history_store() -> None:
    from product_app.run_history_store import RunHistoryStore
    from product_app.run_history_store import configure as configure_run_history_store

    try:
        store = RunHistoryStore.from_env()
    except Exception as exc:  # noqa: BLE001 - best-effort background reopen
        _log.warning("store_reconnect: run_history store reopen attempt failed: %s", exc)
        return
    configure_run_history_store(store)
    _log.info("store_reconnect: run_history store reopened")


def maybe_reconnect_feedback_store(*, monotonic: Callable[[], float] = time.monotonic) -> None:
    """Attempt a feedback-store reopen if it is due, off the calling thread.

    Cheap on the common (healthy-store) path: reads one enum-valued property
    under a lock the store already holds, no cooldown bookkeeping happens
    unless a reopen is actually needed.
    """
    if not settings.store_reconnect_enabled:
        return
    from product_app.feedback_store import get_store

    store = get_store()
    # ``getattr``, not a bare ``store.write_health()``: the singleton holds
    # whatever any caller passed to ``configure()``, and several existing
    # tests install a narrow duck-typed double that implements only the one
    # method under test. Calling an assumed method on it raised
    # AttributeError on the REQUEST PATH — caught by
    # tests/unit/test_cost_rail_units.py the first time this ran against the
    # full suite, not by reasoning. A store that cannot report its write
    # health cannot report "failing", so it is left alone.
    health = getattr(store, "write_health", None)
    needs_reconnect = store is None or (callable(health) and health() == "failing")
    if not needs_reconnect:
        return

    global _feedback_last_attempt_at
    now = monotonic()
    with _lock:
        last = _feedback_last_attempt_at
        if last is not None and (now - last) < settings.store_reconnect_cooldown_seconds:
            return
        _feedback_last_attempt_at = now

    _spawn(_reopen_feedback_store, name="feedback-store-reconnect")


def maybe_reconnect_run_history_store(*, monotonic: Callable[[], float] = time.monotonic) -> None:
    """Attempt a run-history-store reopen if it is due, off the calling thread.

    Narrower trigger than the feedback store's: ``RunHistoryStore`` carries no
    write-health signal, so this only ever fires on the loud, documented
    boot-lock case (``get_store() is None``), not on a store that opened but
    silently stopped writing.
    """
    if not settings.store_reconnect_enabled:
        return
    from product_app.run_history_store import get_store

    if get_store() is not None:
        return

    global _run_history_last_attempt_at
    now = monotonic()
    with _lock:
        last = _run_history_last_attempt_at
        if last is not None and (now - last) < settings.store_reconnect_cooldown_seconds:
            return
        _run_history_last_attempt_at = now

    _spawn(_reopen_run_history_store, name="run-history-store-reconnect")
