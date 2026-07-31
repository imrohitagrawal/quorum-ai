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
from product_app.model_slots import ModelSlot

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


def _provider_event(
    model_id: str,
    provider_path: str,
    duration_ms: int,
    *,
    event_type: str = "provider_initial_answer_completed",
) -> object:
    return type(
        "Row",
        (),
        {
            "recorder": "provider",
            "event_type": event_type,
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


def test_aggregate_provider_counts_failed_events_mixed_with_completed() -> None:
    """#177: a model failing every live call used to be indistinguishable

    from a healthy one, because ``_aggregate_provider`` read only
    ``model_id``, ``duration_ms`` and ``provider_path`` from the payload and
    never ``event_type`` — the field that actually distinguishes a
    ``provider_initial_answer_failed`` event from a completed one. Since
    #171 a live-call failure keeps ``provider_path=openrouter_search`` (the
    same path a healthy call uses), so path-based counting cannot see it
    either.

    This is the MIXED case on purpose: 2 completed and 3 failed calls for
    the SAME model in the SAME window. A test built only from the two
    uniform extremes (all-healthy or all-failed) would not catch an
    aggregator that conflates the two counters or returns one of them
    unconditionally.

    What turns it red: change ``_aggregate_provider`` back to reading
    ``provider_path`` (or nothing) instead of ``event.event_type`` for
    ``failed_count`` — every failed call keeps
    ``provider_path=openrouter_search``, identical to a healthy one, so the
    count silently reads 0.
    """
    events = [
        _provider_event("openai/gpt-4o-mini", "openrouter_search", 800),
        _provider_event("openai/gpt-4o-mini", "openrouter_search", 900),
        _provider_event(
            "openai/gpt-4o-mini",
            "openrouter_search",
            50,
            event_type="provider_initial_answer_failed",
        ),
        _provider_event(
            "openai/gpt-4o-mini",
            "openrouter_search",
            60,
            event_type="provider_initial_answer_failed",
        ),
        _provider_event(
            "openai/gpt-4o-mini",
            "openrouter_search",
            70,
            event_type="provider_initial_answer_failed",
        ),
    ]
    stats = _aggregate_provider(events)
    slot_stats = stats["openai/gpt-4o-mini"]
    assert slot_stats.total_calls == 5
    assert slot_stats.failed_count == 3


def test_aggregate_provider_all_healthy_events_have_zero_failed_count() -> None:
    """Positive partner to the mixed test above.

    A guard that reports "not real" / "failed" for everything would satisfy
    the mixed test's ``!= 0`` shape by accident if it were written as a
    negative-only check; this drives the all-completed case explicitly, so
    a counter that is wired backwards (counting COMPLETED events instead of
    FAILED ones) reds here instead of passing silently.
    """
    events = [
        _provider_event("openai/gpt-4o-mini", "openrouter_search", 800),
        _provider_event("openai/gpt-4o-mini", "openrouter_search", 900),
        _provider_event("openai/gpt-4o-mini", "openrouter_search", 1000),
    ]
    stats = _aggregate_provider(events)
    slot_stats = stats["openai/gpt-4o-mini"]
    assert slot_stats.total_calls == 3
    assert slot_stats.failed_count == 0
    assert slot_stats.cancelled_count == 0
    assert slot_stats.deadline_exceeded_count == 0


def test_aggregate_provider_counts_cancelled_and_deadline_exceeded_mixed_with_other_events() -> (
    None
):
    """#188: ``cancelled_answer``/``deadline_exceeded_answer`` used to record

    NO event at all, so a cancelled or deadline-cut slot was entirely absent
    from ``_aggregate_provider``'s output — not merely miscounted the way a
    failed live call was before #177.

    MIXED on purpose: 2 completed, 1 failed, 2 cancelled and 1
    deadline-exceeded event for the SAME model in the SAME window, so an
    aggregator that conflates any two of the four counters (e.g. folds
    cancelled into failed, or double-counts an event under two labels)
    cannot pass this by accident the way a uniform-extreme test would allow.

    What turns it red: change ``cancelled_count``/``deadline_exceeded_count``
    back to reading nothing (or ``provider_path``, which is
    ``openrouter_search`` for all four event types here) instead of
    ``event.event_type`` — both counts silently read 0.
    """
    events = [
        _provider_event("openai/gpt-4o-mini", "openrouter_search", 800),
        _provider_event("openai/gpt-4o-mini", "openrouter_search", 900),
        _provider_event(
            "openai/gpt-4o-mini",
            "openrouter_search",
            50,
            event_type="provider_initial_answer_failed",
        ),
        _provider_event(
            "openai/gpt-4o-mini",
            "openrouter_search",
            0,
            event_type="provider_initial_answer_cancelled",
        ),
        _provider_event(
            "openai/gpt-4o-mini",
            "openrouter_search",
            0,
            event_type="provider_initial_answer_cancelled",
        ),
        _provider_event(
            "openai/gpt-4o-mini",
            "openrouter_search",
            0,
            event_type="provider_initial_answer_deadline_exceeded",
        ),
    ]
    stats = _aggregate_provider(events)
    slot_stats = stats["openai/gpt-4o-mini"]
    assert slot_stats.total_calls == 6
    assert slot_stats.failed_count == 1
    assert slot_stats.cancelled_count == 2
    assert slot_stats.deadline_exceeded_count == 1


def test_cancelled_and_deadline_exceeded_events_do_not_dilute_the_duration_average() -> None:
    """#188 review finding: a cancelled or deadline-exceeded slot records a

    ``duration_ms=0`` event by construction (no work was attempted, or the
    elapsed time was never measured) -- NOT a real latency sample. Before
    #188 these slots recorded no event at all, so ``avg_duration_ms`` and
    ``p95_duration_ms`` reflected only real attempts. Naively including the
    new zero-duration events in the same ``durations`` list #188 added
    silently pulls both statistics DOWN, making a model that is frequently
    cancelled or timing out look artificially FAST in the nightly ops-audit
    report an operator reads -- the opposite of what the audit needs to
    surface.

    Mixed with a genuinely failed call (``duration_ms=50``, which DOES carry
    a real measured elapsed time and must stay in the average), so a fix
    that excludes ALL non-completed events would fail this test too.

    What turns it red: include events with
    ``event_type in {"provider_initial_answer_cancelled",
    "provider_initial_answer_deadline_exceeded"}`` in the ``durations`` list
    -- ``avg_duration_ms`` drops from the true 583.33 to 291.67.
    """
    events = [
        _provider_event("openai/gpt-4o-mini", "openrouter_search", 800),
        _provider_event("openai/gpt-4o-mini", "openrouter_search", 900),
        _provider_event(
            "openai/gpt-4o-mini",
            "openrouter_search",
            50,
            event_type="provider_initial_answer_failed",
        ),
        _provider_event(
            "openai/gpt-4o-mini",
            "openrouter_search",
            0,
            event_type="provider_initial_answer_cancelled",
        ),
        _provider_event(
            "openai/gpt-4o-mini",
            "openrouter_search",
            0,
            event_type="provider_initial_answer_cancelled",
        ),
        _provider_event(
            "openai/gpt-4o-mini",
            "openrouter_search",
            0,
            event_type="provider_initial_answer_deadline_exceeded",
        ),
    ]
    stats = _aggregate_provider(events)
    slot_stats = stats["openai/gpt-4o-mini"]
    assert slot_stats.total_calls == 6
    assert slot_stats.avg_duration_ms == pytest.approx(583.33, abs=0.1)
    assert slot_stats.p95_duration_ms == pytest.approx(890.0, abs=0.1)


def test_avg_and_p95_duration_are_none_when_every_event_is_zero_duration() -> None:
    """#189: when EVERY event for a model in the window is cancelled or

    deadline-exceeded, ``durations`` ends up empty. The pre-#189 guard
    reported ``0.0`` for both ``avg_duration_ms`` and ``p95_duration_ms`` --
    indistinguishable from "measured, averaged 0ms" -- making a model that
    is cancelled or times out on every single call look artificially FAST
    in the nightly ops-audit report an operator reads, the same failure
    shape #188's own review fix closed for the mixed case, at the 100%
    extreme instead.

    Mixed between cancelled AND deadline-exceeded (not just one repeated
    event type), so a fix that special-cases only one of the two event
    types cannot pass this by accident.

    What turns it red: revert to ``0.0`` -- both assertions below fail
    with ``0.0 is not None``.
    """
    events = [
        _provider_event(
            "openai/gpt-4o-mini",
            "openrouter_search",
            0,
            event_type="provider_initial_answer_cancelled",
        ),
        _provider_event(
            "openai/gpt-4o-mini",
            "openrouter_search",
            0,
            event_type="provider_initial_answer_cancelled",
        ),
        _provider_event(
            "openai/gpt-4o-mini",
            "openrouter_search",
            0,
            event_type="provider_initial_answer_deadline_exceeded",
        ),
    ]
    stats = _aggregate_provider(events)
    slot_stats = stats["openai/gpt-4o-mini"]
    assert slot_stats.total_calls == 3
    assert slot_stats.cancelled_count == 2
    assert slot_stats.deadline_exceeded_count == 1
    assert slot_stats.avg_duration_ms is None
    assert slot_stats.p95_duration_ms is None


def test_a_model_failing_every_live_call_is_visible_through_the_real_recorder() -> None:
    """#177's own reproduction, end to end through the real store.

    Before this fix: ten calls, every one failing, driven through the real
    ``record_event`` + ``FeedbackStore.iter_events`` path (not the synthetic
    ``_provider_event`` helper) reported ``failed_count`` absent entirely and
    a ``simulation_count`` of 0 — a model failing 100% of its calls was
    statistically indistinguishable from a perfectly healthy one, because
    #171 made every live-call failure keep ``provider_path=openrouter_search``
    (the same path a healthy call uses) and ``_aggregate_provider`` never
    read ``event_type``.

    Mixed with 2 healthy calls for a SECOND model in the same window, so the
    aggregation-by-model-id grouping is exercised too, not just a single
    uniform bucket.
    """
    with configure_for_tests() as store:
        run_id = uuid4()
        for _ in range(10):
            record_event(
                recorder="provider",
                event_type="provider_initial_answer_failed",
                account_id=uuid4(),
                query_run_id=run_id,
                payload={
                    "model_id": "openai/gpt-4o-mini",
                    "provider_path": "openrouter_search",
                    "duration_ms": 30,
                    "fallback_used": False,
                    "source_count": 0,
                },
            )
        for _ in range(2):
            record_event(
                recorder="provider",
                event_type="provider_initial_answer_completed",
                account_id=uuid4(),
                query_run_id=run_id,
                payload={
                    "model_id": "anthropic/claude-3-haiku",
                    "provider_path": "openrouter_search",
                    "duration_ms": 700,
                    "fallback_used": False,
                    "source_count": 2,
                },
            )
        rows = list(store.iter_events())

    stats = _aggregate_provider(rows)
    assert stats["openai/gpt-4o-mini"].failed_count == 10
    assert stats["openai/gpt-4o-mini"].simulation_count == 0
    assert stats["anthropic/claude-3-haiku"].failed_count == 0


def test_cancelled_and_deadline_exceeded_slots_are_visible_through_the_real_recorder() -> None:
    """#188's own reproduction, end to end through the REAL provider service
    and the real store — the issue's own acceptance criterion: "a probe
    driving a cancelled slot and a deadline-exceeded slot through the real
    recorder asserts each produces exactly one event, with the correct
    event_type."

    Before this fix: ``provider_execution_service.cancelled_answer`` and
    ``.deadline_exceeded_answer`` built and returned an ``InitialModelAnswer``
    stub directly with no call to ``provider_event_recorder.record(...)``
    anywhere in either function, so a cancelled or deadline-cut slot
    contributed to NEITHER ``total_calls`` NOR ``failed_count`` — it was
    entirely absent, not merely miscounted.

    Drives the actual production methods (not the synthetic
    ``_provider_event``/``record_event`` helpers), mixed with one healthy
    call for a SECOND model, so both the event-type discrimination and the
    per-model grouping are exercised together.
    """
    from product_app.provider_keys import ProviderCredentialSource
    from product_app.providers import provider_execution_service

    with configure_for_tests() as store:
        run_id = uuid4()
        account_id = uuid4()
        cancelled_slot = ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini", search=True)
        deadline_slot = ModelSlot(slot_number=2, model_id="openai/gpt-4o-mini", search=True)

        provider_execution_service.cancelled_answer(
            model_slot=cancelled_slot,
            account_id=account_id,
            query_run_id=run_id,
            credential_source=ProviderCredentialSource.APP_OWNED,
        )
        provider_execution_service.deadline_exceeded_answer(
            model_slot=deadline_slot,
            account_id=account_id,
            query_run_id=run_id,
            credential_source=ProviderCredentialSource.APP_OWNED,
        )
        record_event(
            recorder="provider",
            event_type="provider_initial_answer_completed",
            account_id=account_id,
            query_run_id=run_id,
            payload={
                "model_id": "anthropic/claude-3-haiku",
                "provider_path": "openrouter_search",
                "duration_ms": 700,
                "fallback_used": False,
                "source_count": 2,
            },
        )
        rows = list(store.iter_events())

    provider_rows = [r for r in rows if r.recorder == "provider"]
    assert len(provider_rows) == 3
    cancelled_rows = [
        r for r in provider_rows if r.event_type == "provider_initial_answer_cancelled"
    ]
    deadline_rows = [
        r for r in provider_rows if r.event_type == "provider_initial_answer_deadline_exceeded"
    ]
    assert len(cancelled_rows) == 1
    assert len(deadline_rows) == 1

    stats = _aggregate_provider(rows)
    assert stats["openai/gpt-4o-mini"].total_calls == 2
    assert stats["openai/gpt-4o-mini"].cancelled_count == 1
    assert stats["openai/gpt-4o-mini"].deadline_exceeded_count == 1
    assert stats["openai/gpt-4o-mini"].failed_count == 0
    assert stats["anthropic/claude-3-haiku"].cancelled_count == 0
    assert stats["anthropic/claude-3-haiku"].deadline_exceeded_count == 0


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
                    "event_type": "provider_initial_answer_completed",
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


def test_provider_fallback_prompt_describes_a_whole_run_signal_not_a_per_model_one() -> None:
    """#176: the ``provider_fallback`` category used to tell the audit LLM to
    look for "a specific model_id" with a high local_simulation rate. Since
    #171 that premise is dead: a per-model live-call failure is reported as
    FAILED (the ``model_slot`` category's domain), and local_simulation only
    ever happens uniformly for a WHOLE run (the flag/key are checked once per
    run, not per model). Sending the auditor a category description built
    on an impossible scenario risks a mis-grounded finding.

    What turns it red: restore the old sentence ("A specific model_id has a
    high local_simulation rate (>30%)") — verified by mutation.
    """
    from product_app.feedback_audit import AUDIT_SYSTEM_PROMPT

    assert "A specific model_id has a high local_simulation" not in AUDIT_SYSTEM_PROMPT
    assert "high share of entire RUNS" in AUDIT_SYSTEM_PROMPT
    assert "WHOLE-RUN signal, not a per-model one" in AUDIT_SYSTEM_PROMPT


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
