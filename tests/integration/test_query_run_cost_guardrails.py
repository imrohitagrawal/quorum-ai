from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal
from time import monotonic
from unittest import mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.auth import get_session_cookie_name, session_repository
from product_app.catalog_fetcher import _FALLBACK_CATALOG, openrouter_catalog_fetcher
from product_app.costs import (
    DAILY_CAP_USD,
    HARD_LIMIT_USD,
    SOFT_THRESHOLD_USD,
    CostGuardrailEvent,
    cost_estimation_service,
    cost_event_recorder,
)
from product_app.feedback_store import configure_for_tests
from product_app.main import app
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]

#: issue #16: the guardrail keys off the fail-safe ``max_cost_usd`` bound
#: (worst-case, initial output priced at the enforced cap). One opus slot +
#: three cheap slots lands the BOUND at ~$0.21 (in the (0.15, 0.25] CONFIRM
#: band) while the realistic point estimate is only ~$0.10 — under the $0.20
#: daily cap (which tracks the point estimate), so the per-call confirmation is
#: the binding constraint, not the daily cap. A full opus-tier mix would push
#: the bound over $0.25 into BLOCK.
CONFIRM_MODEL_IDS = [
    "anthropic/claude-opus-4",
    "openai/gpt-4o-mini",
    "deepseek/deepseek-chat-v3.1",
    "google/gemini-2.5-flash",
]
CONFIRM_QUERY = "x" * 2_500

#: A full opus-tier mix — its bound exceeds the $0.25 hard limit → BLOCK.
BLOCKED_MODEL_IDS = [
    "openai/gpt-4.1",
    "anthropic/claude-opus-4",
    "google/gemini-2.5-pro",
    "openai/o3",
]


@pytest.fixture(autouse=True)
def clear_state() -> None:
    query_run_repository.clear()
    cost_event_recorder.clear()


