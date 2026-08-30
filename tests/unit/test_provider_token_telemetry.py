"""Issue #268: measure the INPUT tokens each provider call actually carries.

WHAT IS BLOCKED AND WHY
-----------------------
``config.py`` sets two constants the pre-run cost estimate is built on:

    cost_system_prompt_tokens = 350
    cost_web_search_context_tokens = 2000

The comment above them grounds BOTH on a single live run (``d7785cd8``,
"observed prompt tokens/model 2277-2560"). One sample. Issue #268 already
measured that our system prompts are all comfortably under 350, so that is not
the exposure. The exposure is the web-search context: OpenRouter's ``:online``
suffix injects retrieved passages upstream, bills them to us as input tokens,
and NOTHING of ours bounds or measures them. The cost guardrail keys off the
estimate (``costs.py``), so an under-estimate there is a fail-safe hole.

``injected_tokens_est = prompt_tokens - sent_tokens_est`` is the number that
settles it: what the provider charged as input, minus what we actually sent.

NOTHING IS CHANGED BY THIS FILE. Neither constant moves; no classification
moves. The deliverable is the measurement, and the reading that would justify
moving a constant later is written down in the ADR.

WHAT TURNS EACH TEST RED
------------------------
Named per test. The file-level answer: delete the ``provider_call_tokens``
emission from ``_post_messages`` and every test here fails.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from email.message import Message
from typing import Any
from unittest.mock import MagicMock
from urllib.error import HTTPError

import pytest
from tests.provider_wire import sse_from_completion

from product_app import config, costs, providers, telemetry_sink
from product_app.providers import provider_execution_service

_MODEL_ID = "anthropic/claude-haiku-4.5"
_CANARY = "CANARY-9f3a"


class _Collector(logging.Handler):
    """Captures records off the file-only telemetry logger.

    ``product_app.telemetry`` sets ``propagate=False``, so ``caplog`` — whose
    handler lives on the root logger — cannot see these records at all. That is
    deliberate (see ``test_telemetry_sink.py``), and it is why this file needs
    its own handler rather than the fixture.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def token_records() -> Iterator[_Collector]:
    logger = logging.getLogger(telemetry_sink.TOKEN_TELEMETRY_LOGGER)
    collector = _Collector()
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(collector)
    try:
        yield collector
    finally:
        logger.removeHandler(collector)
        logger.setLevel(previous_level)


def _response_body(
    *,
    prompt_tokens: int | None = 900,
    completion_tokens: int = 120,
    content: str = "An answer.",
) -> bytes:
    payload: dict[str, Any] = {
        "choices": [{"message": {"role": "assistant", "content": content}}],
    }
    if prompt_tokens is not None:
        payload["usage"] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
    return sse_from_completion(payload)


