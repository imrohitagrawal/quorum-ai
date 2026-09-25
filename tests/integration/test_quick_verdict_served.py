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


#: W5's fourth pull request (ADR-0129): a quick run's judge answers the quick
#: schema, which has no ``disagreement_preserved`` and a ``claims`` list.
QUICK_BASE: dict[str, Any] = {
    **{k: v for k, v in VALID_VERDICT.items() if k != "disagreement_preserved"},
    "claims": [],
}


def _verdict(**overrides: Any) -> dict[str, Any]:
    return {**QUICK_BASE, **overrides}


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
    assert verdict.faithfulness is None and verdict.grounding is None
    assert verdict.sources_checked == []
    assert verdict.judge_status is None


def test_a_non_conforming_verdict_is_not_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure mode 2: the judge ran and answered something that is not a
    verdict. RED IF that reads as any of the three levels."""
    calls = _judge(monkeypatch, {"faithfulness": "high"})
    served = qr._result_response(_run(mode="quick"))
    assert len(calls) == 1
    assert served.quick_verdict is not None
    assert served.quick_verdict.level == "not_checked"
    assert served.quick_verdict.reasons is None
    # The status tells "the judge ran and gave no verdict" apart from "no
    # judge"; RED IF it is dropped (the no-judge test is the partner: None).
    assert served.quick_verdict.judge_status is not None


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


def test_no_judge_written_text_reaches_any_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure modes 1 and 4, decision D-5 whole. The judge's rationale,
    steerable by a cited page, reaches NO served body: not a quick one, not a
    panel one. RED IF any field serves the judge's own words. Partner: the
    quick run does carry a verdict, built from the same judge answer."""
    sentinel = "JUDGE-SENTINEL see https://evil.example/login"
    # The panel run's judge answers the panel schema, the quick run's the
    # quick schema (ADR-0129), so each half carries a verdict that parses.
    _judge(monkeypatch, {**VALID_VERDICT, "rationale": sentinel})
    panel = qr._result_response(_run(mode="panel"))
    assert panel.quick_verdict is None
    assert "JUDGE-SENTINEL" not in panel.model_dump_json()
    qr._judge_verdict_memo_clear_for_tests()
    _judge(monkeypatch, _verdict(rationale=sentinel))
    quick = qr._result_response(_run(mode="quick"))
    assert quick.quick_verdict is not None and quick.quick_verdict.level == "partly_supported"
    dumped = quick.model_dump_json()
    assert "JUDGE-SENTINEL" not in dumped
    assert "evil.example" not in dumped


def test_the_reasons_are_the_apps_sentences_from_the_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reasons restate the judge's scores in the app's words, and the
    scores are served as given. RED IF a sentence stops following its score
    (the numbers are varied here so a hard-coded sentence cannot pass)."""
    _judge(monkeypatch, _verdict(faithfulness=2, grounding=5, hallucination_risk="medium"))
    verdict = qr._result_response(_run(mode="quick", n_sources=3)).quick_verdict
    assert verdict is not None
    assert (verdict.faithfulness, verdict.grounding, verdict.hallucination_risk) == (
        2,
        5,
        "medium",
    )
    # RED IF the status of a judge that DID return a verdict is dropped.
    assert verdict.judge_status is not None
    assert verdict.reasons == [
        "The judge scored how closely the answer keeps to its cited sources 2 out of 5.",
        "It scored how well the answer's citations point at those sources 5 out of 5.",
        "It rated the risk of claims the sources do not support as medium.",
        "The judge checked the answer against 3 sources.",
    ]


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


def test_well_supported_needs_a_source_the_judge_could_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An answer with NO source cannot read "well supported" whatever the
    scores. RED IF the cap is removed. Partner: the same verdict with sources
    does read well_supported."""
    top = _verdict(faithfulness=5, grounding=5, hallucination_risk="low")
    _judge(monkeypatch, top)
    none = qr._result_response(_run(mode="quick", n_sources=0))
    assert none.quick_verdict is not None and none.quick_verdict.level == "partly_supported"
    qr._judge_verdict_memo_clear_for_tests()
    some = qr._result_response(_run(mode="quick", n_sources=2))
    assert some.quick_verdict is not None and some.quick_verdict.level == "well_supported"


