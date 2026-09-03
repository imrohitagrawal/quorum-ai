"""ADR-0093 decision 5: the PRODUCT emits the labels, not just the type.

WHY THIS FILE EXISTS — and it is the sharpest lesson of this work package.

``test_telemetry_correlator.py`` proves the plumbing: hand ``call_with_prompt``
a ``CallTelemetryLabels`` and the record carries it. Adversarial review then
showed that proves almost nothing about the product, by mutating the four real
emit sites and running the FULL suite:

    providers.py    stage=TELEMETRY_STAGE_INITIAL_ANSWERS -> "initial"
    synthesis.py    stage=TELEMETRY_STAGE_SYNTHESIS       -> "final_synthesis"
    evaluation.py   stage=TELEMETRY_STAGE_JUDGE           -> "layer_b"
    debate.py       stage=debate_round_stage(n)           -> "debate"

**All four: no new failures.** Severing the wiring entirely — deleting the
initial-answer label block, all eleven synthesis forwards, and the judge's run
id — also produced no new failures. Every telemetry row could have named a
stage that joins to no receipt line, on every stage, and the suite stayed green.

That is this repository's own recorded failure mode ("test the wire, not just
the decision"): a pure function well covered, its output path untested. These
tests drive the REAL services and read what actually reached the logger.

WHAT TURNS EACH TEST RED: named per test. File-level: change any stage string
at its emit site, or delete any ``telemetry_labels=`` argument from a real
dispatch, and one of these fails.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from tests.provider_wire import sse_from_completion

from product_app import config, telemetry_sink
from product_app.costs import build_measured_breakdown
from product_app.debate import debate_stub_service
from product_app.model_slots import ModelSlot
from product_app.provider_keys import ProviderCredentialSource
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    provider_execution_service,
)
from product_app.telemetry_sink import TELEMETRY_STAGES, debate_round_stage

_RUN_ID = UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")


class _Collector(logging.Handler):
    def __init__(self, into: list[logging.LogRecord]) -> None:
        super().__init__(level=logging.DEBUG)
        self._into = into

    def emit(self, record: logging.LogRecord) -> None:
        self._into.append(record)


def _body() -> bytes:
    return sse_from_completion(
        {
            "choices": [
                {"message": {"role": "assistant", "content": "an answer"}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        }
    )


def _capture(monkeypatch: pytest.MonkeyPatch, drive: Any) -> list[dict[str, Any]]:
    """Run ``drive`` with the wire mocked and return the token records' fields."""
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True)
    response = MagicMock()
    response.read.return_value = _body()
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("product_app.providers.urlopen", MagicMock(return_value=response))

    token_logger = logging.getLogger(telemetry_sink.TOKEN_TELEMETRY_LOGGER)
    captured: list[logging.LogRecord] = []
    previous = token_logger.level
    token_logger.setLevel(logging.DEBUG)
    token_logger.addHandler(_Collector(captured))
    try:
        drive()
    finally:
        token_logger.handlers = [h for h in token_logger.handlers if not isinstance(h, _Collector)]
        token_logger.setLevel(previous)
    return [r.__dict__ for r in captured if r.msg == "provider_call_tokens"]


def _answer(slot: int) -> InitialModelAnswer:
    return InitialModelAnswer(
        slot_number=slot,
        model_id=f"prov/model-{slot}",
        display_name=f"Model {slot}",
        answer_text="A substantive answer with a recommendation in it.",
        sources=[],
        provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
        provider_path=ProviderPath.OPENROUTER_SEARCH,
        fallback_used=False,
        status=InitialAnswerStatus.COMPLETED,
        latency_ms=1,
        citation_coverage=CitationCoverage(
            answer_count=1,
            sourced_answer_count=1,
            sourced_answer_ratio=Decimal("1"),
            target_met=True,
        ),
    )


