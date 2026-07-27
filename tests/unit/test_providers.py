"""Tests for provider truncation detection and the ``shortened`` field.

The ``InitialModelAnswer.shortened`` field is set to ``True`` when the
provider signal-indicated truncation (``finish_reason == "length"``).
This module verifies:

* ``_post_messages`` sets ``is_truncated`` on ``LiveProviderResult`` when
  the response carries ``finish_reason == "length"``.
* ``produce_initial_answer`` threads ``is_truncated`` through to
  ``InitialModelAnswer.shortened``.
* A normal response (no truncation signal) leaves ``shortened=False``.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from product_app.config import RuntimeEnvironment, settings
from product_app.model_slots import validate_model_slots
from product_app.provider_keys import ProviderCredentialSource
from product_app.providers import (
    InitialAnswerStatus,
    LiveProviderResult,
    TokenUsage,
    provider_execution_service,
    provider_stub_service,
)

# ``is_truncated`` on ``LiveProviderResult`` and ``shortened`` on
# ``InitialModelAnswer`` do not exist yet — they are WP-D (F-07). These tests are
# RED BY DESIGN and pin the contract WP-D must satisfy. The ``type: ignore``
# comments below exist only so a deliberately-red *runtime* test does not also
# turn the blocking ``make type-check`` gate red. mypy runs with
# ``warn_unused_ignores`` (strict), so the moment WP-D adds the fields these
# ignores become errors and MUST be deleted in that same change.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_openrouter_response(
    *,
    finish_reason: str = "stop",
    content: str = "Here is a complete answer.",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    total_tokens: int = 150,
) -> dict[str, Any]:
    """Build a fake  chat-completions response."""
    return {
        "id": "chatcml-fake",
        "model": "test/model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
    }


def _fake_urlopen_response(body: dict[str, Any]) -> MagicMock:
    """Return a mock urlopen context manager that yields *body* as JSON."""
    raw = json.dumps(body).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ---------------------------------------------------------------------------
# LiveProviderResult.is_truncated propagation
# ---------------------------------------------------------------------------


class TestTruncationPropagation:
    """produce_initial_answer threads is_truncated → shortened."""

    @pytest.fixture(autouse=True)
    def _isolate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Enable live execution so the live path is attempted.
        monkeypatch.setattr(settings, "openrouter_live_execution_enabled", True)
        monkeypatch.setattr(settings, "runtime_environment", RuntimeEnvironment.LOCAL)
        # Disable the :online search suffix so we don't attempt a :online POST
        # first (which would fail with our mock and fall back to bare-id retry).
        # We patch _post_openrouter directly, so search=false avoids the retry.

    def test_shortened_true_when_provider_signal_length(self) -> None:
        """A provider response with finish_reason="length" should set
        shortened=True on the InitialModelAnswer."""
        slots = validate_model_slots(
            [
                "openai/gpt-4o-mini",
                "anthropic/claude-haiku-4.5",
                "google/gemini-2.5-flash",
                "nvidia/nemotron-3-super-120b-a12b",
            ]
        )

        # Build a LiveProviderResult as _post_messages would after seeing
        # finish_reason="length".
        truncated_result = LiveProviderResult(
            answer_text="This answer was cut short by the model's max_tokens limit.",
            sources=[],
            usage=TokenUsage(prompt_tokens=100, completion_tokens=1999, total_tokens=2099),
            is_truncated=True,  # type: ignore[call-arg]  # WP-D adds this field
        )

        # Monkeypatch _post_openrouter to return our truncated result.
        with patch.object(
            provider_execution_service,
            "_post_openrouter",
            return_value=truncated_result,
        ):
            answer = provider_execution_service.produce_initial_answer(
                account_id=uuid4(),
                query_run_id=uuid4(),
                query_text="Explain quantum entanglement in detail",
                model_slot=slots[0],
                credential_source=ProviderCredentialSource.APP_OWNED,
                openrouter_key="sk-test",
            )

        assert answer.shortened is True  # type: ignore[attr-defined]  # WP-D adds this field
        assert answer.status == InitialAnswerStatus.COMPLETED

    def test_shortened_false_on_normal_response(self) -> None:
        """A normal provider response (finish_reason="stop") should set
        shortened=False."""
        slots = validate_model_slots(
            [
                "openai/gpt-4o-mini",
                "anthropic/claude-haiku-4.5",
                "google/gemini-2.5-flash",
                "nvidia/nemotron-3-super-120b-a12b",
            ]
        )

        normal_result = LiveProviderResult(
            answer_text="Here is a complete answer that was not truncated.",
            sources=[],
            usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            is_truncated=False,  # type: ignore[call-arg]  # WP-D adds this field
        )

        with patch.object(
            provider_execution_service,
            "_post_openrouter",
            return_value=normal_result,
        ):
            answer = provider_execution_service.produce_initial_answer(
                account_id=uuid4(),
                query_run_id=uuid4(),
                query_text="What is 2+2?",
                model_slot=slots[0],
                credential_source=ProviderCredentialSource.APP_OWNED,
                openrouter_key="sk-test",
            )

        assert answer.shortened is False  # type: ignore[attr-defined]  # WP-D adds this field
        assert answer.status == InitialAnswerStatus.COMPLETED

    def test_shortened_false_on_simulated_answer(self) -> None:
        """Local simulation answers are never truncated."""
        slots = validate_model_slots(
            [
                "openai/gpt-4o-mini",
                "anthropic/claude-haiku-4.5",
                "google/gemini-2.5-flash",
                "nvidia/nemotron-3-super-120b-a12b",
            ]
        )

        answer = provider_stub_service.produce_initial_answer(
            account_id=uuid4(),
            query_run_id=uuid4(),
            query_text="test query",
            model_slot=slots[0],
            credential_source=ProviderCredentialSource.APP_OWNED,
            openrouter_key="",
        )

        assert answer.shortened is False  # type: ignore[attr-defined]  # WP-D adds this field


# ---------------------------------------------------------------------------
# _post_messages truncation detection
# ---------------------------------------------------------------------------


class TestPostMessagesTruncationDetection:
    """_post_messages detects finish_reason="length" and sets is_truncated."""

    def test_is_truncated_set_when_finish_reason_length(self) -> None:
        """When the provider returns finish_reason='length', the
        LiveProviderResult should carry is_truncated=True."""
        response_body = _make_openrouter_response(
            finish_reason="length",
            content="Truncated output...",
            completion_tokens=1999,
            total_tokens=2099,
        )
        mock_resp = _fake_urlopen_response(response_body)

        with patch("product_app.providers.urlopen", return_value=mock_resp):
            result = provider_execution_service._post_messages(
                openrouter_key="sk-test",
                model_id="test/model",
                messages=[{"role": "user", "content": "test"}],
                max_tokens=2000,
            )

        assert result is not None
        assert isinstance(result, LiveProviderResult)
        assert result.is_truncated is True  # type: ignore[attr-defined]  # WP-D adds this field
        assert result.answer_text == "Truncated output..."

    def test_is_truncated_false_when_finish_reason_stop(self) -> None:
        """A normal finish_reason='stop' leaves is_truncated=False."""
        response_body = _make_openrouter_response(
            finish_reason="stop",
            content="Complete answer.",
        )
        mock_resp = _fake_urlopen_response(response_body)

        with patch("product_app.providers.urlopen", return_value=mock_resp):
            result = provider_execution_service._post_messages(
                openrouter_key="sk-test",
                model_id="test/model",
                messages=[{"role": "user", "content": "test"}],
                max_tokens=2000,
            )

        assert result is not None
        assert isinstance(result, LiveProviderResult)
        assert result.is_truncated is False  # type: ignore[attr-defined]  # WP-D adds this field
        assert result.answer_text == "Complete answer."

    def test_is_truncated_false_when_no_finish_reason(self) -> None:
        """A response without choices[0].finish_reason is not truncated."""
        body = {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Answer."},
                    # No finish_reason key
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        mock_resp = _fake_urlopen_response(body)

        with patch("product_app.providers.urlopen", return_value=mock_resp):
            result = provider_execution_service._post_messages(
                openrouter_key="sk-test",
                model_id="test/model",
                messages=[{"role": "user", "content": "test"}],
                max_tokens=2000,
            )

        assert result is not None
        assert result.is_truncated is False  # type: ignore[union-attr]  # WP-D adds this field
