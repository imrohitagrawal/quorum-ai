"""W87-1 (ADR-0174): the durable half of the maximum session age.

A durable row outlives the process that would have ended its session, so the
maximum age must hold on the READ and on the PURGE, not only in the process
cache (FM-1, FM-2), and the reason a session ended must come from what is on
disk, never from a guess (FM-25). Literal boundaries throughout (rule 7a).

Rows are written straight to a temporary store and read back through
``auth.session_repository`` with an empty process cache, which is exactly what
a restart looks like.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from tests.session_clock import Clock, age, freeze

from product_app import auth, session_store
from product_app.session_store import SessionStore, StoredSession

US = timedelta(microseconds=1)
H12 = timedelta(hours=12)
H24 = timedelta(hours=24)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SessionStore]:
    live = SessionStore(str(tmp_path / "sessions.sqlite3"))
    session_store.configure(live)
    try:
        yield live
    finally:
        auth.session_repository.clear()
        live.close()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    return freeze(monkeypatch)


def _row(
    store: SessionStore,
    session_id: str,
    *,
    account_id: UUID,
    created_at: datetime,
    last_used_at: datetime,
) -> None:
    assert store.save(
        StoredSession(
            session_id=session_id,
            account_id=account_id,
            csrf_token="an-independent-csrf-token",
            created_at=created_at,
            last_used_at=last_used_at,
        )
    )


def _signed_in_account(store: SessionStore, sub: str = "w87-sub-1") -> UUID:
    account = store.upsert_google_account(
        google_sub=sub, email=f"{sub}@example.com", now=datetime.now(UTC)
    )
    assert account is not None
    assert store.is_anonymous(account) is False, "positive partner: a real account row"
    return account


def _restarted() -> None:
    auth.session_repository._sessions.clear()


# -- the read and the purge (FM-1, FM-2) ---------------------------------------


def test_the_read_itself_refuses_a_row_older_than_24_hours(
    store: SessionStore, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Red when: the durable read has no ``created_at`` condition, or uses
    ``>`` (refusing the row at exactly 24 h), or takes its boundary from a
    clock other than the session code's (the two halves would then disagree at
    the boundary instant). The in-process check is switched off here, so only
    the read can refuse."""
    anonymous = uuid4()
    _row(store, "at-24h", account_id=anonymous, created_at=clock.at - H24, last_used_at=clock.at)
    _row(
        store,
        "past-24h",
        account_id=anonymous,
        created_at=clock.at - H24 - US,
        last_used_at=clock.at,
    )
    assert store.count() == 2, "positive partner: both rows are on disk"
    monkeypatch.setattr(auth._Session, "is_expired", lambda self, *, now: False)
    _restarted()
    assert auth.session_repository.get("at-24h") is not None
    assert auth.session_repository.get("past-24h") is None


def test_the_purge_deletes_exactly_the_rows_the_read_refuses(
    store: SessionStore, clock: Clock
) -> None:
    """Red when: the purge ignores ``created_at`` (deletes nothing here), or
    uses ``<=`` (also deletes the row at exactly 24 h). Cardinality: exactly
    one row deleted, exactly one left."""
    anonymous = uuid4()
    _row(store, "at-24h", account_id=anonymous, created_at=clock.at - H24, last_used_at=clock.at)
    _row(
        store,
        "past-24h",
        account_id=anonymous,
        created_at=clock.at - H24 - US,
        last_used_at=clock.at,
    )
    _restarted()
    cached, durable = auth.session_repository.purge_expired()
    assert (cached, durable) == (0, 1)
    assert store.count() == 1
    assert auth.session_repository.get("at-24h") is not None


def test_a_row_that_started_in_the_future_is_refused_and_purged(store: SessionStore) -> None:
    """FM-2: a ``created_at`` in the future never reaches any maximum age, so
    without a guard the session would never end. Red when: the read accepts
    it, or the purge leaves it. The ordinary row is the partner: it resolves
    and survives the purge."""
    now = datetime.now(UTC)
    anonymous = uuid4()
    _row(store, "ordinary", account_id=anonymous, created_at=now, last_used_at=now)
    _row(
        store,
        "started-in-2999",
        account_id=anonymous,
        created_at=datetime(2999, 1, 1, tzinfo=UTC),
        last_used_at=now,
    )
    assert store.count() == 2
    _restarted()
    assert auth.session_repository.get("started-in-2999") is None
    assert auth.session_repository.get("ordinary") is not None
    _restarted()
    assert auth.session_repository.purge_expired()[1] == 1
    assert store.count() == 1
    assert auth.session_repository.get("ordinary") is not None


