"""W7, 2a — the exact history markup and signed-in lede (ADR-0135; the list
builder is shared with ``GET /v1/account/history`` since ADR-0142).

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


#: The rows' markup, pinned with a literal (W33 slice D, ADR-0142: one builder
#: for the page and for ``GET /v1/account/history``).
_LIST = (
    '<ol class="history-list" id="account-history-list">'
    '<li class="history-item"><span class="history-question">Why &lt;this&gt;?</span>'
    '<span class="history-meta">2026-09-26 12:00 UTC · timed out · 4 models · '
    "3 of 4 opening positions carried into the final answer · estimated $0.0412</span></li>"
    '<li class="history-item"><span class="history-question">Quick one</span>'
    '<span class="history-meta">2026-09-25 09:05 UTC · completed · quick answer · '
    "estimated $0.0100</span></li>"
    "</ol>"
)
_EMPTY = '<p class="history-empty" id="account-history-empty">No questions yet.</p>'
_UNAVAILABLE = (
    '<p class="history-empty" id="account-history-unavailable">'
    "Your history could not be loaded just now.</p>"
)
_PANEL_OPEN = (
    '<details class="account-history" id="account-history">'
    '<summary class="topbar-howitworks">History</summary>'
    '<div class="account-history-panel" tabindex="0" role="region" '
    'aria-label="Your question history">'
    '<p class="history-note">Your last 5 questions, kept 30 days. Answers are not kept.</p>'
)


def test_the_history_markup_is_exact() -> None:
    """RED-IF: any tag, class, id, word, separator or the UTC time the shared
    list builder ``main._history_list_html`` writes changes (ADR-0142: the
    page and the route both use it)."""
    assert main._history_list_html(_entries()) == _LIST


@pytest.mark.parametrize(
    ("entries", "body"),
    [([], _EMPTY), (None, _UNAVAILABLE)],
    ids=["empty", "unavailable"],
)
def test_the_empty_and_unavailable_states_are_exact(
    entries: list[HistoryEntry] | None, body: str
) -> None:
    """RED-IF: either state's markup or words change in the shared builder."""
    assert main._history_list_html(entries) == body


@pytest.mark.parametrize(
    ("entries", "body"),
    [(_entries(), _LIST), ([], _EMPTY), (None, _UNAVAILABLE)],
    ids=["rows", "empty", "unavailable"],
)
def test_the_page_panel_wraps_exactly_the_shared_list(
    monkeypatch: pytest.MonkeyPatch, entries: list[HistoryEntry] | None, body: str
) -> None:
    """Row 14 (ADR-0142). RED-IF: the page's History panel stops being the
    note, then EXACTLY the shared builder's list, then the account controls:
    a second renderer, or a changed wrapper, turns this red."""
    monkeypatch.setattr(account_history, "history_for", lambda _id: entries)
    assert main._history_html(uuid4()) == (
        _PANEL_OPEN + body + main._account_delete_html() + "</div></details>"
    )


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


def test_the_delete_account_steps_are_exact() -> None:
    """W7 (ADR-0136). Pinned with a literal: turns red if a step, a word, an
    id or the hidden state of a step changes."""
    assert main._account_delete_html() == (
        '<div class="account-delete" id="account-delete">'
        '<p class="history-note account-delete-heading">Your account</p>'
        '<button type="button" id="sign-out-everywhere" class="account-delete-link">'
        "Sign out everywhere</button>"
        '<button type="button" id="account-delete-start" class="account-delete-link">'
        "Delete my account…</button>"
        '<div id="account-delete-reminder" hidden>'
        "<p>Deleting your account removes your question history and signs you out on "
        "every device. It cannot be undone.</p>"
        '<label for="account-delete-email">Type the email address you signed in with</label>'
        '<input id="account-delete-email" type="email" autocomplete="off" spellcheck="false" '
        'aria-describedby="account-delete-error">'
        '<div class="account-delete-actions">'
        '<button type="button" id="account-delete-continue">Continue</button>'
        '<button type="button" id="account-delete-cancel">Keep my account</button>'
        "</div></div>"
        '<div id="account-delete-final" hidden>'
        "<p><strong>Last check:</strong> this permanently deletes your account. "
        "There is no undo.</p>"
        '<div class="account-delete-actions">'
        '<button type="button" id="account-delete-confirm" class="account-delete-danger">'
        "Delete permanently</button>"
        '<button type="button" id="account-delete-back">Keep my account</button>'
        "</div></div>"
        '<p id="account-delete-error" class="account-delete-error" role="alert" hidden></p>'
        "</div>"
    )