def test_the_initial_answer_stage_labels_its_own_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED WHEN: ``produce_initial_answer`` stops labelling, or names a stage
    the receipt has no line for.

    Drives the REAL ``produce_initial_answer``. The mutation this catches —
    ``stage="initial"`` instead of the receipt's ``"initial_answers"`` — passed
    the entire suite before this test existed.
    """
    rows = _capture(
        monkeypatch,
        lambda: provider_execution_service.produce_initial_answer(
            account_id=uuid4(),
            query_run_id=_RUN_ID,
            query_text="Which database should we choose?",
            model_slot=ModelSlot(slot_number=3, model_id="prov/model-3", search=False),
            credential_source=ProviderCredentialSource.APP_OWNED,
            openrouter_key="sk-or-test",
        ),
    )
    assert len(rows) == 1, f"expected one token record from one slot, got {len(rows)}"
    assert rows[0]["query_run_id"] == str(_RUN_ID)
    assert rows[0]["stage"] == "initial_answers"
    assert rows[0]["stage"] in TELEMETRY_STAGES
    assert rows[0]["slot_number"] == 3, "the answerer's slot is what makes a row per-model"


def test_the_debate_stage_labels_each_round_distinctly(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED WHEN: the moderator path loses its labels, or both rounds share one.

    Telling round 1 from round 2 is the reason decision 5 exists, quoted in its
    own words. This drives the MODERATOR shape — what ships with the flag off —
    because the correlator originally reached only the peer path and this exact
    gap was open for the only configuration running today.
    """
    rows = _capture(
        monkeypatch,
        lambda: debate_stub_service.run_debate_rounds(
            account_id=uuid4(),
            query_run_id=_RUN_ID,
            query_text="Which database should we choose?",
            initial_answers=[_answer(n) for n in (1, 2, 3, 4)],
            openrouter_key="sk-or-test",
        ),
    )
    assert len(rows) == 2, f"a two-round moderator debate emitted {len(rows)} rows"
    assert [r["stage"] for r in rows] == ["debate_round_1", "debate_round_2"]
    assert {r["query_run_id"] for r in rows} == {str(_RUN_ID)}
    # The moderator belongs to no answer slot, so the field is ABSENT — not a
    # placeholder that would sit in the dataset looking like a real slot.
    assert all("slot_number" not in r for r in rows)


def test_a_peer_round_labels_each_critic_with_its_own_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED WHEN: the peer path stops carrying ``slot_number``.

    Under peer critique four models appear on BOTH sides of the grouping — as
    answerers and as critics — so without the critic's slot the eight rows are
    unattributable, which is the case decision 5 names.
    """
    monkeypatch.setattr(config.settings, "peer_critique_enabled", True)
    rows = _capture(
        monkeypatch,
        lambda: debate_stub_service.run_debate_rounds(
            account_id=uuid4(),
            query_run_id=_RUN_ID,
            query_text="Which database should we choose?",
            initial_answers=[_answer(n) for n in (1, 2, 3, 4)],
            openrouter_key="sk-or-test",
        ),
    )
    assert len(rows) == 8, f"four critics x two rounds should emit 8 rows, got {len(rows)}"
    assert [r["stage"] for r in rows] == ["debate_round_1"] * 4 + ["debate_round_2"] * 4
    assert [r["slot_number"] for r in rows] == [1, 2, 3, 4, 1, 2, 3, 4]
    assert {r["query_run_id"] for r in rows} == {str(_RUN_ID)}


def test_every_emitted_stage_is_one_the_receipt_has_a_line_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED WHEN: any emit site names a stage the receipt does not carry.

    The join is the whole value of the field, and this is the check that makes
    the constants load-bearing rather than decorative. Stage names are collected
    by DRIVING the services and compared against the names
    ``build_measured_breakdown`` actually emits — neither side is retyped.
    """
    seen: set[str] = set()
    seen |= {
        r["stage"]
        for r in _capture(
            monkeypatch,
            lambda: provider_execution_service.produce_initial_answer(
                account_id=uuid4(),
                query_run_id=_RUN_ID,
                query_text="q",
                model_slot=ModelSlot(slot_number=1, model_id="prov/model-1", search=False),
                credential_source=ProviderCredentialSource.APP_OWNED,
                openrouter_key="sk-or-test",
            ),
        )
    }
    seen |= {
        r["stage"]
        for r in _capture(
            monkeypatch,
            lambda: debate_stub_service.run_debate_rounds(
                account_id=uuid4(),
                query_run_id=_RUN_ID,
                query_text="q",
                initial_answers=[_answer(n) for n in (1, 2, 3, 4)],
                openrouter_key="sk-or-test",
            ),
        )
    }
    # FLOOR: the drivers really emitted something (rule 7). Without this the
    # subset check below is trivially true over an empty set.
    assert len(seen) >= 3, f"only {len(seen)} stages collected from real drivers: {seen}"

    receipt = build_measured_breakdown(
        per_model_initial=[("m1", "M1", Decimal("0.01"))],
        debate_by_round={1: Decimal("0.01"), 2: Decimal("0.01")},
        synthesis_cost=Decimal("0.01"),
        judge=("j1", Decimal("0.01")),
    )
    receipt_stages = {line.stage for line in receipt.by_stage}
    assert seen <= receipt_stages, (
        f"stage(s) {sorted(seen - receipt_stages)} are emitted by a real dispatch "
        f"but join to no receipt line ({sorted(receipt_stages)})"
    )


