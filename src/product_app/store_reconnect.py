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

#: Issue #122: has a feedback-store reopen COMPLETED without the store
#: having demonstrably recovered since? ``False`` at process start and
#: cleared only by a LANDED write (``write_health() == "ok"``).
#:
#: Deliberately NOT "did the reopen raise". Adversarial review of this
#: change reproduced why, end to end against a real read-only volume:
#: ``FeedbackStore.from_env()`` on an already-schema'd, already-migrated
#: database — the production shape, which ``fly.toml`` pins — attempts ZERO
#: writes at open time, so it opens WITHOUT RAISING even while the volume is
#: still read-only. Keying on "did it raise" therefore latched this flag
#: back to ``False`` on a reopen that fixed nothing, and installed a fresh
#: handle reporting ``"unverified"``. The next billed write failed, health
#: flipped back to ``"failing"``, and the flag was still ``False`` — so
#: ``costs.py`` took the allow-and-log branch. Every subsequent reopen
#: repeated the cycle, meaning the BLOCK never fired for the exact fault
#: shape issue #122 exists to fix. Measured, not theorised:
#: ``tests/integration/test_stale_ledger_block_on_a_real_volume.py``.
#:
#: ``"unverified"`` is the load-bearing state: it is neither stale nor
#: recovered, so it must not clear this flag. Only evidence of a landed
#: write does.
_feedback_reopen_tried_without_recovery: bool = False


def _reset_for_tests() -> None:
    """Clear both cooldown timestamps and the reopen flag. Test-only — a
    real process never needs to forget it just tried."""
    global _feedback_last_attempt_at, _run_history_last_attempt_at
    global _feedback_reopen_tried_without_recovery
    with _lock:
        _feedback_last_attempt_at = None
        _run_history_last_attempt_at = None
        _feedback_reopen_tried_without_recovery = False


def feedback_reopen_tried_without_recovery() -> bool:
    """Has a reopen COMPLETED with the store still not proven writable?

    Completed, not merely started — the flag is written after
    ``FeedbackStore.from_env()`` returns or raises, so during a slow or hung
    open this still reads whatever the previous attempt concluded. That
    matters: ``costs.py`` gates its fail-closed policy on this, and the
    operator's policy is "block only after a reopen has actually been TRIED
    AND FAILED", not "after one has been scheduled".

    ``costs.estimate`` additionally SNAPSHOTS this before spawning its own
    reconnect, so a reopen a request starts can never condemn that same
    request. See the comment at that call site for the measurement behind it.
    """
    return _feedback_reopen_tried_without_recovery


def feedback_ledger_is_stale(store: object | None) -> bool:
    """Is there positive evidence this store's ledger is FAULTY?

    Drives two things: whether to attempt a reconnect, and whether
    ``costs.py`` emits its loud daily-cap-bypass log. NOT the block decision
    — that is :func:`feedback_ledger_is_trustworthy`, and the two are
    deliberately not each other's negation (see its docstring).

    ONE definition for both readers — this module's reconnect trigger and
    ``costs.CostEstimationService.estimate``'s daily-cap guard — because two
    copies of a money-guard predicate drift. Three inputs, three answers:

    * **No store at all** → stale. Issue #101's boot-lock shape.
    * **A store with no ``write_health``** → NOT stale. The signal was never
      built for that type (a narrow duck-typed double, or any implementation
      predating issue #109). Absence of a signal is not evidence of a fault,
      and treating it as one would refuse traffic over an older store type.
      Regression-guarded: calling this method unconditionally raised
      ``AttributeError`` on the REQUEST PATH, caught by
      ``tests/unit/test_cost_rail_units.py``, not by reasoning.
    * **A store whose ``write_health`` RAISES** → stale, and the exception is
      swallowed. Distinct from the case above: there the signal was never
      built; here it exists and is malfunctioning, which is itself evidence
      the store is not well. Found by adversarial review of issue #122 and
      reproduced by execution — before this, the exception propagated out of
      ``estimate()``, which is the request path for
      ``POST /v1/query-runs/estimate``, producing exactly the bare 500 with
      no error envelope that #122 says must never ship as the "fix". Note
      the first raiser was this module's own trigger (issue #123), one frame
      before ``costs.py`` ever got to look.

    Stale on its own never blocks anything — ``costs.py`` blocks on
    :func:`feedback_reopen_tried_without_recovery` AND the absence of
    :func:`feedback_ledger_is_trustworthy`. The operator-facing announcement
    is the rate-limited ERROR in ``costs._log_daily_cap_bypassed`` that
    already fires for this state, so the ``debug`` below is deliberate: this
    runs twice per priced request, and an unbounded ERROR here would spam a
    money path that is already announcing itself once per window.
    """
    if store is None:
        return True
    health = getattr(store, "write_health", None)
    if not callable(health):
        return False
    try:
        return bool(health() == "failing")
    except Exception:  # noqa: BLE001 - must never break the caller's request
        _log.debug(
            "store_reconnect: write_health() raised; treating the ledger as stale",
            exc_info=True,
        )
        return True