def _install(monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    response = MagicMock()
    response.read.return_value = body
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("product_app.providers.urlopen", MagicMock(return_value=response))


def _only(collector: _Collector) -> dict[str, Any]:
    records = [r for r in collector.records if r.msg == "provider_call_tokens"]
    # CARDINALITY (AGENTS.md rule 6b): accounting telemetry that fires twice
    # per call would double every percentile read off it. One call, one record.
    assert len(records) == 1, f"expected exactly 1 token record, got {len(records)}"
    return records[0].__dict__


def test_injected_tokens_is_computed_from_the_messages_actually_sent(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: ``sent_chars`` is hardcoded, or read from anything but ``messages``.

    Literals on both sides (AGENTS.md rules 7a/8b): 4000 characters sent, 3000
    prompt tokens charged, so 1000 tokens estimated sent and 2000 injected.
    Asserting against ``costs.CHARS_PER_TOKEN`` or against either config
    constant would survive that constant being changed to anything at all.

    TWO payloads of DIFFERENT sizes, and that is not decoration. Measured while
    building this: with only the 4000-character call, replacing the whole
    computation with ``sent_chars = 4000`` left all seven tests in this file
    GREEN — the mutant and the fixture agreed on one number. No single constant
    satisfies both arms below.
    """

    def _drive(*, system_len: int, user_len: int, prompt_tokens: int) -> dict[str, Any]:
        token_records.records.clear()
        _install(monkeypatch, _response_body(prompt_tokens=prompt_tokens))
        result = provider_execution_service._post_messages(
            openrouter_key="sk-or-test",
            model_id=_MODEL_ID,
            messages=[
                {"role": "system", "content": "S" * system_len},
                {"role": "user", "content": "U" * user_len},
            ],
        )
        assert result is not None
        return _only(token_records)

    big = _drive(system_len=1500, user_len=2500, prompt_tokens=3000)
    assert big["sent_chars"] == 4000
    assert big["sent_tokens_est"] == 1000
    assert big["prompt_tokens"] == 3000
    assert big["injected_tokens_est"] == 2000
    assert big["system_prompt_chars"] == 1500
    assert big["completion_tokens"] == 120
    assert big["usage_absent"] is False

    small = _drive(system_len=200, user_len=600, prompt_tokens=1000)
    assert small["sent_chars"] == 800
    assert small["sent_tokens_est"] == 200
    assert small["injected_tokens_est"] == 800
    assert small["system_prompt_chars"] == 200


def test_the_output_ceiling_recorded_is_the_one_the_call_actually_asked_for(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: ``max_tokens`` is hardcoded, dropped, or read from settings
    instead of from the call.

    A declared, shipped field with no value assertion anywhere: measured
    2026-08-10, replacing ``"max_tokens": max_tokens`` with ``0`` left the
    whole suite green at ``2801 passed``. It is the only field separating the
    synthesis and judge calls from the rest of the population (ADR-0031 records
    that ``initial_answer_max_tokens`` and ``DEBATE_ROUND_MAX_TOKENS`` are both
    2000, so it does not separate those two), and #268's reading groups by it.

    THREE values, one of them ``None``: two would let a single constant satisfy
    both arms, and ``None`` is the real default on ``_post_messages`` — a
    fabricated ``0`` there would read as "asked for no output at all".
    """

    def _drive(max_tokens: int | None) -> Any:
        token_records.records.clear()
        _install(monkeypatch, _response_body())
        result = provider_execution_service._post_messages(
            openrouter_key="sk-or-test",
            model_id=_MODEL_ID,
            messages=[{"role": "user", "content": "u"}],
            max_tokens=max_tokens,
        )
        assert result is not None
        return _only(token_records)["max_tokens"]

    assert _drive(3000) == 3000
    assert _drive(1024) == 1024
    assert _drive(None) is None


def test_the_telemetry_divisor_matches_the_cost_estimators_divisor() -> None:
    """RED WHEN: the two drift apart.

    ``injected_tokens_est`` is only meaningful as a comparison against the
    estimate, and the estimate divides characters by ``costs.CHARS_PER_TOKEN``.
    If the telemetry used a different divisor, every reading taken from it
    would be measuring a different quantity from the one being calibrated.
    Providers does not import ``costs`` (it would add an import edge to the
    paid path for one integer), so the coupling is pinned here instead.
    """
    assert int(costs.CHARS_PER_TOKEN) == providers._CHARS_PER_TOKEN_ESTIMATE


def test_a_non_searching_call_reports_search_disabled(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: ``search_enabled`` is hardcoded, or derived from anything but
    the ``:online`` suffix.

    The suffix is the search flag as it goes on the wire, and searching calls
    are the whole population #268 is about — a reading that cannot separate
    them from the rest cannot calibrate
    ``cost_web_search_context_tokens``. Both arms are driven in one test so
    neither can pass by accident.
    """
    _install(monkeypatch, _response_body())
    provider_execution_service.call_with_prompt(
        openrouter_key="sk-or-test",
        model_id=_MODEL_ID,
        system_prompt="s",
        user_prompt="u",
    )
    assert _only(token_records)["search_enabled"] is False
    assert _only(token_records)["model_id"] == _MODEL_ID

    token_records.records.clear()
    provider_execution_service.call_with_prompt(
        openrouter_key="sk-or-test",
        model_id=f"{_MODEL_ID}:online",
        system_prompt="s",
        user_prompt="u",
    )
    assert _only(token_records)["search_enabled"] is True
    assert _only(token_records)["model_id"] == f"{_MODEL_ID}:online"


def test_no_message_content_reaches_the_token_record(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: ``messages`` (or any element of it) is added to ``extra=``.

    The record carries COUNTS of what was sent, never the text. A user query
    and a model's prior answer both pass through ``messages``.
    """
    _install(monkeypatch, _response_body())
    provider_execution_service.call_with_prompt(
        openrouter_key="sk-or-test",
        model_id=_MODEL_ID,
        system_prompt=f"system {_CANARY}",
        user_prompt=f"user {_CANARY}",
    )
    record = _only(token_records)
    # POSITIVE PARTNER: the canary really was in the payload, so its absence
    # below is a property of the record and not of a call that never happened.
    assert record["sent_chars"] >= 2 * len(_CANARY)
    assert _CANARY not in json.dumps(record, default=str)


def test_the_token_record_reports_absent_usage_rather_than_a_fabricated_zero(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: ``usage_absent`` is hardcoded, or a zero ``prompt_tokens`` is
    logged when the provider reported none.

    A fabricated ``0`` would sit in the distribution and drag every percentile
    the ADR's reading takes. ``_extract_usage`` already refuses to invent a
    record; the telemetry must refuse the same way.
    """
    _install(monkeypatch, _response_body(prompt_tokens=None))
    provider_execution_service.call_with_prompt(
        openrouter_key="sk-or-test",
        model_id=_MODEL_ID,
        system_prompt="s",
        user_prompt="u",
    )
    record = _only(token_records)
    assert record["usage_absent"] is True
    assert "prompt_tokens" not in record
    assert "completion_tokens" not in record
    assert "injected_tokens_est" not in record
    # POSITIVE PARTNER: the fields DO appear when the provider reports usage,
    # so "not in record" is not trivially true of every record.
    token_records.records.clear()
    _install(monkeypatch, _response_body(prompt_tokens=777))
    provider_execution_service.call_with_prompt(
        openrouter_key="sk-or-test",
        model_id=_MODEL_ID,
        system_prompt="s",
        user_prompt="u",
    )
    present = _only(token_records)
    assert present["usage_absent"] is False
    assert present["prompt_tokens"] == 777


def test_the_token_record_never_fires_on_a_call_that_produced_no_response(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: the emission is moved above the response-parsing guard.

    A 401 bills nothing and parses nothing, so there is no input-token
    measurement to make. Recording one would put a phantom row in the very
    distribution the constants are about to be calibrated against.
    """
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    # A REAL body and REAL headers (AGENTS.md rule 8a): the repo's ``fp=None``
    # doubles read as ``b''``, and this path also drives #105's evidence shape.
    body = json.dumps({"error": {"message": "User not found.", "code": 401}}).encode()

    def fake_urlopen(request: Any, timeout: float = 0) -> Any:
        raise HTTPError(
            url="https://openrouter.ai/api/v1/chat/completions",
            code=401,
            msg="no",
            hdrs=Message(),
            fp=io.BytesIO(body),
        )

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)
    provider_execution_service.call_with_prompt(
        openrouter_key="sk-or-test",
        model_id=_MODEL_ID,
        system_prompt="s",
        user_prompt="u",
    )
    assert [r.msg for r in token_records.records] == []

    # POSITIVE PARTNER: a call that DID produce a response still records, so
    # the emptiness above is about this path and not about a dead emitter.
    _install(monkeypatch, _response_body())
    provider_execution_service.call_with_prompt(
        openrouter_key="sk-or-test",
        model_id=_MODEL_ID,
        system_prompt="s",
        user_prompt="u",
    )
    assert _only(token_records)["usage_absent"] is False


def test_a_telemetry_failure_cannot_change_what_the_provider_call_returns(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: the emission stops being wrapped, or is moved inside the
    response-parsing ``try``.

    The parsing ``try`` in ``_post_messages`` returns ``_DISPATCH_UNMEASURED``
    for anything it catches, so an exception raised by instrumentation INSIDE
    it would silently downgrade a perfectly measurable, already-billed call to
    ``estimated``. Instrumentation must never be able to move money.
    """
    _install(monkeypatch, _response_body(prompt_tokens=3000))

    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("telemetry is broken")

    monkeypatch.setattr(providers, "_log_call_token_shape", explode)
    result = provider_execution_service.call_with_prompt(
        openrouter_key="sk-or-test",
        model_id=_MODEL_ID,
        system_prompt="s",
        user_prompt="u",
    )
    assert result is not None
    assert result.usage is not None
    assert result.usage.prompt_tokens == 3000
    assert result.answer_text == "An answer."
