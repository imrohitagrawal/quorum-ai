"""The LLM-as-judge must be visible from outside the process.

Why this file exists
--------------------
Measured 2026-08-05 on ``bc38bbb``: ``grep -n "judge" src/product_app/main.py``
returned NOTHING. No ``/status``, ``/ready`` or ``/metrics`` field reported
whether the Layer-B judge was configured, so a paid subsystem could be switched
on or off — by setting two Fly secrets — with **no external signal at all**.

That is not merely an observability nicety. Issue #216 is latent only while the
judge is off: once it is on, a ``GET /v1/query-runs/{id}`` whose verdict has
been evicted from the bounded memo fires a fresh PAID judge call that never
reaches the daily spend ledger. So "is the judge on?" is a money question, and
until this file existed the only way to answer it was to read the deploy's
secret list.

The contract pinned here
------------------------
* ``/status`` carries a boolean ``judge_enabled``.
* It is TRUE only when BOTH ``QUORUM_EVAL_JUDGE_API_KEY`` and
  ``QUORUM_EVAL_JUDGE_MODEL_ID`` are non-empty. A key alone is not enough —
  that is the trap the two-value gate sets, and reporting a key-only
  deployment as "on" would be worse than reporting nothing.
* It reports the state, never the values: neither the key nor the pinned model
  id may appear anywhere in the public payload.
* It CANNOT DRIFT from the behaviour it describes. The last test drives the
  real request-path gate (``_request_path_judge``) over every combination and
  requires the two to agree — so a future edit to one predicate that forgets
  the other goes red.

Hermetic: live execution is pinned off, no real key is ever set, and the one
provider seam is never reached because no test here lets a judge call happen.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from product_app import query_runs as qr
from product_app import run_history_store
from product_app.config import settings
from product_app.debate import debate_event_recorder
from product_app.main import app
from product_app.providers import InitialAnswerStatus, provider_event_recorder
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType
from product_app.synthesis import synthesis_event_recorder

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]

JUDGE_KEY = "sk-or-v1-not-a-real-judge-key"
JUDGE_MODEL = "vendor/judge-model-under-test"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the pipeline to local simulation; judge config left to each test."""
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", False)
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", "")
    monkeypatch.setattr(settings, "quorum_eval_judge_model_id", "")


@pytest.fixture(autouse=True)
def _clear_state() -> None:
    query_run_repository.clear()
    provider_event_recorder.clear()
    debate_event_recorder.clear()
    synthesis_event_recorder.clear()
    qr._judge_verdict_memo_clear_for_tests()


def _status(client: TestClient) -> dict[str, Any]:
    response = client.get("/status")
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


def _configure(monkeypatch: pytest.MonkeyPatch, *, key: str, model_id: str) -> None:
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", key)
    monkeypatch.setattr(settings, "quorum_eval_judge_model_id", model_id)


#: Every combination of the two values, with the state each one MUST report.
#: Only the both-set row is on; the middle two are the trap.
_COMBINATIONS = [
    pytest.param("", "", False, id="neither"),
    pytest.param(JUDGE_KEY, "", False, id="key-only"),
    pytest.param("", JUDGE_MODEL, False, id="model-only"),
    pytest.param(JUDGE_KEY, JUDGE_MODEL, True, id="both"),
]


# ---------------------------------------------------------------------------
# The field exists and reports the real state
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("key", "model_id", "expected"), _COMBINATIONS)
def test_status_reports_whether_the_judge_is_configured(
    monkeypatch: pytest.MonkeyPatch, key: str, model_id: str, expected: bool
) -> None:
    """RED IF: ``/status`` drops ``judge_enabled``, or reports a key-only
    deployment as on.

    What turns it red: delete the ``judge_enabled`` key from
    ``status_snapshot``, or weaken its predicate to the key alone.
    """
    _configure(monkeypatch, key=key, model_id=model_id)
    payload = _status(TestClient(app))

    assert "judge_enabled" in payload, (
        "/status no longer reports judge_enabled, so an operator cannot tell "
        "from outside whether the paid Layer-B judge is on (issue #216 makes "
        "that a money question). Restore the field."
    )
    assert payload["judge_enabled"] is expected, (
        f"judge_enabled is {payload['judge_enabled']!r} for "
        f"key={'set' if key else 'empty'}, model_id={'set' if model_id else 'empty'}; "
        f"expected {expected!r}. The judge needs BOTH values."
    )
    # A boolean, not a truthy string: an alert rule thresholds this.
    assert isinstance(payload["judge_enabled"], bool)


