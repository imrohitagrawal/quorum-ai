"""Unit tests for the feedback store and audit module.

These tests exercise the persistence + aggregation paths without
calling the real audit model. The audit model path is covered by an
integration test that mocks the HTTP call.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from product_app.feedback_audit import (
    AuditStatistics,
    CostStats,
    DebateStats,
    Finding,
    SafetyStats,
    SynthesisStats,
    _aggregate_cost,
    _aggregate_provider,
    _aggregate_synthesis,
    _parse_audit_response,
    build_audit_user_prompt,
    collect_statistics,
    generate_status_md,
    render_report,
)
from product_app.feedback_store import (
    configure,
    configure_for_tests,
    record_event,
)

# ---------------------------------------------------------------------------
# FeedbackStore
# ---------------------------------------------------------------------------


def test_feedback_store_round_trip() -> None:
    """Persisted events read back in id order with original payload intact."""
    with configure_for_tests() as store:
        run_id = uuid4()
        record_event(
            recorder="synthesis",
            event_type="synthesis_completed",
            account_id=uuid4(),
            query_run_id=run_id,
            payload={
                "duration_ms": 1234,
                "citation_coverage_ratio": "0.75",
                "status": "completed",
            },
        )
        record_event(
            recorder="provider",
            event_type="provider_initial_answer_completed",
            account_id=uuid4(),
            query_run_id=run_id,
            payload={
                "model_id": "openai/gpt-4o-mini",
                "provider_path": "openrouter_search",
                "duration_ms": 800,
                "fallback_used": False,
                "source_count": 3,
            },
        )
        rows = list(store.iter_events())
    assert len(rows) == 2
    assert rows[0].recorder == "synthesis"
    assert rows[0].payload["citation_coverage_ratio"] == "0.75"
    assert rows[1].recorder == "provider"
    assert rows[1].payload["model_id"] == "openai/gpt-4o-mini"


def test_feedback_store_iter_events_filters_by_since() -> None:
    """The ``since`` argument filters by ``recorded_at`` (lower bound)."""
    with configure_for_tests() as store:
        record_event(
            recorder="synthesis",
            event_type="synthesis_completed",
            account_id=uuid4(),
            query_run_id=uuid4(),
            payload={"duration_ms": 1, "citation_coverage_ratio": "1.0"},
        )
        cutoff = datetime.now(UTC)
        # No new event after the cutoff: should be empty.
        rows = list(store.iter_events(since=cutoff + timedelta(seconds=1)))
    assert rows == []


def test_record_event_is_noop_when_store_unconfigured() -> None:
    """Recording without a configured store does not raise."""
    configure(None)
    # Should be a silent no-op.
    record_event(
        recorder="synthesis",
        event_type="synthesis_completed",
        account_id=uuid4(),
        query_run_id=uuid4(),
        payload={},
    )


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------


def _provider_event(model_id: str, provider_path: str, duration_ms: int) -> object:
    return type(
        "Row",
        (),
        {
            "recorder": "provider",
            "payload": {
                "model_id": model_id,
                "provider_path": provider_path,
                "duration_ms": duration_ms,
            },
        },
    )()


def _synthesis_event(
    *,
    duration_ms: int,
    coverage: str,
    status: str = "completed",
    high_stakes: bool = False,
    false_consensus: bool = True,
) -> object:
    return type(
        "Row",
        (),
        {
            "recorder": "synthesis",
            "payload": {
                "duration_ms": duration_ms,
                "citation_coverage_ratio": coverage,
                "status": status,
                "high_stakes_warning_required": high_stakes,
                "false_consensus_preserved": false_consensus,
            },
        },
    )()


def test_aggregate_provider_computes_stats_per_model() -> None:
    events = [
        _provider_event("openai/gpt-4o-mini", "openrouter_search", 800),
        _provider_event("openai/gpt-4o-mini", "openrouter_search", 1200),
        _provider_event("openai/gpt-4o-mini", "local_simulation", 600),
    ]
    stats = _aggregate_provider(events)
    assert "openai/gpt-4o-mini" in stats
    slot_stats = stats["openai/gpt-4o-mini"]
    assert slot_stats.total_calls == 3
    assert slot_stats.simulation_count == 1
    assert slot_stats.avg_duration_ms == pytest.approx(866.66, abs=1)


def test_aggregate_synthesis_computes_coverage_average() -> None:
    events = [
        _synthesis_event(duration_ms=1000, coverage="0.50"),
        _synthesis_event(duration_ms=2000, coverage="0.90"),
    ]
    stats = _aggregate_synthesis(events)
    assert stats.total == 2
    assert stats.completed == 2
    assert stats.avg_citation_coverage == pytest.approx(0.70, abs=0.01)
    assert stats.avg_duration_ms == pytest.approx(1500, abs=1)


def test_aggregate_cost_groups_by_threshold_action() -> None:
    cost_rows = [
        type(
            "Row",
            (),
            {
                "recorder": "cost",
                "payload": {
                    "threshold_action": "allow",
                    "estimated_cost_usd": "0.05",
                },
            },
        )(),
        type(
            "Row",
            (),
            {
                "recorder": "cost",
                "payload": {
                    "threshold_action": "allow",
                    "estimated_cost_usd": "0.07",
                },
            },
        )(),
        type(
            "Row",
            (),
            {
                "recorder": "cost",
                "payload": {
                    "threshold_action": "block",
                    "estimated_cost_usd": "0.30",
                },
            },
        )(),
    ]
    stats = _aggregate_cost(cost_rows)
    assert stats.allowed == 2
    assert stats.blocked == 1
    assert stats.avg_estimated_cost_usd == pytest.approx(0.14, abs=0.01)


def test_collect_statistics_counts_distinct_runs() -> None:
    """The same query_run_id across multiple recorders counts as one run."""
    run_id = str(uuid4())
    events_by_recorder = {
        "provider": [
            type(
                "Row",
                (),
                {
                    "recorder": "provider",
                    "query_run_id": run_id,
                    "payload": {
                        "model_id": "openai/gpt-4o-mini",
                        "provider_path": "openrouter_search",
                        "duration_ms": 500,
                    },
                },
            )()
        ],
        "synthesis": [
            type(
                "Row",
                (),
                {
                    "recorder": "synthesis",
                    "query_run_id": run_id,
                    "payload": {
                        "duration_ms": 1000,
                        "citation_coverage_ratio": "0.80",
                        "status": "completed",
                        "false_consensus_preserved": True,
                        "high_stakes_warning_required": False,
                    },
                },
            )()
        ],
    }
    now = datetime.now(UTC)
    stats = collect_statistics(
        events_by_recorder=events_by_recorder,
        window_hours=24.0,
        started_at=now - timedelta(hours=24),
        finished_at=now,
    )
    assert stats.total_runs == 1


# ---------------------------------------------------------------------------
# Audit response parsing
# ---------------------------------------------------------------------------


def test_parse_audit_response_strips_code_fences() -> None:
    """Models sometimes wrap JSON in ``` fences; parsing must tolerate that."""
    raw = (
        "```json\n"
        '{"findings": [{"category": "model_slot", "severity": "high", '
        '"title": "Test", "evidence": "Test", "recommendation": "Test", '
        '"proposed_diff": "", "confidence": 0.9}], '
        '"negative_findings": ["Citation coverage is healthy"]}'
        "\n```"
    )
    response = _parse_audit_response(raw)
    assert len(response.findings) == 1
    assert response.findings[0].category == "model_slot"
    assert response.findings[0].severity == "high"
    assert response.negative_findings == ["Citation coverage is healthy"]


