"""W7, 2b re-plan — the spend key (ADR-0136, CHG-025).

Each account life has a random id; the 24-hour spend envelope is keyed on a
separate spend key stored with the account (HMAC-SHA256 of the Google subject
for a new account, the account's own id for one created before). Every test
here drives a SIGNED-IN session, where the two differ: on an anonymous or
legacy-header session they are equal, so a money call left on the account id
would stay green there. Failure modes first:
``docs/analysis/2026-09-27-w7-account-deletion-failure-modes.md`` (S1-S9).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_google_sign_in import SignIn, _boot, _callback, _signed_in, _start
from tests.integration.test_query_run_cost_guardrails import (
    CONFIRM_MODEL_IDS,
    CONFIRM_QUERY,
    DEFAULT_MODEL_IDS,
    _stable_catalog_price,  # noqa: F401 -- a fixture, used by name below
    acknowledged_request,
)

from product_app import auth, session_store
from product_app import query_run_orchestration as qro
from product_app.costs import DAILY_CAP_USD, cost_estimation_service
from product_app.feedback_store import configure_for_tests as ledger_for_tests
from product_app.providers import InitialAnswerStatus
from product_app.query_run_orchestration import query_run_repository
from product_app.session_store import SessionStore

COOKIE = "quorum_session"
EMAIL = "ada@example.com"
QUERY = "Compare these answers"


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    query_run_repository.clear()
    auth.session_repository.forget_deleted_accounts()
    yield
    query_run_repository.clear()
    auth.session_repository.forget_deleted_accounts()


def _account(sign_in: SignIn) -> tuple[UUID, UUID, str]:
    """(account id, spend key, Google subject) of the one account row."""
    (row,) = sign_in.account_rows()
    return UUID(row["account_id"]), UUID(row["spend_key"]), row["google_sub"]


def _csrf(client: TestClient) -> str:
    return str(client.get("/v1/session").json()["csrf_token"])


def _create(client: TestClient, body: dict[str, Any] | None = None) -> Any:
    return client.post(
        "/v1/query-runs",
        json=body or acknowledged_request(QUERY),
        headers={"X-CSRF-Token": _csrf(client)},
    )


def _estimate(client: TestClient) -> Any:
    return client.post(
        "/v1/query-runs/estimate",
        json={"query_text": QUERY, "model_slots": DEFAULT_MODEL_IDS},
        headers={"X-CSRF-Token": _csrf(client)},
    )


def _delete(client: TestClient) -> Any:
    return client.post(
        "/v1/account/delete",
        json={"confirm_email": EMAIL},
        headers={"X-CSRF-Token": _csrf(client)},
    )


def _charge(
    ledger: Any, key: UUID, amount: str, *, run_id: UUID | None = None, live: bool = False
) -> None:
    outcome = ledger.try_record_cost_charge(
        account_id=key,
        query_run_id=run_id or uuid4(),
        estimated_cost_usd=Decimal(amount),
        payload={"account_id": str(key), "estimated_cost_usd": amount},
        daily_cap_usd=DAILY_CAP_USD,
        global_ceiling_usd=Decimal("50.00"),
        live_execution=live,
    )
    assert outcome.value == "recorded"


def test_a_new_account_has_a_random_id_and_a_keyed_spend_key(sign_in: SignIn) -> None:
    """Turns red if a new account's id is derived from its subject again (the
    id would then come back after deletion) or its spend key is not."""
    _signed_in(sign_in.client())
    account, spend_key, subject = _account(sign_in)
    derived = session_store.account_id_for(subject, key=session_store._account_key())
    assert spend_key == derived
    assert account != derived
    assert sign_in.store.spend_key_for(account) == spend_key


def test_deleting_and_signing_in_again_gives_a_new_id_and_keeps_the_days_spend(
    sign_in: SignIn,
) -> None:
    """CHG-012 D7: the envelope is kept. Turns red if the new life's estimate
    reads the spend under its account id (a fresh cap) instead of the spend
    key, or the new life gets the old id back."""
    with ledger_for_tests() as ledger:
        client = sign_in.client()
        _signed_in(client)
        old, spend_key, _ = _account(sign_in)
        assert _estimate(client).json()["cost_estimate"]["threshold_action"] == "allow"
        _charge(ledger, spend_key, "0.39")
        assert _delete(client).status_code == 200
        again = sign_in.client()
        _signed_in(again)
        new, same_key, _ = _account(sign_in)
        assert new != old
        assert same_key == spend_key
        estimate = _estimate(again).json()["cost_estimate"]
        assert estimate["threshold_action"] == "block"
        blocked = _create(again)
        assert blocked.status_code == 402, blocked.text
        assert blocked.json()["detail"]["code"] == "COST_LIMIT_EXCEEDED"


def test_a_run_is_charged_under_the_spend_key(sign_in: SignIn) -> None:
    """S1. Turns red if the create route, the repository or the charge passes
    the account id: the charge row and the in-memory total must both sit
    under the spend key, and nothing under the account id."""
    with ledger_for_tests() as ledger:
        client = sign_in.client()
        _signed_in(client)
        account, spend_key, _ = _account(sign_in)
        created = _create(client)
        assert created.status_code == 202, created.text
        run = query_run_repository.get(UUID(created.json()["query_run_id"]))
        assert run.account_id == account
        assert run.spend_key == spend_key
        unit = run.cost_estimate.estimated_cost_usd
        assert ledger.daily_spend_for(spend_key) == unit
        assert ledger.daily_spend_for(account) == Decimal("0")
        assert cost_estimation_service._cumulative_spend_for(spend_key) == unit


def test_reconcile_and_void_correct_the_charge_under_its_own_key(sign_in: SignIn) -> None:
    """S2 (measured by the read-only map: a correction under another key is
    accepted and changes nothing on the account's meter). Turns red if either
    correction is keyed on the account id. The ledger reconciles only a LIVE
    charge, so the reconcile half opens one for the run under its key; the
    void half uses the run's own (simulated) charge from the create route."""
    with ledger_for_tests() as ledger:
        client = sign_in.client()
        _signed_in(client)
        _, spend_key, _ = _account(sign_in)
        created = query_run_repository.get(UUID(_create(client).json()["query_run_id"]))
        unit = created.cost_estimate.estimated_cost_usd
        assert ledger.daily_spend_for(spend_key) == unit
        qro._void_run_billing(session=None, query_run=created, reason="test")  # type: ignore[arg-type]
        assert ledger.daily_spend_for(spend_key) == Decimal("0")
        query_run_repository.update_status(
            created.query_run_id, status_value=qro.QueryRunStatus.CANCELLED
        )
        live = query_run_repository.create(
            account_id=created.account_id,
            spend_key=spend_key,
            query_text=QUERY,
            model_slots=created.model_slots,
            cost_estimate=created.cost_estimate,
        )
        _charge(ledger, spend_key, "0.0500", run_id=live.query_run_id, live=True)
        actual = Decimal("0.0123")
        qro._reconcile_run_billing(
            query_run=live,
            response=SimpleNamespace(cost_source="measured", actual_cost_usd=actual),  # type: ignore[arg-type]
        )
        assert ledger.daily_spend_for(spend_key) == actual


def test_the_judge_reads_the_spend_key(sign_in: SignIn, monkeypatch: pytest.MonkeyPatch) -> None:
    """The judge's pre-flight re-reads the per-account cap before it pays.
    Turns red if it is built from the account id (it would read 0)."""
    client = sign_in.client()
    _signed_in(client)
    _, spend_key, _ = _account(sign_in)
    run = query_run_repository.get(UUID(_create(client).json()["query_run_id"]))
    monkeypatch.setattr(qro, "judge_configured", lambda: True)
    run.initial_answers = [
        SimpleNamespace(status=InitialAnswerStatus.COMPLETED, provider_path="openrouter")  # type: ignore[list-item]
    ]
    judge = qro._request_path_judge(run)
    assert judge is not None
    assert judge._account_id == spend_key


@pytest.mark.usefixtures("_stable_catalog_price")
def test_a_signed_in_confirmation_still_completes(sign_in: SignIn) -> None:
    """S3. The token stays bound to the account id while the rails take the
    spend key. Turns red if the two sides use different keys (every
    confirm-band run of a signed-in account would be refused)."""
    with ledger_for_tests():
        client = sign_in.client()
        _signed_in(client)
        csrf = _csrf(client)
        estimate = client.post(
            "/v1/query-runs/estimate",
            json={"query_text": CONFIRM_QUERY, "model_slots": CONFIRM_MODEL_IDS},
            headers={"X-CSRF-Token": csrf},
        ).json()["cost_estimate"]
        assert estimate["threshold_action"] == "require_confirmation"
        created = _create(
            client,
            {
                **acknowledged_request(CONFIRM_QUERY, CONFIRM_MODEL_IDS),
                "cost_confirmation": {
                    "estimated_cost_usd": estimate["estimated_cost_usd"],
                    "confirmation_token": estimate["confirmation_token"],
                },
            },
        )
        assert created.status_code == 202, created.text


def test_a_spend_key_that_cannot_be_read_refuses_the_run(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S4. Turns red if a read error falls back to the account id (a fresh,
    empty envelope) instead of refusing, or charges anything."""
    with ledger_for_tests() as ledger:
        client = sign_in.client()
        _signed_in(client)
        account, spend_key, _ = _account(sign_in)
        monkeypatch.setattr(sign_in.store, "spend_key_for", lambda _id: None)
        response = _create(client)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "SPEND_KEY_UNAVAILABLE"
        assert _estimate(client).status_code == 503
        assert ledger.daily_spend_for(account) == Decimal("0")
        assert ledger.daily_spend_for(spend_key) == Decimal("0")


def test_a_run_started_as_the_account_is_deleted_is_refused(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S4, round 2's second tab: the delete lands after this request's session
    check and before its run is created. Turns red if the run is created and
    charged under the account id (a fresh envelope)."""
    from product_app import account_deletion, query_runs

    with ledger_for_tests() as ledger:
        client = sign_in.client()
        _signed_in(client)
        account, spend_key, _ = _account(sign_in)
        real_limit = query_runs._enforce_account_rate_limit

        def limit_then_delete(*args: Any, **kwargs: Any) -> None:
            real_limit(*args, **kwargs)
            assert account_deletion.delete_account(account) is True

        monkeypatch.setattr(query_runs, "_enforce_account_rate_limit", limit_then_delete)
        response = _create(client)
        assert response.status_code == 401, response.text
        assert query_run_repository.get_active_for_account(account) is None
        assert ledger.daily_spend_for(account) == Decimal("0")
        assert ledger.daily_spend_for(spend_key) == Decimal("0")


def test_an_anonymous_run_keeps_its_key_after_sign_in(sign_in: SignIn) -> None:
    """S8. A run started anonymously is charged under the anonymous key; its
    correction after the browser signs in must land there too. Turns red if
    the run's key follows the new session (the void would then miss the
    charge)."""
    with ledger_for_tests() as ledger:
        client = sign_in.client()
        csrf = _boot(client)
        anonymous = auth.session_repository.get(client.cookies[COOKIE]).account_id  # type: ignore[union-attr]
        created = client.post(
            "/v1/query-runs", json=acknowledged_request(QUERY), headers={"X-CSRF-Token": csrf}
        )
        assert created.status_code == 202, created.text
        run = query_run_repository.get(UUID(created.json()["query_run_id"]))
        assert run.spend_key == anonymous
        query = _start(client, _csrf(client))
        _callback(client, code="stub-auth-code-1", state=query["state"])
        _, spend_key, _ = _account(sign_in)
        assert ledger.daily_spend_for(anonymous) == run.cost_estimate.estimated_cost_usd
        qro._void_run_billing(session=None, query_run=run, reason="test")  # type: ignore[arg-type]
        assert ledger.daily_spend_for(anonymous) == Decimal("0")
        assert ledger.daily_spend_for(spend_key) == Decimal("0")


def _old_database(path: Path, account_id: UUID) -> None:
    """A sessions database as the build before this change left it."""
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(
            SessionStore._SCHEMA
            + ";"
            + SessionStore._MIGRATIONS_DDL
            + ";"
            + SessionStore._ACCOUNTS_DDL
            + ";"
        )
        connection.execute(
            "INSERT INTO schema_migrations VALUES ('w7_accounts', '2026-09-26T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO accounts VALUES (?, 'sub-1', 'a@example.com', "
            "'2026-09-26T00:00:00+00:00', '2026-09-26T00:00:00+00:00')",
            (str(account_id),),
        )
        connection.commit()
    finally:
        connection.close()


def test_an_existing_account_keeps_its_own_id_as_its_spend_key(tmp_path: Path) -> None:
    """S5, CHG-024. Turns red if the backfill uses the hash (every existing
    account's day would reset at deploy) or leaves the key empty."""
    path = tmp_path / "old.sqlite3"
    existing = uuid4()
    _old_database(path, existing)
    store = SessionStore(str(path))
    try:
        assert store.accounts_available() is True
        assert store.spend_key_for(existing) == existing
        other = uuid4()
        assert store.spend_key_for(other) == other
    finally:
        store.close()
    connection = sqlite3.connect(str(path))
    try:
        rows = connection.execute("SELECT account_id, spend_key FROM accounts").fetchall()
    finally:
        connection.close()
    assert rows == [(str(existing), str(existing))]


def test_a_row_without_a_spend_key_uses_its_own_id(sign_in: SignIn) -> None:
    """S6: a row written by an older build after a rollback. Turns red if a
    NULL key reads as an error or as anything but the account's id."""
    _signed_in(sign_in.client())
    account, _, _ = _account(sign_in)
    sign_in.store._conn.execute("UPDATE accounts SET spend_key = NULL")
    assert sign_in.store.spend_key_for(account) == account


def test_a_failed_spend_key_migration_keeps_sign_in_off(tmp_path: Path) -> None:
    """S5. Turns red if sign-in stays available when the spend-key column
    could not be added: a new account would then be metered under its id."""
    path = tmp_path / "old.sqlite3"
    _old_database(path, uuid4())
    path.chmod(0o444)
    try:
        store = SessionStore(str(path))
        try:
            assert store.accounts_available() is False
        finally:
            store.close()
    finally:
        path.chmod(0o644)


def test_a_spend_key_read_error_is_none(sign_in: SignIn) -> None:
    """S4 at the store. Turns red if a failed read returns the account id,
    which the route would then meter under (a fresh envelope). Partner: the
    same store reads a real key before the table is broken."""
    _signed_in(sign_in.client())
    account, spend_key, _ = _account(sign_in)
    assert sign_in.store.spend_key_for(account) == spend_key
    sign_in.store._conn.execute("ALTER TABLE accounts RENAME TO accounts_gone")
    assert sign_in.store.spend_key_for(account) is None


def test_the_spend_key_depends_on_the_server_secret() -> None:
    """Turns red if the key stops being keyed (anyone could then compute a
    person's spend key from their public Google subject) or stops depending
    on the subject."""
    first = session_store.account_id_for("108000000000000000001", key=b"k" * 32)
    assert first == session_store.account_id_for("108000000000000000001", key=b"k" * 32)
    assert first != session_store.account_id_for("108000000000000000001", key=b"j" * 32)
    assert first != session_store.account_id_for("108000000000000000002", key=b"k" * 32)


def test_the_create_routes_running_total_reads_the_spend_key(sign_in: SignIn) -> None:
    """The in-memory running total is tested only
    in the estimate, and the create route re-estimates. Turns red if the
    create route's estimate reads the account id: the durable ledger is empty
    here, so only this rail can refuse."""
    from product_app.costs import HARD_LIMIT_USD, CostThresholdAction, cost_event_recorder
    from product_app.feedback_store import COST_ACCEPTED_SIMULATED_EVENT

    assert cost_event_recorder is not None
    with ledger_for_tests() as ledger:
        client = sign_in.client()
        _signed_in(client)
        account, spend_key, _ = _account(sign_in)
        cost_event_recorder.record(
            event_type=COST_ACCEPTED_SIMULATED_EVENT,
            account_id=spend_key,
            query_run_id=uuid4(),
            estimated_cost_usd=HARD_LIMIT_USD - Decimal("0.001"),
            threshold_action=CostThresholdAction.ALLOW,
            confirmed=False,
            persist=False,
        )
        assert ledger.daily_spend_for(spend_key) == Decimal("0")
        response = _create(client)
        assert response.status_code == 402, response.text
        assert query_run_repository.get_active_for_account(account) is None


def test_the_spend_key_is_refused_between_the_rows_going_and_the_second_refusal(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``spend_key_for`` reads the row, then the mark. Deletion must set the
    mark BEFORE the row goes, or a lookup landing just after the commit (and
    before the second refusal) finds neither and meters under the account id,
    a fresh envelope. Turns red if the first refusal is dropped."""
    from fastapi import HTTPException

    from product_app import account_deletion

    client = sign_in.client()
    _signed_in(client)
    account, _, _ = _account(sign_in)
    session = auth.SessionContext(account_id=account, session_id="s", csrf_token="c", legacy=False)
    real_delete = sign_in.store.delete_account
    seen: list[int] = []

    def delete_then_look(account_id: UUID) -> bool:
        assert real_delete(account_id) is True
        with pytest.raises(HTTPException) as refused:
            auth.spend_key_for(session)
        seen.append(refused.value.status_code)
        return True

    monkeypatch.setattr(sign_in.store, "delete_account", delete_then_look)
    assert account_deletion.delete_account(account) is True
    assert seen == [401]


# -- Fail-closed branches of the store (each returns what the caller refuses
# -- on, or the id only where no signed-in account can exist).


def test_spend_key_for_before_the_accounts_table_is_ready_is_the_id(tmp_path: Path) -> None:
    """With no usable accounts table no one can be signed in, so every id is
    metered as itself. Turns red if that reads as an error instead."""
    path = tmp_path / "old.sqlite3"
    _old_database(path, uuid4())
    path.chmod(0o444)
    try:
        store = SessionStore(str(path))
        try:
            anyone = uuid4()
            assert store.spend_key_for(anyone) == anyone
            assert store.delete_account(anyone) is False
        finally:
            store.close()
    finally:
        path.chmod(0o644)


def test_a_closed_store_refuses_both(tmp_path: Path) -> None:
    """Turns red if a closed store reports a key or a deletion."""
    store = SessionStore(str(tmp_path / "s.sqlite3"))
    store.close()
    assert store.spend_key_for(uuid4()) is None
    assert store.delete_account(uuid4()) is False


def test_an_unreadable_spend_key_is_none(sign_in: SignIn) -> None:
    """A value that is not a UUID. Turns red if it is metered as the id."""
    _signed_in(sign_in.client())
    account, _, _ = _account(sign_in)
    sign_in.store._conn.execute("UPDATE accounts SET spend_key = 'not-a-uuid'")
    assert sign_in.store.spend_key_for(account) is None


def test_a_delete_that_fails_inside_its_transaction_removes_nothing(sign_in: SignIn) -> None:
    """Turns red if a failure part-way through the transaction leaves the
    account half-deleted: the history table is dropped, so the first DELETE
    fails and everything rolls back."""
    _signed_in(sign_in.client())
    account, _, _ = _account(sign_in)
    sign_in.store._conn.execute("ALTER TABLE history RENAME TO history_gone")
    assert sign_in.store.delete_account(account) is False
    assert len(sign_in.account_rows()) == 1
    assert sign_in.store._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] > 0


def test_forgetting_run_rows_that_fails_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Best effort, like every run-history write. Turns red if the failure
    escapes into the deletion or goes unlogged."""
    from product_app import run_history_store

    class Broken:
        def forget_account(self, _account_id: str) -> None:
            raise RuntimeError("disk gone")

    monkeypatch.setattr(run_history_store, "get_store", lambda: Broken())
    run_history_store.forget_account(str(uuid4()))
    assert "could not forget a deleted account" in caplog.text


def test_a_sign_in_with_no_session_store_does_not_complete(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turns red if a callback with no store signs anyone in."""
    client = sign_in.client()
    csrf = _boot(client)
    query = _start(client, csrf)
    monkeypatch.setattr(session_store, "get_store", lambda: None)
    response = _callback(client, code="stub-auth-code-1", state=query["state"])
    assert response.status_code == 303
    assert response.headers["location"].endswith("sign_in=failed")


def test_an_older_account_keeps_its_days_spend_when_deleted_and_recreated(
    sign_in: SignIn,
) -> None:
    """CHG-025: the chosen option "also ends the old-account reset (CHG-024)".
    An account created before this change has its own id as its spend key;
    deleting it keeps a 24-hour pointer from the subject's hash to that key,
    and the re-created account takes it. Turns red if the new life starts a
    fresh envelope."""
    with ledger_for_tests() as ledger:
        client = sign_in.client()
        _signed_in(client)
        old, _, _ = _account(sign_in)
        sign_in.store._conn.execute("UPDATE accounts SET spend_key = account_id")
        assert sign_in.store.spend_key_for(old) == old
        _charge(ledger, old, "0.39")
        assert _delete(client).status_code == 200
        again = sign_in.client()
        _signed_in(again)
        new, key, _ = _account(sign_in)
        assert new != old
        assert key == old
        assert _estimate(again).json()["cost_estimate"]["threshold_action"] == "block"


def test_the_spend_key_pointer_lapses_after_a_day(sign_in: SignIn) -> None:
    """The pointer lasts the spend window and no longer. Turns red if a
    lapsed pointer is still used, or the pointer never lapses."""
    client = sign_in.client()
    _signed_in(client)
    old, _, subject = _account(sign_in)
    sign_in.store._conn.execute("UPDATE accounts SET spend_key = account_id")
    assert _delete(client).status_code == 200
    (until,) = sign_in.store._conn.execute("SELECT until FROM spend_key_carry").fetchone()
    assert timedelta(hours=24) == session_store.SPEND_KEY_CARRY
    sign_in.store._conn.execute("UPDATE spend_key_carry SET until = '2000-01-01T00:00:00+00:00'")
    _signed_in(sign_in.client())
    _, key, _ = _account(sign_in)
    assert key == session_store.account_id_for(subject, key=session_store._account_key())
    assert key != old
    assert until > datetime.now(UTC).isoformat()


def test_a_lapsed_pointer_is_removed_at_sign_in_and_on_open(
    sign_in: SignIn, tmp_path: Path
) -> None:
    """docs/48 and ADR-0136 say the pointer is kept 24 hours. Turns red if a
    lapsed row (the keyed hash of a deleted person's subject) is kept until
    some other account happens to be deleted."""
    client = sign_in.client()
    _signed_in(client)
    assert _delete(client).status_code == 200
    lapse = "UPDATE spend_key_carry SET until = '2000-01-01T00:00:00+00:00'"
    count = "SELECT COUNT(*) FROM spend_key_carry"
    sign_in.store._conn.execute(lapse)
    assert sign_in.store._conn.execute(count).fetchone()[0] == 1
    sign_in.stub.claims = {**sign_in.stub.claims, "sub": "someone-else", "email": "b@example.com"}
    _signed_in(sign_in.client())
    assert sign_in.store._conn.execute(count).fetchone()[0] == 0
    # On open: a lapsed row left by a process that stopped.
    path = tmp_path / "reopen.sqlite3"
    first = SessionStore(str(path))
    first._conn.execute(
        "INSERT INTO spend_key_carry VALUES ('k', 'v', '2000-01-01T00:00:00+00:00')"
    )
    first._conn.execute(
        "INSERT INTO spend_key_carry VALUES ('live', 'v', '2999-01-01T00:00:00+00:00')"
    )
    first.close()
    reopened = SessionStore(str(path))
    try:
        rows = [r[0] for r in reopened._conn.execute("SELECT subject_key FROM spend_key_carry")]
    finally:
        reopened.close()
    assert rows == ["live"]


def test_a_database_marked_before_the_pointer_table_gets_it(tmp_path: Path) -> None:
    """A database migrated by an earlier build of this branch has the
    spend-key marker but no pointer table. Turns red if such a database
    cannot sign anyone new in or delete an account."""
    path = tmp_path / "early.sqlite3"
    first = SessionStore(str(path))
    first._conn.execute("DROP TABLE spend_key_carry")
    first.close()
    store = SessionStore(str(path))
    try:
        created = store.upsert_google_account(
            google_sub="sub-new", email="n@example.com", now=datetime.now(UTC)
        )
        assert created is not None
        assert store.delete_account(created) is True
    finally:
        store.close()
