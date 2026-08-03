from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.main import app
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType, warning_event_recorder

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

    response = client.post(
        "/v1/query-runs",
        json={
            "query_text": "Compare legal contract risk",
            "model_slots": DEFAULT_MODEL_IDS,
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
                {"warning_type": WarningType.HIGH_STAKES, "version": WARNING_VERSION},
            ],
        },
        headers={"X-Account-Id": str(account_id)},
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
    response = client.post(
        "/v1/query-runs",
        json={
            "query_text": _BENIGN_FOLLOW_UP,
            "model_slots": DEFAULT_MODEL_IDS,
            "context": {"prior_synthesis": f"The rollout succeeded. {_OWN_CAVEAT}"},
            "safety_acknowledgements": _sensitive_only(),
        },
        headers={"X-Account-Id": str(uuid4())},
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
    created = client.post(
        "/v1/query-runs",
        json={
            **body,
            "model_slots": DEFAULT_MODEL_IDS,
            "safety_acknowledgements": [
                {"warning_type": w, "version": WARNING_VERSION} for w in advertised
            ],
        },
        headers={"X-Account-Id": str(account_id)},
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
