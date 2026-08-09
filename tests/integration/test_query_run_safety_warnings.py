from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.main import app
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType, warning_event_recorder
from product_app.synthesis import HIGH_STAKES_NOTICE_FRAGMENT
from product_app.synthesis_length import truncate_recommendation

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


@pytest.fixture(autouse=True)
def clear_state() -> None:
    query_run_repository.clear()
    warning_event_recorder.clear()


def test_warnings_endpoint_returns_privacy_warning_without_raw_prompt_event() -> None:
    client = TestClient(app)
    account_id = uuid4()

    response = client.post(
        "/v1/query-runs/warnings",
        json={"query_text": "Compare vendors"},
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["warnings"][0]["warning_type"] == WarningType.SENSITIVE_DATA
    assert body["warnings"][0]["acknowledgement_required"] is True
    assert warning_event_recorder.list_events()[0].event_type == "safety_warning_impression"
    assert not hasattr(warning_event_recorder.list_events()[0], "query_text")


def test_high_stakes_query_requires_high_stakes_acknowledgement() -> None:
    client = TestClient(app)
    account_id = uuid4()

    response = client.post(
        "/v1/query-runs",
        json={
            "query_text": "Compare legal contract risk",
            "model_slots": DEFAULT_MODEL_IDS,
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
            ],
        },
        headers={"X-Account-Id": str(account_id)},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["code"] == "VALIDATION_ERROR"
    assert body["detail"]["required_warnings"][0]["warning_type"] == WarningType.HIGH_STAKES


def test_query_run_accepts_all_required_warning_acknowledgements() -> None:
    client = TestClient(app)
    account_id = uuid4()
    headers = {"X-Account-Id": str(account_id)}

    response = client.post(
        "/v1/query-runs",
        json=_confirmed(
            client,
            {
                "query_text": "Compare legal contract risk",
                "model_slots": DEFAULT_MODEL_IDS,
                "safety_acknowledgements": [
                    {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
                    {"warning_type": WarningType.HIGH_STAKES, "version": WARNING_VERSION},
                ],
            },
            headers,
        ),
        headers=headers,
    )

    assert response.status_code == 202
    event = warning_event_recorder.list_events()[0]
    assert event.event_type == "safety_acknowledgement_recorded"
    assert set(event.warning_types) == {WarningType.SENSITIVE_DATA, WarningType.HIGH_STAKES}
    assert not hasattr(event, "query_text")


# ---------------------------------------------------------------------------
# Issue #155 — the bypass via ``context``, at the route boundary
# ---------------------------------------------------------------------------

_BENIGN_FOLLOW_UP = "Follow up on the earlier discussion please."
_HOSTILE = "What is the right medical diagnosis and legal contract for my investment loan?"
_OWN_CAVEAT = (
    "This summary is decision support only and is not medical, legal, "
    "financial, safety, or regulated professional advice."
)


def _sensitive_only() -> list[dict[str, str]]:
    return [{"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION}]


def _confirmed(
    client: TestClient, body: dict[str, object], headers: dict[str, str]
) -> dict[str, object]:
    """ADR-0028: attach the confirmation round-trip a plain create now needs.

    No 4-slot mix reaches the ALLOW band any more, so a plain body would 402
    on every create call below — none of which are testing the cost
    guardrail itself. Returns a COPY of ``body`` with ``cost_confirmation``
    attached when the band requires it.
    """
    preview = client.post(
        "/v1/query-runs/estimate",
        json={
            "query_text": body["query_text"],
            "model_slots": body["model_slots"],
            **({"context": body["context"]} if "context" in body else {}),
        },
        headers=headers,
    )
    cost_estimate = preview.json()["cost_estimate"]
    confirmed = dict(body)
    if cost_estimate["threshold_action"] == "require_confirmation":
        confirmed["cost_confirmation"] = {
            "estimated_cost_usd": cost_estimate["estimated_cost_usd"],
            "confirmation_token": cost_estimate["confirmation_token"],
        }
    return confirmed


def test_high_stakes_wording_in_context_is_refused_without_the_acknowledgement() -> None:
    """The bypass the issue demonstrates: benign query_text, hostile context,
    sensitive-data ack only -> used to be 202 Accepted and the run executed.

    Turns red if: the create route stops passing ``context`` to
    ``required_warnings_for_query``.
    """
    client = TestClient(app)
    response = client.post(
        "/v1/query-runs",
        json={
            "query_text": _BENIGN_FOLLOW_UP,
            "model_slots": DEFAULT_MODEL_IDS,
            "context": {"prior_synthesis": _HOSTILE},
            "safety_acknowledgements": _sensitive_only(),
        },
        headers={"X-Account-Id": str(uuid4())},
    )

    assert response.status_code == 422, response.text
    assert WarningType.HIGH_STAKES in response.text


def test_a_follow_up_carrying_this_apps_own_synthesis_is_still_accepted() -> None:
    """The direction the reverted fix broke. ``synthesis_length`` puts that
    caveat in 100% of recommendations, so this is the ORDINARY follow-up, and
    a fix that 422s it has made the feature unusable.

    Turns red if: the context is scanned without removing the app's own
    caveat first.
    """
    client = TestClient(app)
    headers = {"X-Account-Id": str(uuid4())}
    response = client.post(
        "/v1/query-runs",
        json=_confirmed(
            client,
            {
                "query_text": _BENIGN_FOLLOW_UP,
                "model_slots": DEFAULT_MODEL_IDS,
                "context": {"prior_synthesis": f"The rollout succeeded. {_OWN_CAVEAT}"},
                "safety_acknowledgements": _sensitive_only(),
            },
            headers,
        ),
        headers=headers,
    )

    assert response.status_code == 202, response.text


def test_the_warnings_probe_and_the_create_route_agree_about_context() -> None:
    """The unbreakable 422 loop, closed.

    A client following the documented flow probes ``/warnings``, acknowledges
    exactly what it was told, then creates. Before ``context`` existed on the
    probe, the probe omitted ``high_stakes`` while the create route demanded
    it — so an honest client could never construct an acceptable request.

    Turns red if: ``QueryRunWarningsRequest`` drops ``context``, or the
    handler stops forwarding it.
    """
    client = TestClient(app)
    account_id = uuid4()
    body = {"query_text": _BENIGN_FOLLOW_UP, "context": {"prior_synthesis": _HOSTILE}}

    probe = client.post(
        "/v1/query-runs/warnings", json=body, headers={"X-Account-Id": str(account_id)}
    )
    assert probe.status_code == 200, probe.text
    advertised = [w["warning_type"] for w in probe.json()["warnings"]]
    assert WarningType.HIGH_STAKES in advertised, (
        "the probe must disclose the ack the create route will demand"
    )

    # Acknowledge exactly what the probe advertised -- nothing more.
    headers = {"X-Account-Id": str(account_id)}
    created = client.post(
        "/v1/query-runs",
        json=_confirmed(
            client,
            {
                **body,
                "model_slots": DEFAULT_MODEL_IDS,
                "safety_acknowledgements": [
                    {"warning_type": w, "version": WARNING_VERSION} for w in advertised
                ],
            },
            headers,
        ),
        headers=headers,
    )
    assert created.status_code == 202, created.text


def test_the_warnings_probe_without_context_is_unchanged() -> None:
    """``context`` is additive: a pre-#155 client that omits it gets exactly
    the query-text-only answer it got before, not a 422 from a newly-required
    field."""
    client = TestClient(app)
    response = client.post(
        "/v1/query-runs/warnings",
        json={"query_text": _BENIGN_FOLLOW_UP},
        headers={"X-Account-Id": str(uuid4())},
    )
    assert response.status_code == 200, response.text
    assert [w["warning_type"] for w in response.json()["warnings"]] == [WarningType.SENSITIVE_DATA]


# ---------------------------------------------------------------------------
# Issue #155, second review round — probe and create must agree on EVERY
# constraint, not just on the warning list
# ---------------------------------------------------------------------------


def test_the_probe_accepts_a_query_as_long_as_the_create_route_does() -> None:
    """A field the probe is STRICTER about is its own unbreakable loop.

    Measured before this fix: the probe capped ``query_text`` at 8,000 while
    create allows 20,000, so a benign 9,600-character query got 422 from the
    probe and 202 from create — the client could not ask about a request it
    was allowed to submit.

    Turns red if: the two limits diverge again.
    """
    client = TestClient(app)
    long_but_legal = "benign words " * 800  # ~9,600 chars, under create's 20,000

    probe = client.post(
        "/v1/query-runs/warnings",
        json={"query_text": long_but_legal},
        headers={"X-Account-Id": str(uuid4())},
    )
    assert probe.status_code == 200, probe.text

    create_headers = {"X-Account-Id": str(uuid4())}
    created = client.post(
        "/v1/query-runs",
        json=_confirmed(
            client,
            {
                "query_text": long_but_legal,
                "model_slots": DEFAULT_MODEL_IDS,
                "safety_acknowledgements": _sensitive_only(),
            },
            create_headers,
        ),
        headers=create_headers,
    )
    assert created.status_code == 202, created.text


def test_the_probe_rejects_a_context_the_create_route_would_reject() -> None:
    """The other direction: advice the create route will refuse is worse than
    no advice, because the client acts on it.

    Before this fix the probe had no context validator at all — it answered
    200 for unknown keys and over-long values that create rejects, and
    accepted a 20 MB body.

    Turns red if: ``QueryRunWarningsRequest`` stops sharing
    ``_QueryRunRequestBase._validate_context``.
    """
    client = TestClient(app)
    headers = {"X-Account-Id": str(uuid4())}
    body = {"query_text": "Compare vendors", "context": {"not_a_real_key": "x"}}

    probe = client.post("/v1/query-runs/warnings", json=body, headers=headers)
    created = client.post(
        "/v1/query-runs",
        json={**body, "model_slots": DEFAULT_MODEL_IDS, "safety_acknowledgements": []},
        headers=headers,
    )
    assert probe.status_code == 422, probe.text
    assert created.status_code == 422, created.text


def test_a_truncated_recommendation_does_not_demand_a_spurious_acknowledgement() -> None:
    """This app MANGLES ITS OWN CAVEAT, and the discriminator has to cope.

    ``synthesis_length._truncate_with_caveat_present`` finds the caveat by its
    marker and returns ``text[caveat_idx:]``, dropping the leading "This
    summary is ". So a Recommendation over ``RECOMMENDATION_MAX_CHARS`` ships
    a caveat starting mid-sentence, and a strip requiring the full opening
    missed it — reinstating, for long answers, the exact false 422 that got
    the first attempt at this issue reverted. Measured: ~1500-char body fine,
    ~2100-char body 422.

    Driven through the REAL truncation function, not a hand-written string,
    so it stays honest if that function changes.

    Turns red if: the caveat's opening clause stops being optional.
    """
    long_body = "The rollout succeeded on every measured axis. " * 50
    emitted = truncate_recommendation(f"{long_body} {HIGH_STAKES_NOTICE_FRAGMENT}")
    assert not emitted.rstrip().endswith(HIGH_STAKES_NOTICE_FRAGMENT), (
        "precondition: this body must actually trigger the mangling truncation"
    )

    client = TestClient(app)
    headers = {"X-Account-Id": str(uuid4())}
    response = client.post(
        "/v1/query-runs",
        json=_confirmed(
            client,
            {
                "query_text": _BENIGN_FOLLOW_UP,
                "model_slots": DEFAULT_MODEL_IDS,
                "context": {"prior_synthesis": emitted},
                "safety_acknowledgements": _sensitive_only(),
            },
            headers,
        ),
        headers=headers,
    )
    assert response.status_code == 202, response.text
