"""W5, first pull request: the quick-answer request shape, end to end on the API.

The owner's decision (CHG-012 D1): a separate request shape, ``mode: "quick"``,
with the panel validator untouched (two to four), the judge as a priced
``by_stage`` row, and the cost gate kept. This file drives the real routes
with no key configured, so every answer is local simulation and nothing is
billed.

Every test names what turns it red.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.helpers import isolated_run_semaphore, wait_for_free_permits

from product_app import config, run_history_store
from product_app.debate import debate_stub_service
from product_app.main import app
from product_app.model_slots import QUICK_SLOT_MESSAGE, default_model_slots
from product_app.query_run_orchestration import QueryRunStatus
from product_app.safety import WARNING_VERSION, WarningType
from product_app.synthesis import synthesis_stub_service

DEFAULT_IDS = [slot.model_id for slot in default_model_slots()]
RANGE_MESSAGE = "Between 2 and 4 model slots are required."
QUERY = "compare managed database options for a small team"


def _headers(account_id: UUID, csrf: str) -> dict[str, str]:
    return {
        "X-Account-Id": str(account_id),
        "X-CSRF-Token": csrf,
        "Content-Type": "application/json",
    }


def _client_and_headers() -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app)
    response = client.get("/v1/session")
    assert response.status_code == 200
    return client, _headers(uuid4(), cast(str, response.json()["csrf_token"]))


def _estimate(client: TestClient, headers: dict[str, str], body: dict[str, Any]) -> Any:
    return client.post("/v1/query-runs/estimate", headers=headers, json=body)


def test_the_quick_refusal_is_the_wording_clients_see() -> None:
    """Pins the wire wording a client gets for a quick request with other than
    one model (board row W5's needle is the composer sentence, not this).
    RED IF the message is reworded without deciding to."""
    assert QUICK_SLOT_MESSAGE == "A quick answer takes exactly one model."


def test_a_quick_estimate_prices_one_answer_and_no_debate_or_synthesis() -> None:
    """RED before this change (the one slot is refused with the range
    message). RED IF a debate or synthesis row, or the writer row, appears on
    a quick estimate, if the partitions stop summing to the total, or if the
    bound drops below the point estimate."""
    client, headers = _client_and_headers()
    response = _estimate(
        client, headers, {"query_text": QUERY, "model_slots": DEFAULT_IDS[:1], "mode": "quick"}
    )
    assert response.status_code == 200, response.text
    estimate = response.json()["cost_estimate"]
    breakdown = estimate["breakdown"]
    # No judge is configured in the suite, so the one row is the answer.
    assert [row["stage"] for row in breakdown["by_stage"]] == ["initial_answers"]
    assert [row["kind"] for row in breakdown["by_model"]] == ["model"]
    total = Decimal(str(breakdown["total"]))
    assert sum(Decimal(str(r["usd"])) for r in breakdown["by_stage"]) == total
    assert sum(Decimal(str(r["usd"])) for r in breakdown["by_model"]) == total
    point = Decimal(str(estimate["estimated_cost_usd"]))
    bound = Decimal(str(estimate["max_cost_usd"]))
    assert Decimal(0) < point <= bound
    # Positive partner: the same model in a PANEL prices four stage rows and
    # more money, so the quick shape is not a relabelled panel.
    panel = _estimate(client, headers, {"query_text": QUERY, "model_slots": DEFAULT_IDS[:2]})
    assert panel.status_code == 200, panel.text
    panel_estimate = panel.json()["cost_estimate"]
    assert [row["stage"] for row in panel_estimate["breakdown"]["by_stage"]] == [
        "initial_answers",
        "debate_round_1",
        "debate_round_2",
        "synthesis",
    ]
    assert Decimal(str(panel_estimate["estimated_cost_usd"])) > point


@pytest.mark.parametrize("count", [2, 4])
def test_quick_refuses_more_than_one_model_with_its_own_message(count: int) -> None:
    """RED IF quick accepts a panel, or answers with the panel's range message."""
    client, headers = _client_and_headers()
    response = _estimate(
        client, headers, {"query_text": QUERY, "model_slots": DEFAULT_IDS[:count], "mode": "quick"}
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "INVALID_MODEL_SLOT"
    assert [e["message"] for e in detail["slot_errors"]] == [QUICK_SLOT_MESSAGE]


def test_the_panel_validator_is_untouched() -> None:
    """RED IF the quick shape widened the panel: one model without ``mode``,
    and with ``mode: "panel"``, is still refused with the range message."""
    client, headers = _client_and_headers()
    for body in (
        {"query_text": QUERY, "model_slots": DEFAULT_IDS[:1]},
        {"query_text": QUERY, "model_slots": DEFAULT_IDS[:1], "mode": "panel"},
    ):
        response = _estimate(client, headers, body)
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["slot_errors"][0]["message"] == RANGE_MESSAGE


def test_an_unknown_mode_is_refused() -> None:
    """RED IF ``mode`` is a free string (a typo would silently price a panel)."""
    client, headers = _client_and_headers()
    response = _estimate(
        client, headers, {"query_text": QUERY, "model_slots": DEFAULT_IDS[:2], "mode": "fast"}
    )
    assert response.status_code == 422, response.text


def test_a_quick_quote_is_not_a_panel_quote_for_the_same_model() -> None:
    """The estimate and the create price the same shape (the shared base).
    RED IF ``mode`` lives on only one of the two request models."""
    from product_app.query_runs import QueryRunCreateRequest, QueryRunEstimateRequest

    assert "mode" in QueryRunEstimateRequest.model_fields
    assert "mode" in QueryRunCreateRequest.model_fields
    assert QueryRunEstimateRequest.model_fields["mode"].default == "panel"


def test_a_quick_run_answers_once_skips_debate_and_synthesis_and_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED before this change at the create call (422), and after it if the
    run path calls the debate or synthesis service (the spies count them),
    reaches a crash on ``panel_size_word(1)``, or ends anything but
    ``completed``. The skipped stages are stamped ``skipped`` with the quick
    detail; no agreement figure is served (owner, 2026-09-24)."""
    monkeypatch.setattr(config.settings, "stage_delay_ms", 0)
    calls = {"debate": 0, "synthesis": 0}

    def no_debate(*args: Any, **kwargs: Any) -> Any:
        calls["debate"] += 1
        raise AssertionError("a quick run must not debate")

    def no_synthesis(*args: Any, **kwargs: Any) -> Any:
        calls["synthesis"] += 1
        raise AssertionError("a quick run must not synthesise")

    monkeypatch.setattr(debate_stub_service, "run_debate_rounds", no_debate)
    monkeypatch.setattr(synthesis_stub_service, "produce_final_synthesis", no_synthesis)

    with run_history_store.configure_for_tests() as store, isolated_run_semaphore(1) as semaphore:
        client, headers = _client_and_headers()
        body: dict[str, Any] = {
            "query_text": QUERY,
            "model_slots": DEFAULT_IDS[:1],
            "mode": "quick",
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
                {"warning_type": WarningType.HIGH_STAKES, "version": WARNING_VERSION},
            ],
        }
        estimate = _estimate(client, headers, body)
        assert estimate.status_code == 200, estimate.text
        cost_estimate = estimate.json()["cost_estimate"]
        if cost_estimate["threshold_action"] == "require_confirmation":
            body["cost_confirmation"] = {
                "estimated_cost_usd": cost_estimate["estimated_cost_usd"],
                "confirmation_token": cost_estimate["confirmation_token"],
            }
        created = client.post("/v1/query-runs", headers=headers, json=body)
        assert created.status_code == 202, created.text
        assert created.json()["mode"] == "quick"
        query_run_id = created.json()["query_run_id"]
        assert wait_for_free_permits(semaphore, 1, timeout_s=60.0) == 1
        polled = client.get(f"/v1/query-runs/{query_run_id}", headers=headers)
        assert polled.status_code == 200, polled.text
        payload = polled.json()
        # The durable row is written (its persistence swallows errors, so a
        # crash on the ``None`` agreement would be silent without this) and
        # stores "no agreement measured", not "1 of 1".
        row = store.get(str(query_run_id))
        assert row is not None
        assert (row.agreement_aligned, row.agreement_total) == (0, 0)
        assert row.model_ids == DEFAULT_IDS[:1]
        # No evaluation is persisted for a quick run until its trust shape
        # exists (ADR-0126); the panel test below is the positive partner.
        assert row.eval_json is None and row.trust_json is None

    assert payload["status"] == "completed", payload
    assert payload["mode"] == "quick"
    assert calls == {"debate": 0, "synthesis": 0}
    assert len(payload["result"]["model_answers"]) == 1
    assert payload["result"]["debate_outputs"] == []
    assert payload["result"]["final_synthesis"] is None
    assert payload["result"]["agreement"] is None
    assert payload["result"]["position_movements"] == []
    # No served evaluation until W5's second pull request gives a quick
    # answer its own trust shape (ADR-0126).
    assert payload["evaluation"] is None
    stages = {s["stage"]: s for s in payload["progress"]["stages"]}
    assert stages["initial_answers"]["state"] == "completed"
    for name in ("debate_round_1", "debate_round_2", "synthesis"):
        assert stages[name]["state"] == "skipped", stages[name]
        assert stages[name]["detail"] == "Not part of a quick answer."
    assert payload["failed_steps"] == [] and payload["missing_steps"] == []
    assert payload["partial_failure_notice"] is None


def test_a_panel_run_still_reports_mode_panel_and_an_agreement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positive partner of the quick run: RED IF ``agreement`` is dropped for
    panels too, or a panel is labelled quick."""
    monkeypatch.setattr(config.settings, "stage_delay_ms", 0)
    with run_history_store.configure_for_tests() as store, isolated_run_semaphore(1) as semaphore:
        client, headers = _client_and_headers()
        body: dict[str, Any] = {
            "query_text": QUERY,
            "model_slots": DEFAULT_IDS[:2],
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
                {"warning_type": WarningType.HIGH_STAKES, "version": WARNING_VERSION},
            ],
        }
        estimate = _estimate(client, headers, body).json()["cost_estimate"]
        if estimate["threshold_action"] == "require_confirmation":
            body["cost_confirmation"] = {
                "estimated_cost_usd": estimate["estimated_cost_usd"],
                "confirmation_token": estimate["confirmation_token"],
            }
        created = client.post("/v1/query-runs", headers=headers, json=body)
        assert created.status_code == 202, created.text
        assert wait_for_free_permits(semaphore, 1, timeout_s=60.0) == 1
        deadline = time.monotonic() + 30
        payload: dict[str, Any] = {}
        while time.monotonic() < deadline:
            payload = client.get(
                f"/v1/query-runs/{created.json()['query_run_id']}", headers=headers
            ).json()
            if payload["status"] in {"completed", "failed", "partial", "cancelled"}:
                break
            time.sleep(0.05)
        row = store.get(str(created.json()["query_run_id"]))
    assert payload["status"] == "completed", payload
    assert payload["mode"] == "panel"
    assert row is not None and row.eval_json is not None
    assert row.agreement_total == 2
    assert payload["result"]["agreement"]["total"] == 2
    # Partner of the quick run's ``evaluation is None``: a panel still serves one.
    assert payload["evaluation"] is not None


def test_a_quick_run_whose_one_answer_fails_ends_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    """The quick branch sits AFTER the no-usable-answer check, so a failed
    answer ends ``partial`` like a panel with no answers, never ``completed``
    with nothing in it. RED IF the quick branch is moved above that check.
    Uses the LOCAL-only failure seam; nothing is dispatched."""
    monkeypatch.setattr(config.settings, "stage_delay_ms", 0)
    with isolated_run_semaphore(1) as semaphore:
        client, headers = _client_and_headers()
        body: dict[str, Any] = {
            "query_text": "force provider failure on this quick question",
            "model_slots": DEFAULT_IDS[:1],
            "mode": "quick",
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
                {"warning_type": WarningType.HIGH_STAKES, "version": WARNING_VERSION},
            ],
        }
        created = client.post("/v1/query-runs", headers=headers, json=body)
        assert created.status_code == 202, created.text
        assert wait_for_free_permits(semaphore, 1, timeout_s=60.0) == 1
        payload = client.get(
            f"/v1/query-runs/{created.json()['query_run_id']}", headers=headers
        ).json()
    assert payload["status"] == "partial", payload
    stages = {s["stage"]: s for s in payload["progress"]["stages"]}
    assert stages["initial_answers"]["state"] == "failed"
    # RED IF a failed quick answer reports debate and synthesis as failed or
    # missing, or tells the user to review "the synthesis" (review round 1).
    for name in ("debate_round_1", "debate_round_2", "synthesis"):
        assert stages[name]["state"] == "skipped", stages[name]
        assert stages[name]["detail"] == "Not part of a quick answer."
    assert payload["failed_steps"] == ["initial_answers"]
    assert payload["missing_steps"] == []
    assert payload["partial_failure_notice"] == (
        "This quick answer did not complete. Review the failed step before relying on it."
    )


