"""#178: the downstream sites named in the issue as needing the SAME predicate
as the initial-slot guard, tested directly.

The primary #178 fix (``providers._live_openrouter_response``) means an
``InitialModelAnswer`` built through the real pipeline can no longer carry
invisible-only text with ``status=COMPLETED`` — it is reported FAILED
instead (see ``tests/integration/test_invisible_completion_billing_honesty.py``).
But every function below also accepts a directly-constructed
``InitialModelAnswer`` / ``model_authored_final_text`` — exactly how this
codebase's own unit tests build their inputs (``tests/unit/test_agreement_positions.py``'s
``_answer`` helper bypasses the provider layer entirely) — so each of these
sites is reachable on its own, independent of whether the upstream guard is
ever bypassed, refactored, or fed a differently-constructed answer. #178's
acceptance criterion is "one predicate, applied at every emptiness site, so
no two disagree"; this file is the evidence for the sites that are not
already covered by the primary end-to-end reproduction.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from product_app.costs import cost_estimation_service
from product_app.debate import _opening_synopsis
from product_app.evaluation import _substantive
from product_app.model_slots import ModelSlot
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    estimate_material_claim_count,
)
from product_app.query_runs import InMemoryQueryRunRepository, _result_response
from product_app.synthesis_consensus import classify_model_alignment, compute_consensus_strength

#: #178's own measured reproduction: four ZWSP characters, no other text.
_ZWSP_ONLY = "​​​​"
#: Long enough (>200 chars, ``MATERIAL_CLAIM_CHAR_DENOMINATOR``) that the old
#: ``.strip()``-based length heuristic and the fixed floor-at-1 behaviour
#: produce OBSERVABLY DIFFERENT numbers, not the same answer by coincidence.
_LONG_ZWSP = "​" * 300


def _answer(
    slot: int,
    text: str,
    *,
    status: InitialAnswerStatus = InitialAnswerStatus.COMPLETED,
    provider_path: ProviderPath = ProviderPath.OPENROUTER_SEARCH,
) -> InitialModelAnswer:
    return InitialModelAnswer(
        slot_number=slot,
        model_id=f"prov/model-{slot}",
        display_name=f"Model {slot}",
        answer_text=text,
        sources=[],
        provider_attempt_order=[provider_path],
        provider_path=provider_path,
        fallback_used=False,
        status=status,
        latency_ms=1,
        citation_coverage=CitationCoverage(
            answer_count=1,
            sourced_answer_count=0,
            sourced_answer_ratio=Decimal("0"),
            target_met=False,
        ),
    )


# --- evaluation._substantive -------------------------------------------------


def test_substantive_rejects_a_completed_zwsp_only_answer() -> None:
    answer = _answer(1, _ZWSP_ONLY)
    assert answer.status is InitialAnswerStatus.COMPLETED
    assert _substantive(answer) is False


def test_substantive_accepts_a_completed_real_answer() -> None:
    answer = _answer(1, "A real, visible answer.")
    assert _substantive(answer) is True


# --- synthesis_consensus.compute_consensus_strength --------------------------


def test_compute_consensus_strength_treats_zwsp_only_answers_as_uncompleted() -> None:
    answers = [_answer(n, _ZWSP_ONLY) for n in range(1, 5)]
    # 0 genuinely-completed answers must classify the same as an EMPTY list —
    # not "strong" from four answers clustering on nothing but invisible text.
    assert compute_consensus_strength(answers, []) == compute_consensus_strength([], [])


# --- synthesis_consensus.classify_model_alignment -----------------------------


def test_classify_model_alignment_excludes_zwsp_only_openings_from_completed() -> None:
    answers = [_answer(n, _ZWSP_ONLY) for n in range(1, 5)]
    alignments = classify_model_alignment(answers, [])
    assert all(alignment.completed is False for alignment in alignments), alignments
    assert all(alignment.final_aligned is False for alignment in alignments), alignments


def test_classify_model_alignment_refuses_a_zwsp_only_final_text() -> None:
    """The ``final_text_visible`` gate (paired with the completed-answer gate,
    both now sharing ``is_visible``): a minority opener must NOT be compared
    against a "final answer" that is itself invisible-only.
    """
    answers = [
        _answer(1, "A real minority opinion with substantial content of its own."),
        _answer(2, "The majority position, shared by three models here."),
        _answer(3, "The majority position, shared by three models here."),
        _answer(4, "The majority position, shared by three models here."),
    ]
    alignments = classify_model_alignment(
        answers,
        [],
        model_authored_final_text=_ZWSP_ONLY,
        final_answer_was_templated=False,
    )
    minority = alignments[0]
    assert minority.completed is True
    assert minority.opening_majority is False
    # With a visible final text this would call ``_opening_reflected_in_final``;
    # an invisible one must fall through the SAME "nothing to compare against"
    # path as ``model_authored_final_text=None`` — never silently False from
    # comparing against blank text.
    without_final_text = classify_model_alignment(answers, [])
    assert minority.final_aligned == without_final_text[0].final_aligned


# --- providers.estimate_material_claim_count ----------------------------------


def test_material_claim_count_floors_a_long_zwsp_only_answer_at_one() -> None:
    # Pre-fix, ``len(_LONG_ZWSP.strip())`` == 300 survives untouched (ZWSP is
    # not ``str.isspace()``), so the old heuristic reports
    # ``ceil(300 / 200) == 2`` material claims over an answer with no visible
    # content. The fix floors any invisible-only text at 1, same as "".
    assert estimate_material_claim_count(_LONG_ZWSP) == 1
    assert estimate_material_claim_count("") == 1


def test_material_claim_count_still_scales_with_a_long_real_answer() -> None:
    long_real = "A real sentence with substance. " * 20  # > 200 chars
    assert estimate_material_claim_count(long_real) > 1


# --- query_runs's material-claim filter (``_result_response``) ---------------


def test_result_response_material_claim_count_skips_zwsp_only_slots() -> None:
    """CARDINALITY: the served ``material_claim_count`` must not invent claims
    over slots whose only content is invisible characters, mirroring the
    existing empty-string skip (review A5, same site).
    """
    repository = InMemoryQueryRunRepository()
    account_id = uuid4()
    model_slots = [ModelSlot(slot_number=n, model_id=f"prov/model-{n}") for n in range(1, 5)]
    estimate = cost_estimation_service.estimate(
        query_text="compare options", model_slots=model_slots
    )
    query_run = repository.create(
        account_id=account_id,
        query_text="compare options",
        model_slots=model_slots,
        cost_estimate=estimate,
    )
    answers = [_answer(n, _LONG_ZWSP) for n in range(1, 5)]
    repository.record_initial_answers(query_run.query_run_id, answers)
    query_run = repository.get(query_run.query_run_id)

    response = _result_response(query_run)

    assert response.material_claim_count == 0, (
        "material claims were invented over slots with no visible content: "
        f"{response.material_claim_count}"
    )


def test_result_response_material_claim_count_still_counts_real_answers() -> None:
    repository = InMemoryQueryRunRepository()
    account_id = uuid4()
    model_slots = [ModelSlot(slot_number=n, model_id=f"prov/model-{n}") for n in range(1, 5)]
    estimate = cost_estimation_service.estimate(
        query_text="compare options", model_slots=model_slots
    )
    query_run = repository.create(
        account_id=account_id,
        query_text="compare options",
        model_slots=model_slots,
        cost_estimate=estimate,
    )
    answers = [_answer(n, "A real sentence with substance. " * 20) for n in range(1, 5)]
    repository.record_initial_answers(query_run.query_run_id, answers)
    query_run = repository.get(query_run.query_run_id)

    response = _result_response(query_run)

    assert response.material_claim_count == 4 * 4  # 4 slots x claims-per-slot > 1


# --- debate._opening_synopsis --------------------------------------------------


def test_opening_synopsis_treats_zwsp_only_text_as_no_usable_answer() -> None:
    assert _opening_synopsis(_ZWSP_ONLY) == "No usable answer was returned for this model."


def test_opening_synopsis_still_summarizes_a_real_answer() -> None:
    synopsis = _opening_synopsis("A real answer with a first sentence. And a second one.")
    assert synopsis == "A real answer with a first sentence."
