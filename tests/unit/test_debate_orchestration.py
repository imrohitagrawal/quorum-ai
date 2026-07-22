from uuid import uuid4

import pytest

from product_app.debate import (
    DEBATE_HARD_TIMEOUT_MS,
    DebateOrchestrationService,
    DebateRoundStatus,
    debate_event_recorder,
    debate_stub_service,
)
from product_app.model_slots import validate_model_slots
from product_app.providers import provider_execution_service, provider_stub_service

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


def test_debate_hard_timeout_budget_is_180s_and_gates_round_two_at_the_boundary() -> None:
    """RB-5 / D2 — assert the budget that GENUINELY exists (NFR-004 honesty).

    The ONLY 180s behavioural mechanism in ``src`` is
    ``DEBATE_HARD_TIMEOUT_MS``: it gates whether debate *round 2* runs, measured
    from round-1 start. It is NOT a run-level deadline — nothing terminates a
    stuck run at 180s (see ``docs/18`` NFR-004, recorded UNENFORCED). This test
    pins the mechanism that exists at its exact boundary so no future edit can
    silently move the debate budget while NFR-004 is documented as unenforced.

    Bite proof: change ``180_000`` → the constant assertion reds; change the
    ``>`` in ``_should_skip_round_two`` to ``>=`` → the 180_000-exact boundary
    assertion reds.
    """
    assert DEBATE_HARD_TIMEOUT_MS == 180_000
    orchestrator = DebateOrchestrationService(hard_timeout_ms=DEBATE_HARD_TIMEOUT_MS)
    # Strictly OVER budget skips round two; exactly AT and just under do not.
    assert orchestrator._should_skip_round_two(elapsed_ms=180_001, query_text="q") is True
    assert orchestrator._should_skip_round_two(elapsed_ms=180_000, query_text="q") is False
    assert orchestrator._should_skip_round_two(elapsed_ms=179_999, query_text="q") is False


def test_debate_stub_runs_two_structured_critique_rounds() -> None:
    debate_event_recorder.clear()
    account_id = uuid4()
    query_run_id = uuid4()
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
    initial_answers = provider_stub_service.produce_initial_answers(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare durable options",
        model_slots=model_slots,
    )

    result = debate_stub_service.run_debate_rounds(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare durable options",
        initial_answers=initial_answers,
    )

    assert not result.timed_out
    assert result.failed_steps == []
    assert len(result.debate_outputs) == 2
    assert [output.round_number for output in result.debate_outputs] == [1, 2]
    assert all(output.status is DebateRoundStatus.COMPLETED for output in result.debate_outputs)
    assert all(
        output.focus_areas == ["disagreement", "weak_support", "missing_reasoning"]
        for output in result.debate_outputs
    )
    assert len(debate_event_recorder.list_events()) == 2


def test_debate_stub_returns_partial_plan_when_second_round_exceeds_budget() -> None:
    debate_event_recorder.clear()
    account_id = uuid4()
    query_run_id = uuid4()
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
    initial_answers = provider_stub_service.produce_initial_answers(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare options",
        model_slots=model_slots,
    )

    result = debate_stub_service.run_debate_rounds(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Force debate timeout before round two",
        initial_answers=initial_answers,
    )

    assert result.timed_out
    assert len(result.debate_outputs) == 1
    assert result.failed_steps == ["debate_round_2"]
    assert result.missing_steps == ["debate_round_2", "synthesis"]


def test_debate_live_path_uses_llm_critique_when_key_and_flag_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L4: when a key and the live-execution flag are both set, the
    debate orchestrator should call the LLM and use its output as the
    round text. We mock the provider call so the test does not hit
    the network.
    """
    from product_app import config
    from product_app.providers import LiveProviderResult

    calls: list[str] = []

    def fake_call(**kwargs: object) -> LiveProviderResult | None:
        calls.append(str(kwargs.get("system_prompt", "")))
        # Both rounds get the same critique text for the assertion.
        return LiveProviderResult(
            answer_text="Live LLM critique text.",
            sources=[],
        )

    monkeypatch.setattr(
        provider_execution_service,
        "call_with_prompt",
        fake_call,
    )
    monkeypatch.setattr(
        config.settings,
        "openrouter_live_execution_enabled",
        True,
        raising=False,
    )

    debate_event_recorder.clear()
    account_id = uuid4()
    query_run_id = uuid4()
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
    initial_answers = provider_stub_service.produce_initial_answers(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare durable options",
        model_slots=model_slots,
    )

    result = debate_stub_service.run_debate_rounds(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare durable options",
        initial_answers=initial_answers,
        openrouter_key="sk-or-test-live",
    )

    assert len(result.debate_outputs) == 2
    assert result.debate_outputs[0].critique_text == "Live LLM critique text."
    assert result.debate_outputs[1].critique_text == "Live LLM critique text."
    # Both rounds hit the LLM.
    assert len(calls) == 2


def test_debate_falls_back_to_template_when_live_execution_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L4: even with a key set, if the operator has explicitly
    disabled live execution, the debate orchestrator must fall back
    to the templated critique. Otherwise the test suite / staging
    environments would silently hit the network.
    """
    from product_app import config

    called = {"count": 0}

    def fake_call(**kwargs: object) -> object:
        called["count"] += 1
        return None

    monkeypatch.setattr(
        provider_execution_service,
        "call_with_prompt",
        fake_call,
    )
    monkeypatch.setattr(
        config.settings,
        "openrouter_live_execution_enabled",
        False,
        raising=False,
    )

    account_id = uuid4()
    query_run_id = uuid4()
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
    initial_answers = provider_stub_service.produce_initial_answers(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare options",
        model_slots=model_slots,
    )

    result = debate_stub_service.run_debate_rounds(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare options",
        initial_answers=initial_answers,
        openrouter_key="sk-or-test-live",
    )

    assert len(result.debate_outputs) == 2
    # Template text starts with the magic phrase the integration
    # test asserts on.
    assert result.debate_outputs[0].critique_text.startswith("Round 1 critique.")
    assert called["count"] == 0