def test_parse_audit_response_handles_trailing_prose() -> None:
    """A short note after the JSON object must not break parsing."""
    raw = (
        '{"findings": [], "negative_findings": []}\n\n'
        "Note: I am not confident in any findings for this window."
    )
    response = _parse_audit_response(raw)
    assert response.findings == []


def test_parse_audit_response_raises_on_invalid_json() -> None:
    with pytest.raises(ValueError):
        _parse_audit_response("not json at all")


# ---------------------------------------------------------------------------
# Prompt + report
# ---------------------------------------------------------------------------


def test_build_audit_user_prompt_includes_current_defaults() -> None:
    now = datetime.now(UTC)
    stats = AuditStatistics(
        window_hours=24.0,
        run_started_at=now - timedelta(hours=24),
        run_finished_at=now,
        provider={},
        synthesis=_synthesis_event_aggregate(),
        cost=_cost_event_aggregate(),
        safety=_safety_event_aggregate(),
        debate=_debate_event_aggregate(),
        total_runs=42,
    )
    prompt = build_audit_user_prompt(
        statistics=stats,
        default_model_ids=(
            "openai/gpt-4o-mini",
            "anthropic/claude-3-haiku",
        ),
        safety_regex_pattern=r"\b(diagnosis|medical)\b",
    )
    assert "openai/gpt-4o-mini" in prompt
    assert "anthropic/claude-3-haiku" in prompt
    assert "diagnosis|medical" in prompt
    assert "42" in prompt  # total_runs