def test_a_running_quick_answer_serves_no_verdict_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    """While the run is in flight no judge has been asked, and "not checked"
    would read as a verdict. RED IF a non-terminal quick run serves one.
    Partner: the same run, finished, does."""
    _judge(monkeypatch, _verdict())
    run = _run(mode="quick")
    query_run_repository._query_runs[run.query_run_id].status = (  # noqa: SLF001
        QueryRunStatus.INITIAL_ANSWERS_RUNNING
    )
    running = qr._result_response(query_run_repository.get(run.query_run_id))
    assert running.quick_verdict is None
    query_run_repository._query_runs[run.query_run_id].status = QueryRunStatus.COMPLETED  # noqa: SLF001
    done = qr._result_response(query_run_repository.get(run.query_run_id))
    assert done.quick_verdict is not None and done.quick_verdict.level == "partly_supported"


def test_a_migration_race_loser_still_opens_the_store(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two processes opening one old database can both see ``mode`` missing;
    the second ALTER fails with "duplicate column name". RED IF that error
    stops the store opening. Simulated by making the column check miss once
    on a database that already has the column."""
    from product_app.run_history_store import RunHistoryStore

    db = str(tmp_path / "runs.sqlite3")
    RunHistoryStore(db).close()
    monkeypatch.setattr(RunHistoryStore, "_columns", lambda self: set())
    store = RunHistoryStore(db)
    try:
        assert store.get("absent") is None
    finally:
        store.close()


def test_any_other_migration_error_still_stops_the_store(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Partner of the race test: only "duplicate column name" is tolerated.
    RED IF the migration swallows every OperationalError."""
    import sqlite3

    from product_app.run_history_store import RunHistoryStore

    real_connect = sqlite3.connect

    class _Conn:
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def execute(self, sql: str, *args: Any) -> Any:
            if sql.startswith("ALTER TABLE"):
                raise sqlite3.OperationalError("database is locked")
            return self._inner.execute(sql, *args)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    monkeypatch.setattr(RunHistoryStore, "_columns", lambda self: set())
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: _Conn(real_connect(*a, **k)))
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        RunHistoryStore(str(tmp_path / "runs.sqlite3"))


def test_a_running_high_stakes_quick_answer_already_carries_the_notice() -> None:
    """The caveat does not wait for the verdict. RED IF the safety notice is
    gated on the run being finished."""
    run = _run(mode="quick", query=HIGH_STAKES_QUERY)
    query_run_repository._query_runs[run.query_run_id].status = (  # noqa: SLF001
        QueryRunStatus.INITIAL_ANSWERS_RUNNING
    )
    served = qr._result_response(query_run_repository.get(run.query_run_id))
    assert served.quick_verdict is None
    assert served.result.safety_notice == HIGH_STAKES_NOTICE_FRAGMENT


# --- W5's fourth pull request (ADR-0129): the verification-only judge ------


