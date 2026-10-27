"""W87-3 follow-up (CHG-088, W114 pull request A), review round 2: the fixes.

Each test names the break-it finding it answers and has its "Red when" line.
The fixtures and helpers are the main file's
(``test_unchecked_session_keeps_its_cookie``), so the states are made the same
way: on the REAL store, with the GC tick's readiness refresh stood down.

Every wait and join is bounded (``pytest-timeout`` is not installed).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from tests.security.test_unchecked_session_keeps_its_cookie import (  # noqa: F401
    NOT_READ,
    _daemon_never_refreshes,
    _no_daily_cap,
)
from tests.session_clock import age, freeze
from tests.unchecked_harness import ScriptedCutoff, account, anonymous_session

from product_app import auth, session_store
from product_app.session_store import SessionStore


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "sessions.sqlite3"


@pytest.fixture
def live(db: Path) -> Iterator[SessionStore]:
    """The main file's store fixture, repeated so it is not shadowed."""
    store = SessionStore(str(db))
    session_store.configure(store)
    try:
        yield store
    finally:
        auth.session_repository._sessions.clear()
        auth.session_repository._valid_after.clear()
        store.close()


def test_r2_f1_the_sign_in_rotation_lets_lookups_in_before_it_creates(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2-F1 (break-it round 2). The rotation holds the repository lock for
    its check and its revoke only, as one write, so another request's lookup
    never waits for the new session's write as well (each write can wait the
    5 s busy timeout: 10.07 s measured with both under one hold, 4.9 s on
    ``main``). The new session's creation is held open here; a lookup of
    another session must answer meanwhile. Partners: the rotation then
    finishes with a new signed-in session, and the lookup answered the cached
    session.
    Red when: the create is moved back inside the rotation's lock hold."""
    account_id, _email = account(db, "r2f1")
    previous = anonymous_session()
    other = anonymous_session()
    repository = auth.session_repository
    in_create = threading.Event()
    release = threading.Event()
    real_create = repository.create

    def held_create(**kwargs: Any) -> auth._Session:
        in_create.set()
        release.wait(10)
        return real_create(**kwargs)

    monkeypatch.setattr(repository, "create", held_create)
    rotated: list[auth.SessionIssueResponse] = []
    rotation = threading.Thread(
        target=lambda: rotated.append(
            auth.issue_signed_in_session(previous.session_id, account_id=account_id)
        )
    )
    rotation.start()
    try:
        assert in_create.wait(5), "partner: the rotation reached its create"
        looked: list[auth._Session | None] = []
        lookup = threading.Thread(target=lambda: looked.append(repository.get(other.session_id)))
        lookup.start()
        lookup.join(2.0)
        answered_while_creating = not lookup.is_alive()
    finally:
        release.set()
        rotation.join(10)
    lookup.join(10)
    assert answered_while_creating, "the lookup waited for the rotation's create"
    assert looked == [other]
    assert len(rotated) == 1 and rotated[0].account_id == account_id
    assert previous.session_id not in repository._sessions


def _revoke_during_the_kind_read(
    store: SessionStore, monkeypatch: pytest.MonkeyPatch, who: UUID, session_id: str
) -> list[int]:
    """The restore's kind read of ``who`` first revokes ``session_id`` (a
    sign-out landing after the row was read), by both of the store's two ways
    of asking. Returns the list the reads are counted in."""
    calls: list[int] = []
    real_is, real_has = store.is_anonymous, store.has_no_account_row

    def asked(real: Any) -> Any:
        def answer(target: UUID) -> bool | None:
            if target == who:
                calls.append(1)
                auth.session_repository.revoke(session_id)
            return real(target)  # type: ignore[no-any-return]

        return answer

    monkeypatch.setattr(store, "is_anonymous", asked(real_is))
    monkeypatch.setattr(store, "has_no_account_row", asked(real_has))
    return calls


@pytest.mark.parametrize("revoked", [True, False])
def test_r2_f3_a_restore_does_not_put_back_a_session_revoked_while_not_held(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch, revoked: bool
) -> None:
    """R2-F3 (break-it round 2; SC-104, ADR-0176 A3). An uncached session's
    restore has read its row when a sign-out revokes it; the cache does not
    hold it, so the revoke records it in the signed-out list only. The
    restore must not cache it again, and the next lookup finds nothing.
    Partner (``revoked=False``): the same restore with no sign-out serves the
    session.
    Red when: the restore's last check stops asking the signed-out list."""
    session = anonymous_session()
    sid = session.session_id
    auth.session_repository._sessions.pop(sid)
    if revoked:
        calls = _revoke_during_the_kind_read(live, monkeypatch, session.account_id, sid)
    found = auth.session_repository.lookup(sid)
    if revoked:
        assert calls == [1], "partner: the revoke landed during the restore"
        assert found.session is None and found.unchecked is None
        assert sid not in auth.session_repository._sessions
        assert auth.session_repository.get(sid) is None
    else:
        assert found.session is not None and found.session.session_id == sid


@pytest.mark.parametrize("kind_known", [False, True])
def test_r2_f4_a_cached_session_of_unknown_kind_is_not_ended_by_the_signed_in_limits(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch, kind_known: bool
) -> None:
    """R2-F4 (break-it round 2; ADR-0176 A4, CHG-088 (c)). A session restored
    while its kind read failed carries the signed-in limits. Cached, it
    crosses those 12 hours while its cutoff read waits and fails: it may be
    an anonymous session inside its 24 hours, so it is unchecked (of unknown
    kind), not ended, and is not listed as ended; once the store answers, the
    same cookie is served. Partner (``kind_known=True``): a known signed-in
    session in the same state is ended.
    Red when: ``_check_cached`` ends a session of unknown kind by the
    signed-in limits after a failed cutoff read."""
    clock = freeze(monkeypatch)
    session = anonymous_session()
    sid = session.session_id
    session.kind_known = kind_known
    session.max_age = auth.SIGNED_IN_MAX_AGE
    session.idle_limit = auth.signed_in_idle_limit()
    age(sid, auth.SIGNED_IN_MAX_AGE - timedelta(seconds=1), now=clock.at)

    def crosses_during_the_wait(call: int) -> None:
        clock.advance(timedelta(seconds=2))

    spy = ScriptedCutoff(live, session.account_id, [NOT_READ], on_call=crosses_during_the_wait)
    monkeypatch.setattr(live, "sessions_valid_after", spy)
    found = auth.session_repository.lookup(sid)
    assert spy.calls == 1, "partner: the cache hit's cutoff read ran"
    assert found.session is None
    if kind_known:
        assert found.unchecked is None
        assert sid in auth.session_repository._ended_ids
    else:
        assert found.unchecked is auth.Unchecked.UNKNOWN_KIND
        assert sid not in auth.session_repository._ended_ids
        served = auth.session_repository.lookup(sid)
        assert served.session is not None and served.session.session_id == sid
        assert served.session.max_age == auth.ANONYMOUS_MAX_AGE
