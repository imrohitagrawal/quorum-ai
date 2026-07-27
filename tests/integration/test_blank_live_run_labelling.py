"""F-06 end-to-end: what a longer usage list must NOT change about the labels.

The fix makes ``debate_call_usages`` / ``synthesis_call_usages`` longer — a
dispatched-but-unusable call now records an entry where it previously recorded
nothing. Two families of consumer read those lists, and only one of them may
move:

* the COST provenance (``cost_source`` / ``actual_cost_usd`` /
  ``actual_breakdown``) — this is the whole point of the fix and it moves;
* every LIVENESS / degraded-banner signal (``live_count``, ``local_count``,
  ``demo_mode``) plus the served prose, ``failed_steps`` and ``missing_steps``
  — these must be untouched. A run whose seven debate/synthesis calls all came
  back blank served TEMPLATED prose, and nothing about a longer usage list may
  present it as live.

Drives the REAL create→terminal pipeline; the only fakes are the initial-slot
producer and the ``call_with_prompt`` seam, so no network and no cost.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from product_app import config, run_history_store
from product_app.main import app
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    LiveProviderResult,
    ProviderPath,
    SourceReference,
    TokenUsage,
    provider_execution_service,
)
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType

MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]
_USAGE = TokenUsage(prompt_tokens=4000, completion_tokens=700, total_tokens=4700)


@pytest.fixture(autouse=True)
def _clear_runs() -> None:
    query_run_repository.clear()


def _captured_answer(slot: Any) -> InitialModelAnswer:
    """A slot that PASSES the strict ``initial_fully_captured`` gate."""
    return InitialModelAnswer(
        slot_number=slot.slot_number,
        model_id=slot.model_id,
        display_name=slot.model_id,
        answer_text=(
            "The reviewed evidence supports the conclusion, with one caveat "
            "recorded against the second source."
        ),
        sources=[
            SourceReference(
                title="Primary source",
                url="https://example.com/a",
                provider=ProviderPath.OPENROUTER_SEARCH,
            )
        ],
        provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
        provider_path=ProviderPath.OPENROUTER_SEARCH,
        fallback_used=False,
        status=InitialAnswerStatus.COMPLETED,
        latency_ms=11,
        citation_coverage=CitationCoverage(
            answer_count=2,
            sourced_answer_count=2,
            sourced_answer_ratio=Decimal("1"),
            target_met=True,
        ),
        token_usage=TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500),
    )


_Seam = Callable[[dict[str, Any]], "LiveProviderResult | None"]


def _install(monkeypatch: pytest.MonkeyPatch, seam: _Seam) -> list[dict[str, Any]]:
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    monkeypatch.setattr(config.settings, "openrouter_api_key", "sk-or-test", raising=False)
    monkeypatch.setattr(config.settings, "stage_delay_ms", 0, raising=False)

    def _initial(*args: Any, **kwargs: Any) -> InitialModelAnswer:
        slot = kwargs.get("model_slot") or args[-1]
        return _captured_answer(slot)

    monkeypatch.setattr(provider_execution_service, "produce_initial_answer", _initial)

    calls: list[dict[str, Any]] = []

    def _seam(**kwargs: Any) -> LiveProviderResult | None:
        calls.append(kwargs)
        return seam(kwargs)

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", _seam)
    return calls


def _drive(client: TestClient) -> dict[str, Any]:
    account_id = uuid4()
    create = client.post(
        "/v1/query-runs",
        json={
            "query_text": "Compare durable storage options for a small team",
            "model_slots": MODEL_IDS,
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
            ],
        },
        headers={"X-Account-Id": str(account_id)},
    )
    assert create.status_code in (200, 201, 202), create.text[:400]
    run_id = UUID(create.json()["query_run_id"])
    body: dict[str, Any] = client.get(
        f"/v1/query-runs/{run_id}", headers={"X-Account-Id": str(account_id)}
    ).json()
    body["_run_id"] = str(run_id)
    return body


def _synthesis_sections(body: dict[str, Any]) -> list[tuple[str, str]]:
    final = body["result"]["final_synthesis"]
    return [
        (key, final[key])
        for key in ("consensus", "disagreement", "source_support", "uncertainty", "recommendation")
    ]


def test_all_seven_calls_blank_but_billed_is_priced_yet_never_labelled_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seven billed calls, zero usable words: measured cost, templated prose."""
    calls = _install(
        monkeypatch,
        lambda _kwargs: LiveProviderResult(answer_text="", sources=[], usage=_USAGE),
    )
    with run_history_store.configure_for_tests() as store:
        body = _drive(TestClient(app))

        assert len(calls) == 7, "2 debate rounds + 5 synthesis sections"
        assert body["status"] == "completed"

        # COST: every billed call reported usage, so the receipt is measured
        # and the debate/synthesis dollars are actually in it.
        assert body["cost_source"] == "measured"
        stages = {
            line["stage"]: Decimal(str(line["usd"]))
            for line in body["actual_breakdown"]["by_stage"]
        }
        assert stages["debate_round_1"] > 0
        assert stages["debate_round_2"] > 0
        assert stages["synthesis"] > 0

        # LIVENESS: unchanged, and derived from the INITIAL slots only.
        assert body["live_count"] == 4
        assert body["local_count"] == 0
        assert body["demo_mode"] is False
        assert body["failed_steps"] == []
        assert body["missing_steps"] == []

        # PROSE: nothing live was usable, so everything served is templated.
        rounds = body["result"]["debate_outputs"]
        assert [r["round_number"] for r in rounds] == [1, 2]
        assert rounds[0]["critique_text"].startswith("Round 1 critique.")
        assert rounds[1]["critique_text"].startswith("Round 2 critique, refining round 1.")
        # WP-A moved templated-vs-live provenance out of the prose and into
        # ``FinalSynthesis.synthesis_mode``; ``TEMPLATED_FALLBACK_PREFIX`` is now
        # "" so a startswith() check on it is vacuous in the positive form and
        # unsatisfiable in the negative. Assert the structural signal instead.
        assert body["result"]["final_synthesis"]["synthesis_mode"] != "live"

        # The durable row matches what the user was served.
        row = store.get(body["_run_id"])
        assert row is not None
        assert row.cost_source == "measured"
        assert row.actual_cost_usd == Decimal(str(body["actual_cost_usd"]))
        assert row.live_count == 4
        assert row.demo_mode is False


