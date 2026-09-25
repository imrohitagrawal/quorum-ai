"""W5, second pull request: what a quick answer serves (ADR-0127).

The owner's decision of 2026-09-24: a quick answer shows the judge's
verdict in three levels "along with reasons and artifacts", no agreement
figure, and keeps its safety notice. Failure modes listed first in
``docs/analysis/2026-09-25-w5-quick-verdict-failure-modes.md``; each test
names the row it pins and what turns it red. No provider call is made: the
run is built in the repository and the judge seam is stubbed.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from tests.unit.test_evaluation_judge import VALID_VERDICT

from product_app import query_run_orchestration as qr
from product_app.config import settings
from product_app.costs import CostEstimate, CostThresholdAction
from product_app.model_slots import DEFAULT_MODEL_IDS, validate_model_slots_with_search
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    LiveProviderResult,
    ProviderPath,
    SourceReference,
    TokenUsage,
    provider_execution_service,
)
from product_app.query_run_orchestration import QueryRunStatus, query_run_repository
from product_app.synthesis import HIGH_STAKES_NOTICE_FRAGMENT

QUERY = "What is the capital of Australia and why was it chosen?"
HIGH_STAKES_QUERY = "Should I ask my doctor about a different diagnosis?"


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", False)
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", "")
    monkeypatch.setattr(settings, "quorum_eval_judge_model_id", "")
    query_run_repository.clear()
    qr._judge_verdict_memo_clear_for_tests()


def _judge(monkeypatch: pytest.MonkeyPatch, verdict: dict[str, Any]) -> list[Any]:
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", "sk-not-a-real-key")
    monkeypatch.setattr(settings, "quorum_eval_judge_model_id", "vendor/judge-model")
    calls: list[Any] = []

    def _fake(**kwargs: Any) -> LiveProviderResult:
        calls.append(kwargs)
        return LiveProviderResult(
            answer_text=json.dumps(verdict),
            sources=[],
            usage=TokenUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120),
        )

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", _fake)
    return calls


def _answer(slot: int, model_id: str, n_sources: int) -> InitialModelAnswer:
    return InitialModelAnswer(
        slot_number=slot,
        model_id=model_id,
        display_name=model_id,
        answer_text="Canberra was chosen as a compromise between Sydney and Melbourne [1].",
        sources=[
            SourceReference(
                title=f"Source {n}",
                url=f"https://example.org/page-{n}",
                provider=ProviderPath.OPENROUTER_SEARCH,
            )
            for n in range(n_sources)
        ],
        provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
        provider_path=ProviderPath.OPENROUTER_SEARCH,
        fallback_used=False,
        status=InitialAnswerStatus.COMPLETED,
        latency_ms=10,
        citation_coverage=CitationCoverage(
            answer_count=1,
            sourced_answer_count=1,
            sourced_answer_ratio=Decimal(1),
            target_met=True,
        ),
        token_usage=TokenUsage(prompt_tokens=1000, completion_tokens=200, total_tokens=1200),
    )


def _run(*, mode: str, query: str = QUERY, n_sources: int = 3) -> Any:
    ids = list(DEFAULT_MODEL_IDS)[:1] if mode == "quick" else list(DEFAULT_MODEL_IDS)
    run = query_run_repository.create(
        account_id=uuid4(),
        query_text=query,
        model_slots=validate_model_slots_with_search(ids, mode=mode),
        cost_estimate=CostEstimate(
            estimated_cost_usd=Decimal("0.0200"),
            threshold_action=CostThresholdAction.ALLOW,
            confirmation_token=None,
            reasons=[],
        ),
        mode=mode,  # type: ignore[arg-type]
    )
    for slot, model_id in enumerate(ids, 1):
        query_run_repository.record_initial_answer(
            run.query_run_id, _answer(slot, model_id, n_sources)
        )
    query_run_repository.update_status(run.query_run_id, status_value=QueryRunStatus.COMPLETED)
    return query_run_repository.get(run.query_run_id)


def _verdict(**overrides: Any) -> dict[str, Any]:
    return {**VALID_VERDICT, **overrides}


@pytest.mark.parametrize(
    ("scores", "level"),
    [
        ({"faithfulness": 5, "grounding": 5, "hallucination_risk": "low"}, "well_supported"),
        ({"faithfulness": 4, "grounding": 4, "hallucination_risk": "low"}, "well_supported"),
        ({"faithfulness": 4, "grounding": 3, "hallucination_risk": "low"}, "partly_supported"),
        ({"faithfulness": 5, "grounding": 5, "hallucination_risk": "medium"}, "partly_supported"),
        ({"faithfulness": 1, "grounding": 1, "hallucination_risk": "low"}, "partly_supported"),
        ({"faithfulness": 0, "grounding": 5, "hallucination_risk": "low"}, "not_supported"),
        ({"faithfulness": 5, "grounding": 0, "hallucination_risk": "low"}, "not_supported"),
        ({"faithfulness": 5, "grounding": 5, "hallucination_risk": "high"}, "not_supported"),
    ],
)
def test_the_level_follows_the_verdict(
    monkeypatch: pytest.MonkeyPatch, scores: dict[str, Any], level: str
) -> None:
    """Failure modes 2 and 3. Boundaries pinned on both sides: 4/4/low is
    the lowest well_supported, 4/3 and 5/5/medium are not; a zero or high
    risk is not_supported, as ``verdict_supports_verification`` already rules.
    RED IF a threshold moves or the refusal rule is not honoured."""
    calls = _judge(monkeypatch, _verdict(**scores))
    served = qr._result_response(_run(mode="quick"))
    assert len(calls) == 1
    assert served.quick_verdict is not None
    assert served.quick_verdict.level == level


def test_no_judge_means_not_checked_never_a_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure mode 2. RED IF a quick answer with no judge configured serves
    any level but ``not_checked``, or claims reasons or checked sources."""
    served = qr._result_response(_run(mode="quick"))
    verdict = served.quick_verdict
    assert verdict is not None
    assert verdict.level == "not_checked"
    assert verdict.reasons is None
    assert verdict.sources_checked == []