# -- restore: which limit a row gets ------------------------------------------


def test_a_restored_signed_in_row_ends_at_12_hours(store: SessionStore, clock: Clock) -> None:
    """FM-1: a restart restores the row (it is inside the 24-hour read), and
    the restore itself must apply the signed-in 12 hours. Red when:
    ``_restore`` does not check the maximum age, or gives a signed-in row the
    anonymous 24 h. The row 1 s younger than 12 h is the partner."""
    account = _signed_in_account(store)
    _row(
        store,
        "young",
        account_id=account,
        created_at=clock.at - H12 + timedelta(seconds=1),
        last_used_at=clock.at,
    )
    _row(
        store,
        "old",
        account_id=account,
        created_at=clock.at - H12 - timedelta(seconds=1),
        last_used_at=clock.at,
    )
    _restarted()
    young = auth.session_repository.get("young")
    assert young is not None
    assert young.max_age == timedelta(hours=12)
    assert auth.session_repository.get("old") is None


def test_a_restored_anonymous_row_keeps_its_24_hours(store: SessionStore, clock: Clock) -> None:
    """Partner of the test above: the 12 hours are for signed-in rows only.
    Red when: every restored row gets 12 h."""
    _row(
        store,
        "anonymous",
        account_id=uuid4(),
        created_at=clock.at - H12 - US,
        last_used_at=clock.at,
    )
    _restarted()
    restored = auth.session_repository.get("anonymous")
    assert restored is not None
    assert restored.max_age == timedelta(hours=24)


