"""WP-C / F-03 — what ``citation_coverage`` is allowed to mean.

The defect these tests pin: the ratio's numerator and denominator did not
share units. ``cited_claim_count`` was a BOOLEAN per answer — ``1`` if the
answer carried any primary source, else ``0`` (``providers.py``) — while
``material_claim_count`` was a length heuristic of roughly one claim per 200
characters. A run of four 1500-character answers, every one of them carrying a
primary source, therefore topped out at ``4 / 32 = 12.5%`` against an 80%
target. ``target_met`` was unreachable in practice, so every run was labelled
provisional and the recommendation always said "pause for human review" — even
when four of four models aligned and every answer cited a source.

The approved fix (operator decision, master-plan option **b**) redefines the
metric as **the fraction of answers that carry at least one primary source**,
and renames the fields so the label states its own denominator:

    material_claim_count -> answer_count
    cited_claim_count    -> sourced_answer_count
    coverage_ratio       -> sourced_answer_ratio

``test_ratio_does_not_move_with_answer_length`` is the load-bearing one. It is
the assertion no character-based denominator can satisfy, so the defect cannot
be greened by re-tuning ``MATERIAL_CLAIM_CHAR_DENOMINATOR``, and it cannot be
greened by the field rename alone.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from product_app.config import RuntimeEnvironment, settings
from product_app.debate import debate_stub_service
from product_app.model_slots import ModelSlot, validate_model_slots
from product_app.provider_keys import ProviderCredentialSource
from product_app.providers import (
    InitialAnswerStatus,
    InitialModelAnswer,
    LiveProviderResult,
    ProviderPath,
    SourceReference,
    TokenUsage,
    provider_execution_service,
)
from product_app.synthesis import synthesis_stub_service

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "nvidia/nemotron-3-super-120b-a12b",
]

#: Long enough that the old ~1-claim-per-200-chars denominator would have put a
#: fully-sourced answer at roughly 1/8 coverage. Realistic: the golden fixture's
#: provider answers are this shape, and a real model answer is longer still.
_LONG_ANSWER = (
    "The evidence points in one direction, and the reasoning is worth setting out "
    "at length so the reader can audit it rather than take it on trust. "
) * 12

#: Deliberately just under the 200-character heuristic, so the OLD denominator
#: gave this answer exactly one claim and a fully-sourced answer scored 1.00.
#: This is the short, unrepresentative sample that let F-03 look acceptable.
_SHORT_ANSWER = "A brief but complete answer to the question."


def _primary_source(n: int = 1) -> SourceReference:
    return SourceReference(
        title=f"Primary source {n}",
        url=f"https://example.test/source-{n}",
        provider=ProviderPath.OPENROUTER_SEARCH,
        is_fallback=False,
    )


def _fallback_source() -> SourceReference:
    return SourceReference(
        title="Fallback source",
        url="https://example.test/fallback",
        provider=ProviderPath.FALLBACK_SEARCH,
        is_fallback=True,
    )


@pytest.fixture(autouse=True)
def _live_execution_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Take the live provider path so the answer text is ours, not the stub's.

    The local-simulation stub emits a fixed ~218-character answer, which is
    exactly the narrow sample that hid this defect. These tests need control of
    the answer length, so they drive the live path with a patched transport.
    """
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", True)
    monkeypatch.setattr(settings, "runtime_environment", RuntimeEnvironment.LOCAL)


def _answer_with(
    *,
    answer_text: str,
    sources: list[SourceReference],
    model_slot: ModelSlot,
    account_id: UUID | None = None,
) -> InitialModelAnswer:
    """Produce a real COMPLETED answer through the production code path.

    Constructing ``InitialModelAnswer`` directly would let the test assert a
    ``citation_coverage`` it built itself, which proves nothing. This goes
    through ``produce_initial_answer`` so the coverage is computed by the code
    under test.
    """
    live = LiveProviderResult(
        answer_text=answer_text,
        sources=sources,
        usage=TokenUsage(prompt_tokens=100, completion_tokens=200, total_tokens=300),
    )
    with patch.object(provider_execution_service, "_post_openrouter", return_value=live):
        answer = provider_execution_service.produce_initial_answer(
            account_id=account_id or uuid4(),
            query_run_id=uuid4(),
            query_text="Does the evidence support the proposal?",
            model_slot=model_slot,
            credential_source=ProviderCredentialSource.APP_OWNED,
            openrouter_key="sk-test",
        )
    assert answer.status is InitialAnswerStatus.COMPLETED, "precondition: the answer must complete"
    assert answer.answer_text == answer_text, "precondition: the patched text must reach the answer"
    return answer


