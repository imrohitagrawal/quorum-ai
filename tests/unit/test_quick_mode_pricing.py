"""W5, first pull request: how a quick answer is priced, bound and confirmed.

ADR-0126. A quick answer is one model's sourced answer and the judge. Its
estimate and its fail-safe bound share the panel arithmetic
(``_cost_components`` with ``quick=True``), its partitions carry no debate,
synthesis or writer row, its confirmation token binds a third shape,
``"quick"``, and its measured receipt has the same rows as its estimate.

Every test names what turns it red.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from time import monotonic

import pytest

from product_app.catalog_fetcher import _FALLBACK_CATALOG, openrouter_catalog_fetcher
from product_app.config import settings
from product_app.costs import (
    CRITIQUE_SHAPE_MODERATOR,
    CRITIQUE_SHAPE_QUICK,
    CostEstimationService,
    build_measured_breakdown,
    panel_key,
    token_shape,
)
from product_app.model_slots import MODE_PANEL, MODE_QUICK, ModelSlot
from product_app.query_run_orchestration import ALLOWED_TRANSITIONS, QueryRunStatus

QUERY = "What is the capital of Australia and why was it chosen?"
ONE = [ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini", search=True)]
TWO = [*ONE, ModelSlot(slot_number=2, model_id="anthropic/claude-haiku-4.5", search=True)]


@pytest.fixture(autouse=True)
def _pinned_fallback_catalog() -> Iterator[None]:
    fetcher = openrouter_catalog_fetcher
    previous = (fetcher._cache_entries, fetcher._cache_expires_at)  # noqa: SLF001
    fetcher._cache_entries = list(_FALLBACK_CATALOG)  # noqa: SLF001
    fetcher._cache_expires_at = monotonic() + 86_400.0  # noqa: SLF001
    try:
        yield
    finally:
        fetcher._cache_entries, fetcher._cache_expires_at = previous  # noqa: SLF001


@pytest.fixture
def judge_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured judge, as production runs; no call is made, only priced."""
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", "unused-in-pricing")
    monkeypatch.setattr(settings, "quorum_eval_judge_model_id", "openai/gpt-4o-mini")


def _service() -> CostEstimationService:
    return CostEstimationService(binding_secret="x" * 32)


@pytest.mark.usefixtures("judge_on")
def test_with_the_judge_on_a_quick_estimate_has_the_answer_and_judge_rows_only() -> None:
    """Owner, D1: "judge on, cost gate kept". RED IF the judge row is dropped
    from a quick estimate, a debate/synthesis/writer row appears, a partition
    stops summing to the total, or the point passes the bound."""
    estimate = _service().estimate(query_text=QUERY, model_slots=ONE, mode=MODE_QUICK)
    by_stage = estimate.breakdown.by_stage
    by_model = estimate.breakdown.by_model
    assert [line.stage for line in by_stage] == ["initial_answers", "judge"]
    assert [line.kind for line in by_model] == ["model", "judge"]
    assert all(line.usd > 0 for line in by_stage)
    total = estimate.breakdown.total
    assert sum((line.usd for line in by_stage), Decimal(0)) == total
    assert sum((line.usd for line in by_model), Decimal(0)) == total
    assert estimate.max_cost_usd is not None
    assert Decimal(0) < estimate.estimated_cost_usd <= estimate.max_cost_usd


@pytest.mark.usefixtures("judge_on")
def test_a_quick_bound_prices_no_debate_or_synthesis() -> None:
    """The bound shares the arithmetic. RED IF the quick bound still prices
    two debate rounds and five synthesis sections: it would then exceed the
    panel-of-two bound minus that panel's second answer, which it must not.
    Positive partner: it is above zero and above its own point estimate."""
    service = _service()
    quick = service._estimate_bound_usd(  # noqa: SLF001
        query_text=QUERY, model_slots=ONE, mode=MODE_QUICK
    )
    panel = service._estimate_bound_usd(query_text=QUERY, model_slots=TWO)  # noqa: SLF001
    point = service.estimate(query_text=QUERY, model_slots=ONE, mode=MODE_QUICK)
    assert Decimal(0) < point.estimated_cost_usd <= quick
    # A panel of two costs its debate and synthesis on top of two answers; a
    # quick bound is the one answer and the judge, so it is well under half.
    assert quick * 2 < panel


def test_the_panel_path_still_refuses_one_slot_and_quick_refuses_two() -> None:
    """RED IF the quick count check widened the panel range, or the reverse."""
    service = _service()
    with pytest.raises(ValueError, match="between 2 and 4"):
        service.estimate(query_text=QUERY, model_slots=ONE)
    with pytest.raises(ValueError, match="exactly one slot"):
        service.estimate(query_text=QUERY, model_slots=TWO, mode=MODE_QUICK)