def feedback_ledger_may_be_metered(store: object | None) -> bool:
    """May the daily spend cap be COMPUTED from this store's rows?

    A THIRD question, distinct from both predicates below, and the distinction
    is a live money leak's worth of important.

    * :func:`feedback_ledger_is_stale` → "should we reconnect?"
    * :func:`feedback_ledger_is_trustworthy` → "has this handle PROVEN it
      writes?" — requires an actual landed write, so a cold store answers
      False.
    * this one → "are the rows on disk missing money?"

    True unless there is positive evidence the ledger is INCOMPLETE:

    * no store at all → False.
    * ``write_health() == "failing"``, or a ``write_health`` that raises →
      False. Writes are being lost right now.
    * ``lost_billed_writes() > 0`` → False. Billed charges have been dropped,
      and the counter is monotonic precisely so a later unrelated write cannot
      hide that.
    * everything else → True, INCLUDING ``"unverified"``.

    ``"unverified"`` must meter, and getting that wrong is not hypothetical —
    it broke the A/B control test the moment this function's first draft used
    ``trustworthy`` here instead. ``"unverified"`` means "this handle has
    attempted no write yet", which is the ORDINARY state of a cold process:
    ``fly.toml`` sets ``min_machines_running = 0``, and every read-only
    surface writes nothing. The rows are on disk regardless. Refusing to meter
    there would silently disable the cap on every cold boot — a far bigger
    hole than the one being closed.

    The leak this closes, MEASURED against a real SQLite lock: the allow path
    used to key on ``is_stale`` alone, so the cell ``write_health() == "ok"``
    AND ``lost_billed_writes() >= 1`` metered against a ledger missing money —
    12 requests allowed, real spend $0.3180, ledger reporting $0.00 against a
    $0.20 cap, zero billed rows on disk, and unbounded. Any ordinary telemetry
    write re-stamps health to ``"ok"``, which is exactly what makes the
    monotonic counter, not the health comparator, the signal that matters here.
    """
    if store is None:
        return False
    if feedback_ledger_is_stale(store):
        return False
    lost = getattr(store, "lost_billed_writes", None)
    if not callable(lost):
        # A store type that never carried the counter cannot be judged by it —
        # same rule as the missing-``write_health`` case elsewhere in this
        # module. Absence of a signal is not evidence of loss.
        return True
    try:
        return int(lost()) == 0
    except Exception:  # noqa: BLE001 - must never break the caller's request
        return False


