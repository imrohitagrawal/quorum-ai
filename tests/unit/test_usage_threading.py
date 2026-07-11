"""Debate + synthesis thread captured usage up to their results (P2).

Network-free: the live provider call is mocked and the initial answers are
built directly, so these exercise the usage-collection logic in
``run_debate_rounds`` / ``produce_final_synthesis`` without a catalog fetch or
a real HTTP call. They are the offline stand-in for the live-path integration
tests that need OpenRouter reachable.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from product_app import config
from product_app.debate import (
    ROUND_ONE_SYSTEM_PROMPT,
    DebateOutput,
    DebateRoundStatus,
    debate_stub_service,
)
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
from product_app.synthesis import _RECOMMENDATION_PROMPT, synthesis_stub_service

_USAGE = TokenUsage(prompt_tokens=100, completion_tokens=40, total_tokens=140)


def _answer(slot: int) -> InitialModelAnswer:
    return InitialModelAnswer(
        slot_number=slot,
        model_id=f"vendor/model-{slot}",
        display_name=f"Model {slot}",
        answer_text=f"Answer from model {slot} with a concrete claim.",
        sources=[
            SourceReference(
                title="s",
                url="https://example.com",
                provider=ProviderPath.OPENROUTER_SEARCH,
            )
        ],
        provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
        provider_path=ProviderPath.OPENROUTER_SEARCH,
        fallback_used=False,
        status=InitialAnswerStatus.COMPLETED,
        latency_ms=10,
        citation_coverage=CitationCoverage(
            material_claim_count=1,
            cited_claim_count=1,
            coverage_ratio=Decimal("1"),
            target_met=True,
        ),
        token_usage=_USAGE,
    )


def _answers() -> list[InitialModelAnswer]:
    return [_answer(i) for i in range(1, 5)]


def _mock_live(monkeypatch: pytest.MonkeyPatch, usage: TokenUsage | None) -> None:
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)

    def fake_call(**kwargs: object) -> LiveProviderResult:
        return LiveProviderResult(
            answer_text="Live critique/section text.", sources=[], usage=usage
        )

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", fake_call)


def test_debate_collects_usage_from_live_rounds(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_live(monkeypatch, _USAGE)
    result = debate_stub_service.run_debate_rounds(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare durable options",
        initial_answers=_answers(),
        openrouter_key="sk-or-test-live",
    )
    # Both rounds went live → two usage entries, each tagged with its round.
    assert result.live_call_usages == [(1, _USAGE), (2, _USAGE)]


def test_debate_records_none_when_provider_omits_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_live(monkeypatch, None)
    result = debate_stub_service.run_debate_rounds(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare durable options",
        initial_answers=_answers(),
        openrouter_key="sk-or-test-live",
    )
    # Live calls happened but reported no usage → billed-but-unmeasurable.
    assert result.live_call_usages == [(1, None), (2, None)]


def test_debate_round2_only_is_attributed_to_round2(monkeypatch: pytest.MonkeyPatch) -> None:
    """If round 1 falls back to templated but round 2 goes live, the usage must
    be tagged round 2 — not silently positioned as round 1."""
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)

    def selective_call(**kwargs: object) -> LiveProviderResult | None:
        # Round 1 uses ROUND_ONE_SYSTEM_PROMPT; fail it (templated), let round 2 live.
        if kwargs.get("system_prompt") == ROUND_ONE_SYSTEM_PROMPT:
            return None
        return LiveProviderResult(answer_text="round 2 critique", sources=[], usage=_USAGE)

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", selective_call)
    result = debate_stub_service.run_debate_rounds(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare durable options",
        initial_answers=_answers(),
        openrouter_key="sk-or-test-live",
    )
    assert result.live_call_usages == [(2, _USAGE)]


def test_debate_templated_run_records_no_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", False, raising=False)
    result = debate_stub_service.run_debate_rounds(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare durable options",
        initial_answers=_answers(),
        openrouter_key="sk-or-test-live",
    )
    # No live call was made (templated) → nothing billed, nothing recorded.
    assert result.live_call_usages == []


def _debate_outputs() -> list[DebateOutput]:
    return [
        DebateOutput(
            round_number=n,
            focus_areas=["disagreement"],
            critique_text="critique",
            status=DebateRoundStatus.COMPLETED,
        )
        for n in (1, 2)
    ]


def test_synthesis_collects_usage_from_live_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_live(monkeypatch, _USAGE)
    result = synthesis_stub_service.produce_final_synthesis(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare durable options",
        initial_answers=_answers(),
        debate_outputs=_debate_outputs(),
        openrouter_key="sk-or-test-live",
    )
    # All five sections made a live call → five captured usage entries.
    assert result.live_call_usages == [_USAGE] * 5


def test_synthesis_mixed_live_and_templated_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    """A section that falls back to templated contributes no usage entry.

    Verifies the entries↔billed-calls invariant across the live/templated
    boundary: forcing only the recommendation section to fail its live call
    yields four usage entries, not five.
    """
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)

    def selective_call(**kwargs: object) -> LiveProviderResult | None:
        if kwargs.get("system_prompt") == _RECOMMENDATION_PROMPT:
            return None  # recommendation falls back to templated (not billed)
        return LiveProviderResult(answer_text="section text", sources=[], usage=_USAGE)

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", selective_call)
    result = synthesis_stub_service.produce_final_synthesis(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare durable options",
        initial_answers=_answers(),
        debate_outputs=_debate_outputs(),
        openrouter_key="sk-or-test-live",
    )
    assert result.live_call_usages == [_USAGE] * 4


def test_synthesis_templated_run_records_no_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", False, raising=False)
    result = synthesis_stub_service.produce_final_synthesis(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare durable options",
        initial_answers=_answers(),
        debate_outputs=_debate_outputs(),
        openrouter_key="sk-or-test-live",
    )
    assert result.live_call_usages == []
