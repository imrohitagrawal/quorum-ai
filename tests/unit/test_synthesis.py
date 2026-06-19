from uuid import uuid4

from product_app.debate import debate_stub_service
from product_app.model_slots import validate_model_slots
from product_app.providers import provider_stub_service
from product_app.synthesis import SynthesisStatus, synthesis_event_recorder, synthesis_stub_service

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


def test_synthesis_stub_returns_required_sections_and_quality_checks() -> None:
    synthesis_event_recorder.clear()
    account_id = uuid4()
    query_run_id = uuid4()
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
    initial_answers = provider_stub_service.produce_initial_answers(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare source-backed options with material disagreement",
        model_slots=model_slots,
    )
    debate_result = debate_stub_service.run_debate_rounds(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare source-backed options with material disagreement",
        initial_answers=initial_answers,
    )

    result = synthesis_stub_service.produce_final_synthesis(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare source-backed options with material disagreement",
        initial_answers=initial_answers,
        debate_outputs=debate_result.debate_outputs,
    )

    assert result.failed_steps == []
    assert result.missing_steps == []
    assert result.final_synthesis is not None
    synthesis = result.final_synthesis
    assert synthesis.status is SynthesisStatus.COMPLETED
    assert synthesis.consensus
    assert "disagreement" in synthesis.disagreement
    assert "visible source references" in synthesis.source_support
    assert synthesis.uncertainty
    assert "decision support only" in synthesis.recommendation
    assert synthesis.citation_coverage.target_met
    assert synthesis.quality_checks.citation_coverage_target_met
    assert synthesis.quality_checks.false_consensus_preserved
    assert synthesis.quality_checks.decision_support_framing_present
    event = synthesis_event_recorder.list_events()[0]
    assert event.account_id == account_id
    assert event.query_run_id == query_run_id
    assert event.status is SynthesisStatus.COMPLETED
    assert event.false_consensus_preserved
    assert not hasattr(event, "query_text")
    assert not hasattr(event, "provider_key")


def test_high_stakes_synthesis_includes_decision_support_notice() -> None:
    account_id = uuid4()
    query_run_id = uuid4()
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
    query_text = "Compare legal contract and financial risk"
    initial_answers = provider_stub_service.produce_initial_answers(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text=query_text,
        model_slots=model_slots,
    )
    debate_result = debate_stub_service.run_debate_rounds(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text=query_text,
        initial_answers=initial_answers,
    )

    result = synthesis_stub_service.produce_final_synthesis(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text=query_text,
        initial_answers=initial_answers,
        debate_outputs=debate_result.debate_outputs,
    )

    assert result.final_synthesis is not None
    assert result.final_synthesis.quality_checks.high_stakes_warning_required
    assert result.final_synthesis.high_stakes_notice is not None
    assert "not medical, legal, financial, safety, or regulated professional advice" in (
        result.final_synthesis.high_stakes_notice
    )


def test_synthesis_live_path_uses_llm_text_when_key_and_flag_set(
    monkeypatch: object,
) -> None:
    """L4: when a key and the live-execution flag are both set, the
    synthesis orchestrator should call the LLM for each of the five
    sections and use the LLM text in the result.
    """
    from product_app import config, synthesis as synth_mod
    from product_app.providers import LiveProviderResult

    calls: list[str] = []

    def fake_call(**kwargs: object) -> LiveProviderResult | None:
        calls.append(str(kwargs.get("system_prompt", "")))
        return LiveProviderResult(
            answer_text="Live LLM section text.",
            sources=[],
        )

    monkeypatch.setattr(
        synth_mod.provider_execution_service,
        "call_with_prompt",
        fake_call,
    )
    monkeypatch.setattr(
        config.settings,
        "openrouter_live_execution_enabled",
        True,
        raising=False,
    )

    account_id = uuid4()
    query_run_id = uuid4()
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
    initial_answers = provider_stub_service.produce_initial_answers(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare source-backed options",
        model_slots=model_slots,
    )
    debate_result = debate_stub_service.run_debate_rounds(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare source-backed options",
        initial_answers=initial_answers,
    )

    result = synthesis_stub_service.produce_final_synthesis(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare source-backed options",
        initial_answers=initial_answers,
        debate_outputs=debate_result.debate_outputs,
        openrouter_key="sk-or-test-live",
    )

    assert result.final_synthesis is not None
    # All five sections use LLM text.
    assert result.final_synthesis.consensus == "Live LLM section text."
    assert result.final_synthesis.disagreement == "Live LLM section text."
    assert result.final_synthesis.source_support == "Live LLM section text."
    assert result.final_synthesis.uncertainty == "Live LLM section text."
    assert result.final_synthesis.recommendation == "Live LLM section text."
    # Five section calls total.
    assert len(calls) == 5


def test_synthesis_falls_back_to_template_when_live_execution_disabled(
    monkeypatch: object,
) -> None:
    """L4: even with a key set, if the operator has explicitly
    disabled live execution, the synthesis orchestrator must fall
    back to the templated text on all five sections.
    """
    from product_app import config, synthesis as synth_mod

    called = {"count": 0}

    def fake_call(**kwargs: object) -> object:
        called["count"] += 1
        return None

    monkeypatch.setattr(
        synth_mod.provider_execution_service,
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
        query_text="Compare source-backed options",
        model_slots=model_slots,
    )
    debate_result = debate_stub_service.run_debate_rounds(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare source-backed options",
        initial_answers=initial_answers,
    )

    result = synthesis_stub_service.produce_final_synthesis(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare source-backed options",
        initial_answers=initial_answers,
        debate_outputs=debate_result.debate_outputs,
        openrouter_key="sk-or-test-live",
    )

    assert result.final_synthesis is not None
    # Templated consensus text mentions "Four models were asked".
    assert "Four models were asked" in result.final_synthesis.consensus
    # The "visible source references" phrase from the templated source_support
    # is what the existing integration test pins.
    assert "visible source references" in result.final_synthesis.source_support
    # No LLM calls were made.
    assert called["count"] == 0