def feedback_ledger_is_trustworthy(store: object | None) -> bool:
    """May the daily spend cap be METERED off this store's ledger?

    Deliberately NOT the negation of :func:`feedback_ledger_is_stale`, and
    the gap between them is the whole point of this pair. They answer two
    different questions:

    * :func:`feedback_ledger_is_stale` → "should we attempt a reconnect?"
      True only on positive evidence of a fault (no store, or ``"failing"``).
      A cold ``"unverified"`` store must NOT drag a reopen out of every quiet
      boot, so it answers False there.
    * this function → "may we bill against what this ledger says?" True only
      on positive evidence the ledger is sound. ``"unverified"`` answers
      False: a handle that has attempted no write yet has demonstrated
      nothing, and it is exactly the state a reopen onto a still-broken
      read-only volume leaves behind.

    That asymmetry is what removes a measured flicker. A reopen installs an
    ``"unverified"`` handle; if "not stale" were read as "fine", the very
    next request would allow and meter off a frozen ledger, once per cooldown
    window, for the whole outage. Requiring positive evidence here means the
    block holds continuously from the first completed reopen until a write
    actually lands.

    ``write_health() == "ok"`` is NECESSARY BUT NOT SUFFICIENT, and getting
    that wrong was the third defect adversarial review found here.
    ``feedback_store.lost_billed_writes``'s own docstring says it in capitals:
    *write_health is not the money signal* — it reports the store's LAST
    write, whoever made it, so a landed telemetry write re-stamps success over
    a lost charge. Measured with a flapping fault: one ``"ok"`` reading stood
    the guard down, and ten subsequent priced requests went through with
    ``daily_spend_for`` never consulted once, because the store had gone
    ``"failing"`` again by the time the cap looked. That is the pre-#122 leak
    returning for a whole cooldown window, per flap.

    So a landed write must ALSO come with no billed charge lost on this
    handle. ``lost_billed_writes`` counts exactly the ``(recorder,
    event_type)`` pair ``daily_spend_for`` sums, and it is per-instance: every
    reopen installs a FRESH handle whose count starts at zero. So a handle
    that has lost a charge stays untrustworthy for its whole life, and
    recovery arrives the ordinary way — the next reopen's fresh handle lands a
    write and loses nothing, and no standing down on a signal that cannot see
    the money.

    "No permanent block" is TRUE ONLY BECAUSE of the second clause in
    ``maybe_reconnect_feedback_store``'s reopen condition. An earlier draft of
    this sentence asserted it while the code deadlocked: a handle that had lost
    a charge could never become trustworthy, and the reopen that would replace
    it was gated on staleness, which recovery cleared. See that call site for
    the measured sequence.

    A store with NO ``write_health`` at all answers **True**: the signal was
    never built for that type (a narrow duck-typed double, or any
    implementation predating issue #109), so nothing has ever suggested a
    fault and the pre-#109 posture — trust it — is the honest one. Absence of
    a signal is not evidence of a fault. Such a store is never stale either,
    so the two predicates agree about it.
    """
    if store is None:
        return False
    health = getattr(store, "write_health", None)
    if not callable(health):
        return True
    try:
        if health() != "ok":
            return False
    except Exception:  # noqa: BLE001 - must never break the caller's request
        return False
    lost = getattr(store, "lost_billed_writes", None)
    if not callable(lost):
        # Same rule as the missing-write_health case above: a type that never
        # carried the counter cannot be judged by it.
        return True
    try:
        return int(lost()) == 0
    except Exception:  # noqa: BLE001 - must never break the caller's request
        return False


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
        if target is _reopen_feedback_store:
            # A reopen was DUE and could not even be started, so it has been
            # tried and has not restored anything — record that, or issue
            # #122's fail-closed cap silently fails OPEN.
            #
            # Found by the end-of-batch adversarial review: the flag is set
            # inside ``_reopen_feedback_store``, which never runs if the thread
            # cannot start, while ``_spawn`` swallows the failure AND the
            # cooldown has already been stamped. Measured with ``Thread.start``
            # raising (the real shape of container thread exhaustion): 25 of 25
            # requests allowed against a frozen ledger, ``daily_spend_for``
            # consulted zero times, the flag never set. Thread exhaustion is
            # exactly when a deployment is least healthy, so failing open there
            # is the wrong direction.
            global _feedback_reopen_tried_without_recovery
            _feedback_reopen_tried_without_recovery = True
        _log.error("store_reconnect: could not start reopen thread %r: %s", name, exc)