def acknowledged_request(
    query_text: str, model_slots: list[str] | None = None
) -> dict[str, object]:
    return {
        "query_text": query_text,
        "model_slots": model_slots or DEFAULT_MODEL_IDS,
        "safety_acknowledgements": [
            {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
        ],
    }


def test_normal_cost_query_is_accepted_with_cost_estimate() -> None:
    client = TestClient(app)
    account_id = uuid4()

    response = client.post(
        "/v1/query-runs",
        json=acknowledged_request("Compare these answers"),
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 202
    body = response.json()
    assert Decimal(body["cost_estimate"]["estimated_cost_usd"]) <= Decimal("0.15")
    assert body["cost_estimate"]["threshold_action"] == "allow"
    event = cost_event_recorder.list_events()[0]
    assert event.event_type == "cost_guardrail_accepted"
    assert event.account_id == account_id
    assert not event.confirmed
    assert not hasattr(event, "query_text")


def test_high_cost_query_requires_confirmation_before_creation() -> None:
    client = TestClient(app)
    account_id = uuid4()

    response = client.post(
        "/v1/query-runs",
        json=acknowledged_request(CONFIRM_QUERY, CONFIRM_MODEL_IDS),
        headers={"X-Account-Id": str(account_id)},
    )

    # The guardrail keys off the fail-safe max_cost_usd bound (~$0.21 here) —
    # in the soft band (above USD 0.15) — while the point estimate (~$0.10) is
    # under the USD 0.20 daily cap. So the per-call confirmation is the binding
    # constraint and the create endpoint mints a confirmation token.
    assert response.status_code == 402
    body = response.json()
    assert body["detail"]["code"] == "COST_CONFIRMATION_REQUIRED"
    assert body["detail"]["cost_estimate"]["threshold_action"] == "require_confirmation"
    # The rail keys off the worst-case bound: max_cost_usd crosses USD 0.15
    # while the realistic point estimate stays under it.
    cost_estimate = body["detail"]["cost_estimate"]
    assert Decimal(cost_estimate["max_cost_usd"]) > Decimal("0.15")
    assert Decimal(cost_estimate["estimated_cost_usd"]) < Decimal("0.15")
    assert query_run_repository.get_active_for_account(account_id) is None
    assert cost_event_recorder.list_events()[0].event_type == "cost_confirmation_required"


def test_high_cost_query_accepts_matching_confirmation_token() -> None:
    client = TestClient(app)
    account_id = uuid4()
    request_body = acknowledged_request(CONFIRM_QUERY, CONFIRM_MODEL_IDS)
    confirmation_response = client.post(
        "/v1/query-runs",
        json=request_body,
        headers={"X-Account-Id": str(account_id)},
    )
    cost_estimate = confirmation_response.json()["detail"]["cost_estimate"]

    accepted_response = client.post(
        "/v1/query-runs",
        json={
            **request_body,
            "cost_confirmation": {
                "estimated_cost_usd": cost_estimate["estimated_cost_usd"],
                "confirmation_token": cost_estimate["confirmation_token"],
            },
        },
        headers={"X-Account-Id": str(account_id)},
    )

    assert accepted_response.status_code == 202
    assert accepted_response.json()["cost_estimate"]["threshold_action"] == "require_confirmation"
    assert cost_event_recorder.list_events()[-1].event_type == "cost_guardrail_accepted"
    assert cost_event_recorder.list_events()[-1].confirmed


def test_over_limit_query_is_blocked_even_with_confirmation_shape() -> None:
    client = TestClient(app)
    account_id = uuid4()
    blocked_models = [
        "openai/gpt-4.1",
        "anthropic/claude-opus-4",
        "google/gemini-2.5-pro",
        "openai/o3",
    ]

    response = client.post(
        "/v1/query-runs",
        json={
            **acknowledged_request("x" * 8_000, blocked_models),
            "cost_confirmation": {
                "estimated_cost_usd": "0.3000",
                "confirmation_token": "cost_v1_user_supplied",
            },
        },
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 402
    assert response.json()["detail"]["code"] == "COST_LIMIT_EXCEEDED"
    assert response.json()["detail"]["cost_estimate"]["threshold_action"] == "block"
    assert query_run_repository.get_active_for_account(account_id) is None
    assert cost_event_recorder.list_events()[0].event_type == "cost_guardrail_blocked"


# ---------------------------------------------------------------------------
# F-01: one logical run must be billed exactly once.
#
# ``POST /v1/query-runs/estimate`` is a PREVIEW — nothing has been spent when
# it returns. It must still leave an audit trail, but that trail must not be
# an event type the spend guards count. Both guards
# (``CostEstimationService._cumulative_spend_for`` and
# ``FeedbackStore.daily_spend_for``) count exactly and only
# ``cost_guardrail_accepted``, so a preview that records that type bills the
# user for a run that has not happened.
# ---------------------------------------------------------------------------


def _events_for(account_id: UUID) -> list[CostGuardrailEvent]:
    """Cost events for ONE account.

    ``cost_event_recorder`` is a process-global ring buffer. The module's
    ``clear_state`` fixture empties it per test, but an assertion over the
    whole buffer is still coupled to every other writer in the process — and
    these tests are the ones that pin an EXACT event sequence, so they are
    the most sensitive to that coupling. Every ``account_id`` here is a fresh
    ``uuid4()``, so scoping by account keeps the assertions exact while
    making them independent of anything else the suite records.
    """
    return [e for e in cost_event_recorder.list_events() if e.account_id == account_id]


def _billing_events(account_id: UUID) -> list[CostGuardrailEvent]:
    return [e for e in _events_for(account_id) if e.event_type == "cost_guardrail_accepted"]


def test_estimate_then_create_records_exactly_one_billing_event() -> None:
    """One logical run (preview the estimate, then start it) must produce
    exactly ONE spend-counted cost event, and it must be the one carrying the
    real ``query_run_id``. The preview must survive in the audit trail under a
    non-billing event type."""
    client = TestClient(app)
    account_id = uuid4()
    headers = {"X-Account-Id": str(account_id)}

    with configure_for_tests() as store:
        estimate = client.post(
            "/v1/query-runs/estimate",
            json={"query_text": "Compare these answers", "model_slots": DEFAULT_MODEL_IDS},
            headers=headers,
        )
        assert estimate.status_code == 200
        assert estimate.json()["cost_estimate"]["threshold_action"] == "allow"
        unit = Decimal(estimate.json()["cost_estimate"]["estimated_cost_usd"])

        created = client.post(
            "/v1/query-runs",
            json=acknowledged_request("Compare these answers"),
            headers=headers,
        )
        assert created.status_code == 202

        # A1: exactly one billing-counted event for one logical run.
        billing = _billing_events(account_id)
        assert len(billing) == 1, [e.event_type for e in _events_for(account_id)]
        # A2: the surviving charge is the real run, not the preview.
        assert billing[0].query_run_id == UUID(created.json()["query_run_id"])
        # A3: the durable daily cap sees one estimate, not two.
        assert store.daily_spend_for(account_id) == unit
        # A3b: so does the in-memory cumulative guard.
        assert cost_estimation_service._cumulative_spend_for(account_id) == unit
        # A4: the audit trail still shows that a preview happened — the fix
        # must not be "delete the estimate event".
        types = [e.event_type for e in _events_for(account_id)]
        assert types == ["cost_estimate_previewed", "cost_guardrail_accepted"]
        previews = [e for e in _events_for(account_id) if e.event_type == "cost_estimate_previewed"]
        assert [e.query_run_id for e in previews] == [None]
        assert previews[0].account_id == account_id
        assert previews[0].estimated_cost_usd == unit


def test_abandoned_estimate_contributes_no_spend() -> None:
    """A preview the user walked away from must cost nothing."""
    client = TestClient(app)
    account_id = uuid4()

    with configure_for_tests() as store:
        estimate = client.post(
            "/v1/query-runs/estimate",
            json={"query_text": "Compare these answers", "model_slots": DEFAULT_MODEL_IDS},
            headers={"X-Account-Id": str(account_id)},
        )
        assert estimate.status_code == 200

        assert store.daily_spend_for(account_id) == Decimal("0")
        assert cost_estimation_service._cumulative_spend_for(account_id) == Decimal("0")
        # ...but the operator can still see the preview happened.
        assert [e.event_type for e in _events_for(account_id)] == ["cost_estimate_previewed"]


def test_repeated_estimates_bill_only_the_run_that_started() -> None:
    """The multiplier is 1 + N (N = preview round-trips), not just 2x:
    "Back to edit" then re-preview must not add another charge."""
    client = TestClient(app)
    account_id = uuid4()
    headers = {"X-Account-Id": str(account_id)}

    with configure_for_tests() as store:
        unit = None
        for _ in range(3):
            estimate = client.post(
                "/v1/query-runs/estimate",
                json={"query_text": "Compare these answers", "model_slots": DEFAULT_MODEL_IDS},
                headers=headers,
            )
            assert estimate.status_code == 200
            unit = Decimal(estimate.json()["cost_estimate"]["estimated_cost_usd"])

        created = client.post(
            "/v1/query-runs",
            json=acknowledged_request("Compare these answers"),
            headers=headers,
        )
        assert created.status_code == 202

        assert len(_billing_events(account_id)) == 1
        assert store.daily_spend_for(account_id) == unit


def test_gate_approval_is_honoured_by_the_create_that_follows() -> None:
    """Split verdict: the preview must not inflate the sum the create
    re-reads. A user shown "allow" must not then get a 402."""
    client = TestClient(app)
    account_id = uuid4()
    headers = {"X-Account-Id": str(account_id)}

    with configure_for_tests() as store:
        # Prior real spend, close to the $0.20 daily cap but with room for
        # one more default-mix run (~$0.026).
        store.record(
            recorder="cost",
            event_type="cost_guardrail_accepted",
            account_id=account_id,
            query_run_id=uuid4(),
            recorded_at=datetime.now(UTC),
            payload={"estimated_cost_usd": "0.16"},
        )

        estimate = client.post(
            "/v1/query-runs/estimate",
            json={"query_text": "Compare these answers", "model_slots": DEFAULT_MODEL_IDS},
            headers=headers,
        )
        assert estimate.status_code == 200
        assert estimate.json()["cost_estimate"]["threshold_action"] == "allow"

        created = client.post(
            "/v1/query-runs",
            json=acknowledged_request("Compare these answers"),
            headers=headers,
        )
        assert created.status_code == 202, created.json()


def test_estimate_time_block_still_records_blocked_and_pages_sentry() -> None:
    """Guard (green before AND after the F-01 fix): an estimate-time BLOCK
    must keep recording ``cost_guardrail_blocked`` and must keep reaching
    Sentry. The preview relabelling must not touch the BLOCK path."""
    client = TestClient(app)
    account_id = uuid4()

    with mock.patch("sentry_sdk.capture_message") as capture:
        response = client.post(
            "/v1/query-runs/estimate",
            json={"query_text": "x" * 8_000, "model_slots": BLOCKED_MODEL_IDS},
            headers={"X-Account-Id": str(account_id)},
        )

    assert response.status_code == 200
    assert response.json()["cost_estimate"]["threshold_action"] == "block"
    assert [e.event_type for e in _events_for(account_id)] == ["cost_guardrail_blocked"]
    assert capture.called
    assert "cost_guardrail_blocked" in capture.call_args[0][0]


# ---------------------------------------------------------------------------
# F-01 follow-up: the money envelope, and the one remaining path that bills a
# run that never executes.
# ---------------------------------------------------------------------------

#: Default 4-slot mix price under the app's own static offline catalog
#: (``catalog_fetcher._FALLBACK_CATALOG``). MEASURED, and re-asserted by the
#: envelope test so a catalog price change surfaces as "re-measure the
#: envelope", never as a silently different envelope.
PINNED_DEFAULT_MIX_UNIT_USD = Decimal("0.0244")


@contextmanager
def _pinned_static_catalog() -> Iterator[None]:
    """Serve the app's static offline catalog, then restore what was there.

    Same seam as ``tests/contract/test_api_contract_schemathesis.py`` and
    ``tests/perf/test_workflow_latency_percentiles.py`` — priming the shared
    fetcher's cache short-circuits ``_cache_valid()`` before any transport is
    touched. Unlike those two this one is scoped and reversible: it must not
    change the price the rest of the suite sees.
    """
    fetcher = openrouter_catalog_fetcher
    previous_entries = fetcher._cache_entries  # noqa: SLF001
    previous_expiry = fetcher._cache_expires_at  # noqa: SLF001
    fetcher._cache_entries = list(_FALLBACK_CATALOG)  # noqa: SLF001
    fetcher._cache_expires_at = monotonic() + 86_400.0  # noqa: SLF001
    try:
        yield
    finally:
        fetcher._cache_entries = previous_entries  # noqa: SLF001
        fetcher._cache_expires_at = previous_expiry  # noqa: SLF001


def test_daily_cap_admits_the_number_of_runs_its_dollar_value_pays_for() -> None:
    """The real per-account money envelope, pinned so it cannot move silently.

    ``DAILY_CAP_USD`` is a statement about REAL money: at most that much
    provider spend per account per rolling 24h. Before F-01 the meter that
    enforced it counted every run twice, so the cap admitted only HALF the
    runs its dollar value pays for — MEASURED on the default 4-slot mix:
    3 completed runs before the 402, against a meter reading 0.1827 of which
    only ~0.078 was real spend. Correcting the meter therefore MOVES the real
    envelope (~$0.078 -> ~$0.183 per account per day), which is a money
    decision, not a side effect.

    The decision that ships with the fix is: leave ``DAILY_CAP_USD`` at 0.20.
    That value was never derived from watching production spend — ``git log
    -S 'DAILY_CAP_USD = Decimal("0.20")'`` shows commit 9c50239 ("cost: raise
    daily cap to $0.20 so confirmation band is reachable") chose it from an
    ORDERING constraint: it must sit above ``SOFT_THRESHOLD_USD`` and below
    ``HARD_LIMIT_USD`` or the require-confirmation band becomes dead code.
    So the corrected meter does not invalidate it. (Verified the other way
    too: setting the cap back to 0.10 to preserve the pre-fix real envelope
    re-breaks ``test_high_cost_query_requires_confirmation_before_creation``
    and ``test_high_cost_query_accepts_matching_confirmation_token`` — the
    exact regression 9c50239 fixed.)

    This test states the envelope out loud. Change the meter, or change the
    cap, and it fails — so the next move is a reviewed decision, not a
    side effect.
    """
    # The ordering invariant that actually determines the cap's value.
    assert SOFT_THRESHOLD_USD < DAILY_CAP_USD < HARD_LIMIT_USD
    assert Decimal("0.20") == DAILY_CAP_USD

    client = TestClient(app)
    account_id = uuid4()
    headers = {"X-Account-Id": str(account_id)}

    # The unit price is read from a PROCESS-GLOBAL catalog cache that other
    # test modules pin at import time (``tests/contract/
    # test_api_contract_schemathesis.py::_pin_static_catalog``), so the
    # default-mix price is 0.0261 alone and 0.0244 after that module has been
    # imported. An envelope measured against a price that depends on
    # collection order is not a measurement, so pin it here and restore it.
    with _pinned_static_catalog(), configure_for_tests() as store:
        first = client.post(
            "/v1/query-runs/estimate",
            json={"query_text": "Compare these answers", "model_slots": DEFAULT_MODEL_IDS},
            headers=headers,
        )
        assert first.status_code == 200
        unit = Decimal(first.json()["cost_estimate"]["estimated_cost_usd"])
        assert unit == PINNED_DEFAULT_MIX_UNIT_USD, (
            f"the pinned static catalog's default-mix price moved to {unit}; "
            "re-measure the envelope before updating this constant"
        )
        # The cap admits every run its dollar value pays for, and not one more.
        expected_runs = int((DAILY_CAP_USD / unit).to_integral_value(rounding=ROUND_FLOOR))
        assert expected_runs == 8, f"default-mix unit price moved: {unit}"

        completed = 0
        rejection = None
        for _ in range(expected_runs + 3):
            # Drive it the way the UI does: see the estimate, then start the
            # run. That round-trip is exactly what was being double-billed.
            preview = client.post(
                "/v1/query-runs/estimate",
                json={"query_text": "Compare these answers", "model_slots": DEFAULT_MODEL_IDS},
                headers=headers,
            )
            assert preview.status_code == 200
            created = client.post(
                "/v1/query-runs",
                json=acknowledged_request("Compare these answers"),
                headers=headers,
            )
            if created.status_code != 202:
                rejection = created
                break
            completed += 1

        assert completed == expected_runs, (
            f"real per-account daily envelope moved: {completed} runs completed, "
            f"expected {expected_runs} at unit={unit} against DAILY_CAP_USD={DAILY_CAP_USD}"
        )
        # The meter equals real spend — no phantom charges left anywhere.
        assert store.daily_spend_for(account_id) == unit * completed
        assert unit * completed <= DAILY_CAP_USD
        # ...and the next run really is refused.
        assert rejection is not None
        assert rejection.status_code == 402
        assert rejection.json()["detail"]["code"] == "COST_LIMIT_EXCEEDED"


def test_capacity_rejection_neither_bills_nor_orphans_a_run() -> None:
    """A 503 ``RUN_CAPACITY_EXCEEDED`` is a run that never executes, so it
    must not be billed — and it must not consume the account's single
    active-run slot either, which would lock the account out permanently
    (nothing will ever terminate a run whose worker was never started).

    Uses the cookie session path: the semaphore is only acquired there.
    """
    from product_app.query_runs import _run_semaphore

    while _run_semaphore.acquire(blocking=False):
        pass
    try:
        client = TestClient(app)
        with configure_for_tests() as store:
            session = client.get("/v1/session")
            csrf = session.json()["csrf_token"]
            response = client.post(
                "/v1/query-runs",
                json=acknowledged_request("Compare these answers"),
                headers={"x-csrf-token": csrf},
            )
            assert response.status_code == 503, response.json()
            assert response.json()["detail"]["code"] == "RUN_CAPACITY_EXCEEDED"

            session_row = session_repository.get(client.cookies[get_session_cookie_name()])
            assert session_row is not None
            account_id = session_row.account_id

            # Nothing was billed: no spend-counted event for this account.
            assert _billing_events(account_id) == [], [
                e.event_type for e in _events_for(account_id)
            ]
            assert store.daily_spend_for(account_id) == Decimal("0")
            # ...and no non-terminal run was left holding the account's slot.
            assert query_run_repository.get_active_for_account(account_id) is None
    finally:
        while True:
            try:
                _run_semaphore.release()
            except ValueError:
                break
        query_run_repository.clear()
