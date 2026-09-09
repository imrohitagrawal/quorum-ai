"""ADR-0108: round 2 is marked RUNNING while it runs, not after it finished.

THE DEFECT. ``run_debate_rounds`` executes BOTH rounds inside one call, so the
orchestrator could only move the stage markers around it: it marked
``debate_round_1`` RUNNING, made the call, and then fired round 1 COMPLETED,
round 2 RUNNING and round 2 COMPLETED in a burst on return. The burst is
``settings.stage_delay_ms`` wide -- 5 ms by default -- against ``app.js``'s
750 ms poll, so "round 2 is running" was a state the UI essentially could not
observe, and the round it describes had already finished by the time it was
announced.

WHY THIS FILE EXISTS AT ALL. Nothing in the suite observed the ORDER or TIMING
of these transitions -- every existing assertion reads the run's FINAL state or
a single seeded snapshot, so a build that never marked ``debate_round_2``
RUNNING at all would have been green everywhere. Verified by grep over
``debate_round_1|debate_round_2`` across tests/: every hit is about
``missing_steps``/``failed_steps``, terminal-write refusal, enum membership or
cost telemetry. The fix would otherwise have shipped with no bite-proof.

WHAT TURNS THESE RED: deleting the ``on_round_two_start`` callback from
``debate.py``'s seam, or the orchestrator ceasing to pass ``_announce_round_two``.

Hermetic: local simulation, no live calls.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.config import RuntimeEnvironment, settings
from product_app.debate import debate_event_recorder, debate_stub_service
from product_app.main import app
from product_app.providers import provider_event_recorder
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType
from product_app.synthesis import synthesis_event_recorder

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", False)
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", "")
    monkeypatch.setattr(settings, "stage_delay_ms", 0)


@pytest.fixture(autouse=True)
def _clear_state() -> None:
    query_run_repository.clear()
    provider_event_recorder.clear()
    debate_event_recorder.clear()
    synthesis_event_recorder.clear()


def _stages(query_run_id: UUID) -> dict[str, str]:
    run = query_run_repository.get(query_run_id)
    return {s.stage: str(s.state) for s in run.progress}


def _drive(
    client: TestClient, *, query: str = "Compare transparent model answers"
) -> tuple[UUID, dict[str, Any]]:
    """Create a run and return (query_run_id, final body)."""
    headers = {"X-Account-Id": str(uuid4())}
    created = client.post(
        "/v1/query-runs",
        json={
            "query_text": query,
            "model_slots": DEFAULT_MODEL_IDS,
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
            ],
        },
        headers=headers,
    )
    if created.status_code == 402:  # cost confirmation round-trip
        token = created.json()["detail"]["confirmation_token"]
        created = client.post(
            "/v1/query-runs",
            json={
                "query_text": query,
                "model_slots": DEFAULT_MODEL_IDS,
                "safety_acknowledgements": [
                    {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
                ],
                "cost_confirmation": {"confirmation_token": token},
            },
            headers=headers,
        )
    assert created.status_code in (200, 201, 202), created.text
    run_id = UUID(created.json()["query_run_id"])
    body = client.get(f"/v1/query-runs/{run_id}", headers=headers).json()
    return run_id, body


def test_round_two_is_running_while_it_runs_not_after_it_finished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED WHEN: the round-boundary callback stops firing.

    Three snapshots, taken from inside the debate call rather than after it.
    The middle one is the whole point: at the instant round 2 is dispatched,
    round 1 must already read COMPLETED and round 2 must read RUNNING.
    """
    at_entry: dict[str, str] = {}
    at_boundary: dict[str, str] = {}
    original = debate_stub_service.run_debate_rounds

    def _spy(**kwargs: Any) -> Any:
        run_id = kwargs["query_run_id"]
        at_entry.update(_stages(run_id))
        inner = kwargs.get("on_round_two_start")

        def _wrapped() -> None:
            if inner is not None:
                inner()
            # Snapshot AFTER the announcement and BEFORE round 2 is dispatched.
            at_boundary.update(_stages(run_id))

        kwargs["on_round_two_start"] = _wrapped
        return original(**kwargs)

    monkeypatch.setattr(debate_stub_service, "run_debate_rounds", _spy)

    client = TestClient(app)
    run_id, body = _drive(client)

    # Positive partner FIRST: the snapshots must have been taken at all, and
    # the run must have actually reached round 2. Without this, every
    # assertion below is satisfied by an empty dict.
    assert at_entry, "the debate call was never made — nothing below measures anything"
    assert at_boundary, "the round-two boundary never fired"
    assert body["status"] == "completed", body.get("status")

    # ON ENTRY: round 1 is running, round 2 has not started.
    assert at_entry["debate_round_1"] == "running", at_entry
    assert at_entry["debate_round_2"] == "pending", at_entry

    # AT THE BOUNDARY: this is the state the old code could never show.
    assert at_boundary["debate_round_1"] == "completed", at_boundary
    assert at_boundary["debate_round_2"] == "running", at_boundary

    # AND AFTER: both completed, so the fix did not simply strand round 2 in
    # "running" — which would be the defect in the other direction.
    final = _stages(run_id)
    assert final["debate_round_1"] == "completed", final
    assert final["debate_round_2"] == "completed", final


def test_a_skipped_round_two_is_never_announced_as_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED WHEN: the callback is moved ABOVE the round-two skip gate.

    The seam sits AFTER ``_should_skip_round_two``. Placed before it, a run
    whose debate budget was already spent would announce a round that never
    ran -- reporting work the user was never given. That is why the callback is
    not simply fired when round 1 ends.

    NOTE ON THIS TEST'S OWN HISTORY: the first version asserted inside
    ``if "debate_round_2" in body["missing_steps"]`` and used the phrase
    "skip round two please", which is not the trigger. The real knob is
    ``"force debate timeout"`` and it is gated to
    ``runtime_environment=LOCAL``. So the guard never entered and the test
    passed over nothing. It asserts unconditionally now, and the skip is
    verified as a precondition before the absence is asserted.
    """
    announced: list[str] = []
    original = debate_stub_service.run_debate_rounds
    monkeypatch.setattr(settings, "runtime_environment", RuntimeEnvironment.LOCAL)

    def _spy(**kwargs: Any) -> Any:
        inner = kwargs.get("on_round_two_start")

        def _wrapped() -> None:
            announced.append("fired")
            if inner is not None:
                inner()

        kwargs["on_round_two_start"] = _wrapped
        return original(**kwargs)

    monkeypatch.setattr(debate_stub_service, "run_debate_rounds", _spy)

    client = TestClient(app)
    run_id, body = _drive(client, query="force debate timeout on this run")

    # PRECONDITION, asserted not assumed: this run really did skip round 2.
    # Without it the absence below is measured over a run that never tried.
    assert "debate_round_2" in body.get("missing_steps", []), (
        f"the skip path was not taken; missing_steps={body.get('missing_steps')!r} "
        f"status={body.get('status')!r}"
    )
    assert announced == [], "round 2 was skipped, but the boundary announced it as started"
    stages = _stages(run_id)
    assert stages["debate_round_2"] != "running", stages
