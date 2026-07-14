"""issue #16 — the four initial-answer live calls are output-capped.

Without a ``max_tokens`` cap, initial-answer output is unbounded, so a verbose
prompt on an expensive model mix can bill far above any pre-run estimate and
slip the cost guardrail. Debate and synthesis were already capped; this pins
that the initial-answer search path now passes
``settings.initial_answer_max_tokens`` on every attempt (``:online``, the
bare-id retry, and the search-disabled path).
"""

from __future__ import annotations

import pytest

from product_app.config import settings
from product_app.model_slots import ModelSlot
from product_app.providers import ProviderExecutionService


def _service_capturing_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ProviderExecutionService, list[int | None]]:
    """A live provider service whose ``_post_messages`` is stubbed to record the
    ``max_tokens`` each call passes (and answer nothing, since only the cap
    matters here). Returns the service and the capture list."""
    captured: list[int | None] = []
    service = ProviderExecutionService()

    def fake_post_messages(
        *,
        openrouter_key: str,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> None:
        captured.append(max_tokens)
        return None

    monkeypatch.setattr(service, "_post_messages", fake_post_messages)
    return service, captured


def test_searching_initial_answer_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    service, captured = _service_capturing_max_tokens(monkeypatch)
    service._call_openrouter_with_optional_search(
        openrouter_key="test-key",
        query_text="anything",
        model_slot=ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini", search=True),
    )
    assert captured  # at least the :online attempt happened
    assert all(mt == settings.initial_answer_max_tokens for mt in captured)


def test_search_disabled_initial_answer_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    service, captured = _service_capturing_max_tokens(monkeypatch)
    service._call_openrouter_with_optional_search(
        openrouter_key="test-key",
        query_text="anything",
        model_slot=ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini", search=False),
    )
    assert captured == [settings.initial_answer_max_tokens]
