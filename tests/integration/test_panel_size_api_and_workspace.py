"""W4, second pull request: the API accepts two or three slots; the workspace ships the control.

ADR-0120 decision 6 keeps the count check in the domain validator, so this
file drives the real routes: ``POST /v1/query-runs/estimate`` and
``POST /v1/query-runs`` with two and three slots (accepted, $0: no key, so
every answer is local simulation), and with five (refused with the typed
``INVALID_MODEL_SLOT`` envelope and the new message). It also pins that the
orchestrator hands the REQUESTED panel size to the debate and synthesis
services, and that ``/ui`` serves the add control hidden at the default four.

Every test names what turns it red.
"""

from __future__ import annotations

import time
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.helpers import isolated_run_semaphore, wait_for_free_permits

from product_app import config
from product_app.debate import debate_stub_service
from product_app.main import app
from product_app.model_slots import default_model_slots
from product_app.query_run_orchestration import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType
from product_app.synthesis import synthesis_stub_service

DEFAULT_IDS = [slot.model_id for slot in default_model_slots()]
RANGE_MESSAGE = "Between 2 and 4 model slots are required."


def _headers(account_id: UUID, csrf: str) -> dict[str, str]:
    return {
        "X-Account-Id": str(account_id),
        "X-CSRF-Token": csrf,
        "Content-Type": "application/json",
    }


def _session_csrf(client: TestClient) -> str:
    response = client.get("/v1/session")
    assert response.status_code == 200
    return cast(str, response.json()["csrf_token"])


