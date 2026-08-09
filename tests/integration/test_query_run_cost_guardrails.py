from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal
from time import monotonic
from unittest import mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.helpers import isolated_run_semaphore

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

#: The mix the product actually ships (``model_slots.DEFAULT_MODEL_IDS``).
#: WP-G1 migrated slot 4 deepseek -> nvidia; this module was missed, so the
#: money envelope below was being measured against a mix that no longer ships.
DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "nvidia/nemotron-3-nano-30b-a3b",
]

#: issue #16: the guardrail keys off the fail-safe ``max_cost_usd`` bound
#: (worst-case, initial output priced at the enforced cap), while the daily cap
#: tracks the point estimate — so for this mix the per-call confirmation is the
#: binding constraint, not the daily cap.
#:
#: ADR-0028 (synthesis stage moved ``openai/gpt-4o-mini`` -> ``openai/gpt-5-mini``)
#: re-priced synthesis high enough to invert this fixture's whole strategy.
#: MEASURED: the OLD opus-tier mix now bounds at 0.3661 — clear over
#: ``HARD_LIMIT_USD`` (0.25), so it moved from CONFIRM to BLOCK, not just up a
#: little. Worse: the fixed synthesis + two debate rounds now put a FLOOR under
#: every possible 4-slot mix that sits inside the confirmation band on its
#: own, regardless of which four models are chosen — MEASURED, the four
#: CHEAPEST-priced models in the whole catalog (nemotron, gemini-2.5-flash-lite,
#: llama-3.1-8b-instruct, deepseek-chat-v3.1) still bound at 0.1772-0.1779, and
#: that floor barely moves with query length or the per-slot web-search flag.
#: So reaching CONFIRM no longer needs an expensive slot — every mix lands
#: there or above; this fixture is simply the cheapest one available, chosen
#: so it stays clear of ``HARD_LIMIT_USD`` with the biggest margin the catalog
#: allows. MEASURED point 0.1065, bound 0.1779 for ``CONFIRM_QUERY`` below.
#:
#: UNVERIFIED against the live catalog: ``catalog_fetcher.py`` itself flags
#: gemini-2.5-flash-lite, llama-3.1-8b-instruct and deepseek-chat-v3.1 as
#: stale fallback rows (nemotron's row is the one verified exact). Those four
#: are the cheapest the offline catalog has, so this fixture is the best
#: available proof that CONFIRM is reachable at all post-ADR-0028 — but unlike
#: the mix it replaces, its exact numbers could move if those rows are ever
#: corrected. That is an accepted, named tradeoff, not an oversight.
CONFIRM_MODEL_IDS = [
    "nvidia/nemotron-3-nano-30b-a3b",
    "google/gemini-2.5-flash-lite",
    "meta-llama/llama-3.1-8b-instruct",
    "deepseek/deepseek-chat-v3.1",
]
CONFIRM_QUERY = "Compare vendors"

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


