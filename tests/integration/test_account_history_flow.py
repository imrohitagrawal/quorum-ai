"""W7, 2a — signed-in history through the real sign-in flow (ADR-0135).

Uses the sign-in suite's loopback Google stub. Runs are built directly in the
in-memory repository and finished through the real ``_persist_terminal_run``,
the one place a finished run is recorded.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_google_sign_in import (
    SignIn,
    _boot,
    _callback,
    _signed_in,
    _start,
)

from product_app import account_history, auth
from product_app import query_run_orchestration as qro
from product_app.costs import CostEstimate, CostThresholdAction
from product_app.model_slots import validate_model_slots_with_search
from product_app.query_run_orchestration import QueryRunStatus, query_run_repository

COOKIE = "quorum_session"


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    query_run_repository.clear()
    account_history.clear_carried()
    yield
    query_run_repository.clear()
    account_history.clear_carried()


def _session_account(client: TestClient) -> UUID:
    session = auth.session_repository.get(client.cookies[COOKIE])
    assert session is not None
    return session.account_id


def _start_run(account_id: UUID, question: str) -> Any:
    ids = ["openai/gpt-4.1-mini", "anthropic/claude-haiku-4.5"]
    return query_run_repository.create(
        account_id=account_id,
        query_text=question,
        model_slots=validate_model_slots_with_search(ids, mode="panel"),
        cost_estimate=CostEstimate(
            estimated_cost_usd=Decimal("0.0300"),
            threshold_action=CostThresholdAction.ALLOW,
            confirmation_token=None,
            reasons=[],
        ),
    )


def _finish(run: Any) -> None:
    query_run_repository.update_status(run.query_run_id, status_value=QueryRunStatus.COMPLETED)
    qro._persist_terminal_run(run.query_run_id)


def _questions(account_id: UUID) -> list[str]:
    return [entry.question for entry in account_history.history_for(account_id)]


def _account_id(sign_in: SignIn) -> UUID:
    (row,) = sign_in.account_rows()
    return UUID(row["account_id"])


def test_a_signed_in_accounts_finished_run_joins_its_history(sign_in: SignIn) -> None:
    """Turns red if a signed-in account's finished run is not recorded."""
    client = sign_in.client()
    assert _signed_in(client).status_code == 303
    account = _account_id(sign_in)
    _finish(_start_run(account, "What is the capital of Australia?"))
    assert _questions(account) == ["What is the capital of Australia?"]


def test_an_anonymous_run_is_kept_nowhere(sign_in: SignIn) -> None:
    """Positive partner of the test above: an anonymous visitor's question
    is not stored. Turns red if anonymous runs are recorded."""
    client = sign_in.client()
    _boot(client)
    anonymous = _session_account(client)
    _finish(_start_run(anonymous, "an anonymous question"))
    assert _questions(anonymous) == []
    assert (
        sign_in.store.history_for(str(anonymous), keep_count=5, keep_days=30, now=datetime.now(UTC))
        == []
    )


def test_this_sessions_finished_runs_are_carried_over_at_sign_in(sign_in: SignIn) -> None:
    """CHG-021 (a). Turns red if the signing-in session's finished runs do
    not join the account, or another browser's runs do."""
    other = sign_in.client()
    _boot(other)
    _finish(_start_run(_session_account(other), "another browser's question"))

    client = sign_in.client()
    csrf = _boot(client)
    _finish(_start_run(_session_account(client), "asked before signing in"))
    query = _start(client, csrf)
    assert _callback(client, code="stub-auth-code-1", state=query["state"]).status_code == 303
    assert _questions(_account_id(sign_in)) == ["asked before signing in"]


def test_a_run_still_running_at_sign_in_joins_when_it_finishes(sign_in: SignIn) -> None:
    """THE PROMISED RACE (2026-09-25, 11:30:42Z). A run started anonymously
    is still running when its browser signs in; it finishes afterwards under
    its anonymous id and must still join the account's history, once.
    Turns red if the run is lost, or listed twice."""
    client = sign_in.client()
    csrf = _boot(client)
    running = _start_run(_session_account(client), "still running at sign-in")
    query = _start(client, csrf)
    assert _callback(client, code="stub-auth-code-1", state=query["state"]).status_code == 303
    account = _account_id(sign_in)
    assert _questions(account) == []  # not finished yet
    _finish(running)
    qro._persist_terminal_run(running.query_run_id)  # a second terminal fire
    assert _questions(account) == ["still running at sign-in"]


