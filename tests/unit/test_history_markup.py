"""W7, 2a — the exact history markup and signed-in lede (ADR-0135).

Pinned whole, so a change to any tag, class, word or the time shown turns
this red (CI's mutation job found fragment checks let markup mutants live).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from product_app import account_history, main
from product_app.session_store import HistoryEntry, _to_utc


def _entries() -> list[HistoryEntry]:
    ist = timezone(timedelta(hours=5, minutes=30))
    return [
        HistoryEntry(
            query_run_id="r1",
            account_id="a",
            question="Why <this>?",
            status="timed_out",
            mode="panel",
            model_count=4,
            cost_usd=Decimal("0.0412"),
            # 17:30 in India is 12:00 UTC: the page shows UTC.
            completed_at=datetime(2026, 9, 26, 17, 30, tzinfo=ist),
            verdict="3 of 4 opening positions carried into the final answer",
        ),
        HistoryEntry(
            query_run_id="r2",
            account_id="a",
            question="Quick one",
            status="completed",
            mode="quick",
            model_count=1,
            cost_usd=Decimal("0.0100"),
            completed_at=datetime(2026, 9, 25, 9, 5, tzinfo=UTC),
            verdict=None,
        ),
    ]


def test_the_history_markup_is_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turns red if any tag, class, id, word, separator or the UTC time in
    the history box changes."""
    monkeypatch.setattr(account_history, "history_for", lambda _id: _entries())
    assert main._history_html(uuid4()) == (
        '<details class="account-history" id="account-history">'
        '<summary class="topbar-howitworks">History</summary>'
        '<div class="account-history-panel" tabindex="0" role="region" '
        'aria-label="Your question history">'
        '<p class="history-note">Your last 5 questions, kept 30 days. Answers are not kept.</p>'
        '<ol class="history-list" id="account-history-list">'
        '<li class="history-item"><span class="history-question">Why &lt;this&gt;?</span>'
        '<span class="history-meta">2026-09-26 12:00 UTC · timed out · 4 models · '
        "3 of 4 opening positions carried into the final answer · estimated $0.0412</span></li>"
        '<li class="history-item"><span class="history-question">Quick one</span>'
        '<span class="history-meta">2026-09-25 09:05 UTC · completed · quick answer · '
        "estimated $0.0100</span></li>"
        "</ol></div></details>"
    )


@pytest.mark.parametrize(
    ("entries", "body"),
    [
        ([], '<p class="history-empty" id="account-history-empty">No questions yet.</p>'),
        (
            None,
            '<p class="history-empty" id="account-history-unavailable">'
            "Your history could not be loaded just now.</p>",
        ),
    ],
    ids=["empty", "unavailable"],
)
def test_the_empty_and_unavailable_states_are_exact(
    monkeypatch: pytest.MonkeyPatch, entries: list[HistoryEntry] | None, body: str
) -> None:
    """Turns red if either state's markup or words change."""
    monkeypatch.setattr(account_history, "history_for", lambda _id: entries)
    html = main._history_html(uuid4())
    assert html.endswith(body + "</div></details>")


def test_the_signed_in_lede_is_exact() -> None:
    """Turns red if a word of the signed-in lede changes."""
    assert main._signed_in_lede() == (
        "Your last 5 questions stay in your history for 30 days; answers are not kept, "
        "so export one to keep it. Cost is shown before each run; nothing executes without "
        "your confirmation."
    )


def test_times_are_stored_in_utc() -> None:
    """Turns red if a naive time is not taken as UTC, or an aware one is not
    converted to UTC."""
    naive = datetime(2026, 9, 26, 12, 0)
    assert _to_utc(naive) == datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
    assert _to_utc(naive).tzinfo is UTC
    ist = datetime(2026, 9, 26, 17, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert _to_utc(ist) == datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
    assert _to_utc(ist).tzinfo is UTC
