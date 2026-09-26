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
from product_app.model_slots import DEFAULT_MODEL_IDS, validate_model_slots_with_search
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
    # The shipped default ids: a hard-coded pair failed in the full suite once
    # other tests had replaced the process-global catalog (review).
    ids = list(DEFAULT_MODEL_IDS)[:2]
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
    return [entry.question for entry in account_history.history_for(account_id) or []]


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


def test_signing_in_as_another_account_moves_nothing(sign_in: SignIn) -> None:
    """CRITICAL in review round 1: a browser signed in as A that completes a
    sign-in as B moved A's question into B's history. Turns red if a
    signed-in session's runs are carried over, or a run changes account."""
    from tests.google_token_stub import good_claims

    client = sign_in.client()
    _signed_in(client)
    (row_a,) = sign_in.account_rows()
    account_a = UUID(row_a["account_id"])
    _finish(_start_run(account_a, "A's own question"))
    sign_in.stub.claims = good_claims(sub="108000000000000000002", email="grace@example.com")
    csrf = client.get("/v1/session").json()["csrf_token"]
    query = _start(client, csrf)
    assert _callback(client, code="stub-auth-code-2", state=query["state"]).status_code == 303
    account_b = next(
        UUID(r["account_id"]) for r in sign_in.account_rows() if r["email"] == "grace@example.com"
    )
    assert _questions(account_a) == ["A's own question"]
    assert _questions(account_b) == []
    # No carry-over link either: A's later runs must never be sent to B.
    assert account_a not in account_history._carried
    assert "A&#x27;s own question" not in client.get("/ui").text


def test_the_verdict_the_result_showed_is_kept(sign_in: SignIn) -> None:
    """A panel run's history row carries the agreement caption, in the
    result's own words. Turns red if the verdict is dropped or reworded."""
    from tests.integration.test_quick_verdict_served import _answer

    client = sign_in.client()
    _signed_in(client)
    account = _account_id(sign_in)
    run = _start_run(account, "with a verdict")
    for slot, slot_model in enumerate(run.model_slots, 1):
        query_run_repository.record_initial_answer(
            run.query_run_id, _answer(slot, slot_model.model_id, 2)
        )
    _finish(run)
    (entry,) = account_history.history_for(account) or []
    assert entry.verdict is not None
    assert entry.verdict.endswith(" of 2 opening positions carried into the final answer")
    assert entry.verdict in client.get("/ui").text


def test_a_history_that_cannot_be_read_says_so(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turns red if a read failure is shown as "No questions yet." (review:
    a visitor whose questions are stored was told none are)."""
    client = sign_in.client()
    _signed_in(client)
    monkeypatch.setattr(sign_in.store, "history_for", lambda *a, **k: None)
    html = client.get("/ui").text
    assert "Your history could not be loaded just now." in html
    assert "No questions yet." not in html


def test_the_history_panel_is_reachable_by_keyboard(sign_in: SignIn) -> None:
    """axe: a scroll box a keyboard cannot reach is SERIOUS
    (scrollable-region-focusable). Turns red if the panel loses its tabindex
    or its accessible name."""
    client = sign_in.client()
    _signed_in(client)
    html = client.get("/ui").text
    assert (
        '<div class="account-history-panel" tabindex="0" role="region" '
        'aria-label="Your question history">' in html
    )


def test_the_link_waits_as_long_as_a_run_can_run(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the run deadline raised to 50 minutes, a run finishing 40
    minutes after sign-in still joins. Turns red if the link lasts only the
    30-minute active lifetime."""
    from product_app.config import settings

    monkeypatch.setattr(settings, "quorum_run_deadline_seconds", 3000.0)
    client = sign_in.client()
    csrf = _boot(client)
    anonymous = _session_account(client)
    running = _start_run(anonymous, "a long run")
    query = _start(client, csrf)
    _callback(client, code="stub-auth-code-1", state=query["state"])
    later = datetime.now(UTC) + timedelta(minutes=40)
    monkeypatch.setattr(account_history, "_now", lambda: later)
    query_run_repository.update_status(running.query_run_id, status_value=QueryRunStatus.COMPLETED)
    account_history.record_finished_run(query_run_repository.get(running.query_run_id))
    assert _questions(_account_id(sign_in)) == ["a long run"]


def test_a_failed_run_has_no_verdict(sign_in: SignIn) -> None:
    """Review round 2: a FAILED run showed "2 of 2 carried into the final
    answer" with no final answer. Turns red if a run that did not complete
    gets a verdict."""
    from tests.integration.test_quick_verdict_served import _answer

    client = sign_in.client()
    _signed_in(client)
    account = _account_id(sign_in)
    run = _start_run(account, "a failed run")
    for slot, slot_model in enumerate(run.model_slots, 1):
        query_run_repository.record_initial_answer(
            run.query_run_id, _answer(slot, slot_model.model_id, 2)
        )
    query_run_repository.update_status(run.query_run_id, status_value=QueryRunStatus.FAILED)
    qro._persist_terminal_run(run.query_run_id)
    (entry,) = account_history.history_for(account) or []
    assert entry.status == "failed"
    assert entry.verdict is None


def test_carry_over_fails_closed_when_the_accounts_cannot_be_read(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review round 2: with the accounts lookup failing, carry-over read the
    signed-in session as anonymous and moved its runs. Turns red if a read
    error lets runs move."""
    client = sign_in.client()
    csrf = _boot(client)
    _finish(_start_run(_session_account(client), "must not move on an error"))
    monkeypatch.setattr(sign_in.store, "is_anonymous", lambda _id: None)
    query = _start(client, csrf)
    _callback(client, code="stub-auth-code-1", state=query["state"])
    assert _questions(_account_id(sign_in)) == []
