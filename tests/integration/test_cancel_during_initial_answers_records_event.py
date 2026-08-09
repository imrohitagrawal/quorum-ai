"""#188: a REAL cancel landing during the initial-answers stage.

``query_runs._produce_one_initial_answer`` has its own ``_should_stop`` gate
(``query_runs.py:1770``) that returns a stub via
``provider_execution_service.cancelled_answer`` when a slot is cancelled
mid-flight. Every other test that reaches ``cancelled_answer`` either calls
it directly (``tests/unit/test_provider_stubs.py``) or monkeypatches
``produce_initial_answer`` itself (``test_partial_run_is_persisted`` in
``tests/integration/test_query_run_history_persist.py``), which bypasses
this exact branch — ``_should_stop`` returns ``False`` (no real cancel) and
control never reaches ``query_runs.py:1770`` at all.

This test drives a genuine concurrent cancel — the same handshake technique
as ``tests/integration/test_f05_terminal_status_not_overwritten.py`` — so
the real branch executes, and asserts the fix this exercises (#188): the
event actually reaches ``provider_event_recorder``, proving the wiring is
correct end to end from a real cancel, not just from a direct unit call.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from tests.helpers import isolated_run_semaphore, wait_for_free_permits

from product_app import config, query_runs
from product_app.main import app
from product_app.providers import provider_event_recorder
from product_app.safety import WARNING_VERSION, WarningType

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]

#: Bounded so a regression that never reaches the window fails loudly
#: instead of hanging the suite.
HANDSHAKE_TIMEOUT_S = 30.0


class _FakeResponse:
    """Minimal stand-in for the ``urlopen`` context manager."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


_LIVE_BODY = json.dumps(
    {
        "choices": [{"message": {"content": "live provider answer text"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }
).encode()


@dataclass
class _Rendezvous:
    """Deterministic two-way handshake between the worker and the test."""

    reached: threading.Event = field(default_factory=threading.Event)
    released: threading.Event = field(default_factory=threading.Event)

    def arrive(self) -> None:
        self.reached.set()
        if not self.released.wait(timeout=HANDSHAKE_TIMEOUT_S):  # pragma: no cover
            raise AssertionError("test thread never released the cancel window")

    def release(self) -> None:
        self.released.set()


def _acknowledged_request(query_text: str) -> dict[str, object]:
    return {
        "query_text": query_text,
        "model_slots": DEFAULT_MODEL_IDS,
        "safety_acknowledgements": [
            {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
            {"warning_type": WarningType.HIGH_STAKES, "version": WARNING_VERSION},
        ],
    }


def _confirmed_request(
    client: TestClient, query_text: str, headers: dict[str, str]
) -> dict[str, object]:
    """ADR-0028: attach the confirmation round-trip a plain create now needs.

    The shipped DEFAULT_MODEL_IDS mix stays in ALLOW under ADR-0028 (MEASURED
    bound 0.1043), but this file's own fixture mix may not, so this
    defensively round-trips a confirmation whenever the estimate lands in
    require_confirmation (a no-op otherwise). None of the create calls below
    are testing the cost guardrail itself.
    """
    preview = client.post(
        "/v1/query-runs/estimate",
        json={"query_text": query_text, "model_slots": DEFAULT_MODEL_IDS},
        headers=headers,
    )
    cost_estimate = preview.json()["cost_estimate"]
    body = _acknowledged_request(query_text)
    if cost_estimate["threshold_action"] == "require_confirmation":
        body["cost_confirmation"] = {
            "estimated_cost_usd": cost_estimate["estimated_cost_usd"],
            "confirmation_token": cost_estimate["confirmation_token"],
        }
    return body


def test_a_cancel_landing_during_initial_answers_is_recorded_as_a_cancelled_provider_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_event_recorder.clear()
    rendezvous = _Rendezvous()
    triggered = threading.Event()

    def fake_urlopen(request: Any, timeout: float = 0) -> _FakeResponse:
        return _FakeResponse(_LIVE_BODY)

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True)
    monkeypatch.setattr(config.settings, "openrouter_api_key", "sk-or-test-188-initial")
    monkeypatch.setattr(config.settings, "stage_delay_ms", 0)

    real_should_stop = query_runs._should_stop

    def wrapped_should_stop(query_run_id: UUID) -> bool:
        if not triggered.is_set():
            triggered.set()
            rendezvous.arrive()
        return real_should_stop(query_run_id)

    monkeypatch.setattr(query_runs, "_should_stop", wrapped_should_stop)

    with isolated_run_semaphore(1) as semaphore:
        client = TestClient(app)
        csrf = client.get("/v1/session").json()["csrf_token"]
        headers = {"x-csrf-token": csrf}
        created = client.post(
            "/v1/query-runs",
            json=_confirmed_request(client, "compare managed database options", headers),
            headers=headers,
        )
        assert created.status_code == 202, created.text
        query_run_id = created.json()["query_run_id"]

        assert rendezvous.reached.wait(timeout=HANDSHAKE_TIMEOUT_S), (
            "pipeline never reached the initial-answers cancel window"
        )
        deleted = client.delete(
            f"/v1/query-runs/{query_run_id}",
            headers={"x-csrf-token": csrf},
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["status"] == "cancelled"
        rendezvous.release()

        # The worker returns its permit in a ``finally`` after the run
        # reaches a terminal state, so a restored permit is the join point.
        assert wait_for_free_permits(semaphore, 1, timeout_s=HANDSHAKE_TIMEOUT_S) == 1

    events = provider_event_recorder.list_events()
    cancelled_events = [e for e in events if e.event_type == "provider_initial_answer_cancelled"]
    assert len(cancelled_events) >= 1, (
        f"expected at least one provider_initial_answer_cancelled event, got "
        f"{[e.event_type for e in events]}"
    )
    assert str(cancelled_events[0].query_run_id) == query_run_id
