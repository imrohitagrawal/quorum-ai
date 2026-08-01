"""Issue #100 §2.6: the PRE-run banner needs a deployment-level signal that
fires BEFORE any query run exists — ``/ready`` is that surface. Distinct
from the per-run ``global_spend_ceiling_reached`` field on
``QueryRunResultResponse`` (issue #100 PR1): this one is read at page load,
before a user has submitted anything.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from product_app.costs import GLOBAL_DAILY_CEILING_USD
from product_app.feedback_store import FeedbackStore, configure_for_tests
from product_app.main import app


def _seed_accepted(store: FeedbackStore, usd: str) -> None:
    store.record(
        recorder="cost",
        event_type="cost_guardrail_accepted",
        account_id=uuid4(),
        query_run_id=None,
        recorded_at=datetime.now(UTC),
        payload={"estimated_cost_usd": usd},
    )


def test_ready_reports_ceiling_not_reached_by_default() -> None:
    with configure_for_tests():
        body = TestClient(app).get("/ready").json()
    assert body["live_readiness"]["global_spend_ceiling_reached"] is False


def test_ready_reports_ceiling_reached_once_tripped() -> None:
    with configure_for_tests() as store:
        _seed_accepted(store, str(GLOBAL_DAILY_CEILING_USD))
        body = TestClient(app).get("/ready").json()
    assert body["live_readiness"]["global_spend_ceiling_reached"] is True


def test_ready_ceiling_field_is_false_when_no_store_configured() -> None:
    """Fail open, same posture as every other durable-store bypass in this
    codebase — matches CostEstimationService.estimate()'s own fail-open."""
    from product_app.feedback_store import configure, get_store

    original = get_store()
    try:
        configure(None)
        body = TestClient(app).get("/ready").json()
        assert body["live_readiness"]["global_spend_ceiling_reached"] is False
    finally:
        configure(original)


def test_ui_page_load_seed_carries_the_ceiling_field_too() -> None:
    """The pre-run banner must render on FIRST PAINT, before any /ready
    round-trip completes — so the server-rendered ``window.LIVE_READINESS``
    data island needs the same field, not just the live /ready endpoint."""
    with configure_for_tests() as store:
        _seed_accepted(store, str(GLOBAL_DAILY_CEILING_USD))
        html = TestClient(app).get("/ui").text
    assert "window.LIVE_READINESS" in html
    marker = "window.LIVE_READINESS = "
    start = html.index(marker) + len(marker)
    end = html.index(";", start)
    import json

    seeded = json.loads(html[start:end])
    assert seeded["global_spend_ceiling_reached"] is True