def _create_body(model_slots: list[str]) -> dict[str, Any]:
    return {
        "query_text": "compare managed database options for a small team",
        "model_slots": model_slots,
        "safety_acknowledgements": [
            {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
            {"warning_type": WarningType.HIGH_STAKES, "version": WARNING_VERSION},
        ],
    }


@pytest.mark.parametrize("count", [2, 3])
def test_estimate_accepts_two_and_three_slots_and_prices_them(count: int) -> None:
    """RED before this change: the validator refused anything but four.
    The stage rows that scale with N (initial answers) must be strictly
    cheaper than the four-slot estimate, so the price is N-relative, not
    a relabelled four."""
    client = TestClient(app)
    csrf = _session_csrf(client)
    headers = _headers(uuid4(), csrf)
    small = client.post(
        "/v1/query-runs/estimate",
        headers=headers,
        json={"query_text": "compare managed database options", "model_slots": DEFAULT_IDS[:count]},
    )
    assert small.status_code == 200, small.text
    full = client.post(
        "/v1/query-runs/estimate",
        headers=headers,
        json={"query_text": "compare managed database options", "model_slots": DEFAULT_IDS},
    )
    assert full.status_code == 200, full.text
    assert [slot["slot_number"] for slot in small.json()["model_slots"]] == list(
        range(1, count + 1)
    )
    small_usd = float(small.json()["cost_estimate"]["estimated_cost_usd"])
    full_usd = float(full.json()["cost_estimate"]["estimated_cost_usd"])
    assert 0 < small_usd < full_usd


@pytest.mark.parametrize("count", [1, 5])
def test_estimate_refuses_one_and_five_slots_with_the_range_message(count: int) -> None:
    """RED if the count check is dropped (five accepted) or the message keeps
    saying "Exactly four". The envelope stays the typed one (decision 6)."""
    client = TestClient(app)
    csrf = _session_csrf(client)
    ids = (DEFAULT_IDS + ["mistralai/mistral-small"])[:count]
    response = client.post(
        "/v1/query-runs/estimate",
        headers=_headers(uuid4(), csrf),
        json={"query_text": "compare managed database options", "model_slots": ids},
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "INVALID_MODEL_SLOT"
    assert detail["slot_errors"][0]["slot_number"] == 0
    assert detail["slot_errors"][0]["message"] == RANGE_MESSAGE


def test_a_two_slot_run_is_created_and_the_requested_size_reaches_debate_and_synthesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED before this change at the create call (422). RED if the orchestrator
    stops passing ``panel_size`` (both captures stay ``None``) or passes the
    recorded answer count instead of the requested one.

    No key is configured, so every answer is local simulation and nothing is
    billed; the run is $0."""
    monkeypatch.setattr(config.settings, "stage_delay_ms", 0)
    captured: dict[str, int | None] = {"debate": None, "synthesis": None}
    real_debate = debate_stub_service.run_debate_rounds
    real_synthesis = synthesis_stub_service.produce_final_synthesis

    def spy_debate(*args: Any, **kwargs: Any) -> Any:
        captured["debate"] = kwargs.get("panel_size")
        return real_debate(*args, **kwargs)

    def spy_synthesis(*args: Any, **kwargs: Any) -> Any:
        captured["synthesis"] = kwargs.get("panel_size")
        return real_synthesis(*args, **kwargs)

    monkeypatch.setattr(debate_stub_service, "run_debate_rounds", spy_debate)
    monkeypatch.setattr(synthesis_stub_service, "produce_final_synthesis", spy_synthesis)
    # The live stage strip renders every ``detail`` the orchestrator writes
    # beside "N/M answers"; the running detail is overwritten on completion, so
    # it is captured at the repository write rather than read back later.
    # Review round 1 found it still said "Running four initial model calls."
    details: list[str] = []
    real_update_status = query_run_repository.update_status

    def spy_update_status(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("detail"):
            details.append(str(kwargs["detail"]))
        return real_update_status(*args, **kwargs)

    monkeypatch.setattr(query_run_repository, "update_status", spy_update_status)

    with isolated_run_semaphore(1) as semaphore:
        client = TestClient(app)
        csrf = _session_csrf(client)
        headers = _headers(uuid4(), csrf)
        estimate = client.post(
            "/v1/query-runs/estimate",
            headers=headers,
            json={"query_text": _create_body([])["query_text"], "model_slots": DEFAULT_IDS[:2]},
        )
        assert estimate.status_code == 200, estimate.text
        body = _create_body(DEFAULT_IDS[:2])
        cost_estimate = estimate.json()["cost_estimate"]
        if cost_estimate["threshold_action"] == "require_confirmation":
            body["cost_confirmation"] = {
                "estimated_cost_usd": cost_estimate["estimated_cost_usd"],
                "confirmation_token": cost_estimate["confirmation_token"],
            }
        created = client.post("/v1/query-runs", headers=headers, json=body)
        assert created.status_code == 202, created.text
        query_run_id = created.json()["query_run_id"]
        assert wait_for_free_permits(semaphore, 1, timeout_s=60.0) == 1

        deadline = time.monotonic() + 30
        status = ""
        payload: dict[str, Any] = {}
        while time.monotonic() < deadline:
            polled = client.get(f"/v1/query-runs/{query_run_id}", headers=headers)
            assert polled.status_code == 200, polled.text
            payload = polled.json()
            status = str(payload["status"])
            if status in {"completed", "failed", "partial", "cancelled"}:
                break
            time.sleep(0.05)
        assert status == "completed", payload

    assert captured == {"debate": 2, "synthesis": 2}
    assert [slot["slot_number"] for slot in payload["model_slots"]] == [1, 2]
    assert len(payload["result"]["model_answers"]) == 2
    # RED if the stage detail hard-codes "four" (it did until review round 1).
    assert "Running two initial model calls." in details
    assert not any("four" in detail for detail in details), details


def test_workspace_serves_four_slots_the_hidden_add_control_and_the_range_copy() -> None:
    """RED if the template drops the default four, ships the add control
    visible at four, or keeps the "Four model slots" legend."""
    client = TestClient(app)
    html = client.get("/ui").text
    assert html.count("data-model-slot=") == 4
    assert '<button type="button" id="model-slot-add" class="model-slot-add" hidden>' in html
    assert "<legend>Model slots</legend>" in html
    assert "Choose two to four different models." in html
    assert "Four model slots" not in html
    assert 'id="cost-gate-question-meta"' in html