def test_a_quick_run_asks_the_quick_prompt_and_a_panel_run_the_panel_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The request path picks the prompt by the run's mode. RED IF a quick
    run is judged with the panel prompt (it would be asked about a synthesis
    it does not have) or a panel run with the quick prompt (every production
    panel run's judge would change). Both ids are literals here."""
    calls = _judge(monkeypatch, _verdict())
    qr._result_response(_run(mode="quick"))
    qr._judge_verdict_memo_clear_for_tests()
    qr._result_response(_run(mode="panel"))
    assert len(calls) == 2
    assert "PR-EVAL-JUDGE-QUICK-v1" in calls[0]["system_prompt"]
    assert "PR-EVAL-JUDGE-v1" not in calls[0]["system_prompt"]
    assert "PR-EVAL-JUDGE-v1" in calls[1]["system_prompt"]
    assert "PR-EVAL-JUDGE-QUICK-v1" not in calls[1]["system_prompt"]


def test_a_panel_shaped_answer_to_a_quick_run_is_not_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The quick run parses the quick schema only. A panel-shaped verdict is
    non-conforming there: the call is billed as dispatched and the page reads
    "not checked". RED IF the quick path accepts the panel shape."""
    calls = _judge(monkeypatch, dict(VALID_VERDICT))
    served = qr._result_response(_run(mode="quick"))
    assert len(calls) == 1
    assert served.quick_verdict is not None
    assert served.quick_verdict.level == "not_checked"
    assert served.quick_verdict.judge_status == "no_verdict_dispatched"


#: The whole of ``_answer``'s text, which the judge quotes exactly.
_REAL_QUOTE = "Canberra was chosen as a compromise between Sydney and Melbourne [1]."


def test_the_judges_claims_are_served_when_their_words_are_the_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end through the request path. RED IF a claim quoting the
    answer is not served, or a claim the judge wrote is. The count of
    dropped claims is served."""
    _judge(
        monkeypatch,
        _verdict(
            claims=[
                {"quote": _REAL_QUOTE, "source": 1, "support": "supported"},
                {"quote": "Canberra is the largest city.", "source": 2, "support": "contradicted"},
            ]
        ),
    )
    verdict = qr._result_response(_run(mode="quick")).quick_verdict
    assert verdict is not None
    assert [(c.quote, c.source, c.support) for c in verdict.claims] == [
        (_REAL_QUOTE, 1, "supported")
    ]
    assert verdict.claims_dropped == 1


def test_no_judge_written_claim_text_reaches_any_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure mode 1 and decision D-5, extended to claims. A sentinel the
    judge wrote into a claim (not the answer's text) and into the rationale
    reaches no quick and no panel body. Partner: the same quick verdict does
    serve its real claim, so the claim path is live."""
    _judge(
        monkeypatch,
        _verdict(
            rationale="JUDGE-SENTINEL-RATIONALE",
            claims=[
                {
                    "quote": "JUDGE-SENTINEL-CLAIM visit https://evil.example/login",
                    "source": 1,
                    "support": "supported",
                },
                {
                    "quote": "Canberra was chosen as a compromise",
                    "source": 1,
                    "support": "supported",
                },
            ],
        ),
    )
    quick = qr._result_response(_run(mode="quick"))
    assert quick.quick_verdict is not None
    assert [c.quote for c in quick.quick_verdict.claims] == ["Canberra was chosen as a compromise"]
    dumped = quick.model_dump_json()
    assert "JUDGE-SENTINEL" not in dumped and "evil.example" not in dumped
    qr._judge_verdict_memo_clear_for_tests()
    panel = qr._result_response(_run(mode="panel"))
    assert "JUDGE-SENTINEL" not in panel.model_dump_json()


def test_a_quick_verdict_never_reaches_the_panel_evaluation_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The quick verdict is memoised and billed, but the panel engine is
    handed no judge for a quick run (its record needs
    ``disagreement_preserved``, which a quick verdict does not have; failure
    mode 11). RED IF the memo judge hands the quick verdict to the engine:
    the evaluation then fails to build. Partner: the quick verdict IS in the
    memo and IS served."""
    from product_app.synthesis import build_agreement_and_positions

    _judge(monkeypatch, _verdict(faithfulness=5, grounding=5))
    run = _run(mode="quick")
    agreement, _ = build_agreement_and_positions(
        initial_answers=run.initial_answers, debate_outputs=[], final_synthesis=None
    )
    result = qr._evaluate_terminal_run(run, agreement=agreement)
    assert result is not None
    assert result.evaluation.judge is None
    outcome = qr._judge_verdict_memo[str(run.query_run_id)]
    assert type(outcome.verdict).__name__ == "EvalJudgeQuickVerdict"
    served = qr._result_response(run).quick_verdict
    assert served is not None and served.level == "well_supported"
