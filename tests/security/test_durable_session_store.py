"""What a durable session store must not become.

Sessions are the only credential this app has — there is no login, so the
cookie IS the identity (``test_session_cookie_prefix_binding`` says so
outright). Moving them from a process dict onto a mounted volume therefore
creates security properties that did not exist before, and this suite pins
the ones ADR-0073 committed to.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from product_app import auth, session_store
from product_app.auth import SESSION_TTL
from product_app.session_store import SessionStore, StoredSession, _digest

ACCOUNT = UUID("11111111-2222-3333-4444-555555555555")


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SessionStore]:
    live = SessionStore(str(tmp_path / "sessions.sqlite3"))
    session_store.configure(live)
    try:
        yield live
    finally:
        live.close()
        session_store.configure(None)


def _session(session_id: str, *, last_used: datetime | None = None) -> StoredSession:
    now = datetime.now(UTC)
    return StoredSession(
        session_id=session_id,
        account_id=ACCOUNT,
        # Deliberately NOT derived from ``session_id``: the CSRF token is
        # stored in CLEAR, so a token that embedded the session id would put
        # the id on disk by the back door — which is exactly what an earlier
        # draft of this helper did, and the test below caught it.
        csrf_token="an-independent-csrf-token",
        created_at=now,
        last_used_at=last_used or now,
    )


def test_the_session_id_is_never_written_to_disk(tmp_path: Path) -> None:
    """RED IF the store starts persisting the raw id: read access to the Fly
    volume would then be equivalent to holding every live visitor's cookie.

    The digest assertion is the positive partner (rule 7) — without it, "the
    token is absent" is trivially true of a database with no rows in it.
    """
    path = tmp_path / "sessions.sqlite3"
    live = SessionStore(str(path))
    try:
        live.save(_session("Sup3r-Secret-Cookie-Value"))
    finally:
        live.close()

    raw = path.read_bytes()
    assert b"Sup3r-Secret-Cookie-Value" not in raw
    assert _digest("Sup3r-Secret-Cookie-Value").encode() in raw


def test_the_csrf_token_cannot_smuggle_the_session_id_onto_disk() -> None:
    """PARTNER to the check above, on the real minting code rather than a
    fixture. RED IF the two secrets ever become derived from one another.

    The CSRF token is stored in clear — defensibly, because it is useless
    without the cookie it is bound to. That argument only holds while the
    token reveals nothing ABOUT the cookie.
    """
    repository = auth.SessionRepository()
    session = repository.create(account_id=ACCOUNT)

    assert session.csrf_token != session.session_id
    assert session.session_id not in session.csrf_token
    assert session.csrf_token not in session.session_id


def test_an_expired_row_never_resolves_even_if_the_purge_never_ran(
    store: SessionStore,
) -> None:
    """RED IF expiry is enforced only by the purge.

    A durable row outlives the process that would have purged it — an
    unwritable volume, or a machine that stopped before the next 60s tick.
    Expiry must therefore be a condition of the READ.
    """
    fresh, stale = "fresh-id", "stale-id"
    store.save(_session(fresh))
    store.save(_session(stale, last_used=datetime.now(UTC) - SESSION_TTL - timedelta(minutes=1)))
    horizon = datetime.now(UTC) - SESSION_TTL

    assert store.count() == 2, "positive partner: both rows really are on disk"
    assert store.fetch(fresh, not_used_before=horizon) is not None
    assert store.fetch(stale, not_used_before=horizon) is None


def test_a_presented_session_id_is_never_adopted(store: SessionStore) -> None:
    """RED IF a lookup ever upserts the id it was handed.

    Session fixation: an attacker who can plant a cookie must not be able to
    make the server bless the value they chose. Today no code path writes a
    row for a caller-supplied id — this pins that, because a durable store is
    exactly where "upsert on read" starts to look natural.
    """
    repository = auth.SessionRepository()

    assert repository.get("attacker-chosen-id") is None
    assert store.count() == 0

    minted = repository.create(account_id=ACCOUNT)
    assert store.count() == 1, "positive partner: the store does record real mints"
    assert minted.session_id != "attacker-chosen-id"


def test_a_corrupt_row_yields_no_session_rather_than_a_fabricated_one(
    store: SessionStore,
) -> None:
    """RED IF an unreadable row is allowed to become a ``SessionContext``.

    A NULL or non-UUID account id must fail CLOSED — the caller then mints a
    fresh session. Failing open would hand out an identity assembled from a
    row nobody can vouch for.
    """
    store.save(_session("good-id"))
    connection = sqlite3.connect(store._db_path)
    try:
        connection.execute(
            "INSERT INTO sessions "
            "(session_digest, account_id, csrf_token, created_at, last_used_at) "
            "VALUES (?, 'not-a-uuid', 'c', ?, ?)",
            (
                _digest("corrupt-id"),
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    horizon = datetime.now(UTC) - SESSION_TTL
    assert store.fetch("corrupt-id", not_used_before=horizon) is None
    assert store.fetch("good-id", not_used_before=horizon) is not None


def test_clear_empties_the_durable_half_too(store: SessionStore) -> None:
    """RED IF ``clear()`` only empties the dict.

    ``tests/conftest.py`` calls this before and after EVERY test. A clear that
    left rows behind would let one test's session resolve inside the next, and
    the failure would surface somewhere unrelated.
    """
    repository = auth.SessionRepository()
    session = repository.create(account_id=ACCOUNT)
    assert store.count() == 1, "positive partner: there was something to clear"

    repository.clear()

    assert store.count() == 0
    assert repository.get(session.session_id) is None


def test_the_gc_purge_reports_what_it_deleted(store: SessionStore) -> None:
    """RED IF the purge stops touching the durable half, or stops counting.

    The 60-second daemon is the ONLY caller that deletes durable rows, and it
    runs inside a broad ``except``. A purge that silently did nothing would be
    indistinguishable from one that worked.
    """
    repository = auth.SessionRepository()
    live = repository.create(account_id=ACCOUNT)
    store.save(_session("old", last_used=datetime.now(UTC) - SESSION_TTL - timedelta(hours=1)))
    assert store.count() == 2

    _, durable = repository.purge_expired()

    assert durable == 1
    assert store.count() == 1
    assert repository.get(live.session_id) is not None


@pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root ignores the read-only bit, so this test would pass vacuously",
)
def test_an_unwritable_volume_degrades_instead_of_locking_everyone_out(
    tmp_path: Path,
) -> None:
    """RED IF an unwritable volume can stop a session being issued.

    Measured shapes (CPython 3.12.13 / SQLite 3.50.4): an EXISTING file whose
    table is already present opens fine on a read-only volume and fails only
    on write, which is the production shape once this store has ever run. The
    required behaviour is the behaviour this app had before the store
    existed: sessions work, and they do not survive a restart.
    """
    path = tmp_path / "sessions.sqlite3"
    SessionStore(str(path)).close()
    os.chmod(path, stat.S_IRUSR)
    os.chmod(tmp_path, stat.S_IRUSR | stat.S_IXUSR)
    try:
        live = SessionStore(str(path))  # must NOT raise
        session_store.configure(live)
        repository = auth.SessionRepository()
        session = repository.create(account_id=ACCOUNT)

        assert repository.get(session.session_id) is not None, "sessions still work"
        assert live.save(_session("anything")) is False, (
            "positive partner: the volume really is unwritable, so the "
            "assertion above is not passing over a healthy store"
        )
        assert auth.SessionRepository().get(session.session_id) is None, (
            "nothing was persisted, so a restart loses it — the documented "
            "degradation, not a silent success"
        )
    finally:
        os.chmod(tmp_path, stat.S_IRWXU)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        session_store.configure(None)


def test_a_touch_does_not_write_through_on_every_request(store: SessionStore) -> None:
    """CARDINALITY (rule 6b). RED IF the throttle is removed: ``require_session``
    touches on EVERY authenticated request, and ADR-0002 pinned this app's
    single-writer SQLite design against ~16 writes per RUN, not one per
    REQUEST.

    The positive partner is the second half: a touch far enough past the
    interval MUST write, or the throttle would be indistinguishable from
    never persisting at all.
    """
    repository = auth.SessionRepository()
    session = repository.create(account_id=ACCOUNT)
    stamped = session.persisted_last_used_at

    for _ in range(20):
        repository.touch(session.session_id)
    assert session.persisted_last_used_at == stamped, "20 touches, no extra write"

    session.persisted_last_used_at = datetime.now(UTC) - timedelta(hours=1)
    repository.touch(session.session_id)
    assert session.persisted_last_used_at != stamped


# ---------------------------------------------------------------------------
# Degradation paths. Every one of these is a branch whose whole job is to fail
# quietly, which is exactly the kind that ships untested and then turns out to
# raise. They are asserted on OUTCOME (the app still works), never on a log
# line.
# ---------------------------------------------------------------------------


def test_a_closed_store_answers_everything_without_raising(tmp_path: Path) -> None:
    """RED IF any method raises after ``close()``.

    ``atexit`` closes every open store, and the 60s GC daemon keeps running
    through interpreter shutdown. A method that raised here would surface as a
    noisy, unactionable traceback at every process exit.
    """
    live = SessionStore(str(tmp_path / "sessions.sqlite3"))
    live.save(_session("before-close"))
    assert live.count() == 1, "positive partner: the store worked while open"
    live.close()

    assert live.save(_session("after-close")) is False
    assert live.delete("after-close") is False
    assert live.delete_all() is False
    assert live.fetch("before-close", not_used_before=datetime.now(UTC)) is None
    assert live.purge_expired(cutoff=datetime.now(UTC)) == 0
    assert live.count() == 0
    live.close()  # idempotent


def test_a_broken_connection_degrades_instead_of_raising(store: SessionStore) -> None:
    """RED IF a mid-flight SQLite fault escapes to the caller.

    Distinct from the closed-store case above: here the store believes it is
    open, so the ``sqlite3.Error`` handlers are what stand between a disk fault
    and a 500 on every authenticated request.
    """
    store.save(_session("live-id"))
    assert store.count() == 1, "positive partner: the store was healthy first"
    store._conn.close()  # the handle dies underneath the store

    assert store.save(_session("another")) is False
    assert store.delete("live-id") is False
    assert store.delete_all() is False
    assert store.fetch("live-id", not_used_before=datetime.now(UTC)) is None
    assert store.purge_expired(cutoff=datetime.now(UTC)) == 0
    assert store.count() == 0


def test_the_repository_still_works_with_a_broken_store(store: SessionStore) -> None:
    """RED IF a storage fault can stop a session being ISSUED.

    This is the one-way door ADR-0073 turns on: sessions are the only
    credential, so the failure must land on "does not survive a restart",
    never on "nobody can start one".
    """
    repository = auth.SessionRepository()
    store._conn.close()

    session = repository.create(account_id=ACCOUNT)
    assert repository.get(session.session_id) is not None
    assert repository.touch(session.session_id) is not None
    assert repository.rotate_csrf(session.session_id) is not None
    repository.revoke(session.session_id)
    repository.clear()
    assert repository.purge_expired() == (0, 0)


def test_revoke_removes_the_durable_row(store: SessionStore) -> None:
    """RED IF ``revoke`` forgets the durable half.

    It has no caller in ``src/`` today. That is precisely why it needs a test:
    a revoke that dropped only the cached copy would let the revoked cookie
    resolve again after the next restart — a revocation that silently expires
    instead of revoking.
    """
    repository = auth.SessionRepository()
    session = repository.create(account_id=ACCOUNT)
    assert store.count() == 1, "positive partner: there was a row to revoke"

    repository.revoke(session.session_id)

    assert store.count() == 0
    assert auth.SessionRepository().get(session.session_id) is None


def test_from_env_creates_the_parent_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RED IF ``from_env`` stops creating the directory: the first boot on a
    fresh volume would fail to open and silently fall back to non-durable
    sessions — the bug, shipped behind the fix."""
    target = tmp_path / "nested" / "deeper" / "sessions.sqlite3"
    assert not target.parent.exists(), "positive partner: the directory is genuinely missing"
    monkeypatch.setenv("SESSION_DB_PATH", str(target))

    live = SessionStore.from_env()
    try:
        assert target.parent.is_dir()
        assert live.save(_session("works")) is True
    finally:
        live.close()