def test_a_failed_lookup_gives_the_shorter_12_hours(
    store: SessionStore, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The restore cannot tell whether the row is signed in: it takes the
    closed side, 12 h, as it already does for the idle limit. Red when: a
    failed lookup gives 24 h. Partner: the same row with a working lookup is
    an anonymous row and alive."""
    _row(
        store,
        "unknown-kind",
        account_id=uuid4(),
        created_at=clock.at - H12 - US,
        last_used_at=clock.at,
    )
    _restarted()
    assert auth.session_repository.get("unknown-kind") is not None, "partner: lookup works"
    monkeypatch.setattr(store, "is_anonymous", lambda _account: None)
    _restarted()
    assert auth.session_repository.get("unknown-kind") is None
    _row(
        store,
        "unknown-young",
        account_id=uuid4(),
        created_at=clock.at - timedelta(hours=11),
        last_used_at=clock.at,
    )
    restored = auth.session_repository.get("unknown-young")
    assert restored is not None
    assert restored.max_age == timedelta(hours=12)


# -- why a session ended (FM-25) ---------------------------------------------


def test_the_reason_is_max_age_only_for_a_signed_in_row_past_12_hours(
    store: SessionStore, clock: Clock
) -> None:
    """The positive case. Red when: ``end_reason`` never says
    ``SESSION_MAX_AGE``, or says it for a signed-in row that is not yet past
    12 h (the young row would then read as aged)."""
    account = _signed_in_account(store)
    _row(store, "aged", account_id=account, created_at=clock.at - H12 - US, last_used_at=clock.at)
    _restarted()
    assert auth.session_repository.get("aged") is None
    assert auth.session_repository.end_reason("aged") == "SESSION_MAX_AGE"


@pytest.mark.parametrize(
    "case",
    [
        "anonymous past 24 h",
        "signed in, idle end",
        "signed in past 12 h, row gone",
        "signed in past 12 h, failed lookup",
        "unknown id",
    ],
)
def test_every_other_end_reads_as_the_generic_expiry(
    store: SessionStore, clock: Clock, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """Never guess "12 hours": an anonymous end, an idle end, a row that is
    gone and a lookup that fails all give ``SESSION_EXPIRED``. Red when: any of
    these says ``SESSION_MAX_AGE`` (the page would then tell someone they were
    signed out after 12 hours when they were not). The positive case is the
    test above."""
    account = _signed_in_account(store)
    session_id = "ended"
    if case == "anonymous past 24 h":
        _row(
            store,
            session_id,
            account_id=uuid4(),
            created_at=clock.at - H24 - US,
            last_used_at=clock.at,
        )
    elif case == "signed in, idle end":
        _row(
            store,
            session_id,
            account_id=account,
            created_at=clock.at - timedelta(hours=1),
            last_used_at=clock.at - timedelta(minutes=121),
        )
    elif case == "signed in past 12 h, row gone":
        _row(
            store,
            session_id,
            account_id=account,
            created_at=clock.at - H12 - US,
            last_used_at=clock.at,
        )
        assert store.delete(session_id)
    elif case == "signed in past 12 h, failed lookup":
        _row(
            store,
            session_id,
            account_id=account,
            created_at=clock.at - H12 - US,
            last_used_at=clock.at,
        )
        monkeypatch.setattr(store, "is_anonymous", lambda _account: None)
    _restarted()
    assert auth.session_repository.get(session_id) is None
    assert auth.session_repository.end_reason(session_id) == "SESSION_EXPIRED"


def test_with_no_store_the_reason_is_the_generic_expiry(clock: Clock) -> None:
    """FM-25: with no durable store there is nothing to read the reason from.
    Red when: it guesses ``SESSION_MAX_AGE``. Partner: the same session, aged
    the same way, has ended."""
    session_store.configure(None)
    issued = auth.issue_signed_in_session("no-previous-session", account_id=uuid4())
    cached = auth.session_repository._sessions[issued.session_id]
    cached.created_at = clock.at - H12 - US
    assert auth.session_repository.get(issued.session_id) is None
    assert auth.session_repository.end_reason(issued.session_id) == "SESSION_EXPIRED"


# -- W87-1 round 1: one clock reading per decision, and the freshest facts ----


def _cached_signed_in(store: SessionStore, sub: str = "w87-round-1") -> str:
    account = _signed_in_account(store, sub)
    issued = auth.issue_signed_in_session("no-previous-session", account_id=account)
    assert issued.session_id in auth.session_repository._sessions, "partner: cached"
    return issued.session_id


def _step_after_lookup(monkeypatch: pytest.MonkeyPatch, clock: Clock, by: timedelta) -> None:
    real_get = auth.session_repository.get

    def stepped(session_id: str) -> auth._Session | None:
        found = real_get(session_id)
        clock.advance(by)
        return found

    monkeypatch.setattr(auth.session_repository, "get", stepped)


def test_rotating_the_csrf_token_rechecks_the_12_hours_with_the_time_it_records(
    store: SessionStore, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex, round 1. The lookup sees the session at exactly 12 h; the clock
    steps 1 us before the rotation records its last use. Red when: the
    rotation hands out a new token for a session that has ended (a resumed
    ``/v1/session`` after 12 h). Partner: 1 s younger, the same step gives a
    new token."""
    session_id = _cached_signed_in(store)
    _step_after_lookup(monkeypatch, clock, US)
    age(session_id, H12 - timedelta(seconds=1), now=clock.at)
    before = auth.session_repository._sessions[session_id].csrf_token
    rotated = auth.session_repository.rotate_csrf(session_id)
    assert rotated is not None and rotated.csrf_token != before, "partner: alive, rotated"

    age(session_id, H12, now=clock.at)
    assert auth.session_repository.rotate_csrf(session_id) is None
    assert session_id not in auth.session_repository._sessions


@pytest.mark.parametrize("case", ["signed out everywhere before 12 h", "cutoff unreadable"])
def test_a_revoked_session_is_never_told_12_hours(
    store: SessionStore, clock: Clock, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """Codex + break-it F1, round 1. A signed-in row past 12 h whose account
    ended its sessions after the row started (here a stale row written back
    after the sign-out everywhere), or whose cutoff cannot be read, was not
    ended by its 12 hours. Red when: ``end_reason`` says ``SESSION_MAX_AGE``
    for either. Partner: the same row with no cutoff says ``SESSION_MAX_AGE``
    (``test_the_reason_is_max_age_only_for_a_signed_in_row_past_12_hours``)."""
    account = _signed_in_account(store)
    created = clock.at - H12 - US
    _row(store, "revoked", account_id=account, created_at=created, last_used_at=clock.at)
    if case == "signed out everywhere before 12 h":
        assert store.end_sessions_before(account, created + timedelta(minutes=5)) == "ended"
        assert store.fetch("revoked", not_used_before=datetime(1970, 1, 1, tzinfo=UTC)) is None
        _row(store, "revoked", account_id=account, created_at=created, last_used_at=clock.at)
    else:
        monkeypatch.setattr(store, "sessions_valid_after", lambda _account: (False, None))
    _restarted()
    assert auth.session_repository.get("revoked") is None
    assert auth.session_repository.end_reason("revoked") == "SESSION_EXPIRED"


def test_the_reason_uses_the_last_use_the_process_held_not_the_stale_row(
    store: SessionStore, clock: Clock
) -> None:
    """Break-it F1, round 1. The touch throttle lets the row lag the last use
    by up to 300 s. Here the process last saw the session 118 minutes ago (its
    idle end, 2 minutes from now, is after its 12 hours, which ended 1 us ago)
    while the row says 122 minutes (an idle end 2 minutes ago). The session
    ended by its 12 hours. Red when: the reason is read from the stale row
    alone and says ``SESSION_EXPIRED``. Partner: after a restart, with only the
    row to go on, it is not guessed (``SESSION_EXPIRED``)."""
    session_id = _cached_signed_in(store)
    created = clock.at - H12 - US
    fresh = clock.at - timedelta(minutes=118)
    stale = clock.at - timedelta(minutes=122)
    with auth.session_repository._lock:
        cached = auth.session_repository._sessions[session_id]
        cached.created_at = created
        cached.last_used_at = fresh
        cached.persisted_last_used_at = stale
    with store._lock:
        store._conn.execute(
            "UPDATE sessions SET created_at = ?, last_used_at = ? WHERE session_digest = ?",
            (created.isoformat(), stale.isoformat(), session_store._digest(session_id)),
        )
    assert auth.session_repository.get(session_id) is None
    assert auth.session_repository.end_reason(session_id) == "SESSION_MAX_AGE"

    auth.session_repository.clear()
    other = _cached_signed_in(store, "w87-round-1-restart")
    with store._lock:
        store._conn.execute(
            "UPDATE sessions SET created_at = ?, last_used_at = ? WHERE session_digest = ?",
            (created.isoformat(), stale.isoformat(), session_store._digest(other)),
        )
    _restarted()
    assert auth.session_repository.get(other) is None
    assert auth.session_repository.end_reason(other) == "SESSION_EXPIRED"


@pytest.mark.parametrize("case", ["ended in this process only", "account deleted"])
def test_a_session_this_process_ended_is_never_told_12_hours(
    store: SessionStore, clock: Clock, case: str
) -> None:
    """Falsification M4b, round 2. The process's own marks, with no durable
    cutoff to read: a sign out everywhere it recorded in memory only, or an
    account it deleted. The row is a signed-in row past 12 h, so without the
    marks ``end_reason`` says ``SESSION_MAX_AGE``. Red when: the in-memory
    cutoff or the deleted-account check is removed from ``end_reason`` (it
    would then tell a visitor whose sessions were ended that 12 hours had
    passed). Partner: the same row with no mark says ``SESSION_MAX_AGE``,
    asserted first."""
    account = _signed_in_account(store, f"w87-m4b-{case}")
    created = clock.at - H12 - US
    _row(store, "marked", account_id=account, created_at=created, last_used_at=clock.at)
    _restarted()
    assert auth.session_repository.get("marked") is None
    assert auth.session_repository.end_reason("marked") == "SESSION_MAX_AGE", "partner: unmarked"
    assert store.sessions_valid_after(account) == (True, None), "partner: no durable cutoff"
    try:
        if case == "ended in this process only":
            auth.session_repository.end_sessions_of(account, created + timedelta(minutes=5))
        else:
            auth.session_repository.revoke_account(account)
        assert auth.session_repository.end_reason("marked") == "SESSION_EXPIRED"
    finally:
        auth.session_repository.forget_deleted_accounts()
