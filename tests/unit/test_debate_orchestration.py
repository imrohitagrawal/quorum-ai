from uuid import uuid4

from product_app.debate import DebateRoundStatus, debate_event_recorder, debate_stub_service
from product_app.model_slots import validate_model_slots
from product_app.providers import provider_stub_service

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


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
    monkeypatch: object,
) -> None:
    """L4: when a key and the live-execution flag are both set, the
    debate orchestrator should call the LLM and use its output as the
    round text. We mock the provider call so the test does not hit
    the network.
    """
    from product_app import config, debate as debate_mod
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
        debate_mod.provider_execution_service,
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
    monkeypatch: object,
) -> None:
    """L4: even with a key set, if the operator has explicitly
    disabled live execution, the debate orchestrator must fall back
    to the templated critique. Otherwise the test suite / staging
    environments would silently hit the network.
    """
    from product_app import config, debate as debate_mod

    called = {"count": 0}

    def fake_call(**kwargs: object) -> object:
        called["count"] += 1
        return None

    monkeypatch.setattr(
        debate_mod.provider_execution_service,
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