def test_status_never_leaks_the_judge_key_or_model_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED IF: the judge's configured VALUES reach the public payload.

    ``/status`` is unauthenticated. The key is a credential and the pinned
    model id is free recon about the deployment, so the field reports the
    STATE and nothing else — the same discipline ``error_tracking`` follows by
    refusing to name its vendor.

    What turns it red: report ``settings.quorum_eval_judge_model_id`` (or the
    key) instead of a boolean.
    """
    _configure(monkeypatch, key=JUDGE_KEY, model_id=JUDGE_MODEL)
    client = TestClient(app)
    raw = client.get("/status").text

    # Positive partner: the leak check below is trivially true over a payload
    # that does not report the judge at all, which is exactly the state this
    # work package is fixing. Require the field to be present AND on first.
    assert '"judge_enabled":true' in raw.replace(" ", ""), (
        "judge_enabled is absent or false with both values set, so the leak "
        "assertions below would pass over a payload that says nothing"
    )
    assert JUDGE_KEY not in raw, "/status leaked the judge API key"
    assert JUDGE_MODEL not in raw, "/status leaked the pinned judge model id"


# ---------------------------------------------------------------------------
# The reported state cannot drift from the gate it describes
# ---------------------------------------------------------------------------


def _create_terminal_run(client: TestClient, account_id: UUID) -> dict[str, Any]:
    response = client.post(
        "/v1/query-runs",
        json={
            "query_text": "Compare transparent model answers",
            "model_slots": DEFAULT_MODEL_IDS,
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
            ],
        },
        headers={"X-Account-Id": str(account_id)},
    )
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    assert body["status"] == "completed"
    return body


@pytest.mark.parametrize(("key", "model_id", "expected"), _COMBINATIONS)
def test_the_reported_state_matches_the_real_request_path_gate(
    monkeypatch: pytest.MonkeyPatch, key: str, model_id: str, expected: bool
) -> None:
    """RED IF: ``/status`` and the request-path judge gate disagree.

    This is the test that makes the field trustworthy rather than decorative.
    ``_request_path_judge`` is what actually decides whether a paid judge call
    can happen on a ``GET``; ``judge_enabled`` is what an operator reads. They
    must be ONE predicate, so a future edit to either goes red here.

    The run below is COMPLETED with completed answers, so the gate's other
    conditions (not cancelled, not blocked by cost, at least one completed
    answer) are all satisfied and the judge configuration is the only variable
    left — which is what makes the equality below meaningful rather than a
    coincidence of two ``None``s.

    What turns it red: change ``_request_path_judge``'s configuration gate
    without changing ``status_snapshot``, or vice versa.
    """
    with run_history_store.configure_for_tests():
        client = TestClient(app)
        account_id = uuid4()
        body = _create_terminal_run(client, account_id)
        run = query_run_repository.get(UUID(body["query_run_id"]))

        # Sanity: the non-configuration conditions really are satisfied, so a
        # ``None`` below can only be the configuration gate talking.
        assert run.status is qr.QueryRunStatus.COMPLETED
        assert any(
            answer.status is InitialAnswerStatus.COMPLETED for answer in run.initial_answers
        ), "the run produced no completed answer, so the gate would be None for the wrong reason"

        _configure(monkeypatch, key=key, model_id=model_id)

        gate_would_judge = qr._request_path_judge(run) is not None
        reported = _status(client)["judge_enabled"]

        assert gate_would_judge is expected, (
            f"the REAL request-path gate says judge={gate_would_judge} for "
            f"key={'set' if key else 'empty'}/model={'set' if model_id else 'empty'}; "
            f"expected {expected}"
        )
        assert reported == gate_would_judge, (
            f"/status reports judge_enabled={reported} but the request-path gate "
            f"would {'' if gate_would_judge else 'NOT '}judge. The operator-visible "
            f"signal has drifted from the behaviour it describes."
        )