def _reopen_feedback_store() -> None:
    from product_app.feedback_store import FeedbackStore
    from product_app.feedback_store import configure as configure_feedback_store

    global _feedback_reopen_tried_without_recovery
    try:
        store = FeedbackStore.from_env()
    except Exception as exc:  # noqa: BLE001 - best-effort background reopen
        # Tried, and failed outright.
        _feedback_reopen_tried_without_recovery = True
        _log.error(
            "store_reconnect: feedback store reopen attempt failed — the "
            "per-account 24h daily spend cap is still NOT being enforced: %s",
            exc,
        )
        return
    configure_feedback_store(store)
    # Tried, and the open did not raise — which is NOT the same as recovered.
    # On the production shape (an existing, already-migrated database) the
    # open attempts zero writes and succeeds against a still-read-only
    # volume, leaving a handle that reports ``"unverified"``. So the outcome
    # is judged on what the NEW store can actually show, not on the absence
    # of an exception. Set AFTER the attempt completes, so the flag means
    # what its name says: a reopen was tried and did not restore writability.
    _feedback_reopen_tried_without_recovery = not feedback_ledger_is_trustworthy(store)
    _log.info(
        "store_reconnect: feedback store reopened — the daily spend cap is "
        "enforced again once a write lands on the new handle"
    )


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
    # Issue #122: a LANDED write is the only thing that stands the
    # fail-closed policy down. Checked on every call — this is the one place
    # that reliably observes the store after a reopen has had time to be
    # exercised by real traffic, since the reopen itself proves nothing.
    global _feedback_reopen_tried_without_recovery
    if _feedback_reopen_tried_without_recovery and feedback_ledger_is_trustworthy(store):
        _feedback_reopen_tried_without_recovery = False
        _log.info(
            "store_reconnect: a write landed on the reopened feedback store — "
            "the per-account 24h daily spend cap is enforced again"
        )

    # A reopen is due when the ledger shows a fault, OR when we are already
    # failing closed and the current handle still cannot be shown to write.
    #
    # THE SECOND CLAUSE EXISTS BECAUSE THE FIRST ALONE DEADLOCKS — found by the
    # end-of-batch holistic review, the only pass that could see it: issue #122
    # owns the predicate and issue #123 owns this trigger, so each per-issue
    # review saw half of it. Reproduced end to end against a real SQLite
    # RESERVED lock (a fault feedback_store documents as recovering on the
    # SAME handle):
    #
    #   fault begins        health=failing    lost=1  stale=True   flag=False
    #   after reopen        health=unverified lost=0  stale=False  flag=True
    #   new handle loses 1  health=failing    lost=1  stale=True   flag=True
    #   OPERATOR FIXES IT   health=ok         lost=1  stale=False  flag=True
    #   +5 more requests    health=ok         lost=1  stale=False  flag=True
    #
    # ``lost_billed_writes`` is monotonic per handle and never resets, so once
    # the reopened handle has lost even one charge, ``trustworthy`` can never
    # go true for it again. The clear-path needs ``trustworthy``; the reopen
    # that would supply a clean handle needed ``stale``, which recovery had
    # just made False. Every priced request 402s until a process restart —
    # precisely the "no way back short of a restart" issue #123 exists to
    # remove, reintroduced by its own sibling fix.
    #
    # Keying the retry on ``not trustworthy`` while the flag is set keeps
    # trying for a clean handle, and cannot fire on a quiet boot: the flag is
    # False there, so an ordinary ``"unverified"`` cold store still drags no
    # reopen out of every idle process.
    #
    # The underlying mistake was mine and is worth naming: I used
    # ``lost_billed_writes`` — a COMPLETENESS signal, permanently true once
    # anything has been lost — to answer a LIVENESS question ("is this store
    # broken right now"). It still belongs in ``trustworthy``, because a handle
    # that dropped a charge must not be metered against; it just cannot be the
    # only thing gating the retry that would replace that handle.
    # REOPEN WHENEVER THE LEDGER CANNOT BE METERED. This subsumes staleness and
    # needs no flag: `may_be_metered` is already False for no store, for
    # "failing", for a raising signal, and for any handle that has dropped a
    # billed charge.
    #
    # The flag-based version this replaces had ANOTHER absorbing state, found
    # by `tests/unit/test_spend_cap_state_table.py` the day it was written --
    # in code committed hours earlier. `("ok", lost=1, tried=False)`: a charge
    # was lost during a window in which no request happened to observe the
    # store, so no reopen was ever triggered and the flag stayed False; by the
    # next request the handle had recovered to "ok", so it was not stale
    # either. The counter is monotonic, so it could never be metered again,
    # and nothing would ever replace the handle. The cap silently stopped
    # working for the life of the process.
    #
    # That is the SIXTH defect in this predicate and the third of the same
    # shape. The lesson is in the shape, not the instance: a decision derived
    # from a process-global flag written by two thread classes keeps producing
    # dead ends. Deriving it from the handle alone does not.
    if feedback_ledger_may_be_metered(store):
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
