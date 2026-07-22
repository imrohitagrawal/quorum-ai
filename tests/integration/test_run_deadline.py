"""P3: the NFR-004 run-level wall-clock deadline, enforced with honest degrade.

docs/11 pins the budget (NFR-001 "hard timeout at 180 seconds"; NFR-004 "a
completed result or a partial-result explanation within 180 seconds"). Until
this slice NOTHING in ``src/`` bounded total run wall-clock — the only 180s
timer was ``DEBATE_HARD_TIMEOUT_MS``, which merely gates debate round 2.

The contract under test, end to end through the create endpoint:

* A slot that outlives the deadline is cut: the run returns TERMINAL
  ``timed_out`` within ~the deadline (never hanging for the slow slot),
  carrying every slot completed so far; uncollected slots appear as FAILED
  answers with ``error_code="RUN_DEADLINE_EXCEEDED"`` so the "N of 4" math
  stays honest (RB-5: ``live_count`` counts COMPLETED live slots only).
* A breach BETWEEN stages stops before the next stage starts (synthesis is
  never entered after the budget is spent) while preserving completed work.
* DO-NO-HARM: a normal-latency run under the default 180s budget — and under
  a tight-but-sufficient explicit budget — is NEVER cut and completes fully.
* A run already degraded for another reason keeps its own honest label — the
  deadline never relabels or double-degrades it.

Hermetic: local simulation pipeline, no live calls, short test-only deadlines
via the ``quorum_run_deadline_seconds`` setting (monkeypatched, mirroring the
env var ``QUORUM_RUN_DEADLINE_SECONDS``).
"""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.config import settings
from product_app.debate import debate_event_recorder, debate_stub_service
from product_app.main import app
from product_app.providers import (
    provider_event_recorder,
    provider_execution_service,
)
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType
from product_app.synthesis import synthesis_event_recorder, synthesis_stub_service

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]

QUERY_TEXT = "Compare transparent model answers"


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