def confirmed_request(
    client: TestClient,
    query_text: str,
    model_slots: list[str] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    """Build a create-request body that clears the cost guardrail.

    ADR-0028's pricier synthesis stage means no 4-slot mix reaches the ALLOW
    band any more (MEASURED: even the cheapest four models in the whole
    catalog bound at 0.1772-0.1779, still above ``SOFT_THRESHOLD_USD``). Tests
    below this point are not ABOUT the cost band -- they use a plain create
    call as a means to reach some other behaviour (billing dedup, capacity
    rejection, a stubbed charge outcome) -- so this fetches a real preview
    first and attaches its confirmation token whenever the band requires one,
    the same round-trip a real client makes for every run today.
    """
    headers = dict(headers or {})
    preview = client.post(
        "/v1/query-runs/estimate",
        json={"query_text": query_text, "model_slots": model_slots or DEFAULT_MODEL_IDS},
        headers=headers,
    )
    cost_estimate = preview.json()["cost_estimate"]
    body = acknowledged_request(query_text, model_slots)
    if cost_estimate["threshold_action"] == "require_confirmation":
        body["cost_confirmation"] = {
            "estimated_cost_usd": cost_estimate["estimated_cost_usd"],
            "confirmation_token": cost_estimate["confirmation_token"],
        }
    return body


def test_cheapest_possible_query_still_requires_confirmation() -> None:
    """ADR-0028: the ALLOW band is unreachable at 4 slots, by any mix.

    Until 2026-08-09 this test asserted the DEFAULT mix returned 202 with
    threshold_action "allow" (a no-friction create). ADR-0028's pricier
    synthesis stage means the fixed debate+synthesis overhead alone now bounds
    EVERY possible 4-slot mix above SOFT_THRESHOLD_USD, regardless of which
    models are chosen -- MEASURED: even CONFIRM_MODEL_IDS, the four
    cheapest-priced models in the whole fallback catalog, bound at
    0.1772-0.1779. So there is no create call, of any model mix, that reaches
    "allow" today; every run needs one confirmation. This pins that: the
    cheapest possible query still lands in require_confirmation, and once
    confirmed, the run is admitted and billed exactly like any other confirmed
    run. Turns red if a future change (a cheaper catalog price, a lower
    synthesis cap, a threshold move) makes ALLOW reachable again without
    anyone updating this test, or if confirmation stops working for the
    cheapest mix.
    """
    client = TestClient(app)
    account_id = uuid4()

    preview = client.post(
        "/v1/query-runs",
        json=acknowledged_request(CONFIRM_QUERY, CONFIRM_MODEL_IDS),
        headers={"X-Account-Id": str(account_id)},
    )
    assert preview.status_code == 402
    preview_estimate = preview.json()["detail"]["cost_estimate"]
    assert preview_estimate["threshold_action"] == "require_confirmation"
    assert Decimal(preview_estimate["max_cost_usd"]) > Decimal("0.15")

    response = client.post(
        "/v1/query-runs",
        json={
            **acknowledged_request(CONFIRM_QUERY, CONFIRM_MODEL_IDS),
            "cost_confirmation": {
                "estimated_cost_usd": preview_estimate["estimated_cost_usd"],
                "confirmation_token": preview_estimate["confirmation_token"],
            },
        },
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["cost_estimate"]["threshold_action"] == "require_confirmation"
    event = cost_event_recorder.list_events()[-1]
    assert event.event_type == "cost_guardrail_accepted"
    assert event.account_id == account_id
    assert event.confirmed
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
    non-billing event type.

    ADR-0028's pricier synthesis stage puts the default mix in the CONFIRM
    band for this query (MEASURED: point 0.1145, bound 0.1956), so the
    preview now records ``cost_confirmation_required`` and the create call
    must round-trip the confirmation token — this is exactly the "preview,
    then start it" flow the test's own name describes, just with an extra
    required step. The one-billing-event contract this test proves is
    unaffected by whether the request went through ALLOW or a confirmed
    CONFIRM."""
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
        cost_estimate = estimate.json()["cost_estimate"]
        assert cost_estimate["threshold_action"] == "require_confirmation"
        unit = Decimal(cost_estimate["estimated_cost_usd"])

        created = client.post(
            "/v1/query-runs",
            json={
                **acknowledged_request("Compare these answers"),
                "cost_confirmation": {
                    "estimated_cost_usd": cost_estimate["estimated_cost_usd"],
                    "confirmation_token": cost_estimate["confirmation_token"],
                },
            },
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
        assert types == ["cost_confirmation_required", "cost_guardrail_accepted"]
        previews = [
            e for e in _events_for(account_id) if e.event_type == "cost_confirmation_required"
        ]
        assert [e.query_run_id for e in previews] == [None]
        assert previews[0].account_id == account_id
        assert previews[0].estimated_cost_usd == unit


def test_abandoned_estimate_contributes_no_spend() -> None:
    """A preview the user walked away from must cost nothing.

    ADR-0028's pricier synthesis stage means the shipped default mix now
    bounds into the CONFIRM band even for this short query (MEASURED: point
    0.1145, bound 0.1956) — so the preview records ``cost_confirmation_required``
    rather than ``cost_estimate_previewed`` (the ALLOW-band preview event, see
    ``costs.py``'s event-type mapping). Neither event is spend-counted; the
    "abandoned preview costs nothing" contract this test proves does not
    depend on which of the two non-billing event types was recorded.
    """
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
        assert [e.event_type for e in _events_for(account_id)] == ["cost_confirmation_required"]


def test_repeated_estimates_bill_only_the_run_that_started() -> None:
    """The multiplier is 1 + N (N = preview round-trips), not just 2x:
    "Back to edit" then re-preview must not add another charge.

    ADR-0028's pricier synthesis stage puts the default mix in the CONFIRM
    band (MEASURED: point 0.1145, bound 0.1956), so the final create call
    must carry the confirmation token from the last preview — same round-trip
    a real client makes. Unaffected: the thing this test proves, that N
    preview round-trips bill only once.
    """
    client = TestClient(app)
    account_id = uuid4()
    headers = {"X-Account-Id": str(account_id)}

    with configure_for_tests() as store:
        cost_estimate = None
        for _ in range(3):
            estimate = client.post(
                "/v1/query-runs/estimate",
                json={"query_text": "Compare these answers", "model_slots": DEFAULT_MODEL_IDS},
                headers=headers,
            )
            assert estimate.status_code == 200
            cost_estimate = estimate.json()["cost_estimate"]
        assert cost_estimate is not None
        unit = Decimal(cost_estimate["estimated_cost_usd"])

        created = client.post(
            "/v1/query-runs",
            json={
                **acknowledged_request("Compare these answers"),
                "cost_confirmation": {
                    "estimated_cost_usd": cost_estimate["estimated_cost_usd"],
                    "confirmation_token": cost_estimate["confirmation_token"],
                },
            },
            headers=headers,
        )
        assert created.status_code == 202

        assert len(_billing_events(account_id)) == 1
        assert store.daily_spend_for(account_id) == unit


def test_gate_approval_is_honoured_by_the_create_that_follows() -> None:
    """Split verdict: the preview must not inflate the sum the create
    re-reads. A user shown a passable verdict must not then get an
    unexplained 402.

    ADR-0028's pricier synthesis stage means the default mix's preview is
    "require_confirmation", not "allow" (MEASURED: point 0.1145, bound
    0.1956), so the split-verdict story is now: prior spend leaves room under
    the DAILY CAP for one more run, the preview correctly asks for
    confirmation (not a cap block), and the create call — carrying that
    confirmation — must not then be double-counted against the cap and
    refused anyway.
    """
    client = TestClient(app)
    account_id = uuid4()
    headers = {"X-Account-Id": str(account_id)}

    with configure_for_tests() as store:
        # Prior real spend, close to the $0.20 daily cap but with room for
        # one more default-mix run (point estimate ~$0.1145).
        store.record(
            recorder="cost",
            event_type="cost_guardrail_accepted",
            account_id=account_id,
            query_run_id=uuid4(),
            recorded_at=datetime.now(UTC),
            payload={"estimated_cost_usd": "0.08"},
        )

        estimate = client.post(
            "/v1/query-runs/estimate",
            json={"query_text": "Compare these answers", "model_slots": DEFAULT_MODEL_IDS},
            headers=headers,
        )
        assert estimate.status_code == 200
        cost_estimate = estimate.json()["cost_estimate"]
        assert cost_estimate["threshold_action"] == "require_confirmation"

        created = client.post(
            "/v1/query-runs",
            json={
                **acknowledged_request("Compare these answers"),
                "cost_confirmation": {
                    "estimated_cost_usd": cost_estimate["estimated_cost_usd"],
                    "confirmation_token": cost_estimate["confirmation_token"],
                },
            },
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
#:
#: WP-D re-measured and ratified this: 0.0244 -> 0.0317 against the SHIPPED
#: mix (slot 4 is nvidia, not the deepseek this module used to name). See the
#: envelope test's docstring for the attribution — the admitted run count fell
#: 8 -> 6 BEFORE WP-D, and this constant had been hiding it.
#:
#: ADR-0028 (synthesis stage moved ``openai/gpt-4o-mini`` -> ``openai/gpt-5-mini``)
#: re-priced synthesis high enough to move this again: MEASURED 0.0317 -> 0.1145,
#: and the admitted run count 6 -> 1. This is the direct, intended consequence
#: of the ADR (a pricier synthesis stage means real money moves faster per
#: run), not a side effect of anything in this test file.
PINNED_DEFAULT_MIX_UNIT_USD = Decimal("0.1145")


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


@pytest.fixture(autouse=True)
def _stable_catalog_price() -> Iterator[None]:
    """Pin the catalog price for EVERY test in this module.

    Every threshold assertion here is a statement about a price, and that
    price comes from a PROCESS-GLOBAL catalog cache that other test modules
    prime at import time. MEASURED on this tree: the same ``POST
    /v1/query-runs/estimate`` for the default 4-slot mix returns 0.0261 with
    the cache cold and 0.0244 once ``tests/contract/
    test_api_contract_schemathesis.py`` has been imported — so the input to
    this suite depends on which other modules pytest happened to collect. A
    guardrail suite whose input price is decided by collection order is not
    measuring the guardrail.

    The pin is restored on exit, so it cannot change the price the rest of the
    suite sees.
    """
    with _pinned_static_catalog():
        yield


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

    WP-D re-measurement and ratification (operator-approved).
    ``PINNED_DEFAULT_MIX_UNIT_USD`` moved 0.0244 -> 0.0317 and the admitted
    run count 8 -> 6. Attribution, measured rather than assumed:

    * The 8 -> 6 drop is **pre-existing** and was NOT caused by WP-D. At this
      branch's parent the unit was already 0.0310, and ``floor(0.20/0.0310)``
      is 6. The stale 0.0244 pin had been *hiding* a cut that the earlier
      ``config.py`` cap raise (700->2000, 800->3000) already made.
    * WP-D moves the unit 0.0310 -> 0.0317 through ONE correction to this
      figure: the ``google/gemini-2.5-flash`` fallback output price
      (0.0012 -> 0.0025, measured against the live public catalog). It does
      not change the run count; it makes the number truer.
    * WP-D's other money fix — pricing round 2's prior-critique input, without
      which ``max_cost_usd`` was not a true ceiling — deliberately does NOT
      appear here. It applies to the BOUND only
      (``_cost_components(price_round_two_prior_critique=True)``), because
      charging it on the point path either hard-refused affordable runs or
      broke the breakdown's reconciliation invariant. The daily meter tracks
      the point estimate, so this constant is unaffected by it.

    ADR-0028 re-measurement (2026-08-09, this task): synthesis moved
    ``openai/gpt-4o-mini`` -> ``openai/gpt-5-mini``, a deliberate quality
    decision (see the ADR) with an accepted, measured cost consequence. The
    unit moved 0.0317 -> 0.1145 and the admitted run count 6 -> 1 — every
    default-mix run now bounds into the CONFIRM band on its own (MEASURED
    max_cost_usd 0.1956), so the loop below must round-trip a confirmation
    token for the one run the cap admits, same as every other create call in
    this file post-ADR-0028.

    The decision stands: ``DAILY_CAP_USD`` stays at 0.20. Raising it to
    preserve a bigger run count would be counter-tuning a safety weight to
    hold a metric constant — the envelope shrank because the pricing got more
    honest (WP-D) and then because a genuinely more capable, more expensive
    model was deliberately put on the synthesis stage (ADR-0028) — not
    because the policy changed.

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
    # collection order is not a measurement — the module-wide
    # ``_stable_catalog_price`` fixture pins it for every test here.
    with configure_for_tests() as store:
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
        assert expected_runs == 1, f"default-mix unit price moved: {unit}"

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
            preview_cost_estimate = preview.json()["cost_estimate"]
            body = acknowledged_request("Compare these answers")
            if preview_cost_estimate["threshold_action"] == "require_confirmation":
                # Post-ADR-0028 every default-mix run bounds into CONFIRM on
                # its own, so admission is decided by the daily cap alone --
                # round-trip the token the same way a real client would.
                body["cost_confirmation"] = {
                    "estimated_cost_usd": preview_cost_estimate["estimated_cost_usd"],
                    "confirmation_token": preview_cost_estimate["confirmation_token"],
                }
            created = client.post(
                "/v1/query-runs",
                json=body,
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

    Runs against a PRIVATE capacity semaphore. Draining the process-global one
    and then releasing until ``ValueError`` (the shape this test used to have)
    restores it to its BOUND rather than to the number of permits actually
    drained: with one permit held by an in-flight worker from an earlier test
    it mints a permit the process never had, and that worker's own release
    then raises ``ValueError`` inside
    ``_execute_query_run_with_semaphore_release``'s ``finally`` and kills the
    thread. Measured, and the shape that made the F-01 permit specs
    non-deterministic in a full-suite run — see
    ``tests/helpers.isolated_run_semaphore``.

    ADR-0028's pricier synthesis stage puts the default mix in the CONFIRM
    band (MEASURED: point 0.1145, bound 0.1956), so the request must clear
    the cost guardrail with a confirmation token before it can even reach the
    capacity check this test is about.
    """
    with isolated_run_semaphore(1) as semaphore:
        # At capacity: the single permit is taken, so the request is refused
        # before anything can charge the account or claim its run slot.
        assert semaphore.acquire(blocking=False)

        client = TestClient(app)
        with configure_for_tests() as store:
            session = client.get("/v1/session")
            csrf = session.json()["csrf_token"]
            response = client.post(
                "/v1/query-runs",
                json=confirmed_request(
                    client, "Compare these answers", headers={"x-csrf-token": csrf}
                ),
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


def test_thread_start_failure_neither_bills_nor_orphans_a_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run whose worker thread could not be STARTED is the same failure as
    the 503 above, one statement later — and it used to be left open.

    ``Thread.start()`` raises ``RuntimeError`` under thread exhaustion and
    during interpreter shutdown. The billing event used to be written before
    that call, so the caller was charged for a run that never executed AND was
    left holding a non-terminal run: ``get_active_for_account`` treats it as
    the account's one in-flight run, so every later ``POST /v1/query-runs``
    is a 409 ``ACTIVE_QUERY_EXISTS`` until ``QUERY_RUN_ACTIVE_TTL`` (30
    minutes) expires it. A phantom charge plus a half-hour lockout, from a
    request that did nothing.

    The three things that must hold, none of which held before:
      * no spend-counted event (billing happens only after ``start()`` returns);
      * no non-terminal run left behind (``_abandon_unstarted_run``);
      * the capacity permit is returned (the ``except BaseException`` handler).

    ADR-0028's pricier synthesis stage puts the default mix in the CONFIRM
    band (MEASURED: point 0.1145, bound 0.1956), so the request must clear
    the cost guardrail with a confirmation token before it can reach the
    thread-start failure this test is about.
    """
    import product_app.query_runs as qr

    class _RefusingThread:
        """``Thread`` that cannot be started — the real ``RuntimeError``
        CPython raises when the process is out of threads."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(qr, "Thread", _RefusingThread)

    with isolated_run_semaphore(1) as semaphore:
        # ``raise_server_exceptions=False`` so the 500 is rendered rather than
        # re-raised into the test — we care about the state the server is left
        # in, not about the traceback.
        client = TestClient(app, raise_server_exceptions=False)
        with configure_for_tests() as store:
            session = client.get("/v1/session")
            csrf = session.json()["csrf_token"]
            response = client.post(
                "/v1/query-runs",
                json=confirmed_request(
                    client, "Compare these answers", headers={"x-csrf-token": csrf}
                ),
                headers={"x-csrf-token": csrf},
            )
            assert response.status_code == 500

            session_row = session_repository.get(client.cookies[get_session_cookie_name()])
            assert session_row is not None
            account_id = session_row.account_id

            # Nothing was billed for a run that never ran.
            assert _billing_events(account_id) == [], [
                e.event_type for e in _events_for(account_id)
            ]
            assert store.daily_spend_for(account_id) == Decimal("0")
            assert cost_estimation_service._cumulative_spend_for(account_id) == Decimal("0")
            # ...the account is not locked out of the product for 30 minutes...
            assert query_run_repository.get_active_for_account(account_id) is None
            # ...and the capacity permit came back.
            assert semaphore._value == 1  # noqa: SLF001


def _charge_outcome_stub(outcome: object) -> Callable[..., object]:
    """Force ``try_record_run_charge`` to a chosen outcome, writing nothing.

    The three non-RECORDED outcomes are decided INSIDE the store's lock, at the
    instant of the write, by a rail another request moved. Driving them through
    two real concurrent requests would be a race the test has to win; stubbing
    the outcome exercises the request path's response to each one, which is the
    part that lives in ``query_runs`` and the part these tests are about.
    """

    def _stub(**_kwargs: object) -> object:
        return outcome

    return _stub


def test_a_cap_crossed_between_estimate_and_charge_refuses_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED IF the request path stops refusing on ``OVER_DAILY_CAP``.

    The daily cap is re-tested atomically as the charge is written, because the
    estimate-time read is a whole request stale. When it says the cap is now
    crossed, the run must be refused with the same 402 the estimate-time check
    would have produced -- and it must NOT be left occupying the account's one
    in-flight slot, or the caller is locked out for 30 minutes by
    ACTIVE_QUERY_EXISTS.

    ADR-0028's pricier synthesis stage puts the default mix in the CONFIRM
    band (MEASURED: point 0.1145, bound 0.1956), so the request must clear
    the cost guardrail with a confirmation token to reach the atomic re-check
    at charge time -- the stub below fires there, not at the estimate-time
    gate this confirmation clears.
    """
    from product_app.feedback_store import ChargeOutcome

    monkeypatch.setattr(
        cost_estimation_service,
        "try_record_run_charge",
        _charge_outcome_stub(ChargeOutcome.OVER_DAILY_CAP),
    )
    with isolated_run_semaphore(2):
        client = TestClient(app)
        with configure_for_tests() as store:
            session = client.get("/v1/session")
            csrf = session.json()["csrf_token"]
            response = client.post(
                "/v1/query-runs",
                json=confirmed_request(
                    client, "Compare these answers", headers={"x-csrf-token": csrf}
                ),
                headers={"x-csrf-token": csrf},
            )

            assert response.status_code == 402
            assert response.json()["detail"]["code"] == "COST_LIMIT_EXCEEDED"

            row = session_repository.get(client.cookies[get_session_cookie_name()])
            assert row is not None
            # Refused, so nothing was billed...
            assert store.daily_spend_for(row.account_id) == Decimal("0")
            # ...and the account is not locked out of the product.
            assert query_run_repository.get_active_for_account(row.account_id) is None


def test_a_ceiling_crossed_between_estimate_and_charge_degrades_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED IF the request path stops degrading on ``OVER_GLOBAL_CEILING``.

    The deployment-wide ceiling degrades rather than blocks, so the run is
    accepted (202) and marked so the worker simulates it. Distinct from the
    daily cap above, which refuses -- the caller sees a completely different
    outcome and the difference is the point.

    ADR-0028's pricier synthesis stage puts the default mix in the CONFIRM
    band (MEASURED: point 0.1145, bound 0.1956), so the request must clear
    the cost guardrail with a confirmation token to reach the atomic re-check
    at charge time, where the stub below fires.
    """
    from product_app.feedback_store import ChargeOutcome

    monkeypatch.setattr(
        cost_estimation_service,
        "try_record_run_charge",
        _charge_outcome_stub(ChargeOutcome.OVER_GLOBAL_CEILING),
    )
    with isolated_run_semaphore(2):
        client = TestClient(app)
        with configure_for_tests():
            session = client.get("/v1/session")
            csrf = session.json()["csrf_token"]
            response = client.post(
                "/v1/query-runs",
                json=confirmed_request(
                    client, "Compare these answers", headers={"x-csrf-token": csrf}
                ),
                headers={"x-csrf-token": csrf},
            )

            assert response.status_code == 202
            run = query_run_repository.get(UUID(response.json()["query_run_id"]))
            assert run.cost_estimate.global_ceiling_reached is True
            # The OTHER degrade cause must not be claimed as well.
            assert run.cost_estimate.spend_metering_unavailable is False


def test_a_ledger_that_goes_unmeterable_mid_request_degrades_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED IF the request path stops degrading on ``METERING_UNAVAILABLE``.

    ADR-0016. Same effect as the ceiling, DIFFERENT cause, and the two must not
    be conflated: the flags drive different user-facing copy, and reporting a
    storage fault as a spend ceiling puts a false reason on screen.

    ADR-0028's pricier synthesis stage puts the default mix in the CONFIRM
    band (MEASURED: point 0.1145, bound 0.1956), so the request must clear
    the cost guardrail with a confirmation token to reach the atomic re-check
    at charge time, where the stub below fires.
    """
    from product_app.feedback_store import ChargeOutcome

    monkeypatch.setattr(
        cost_estimation_service,
        "try_record_run_charge",
        _charge_outcome_stub(ChargeOutcome.METERING_UNAVAILABLE),
    )
    with isolated_run_semaphore(2):
        client = TestClient(app)
        with configure_for_tests():
            session = client.get("/v1/session")
            csrf = session.json()["csrf_token"]
            response = client.post(
                "/v1/query-runs",
                json=confirmed_request(
                    client, "Compare these answers", headers={"x-csrf-token": csrf}
                ),
                headers={"x-csrf-token": csrf},
            )

            assert response.status_code == 202
            run = query_run_repository.get(UUID(response.json()["query_run_id"]))
            assert run.cost_estimate.spend_metering_unavailable is True
            assert run.cost_estimate.global_ceiling_reached is False


def test_the_legacy_path_refuses_on_a_crossed_cap_exactly_like_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED IF the legacy/test path stops mirroring the production decision.

    The legacy path runs the query INLINE so the suite can assert against the
    final state synchronously. That makes it the path most of this repo's tests
    exercise -- so a rail enforced only on the production path would be a rail
    whose tests pass while production overspends, and vice versa. Kept in step
    deliberately.

    ADR-0028's pricier synthesis stage puts the default mix in the CONFIRM
    band (MEASURED: point 0.1145, bound 0.1956), so the request must clear
    the cost guardrail with a confirmation token to reach the atomic re-check
    at charge time, where the stub below fires.
    """
    from product_app.feedback_store import ChargeOutcome

    monkeypatch.setattr(
        cost_estimation_service,
        "try_record_run_charge",
        _charge_outcome_stub(ChargeOutcome.OVER_DAILY_CAP),
    )
    account_id = uuid4()
    with configure_for_tests() as store:
        client = TestClient(app)
        headers = {"X-Account-Id": str(account_id)}
        response = client.post(
            "/v1/query-runs",
            json=confirmed_request(client, "Compare these answers", headers=headers),
            headers=headers,
        )

        assert response.status_code == 402
        assert response.json()["detail"]["code"] == "COST_LIMIT_EXCEEDED"
        assert store.daily_spend_for(account_id) == Decimal("0")
        assert query_run_repository.get_active_for_account(account_id) is None
