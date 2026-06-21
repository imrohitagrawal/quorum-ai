"""Magic-phrase test paths must be inert in non-LOCAL runtime environments.

The phrases ``"force provider failure"``, ``"force fallback search"``, and
``"force debate timeout"`` are query-text markers the unit tests use to
trigger deterministic failure / fallback / timeout paths. They are a
test-only convenience and must not be reachable from a real user request
in ``staging`` or ``production``. The model-id markers (used by the
provider stub fixtures) are NOT gated — operators curate those.
"""

from __future__ import annotations

import pytest

from product_app.config import RuntimeEnvironment
from product_app.debate import DebateOrchestrationService, debate_event_recorder
from product_app.model_slots import ModelSlot
from product_app.providers import (
    ProviderExecutionService,
    provider_event_recorder,
)
from product_app.query_runs import query_run_repository
from product_app.synthesis import synthesis_event_recorder


@pytest.fixture(autouse=True)
def _clear_state() -> None:
    query_run_repository.clear()
    provider_event_recorder.clear()
    debate_event_recorder.clear()
    synthesis_event_recorder.clear()


@pytest.fixture
def production_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``runtime_environment`` to ``production`` for the duration of
    the test. The providers and debate modules read
    ``settings.runtime_environment`` lazily, so monkeypatching the
    attribute is enough — no need to reload the modules.
    """
    monkeypatch.setattr(
        "product_app.providers.settings.runtime_environment",
        RuntimeEnvironment.PRODUCTION,
    )
    monkeypatch.setattr(
        "product_app.debate.settings.runtime_environment",
        RuntimeEnvironment.PRODUCTION,
    )


def test_provider_failure_phrase_is_inert_in_production(
    production_runtime: None,
) -> None:
    """``"force provider failure"`` in query_text must not flip a slot
    to FAILED when the runtime is production. We assert by calling the
    helper directly.
    """
    service = ProviderExecutionService()
    slot = ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini", search=True)
    should = service._should_force_provider_failure(
        query_text="Please force provider failure in this research question.",
        model_slot=slot,
    )
    assert should is False


def test_fallback_phrase_is_inert_in_production(
    production_runtime: None,
) -> None:
    """``"force fallback search"`` must not force a slot into the
    fallback path when the runtime is production.
    """
    service = ProviderExecutionService()
    slot = ModelSlot(slot_number=2, model_id="anthropic/claude-haiku-4.5", search=True)
    should = service._should_force_fallback(
        query_text="force fallback search please",
        model_slot=slot,
    )
    assert should is False


def test_debate_timeout_phrase_is_inert_in_production(
    production_runtime: None,
) -> None:
    """``"force debate timeout"`` must not cause round-2 skipping when
    the runtime is production. We pass a small elapsed_ms well under
    the hard timeout, so the only way the helper can return True is
    via the magic phrase.
    """
    service = DebateOrchestrationService()
    should_skip = service._should_skip_round_two(
        elapsed_ms=1.0,
        query_text="force debate timeout please",
    )
    assert should_skip is False


def test_provider_failure_phrase_still_works_in_local() -> None:
    """Sanity check: the gate must NOT fire in local mode, where the
    unit tests that depend on these phrases run.
    """
    service = ProviderExecutionService()
    slot = ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini", search=True)
    should = service._should_force_provider_failure(
        query_text="force provider failure",
        model_slot=slot,
    )
    assert should is True
