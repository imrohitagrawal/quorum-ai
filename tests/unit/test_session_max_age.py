"""W87-1 (ADR-0174): a session ends at a maximum age, whatever its use.

A signed-in session ends 12 hours after the sign-in that made it (CHG-056 c),
an anonymous one 24 hours after its mint. Both boundaries are strict: alive at
exactly the limit, ended one microsecond past it. Every boundary here is a
LITERAL (rule 7a), never the constant under test.

In-process half only; the durable half is
``tests/security/test_session_max_age_durable.py`` and the routes are
``tests/integration/test_session_max_age_routes.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from tests.session_clock import Clock, age, freeze

from product_app import auth, feedback_store
from product_app.feedback_store import configure_for_tests

US = timedelta(microseconds=1)
H12 = timedelta(hours=12)
H24 = timedelta(hours=24)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    return freeze(monkeypatch)


def _cached(session_id: str) -> auth._Session:
    return auth.session_repository._sessions[session_id]


# -- the values ----------------------------------------------------------------


def test_the_maximum_ages_and_the_late_run_window_are_pinned_by_literal() -> None:
    """Red when: either maximum age, or the late-run window, moves, or the two
    new reasons are missing from ``AuthError``. These are the owner's numbers
    (CHG-056 c; CHG-066 b: "less than 12 minutes")."""
    assert timedelta(hours=12) == auth.SIGNED_IN_MAX_AGE
    assert timedelta(hours=24) == auth.ANONYMOUS_MAX_AGE
    assert auth.LATE_RUN_REFUSAL_SECONDS == 720
    assert auth.AuthError("SESSION_MAX_AGE").value == "SESSION_MAX_AGE"
    assert auth.AuthError("SESSION_ENDS_SOON").value == "SESSION_ENDS_SOON"


# -- the boundaries ------------------------------------------------------------


def test_a_signed_in_session_is_alive_at_12_hours_and_ended_one_microsecond_later(
    clock: Clock,
) -> None:
    """Red when: the maximum-age check is missing, uses ``>=`` (ends at
    exactly 12 h), or a signed-in session gets the anonymous 24 h."""
    issued = auth.issue_signed_in_session("no-previous-session", account_id=uuid4())
    session = _cached(issued.session_id)
    assert session.created_at == clock.at, "a signed-in session starts at the sign-in"
    assert session.max_age == timedelta(hours=12)

    session.last_used_at = clock.at + H12  # in use all along: idle is not the reason
    assert session.is_expired(now=clock.at + H12) is False
    assert session.is_expired(now=clock.at + H12 + US) is True

    start = clock.at
    clock.advance(H12)
    session.last_used_at = clock.at
    assert auth.session_repository.get(issued.session_id) is not None, "alive at 12 h"
    clock.at = start + H12 + US
    assert auth.session_repository.get(issued.session_id) is None, "ended at 12 h + 1 us"


def test_an_anonymous_session_is_alive_at_24_hours_and_ended_one_microsecond_later(
    clock: Clock,
) -> None:
    """Red when: the anonymous check is missing, uses ``>=``, or an anonymous
    session gets the signed-in 12 h. The 12 h + 1 us line is the partner that
    shows the two limits differ."""
    issued = auth.issue_session()
    session = _cached(issued.session_id)
    assert session.created_at == clock.at
    assert session.max_age == timedelta(hours=24)

    for alive_at in (H12 + US, H24):
        session.last_used_at = clock.at + alive_at
        assert session.is_expired(now=clock.at + alive_at) is False, alive_at
    session.last_used_at = clock.at + H24 + US
    assert session.is_expired(now=clock.at + H24 + US) is True


def test_idle_still_ends_a_young_session() -> None:
    """Partner (true today): the maximum age is added to the idle limit, it
    does not replace it. Red when: ``is_expired`` stops checking idle time."""
    issued = auth.issue_signed_in_session("no-previous-session", account_id=uuid4())
    session = _cached(issued.session_id)
    used = session.last_used_at
    assert session.is_expired(now=used + timedelta(minutes=120)) is False
    assert session.is_expired(now=used + timedelta(minutes=120) + US) is True


def test_an_anonymous_session_that_signs_in_gets_a_fresh_12_hours(clock: Clock) -> None:
    """The anonymous age is not carried over: the sign-in rotation makes a new
    session that starts now. Red when: the rotation keeps the old
    ``created_at``, or gives the new session the anonymous 24 h."""
    anonymous = auth.issue_session()
    age(anonymous.session_id, timedelta(hours=23), now=clock.at)
    signed = auth.issue_signed_in_session(anonymous.session_id, account_id=uuid4())
    assert auth.session_repository.get(anonymous.session_id) is None
    session = _cached(signed.session_id)
    assert session.created_at == clock.at
    assert session.max_age == timedelta(hours=12)


# -- the mint count (FM-3, FM-4) ---------------------------------------------


def test_a_mint_counts_while_its_session_is_alive_and_both_end_together() -> None:
    """FM-3, with literals: a mint at t0 for a session created at t0. At
    t0 + 24 h the session is alive AND the mint still counts; at t0 + 24 h + 1 us
    the session has ended AND the mint no longer counts. Red when: the session
    check is ``>=`` or missing (alive past the window), or the window changes."""
    t0 = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    account = uuid4()
    with configure_for_tests() as ledger:
        assert ledger.try_record_session_mint(ip="203.0.113.7", account_id=account, cap=2, now=t0)
        session = auth._Session(
            session_id="s",
            account_id=account,
            csrf_token="c",
            created_at=t0,
            last_used_at=t0 + H24,
            max_age=timedelta(hours=24),
        )
        assert session.is_expired(now=t0 + H24) is False
        assert ledger.session_mint_count_for_ip("203.0.113.7", now=t0 + H24) == 1
        assert session.is_expired(now=t0 + H24 + US) is True
        assert ledger.session_mint_count_for_ip("203.0.113.7", now=t0 + H24 + US) == 0


def test_the_mint_is_recorded_no_later_than_the_session_it_counts() -> None:
    """F12, true today: the mint is recorded before the session is made, so a
    session ended by its 24 hours has always aged out of the count. Red when:
    the order is swapped. Cardinality: exactly one mint row."""
    with configure_for_tests() as ledger:
        issued = auth.issue_session(client_ip="203.0.113.8")
        rows = ledger._conn.execute(
            "SELECT recorded_at FROM events WHERE event_type = 'session_minted'"
        ).fetchall()
        assert len(rows) == 1
        minted = datetime.fromisoformat(rows[0]["recorded_at"])
        assert minted <= _cached(issued.session_id).created_at


def test_a_session_ended_by_its_24_hours_frees_its_slot_and_an_idle_end_does_not() -> None:
    """FM-4: the promise is narrow. Positive: two mints in one hour; once the
    first session has ended at its 24 hours, a third mint is allowed. Negative:
    when the first session ended at its 2-hour idle limit instead, the third is
    still refused. Red when: the window or cap moves, or the first session
    does not end at 24 h + 1 us."""
    t0 = datetime(2026, 10, 19, 6, 0, tzinfo=UTC)
    first = auth._Session(
        session_id="first",
        account_id=uuid4(),
        csrf_token="c",
        created_at=t0,
        last_used_at=t0 + H24,
        max_age=timedelta(hours=24),
    )
    with configure_for_tests() as ledger:
        ip = "198.51.100.4"
        assert ledger.try_record_session_mint(ip=ip, account_id=uuid4(), cap=2, now=t0)
        assert ledger.try_record_session_mint(
            ip=ip, account_id=uuid4(), cap=2, now=t0 + timedelta(minutes=30)
        )
        idle_end = t0 + timedelta(hours=2) + US
        assert (
            ledger.try_record_session_mint(ip=ip, account_id=uuid4(), cap=2, now=idle_end) is False
        )
        assert first.is_expired(now=t0 + H24 + US) is True
        assert (
            ledger.try_record_session_mint(ip=ip, account_id=uuid4(), cap=2, now=t0 + H24 + US)
            is True
        )


# -- invite links, the allow-list and sign-in-only sessions (FM-5, FM-6) -----


def test_an_invite_session_ends_at_24_hours_and_its_replacement_counts_once(
    clock: Clock,
) -> None:
    """FM-5: no exemption for invite links. Red when: an invite session lives
    past 24 h, or its replacement is not minted under the link (cardinality:
    exactly one more mint for ``invite:<id>``)."""
    key = "invite:link-w87"
    with configure_for_tests() as ledger:
        issued = auth.issue_session(client_ip=key, mint_cap=12)
        assert ledger.session_mint_count_for_ip(key) == 1
        age(issued.session_id, H24, now=clock.at)
        assert auth.session_repository.get(issued.session_id) is not None, "alive at 24 h"
        age(issued.session_id, H24 + US, now=clock.at)
        assert auth.session_repository.get(issued.session_id) is None
        again = auth.issue_or_resume_session(issued.session_id, client_ip=key, mint_cap=12)
        assert again.session_id != issued.session_id
        assert ledger.session_mint_count_for_ip(key) == 2


def test_an_allow_listed_session_also_ends_at_24_hours(clock: Clock) -> None:
    """FM-5: the allow-list lifts the two per-network limits only. Red when:
    a session with no counted mint lives past 24 h. Cardinality: no mint row,
    so the session ending is not a side effect of a count."""
    with configure_for_tests() as ledger:
        issued = auth.issue_or_resume_session(None, client_ip=None)
        assert (
            ledger._conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_type = 'session_minted'"
            ).fetchone()[0]
            == 0
        )
        age(issued.session_id, H24, now=clock.at)
        assert auth.session_repository.get(issued.session_id) is not None
        age(issued.session_id, H24 + US, now=clock.at)
        assert auth.session_repository.get(issued.session_id) is None


def test_a_sign_in_only_session_is_not_resumed_past_24_hours(clock: Clock) -> None:
    """FM-6: the capped page's session is in memory only and was resumed
    without limit. Red when: ``resume_sign_in_only_session`` resumes it at
    24 h + 1 us. Partner: at exactly 24 h it is resumed."""
    issued = auth.issue_sign_in_only_session()
    age(issued.session_id, H24, now=clock.at)
    assert auth.resume_sign_in_only_session(issued.session_id) is not None
    age(issued.session_id, H24 + US, now=clock.at)
    assert auth.resume_sign_in_only_session(issued.session_id) is None


# -- the reported expiry (FM-7) ----------------------------------------------


def test_every_issue_and_resume_path_reports_the_earlier_end(clock: Clock) -> None:
    """FM-7: ``expires_at`` is the smaller of the idle end and the maximum-age
    end. Red when: any path still reports ``last_used_at + idle_limit`` once
    the maximum age is nearer. The fresh sessions are the partners: there the
    idle end (2 h) is the nearer one, and it is still reported."""
    t = clock.at

    fresh_anonymous = auth.issue_session()
    assert fresh_anonymous.expires_at == t + timedelta(hours=2)

    fresh_signed = auth.issue_signed_in_session("no-previous-session", account_id=uuid4())
    assert fresh_signed.expires_at == t + timedelta(minutes=120)

    age(fresh_signed.session_id, timedelta(hours=11), now=t)
    kept = auth.issue_or_resume_session(fresh_signed.session_id, rotate_csrf=False)
    assert kept.session_id == fresh_signed.session_id
    assert kept.expires_at == t + timedelta(hours=1)
    rotated = auth.issue_or_resume_session(fresh_signed.session_id, rotate_csrf=True)
    assert rotated.session_id == fresh_signed.session_id
    assert rotated.expires_at == t + timedelta(hours=1)

    age(fresh_anonymous.session_id, timedelta(hours=23), now=t)
    resumed = auth.issue_or_resume_session(fresh_anonymous.session_id, rotate_csrf=False)
    assert resumed.session_id == fresh_anonymous.session_id
    assert resumed.expires_at == t + timedelta(hours=1)

    sign_in_only = auth.issue_sign_in_only_session()
    age(sign_in_only.session_id, timedelta(hours=23, minutes=30), now=t)
    again = auth.resume_sign_in_only_session(sign_in_only.session_id)
    assert again is not None
    assert again.expires_at == t + timedelta(minutes=30)


def test_the_feedback_store_used_here_is_the_isolated_one() -> None:
    """Partner for the mint tests above: ``configure_for_tests`` really swaps
    the store, so their counts are this file's alone. Red when: it stops
    swapping (the counts would then include other tests' mints)."""
    outer = feedback_store.get_store()
    with configure_for_tests() as ledger:
        assert feedback_store.get_store() is ledger
        assert ledger is not outer