def test_a_quick_request_with_follow_up_context_is_refused() -> None:
    """Follow-up context is priced into and sent to debate and synthesis only,
    which a quick answer does not run. RED IF it is accepted (review round 1:
    it was, priced at $0 and never sent). Partner: a panel still takes it, and
    a quick request with an empty context is still accepted."""
    client, headers = _client_and_headers()
    context = {"prior_question": "What is a database?", "prior_synthesis": "A store."}
    quick = _estimate(
        client,
        headers,
        {"query_text": QUERY, "model_slots": DEFAULT_IDS[:1], "mode": "quick", "context": context},
    )
    assert quick.status_code == 422, quick.text
    assert "A quick answer takes no follow-up context." in quick.text
    panel = _estimate(
        client, headers, {"query_text": QUERY, "model_slots": DEFAULT_IDS[:2], "context": context}
    )
    assert panel.status_code == 200, panel.text
    empty = _estimate(
        client,
        headers,
        {
            "query_text": QUERY,
            "model_slots": DEFAULT_IDS[:1],
            "mode": "quick",
            "context": {"prior_question": " ", "prior_synthesis": None},
        },
    )
    assert empty.status_code == 200, empty.text


def test_the_active_run_reports_its_mode() -> None:
    """RED IF ``/active`` drops ``mode`` (a resuming client would have to guess
    the shape from the slot count). No active run reports ``None``."""
    from decimal import Decimal

    from product_app.costs import CostEstimate, CostThresholdAction
    from product_app.model_slots import validate_model_slots_with_search
    from product_app.query_run_orchestration import query_run_repository

    # No session cookie: the account is the header's (the pattern
    # ``test_query_run_active_rule.py`` uses), so the run below is this one's.
    client = TestClient(app)
    account_id = uuid4()
    headers = {"X-Account-Id": str(account_id)}
    none = client.get("/v1/query-runs/active", headers=headers)
    assert none.status_code == 200 and none.json()["mode"] is None
    run = query_run_repository.create(
        account_id=account_id,
        query_text=QUERY,
        model_slots=validate_model_slots_with_search(DEFAULT_IDS[:1], mode="quick"),
        cost_estimate=CostEstimate(
            estimated_cost_usd=Decimal("0.0100"),
            threshold_action=CostThresholdAction.ALLOW,
            confirmation_token=None,
            reasons=[],
        ),
        mode="quick",
    )
    try:
        active = client.get("/v1/query-runs/active", headers=headers)
        assert active.status_code == 200, active.text
        assert active.json()["query_run_id"] == str(run.query_run_id)
        assert active.json()["mode"] == "quick"
    finally:
        query_run_repository.transition(run.query_run_id, QueryRunStatus.CANCELLED)