def test_a_quick_token_binds_the_quick_shape_and_a_panel_token_does_not() -> None:
    """ADR-0123 binds (panel, shape). RED IF a quick estimate mints with the
    panel's shape, so a quick quote could confirm a panel run pricing the same
    list, or if ``token_shape`` answers "quick" for a panel."""
    assert token_shape(MODE_QUICK) == CRITIQUE_SHAPE_QUICK == "quick"
    assert token_shape(MODE_PANEL) == CRITIQUE_SHAPE_MODERATOR  # peer critique is off here
    service = _service()
    service.estimate(query_text=QUERY, model_slots=ONE, mode=MODE_QUICK)
    (record,) = service._tokens.values()  # noqa: SLF001
    assert record.critique_shape == CRITIQUE_SHAPE_QUICK
    assert record.panel == panel_key(ONE)
    # The verifier refuses the same panel under the panel shape and consumes
    # the token (ADR-0123); a fresh quick token under the quick shape confirms.
    assert (
        service._verify_confirmation_token(  # noqa: SLF001
            token=record.token,
            account_id=None,
            estimated_cost_usd=record.estimated_cost_usd,
            panel=panel_key(ONE),
            critique_shape=token_shape(MODE_PANEL),
        )
        is False
    )
    assert len(service._tokens) == 0  # noqa: SLF001
    service.estimate(query_text=QUERY, model_slots=ONE, mode=MODE_QUICK)
    (record,) = service._tokens.values()  # noqa: SLF001
    assert (
        service._verify_confirmation_token(  # noqa: SLF001
            token=record.token,
            account_id=None,
            estimated_cost_usd=record.estimated_cost_usd,
            panel=panel_key(ONE),
            critique_shape=token_shape(MODE_QUICK),
        )
        is True
    )


def test_a_quick_receipt_has_the_rows_its_estimate_has() -> None:
    """Cardinality (rule 6b): the answer row and the judge row, no debate,
    synthesis or writer row. RED IF the quick receipt emits the panel's four
    stage rows at $0, which the receipt pairs against nothing."""
    breakdown = build_measured_breakdown(
        per_model_initial=[("openai/gpt-4o-mini", "GPT-4o mini", Decimal("0.0031"))],
        debate_by_round={},
        synthesis_cost=Decimal(0),
        judge=("openai/gpt-4o-mini", Decimal("0.0012")),
        quick=True,
    )
    assert [line.stage for line in breakdown.by_stage] == ["initial_answers", "judge"]
    assert [line.kind for line in breakdown.by_model] == ["model", "judge"]
    assert breakdown.total == Decimal("0.0043")
    assert sum((line.usd for line in breakdown.by_stage), Decimal(0)) == breakdown.total
    # Positive partner: the panel receipt of the same spend keeps its rows.
    panel = build_measured_breakdown(
        per_model_initial=[("openai/gpt-4o-mini", "GPT-4o mini", Decimal("0.0031"))],
        debate_by_round={},
        synthesis_cost=Decimal(0),
        judge=("openai/gpt-4o-mini", Decimal("0.0012")),
    )
    assert len(panel.by_stage) == 5


def test_debate_spend_on_a_quick_receipt_is_refused_not_hidden() -> None:
    """RED IF debate or synthesis money on a quick run is silently dropped
    from the receipt; raising makes ``_actual_cost`` fall back to the
    estimate, so the money is never shown as lower than it was."""
    for extra in (
        {"debate_by_round": {1: Decimal("0.001")}, "synthesis_cost": Decimal(0)},
        {"debate_by_round": {}, "synthesis_cost": Decimal("0.001")},
    ):
        with pytest.raises(ValueError, match="no debate or synthesis"):
            build_measured_breakdown(
                per_model_initial=[("m/x", "X", Decimal("0.001"))], quick=True, **extra
            )


def test_a_quick_answer_can_complete_after_its_one_answer() -> None:
    """RED IF the transition table has no INITIAL_ANSWERS_RUNNING -> COMPLETED
    edge (the quick run path writes it)."""
    assert QueryRunStatus.COMPLETED in ALLOWED_TRANSITIONS[QueryRunStatus.INITIAL_ANSWERS_RUNNING]


def test_a_measured_quick_run_gets_the_quick_receipt_through_actual_cost() -> None:
    """The wire, not just the builder: ``_actual_cost`` must pass the run's
    shape on. RED IF the call site drops ``quick=`` (the receipt then carries
    the panel's four stage rows and its writer row at $0)."""
    from types import SimpleNamespace
    from uuid import uuid4

    from product_app.costs import CostEstimate, CostThresholdAction
    from product_app.providers import (
        CitationCoverage,
        InitialAnswerStatus,
        InitialModelAnswer,
        ProviderPath,
        SourceReference,
        TokenUsage,
    )
    from product_app.query_run_orchestration import (
        BillableStage,
        StageBillingState,
        _actual_cost,
    )

    answer = InitialModelAnswer(
        slot_number=1,
        model_id=ONE[0].model_id,
        display_name=ONE[0].model_id,
        answer_text="An answer.",
        searched=True,
        sources=[
            SourceReference(
                title="s", url="https://example.com/s", provider=ProviderPath.OPENROUTER_SEARCH
            )
        ],
        provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
        provider_path=ProviderPath.OPENROUTER_SEARCH,
        fallback_used=False,
        status=InitialAnswerStatus.COMPLETED,
        latency_ms=10,
        citation_coverage=CitationCoverage(
            answer_count=1,
            sourced_answer_count=1,
            sourced_answer_ratio=Decimal("1"),
            target_met=True,
        ),
        token_usage=TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500),
    )
    run = SimpleNamespace(
        query_run_id=uuid4(),
        mode=MODE_QUICK,
        debate_outputs=[],
        cost_estimate=CostEstimate(
            estimated_cost_usd=Decimal("0.0100"),
            threshold_action=CostThresholdAction.ALLOW,
            confirmation_token=None,
            reasons=[],
        ),
        model_slots=ONE,
        initial_answers=[answer],
        debate_call_usages=[],
        synthesis_call_usages=[],
        billing_stages=dict.fromkeys(BillableStage, StageBillingState.NOT_ENTERED),
    )
    actual, breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "measured"
    assert breakdown is not None
    assert [line.stage for line in breakdown.by_stage] == ["initial_answers"]
    assert [line.kind for line in breakdown.by_model] == ["model"]
    assert actual == breakdown.total > 0
