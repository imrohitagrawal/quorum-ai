"""Issue #100: the deployment-wide $5/24h ceiling forces a WHOLE-RUN degrade.

The money-critical property under test: once the global ceiling is reached,
a run must produce ZERO provider HTTP calls — never bill anything, and never
substitute a live answer for some slots but not others (the #171 defect
class). Live execution is enabled and a key IS configured in every test
here; only the ceiling being tripped should be why nothing goes live.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.config import settings
from product_app.costs import GLOBAL_DAILY_CEILING_USD
from product_app.feedback_store import configure_for_tests
from product_app.main import app
from product_app.providers import (
    LiveProviderResult,
    ProviderPath,
    SourceReference,
    provider_stub_service,
)
from product_app.query_runs import query_run_repository
from product_app.safety import WARNING_VERSION, WarningType

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


@pytest.fixture(autouse=True)
def clear_state() -> None:
    query_run_repository.clear()


def acknowledged_request(query_text: str) -> dict[str, object]:
    return {
        "query_text": query_text,
        "model_slots": DEFAULT_MODEL_IDS,
        "safety_acknowledgements": [
            {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
        ],
    }


def _fake_post_messages_tracking_calls(
    calls: list[str],
) -> Callable[..., LiveProviderResult]:
    def fake_post_messages(
        *,
        openrouter_key: str,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> LiveProviderResult:
        calls.append(model_id)
        return LiveProviderResult(
            answer_text=f"Live answer for {model_id}. Source: example.",
            sources=[
                SourceReference(
                    title=f"citation {model_id}",
                    url="https://example.org/citation",
                    provider=ProviderPath.OPENROUTER_SEARCH,
                    is_fallback=False,
                )
            ],
        )

    return fake_post_messages


def test_ceiling_reached_forces_the_whole_run_to_local_simulation_and_calls_no_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The core money-safety property: HTTP boundary is never touched.

    Live execution is genuinely enabled and a genuine key is configured —
    if the degrade mechanism failed, the mocked HTTP layer WOULD succeed and
    the run WOULD come back live. What turns this red: deleting the
    ``global_ceiling_reached`` override in ``_execute_query_run`` (or
    passing the real ``settings.openrouter_api_key`` instead of the forced
    empty string) — the run would then go live, ``calls`` would be
    non-empty, and every assertion below would fail.
    """
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", True)
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-test-fake-key")

    calls: list[str] = []
    monkeypatch.setattr(
        provider_stub_service,
        "_post_messages",
        _fake_post_messages_tracking_calls(calls),
    )

    with configure_for_tests() as store:
        # Seed the global ledger at the ceiling with a DIFFERENT account's
        # spend, so this run's own account has spent nothing and would pass
        # every per-account guard on its own merits.
        store.record(
            recorder="cost",
            event_type="cost_guardrail_accepted",
            account_id=uuid4(),
            query_run_id=None,
            recorded_at=datetime.now(UTC),
            payload={"estimated_cost_usd": str(GLOBAL_DAILY_CEILING_USD)},
        )

        client = TestClient(app)
        account_id = uuid4()

        create_response = client.post(
            "/v1/query-runs",
            json=acknowledged_request("Compare degrade-path research options"),
            headers={"X-Account-Id": str(account_id)},
        )
        assert create_response.status_code == 202
        query_run_id = create_response.json()["query_run_id"]

        result_response = client.get(
            f"/v1/query-runs/{query_run_id}",
            headers={"X-Account-Id": str(account_id)},
        )
        assert result_response.status_code == 200
        body = result_response.json()

        # The money-critical assertion: the HTTP boundary was NEVER reached.
        assert calls == [], f"provider was billed during a ceiling-degraded run: {calls}"

        model_answers = body["result"]["model_answers"]
        assert len(model_answers) == 4
        assert all(answer["provider_path"] == "local_simulation" for answer in model_answers)
        assert all(answer["fallback_used"] is False for answer in model_answers)

        # The #171 contract: WHOLE-RUN degrade, never a per-slot mix.
        assert body["live_count"] == 0
        assert body["local_count"] == 4

        # The new #100 signal the post-run banner needs to distinguish this
        # from an ordinary no-key demo run.
        assert body["global_spend_ceiling_reached"] is True

        # Meter honesty: this run's own billing event must not itself count
        # as accepted spend, or the ceiling would never clear on real spend.
        assert store.global_daily_spend() == GLOBAL_DAILY_CEILING_USD


def test_ceiling_not_reached_leaves_the_live_path_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: with the ledger empty, the same setup goes live as normal —
    proves the previous test's degrade is caused by the ceiling, not by
    some other side effect of the test setup (mocked HTTP, enabled flag)."""
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", True)
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-test-fake-key")

    calls: list[str] = []
    monkeypatch.setattr(
        provider_stub_service,
        "_post_messages",
        _fake_post_messages_tracking_calls(calls),
    )

    with configure_for_tests():
        client = TestClient(app)
        account_id = uuid4()

        create_response = client.post(
            "/v1/query-runs",
            json=acknowledged_request("Compare live-path control research options"),
            headers={"X-Account-Id": str(account_id)},
        )
        assert create_response.status_code == 202
        query_run_id = create_response.json()["query_run_id"]

        result_response = client.get(
            f"/v1/query-runs/{query_run_id}",
            headers={"X-Account-Id": str(account_id)},
        )
        body = result_response.json()

        assert len(calls) >= 4
        assert body["live_count"] == 4
        assert body["local_count"] == 0
        assert body["global_spend_ceiling_reached"] is False


def test_status_reports_global_daily_spend_against_the_ceiling() -> None:
    """§2.8: ongoing visibility, not just an alert after the ceiling trips."""
    with configure_for_tests() as store:
        store.record(
            recorder="cost",
            event_type="cost_guardrail_accepted",
            account_id=uuid4(),
            query_run_id=None,
            recorded_at=datetime.now(UTC),
            payload={"estimated_cost_usd": "1.23"},
        )
        client = TestClient(app)
        body = client.get("/status").json()
        assert body["global_daily_spend_usd"] == "1.23"
        assert body["global_daily_ceiling_usd"] == str(GLOBAL_DAILY_CEILING_USD)


def test_status_global_spend_is_null_not_zero_when_no_store() -> None:
    """A missing store must not be indistinguishable from a genuine $0.00 day."""
    from product_app.feedback_store import configure, get_store

    original = get_store()
    try:
        configure(None)
        client = TestClient(app)
        body = client.get("/status").json()
        assert body["global_daily_spend_usd"] is None
    finally:
        configure(original)
