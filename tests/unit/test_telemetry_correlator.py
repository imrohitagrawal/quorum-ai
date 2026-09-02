"""ADR-0093 decision 5: a telemetry row says which run and stage it came from.

WHAT TURNS EACH TEST RED
------------------------
Named per test. The file-level answer: delete the ``telemetry_labels``
parameter from ``ProviderExecutionService.call_with_prompt`` and every test
here fails.

WHY THIS EXISTS
---------------
``TELEMETRY_FIELD_NAMES`` carried no ``query_run_id``, no ``stage`` and no
``finish_reason`` before this change — verified by ``grep``, zero hits each.
Two consequences ADR-0093 recorded against the shipped list:

* a token row could not be joined to a receipt, and round 1 could not be told
  from round 2. The only grouping available was file order plus ``model_id``.
* #290 turns one debate call per run into **eight**, from four models that also
  appear as answerers — so every one of those rows was unattributable.

``finish_reason`` is the quality signal no cost row can carry: the #290 probe
measured seven of eight critique calls returning ``"length"``, i.e. full price
for a clipped critique on a receipt that looks healthy.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from tests.provider_wire import sse_from_completion

from product_app import config, telemetry_sink
from product_app.providers import CallTelemetryLabels, provider_execution_service

_MODEL_ID = "anthropic/claude-haiku-4.5"
_RUN_ID = UUID("11111111-2222-3333-4444-555555555555")


def _live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)


def _completion_body(*, finish_reason: object = "stop") -> bytes:
    choice: dict[str, Any] = {"message": {"role": "assistant", "content": "an answer"}}
    if finish_reason is not _ABSENT:
        choice["finish_reason"] = finish_reason
    payload = {
        "choices": [choice],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }
    return sse_from_completion(payload)


class _Absent:
    pass


_ABSENT = _Absent()


class _Collector(logging.Handler):
    def __init__(self, into: list[logging.LogRecord]) -> None:
        super().__init__(level=logging.DEBUG)
        self._into = into

    def emit(self, record: logging.LogRecord) -> None:
        self._into.append(record)


def _drive(
    monkeypatch: pytest.MonkeyPatch,
    *,
    labels: CallTelemetryLabels | None,
    finish_reason: object = "stop",
) -> list[logging.LogRecord]:
    """Drive the REAL provider success path and return the token records."""
    _live(monkeypatch)
    response = MagicMock()
    response.read.return_value = _completion_body(finish_reason=finish_reason)
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("product_app.providers.urlopen", MagicMock(return_value=response))

    token_logger = logging.getLogger(telemetry_sink.TOKEN_TELEMETRY_LOGGER)
    captured: list[logging.LogRecord] = []
    previous_level = token_logger.level
    token_logger.setLevel(logging.DEBUG)
    token_logger.addHandler(_Collector(captured))
    try:
        provider_execution_service.call_with_prompt(
            openrouter_key="sk-or-test",
            model_id=_MODEL_ID,
            system_prompt="s",
            user_prompt="u",
            telemetry_labels=labels,
        )
    finally:
        token_logger.handlers = [h for h in token_logger.handlers if not isinstance(h, _Collector)]
        token_logger.setLevel(previous_level)
    return [r for r in captured if r.msg == "provider_call_tokens"]


def test_the_token_record_carries_the_run_and_stage_it_belongs_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED WHEN: ``_log_call_token_shape`` stops folding the labels in.

    This is the join. Without it a row can be grouped only by file order plus
    ``model_id``, which is guesswork the moment two runs overlap — and #290
    puts four models on both sides of that grouping.
    """
    records = _drive(
        monkeypatch,
        labels=CallTelemetryLabels(
            query_run_id=str(_RUN_ID), stage="debate_round_2", slot_number=3
        ),
    )
    assert len(records) == 1, f"expected exactly one token record, got {len(records)}"
    fields = records[0].__dict__
    assert fields["query_run_id"] == str(_RUN_ID)
    assert fields["stage"] == "debate_round_2"
    assert fields["slot_number"] == 3


