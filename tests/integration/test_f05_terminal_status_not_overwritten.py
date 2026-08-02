"""F-05: a cancel must not be silently reverted by the pipeline.

``InMemoryQueryRunRepository.update_status`` assigned ``query_run.status``
with no ``ALLOWED_TRANSITIONS`` check, while ``transition()`` consulted it
under the same lock. Eleven pipeline call sites pass ``status_value`` and
therefore overwrote a terminal status unconditionally.

That is not merely a mislabel. ``_should_stop`` reads ONLY the status field
(there is no separate cancel ``Event``), so clobbering ``CANCELLED`` with
``DEBATE_ROUND_2_RUNNING`` ERASES the cancel signal and every downstream
``_should_stop`` then returns ``False`` — the run keeps making billed
provider calls and ends ``completed`` after the user was told ``cancelled``.

Defects closed here:

1. A cancel landing at or after the pre-debate gate is erased and further
   provider calls are billed (measured here: 6 of a 10-call run, all after
   the DELETE returned 200 ``{"status": "cancelled"}``).
2. ``_execute_query_run_safely``'s ``except BaseException`` backstop
   relabels an ALREADY-TERMINAL run as ``failed`` — including the user's
   ``cancelled`` — through the same unguarded write.
3. The status field is only ONE of the six things ``update_status`` writes.
   A guard scoped to the ``status_value`` branch alone still lets the
   backstop brand a cancelled run with ``failed_steps=['pipeline']`` and a
   "Unhandled pipeline error" stage detail (with no
   ``partial_failure_notice`` to explain it), and still lets the pipeline's
   status-NEUTRAL writes leave a terminal run with a stage spinning
   ``running`` forever. The guard therefore refuses the WHOLE write, with
   ``allow_terminal=True`` as the narrow opt-in for the two callers that
   legitimately annotate a run they themselves just made terminal.

The tests below assert COUNTS, not just outcomes: billed provider calls at
the ``product_app.providers`` HTTP seam (``urlopen``), and the number of
terminal runs the backstop rewrote — plus the run's WHOLE observable state
(status, failed/missing steps, every stage's state and detail,
``updated_at``), because comparing ``.status`` alone is exactly what let
defect 3 through.

Synchronisation is by ``threading.Event`` handshake only — no sleeps — so
the cancel lands at an exactly known point in the pipeline every run. The
atomicity pin adds one more seam: it wraps the repository lock so the
pipeline writer is parked at the lock DOOR until the DELETE has committed,
which is the only construction that deterministically produces the
check-then-act interleaving (a bare ``threading.Barrier`` race does not —
measured, see that test's docstring).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.helpers import isolated_run_semaphore, wait_for_free_permits

from product_app import config, query_runs
from product_app.costs import CostEstimate, CostThresholdAction
from product_app.debate import DebateResult, debate_stub_service
from product_app.main import app
from product_app.model_slots import ModelSlot
from product_app.query_runs import (
    TERMINAL_STATUSES,
    BillableStage,
    InvalidQueryRunTransitionError,
    QueryRun,
    QueryRunStatus,
    StageBillingState,
    StageState,
    _initial_progress,
    query_run_repository,
)
from product_app.safety import WARNING_VERSION, WarningType
from product_app.synthesis import synthesis_stub_service

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]

#: Every handshake wait is bounded so a regression that never reaches the
#: window fails loudly instead of hanging the suite.
HANDSHAKE_TIMEOUT_S = 30.0


# ---------------------------------------------------------------------------
# (1) behavioural: billed provider calls after a cancel, per cancel window
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal stand-in for the ``urlopen`` context manager."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


_LIVE_BODY = json.dumps(
    {
        "choices": [{"message": {"content": "live provider answer text"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }
).encode()


@dataclass
class _Rendezvous:
    """Deterministic two-way handshake between the worker and the test.

    The worker thread calls :meth:`arrive` at the chosen point in the
    pipeline; it blocks there until the test thread has issued the DELETE
    and calls :meth:`release`. No sleeps, no polling on wall-clock time.
    """

    reached: threading.Event = field(default_factory=threading.Event)
    released: threading.Event = field(default_factory=threading.Event)
    calls_at_cancel: int | None = None

    def arrive(self, call_count: int) -> None:
        self.calls_at_cancel = call_count
        self.reached.set()
        if not self.released.wait(timeout=HANDSHAKE_TIMEOUT_S):  # pragma: no cover
            raise AssertionError("test thread never released the cancel window")

    def release(self) -> None:
        self.released.set()


class _CallCounter:
    """Counts calls at the ``product_app.providers`` HTTP seam."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.total = 0

    def bump(self) -> int:
        with self._lock:
            self.total += 1
            return self.total

    @property
    def count(self) -> int:
        with self._lock:
            return self.total


def _acknowledged_request(query_text: str) -> dict[str, object]:
    return {
        "query_text": query_text,
        "model_slots": DEFAULT_MODEL_IDS,
        "safety_acknowledgements": [
            {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
            {"warning_type": WarningType.HIGH_STAKES, "version": WARNING_VERSION},
        ],
    }


@pytest.fixture
def _live_provider_seam(monkeypatch: pytest.MonkeyPatch) -> _CallCounter:
    """Enable live execution with the HTTP seam faked and counted."""
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True)
    monkeypatch.setattr(config.settings, "openrouter_api_key", "sk-or-test-f05")
    monkeypatch.setattr(config.settings, "stage_delay_ms", 0)
    counter = _CallCounter()
    return counter


