"""NFR-012 / AC-042: judge OFF is a proven no-op, and NFR-011 hermeticity.

Two claims, both asserted mechanically rather than by inspection:

1. The TrustScore served with the judge OFF is byte-identical to the one
   served with ``StubEvalJudge`` ON.
2. With the judge OFF, the LLM seam (``providers.call_with_prompt``) is
   called ZERO times. The spy raises on contact, so a future refactor that
   sneaks a call in fails this test rather than silently costing money.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from product_app.config import settings
from product_app.debate import AgreementSummary
from product_app.evaluation import StubEvalJudge, evaluate_run
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    SourceReference,
    provider_execution_service,
)
from product_app.synthesis import FinalSynthesis, SynthesisQualityChecks, SynthesisStatus

REAL_URL = "https://pages.nist.gov/800-63-3/sp800-63b.html"


@pytest.fixture(autouse=True)
def _seam_spy(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every test in this module runs with a seam that explodes on contact."""
    calls: list[dict[str, Any]] = []

    def _spy(**kwargs: Any) -> None:
        calls.append(kwargs)
        raise AssertionError(
            "provider_execution_service.call_with_prompt was called during a "
            "judge-OFF evaluation — NFR-011/NFR-012 require zero seam calls."
        )

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", _spy)
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", "")
    return calls


def _answers() -> list[InitialModelAnswer]:
    source = SourceReference(
        title="A source", url=REAL_URL, provider=ProviderPath.OPENROUTER_SEARCH
    )
    return [
        InitialModelAnswer(
            slot_number=slot,
            model_id=f"vendor/model-{slot}",
            display_name=f"Model {slot}",
            answer_text=f"Slot {slot} makes a claim [1] and a second one [1].",
            sources=[source],
            provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
            provider_path=ProviderPath.OPENROUTER_SEARCH,
            fallback_used=False,
            status=InitialAnswerStatus.COMPLETED,
            latency_ms=100 + slot,
            citation_coverage=CitationCoverage(
                material_claim_count=2,
                cited_claim_count=2,
                coverage_ratio=Decimal("1.00"),
                target_met=True,
            ),
        )
        for slot in (1, 2, 3, 4)
    ]


def _synthesis() -> FinalSynthesis:
    return FinalSynthesis(
        status=SynthesisStatus.COMPLETED,
        consensus="The panel agrees on the mechanism [1].",
        disagreement="No material disagreement.",
        source_support="One source carried the load.",
        uncertainty="Durability beyond a year is unestablished.",
        recommendation="Treat this as decision support, not a decision.",
        high_stakes_notice=None,
        citation_coverage=CitationCoverage(
            material_claim_count=8,
            cited_claim_count=4,
            coverage_ratio=Decimal("0.50"),
            target_met=False,
        ),
        quality_checks=SynthesisQualityChecks(
            citation_coverage_target_met=False,
            false_consensus_preserved=False,
            decision_support_framing_present=True,
            high_stakes_warning_required=False,
        ),
    )


def _run(judge: Any) -> Any:
    return evaluate_run(
        initial_answers=_answers(),
        final_synthesis=_synthesis(),
        agreement=AgreementSummary(aligned=4, total=4),
        judge=judge,
        query_text="Should we require periodic password rotation?",
    )


def test_judge_off_and_stub_on_produce_byte_identical_trust(
    _seam_spy: list[dict[str, Any]],
) -> None:
    off = _run(None)
    stub = _run(StubEvalJudge())

    assert off.trust.model_dump_json() == stub.trust.model_dump_json()
    assert off.trust_json() == stub.trust_json()
    assert off.trust.support_verified is False
    assert stub.trust.support_verified is False
    assert stub.trust.band == "unverified"
    assert stub.trust.score is None
    assert _seam_spy == []


def test_the_stub_judge_verdict_is_advisory_metadata_only(
    _seam_spy: list[dict[str, Any]],
) -> None:
    off = _run(None)
    stub = _run(StubEvalJudge())

    assert off.evaluation.judge is None
    assert stub.evaluation.judge is not None
    # The verdict is present but changes nothing in the arithmetic.
    assert off.evaluation.signals.model_dump_json() == stub.evaluation.signals.model_dump_json()
    assert off.evaluation.faithfulness_label == stub.evaluation.faithfulness_label
    assert off.evaluation.hallucination_risk == stub.evaluation.hallucination_risk
    assert _seam_spy == []


def test_evaluation_is_reproducible_across_calls(_seam_spy: list[dict[str, Any]]) -> None:
    first = _run(None)
    second = _run(None)
    assert first.eval_json() == second.eval_json()
    assert first.trust_json() == second.trust_json()
    assert _seam_spy == []


def test_persisted_payloads_carry_metrics_only(_seam_spy: list[dict[str, Any]]) -> None:
    result = _run(StubEvalJudge())
    serialized = repr(result.eval_json()) + repr(result.trust_json())
    assert "Should we require periodic password rotation?" not in serialized
    assert "The panel agrees on the mechanism" not in serialized
    assert "makes a claim" not in serialized
    assert "rationale" not in serialized
    assert _seam_spy == []
