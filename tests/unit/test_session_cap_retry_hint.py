"""The advertised wait, at the edges where it must say nothing at all.

``seconds_until_a_session_mint_frees`` is read only when a mint is REFUSED,
and its ``None`` return means "not knowable". The route layer must translate
that into silence about timing, never into a guess: a fabricated
``Retry-After`` teaches a client to come back at a time nothing computed.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from product_app.feedback_store import FeedbackStore
from product_app.main import _describe_retry_wait, _retry_after_header


def _store() -> FeedbackStore:
    return FeedbackStore(":memory:")


def test_no_mints_at_all_is_not_knowable() -> None:
    """RED IF an empty window reports a wait. There is nothing to age out, so
    there is no time to name."""
    store = _store()
    try:
        assert store.seconds_until_a_session_mint_frees(ip="1.2.3.4", cap=2) is None
    finally:
        store.close()


def test_fewer_mints_than_the_cap_is_not_knowable() -> None:
    """RED IF a caller under the cap is told to wait. Positive partner below
    proves the same store DOES answer once the cap is reached."""
    store = _store()
    try:
        store.record(
            recorder="session",
            event_type="session_minted",
            account_id=uuid4(),
            query_run_id=None,
            recorded_at=datetime.now(UTC) - timedelta(hours=5),
            payload={"ip": "1.2.3.4"},
        )
        assert store.seconds_until_a_session_mint_frees(ip="1.2.3.4", cap=2) is None

        store.record(
            recorder="session",
            event_type="session_minted",
            account_id=uuid4(),
            query_run_id=None,
            recorded_at=datetime.now(UTC) - timedelta(hours=5),
            payload={"ip": "1.2.3.4"},
        )
        answer = store.seconds_until_a_session_mint_frees(ip="1.2.3.4", cap=2)
        assert answer is not None
        assert 18 * 3600 < answer <= 19 * 3600
    finally:
        store.close()


def test_a_broken_read_is_not_knowable_rather_than_zero() -> None:
    """RED IF a storage fault is reported as "retry now".

    Rounding an unreadable ledger down to zero would invite a client to
    hammer an endpoint that is still refusing it.
    """
    store = _store()
    try:
        store._conn.close()
        assert store.seconds_until_a_session_mint_frees(ip="1.2.3.4", cap=2) is None
    finally:
        with __import__("contextlib").suppress(sqlite3.Error):
            store.close()


def test_more_mints_than_the_cap_waits_for_the_deciding_row() -> None:
    """RED IF the query takes the OLDEST row instead of the deciding one.

    With 3 mints against a cap of 2, TWO must age out before another is
    allowed, so the answer is governed by the SECOND oldest. Taking the oldest
    would under-report the wait — and the page would then tell a visitor to
    come back while the cap is still refusing them.
    """
    store = _store()
    try:
        for hours in (23, 20, 1):
            store.record(
                recorder="session",
                event_type="session_minted",
                account_id=uuid4(),
                query_run_id=None,
                recorded_at=datetime.now(UTC) - timedelta(hours=hours),
                payload={"ip": "1.2.3.4"},
            )
        answer = store.seconds_until_a_session_mint_frees(ip="1.2.3.4", cap=2)
        assert answer is not None
        # Governed by the 20h-old row -> ~4h. The 23h-old row would give ~1h.
        assert 3.5 * 3600 < answer < 4.5 * 3600
    finally:
        store.close()


def test_an_unknown_wait_produces_no_header_and_no_claimed_time() -> None:
    """RED IF ``None`` starts producing a header or a numbered sentence."""
    assert _retry_after_header(None) == {}
    sentence = _describe_retry_wait(None)
    # It may still explain the MECHANISM ("the 24-hour window"); what it must
    # not do is name a wait. An earlier draft asserted "no digits at all",
    # which failed on the honest mechanism sentence — the claim to forbid is
    # "come back in N", not the number 24.
    assert "window" in sentence
    assert re.search(r"in about \d+ hour", sentence) is None


def test_a_known_wait_produces_both() -> None:
    """POSITIVE PARTNER (rule 7) for the check above: without this, "no header
    and no digits" is trivially satisfiable by a function that never emits
    either."""
    assert _retry_after_header(7200) == {"Retry-After": "7200"}
    assert "2 hours" in _describe_retry_wait(7200)
    assert "1 hour" in _describe_retry_wait(60)


def test_the_enforcement_window_is_driven_by_the_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED IF any mint-window call site goes back to a hardcoded 24 hours.

    A literal pin on ``SESSION_MINT_WINDOW`` is not enough on its own, and
    adversarial review proved it: when ``try_record_session_mint`` still wrote
    ``timedelta(hours=24)`` by hand, mutating THAT line moved the enforcement
    window while the pin stayed green — the pin guarded a constant nothing
    enforced. This asserts the BEHAVIOUR instead: shrink the window and the cap
    must forget a mint that is now outside it.

    The positive partner is the first block: with the real window, the same two
    mints DO still fill the cap, so "the third mint was allowed" is not passing
    over a cap that never refused anything.
    """
    store = _store()
    try:
        for _ in range(2):
            store.record(
                recorder="session",
                event_type="session_minted",
                account_id=uuid4(),
                query_run_id=None,
                recorded_at=datetime.now(UTC) - timedelta(hours=2),
                payload={"ip": "1.2.3.4"},
            )
        assert store.try_record_session_mint(ip="1.2.3.4", account_id=uuid4(), cap=2) is False
        assert store.session_mint_count_for_ip("1.2.3.4") == 2

        monkeypatch.setattr(FeedbackStore, "SESSION_MINT_WINDOW", timedelta(hours=1))

        assert store.session_mint_count_for_ip("1.2.3.4") == 0
        assert store.try_record_session_mint(ip="1.2.3.4", account_id=uuid4(), cap=2) is True
    finally:
        store.close()


def test_the_header_is_rounded_to_the_hour_and_never_early() -> None:
    """RED IF ``Retry-After`` goes back to second precision.

    The value is derived from a mint that may belong to a STRANGER behind the
    same NAT. At second precision adversarial review recovered the exact moment
    that stranger last started a session, to 0.0s. An hour of resolution keeps
    the RFC-9110 benefit and drops the oracle.

    It also has to agree with the page, which renders whole hours: a client
    honouring a finer header would return while the page it was just shown
    still said to wait. Both are asserted here, against literals on both sides
    (rule 7a) rather than against the rounding expression.
    """
    for seconds, expected_header, expected_words in [
        (1, 3600, "about 1 hour"),
        (3599, 3600, "about 1 hour"),
        (3600, 3600, "about 1 hour"),
        (3601, 7200, "about 2 hours"),
        (82800, 82800, "about 23 hours"),
    ]:
        header = int(_retry_after_header(seconds)["Retry-After"])
        assert header == expected_header, f"{seconds}s -> {header}"
        assert expected_words in _describe_retry_wait(seconds)
        assert header >= seconds, "rounding must never send a client back early"