def test_render_report_no_findings_uses_health_indicator() -> None:
    now = datetime.now(UTC)
    stats = AuditStatistics(
        window_hours=24.0,
        run_started_at=now - timedelta(hours=24),
        run_finished_at=now,
        provider={},
        synthesis=_synthesis_event_aggregate(),
        cost=_cost_event_aggregate(),
        safety=_safety_event_aggregate(),
        debate=_debate_event_aggregate(),
        total_runs=10,
    )
    report = render_report(statistics=stats, audit_response=None)
    assert "No findings were generated" in report
    assert "10" in report  # total_runs appears in the statistics appendix


def test_render_report_with_high_severity_marks_action_required() -> None:
    now = datetime.now(UTC)
    stats = AuditStatistics(
        window_hours=24.0,
        run_started_at=now - timedelta(hours=24),
        run_finished_at=now,
        provider={},
        synthesis=_synthesis_event_aggregate(),
        cost=_cost_event_aggregate(),
        safety=_safety_event_aggregate(),
        debate=_debate_event_aggregate(),
        total_runs=5,
    )
    response = type(
        "Response",
        (),
        {
            "findings": [
                Finding(
                    category="model_slot",
                    severity="high",
                    title="Slot 2 has a 40% failure rate",
                    evidence="40% of slot-2 calls failed over 7 days",
                    recommendation="Swap to claude-haiku-4.5",
                    proposed_diff="",
                    confidence=0.85,
                ),
            ],
            "negative_findings": [],
            "used_model": "anthropic/claude-haiku-4.5",
        },
    )()
    report = render_report(statistics=stats, audit_response=response)
    assert "DEGRADED" in report
    assert "Action required" in report
    assert "Slot 2 has a 40% failure rate" in report


# ---------------------------------------------------------------------------
# Helpers (kept here so each test is self-contained)
# ---------------------------------------------------------------------------


def _synthesis_event_aggregate() -> SynthesisStats:

    return SynthesisStats(
        total=0,
        completed=0,
        avg_citation_coverage=0.0,
        avg_duration_ms=0.0,
        high_stakes_required_count=0,
        false_consensus_preserved_count=0,
    )


def _cost_event_aggregate() -> CostStats:

    return CostStats(
        total=0,
        allowed=0,
        required_confirmation=0,
        blocked=0,
        avg_estimated_cost_usd=0.0,
    )


def _safety_event_aggregate() -> SafetyStats:

    return SafetyStats(total=0, impressions=0, acknowledgements=0)


def _debate_event_aggregate() -> DebateStats:

    return DebateStats(
        total=0,
        round_one_count=0,
        round_two_count=0,
        skipped_round_two_count=0,
        avg_round_one_ms=0.0,
        avg_round_two_ms=0.0,
    )


def test_status_md_renders_error_tracking_from_a_current_status_snapshot(
    tmp_path: Path,
) -> None:
    """The documented ``--status-json`` path feeds a REAL /status payload,
    whose error-tracking key is ``error_tracking`` after the #86-closeout
    rename. Cycle-2 review finding: the renderer still read the old
    ``sentry`` key and produced ``| Sentry | None |``."""
    md_path, _ = generate_status_md(
        status={"error_tracking": "active", "uptime_seconds": 5.0},
        output_dir=tmp_path,
    )
    text = md_path.read_text(encoding="utf-8")
    assert "| Error tracking | active |" in text
    assert "| Sentry |" not in text


def test_status_md_falls_back_to_the_legacy_sentry_key(tmp_path: Path) -> None:
    """A snapshot captured BEFORE the rename must still render its value."""
    md_path, _ = generate_status_md(
        status={"sentry": "inactive", "uptime_seconds": 5.0},
        output_dir=tmp_path,
    )
    assert "| Error tracking | inactive |" in md_path.read_text(encoding="utf-8")