def _run_coverage(answers: list[InitialModelAnswer]) -> tuple[Decimal, bool, bool]:
    """Synthesize *answers* and return (ratio, target_met, quality_check)."""
    account_id, query_run_id = uuid4(), uuid4()
    debate = debate_stub_service.run_debate_rounds(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Does the evidence support the proposal?",
        initial_answers=answers,
    )
    result = synthesis_stub_service.produce_final_synthesis(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Does the evidence support the proposal?",
        initial_answers=answers,
        debate_outputs=debate.debate_outputs,
    )
    assert result.final_synthesis is not None
    coverage = result.final_synthesis.citation_coverage
    return (
        coverage.sourced_answer_ratio,
        coverage.target_met,
        result.final_synthesis.quality_checks.citation_coverage_target_met,
    )


def _four_answers(*, texts: list[str], sourced: list[bool]) -> list[InitialModelAnswer]:
    slots = validate_model_slots(DEFAULT_MODEL_IDS)
    return [
        _answer_with(
            answer_text=text,
            sources=[_primary_source(i + 1)] if has_source else [],
            model_slot=slots[i],
        )
        for i, (text, has_source) in enumerate(zip(texts, sourced, strict=True))
    ]


# ---------------------------------------------------------------------------
# The bite: the ratio must not depend on how much the model wrote
# ---------------------------------------------------------------------------


def test_ratio_does_not_move_with_answer_length() -> None:
    """Two identically-sourced runs must score the same regardless of length.

    This is the assertion that cannot be satisfied by any characters-per-claim
    denominator, and cannot be satisfied by the field rename alone. Under the
    old math the short run scored 1.00 and the long run scored ~0.13.
    """
    short_ratio, short_met, _ = _run_coverage(
        _four_answers(texts=[_SHORT_ANSWER] * 4, sourced=[True] * 4)
    )
    long_ratio, long_met, _ = _run_coverage(
        _four_answers(texts=[_LONG_ANSWER] * 4, sourced=[True] * 4)
    )

    assert len(_LONG_ANSWER) > 5 * len(_SHORT_ANSWER), "precondition: the lengths must differ a lot"
    assert long_ratio == short_ratio
    assert long_ratio == Decimal("1.00")
    assert short_met is True
    assert long_met is True


def test_fully_sourced_long_run_meets_the_target() -> None:
    """The exact case F-03 made unreachable: 4 long answers, all sourced."""
    ratio, target_met, quality_check = _run_coverage(
        _four_answers(texts=[_LONG_ANSWER] * 4, sourced=[True] * 4)
    )
    assert ratio == Decimal("1.00")
    assert target_met is True
    assert quality_check is True


# ---------------------------------------------------------------------------
# The other direction: the metric must still be able to fail
# ---------------------------------------------------------------------------


def test_run_with_no_primary_sources_reports_zero() -> None:
    ratio, target_met, quality_check = _run_coverage(
        _four_answers(texts=[_LONG_ANSWER] * 4, sourced=[False] * 4)
    )
    assert ratio == Decimal("0.00")
    assert target_met is False
    assert quality_check is False


def test_half_sourced_run_reports_half_and_misses_the_target() -> None:
    ratio, target_met, _ = _run_coverage(
        _four_answers(texts=[_LONG_ANSWER] * 4, sourced=[True, True, False, False])
    )
    assert ratio == Decimal("0.50")
    assert target_met is False


def test_three_of_four_sourced_still_misses_the_eighty_percent_target() -> None:
    """0.75 < 0.80 — the target is a real bar, not a formality."""
    ratio, target_met, _ = _run_coverage(
        _four_answers(texts=[_LONG_ANSWER] * 4, sourced=[True, True, True, False])
    )
    assert ratio == Decimal("0.75")
    assert target_met is False


def _failed_answer(slot_index: int = 3) -> InitialModelAnswer:
    """A slot that failed outright — no text, so nothing to source."""
    slots = validate_model_slots(DEFAULT_MODEL_IDS)
    answer = provider_execution_service._failed_answer(
        account_id=uuid4(),
        query_run_id=uuid4(),
        model_slot=slots[slot_index],
        credential_source=ProviderCredentialSource.APP_OWNED,
        started_at=0.0,
    )
    assert answer.status is InitialAnswerStatus.FAILED, "precondition: the answer must fail"
    return answer