def test_all_seven_calls_unmeasurable_downgrades_cost_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same run without usage: only ``cost_source`` moves."""
    calls = _install(
        monkeypatch,
        lambda _kwargs: LiveProviderResult(answer_text="", sources=[], usage=None),
    )
    with run_history_store.configure_for_tests() as store:
        body = _drive(TestClient(app))

        assert len(calls) == 7
        assert body["cost_source"] == "estimated", "a charge we cannot price is not a measurement"
        assert body["live_count"] == 4
        assert body["local_count"] == 0
        assert body["demo_mode"] is False
        assert body["failed_steps"] == []
        # WP-A moved templated-vs-live provenance out of the prose and into
        # ``FinalSynthesis.synthesis_mode``; ``TEMPLATED_FALLBACK_PREFIX`` is now
        # "" so a startswith() check on it is vacuous in the positive form and
        # unsatisfiable in the negative. Assert the structural signal instead.
        assert body["result"]["final_synthesis"]["synthesis_mode"] != "live"

        row = store.get(body["_run_id"])
        assert row is not None
        assert row.cost_source == "estimated"
        assert row.live_count == 4


def test_unbilled_failure_keeps_the_receipt_measured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FINDING B end-to-end: ``None`` from the seam records nothing.

    ec5c853 recorded an entry for every dispatched call regardless of whether
    it could have been billed, so a stale model id (HTTP 404, nothing
    inferred) downgraded an otherwise perfectly measurable run and inflated the
    SERVED figure to the pre-run estimate. ``None`` now means "not billed".
    """
    _install(monkeypatch, lambda _kwargs: None)
    body = _drive(TestClient(app))

    run = query_run_repository.get(UUID(body["_run_id"]))
    assert run.debate_call_usages == []
    assert run.synthesis_call_usages == []
    assert body["cost_source"] == "measured"
    # The served figure is the MEASURED initial-answer cost, not the pre-run
    # estimate — which is what a false downgrade would have served instead.
    assert Decimal(str(body["actual_cost_usd"])) != run.cost_estimate.estimated_cost_usd
    assert Decimal(str(body["actual_cost_usd"])) > Decimal("0")
    assert body["live_count"] == 4
    assert body["result"]["final_synthesis"]["synthesis_mode"] != "live"


def test_control_all_seven_calls_usable_is_live_prose_and_measured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CONTROL: the happy path is untouched, so the tests above measure something."""
    live_text = "A usable critique with real substance and a clear disagreement."
    _install(
        monkeypatch,
        lambda _kwargs: LiveProviderResult(answer_text=live_text, sources=[], usage=_USAGE),
    )
    body = _drive(TestClient(app))

    assert body["cost_source"] == "measured"
    assert body["live_count"] == 4
    assert body["demo_mode"] is False
    rounds = body["result"]["debate_outputs"]
    assert rounds[0]["critique_text"] == live_text
    assert rounds[1]["critique_text"] == live_text
    for label, text in _synthesis_sections(body):
        assert live_text in text, label
    # ...and it is LABELLED live. WP-A carries that structurally in
    # ``synthesis_mode`` rather than as a text prefix on the prose.
    assert body["result"]["final_synthesis"]["synthesis_mode"] == "live"