def _run_pipeline_with_cancel_at(
    monkeypatch: pytest.MonkeyPatch,
    counter: _CallCounter,
    window: str,
) -> tuple[int, int, QueryRun]:
    """Drive one full run over the real HTTP path, cancelling at ``window``.

    Returns ``(calls_at_cancel, total_calls, final_run)`` — the whole run, not
    just its status, because the label is only one of the fields the pipeline
    can still corrupt after the cancel (see the stage-integrity test below).

    ``window`` is one of:

    * ``"pre_debate"`` — the cancel lands just after the pre-debate
      ``_should_stop`` gate (at ``run_debate_rounds`` entry).
    * ``"mid_debate_round_1"`` — the cancel lands while round 1's provider
      call is in flight.
    * ``"pre_synthesis"`` — the cancel lands just after the pre-synthesis
      ``_should_stop`` gate (at ``produce_final_synthesis`` entry).
    """
    rendezvous = _Rendezvous()
    debate_active = threading.Event()
    triggered = threading.Event()

    def fake_urlopen(request: Any, timeout: float = 0) -> _FakeResponse:
        started = counter.bump()
        if window == "mid_debate_round_1" and debate_active.is_set() and not triggered.is_set():
            triggered.set()
            # The cancel lands while THIS call is still in flight.
            rendezvous.arrive(started)
        return _FakeResponse(_LIVE_BODY)

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)

    real_debate = debate_stub_service.run_debate_rounds
    real_synthesis = synthesis_stub_service.produce_final_synthesis

    def wrapped_debate(**kwargs: Any) -> Any:
        if window == "pre_debate" and not triggered.is_set():
            triggered.set()
            rendezvous.arrive(counter.count)
        debate_active.set()
        try:
            return real_debate(**kwargs)
        finally:
            debate_active.clear()

    def wrapped_synthesis(**kwargs: Any) -> Any:
        if window == "pre_synthesis" and not triggered.is_set():
            triggered.set()
            rendezvous.arrive(counter.count)
        return real_synthesis(**kwargs)

    monkeypatch.setattr(debate_stub_service, "run_debate_rounds", wrapped_debate)
    monkeypatch.setattr(synthesis_stub_service, "produce_final_synthesis", wrapped_synthesis)

    with isolated_run_semaphore(1) as semaphore:
        client = TestClient(app)
        # Cookie session path (no X-Account-Id): the pipeline runs on a
        # background thread, which is the production shape and the only
        # one where a concurrent DELETE is possible at all.
        csrf = client.get("/v1/session").json()["csrf_token"]
        created = client.post(
            "/v1/query-runs",
            json=_acknowledged_request("compare managed database options"),
            headers={"x-csrf-token": csrf},
        )
        assert created.status_code == 202, created.text
        query_run_id = UUID(created.json()["query_run_id"])

        assert rendezvous.reached.wait(timeout=HANDSHAKE_TIMEOUT_S), (
            f"pipeline never reached the {window!r} cancel window"
        )
        deleted = client.delete(
            f"/v1/query-runs/{query_run_id}",
            headers={"x-csrf-token": csrf},
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["status"] == "cancelled"
        rendezvous.release()

        # The worker returns its permit in a ``finally`` after the run
        # reaches a terminal state, so a restored permit is the join point.
        assert wait_for_free_permits(semaphore, 1, timeout_s=HANDSHAKE_TIMEOUT_S) == 1

    final_run = query_run_repository.get(query_run_id)
    assert rendezvous.calls_at_cancel is not None
    return rendezvous.calls_at_cancel, counter.count, final_run


# Billed provider calls AFTER the user was told "cancelled", MEASURED at the
# ``product_app.providers.urlopen`` seam on this fixture (4 initial answers +
# 2 debate rounds + 4 live synthesis sections; the fifth synthesis section
# falls back to templated because the faked provider body carries no sources,
# so a full run is 10 calls, not 11):
#
#   window               Layer 1 only   Layer 1 + 2   exact?
#   pre_debate                     2             0   yes — both rounds gated
#   mid_debate_round_1             1             0   yes — round 2 gated
#   pre_synthesis                  4             0   yes — all 5 sections gated
#
# Layer 1 (#98) stops the run at the NEXT ``_should_stop`` gate after the
# cancel. It cannot cut a stage service that has already been entered. Layer 2
# (#106) closes that gap: ``should_stop`` is threaded into the single
# provider-call seam each stage uses (``debate._call_debate_model`` /
# ``synthesis._call_synthesis_model``), so a call not yet dispatched when the
# cancel commits is never dispatched at all — see FOLLOWUP-F05-LAYER2.md.
@pytest.mark.parametrize(
    ("window", "max_calls_after_cancel", "exact_calls_after_cancel"),
    [
        ("pre_debate", 0, 0),
        ("mid_debate_round_1", 0, 0),
        ("pre_synthesis", 0, 0),
    ],
)
def test_cancel_is_not_reverted_and_bounds_billed_calls(
    monkeypatch: pytest.MonkeyPatch,
    _live_provider_seam: _CallCounter,
    window: str,
    max_calls_after_cancel: int,
    exact_calls_after_cancel: int | None,
) -> None:
    """A cancel must survive the pipeline and cap the calls it still bills."""
    calls_at_cancel, total_calls, final_run = _run_pipeline_with_cancel_at(
        monkeypatch, _live_provider_seam, window
    )
    final_status = final_run.status.value
    calls_after_cancel = total_calls - calls_at_cancel

    # Non-vacuity: the run must genuinely have reached the provider seam,
    # otherwise a low "calls after the cancel" would be trivially true.
    assert calls_at_cancel > 0, "the cancel window was reached before any provider call"

    assert calls_after_cancel <= max_calls_after_cancel, (
        f"{window}: {calls_after_cancel} provider calls billed after the cancel "
        f"(cap {max_calls_after_cancel}); at cancel={calls_at_cancel}, total={total_calls}"
    )
    if exact_calls_after_cancel is not None:
        assert calls_after_cancel == exact_calls_after_cancel, (
            f"{window}: expected exactly {exact_calls_after_cancel} billed calls after "
            f"the cancel, got {calls_after_cancel} "
            f"(at cancel={calls_at_cancel}, total={total_calls})"
        )
    assert final_status == "cancelled", (
        f"{window}: the run ended {final_status!r} after the user was told 'cancelled'"
    )


@pytest.mark.parametrize("window", ["pre_debate", "pre_synthesis"])
def test_a_cancel_with_nothing_billed_skips_the_record_call_entirely(
    monkeypatch: pytest.MonkeyPatch,
    _live_provider_seam: _CallCounter,
    window: str,
) -> None:
    """Layer 2's second half: when nothing was billed, record_* must not land.

    ``record_debate_outputs`` / ``record_final_synthesis`` are NOT guarded by
    the F-05 terminal-write refusal (deliberately — see
    FOLLOWUP-F05-LAYER2.md, "guarding record_* masks a symptom whose cause is
    that the stage service was already entered"). So the fix has to stop the
    ORCHESTRATOR from calling them at all once it knows nothing new was
    billed, rather than making the repository swallow the write. Proven here
    by the field the record call would have populated staying at its
    pre-run default (``[]`` / ``None``), not by inspecting ``updated_at``
    (timing-based and not deterministic under a fast fallback path).
    """
    _, _, run = _run_pipeline_with_cancel_at(monkeypatch, _live_provider_seam, window)

    if window == "pre_debate":
        assert run.debate_outputs == [], (
            "record_debate_outputs landed on a cancelled run with nothing billed"
        )
        assert run.billing_stages[BillableStage.DEBATE] is StageBillingState.ENTERED, (
            "the debate billing stage was marked RECORDED despite the skipped record call"
        )
    else:
        assert run.final_synthesis is None, (
            "record_final_synthesis landed on a cancelled run with nothing billed"
        )
        assert run.billing_stages[BillableStage.SYNTHESIS] is StageBillingState.ENTERED, (
            "the synthesis billing stage was marked RECORDED despite the skipped record call"
        )


def test_a_mid_flight_billed_debate_round_is_still_recorded_after_cancel(
    monkeypatch: pytest.MonkeyPatch,
    _live_provider_seam: _CallCounter,
) -> None:
    """The one window where record_debate_outputs legitimately still lands.

    Round 1's provider call is already in flight when the cancel commits
    (``mid_debate_round_1``): it cannot be un-billed, so its usage MUST be
    recorded or a real charge would silently vanish from the receipt — the
    exact defect the F-06 contract exists to prevent. This is the
    counter-case to the skip above: proves the skip is conditioned on
    "nothing new was billed", not on "the run is cancelled".
    """
    _, _, run = _run_pipeline_with_cancel_at(monkeypatch, _live_provider_seam, "mid_debate_round_1")

    assert len(run.debate_outputs) == 2, (
        "round 1's billed output must still be recorded, not dropped with round 2's skip"
    )
    assert run.debate_outputs[0].debate_mode == "live", "round 1 was genuinely billed and live"
    assert run.debate_outputs[1].debate_mode == "fallback", (
        "round 2 must have been stopped before it could bill, and fall back to the template"
    )
    assert run.debate_call_usages != [], "round 1's billed usage must not be lost"
    assert len(run.debate_call_usages) == 1, (
        f"expected exactly round 1's usage entry, got {len(run.debate_call_usages)}"
    )
    assert run.billing_stages[BillableStage.DEBATE] is StageBillingState.RECORDED, (
        "a genuinely billed stage must reach RECORDED, not stay ENTERED"
    )


def test_a_cancelled_run_is_never_left_with_a_stage_still_running(
    monkeypatch: pytest.MonkeyPatch,
    _live_provider_seam: _CallCounter,
) -> None:
    """A terminal run must not carry an in-progress stage, forever.

    The status label alone is not the run's state. After the cancel lands at
    the pre-debate gate the pipeline is already past ``_should_stop`` and goes
    on to finish ``run_debate_rounds``; it then issues two more writes:

    1. ``status_value=DEBATE_ROUND_2_RUNNING`` + ``debate_round_1``
       ``COMPLETED`` / "Debate round 1 completed." — a guard scoped to the
       ``status_value`` branch refuses the label but lets the stage annotation
       land, ERASING the "Cancelled by the user." evidence the DELETE wrote.
    2. ``stage_name="debate_round_2", stage_state=RUNNING`` — status-NEUTRAL,
       so a ``status_value``-only guard never even looks at it.

    The next ``_should_stop`` then returns and the run is terminal FOREVER
    with ``debate_round_2`` in state ``running``; the UI renders a spinner on
    a cancelled run. Unreachable before the F-05 branch, so it is a
    regression the branch itself introduced.
    """
    _, _, run = _run_pipeline_with_cancel_at(monkeypatch, _live_provider_seam, "pre_debate")

    assert run.status is QueryRunStatus.CANCELLED
    still_running = [stage.stage for stage in run.progress if stage.state is StageState.RUNNING]
    assert still_running == [], (
        f"a terminal (cancelled) run was left with {still_running} still 'running'"
    )
    by_stage = {stage.stage: stage for stage in run.progress}
    assert by_stage["debate_round_1"].state is StageState.SKIPPED, (
        "the cancel's SKIPPED stamp on the in-flight stage was overwritten by the pipeline"
    )
    assert by_stage["debate_round_1"].detail == "Cancelled by the user.", (
        f"the cancel evidence was erased; the stage now reads {by_stage['debate_round_1'].detail!r}"
    )
    assert by_stage["debate_round_2"].state is StageState.PENDING, (
        "a stage the cancelled run never legitimately entered was annotated anyway"
    )
    assert query_runs._running_stage_name(run.progress) == "estimate", (  # noqa: SLF001
        "the served current_stage points at a stage that was never really running"
    )


# ---------------------------------------------------------------------------
# (2) the ``except BaseException`` backstop must not relabel a terminal run
# ---------------------------------------------------------------------------


TERMINAL_STATUSES_UNDER_TEST = sorted(TERMINAL_STATUSES, key=lambda status: status.value)


def test_terminal_statuses_under_test_covers_every_production_terminal_status() -> None:
    """Guard against re-hardcoding the coverage list (#161).

    ``TERMINAL_STATUSES_UNDER_TEST`` used to be a retyped literal list that
    silently omitted ``BLOCKED_BY_COST`` — the one terminal status this
    file's own backstop test exists to guard never got exercised. Deriving
    the list from the production ``TERMINAL_STATUSES`` set means a future
    terminal status is automatically covered; this test exists so that if
    someone re-hardcodes the list, it goes red instead of silently
    dropping coverage again. Non-vacuity: also asserts the set is not
    empty, so a derivation bug collapsing to nothing can't pass by having
    nothing to compare.
    """
    assert TERMINAL_STATUSES_UNDER_TEST, "the derived coverage list must not be empty"
    assert set(TERMINAL_STATUSES_UNDER_TEST) == TERMINAL_STATUSES, (
        "TERMINAL_STATUSES_UNDER_TEST has drifted from the production TERMINAL_STATUSES set"
    )


def _seed_run(
    *,
    status: QueryRunStatus,
    running_stage: str = "synthesis",
    account_id: UUID | None = None,
) -> QueryRun:
    """Park a run directly in the repository in a chosen state."""
    now = datetime.now(UTC)
    progress = _initial_progress()
    for stage in progress:
        if stage.stage == running_stage:
            stage.state = StageState.RUNNING
    run = QueryRun(
        query_run_id=uuid4(),
        account_id=account_id or uuid4(),
        query_text="F-05 backstop test",
        status=status,
        correlation_id=f"f05_{uuid4().hex[:8]}",
        created_at=now,
        updated_at=now,
        started_at=now,
        model_slots=[
            ModelSlot(slot_number=i + 1, model_id=mid) for i, mid in enumerate(DEFAULT_MODEL_IDS)
        ],
        cost_estimate=CostEstimate(
            estimated_cost_usd=Decimal("0.05"),
            currency="USD",
            threshold_action=CostThresholdAction.ALLOW,
            confirmation_token="f05-test-token",
            reasons=[],
        ),
        progress=progress,
    )
    query_run_repository._query_runs[run.query_run_id] = run  # noqa: SLF001
    return run


def _observable_state(run: QueryRun) -> dict[str, Any]:
    """Everything a write to a terminal run could corrupt, not just the label.

    The status field is one of SIX things ``update_status`` assigns. A test
    that compares only ``.status`` passes over a run whose ``failed_steps``
    now read ``['pipeline']`` and whose stage detail reads "Unhandled
    pipeline error" — which is exactly how the first cut of this fix shipped
    a right label with a defamatory annotation.
    """
    return {
        "status": run.status,
        "failed_steps": list(run.failed_steps),
        "missing_steps": list(run.missing_steps),
        "updated_at": run.updated_at,
        "progress": [(stage.stage, stage.state, stage.detail) for stage in run.progress],
    }


def test_backstop_never_relabels_an_already_terminal_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_execute_query_run_safely`` must not rewrite a terminal run AT ALL.

    Counts rewrites over EVERY terminal status rather than spot-checking
    ``cancelled``, and compares the whole observable state
    (:func:`_observable_state`) rather than the status field alone: the
    backstop's write also carries ``failed_steps=['pipeline']``, the PENDING
    stages as ``missing_steps``, and a FAILED stage annotation, none of which
    belong on a run the user already saw finish.

    Paired with a non-vacuity counter-assertion: the backstop must still
    drive a NON-terminal run to ``failed`` ("never stuck" is the contract it
    exists for), and the injected failure must actually have fired.
    """
    boom_calls = 0

    def boom(*, query_run_id: UUID, account_id: UUID) -> None:
        nonlocal boom_calls
        boom_calls += 1
        raise RuntimeError("injected unhandled pipeline error")

    monkeypatch.setattr(query_runs, "_execute_query_run", boom)

    rewrites = 0
    corruptions: list[str] = []
    for status in TERMINAL_STATUSES_UNDER_TEST:
        run = _seed_run(status=status)
        before = _observable_state(run)
        query_runs._execute_query_run_safely(  # noqa: SLF001
            query_run_id=run.query_run_id,
            account_id=run.account_id,
        )
        after = _observable_state(query_run_repository.get(run.query_run_id))
        if after["status"] is not status:
            rewrites += 1
        for field_name, was in before.items():
            if after[field_name] != was:
                corruptions.append(f"{status.value}.{field_name}: {was!r} -> {after[field_name]!r}")

    # Non-vacuity: the backstop still guarantees "never stuck" for a
    # non-terminal run, so the guard cannot have been implemented by
    # disabling the backstop outright.
    non_terminal = _seed_run(status=QueryRunStatus.SYNTHESIS_RUNNING)
    query_runs._execute_query_run_safely(  # noqa: SLF001
        query_run_id=non_terminal.query_run_id,
        account_id=non_terminal.account_id,
    )
    rescued = query_run_repository.get(non_terminal.query_run_id)

    assert boom_calls == len(TERMINAL_STATUSES_UNDER_TEST) + 1, (
        "the injected pipeline failure did not fire for every seeded run"
    )
    assert rescued.status is QueryRunStatus.FAILED, (
        "the backstop must still drive a NON-terminal run to a terminal state"
    )
    assert rewrites == 0, (
        f"{rewrites} of {len(TERMINAL_STATUSES_UNDER_TEST)} terminal runs were "
        "relabelled by the except-BaseException backstop"
    )
    assert corruptions == [], "the backstop mutated an already-terminal run:\n  " + "\n  ".join(
        corruptions
    )


def test_the_backstop_leaves_a_user_cancelled_run_entirely_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The realistic shape: a real DELETE, then the backstop fires.

    Built through the cancel ENDPOINT rather than a hand-seeded status, so
    the run has the shape a cancel actually leaves: no stage is RUNNING any
    more (the in-flight one was stamped SKIPPED). ``_running_stage_name``
    therefore falls back to ``"estimate"`` — the one stage that definitively
    SUCCEEDED — and the backstop's write brands it
    ``failed`` / "Unhandled pipeline error: RuntimeError." while attaching
    ``failed_steps=['pipeline']`` and every PENDING stage as a missing step.

    ``partial_failure_notice`` is emitted only for PARTIAL/FAILED/TIMED_OUT,
    so on a CANCELLED run the UI renders those failed steps with NO
    explanatory sentence at all: a right label with an unexplained,
    defamatory annotation.
    """
    account_id = uuid4()
    run = _seed_run(
        status=QueryRunStatus.DEBATE_ROUND_1_RUNNING,
        running_stage="debate_round_1",
        account_id=account_id,
    )
    client = TestClient(app)
    deleted = client.delete(
        f"/v1/query-runs/{run.query_run_id}",
        headers={"X-Account-Id": str(account_id)},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["status"] == "cancelled"

    cancelled = query_run_repository.get(run.query_run_id)
    before = _observable_state(cancelled)
    # Precondition for the 'estimate' fallback: a cancel leaves NOTHING running.
    assert all(stage.state is not StageState.RUNNING for stage in cancelled.progress)

    def boom(*, query_run_id: UUID, account_id: UUID) -> None:
        raise RuntimeError("injected unhandled pipeline error")

    monkeypatch.setattr(query_runs, "_execute_query_run", boom)
    query_runs._execute_query_run_safely(  # noqa: SLF001
        query_run_id=run.query_run_id,
        account_id=account_id,
    )

    after_run = query_run_repository.get(run.query_run_id)
    assert after_run.failed_steps == [], (
        f"the cancelled run was branded with failed_steps={after_run.failed_steps!r} "
        "and no partial_failure_notice is emitted for a cancelled run to explain it"
    )
    assert after_run.missing_steps == [], (
        f"the cancelled run was branded with missing_steps={after_run.missing_steps!r}"
    )
    estimate_stage = next(s for s in after_run.progress if s.stage == "estimate")
    assert estimate_stage.state is not StageState.FAILED, (
        f"the ONE stage that definitively succeeded was marked failed: {estimate_stage.detail!r}"
    )
    assert _observable_state(after_run) == before, (
        "a write to an already-terminal run must be a FULL no-op, not a status-only one"
    )


# ---------------------------------------------------------------------------
# (3) the guard's boundary: what a terminal run still accepts, and how it
#     refuses everything else
# ---------------------------------------------------------------------------


def test_an_explicitly_opted_in_write_still_annotates_a_terminal_run() -> None:
    """The two sanctioned post-terminal annotators must keep working.

    ``cancel_query_run`` marks the in-flight stage ``SKIPPED`` immediately
    AFTER transitioning to ``CANCELLED``, and ``_degrade_run_for_deadline``
    annotates after its own flip. Both are the party that MADE the run
    terminal, so both say so with ``allow_terminal=True``. A guard with no
    opt-in silently breaks cancel's stage stamp.
    """
    run = _seed_run(status=QueryRunStatus.CANCELLED, running_stage="synthesis")
    before = run.updated_at

    updated = query_run_repository.update_status(
        run.query_run_id,
        stage_name="synthesis",
        stage_state=StageState.SKIPPED,
        detail="Cancelled by the user.",
        failed_steps=["synthesis"],
        missing_steps=["synthesis"],
        allow_terminal=True,
    )

    assert updated.status is QueryRunStatus.CANCELLED
    stage = next(s for s in updated.progress if s.stage == "synthesis")
    assert stage.state is StageState.SKIPPED
    assert stage.detail == "Cancelled by the user."
    assert updated.failed_steps == ["synthesis"]
    assert updated.missing_steps == ["synthesis"]
    assert updated.updated_at >= before


def test_a_status_neutral_write_to_a_terminal_run_is_refused_by_default() -> None:
    """The unit-level statement of finding 2.

    ``update_status(stage_name="debate_round_2", stage_state=RUNNING)`` from
    the pipeline carries no ``status_value`` at all, so a guard scoped to the
    ``status_value`` branch never sees it — and it leaves a terminal run with
    a stage stuck ``running`` forever, plus a bumped ``updated_at`` that
    inflates the receipt's ``elapsed_time_ms`` past the cancel.
    """
    run = _seed_run(status=QueryRunStatus.CANCELLED, running_stage="debate_round_1")
    run.progress[0].detail = "Cost estimated."
    before = _observable_state(run)

    returned = query_run_repository.update_status(
        run.query_run_id,
        stage_name="debate_round_2",
        stage_state=StageState.RUNNING,
        detail="Running debate round 2.",
    )

    assert _observable_state(returned) == before, (
        "a non-opted-in write mutated an already-terminal run"
    )
    assert returned.updated_at == before["updated_at"], (
        "a refused write still bumped updated_at, inflating the served elapsed_time_ms"
    )


def test_status_write_to_a_non_terminal_run_still_applies() -> None:
    """The guard must only refuse writes to an ALREADY-TERMINAL run.

    Counter-assertion to the guard: ordinary forward pipeline progress
    (11 call sites) must be unaffected, and a non-terminal run must still
    be drivable all the way to a terminal state.
    """
    run = _seed_run(status=QueryRunStatus.DEBATE_ROUND_1_RUNNING, running_stage="debate_round_1")

    running = query_run_repository.update_status(
        run.query_run_id,
        status_value=QueryRunStatus.DEBATE_ROUND_2_RUNNING,
        stage_name="debate_round_1",
        stage_state=StageState.COMPLETED,
        detail="Debate round 1 completed.",
    )
    assert running.status is QueryRunStatus.DEBATE_ROUND_2_RUNNING

    terminal = query_run_repository.update_status(
        run.query_run_id,
        status_value=QueryRunStatus.COMPLETED,
        stage_name="synthesis",
        stage_state=StageState.COMPLETED,
        detail="Synthesis completed.",
    )
    assert terminal.status is QueryRunStatus.COMPLETED


# ---------------------------------------------------------------------------
# (4) the refusal is a NO-OP, not an exception
# ---------------------------------------------------------------------------


def test_a_refused_status_write_returns_normally_instead_of_raising() -> None:
    """The eleven pipeline call sites have no handler; a raise aborts the run.

    Nothing else pins this: swapping the refusal for
    ``raise InvalidQueryRunTransitionError(...)`` leaves every behavioural
    test above green, because the raise is swallowed — by
    ``_execute_query_run_safely``'s ``except BaseException`` on the worker
    path, and by ``contextlib.suppress`` inside it on the backstop path — so
    the run still ends ``cancelled`` and the call counts still hold. It would
    nonetheless skip the pipeline's own cleanup and turn every refused
    forward-progress write into a stack unwind.
    """
    run = _seed_run(status=QueryRunStatus.DEBATE_ROUND_1_RUNNING, running_stage="debate_round_1")
    query_run_repository.transition(run.query_run_id, QueryRunStatus.CANCELLED)

    returned = query_run_repository.update_status(
        run.query_run_id,
        status_value=QueryRunStatus.COMPLETED,
    )

    assert returned.status is QueryRunStatus.CANCELLED
    assert query_run_repository.get(run.query_run_id).status is QueryRunStatus.CANCELLED


# ---------------------------------------------------------------------------
# (5) the guard is ATOMIC: it decides under the same lock that writes
# ---------------------------------------------------------------------------


#: Enough iterations to hit the interleaving reliably while staying well
#: under a second; measured hit rate for the stale-pre-lock-read mutant is
#: recorded in the commit message.
RACE_ITERATIONS = 400

#: Per-thread join budget. A deadlocked or wedged implementation must make
#: this test FAIL, never hang the suite.
RACE_JOIN_TIMEOUT_S = 10.0


def test_a_committed_cancel_survives_a_concurrent_pipeline_status_write() -> None:
    """Contention smoke test: two real threads, no rendezvous, no reverts.

    Only one outcome is a defect: ``transition`` SUCCEEDED — the user was
    told "cancelled" — and ``update_status`` then overwrote it. The pipeline
    write winning outright is fine: then the cancel was rejected and the user
    was never told anything.

    HONEST LIMIT, measured, not assumed: a bare ``Barrier`` does NOT schedule
    the interleaving that a check-then-act guard needs. On CPython 3.14 /
    darwin the thread that TRIPS the barrier keeps running while the waiter
    has to be rescheduled, so the pipeline write consistently lands first —
    against the ``_refuse`` mutant (terminal check hoisted to a stale
    pre-lock read) this loop measured 0 reverted out of 5000 iterations with
    5000 committed cancels. It is kept because it exercises genuine lock
    contention cheaply, but the test that actually BITES that mutation is
    :func:`test_the_terminal_check_is_made_under_the_writing_lock` below,
    which opens the window deterministically.
    """
    reverted: list[str] = []
    committed_cancels = 0

    for _ in range(RACE_ITERATIONS):
        run = _seed_run(
            status=QueryRunStatus.DEBATE_ROUND_1_RUNNING, running_stage="debate_round_1"
        )
        query_run_id = run.query_run_id
        start = threading.Barrier(2)
        cancel_committed: list[bool] = []

        def cancel(
            run_id: UUID = query_run_id,
            committed: list[bool] = cancel_committed,
            gate: threading.Barrier = start,
        ) -> None:
            gate.wait(timeout=RACE_JOIN_TIMEOUT_S)
            try:
                query_run_repository.transition(run_id, QueryRunStatus.CANCELLED)
            except InvalidQueryRunTransitionError:
                committed.append(False)
            else:
                committed.append(True)

        def pipeline(run_id: UUID = query_run_id, gate: threading.Barrier = start) -> None:
            gate.wait(timeout=RACE_JOIN_TIMEOUT_S)
            query_run_repository.update_status(
                run_id, status_value=QueryRunStatus.DEBATE_ROUND_2_RUNNING
            )

        threads = [threading.Thread(target=cancel), threading.Thread(target=pipeline)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=RACE_JOIN_TIMEOUT_S)
            assert not thread.is_alive(), "a racing writer never finished — the guard deadlocks"

        final = query_run_repository.get(query_run_id).status
        if cancel_committed and cancel_committed[0]:
            committed_cancels += 1
            if final is not QueryRunStatus.CANCELLED:
                reverted.append(final.value)

    # Non-vacuity: the race must actually have produced committed cancels,
    # otherwise "no cancel was reverted" is trivially true.
    assert committed_cancels > 0, "no cancel ever committed — the race never happened"
    assert reverted == [], (
        f"{len(reverted)} of {committed_cancels} committed cancels were reverted "
        f"by a concurrent pipeline write (final statuses: {sorted(set(reverted))})"
    )


# ---------------------------------------------------------------------------
# (6) the follow-on stage stamps are gated on OUR terminal write landing
# ---------------------------------------------------------------------------


def test_a_cancel_that_wins_also_suppresses_the_skipped_stage_stamps(
    monkeypatch: pytest.MonkeyPatch,
    _live_provider_seam: _CallCounter,
) -> None:
    """``_mark_remaining_stages`` opts in — so its callers must not.

    Every ``_mark_remaining_stages`` call site runs on a run this pipeline
    has just driven terminal, so the helper passes ``allow_terminal=True``.
    That is only sound while each caller first confirms its own terminal
    write LANDED. Here it did not: the cancel got there first, so the
    ``PARTIAL`` write is refused — and stamping "Not executed because an
    earlier stage failed or timed out" onto the cancelled run would be both
    untrue and unexplained (a cancelled run gets no
    ``partial_failure_notice`` to account for it).

    Drives the real pipeline: the cancel lands at the pre-debate gate and
    debate then returns no outputs, which is the branch that terminates with
    ``PARTIAL`` + ``_mark_remaining_stages(["debate_round_2", "synthesis"])``.
    """

    def _no_debate_outputs(**kwargs: Any) -> DebateResult:
        return DebateResult(
            debate_outputs=[],
            failed_steps=["debate_round_1", "debate_round_2", "synthesis"],
            missing_steps=["debate_round_2", "synthesis"],
            timed_out=False,
            round_timings_ms={},
        )

    monkeypatch.setattr(debate_stub_service, "run_debate_rounds", _no_debate_outputs)

    _, _, run = _run_pipeline_with_cancel_at(monkeypatch, _live_provider_seam, "pre_debate")

    assert run.status is QueryRunStatus.CANCELLED
    by_stage = {stage.stage: stage for stage in run.progress}
    assert by_stage["debate_round_1"].detail == "Cancelled by the user."
    for stage_name in ("debate_round_2", "synthesis"):
        assert by_stage[stage_name].state is StageState.PENDING, (
            f"{stage_name} was stamped {by_stage[stage_name].state.value!r} / "
            f"{by_stage[stage_name].detail!r} on a run that was CANCELLED, not failed"
        )
    assert run.failed_steps == [], f"cancelled run branded failed_steps={run.failed_steps!r}"
    assert run.missing_steps == [], f"cancelled run branded missing_steps={run.missing_steps!r}"


#: Name of the thread whose lock acquisition the door below delays.
_DELAYED_WRITER = "f05-pipeline-writer"


class _CancelFirstLock:
    """The repository lock, with a door the pipeline writer must knock at.

    Wraps the real ``RLock``. The FIRST acquisition made by the thread named
    :data:`_DELAYED_WRITER` announces itself and then waits until the cancel
    has committed, before taking the real lock. Every other thread passes
    straight through, so the cancel itself is never delayed.

    This turns the check-then-act window into a deterministic one: anything
    ``update_status`` decided BEFORE this door is provably stale by the time
    it writes. No sleeps and no polling — two ``Event`` handshakes.
    """

    def __init__(self, real: Any, at_door: threading.Event, cancel_done: threading.Event) -> None:
        self._real = real
        self._at_door = at_door
        self._cancel_done = cancel_done
        self._gated = False

    def __enter__(self) -> Any:
        if not self._gated and threading.current_thread().name == _DELAYED_WRITER:
            self._gated = True
            self._at_door.set()
            if not self._cancel_done.wait(timeout=HANDSHAKE_TIMEOUT_S):  # pragma: no cover
                raise AssertionError("the cancel never committed")
        return self._real.__enter__()

    def __exit__(self, *exc_info: Any) -> Any:
        return self._real.__exit__(*exc_info)


def test_the_terminal_check_is_made_under_the_writing_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Atomicity, pinned: read-and-decide must share the write's lock hold.

    Hoisting the terminal check above ``with self._lock`` — a stale pre-lock
    read — survives every rendezvous-synchronised test in this file AND the
    barrier stress loop above, yet silently reverts a cancel that lands in
    the window. Here the pipeline writer is held at the lock door until the
    DELETE has committed, so a decision taken before the door is guaranteed
    stale and the guard must be re-deciding inside the lock to get this
    right.
    """
    run = _seed_run(status=QueryRunStatus.DEBATE_ROUND_1_RUNNING, running_stage="debate_round_1")
    at_door = threading.Event()
    cancel_done = threading.Event()
    monkeypatch.setattr(
        query_run_repository,
        "_lock",
        _CancelFirstLock(query_run_repository._lock, at_door, cancel_done),  # noqa: SLF001
    )

    def pipeline_write() -> None:
        query_run_repository.update_status(
            run.query_run_id, status_value=QueryRunStatus.DEBATE_ROUND_2_RUNNING
        )

    writer = threading.Thread(target=pipeline_write, name=_DELAYED_WRITER)
    writer.start()
    assert at_door.wait(timeout=HANDSHAKE_TIMEOUT_S), "the pipeline writer never reached the lock"

    # The DELETE lands while the pipeline writer is parked at the door.
    cancelled = query_run_repository.transition(run.query_run_id, QueryRunStatus.CANCELLED)
    assert cancelled.status is QueryRunStatus.CANCELLED
    cancel_done.set()

    writer.join(timeout=HANDSHAKE_TIMEOUT_S)
    assert not writer.is_alive(), "the pipeline writer never finished — the guard deadlocks"

    assert query_run_repository.get(run.query_run_id).status is QueryRunStatus.CANCELLED, (
        "a cancel that committed while the pipeline writer waited for the lock was "
        "reverted — the terminal check was made on a read taken before the lock"
    )


def _run_inline(client: TestClient, account_id: UUID) -> dict[str, Any]:
    """POST a run over the legacy inline path and return the result body."""
    created = client.post(
        "/v1/query-runs",
        json=_acknowledged_request("compare managed database options"),
        headers={"X-Account-Id": str(account_id)},
    )
    assert created.status_code == 202, created.text
    fetched = client.get(
        f"/v1/query-runs/{created.json()['query_run_id']}",
        headers={"X-Account-Id": str(account_id)},
    )
    assert fetched.status_code == 200, fetched.text
    body: dict[str, Any] = fetched.json()
    return body


def _stage_states(body: dict[str, Any]) -> dict[str, tuple[str, str | None]]:
    return {s["stage"]: (s["state"], s["detail"]) for s in body["progress"]["stages"]}


def test_a_missing_server_key_still_fails_and_skips_the_remaining_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other direction of the gate: when OUR write lands, the skips land.

    Gating ``_mark_remaining_stages`` on the terminal write would be a silent
    regression if the gate also fired on the ordinary path. This is the
    ordinary path for the earliest terminal branch in ``_execute_query_run``
    (live execution enabled with no server-side key): the run really does end
    ``failed``, so the three stages it never reached must really be stamped
    SKIPPED.
    """
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True)
    monkeypatch.setattr(config.settings, "openrouter_api_key", "")
    monkeypatch.setattr(config.settings, "stage_delay_ms", 0)

    body = _run_inline(TestClient(app), uuid4())

    assert body["status"] == "failed"
    stages = _stage_states(body)
    assert stages["initial_answers"][0] == "failed"
    for stage_name in ("debate_round_1", "debate_round_2", "synthesis"):
        assert stages[stage_name] == (
            "skipped",
            "Not executed because an earlier stage failed or timed out.",
        ), f"{stage_name} was left {stages[stage_name]!r} on a genuinely failed run"


def test_a_debate_that_produces_nothing_still_skips_the_remaining_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same counter-direction for the debate branch the cancel test uses.

    ``test_a_cancel_that_wins_also_suppresses_the_skipped_stage_stamps``
    drives this exact branch with a cancel in flight and asserts NO skip
    stamps. Without this pair, deleting the stamps entirely would look fine.
    """

    def _no_debate_outputs(**kwargs: Any) -> DebateResult:
        return DebateResult(
            debate_outputs=[],
            failed_steps=["debate_round_1", "debate_round_2", "synthesis"],
            missing_steps=["debate_round_2", "synthesis"],
            timed_out=False,
            round_timings_ms={},
        )

    monkeypatch.setattr(config.settings, "stage_delay_ms", 0)
    monkeypatch.setattr(debate_stub_service, "run_debate_rounds", _no_debate_outputs)

    body = _run_inline(TestClient(app), uuid4())

    assert body["status"] == "partial"
    stages = _stage_states(body)
    assert stages["debate_round_1"][0] == "failed"
    for stage_name in ("debate_round_2", "synthesis"):
        assert stages[stage_name] == (
            "skipped",
            "Not executed because an earlier stage failed or timed out.",
        ), f"{stage_name} was left {stages[stage_name]!r} on a genuinely partial run"