def test_the_gc_daemon_survives_a_purge_that_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED IF a raising purge kills the session-gc thread.

    The loop runs forever in a daemon thread; one escaped exception would end
    it permanently and expired sessions would then accumulate for the life of
    the process, with nothing to notice.
    """
    calls: list[str] = []

    class _Exploding:
        def purge_expired(self) -> tuple[int, int]:
            calls.append("tick")
            raise RuntimeError("the volume went away")

    monkeypatch.setattr(auth, "session_repository", _Exploding())

    auth._gc_tick()  # must not raise
    auth._gc_tick()

    assert calls == ["tick", "tick"], (
        "positive partner: the tick really did reach the purge both times, so "
        "'it did not raise' is not passing over a tick that never ran"
    )


def test_the_gc_daemon_actually_ticks(store: SessionStore) -> None:
    """POSITIVE PARTNER for the test above (rule 7). RED IF ``_gc_tick`` stops
    being wired to a real purge — without this, "nothing escaped" is
    satisfiable by a tick that does nothing at all."""
    repository = auth.SessionRepository()
    auth.session_repository = repository
    try:
        store.save(
            _session("ancient", last_used=datetime.now(UTC) - SESSION_TTL - timedelta(days=1))
        )
        assert store.count() == 1

        auth._gc_tick()

        assert store.count() == 0
    finally:
        auth.session_repository = repository


def test_touching_or_rotating_an_unknown_session_returns_nothing(store: SessionStore) -> None:
    """RED IF ``touch``/``rotate_csrf`` start inventing a session for an id
    they cannot resolve.

    Both now resolve through ``get``, which reads durable rows. An unknown id
    must stay unknown — inventing one here would be the fixation hole in
    another doorway.
    """
    repository = auth.SessionRepository()

    assert repository.touch("no-such-session") is None
    assert repository.rotate_csrf("no-such-session") is None
    assert store.count() == 0

    real = repository.create(account_id=ACCOUNT)
    assert repository.touch(real.session_id) is not None, "positive partner"
    assert repository.rotate_csrf(real.session_id) is not None


def test_the_repository_works_with_no_durable_store_at_all() -> None:
    """RED IF an unconfigured sink breaks the repository.

    This is the shape every release before ADR-0073 shipped, and the one the
    boot fallback lands on. It must behave exactly as it always did.
    """
    session_store.configure(None)
    repository = auth.SessionRepository()

    session = repository.create(account_id=ACCOUNT)
    assert repository.get(session.session_id) is not None
    assert repository.get("unknown") is None
    assert repository.purge_expired() == (0, 0)
    repository.revoke(session.session_id)
    repository.clear()