# ---------------------------------------------------------------------------
# Runs that are NOT four clean successes — the shapes the first cut missed
# ---------------------------------------------------------------------------


def test_a_failed_slot_leaves_the_coverage_denominator_and_does_not_dilute_it() -> None:
    """A slot that produced no text is out of the denominator entirely.

    This pins the judgement call WP-C makes: a missing slot is penalised by
    ``completeness``, not twice. Reverting ``_failed_answer``'s ``answer_count``
    to 1 silently flips this run from 3/3 to 3/4 and changes the recommendation,
    and before this test the whole suite stayed green when it did.
    """
    answers = _four_answers(texts=[_LONG_ANSWER] * 3, sourced=[True] * 3) + [_failed_answer()]
    account_id, query_run_id = uuid4(), uuid4()
    debate = debate_stub_service.run_debate_rounds(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Does the evidence support the proposal?",
        initial_answers=answers,
    )
    result = synthesis_stub_service.produce_final_synthesis(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Does the evidence support the proposal?",
        initial_answers=answers,
        debate_outputs=debate.debate_outputs,
    )
    assert result.final_synthesis is not None
    coverage = result.final_synthesis.citation_coverage
    assert coverage.answer_count == 3, "the failed slot must not be in the denominator"
    assert coverage.sourced_answer_count == 3
    assert coverage.sourced_answer_ratio == Decimal("1.00")
    assert coverage.target_met is True

    # ...and the prose under the trust tile must state the SAME denominator.
    # A "100%" tile above "3 of 4 models" is two denominators on one screen —
    # the misreading this work package exists to remove (review A1).
    assert "3 of 3 responding models" in result.final_synthesis.source_support, (
        "source_support must count the answers that came back, not the slot count: "
        f"{result.final_synthesis.source_support!r}"
    )


def test_the_prose_denominator_tracks_the_tile_on_a_mostly_failed_run() -> None:
    """One survivor of four: the tile says 100%, so the prose must say 1 of 1."""
    answers = _four_answers(texts=[_LONG_ANSWER], sourced=[True]) + [
        _failed_answer(slot_index=i) for i in (1, 2, 3)
    ]
    ratio, target_met, _ = _run_coverage(answers)
    assert ratio == Decimal("1.00")
    assert target_met is True


def test_a_run_sourced_only_by_fallbacks_reports_zero_at_RUN_level() -> None:
    """The fallback exclusion must hold on the AGGREGATE, not just per answer.

    Deleting the ``not source.is_fallback`` gate in synthesis.py used to be
    invisible: the old denominator kept the mutant at ~0.33, still under target.
    Under the new math the same mutation flips ``target_met`` False -> True and
    turns "do not act on the consensus yet" into "the source coverage target is
    met" (review A3).
    """
    slots = validate_model_slots(DEFAULT_MODEL_IDS)
    answers = [
        _answer_with(answer_text=_LONG_ANSWER, sources=[_fallback_source()], model_slot=slots[i])
        for i in range(4)
    ]
    ratio, target_met, quality_check = _run_coverage(answers)
    assert ratio == Decimal("0.00")
    assert target_met is False
    assert quality_check is False


# ---------------------------------------------------------------------------
# Per-answer semantics, and the fallback exclusion that must survive
# ---------------------------------------------------------------------------


def test_a_single_answer_is_one_unit_of_coverage() -> None:
    slots = validate_model_slots(DEFAULT_MODEL_IDS)
    answer = _answer_with(
        answer_text=_LONG_ANSWER, sources=[_primary_source()], model_slot=slots[0]
    )
    assert answer.citation_coverage.answer_count == 1
    assert answer.citation_coverage.sourced_answer_count == 1
    assert answer.citation_coverage.sourced_answer_ratio == Decimal("1.00")


def test_fallback_only_sources_do_not_count_as_coverage() -> None:
    """Unchanged rule: a fallback source is real, but it is not the model's own
    research, so it must not inflate the metric."""
    slots = validate_model_slots(DEFAULT_MODEL_IDS)
    answer = _answer_with(
        answer_text=_LONG_ANSWER, sources=[_fallback_source()], model_slot=slots[0]
    )
    assert answer.citation_coverage.answer_count == 1
    assert answer.citation_coverage.sourced_answer_count == 0
    assert answer.citation_coverage.sourced_answer_ratio == Decimal("0.00")
    assert answer.citation_coverage.target_met is False