def _acknowledged_request() -> dict[str, object]:
    return {
        "query_text": QUERY_TEXT,
        "model_slots": DEFAULT_MODEL_IDS,
        "safety_acknowledgements": [
            {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
        ],
    }


def _run(client: TestClient, account_id: Any) -> dict[str, Any]:
    """Create a run (synchronous inline path) and return the served result."""
    response = client.post(
        "/v1/query-runs",
        json=_acknowledged_request(),
        headers={"X-Account-Id": str(account_id)},
    )
    assert response.status_code == 202, response.text
    created: dict[str, Any] = response.json()
    result = client.get(
        f"/v1/query-runs/{created['query_run_id']}",
        headers={"X-Account-Id": str(account_id)},
    )
    assert result.status_code == 200, result.text
    payload: dict[str, Any] = result.json()
    return payload


def _slow_slots(monkeypatch: pytest.MonkeyPatch, slow: set[int], sleep_s: float) -> None:
    """Slots in ``slow`` sleep before answering; the rest answer normally."""
    original = provider_execution_service.produce_initial_answer

    def _maybe_slow(**kwargs: Any) -> Any:
        if kwargs["model_slot"].slot_number in slow:
            time.sleep(sleep_s)
        return original(**kwargs)

    monkeypatch.setattr(provider_execution_service, "produce_initial_answer", _maybe_slow)


# ---------------------------------------------------------------------------
# The breach: a slow slot is cut at the deadline, honestly
# ---------------------------------------------------------------------------


def test_a_slow_slot_degrades_to_a_timed_out_partial_within_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(app)
    account_id = uuid4()
    # Warm the app with one full untimed run first: the FIRST create pays
    # ~1.7s of one-time lazy init (estimation/catalog), which is not run
    # wall-clock and must not skew the deadline measurement. The short
    # deadline and the slow-slot patch land only AFTER the warm-up.
    warm = _run(client, uuid4())
    assert warm["status"] == "completed"
    monkeypatch.setattr(settings, "quorum_run_deadline_seconds", 0.5)
    _slow_slots(monkeypatch, {3, 4}, sleep_s=3.0)
    started = time.perf_counter()
    body = _run(client, account_id)
    elapsed = time.perf_counter() - started

    # Terminal within ~the deadline — never the slow slot's 3s. The served
    # run clock agrees (its elapsed is the run's own, startup-free measure).
    assert body["status"] == "timed_out", body["status"]
    assert elapsed < 2.0, f"run took {elapsed:.2f}s against a 0.5s deadline"
    assert body["elapsed_time_ms"] < 2_000

    # Every slot is accounted for: the fast ones COMPLETED, the cut ones are
    # FAILED with the deadline error code — never silently missing.
    answers = body["result"]["model_answers"]
    assert len(answers) == 4
    by_slot = {a["slot_number"]: a for a in answers}
    assert by_slot[1]["status"] == "completed"
    assert by_slot[2]["status"] == "completed"
    for slot in (3, 4):
        assert by_slot[slot]["status"] == "failed"
        assert by_slot[slot]["error_code"] == "RUN_DEADLINE_EXCEEDED"

    # RB-5 honesty: live_count counts COMPLETED live slots only — the sim
    # pipeline is local, so live stays 0 and the cut slots inflate nothing.
    assert body["live_count"] == 0
    assert body["partial_failure_notice"] is not None
    assert "debate_round_1" in body["missing_steps"]
    assert "synthesis" in body["missing_steps"]


def test_a_breach_before_debate_starts_never_enters_debate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pre-debate checkpoint: answers finished, but the budget is spent
    before debate begins — debate is never entered, answers are served."""
    monkeypatch.setattr(settings, "quorum_run_deadline_seconds", 0.5)
    monkeypatch.setattr(settings, "stage_delay_ms", 800)  # spends the budget

    debate_calls: list[Any] = []
    original_debate = debate_stub_service.run_debate_rounds

    def _spy_debate(**kwargs: Any) -> Any:
        debate_calls.append(kwargs)
        return original_debate(**kwargs)

    monkeypatch.setattr(debate_stub_service, "run_debate_rounds", _spy_debate)

    client = TestClient(app)
    body = _run(client, uuid4())

    assert body["status"] == "timed_out"
    assert debate_calls == [], "debate must never start after the budget is spent"
    answers = body["result"]["model_answers"]
    assert len(answers) == 4
    assert all(a["status"] == "completed" for a in answers)
    assert body["result"]["debate_outputs"] == []
    for step in ("debate_round_1", "debate_round_2", "synthesis"):
        assert step in body["missing_steps"]


def test_a_breach_between_stages_stops_before_synthesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The budget is checked between stages: work that finished is kept, the
    next stage is never entered after the budget is spent."""
    monkeypatch.setattr(settings, "quorum_run_deadline_seconds", 0.5)

    original_debate = debate_stub_service.run_debate_rounds

    def _slow_debate(**kwargs: Any) -> Any:
        time.sleep(0.8)  # spends the whole budget inside debate
        return original_debate(**kwargs)

    monkeypatch.setattr(debate_stub_service, "run_debate_rounds", _slow_debate)

    synthesis_calls: list[Any] = []
    original_synthesis = synthesis_stub_service.produce_final_synthesis

    def _spy_synthesis(**kwargs: Any) -> Any:
        synthesis_calls.append(kwargs)
        return original_synthesis(**kwargs)

    monkeypatch.setattr(synthesis_stub_service, "produce_final_synthesis", _spy_synthesis)

    client = TestClient(app)
    body = _run(client, uuid4())

    assert body["status"] == "timed_out"
    assert synthesis_calls == [], "synthesis must never start after the budget is spent"
    # Completed work is preserved and served.
    answers = body["result"]["model_answers"]
    assert len(answers) == 4
    assert all(a["status"] == "completed" for a in answers)
    assert body["result"]["debate_outputs"], "the finished debate must be served"
    assert "synthesis" in body["missing_steps"]
    assert body["result"]["final_synthesis"] is None


# ---------------------------------------------------------------------------
# DO-NO-HARM: normal runs are never cut
# ---------------------------------------------------------------------------


def test_a_normal_run_under_the_default_deadline_completes_fully() -> None:
    assert settings.quorum_run_deadline_seconds == 180.0
    client = TestClient(app)
    body = _run(client, uuid4())
    assert body["status"] == "completed"
    assert all(a["status"] == "completed" for a in body["result"]["model_answers"])
    assert body["result"]["final_synthesis"] is not None
    assert body["missing_steps"] == []


def test_a_normal_run_under_a_tight_but_sufficient_deadline_is_not_cut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deadline must be a safety net, not a scheduler: a run that fits
    the budget is never cut by the mere existence of the mechanism."""
    monkeypatch.setattr(settings, "quorum_run_deadline_seconds", 30.0)
    client = TestClient(app)
    body = _run(client, uuid4())
    assert body["status"] == "completed"
    assert body["result"]["final_synthesis"] is not None


def test_a_run_degraded_for_another_reason_keeps_its_own_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No double-degrade: a run that is PARTIAL because no answers completed
    keeps that label and detail — the deadline never relabels it."""
    monkeypatch.setattr(settings, "quorum_run_deadline_seconds", 180.0)

    def _all_fail(**kwargs: Any) -> Any:
        raise RuntimeError("provider down")

    monkeypatch.setattr(provider_execution_service, "produce_initial_answer", _all_fail)

    client = TestClient(app)
    body = _run(client, uuid4())
    assert body["status"] == "partial"
    assert body["status"] != "timed_out"


# ---------------------------------------------------------------------------
# Config guard
# ---------------------------------------------------------------------------


def test_a_non_positive_or_non_finite_deadline_is_rejected() -> None:
    from pydantic import ValidationError

    from product_app.config import Settings

    # NaN compares False to BOTH bounds (nan <= 0 and nan > max are False), so
    # it would sail through a pure range check — and a NaN timeout makes
    # ``Future.result`` raise immediately, cutting EVERY run at t=0 (review
    # finding, proven by execution). It must be rejected explicitly.
    for bad in (0, -1, -0.5, 3_601, float("inf"), float("nan")):
        with pytest.raises(ValidationError):
            Settings(quorum_run_deadline_seconds=bad)
    assert Settings(quorum_run_deadline_seconds=3_600).quorum_run_deadline_seconds == 3_600


def test_a_worker_raised_timeout_error_is_not_a_deadline_breach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On Python >=3.11 ``concurrent.futures.TimeoutError`` IS builtin
    ``TimeoutError``, so a TimeoutError raised INSIDE a worker re-raises from
    ``future.result()`` with the same type as a budget expiry. With ~180s of
    budget left it must be treated as that slot's own failure — never
    relabel the whole healthy run as a run-deadline breach."""
    original = provider_execution_service.produce_initial_answer

    def _slot_two_times_out(**kwargs: Any) -> Any:
        if kwargs["model_slot"].slot_number == 2:
            raise TimeoutError("socket timeout escaping a worker")
        return original(**kwargs)

    monkeypatch.setattr(provider_execution_service, "produce_initial_answer", _slot_two_times_out)

    client = TestClient(app)
    body = _run(client, uuid4())

    assert body["status"] != "timed_out", (
        "a worker-raised TimeoutError must not masquerade as a run-deadline breach"
    )
    answers = body["result"]["model_answers"]
    assert not any(a.get("error_code") == "RUN_DEADLINE_EXCEEDED" for a in answers)
    # Pinned CONVENTION (matches every escaped-worker exception, the
    # pre-existing ``except Exception: continue`` path): the raising slot is
    # simply absent from the recorded answers — it is not silently mislabeled
    # as a deadline cut, and the run's own label stays correct.
    assert {a["slot_number"] for a in answers} == {1, 3, 4}


def test_the_deadline_degrade_never_overwrites_a_cancelled_run() -> None:
    """A cancel landing just before the degrade write must win: CANCELLED is
    what the user was told, and a terminal→terminal overwrite would be a
    permanently wrong label."""
    from product_app.costs import cost_estimation_service
    from product_app.model_slots import validate_model_slots_with_search
    from product_app.query_runs import QueryRunStatus

    model_slots = validate_model_slots_with_search(DEFAULT_MODEL_IDS)
    estimate = cost_estimation_service.estimate(query_text=QUERY_TEXT, model_slots=model_slots)
    run = query_run_repository.create(
        account_id=uuid4(),
        query_text=QUERY_TEXT,
        model_slots=model_slots,
        cost_estimate=estimate,
    )
    run.status = QueryRunStatus.CANCELLED

    from product_app import query_runs as qr

    applied = qr._degrade_run_for_deadline(
        run.query_run_id,
        deadline_seconds=180.0,
        stage_name="synthesis",
        failed_steps=[],
        missing_steps=["synthesis"],
    )
    assert applied is False
    assert query_run_repository.get(run.query_run_id).status is QueryRunStatus.CANCELLED
