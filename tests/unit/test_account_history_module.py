"""W7, 2a — account_history's fail-safe paths (ADR-0135).

History is best effort: no failure here may reach the run or the sign-in.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from product_app import account_history, session_store
from product_app.query_run_orchestration import query_run_repository
from product_app.session_store import HistoryEntry

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def _entry() -> HistoryEntry:
    return HistoryEntry(
        query_run_id="r",
        account_id="a",
        question="q",
        status="completed",
        mode="panel",
        model_count=2,
        cost_usd=Decimal("0.01"),
        completed_at=NOW,
    )


def test_no_store_writes_nothing_and_reads_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turns red if a missing store raises, or reads as an empty history."""
    monkeypatch.setattr(session_store, "get_store", lambda: None)
    account_history._write(_entry(), NOW)  # must not raise
    assert account_history.history_for(uuid4()) is None


def test_a_refused_write_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Turns red if a failed history write is silent."""

    class Refusing:
        def record_history(self, *args: Any, **kwargs: Any) -> bool:
            return False

    monkeypatch.setattr(session_store, "get_store", lambda: Refusing())
    caplog.set_level(logging.WARNING, logger="product_app.account_history")
    account_history._write(_entry(), NOW)
    assert "a finished run could not be recorded" in caplog.text


def test_an_error_while_recording_never_reaches_the_run(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Turns red if an exception in history escapes record_finished_run."""

    def boom(*args: Any) -> None:
        raise RuntimeError("history broke")

    class Run:
        is_terminal = True
        account_id = uuid4()

    monkeypatch.setattr(account_history, "_owner", boom)
    caplog.set_level(logging.ERROR, logger="product_app.account_history")
    account_history.record_finished_run(Run())  # type: ignore[arg-type]
    assert "recording a finished run failed" in caplog.text


def test_an_error_while_carrying_over_never_reaches_the_sign_in(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Turns red if an exception in carry-over escapes into the callback."""

    class Anonymous:
        def is_anonymous(self, _id: Any) -> bool:
            return True

    def boom(_id: Any) -> list[Any]:
        raise RuntimeError("repository broke")

    monkeypatch.setattr(session_store, "get_store", lambda: Anonymous())
    monkeypatch.setattr(query_run_repository, "terminal_runs_for_account", boom)
    caplog.set_level(logging.ERROR, logger="product_app.account_history")
    account_history.carry_over(anonymous_account_id=uuid4(), account_id=uuid4())
    assert "carrying runs over at sign-in failed" in caplog.text
    account_history.clear_carried()