def test_carry_over_is_capped_by_the_keep_rule(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CHG-021 (a): "capped by the same keep-the-last-5 rule". With the rule
    held at 2, three carried runs leave the newest 2. Turns red if carry-over
    bypasses the keep rule."""
    from product_app.config import settings

    monkeypatch.setattr(settings, "history_keep_count", 2)
    client = sign_in.client()
    csrf = _boot(client)
    anonymous = _session_account(client)
    for n in range(3):
        run = _start_run(anonymous, f"q{n}")
        _finish(run)
    query = _start(client, csrf)
    _callback(client, code="stub-auth-code-1", state=query["state"])
    assert len(_questions(_account_id(sign_in))) == 2


def test_signing_out_keeps_the_history(sign_in: SignIn) -> None:
    """CHG-012 D7: "the whole purpose will be forfeited if we delete the
    history on every sign-out". Turns red if sign-out deletes history."""
    client = sign_in.client()
    _signed_in(client)
    account = _account_id(sign_in)
    _finish(_start_run(account, "kept across sign-out"))
    csrf = client.get("/v1/session").json()["csrf_token"]
    assert client.post("/v1/auth/sign-out", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert _questions(account) == ["kept across sign-out"]
    again = sign_in.client()
    _signed_in(again)
    assert _account_id(sign_in) == account
    assert "kept across sign-out" in again.get("/ui").text


def test_the_page_lists_the_history_escaped(sign_in: SignIn) -> None:
    """Turns red if the history is missing from a signed-in page or a
    question is inserted unescaped."""
    client = sign_in.client()
    _signed_in(client)
    _finish(_start_run(_account_id(sign_in), "is <b>this</b> escaped?"))
    html = client.get("/ui").text
    assert 'id="account-history"' in html
    assert "is &lt;b&gt;this&lt;/b&gt; escaped?" in html
    assert "is <b>this</b> escaped?" not in html
    assert "2 models" in html
    assert "estimated $0.0300" in html


def test_an_empty_history_says_so(sign_in: SignIn) -> None:
    """Turns red if a signed-in account with no runs gets no history box."""
    client = sign_in.client()
    _signed_in(client)
    html = client.get("/ui").text
    assert 'id="account-history-empty"' in html
    assert "No questions yet." in html


def test_a_signed_in_page_says_what_is_kept(sign_in: SignIn) -> None:
    """CHG-012 D7: "Results are ephemeral" rewritten for signed-in users.
    Turns red if a signed-in visitor is told results are ephemeral, or the
    new line misstates the keep rules."""
    client = sign_in.client()
    _signed_in(client)
    html = client.get("/ui").text
    assert "Results are ephemeral." not in html
    assert (
        "Your last 5 questions stay in your history for 30 days; answers are not kept, "
        "so export one to keep it." in html
    )


def test_an_anonymous_page_is_unchanged(sign_in: SignIn) -> None:
    """The positive partner: an anonymous visitor keeps the old line and gets
    no history box. Turns red if the anonymous page changes."""
    html = sign_in.client().get("/ui").text
    assert "Results are ephemeral. Cost is shown before each run" in html
    assert 'id="account-history"' not in html


def test_another_accounts_history_is_never_shown(sign_in: SignIn) -> None:
    """Turns red if a page lists runs of an account other than its own."""
    client = sign_in.client()
    _signed_in(client)
    mine = _account_id(sign_in)
    _finish(_start_run(mine, "my own question 7f3a"))
    stranger = UUID(int=7)
    sign_in.store.record_history(
        account_history._entry(_start_run(stranger, "a stranger question 9c1d"), stranger),
        keep_count=5,
        keep_days=30,
        now=datetime.now(UTC),
    )
    html = client.get("/ui").text
    assert "my own question 7f3a" in html
    assert "a stranger question 9c1d" not in html


def test_the_sign_in_link_lapses_once_no_run_can_still_be_running(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The carry-over link lasts QUERY_RUN_ACTIVE_TTL (30 minutes). Turns red
    if a run of the old anonymous session that finishes after the link has
    lapsed still joins the account's history."""
    client = sign_in.client()
    csrf = _boot(client)
    anonymous = _session_account(client)
    query = _start(client, csrf)
    _callback(client, code="stub-auth-code-1", state=query["state"])
    later = datetime.now(UTC) + qro.QUERY_RUN_ACTIVE_TTL + timedelta(minutes=1)
    monkeypatch.setattr(account_history, "_now", lambda: later)
    run = _start_run(anonymous, "finished after the link lapsed")
    query_run_repository.update_status(run.query_run_id, status_value=QueryRunStatus.COMPLETED)
    account_history.record_finished_run(query_run_repository.get(run.query_run_id))
    assert _questions(_account_id(sign_in)) == []


def test_a_run_still_in_progress_is_not_recorded(sign_in: SignIn) -> None:
    """Turns red if record_finished_run records a run that has not finished."""
    client = sign_in.client()
    _signed_in(client)
    account = _account_id(sign_in)
    running = _start_run(account, "not finished")
    account_history.record_finished_run(running)
    assert _questions(account) == []
    # Positive partner: the same run, once finished, is recorded.
    query_run_repository.update_status(running.query_run_id, status_value=QueryRunStatus.COMPLETED)
    account_history.record_finished_run(query_run_repository.get(running.query_run_id))
    assert _questions(account) == ["not finished"]
