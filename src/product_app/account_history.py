"""Signed-in history (W7, second pull request, part a; ADR-0135).

A signed-in account keeps a summary of its newest finished runs: the
question, when, how and at what estimated cost it ran. Never the answer. The
owner decided the purpose and the "last 5" (CHG-012 D7), carrying over the
same browser session's runs at sign-in (CHG-021 a), and storing the question
text (2026-09-26, 15:05:11Z). Failure modes:
``docs/analysis/2026-09-26-w7-history-failure-modes.md``.

Whose history a finished run joins:

* a run of a signed-in account joins that account's history;
* a run of an anonymous session that has since signed in joins the signed-in
  account's history. The sign-in callback records the link here
  (:func:`carry_over`), in memory, for as long as a run can still be running
  (``QUERY_RUN_ACTIVE_TTL``). That covers the promised race: a run still
  running at sign-in finishes under its anonymous id and is carried then;
* any other run joins nothing.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID

from product_app import session_store
from product_app.config import settings
from product_app.query_run_orchestration import (
    QUERY_RUN_ACTIVE_TTL,
    QueryRun,
    query_run_repository,
)
from product_app.session_store import HistoryEntry

_log = logging.getLogger(__name__)

_lock = threading.Lock()
#: anonymous account id -> (signed-in account id, when the link lapses)
_carried: dict[UUID, tuple[UUID, datetime]] = {}


def _now() -> datetime:
    return datetime.now(UTC)


def _owner(account_id: UUID, now: datetime) -> UUID | None:
    """The signed-in account whose history a run of ``account_id`` joins."""
    store = session_store.get_store()
    if store is not None and store.account_for(account_id) is not None:
        return account_id
    with _lock:
        link = _carried.get(account_id)
        if link is None:
            return None
        if link[1] < now:
            del _carried[account_id]
            return None
        return link[0]


def _entry(query_run: QueryRun, owner: UUID) -> HistoryEntry:
    return HistoryEntry(
        query_run_id=str(query_run.query_run_id),
        account_id=str(owner),
        question=query_run.query_text,
        status=query_run.status.value,
        mode=query_run.mode,
        model_count=len(query_run.model_slots),
        cost_usd=query_run.cost_estimate.estimated_cost_usd,
        completed_at=query_run.updated_at,
        verdict=query_run.history_verdict,
    )


def _write(entry: HistoryEntry, now: datetime) -> None:
    store = session_store.get_store()
    if store is None:
        return
    if not store.record_history(
        entry,
        keep_count=settings.history_keep_count,
        keep_days=settings.history_keep_days,
        now=now,
    ):
        _log.warning("account history: a finished run could not be recorded")


def record_finished_run(query_run: QueryRun) -> None:
    """Add a finished run to its owner's history, if it has one. Best effort:
    a failure is logged and never reaches the run."""
    try:
        if not query_run.is_terminal:
            return
        now = _now()
        owner = _owner(query_run.account_id, now)
        if owner is not None:
            _write(_entry(query_run, owner), now)
    except Exception:
        _log.exception("account history: recording a finished run failed")


def _link_lifetime() -> timedelta:
    """How long a sign-in link waits for a run still running: as long as one
    can run, the longer of the repository's active lifetime and the run
    deadline (which a setting can raise to an hour)."""
    return max(QUERY_RUN_ACTIVE_TTL, timedelta(seconds=settings.quorum_run_deadline_seconds))


def carry_over(*, anonymous_account_id: UUID, account_id: UUID) -> None:
    """At sign-in: the signing-in session's finished runs join the account's
    history now, and any run of it still running joins when it finishes. Only
    an ANONYMOUS session's runs: a session already signed in as another
    account carries nothing (review found a switch moved one account's
    questions into another's). The keep rules then apply as for any write."""
    try:
        store = session_store.get_store()
        if store is None or store.is_anonymous(anonymous_account_id) is not True:
            return
        now = _now()
        with _lock:
            _carried[anonymous_account_id] = (account_id, now + _link_lifetime())
        for query_run in query_run_repository.terminal_runs_for_account(anonymous_account_id):
            _write(_entry(query_run, account_id), now)
    except Exception:
        _log.exception("account history: carrying runs over at sign-in failed")


def history_for(account_id: UUID) -> list[HistoryEntry] | None:
    """The account's history, or ``None`` if it could not be read."""
    store = session_store.get_store()
    if store is None:
        return None
    return store.history_for(
        str(account_id),
        keep_count=settings.history_keep_count,
        keep_days=settings.history_keep_days,
        now=_now(),
    )


def clear_carried() -> None:
    """Tests: forget every sign-in link."""
    with _lock:
        _carried.clear()