def test_a_call_with_no_labels_emits_a_record_with_no_correlator_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED WHEN: the correlator is stamped unconditionally with a placeholder.

    The POSITIVE PARTNER for the test above (AGENTS.md rule 7): a row that
    genuinely has no run to point at must say so by ABSENCE, not by carrying a
    fabricated id that would sit in the dataset looking like a real one.
    """
    records = _drive(monkeypatch, labels=None)
    assert len(records) == 1, f"expected exactly one token record, got {len(records)}"
    fields = records[0].__dict__
    for name in ("query_run_id", "stage", "slot_number"):
        assert name not in fields, f"{name} was stamped on an unlabelled call"
    # The record is still a real record, not an empty one.
    assert fields["model_id"] == _MODEL_ID
    assert fields["prompt_tokens"] == 11


@pytest.mark.parametrize(
    ("wire_value", "expected"),
    [
        ("stop", "stop"),
        ("length", "length"),
        ("content_filter", "content_filter"),
        ("tool_calls", "tool_calls"),
        ("error", "error"),
        ("some-provider-specific-string", "other"),
        (_ABSENT, "absent"),
        (None, "absent"),
        (["length"], "absent"),
        (7, "absent"),
    ],
)
def test_the_finish_reason_is_reported_as_a_bounded_label(
    monkeypatch: pytest.MonkeyPatch, wire_value: object, expected: str
) -> None:
    """RED WHEN: the raw upstream string is passed through, or the map changes.

    Two things at once, and both matter.

    The label is BOUNDED because the upstream controls this string and the
    sink's rule is shapes and enumerations, never content (ADR-0031). An
    unknown value collapses to ``"other"`` rather than landing verbatim in a
    durable file.

    And it is reported for EVERY call, not only truncated ones. The existing
    ``is_truncated`` flag answers "was the answer clipped"; this answers "what
    did the provider say", which is what separates a clean stop from a
    ``"length"`` at full price on a receipt that looks healthy.
    """
    records = _drive(monkeypatch, labels=None, finish_reason=wire_value)
    assert len(records) == 1
    assert records[0].__dict__["finish_reason"] == expected


def test_the_correlator_fields_are_declared_on_the_sink() -> None:
    """RED WHEN: a correlator field is emitted without being declared.

    ``JsonFormatter.format`` drops an ``extra=`` key it already owns with no
    error and no warning, so an undeclared field would look healthy in
    production and carry nothing. The sink's own bidirectional gate
    (``test_telemetry_sink.py``) enforces this in general; this states the four
    names #290 depends on explicitly, so deleting one is named rather than
    counted.
    """
    for name in ("query_run_id", "stage", "slot_number", "finish_reason"):
        assert name in telemetry_sink.TELEMETRY_FIELD_NAMES, (
            f"{name!r} is emitted by the token record but not declared"
        )


def test_the_stage_labels_are_exactly_the_receipt_stage_names() -> None:
    """RED WHEN: a stage label drifts from the ``by_stage`` name it joins to.

    The whole value of ``stage`` is that a telemetry row joins a receipt line
    by string equality with no derivation. Two spellings for one stage is how
    the join silently returns nothing, so the names are DRIVEN out of
    ``build_measured_breakdown`` rather than retyped here.
    """
    from decimal import Decimal

    from product_app.costs import build_measured_breakdown

    breakdown = build_measured_breakdown(
        per_model_initial=[("m1", "M1", Decimal("0.01"))],
        debate_by_round={1: Decimal("0.01"), 2: Decimal("0.01")},
        synthesis_cost=Decimal("0.01"),
        judge=("j1", Decimal("0.01")),
    )
    receipt_stages = {line.stage for line in breakdown.by_stage}
    assert receipt_stages, "the receipt produced no stage lines to compare against"
    assert frozenset(receipt_stages) == telemetry_sink.TELEMETRY_STAGES, (
        f"telemetry stages {sorted(telemetry_sink.TELEMETRY_STAGES)} do not match "
        f"the receipt's {sorted(receipt_stages)}"
    )


def test_no_query_text_reaches_the_correlator(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED WHEN: a label carries content instead of an identifier.

    The sink writes counts, shapes and identifiers — never content. The
    ``user_prompt`` driven below is a distinctive sentinel; it must not appear
    anywhere in the emitted JSON.
    """
    _live(monkeypatch)
    response = MagicMock()
    response.read.return_value = _completion_body()
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("product_app.providers.urlopen", MagicMock(return_value=response))
    sentinel = "SECRET-QUESTION-9f2a"

    token_logger = logging.getLogger(telemetry_sink.TOKEN_TELEMETRY_LOGGER)
    captured: list[logging.LogRecord] = []
    previous_level = token_logger.level
    token_logger.setLevel(logging.DEBUG)
    token_logger.addHandler(_Collector(captured))
    try:
        provider_execution_service.call_with_prompt(
            openrouter_key="sk-or-test",
            model_id=_MODEL_ID,
            system_prompt="s",
            user_prompt=sentinel,
            telemetry_labels=CallTelemetryLabels(
                query_run_id=str(_RUN_ID), stage="initial_answers", slot_number=1
            ),
        )
    finally:
        token_logger.handlers = [h for h in token_logger.handlers if not isinstance(h, _Collector)]
        token_logger.setLevel(previous_level)

    rows = [r for r in captured if r.msg == "provider_call_tokens"]
    assert len(rows) == 1
    from product_app.logging_config import JsonFormatter

    emitted = JsonFormatter().format(rows[0])
    assert sentinel not in emitted, "the user's question reached the durable token stream"
    # POSITIVE PARTNER: the record really did carry the sentinel's SHAPE, so
    # the assertion above is not passing over an empty record.
    assert json.loads(emitted)["sent_chars"] >= len(sentinel)
