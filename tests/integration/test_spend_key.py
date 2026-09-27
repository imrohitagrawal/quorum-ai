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
        SimpleNamespace(status=qro.InitialAnswerStatus.COMPLETED, provider_path="openrouter")
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
