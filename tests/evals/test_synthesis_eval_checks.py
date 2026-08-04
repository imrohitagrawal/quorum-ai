from uuid import uuid4

from product_app.debate import debate_stub_service
from product_app.model_slots import validate_model_slots
from product_app.providers import provider_stub_service
from product_app.synthesis import FinalSynthesis, synthesis_stub_service

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


def produce_synthesis(query_text: str) -> FinalSynthesis:
    account_id = uuid4()
    query_run_id = uuid4()
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
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
    return result.final_synthesis


def test_synthesis_eval_preserves_disagreement_and_meets_citation_target() -> None:
    synthesis = produce_synthesis(
        "Compare evidence where models materially disagree on the recommendation",
    )

    # #247. Two assertions here, needing two different corrections.
    #
    # The flag: ``eee93ca`` flipped this from
    # ``assert synthesis.quality_checks.false_consensus_preserved`` on the
    # reasoning that four identical stub answers are a "strong" consensus. They
    # are identical because ONE template produced all four, so the original
    # value is restored. Note the flipped version contradicted this test's own
    # name — ``..._preserves_disagreement_...`` asserting disagreement was NOT
    # preserved.
    #
    # The prose: this run asks nobody, so the disagreement section no longer
    # carries "unsupported consensus" (the weak-path wording). Asserting the
    # section's PROPERTY rather than one branch's incidental phrase — it must
    # say something, and it must not claim the models disagreed.
    assert synthesis.disagreement.strip()
    assert "No model was asked this question" in synthesis.disagreement
    assert "Models disagree" not in synthesis.disagreement
    assert synthesis.quality_checks.false_consensus_preserved
    # WP-C / F-03: all four local-simulation answers carry a primary source,
    # so coverage is 4/4 and the target IS met. That is the point of the
    # redefinition — under the old chars-per-claim denominator this same
    # fully-sourced run scored 0.50 and was reported as failing the target.
    assert synthesis.citation_coverage.answer_count == 4
    assert synthesis.citation_coverage.sourced_answer_count == 4
    coverage = synthesis.citation_coverage
    assert coverage.sourced_answer_ratio >= coverage.target_ratio
    assert synthesis.quality_checks.citation_coverage_target_met


def test_synthesis_eval_flags_high_stakes_examples_as_decision_support() -> None:
    examples = [
        "Compare medical diagnosis options",
        "Review legal contract risk",
        "Compare financial investment options",
        "Assess workplace safety hazard",
        "Review regulated compliance response",
    ]

    for example in examples:
        synthesis = produce_synthesis(example)
        assert synthesis.quality_checks.high_stakes_warning_required
        assert synthesis.high_stakes_notice is not None
        assert "decision support only" in synthesis.high_stakes_notice
        assert "not medical, legal, financial, safety, or regulated professional advice" in (
            synthesis.high_stakes_notice
        )
