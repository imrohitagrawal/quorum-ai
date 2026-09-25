"""Unit checks on the sign-in module's in-memory state (W7, ADR-0130)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from product_app import google_signin
from product_app.google_signin import PendingSignIns


def test_the_pending_table_drops_its_oldest_entry_when_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-IF: begin() stops evicting (the table grows past its bound) or
    evicts the newest entry instead of the oldest."""
    monkeypatch.setattr(google_signin, "MAX_PENDING_SIGN_INS", 3)
    table = PendingSignIns()
    now = datetime.now(UTC)
    for index in range(5):
        table.begin(f"session-{index}", now=now)
    assert len(table) == 3
    assert table.take("session-0", now=now) is None
    assert table.take("session-1", now=now) is None
    assert table.take("session-4", now=now) is not None  # the newest survives


def test_starting_again_replaces_the_previous_state() -> None:
    """One valid state per session. RED-IF: begin() keeps the earlier entry,
    so an older state would still be accepted."""
    table = PendingSignIns()
    now = datetime.now(UTC)
    first = table.begin("s", now=now)
    second = table.begin("s", now=now)
    assert first.state != second.state
    assert len(table) == 1
    taken = table.take("s", now=now)
    assert taken is not None and taken.state == second.state


def test_a_state_and_a_verifier_are_long_random_and_distinct() -> None:
    """RED-IF: the state or verifier gets shorter than RFC 7636's 43-character
    minimum for a verifier, or they share a value."""
    pending = PendingSignIns().begin("s", now=datetime.now(UTC))
    assert len(pending.code_verifier) >= 43
    assert len(pending.state) >= 43
    assert pending.state != pending.code_verifier


def test_the_code_challenge_is_rfc_7636_s256() -> None:
    """RFC 7636 appendix B's own example. RED-IF: the challenge is the plain
    verifier, padded, or not base64url."""
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert google_signin.code_challenge_for(verifier) == (
        "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )


def test_an_expired_entry_is_purged_when_another_session_starts() -> None:
    """RED-IF: begin() stops purging expired entries (the table would keep
    every abandoned sign-in until the size bound evicts it)."""
    from datetime import timedelta

    table = PendingSignIns()
    started = datetime.now(UTC)
    table.begin("abandoned", now=started)
    table.begin("fresh", now=started + timedelta(minutes=10, seconds=1))
    assert len(table) == 1
    assert table.take("fresh", now=started + timedelta(minutes=10, seconds=2)) is not None
