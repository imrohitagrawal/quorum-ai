"""W7, part 3, pull request A (ADR-0137): sign out everywhere, sign-in
events, and a rate limit on starting a sign-in (CHG-021 c to e).

Through the real sign-in flow (the sign-in suite's loopback Google stub).
Failure modes first: ``docs/analysis/2026-09-28-w7-session-safety-failure-modes.md``.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_google_sign_in import SignIn, _boot, _callback, _signed_in, _start

from product_app import account_history, auth, google_signin, session_store
from product_app.config import settings
from product_app.costs import CostEstimate, CostThresholdAction
from product_app.feedback_store import configure_for_tests as ledger_for_tests
from product_app.model_slots import DEFAULT_MODEL_IDS, validate_model_slots_with_search
from product_app.query_run_orchestration import QueryRunStatus, query_run_repository
from product_app.query_runs import _ip_rate_limiter

COOKIE = "quorum_session"
EVERYWHERE = "/v1/auth/sign-out-everywhere"


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    query_run_repository.clear()
    account_history.clear_carried()
    google_signin.sign_in_start_limiter.clear()
    yield
    query_run_repository.clear()
    account_history.clear_carried()
    google_signin.sign_in_start_limiter.clear()


def _account(sign_in: SignIn) -> UUID:
    (row,) = sign_in.account_rows()
    return UUID(row["account_id"])


def _csrf(client: TestClient) -> str:
    return str(client.get("/v1/session").json()["csrf_token"])


def _everywhere(client: TestClient, *, csrf: str | None = None) -> Any:
    headers = {} if csrf == "" else {"X-CSRF-Token": csrf or _csrf(client)}
    return client.post(EVERYWHERE, headers=headers)


def _session_rows(sign_in: SignIn, account: UUID) -> int:
    return int(
        sign_in.store._conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE account_id = ?", (str(account),)
        ).fetchone()[0]
    )


def _signed_in_page(client: TestClient) -> bool:
    return 'id="account-email"' in client.get("/ui").text


def _restart() -> None:
    """The in-process half is gone; the disk and its cutoff remain."""
    auth.session_repository._sessions.clear()
    auth.session_repository.forget_deleted_accounts()
    auth.session_repository._valid_after.clear()


# -- (c) Sign out everywhere ----------------------------------------------


def test_sign_out_everywhere_ends_every_session_of_the_account(sign_in: SignIn) -> None:
    """Turns red if any device of the account is still signed in afterwards,
    from the cache or from disk after a restart, or this browser keeps its
    cookie."""
    phone = sign_in.client()
    laptop = sign_in.client()
    _signed_in(phone)
    _signed_in(laptop)
    account = _account(sign_in)
    laptop_session = laptop.cookies[COOKIE]
    assert _signed_in_page(laptop)
    response = _everywhere(phone)
    assert response.status_code == 200, response.text
    assert response.json() == {"signed_out": True}
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"
    assert auth.session_repository.get(laptop_session) is None
    assert _session_rows(sign_in, account) == 0
    _restart()
    assert auth.session_repository.get(laptop_session) is None
    assert not _signed_in_page(laptop)


def test_the_next_sign_in_works_and_survives_a_restart(sign_in: SignIn) -> None:
    """The cutoff is a time, not a refusal of the account: a session created
    after it must work, even after a restart (account deletion's refusal
    would refuse it for two hours). Turns red if it does not."""
    phone = sign_in.client()
    _signed_in(phone)
    assert _everywhere(phone).status_code == 200
    again = sign_in.client()
    _signed_in(again)
    session_id = again.cookies[COOKIE]
    assert _signed_in_page(again)
    _restart()
    assert auth.session_repository.get(session_id) is not None
    assert _signed_in_page(again)


def test_it_removes_nothing_but_sessions(sign_in: SignIn) -> None:
    """Turns red if signing out everywhere touches the account, its history,
    its spend key, or marks it as deleted."""
    phone = sign_in.client()
    _signed_in(phone)
    account = _account(sign_in)
    run = query_run_repository.create(
        account_id=account,
        query_text="kept",
        model_slots=validate_model_slots_with_search(list(DEFAULT_MODEL_IDS)[:2], mode="panel"),
        cost_estimate=CostEstimate(
            estimated_cost_usd=Decimal("0.0300"),
            threshold_action=CostThresholdAction.ALLOW,
            confirmation_token=None,
            reasons=[],
        ),
    )
    query_run_repository.update_status(run.query_run_id, status_value=QueryRunStatus.COMPLETED)
    account_history.record_finished_run(query_run_repository.get(run.query_run_id))
    (before,) = sign_in.account_rows()
    assert _everywhere(phone).status_code == 200
    (after,) = sign_in.account_rows()
    assert dict(after) == {**dict(before), "sessions_valid_after": after["sessions_valid_after"]}
    assert after["sessions_valid_after"] is not None
    assert [e.question for e in account_history.history_for(account) or []] == ["kept"]
    assert auth.session_repository.account_is_going(account) is False


def test_only_a_signed_in_browser_with_its_csrf_token_can_do_it(sign_in: SignIn) -> None:
    """Turns red if an anonymous session, a request without the CSRF token or
    the local header path can end an account's sessions. Partner: the
    account's session still resolves after each refusal."""
    laptop = sign_in.client()
    _signed_in(laptop)
    account = _account(sign_in)
    laptop_session = laptop.cookies[COOKIE]
    anonymous = sign_in.client()
    assert _everywhere(anonymous).status_code == 403
    assert _everywhere(laptop, csrf="").status_code == 403
    bare = sign_in.client()
    legacy = bare.post(
        EVERYWHERE,
        headers={"X-Account-Id": str(account), "X-CSRF-Token": auth.LEGACY_CSRF_PLACEHOLDER},
    )
    assert legacy.status_code == 403
    assert auth.session_repository.get(laptop_session) is not None
    assert _session_rows(sign_in, account) >= 1