def test_a_non_conforming_verdict_is_not_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure mode 2: the judge ran and answered something that is not a
    verdict. RED IF that reads as any of the three levels."""
    calls = _judge(monkeypatch, {"faithfulness": "high"})
    served = qr._result_response(_run(mode="quick"))
    assert len(calls) == 1
    assert served.quick_verdict is not None
    assert served.quick_verdict.level == "not_checked"
    assert served.quick_verdict.reasons is None


def test_the_reasons_are_served_as_plain_text_with_links_reduced_to_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure mode 1. RED IF a full URL (a clickable destination an
    injected page could choose) survives into the served reasons. Partner:
    the rest of the judge's sentence, and the host, are kept."""
    _judge(
        monkeypatch,
        _verdict(
            rationale=(
                "Claims track the sources. See https://evil.example.com/login?next=x "
                "and http://www.other.example/path for details."
            )
        ),
    )
    reasons = qr._result_response(_run(mode="quick")).quick_verdict.reasons  # type: ignore[union-attr]
    assert reasons is not None
    assert "https://" not in reasons and "http://" not in reasons
    assert "/login" not in reasons and "/path" not in reasons
    assert reasons.startswith("Claims track the sources. See evil.example.com")
    assert "www.other.example" in reasons


def test_the_sources_listed_are_the_ones_the_judge_saw(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure mode 6. The served list is the judge's own selection, capped
    at ``JUDGE_MAX_SOURCE_LINES``. RED IF the list is longer than what the
    judge was given or disagrees with the prompt's SOURCES block."""
    from product_app.evaluation import JUDGE_MAX_SOURCE_LINES

    calls = _judge(monkeypatch, _verdict())
    served = qr._result_response(_run(mode="quick", n_sources=JUDGE_MAX_SOURCE_LINES + 5))
    checked = served.quick_verdict.sources_checked  # type: ignore[union-attr]
    assert len(checked) == JUDGE_MAX_SOURCE_LINES
    prompt = repr(calls[0])
    for source in checked:
        assert source.url in prompt
    assert f"page-{JUDGE_MAX_SOURCE_LINES}" not in {s.url.rsplit("/", 1)[-1] for s in checked}


def test_a_panel_run_serves_no_quick_verdict_and_no_judge_prose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure mode 4. RED IF the quick verdict, or its reasons, appear on a
    panel run. Partner: the same judge on a quick run does serve it."""
    _judge(monkeypatch, _verdict(rationale="PANEL-SENTINEL reasons"))
    panel = qr._result_response(_run(mode="panel"))
    assert panel.quick_verdict is None
    assert "PANEL-SENTINEL" not in panel.model_dump_json()
    qr._judge_verdict_memo_clear_for_tests()
    quick = qr._result_response(_run(mode="quick"))
    assert quick.quick_verdict is not None
    assert "PANEL-SENTINEL" in (quick.quick_verdict.reasons or "")


def test_a_high_stakes_quick_answer_carries_the_safety_notice() -> None:
    """Failure mode 8. RED IF a quick answer to a high-stakes question has
    no caveat. Partners: an ordinary question gets none, and a panel run
    keeps using its synthesis carrier (this field stays null)."""
    high = qr._result_response(_run(mode="quick", query=HIGH_STAKES_QUERY))
    assert high.result.safety_notice == HIGH_STAKES_NOTICE_FRAGMENT
    plain = qr._result_response(_run(mode="quick"))
    assert plain.result.safety_notice is None
    panel = qr._result_response(_run(mode="panel", query=HIGH_STAKES_QUERY))
    assert panel.result.safety_notice is None


def test_an_old_run_store_gains_the_mode_column_and_keeps_its_rows(tmp_path: Any) -> None:
    """Failure mode 9. A database created by the schema before W5 (no
    ``mode``) is opened by this code: the column is added in place, the old
    row reads "panel", and a new quick row reads "quick". RED IF the column is
    not added (the insert fails) or an existing row is lost."""
    import sqlite3

    from product_app.run_history_store import RunHistoryStore

    db = tmp_path / "runs.sqlite3"
    old_schema = RunHistoryStore._SCHEMA.replace(
        ",\n        mode TEXT NOT NULL DEFAULT 'panel'", ""
    )
    assert "mode TEXT" not in old_schema and "mode TEXT" in RunHistoryStore._SCHEMA
    conn = sqlite3.connect(db)
    conn.executescript(old_schema)
    conn.execute(
        "INSERT INTO runs VALUES ('old-run', NULL, 'c', 'completed', '2026-09-01T00:00:00+00:00',"
        " '2026-09-01T00:00:01+00:00', 1, '[]', 1, 0, 4, 0, 4, 4, NULL, 'estimated',"
        " '0.1', '0.1', '[]', '[]', NULL, NULL)"
    )
    conn.commit()
    conn.close()

    store = RunHistoryStore(str(db))
    try:
        old = store.get("old-run")
        assert old is not None and old.mode == "panel" and old.agreement_total == 4
        run = _run(mode="quick")
        response = qr._result_response(run)
        from product_app.run_history_store import RunHistoryRow

        store.record_terminal_run(
            RunHistoryRow(
                query_run_id=str(run.query_run_id),
                account_id=None,
                correlation_id="c2",
                status="completed",
                created_at=run.created_at,
                completed_at=run.updated_at,
                elapsed_time_ms=response.elapsed_time_ms,
                model_ids=[s.model_id for s in run.model_slots],
                demo_mode=False,
                live_count=1,
                local_count=0,
                material_claim_count=1,
                agreement_aligned=0,
                agreement_total=0,
                citation_ratio=None,
                cost_source="estimated",
                estimated_cost_usd=Decimal("0.01"),
                actual_cost_usd=Decimal("0.01"),
                failed_steps=[],
                missing_steps=[],
                eval_json=None,
                trust_json=None,
                mode="quick",
            )
        )
        new = store.get(str(run.query_run_id))
        assert new is not None and new.mode == "quick"
    finally:
        store.close()


def test_a_quick_run_is_stored_as_quick(monkeypatch: pytest.MonkeyPatch) -> None:
    """The wire: the orchestrator writes the run's mode. RED IF the durable
    row of a quick run reads "panel". Partner: a panel run reads "panel"."""
    from product_app import run_history_store

    with run_history_store.configure_for_tests() as store:
        quick = _run(mode="quick")
        panel = _run(mode="panel")
        qr._persist_terminal_run(quick.query_run_id)
        qr._persist_terminal_run(panel.query_run_id)
        quick_row = store.get(str(quick.query_run_id))
        panel_row = store.get(str(panel.query_run_id))
    assert quick_row is not None and quick_row.mode == "quick"
    assert panel_row is not None and panel_row.mode == "panel"
