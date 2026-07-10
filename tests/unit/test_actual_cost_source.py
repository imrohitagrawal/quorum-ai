"""Item 1 of the PR #7 coordinated backend follow-ups.

Per-call provider-usage capture is not yet plumbed through the pipeline, so
``actual_cost_usd`` / ``actual_breakdown`` are the pre-run ESTIMATE on every
run (demo and live). The response therefore tags the provenance with
``cost_source`` so the UI can label an estimate as such instead of presenting
it as a measured "actual". These network-free tests pin that contract.
"""

from decimal import Decimal
from types import SimpleNamespace

from product_app.costs import CostEstimate, CostThresholdAction
from product_app.query_runs import QueryRunResultResponse, _actual_cost


def _estimate(value: str) -> CostEstimate:
    return CostEstimate(
        estimated_cost_usd=Decimal(value),
        threshold_action=CostThresholdAction.ALLOW,
        confirmation_token=None,
        reasons=[],
    )


def test_actual_cost_returns_the_estimate_tagged_estimated() -> None:
    est = _estimate("0.0400")
    run = SimpleNamespace(cost_estimate=est)
    actual, breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert actual == est.estimated_cost_usd
    assert breakdown is est.breakdown
    # Only "estimated" is emitted today — usage capture is not yet plumbed.
    assert source == "estimated"


def test_cost_source_field_defaults_to_estimated() -> None:
    field = QueryRunResultResponse.model_fields["cost_source"]
    assert field.default == "estimated"