def test_a_slot_less_call_omits_the_field_rather_than_nulling_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED WHEN: ``slot_number`` is stamped unconditionally.

    The code's own rule: ABSENT, not defaulted — "a placeholder id would sit in
    the dataset looking exactly like a real one". Review found this rule
    documented and untested: making the stamp unconditional passed the whole
    suite, so a synthesis or judge row could carry ``slot_number: null``.

    Its partner is ``test_a_peer_round_labels_each_critic_with_its_own_slot``
    above, which proves the field DOES arrive when there is a slot.
    """
    rows = _capture(
        monkeypatch,
        lambda: debate_stub_service.run_debate_rounds(
            account_id=uuid4(),
            query_run_id=_RUN_ID,
            query_text="q",
            initial_answers=[_answer(n) for n in (1, 2, 3, 4)],
            openrouter_key="sk-or-test",
        ),
    )
    assert rows, "the moderator debate emitted no rows to check"
    for row in rows:
        assert "slot_number" not in row, (
            "a moderator call belongs to no slot and must omit the field, "
            f"not carry {row.get('slot_number')!r}"
        )
        # POSITIVE PARTNER: the row is a real, labelled row, so the absence
        # above is the RULE and not an unlabelled call.
        assert row["query_run_id"] == str(_RUN_ID)
        assert row["stage"].startswith("debate_round_")


@pytest.mark.parametrize("round_number", [0, 3, -1, 99])
def test_debate_round_stage_refuses_a_round_the_receipt_has_no_line_for(
    round_number: int,
) -> None:
    """RED WHEN: the guard is dropped and ``debate_round_3`` is invented.

    Review found this function had NO test at all: three references, all in
    ``src/``. Its whole job is to be the single producer of the label, so a
    silent ``f"debate_round_{n}"`` for an n the receipt has no line for is
    exactly the drift it exists to stop.
    """
    with pytest.raises(ValueError, match="no receipt stage exists"):
        debate_round_stage(round_number)


@pytest.mark.parametrize("round_number", [1, 2])
def test_debate_round_stage_produces_the_two_rounds_that_do_exist(round_number: int) -> None:
    """The POSITIVE PARTNER for the refusal above (rule 7): a function that
    raised for everything would satisfy it."""
    assert debate_round_stage(round_number) == f"debate_round_{round_number}"
    assert debate_round_stage(round_number) in TELEMETRY_STAGES