def test_a_create_already_past_the_session_check_is_refused(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE OWNER'S REQUIRED RACE: the laptop's create has passed its session
    check when the phone signs out everywhere. Turns red if the create still
    starts a run or charges anything."""
    from product_app import query_runs

    phone = sign_in.client()
    laptop = sign_in.client()
    _signed_in(phone)
    _signed_in(laptop)
    account = _account(sign_in)
    phone_csrf = _csrf(phone)
    laptop_csrf = _csrf(laptop)
    real_limit = query_runs._enforce_account_rate_limit
    ended: list[int] = []

    def limit_then_phone_signs_out_everywhere(*args: Any, **kwargs: Any) -> None:
        real_limit(*args, **kwargs)
        if not ended:
            ended.append(_everywhere(phone, csrf=phone_csrf).status_code)

    with ledger_for_tests() as ledger:
        monkeypatch.setattr(
            query_runs, "_enforce_account_rate_limit", limit_then_phone_signs_out_everywhere
        )
        created = laptop.post(
            "/v1/query-runs",
            json={
                "query_text": "in flight",
                "model_slots": list(DEFAULT_MODEL_IDS),
                "safety_acknowledgements": [],
            },
            headers={"X-CSRF-Token": laptop_csrf},
        )
        assert ended == [200]
        assert created.status_code == 401, created.text
        assert query_run_repository.get_active_for_account(account) is None
        (row,) = sign_in.account_rows()
        assert ledger.daily_spend_for(UUID(row["spend_key"])) == Decimal("0")


def test_a_session_being_restored_during_it_is_not_put_back(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The laptop's session is read from disk just before the cutoff and
    cached just after. Turns red if it comes back."""
    phone = sign_in.client()
    laptop = sign_in.client()
    _signed_in(phone)
    _signed_in(laptop)
    phone_csrf = _csrf(phone)
    laptop_session = laptop.cookies[COOKIE]
    auth.session_repository._sessions.pop(laptop_session)
    real_fetch = sign_in.store.fetch

    def fetch_then_sign_out(*args: Any, **kwargs: Any) -> Any:
        stored = real_fetch(*args, **kwargs)
        monkeypatch.setattr(sign_in.store, "fetch", real_fetch)
        assert _everywhere(phone, csrf=phone_csrf).status_code == 200
        return stored

    monkeypatch.setattr(sign_in.store, "fetch", fetch_then_sign_out)
    assert auth.session_repository.get(laptop_session) is None


def test_a_session_written_back_during_it_does_not_survive_a_restart(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another device's request lands after the rows are deleted and before
    its cached session is dropped, and writes its row back. Turns red if the
    row is still on disk afterwards."""
    phone = sign_in.client()
    laptop = sign_in.client()
    _signed_in(phone)
    _signed_in(laptop)
    account = _account(sign_in)
    laptop_session = laptop.cookies[COOKIE]
    real_end = sign_in.store.end_sessions_before

    def end_then_laptop_calls(*args: Any, **kwargs: Any) -> Any:
        done = real_end(*args, **kwargs)
        laptop.get("/v1/session")
        return done

    monkeypatch.setattr(sign_in.store, "end_sessions_before", end_then_laptop_calls)
    assert _everywhere(phone).status_code == 200
    assert _session_rows(sign_in, account) == 0
    _restart()
    assert auth.session_repository.get(laptop_session) is None


def test_concurrent_requests_of_another_device_all_end(sign_in: SignIn) -> None:
    """Ten threads of the laptop keep calling while the phone signs out
    everywhere. Turns red if any of the laptop's requests succeeds after the
    sign-out returned, or a row of the account is left."""
    phone = sign_in.client()
    laptop = sign_in.client()
    _signed_in(phone)
    _signed_in(laptop)
    account = _account(sign_in)
    cookie = laptop.cookies[COOKIE]
    done = threading.Event()
    after: list[int] = []
    lock = threading.Lock()

    def keep_calling() -> None:
        client = TestClient(sign_in.client().app)
        client.cookies.set(COOKIE, cookie)
        while True:
            finished = done.is_set()
            status_code = client.get("/v1/query-runs/active").status_code
            if finished:
                with lock:
                    after.append(status_code)
                return

    threads = [threading.Thread(target=keep_calling) for _ in range(10)]
    for thread in threads:
        thread.start()
    assert _everywhere(phone).status_code == 200
    done.set()
    for thread in threads:
        thread.join(timeout=30)
    assert len(after) == 10
    assert set(after) == {401}
    assert _session_rows(sign_in, account) == 0


def test_a_store_that_cannot_record_the_cutoff_refuses_and_changes_nothing(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turns red if a failed write reports success, or refuses any session."""
    phone = sign_in.client()
    laptop = sign_in.client()
    _signed_in(phone)
    _signed_in(laptop)
    laptop_session = laptop.cookies[COOKIE]
    monkeypatch.setattr(sign_in.store, "end_sessions_before", lambda *_a, **_k: "failed")
    response = _everywhere(phone)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SIGN_OUT_EVERYWHERE_FAILED"
    assert auth.session_repository.get(laptop_session) is not None
    assert _signed_in_page(phone)


# -- (d) Sign-in events -----------------------------------------------------


def _events(sign_in: SignIn) -> list[sqlite3.Row]:
    return list(sign_in.store._conn.execute("SELECT * FROM sign_in_events ORDER BY at, rowid"))


def test_sign_in_sign_out_and_sign_out_everywhere_are_recorded(sign_in: SignIn) -> None:
    """CHG-021 d: time and outcome. Turns red if an outcome is missing, a
    column is added, or a row belongs to the wrong account."""
    client = sign_in.client()
    _signed_in(client)
    account = _account(sign_in)
    csrf = _csrf(client)
    assert client.post("/v1/auth/sign-out", headers={"X-CSRF-Token": csrf}).status_code == 200
    again = sign_in.client()
    _signed_in(again)
    assert _everywhere(again).status_code == 200
    rows = _events(sign_in)
    assert [r["outcome"] for r in rows] == [
        "signed_in",
        "signed_out",
        "signed_in",
        "signed_out_everywhere",
    ]
    assert {r["account_id"] for r in rows} == {str(account)}
    assert set(rows[0].keys()) == {"account_id", "at", "outcome"}


def test_no_secret_reaches_an_event_row(sign_in: SignIn) -> None:
    """Turns red if a code, state, verifier, token, subject, email, session
    id or address reaches the table. Partner: the same scan finds each one
    in a planted row, so the scan is not blind."""
    client = sign_in.client()
    csrf = _boot(client)
    query = _start(client, csrf)
    _callback(client, code="stub-auth-code-1", state=query["state"])
    session_id = client.cookies[COOKIE]
    (row,) = sign_in.account_rows()
    secrets = [
        "stub-auth-code-1",
        query["state"],
        query["code_challenge"],
        row["google_sub"],
        row["email"],
        session_id,
        "testclient",
    ]

    def dump() -> str:
        return "\n".join(
            "|".join(str(v) for v in r)
            for r in sign_in.store._conn.execute("SELECT * FROM sign_in_events")
        )

    text = dump()
    assert text
    assert [s for s in secrets if s in text] == []
    sign_in.store._conn.execute(
        "INSERT INTO sign_in_events VALUES (?, ?, ?)",
        (row["account_id"], "|".join(secrets), "planted"),
    )
    assert [s for s in secrets if s in dump()] == secrets


def test_events_keep_the_newest_and_drop_the_old(sign_in: SignIn) -> None:
    """Turns red if more than the keep count is kept, or a row older than the
    keep window survives the next write."""
    client = sign_in.client()
    _signed_in(client)
    account = _account(sign_in)
    old = (datetime.now(UTC) - timedelta(days=settings.sign_in_events_keep_days + 1)).isoformat()
    sign_in.store._conn.execute(
        "INSERT INTO sign_in_events VALUES (?, ?, 'signed_in')", (str(account), old)
    )
    before_last = ""
    for _ in range(settings.sign_in_events_keep_count + 2):
        # Neither limiter is what this test is about.
        google_signin.sign_in_start_limiter.clear()
        _ip_rate_limiter.clear()
        before_last = datetime.now(UTC).isoformat()
        _signed_in(sign_in.client())
    rows = _events(sign_in)
    assert len(rows) == settings.sign_in_events_keep_count
    assert old not in {r["at"] for r in rows}
    # The NEWEST are kept: the last sign-in's own row is among them.
    assert [r for r in rows if r["at"] >= before_last]


def test_deleting_the_account_deletes_its_events(sign_in: SignIn) -> None:
    """Turns red if an event row outlives its account."""
    client = sign_in.client()
    _signed_in(client)
    assert _events(sign_in)
    deleted = client.post(
        "/v1/account/delete",
        json={"confirm_email": "ada@example.com"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert deleted.status_code == 200
    assert _events(sign_in) == []


def test_an_event_for_an_id_with_no_account_is_not_stored(sign_in: SignIn) -> None:
    """Turns red if an event can be written for an id with no account row
    (a deleted account, or an anonymous session)."""
    from uuid import uuid4

    assert sign_in.store.record_sign_in_event(
        uuid4(), "signed_in", now=datetime.now(UTC), keep_count=10, keep_days=30
    ) in (True, False)
    assert _events(sign_in) == []


# -- (e) The sign-in start is rate-limited -----------------------------------


def test_starting_a_sign_in_is_limited_per_address(sign_in: SignIn) -> None:
    """Turns red if the start is not limited, the limit is not its own (the
    session limiter still answers), or the 429 lacks its code or Retry-After."""
    client = sign_in.client()
    csrf = _boot(client)
    burst = settings.sign_in_starts_per_address_burst
    for _ in range(burst):
        assert (
            client.post("/v1/auth/google/start", headers={"X-CSRF-Token": csrf}).status_code == 200
        )
    refused = client.post("/v1/auth/google/start", headers={"X-CSRF-Token": csrf})
    assert refused.status_code == 429
    assert refused.json()["detail"]["code"] == "SIGN_IN_RATE_LIMITED"
    assert int(refused.headers["retry-after"]) > 0
    assert client.get("/v1/session").status_code == 200


def test_a_sign_in_already_started_still_finishes(sign_in: SignIn) -> None:
    """Only the start is limited. Turns red if the callback of a sign-in
    started before the address used up its starts is refused."""
    client = sign_in.client()
    query = _start(client, _boot(client))
    other = sign_in.client()  # the same address (the test client's)
    other_csrf = _boot(other)
    for _ in range(settings.sign_in_starts_per_address_burst - 1):
        assert (
            other.post("/v1/auth/google/start", headers={"X-CSRF-Token": other_csrf}).status_code
            == 200
        )
    refused = other.post("/v1/auth/google/start", headers={"X-CSRF-Token": other_csrf})
    assert refused.status_code == 429
    response = _callback(client, code="stub-auth-code-1", state=query["state"])
    assert response.status_code == 303
    assert response.headers["location"] == "/ui"


def test_the_proposed_values_are_pinned() -> None:
    """PROPOSED — AWAITING OWNER (CHG-021: the session proposes them as
    settings). Turns red if a default moves without the ADR moving too."""
    assert settings.sign_in_starts_per_address_burst == 5
    assert settings.sign_in_starts_per_address_per_minute == 1
    assert settings.sign_in_events_keep_count == 10
    assert settings.sign_in_events_keep_days == 30


def test_rows_go_with_the_cutoff_even_if_the_process_stops_after_it(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rows are deleted in the transaction that records the cutoff, not
    only by the second pass. Turns red if a process stopping right after the
    commit leaves them on disk."""
    phone = sign_in.client()
    laptop = sign_in.client()
    _signed_in(phone)
    _signed_in(laptop)
    account = _account(sign_in)

    def process_stops(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("the process stopped")

    monkeypatch.setattr(auth.session_repository, "end_sessions_of", process_stops)
    with pytest.raises(RuntimeError):
        _everywhere(phone)
    assert _session_rows(sign_in, account) == 0


def test_the_cutoff_on_disk_refuses_a_row_written_back_before_a_crash(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another device writes its row back after the commit, then the process
    stops before dropping the cache and the second pass. Turns red if, after
    the restart, that row resolves: only the durable cutoff can refuse it."""
    phone = sign_in.client()
    laptop = sign_in.client()
    _signed_in(phone)
    _signed_in(laptop)
    laptop_session = laptop.cookies[COOKIE]
    real_end = sign_in.store.end_sessions_before

    def end_then_laptop_calls(*args: Any, **kwargs: Any) -> Any:
        done = real_end(*args, **kwargs)
        laptop.get("/v1/session")
        return done

    def process_stops(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("the process stopped")

    monkeypatch.setattr(sign_in.store, "end_sessions_before", end_then_laptop_calls)
    monkeypatch.setattr(auth.session_repository, "end_sessions_of", process_stops)
    with pytest.raises(RuntimeError):
        _everywhere(phone)
    account = _account(sign_in)
    assert _session_rows(sign_in, account) == 1  # the written-back row
    _restart()
    assert auth.session_repository.get(laptop_session) is None


def test_a_sign_out_between_the_cutoff_read_and_the_cache_write_is_seen(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A restore reads the cutoff on disk (none yet), then the account signs
    out everywhere, then the restore caches the session. Turns red if the
    restore does not re-check the in-memory cutoff under the lock."""
    phone = sign_in.client()
    laptop = sign_in.client()
    _signed_in(phone)
    _signed_in(laptop)
    phone_csrf = _csrf(phone)
    laptop_session = laptop.cookies[COOKIE]
    auth.session_repository._sessions.pop(laptop_session)
    real_read = sign_in.store.sessions_valid_after

    def read_then_sign_out(account_id: UUID) -> Any:
        result = real_read(account_id)
        monkeypatch.setattr(sign_in.store, "sessions_valid_after", real_read)
        assert _everywhere(phone, csrf=phone_csrf).status_code == 200
        return result

    monkeypatch.setattr(sign_in.store, "sessions_valid_after", read_then_sign_out)
    assert auth.session_repository.get(laptop_session) is None


def test_a_cutoff_that_cannot_be_read_refuses_the_restore(sign_in: SignIn) -> None:
    """Turns red if a failed read of the cutoff lets a session restore (the
    open side). Partner: the same session restores while the read works."""
    laptop = sign_in.client()
    _signed_in(laptop)
    laptop_session = laptop.cookies[COOKIE]
    auth.session_repository._sessions.pop(laptop_session)
    assert auth.session_repository.get(laptop_session) is not None
    auth.session_repository._sessions.pop(laptop_session)
    sign_in.store._conn.execute("ALTER TABLE accounts RENAME TO accounts_gone")
    assert auth.session_repository.get(laptop_session) is None


# -- Review round 1 (2026-09-28) ------------------------------------------------


def test_a_session_held_by_a_request_in_flight_is_not_written_back(sign_in: SignIn) -> None:
    """A request of the laptop holds its session object while the phone signs
    out everywhere, then writes it (a CSRF rotation). Turns red if the row
    comes back: the dropped session must no longer be the cached one."""
    phone = sign_in.client()
    laptop = sign_in.client()
    _signed_in(phone)
    _signed_in(laptop)
    account = _account(sign_in)
    held = auth.session_repository.get(laptop.cookies[COOKIE])
    assert held is not None
    assert _everywhere(phone).status_code == 200
    auth.session_repository._persist(held)
    assert _session_rows(sign_in, account) == 0


def test_the_cutoff_never_moves_back(sign_in: SignIn) -> None:
    """Turns red if a later write with an older cutoff lowers the stored one,
    on disk or in memory."""
    _signed_in(sign_in.client())
    account = _account(sign_in)
    later = datetime.now(UTC)
    earlier = later - timedelta(seconds=5)
    assert sign_in.store.end_sessions_before(account, later) == "ended"
    assert sign_in.store.end_sessions_before(account, earlier) == "ended"
    assert sign_in.store.sessions_valid_after(account) == (True, later)
    auth.session_repository.end_sessions_of(account, later)
    auth.session_repository.end_sessions_of(account, earlier)
    assert auth.session_repository._valid_after[account] == later


def test_lapsed_cutoffs_are_dropped_from_memory() -> None:
    """Turns red if a cutoff older than the session lifetime is kept (it can
    refuse nothing, and the map would grow by one entry per account), or if
    another account's live cutoff is dropped with it."""
    from uuid import uuid4

    old, live, fresh = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    auth.session_repository._valid_after[old] = now - auth.SESSION_TTL
    auth.session_repository._valid_after[live] = now - timedelta(minutes=1)
    auth.session_repository.end_sessions_of(fresh, now)
    assert old not in auth.session_repository._valid_after
    assert live in auth.session_repository._valid_after
    assert fresh in auth.session_repository._valid_after


def test_signing_out_everywhere_as_the_account_is_deleted_says_not_signed_in(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turns red if a sign-out racing the account's deletion is told to try
    again (503) rather than that there is no account (403)."""
    phone = sign_in.client()
    _signed_in(phone)
    account = _account(sign_in)
    real_end = sign_in.store.end_sessions_before

    def delete_then_end(*args: Any, **kwargs: Any) -> Any:
        assert sign_in.store.delete_account(account) is True
        return real_end(*args, **kwargs)

    monkeypatch.setattr(sign_in.store, "end_sessions_before", delete_then_end)
    response = _everywhere(phone)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "NOT_SIGNED_IN"


def test_a_closed_or_unreadable_cutoff_refuses_the_restore(sign_in: SignIn) -> None:
    """The two other fail-closed branches of the cutoff read. Turns red if a
    closed store or a corrupt stored cutoff lets a session restore."""
    from uuid import uuid4

    _signed_in(sign_in.client())
    account = _account(sign_in)
    sign_in.store._conn.execute("UPDATE accounts SET sessions_valid_after = 'not a time'")
    assert sign_in.store.sessions_valid_after(account) == (False, None)
    closed = session_store.SessionStore(":memory:")
    closed.close()
    assert closed.sessions_valid_after(uuid4()) == (False, None)


def test_sign_in_events_older_than_the_window_go_at_the_next_event(sign_in: SignIn) -> None:
    """With fewer rows than the keep count, only the day rule can remove an
    old one. Turns red if it is not applied."""
    client = sign_in.client()
    _signed_in(client)
    account = _account(sign_in)
    sign_in.store._conn.execute("DELETE FROM sign_in_events")
    old = (datetime.now(UTC) - timedelta(days=settings.sign_in_events_keep_days + 1)).isoformat()
    sign_in.store._conn.execute(
        "INSERT INTO sign_in_events VALUES (?, ?, 'signed_in')", (str(account), old)
    )
    google_signin.sign_in_start_limiter.clear()
    _signed_in(sign_in.client())
    rows = _events(sign_in)
    assert len(rows) == 1
    assert rows[0]["at"] != old


def test_the_start_limit_is_per_address_and_says_when_to_retry(sign_in: SignIn) -> None:
    """Turns red if the start limit is one site-wide bucket, is not grouped
    by IPv6 /64, or Retry-After is not 60 seconds at the proposed rate."""

    def boot(address: str) -> tuple[TestClient, str]:
        client = TestClient(sign_in.client().app, client=(address, 50000))
        return client, _csrf(client)

    first, first_csrf = boot("2001:db8:1:2::1")
    same64, same64_csrf = boot("2001:db8:1:2::99")
    other64, other64_csrf = boot("2001:db8:1:3::1")
    v4, v4_csrf = boot("203.0.113.7")
    start = "/v1/auth/google/start"
    for _ in range(settings.sign_in_starts_per_address_burst):
        assert first.post(start, headers={"X-CSRF-Token": first_csrf}).status_code == 200
    refused = same64.post(start, headers={"X-CSRF-Token": same64_csrf})
    assert refused.status_code == 429
    assert refused.headers["retry-after"] == "60"
    assert other64.post(start, headers={"X-CSRF-Token": other64_csrf}).status_code == 200
    assert v4.post(start, headers={"X-CSRF-Token": v4_csrf}).status_code == 200
