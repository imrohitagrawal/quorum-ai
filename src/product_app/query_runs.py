"""Query run orchestration, HTTP routes, and in-memory repository.

The application runs exactly one query at a time per ``account_id``. The
query run is the unit of audit, billing, and observability; every
contributor records an event with the same ``account_id``/``query_run_id``
pair so the audit trail is consistent.

Two execution modes:

* **Legacy / test mode** (the existing test fixture uses this): the
  handler runs the pipeline inline in the request thread and returns the
  final state in the 202 response. The legacy auth path is gated by a
  server-side feature flag (``settings.account_legacy_header_enabled``)
  and is disabled in production. The legacy path is intentional: it lets
  the existing test suite exercise the full pipeline deterministically
  without ever touching a thread pool.
* **Cookie / CSRF mode** (production): the handler validates the session
  cookie and CSRF token, validates the model slots and the cost
  threshold, persists the run, and returns 202 with the ``ACCEPTED``
  state. A background thread then runs the pipeline.

Either way, the pipeline itself is wrapped in a try/except that always
reaches a terminal state — a bug in the pipeline can never leave a run
stuck in ``RUNNING`` forever.
"""

from __future__ import annotations

import contextlib
import logging
import time as _time_module
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from threading import BoundedSemaphore, RLock, Thread
from time import sleep
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from product_app.auth import SessionContext, enforce_csrf, require_session
from product_app.config import settings
from product_app.costs import (
    CostBreakdown,
    CostConfirmation,
    CostEstimate,
    CostThresholdAction,
    build_measured_breakdown,
    cost_estimation_service,
    measured_call_cost_usd,
)
from product_app.debate import (
    AgreementSummary,
    DebateOutput,
    PositionMovement,
    debate_stub_service,
)
from product_app.model_slots import (
    InvalidModelSlotError,
    ModelSlot,
    model_slot_event_recorder,
    validate_model_slots_with_search,
)
from product_app.provider_keys import ProviderCredentialSource
from product_app.providers import (
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    TokenUsage,
    provider_execution_service,
)
from product_app.safety import (
    SafetyAcknowledgement,
    SafetyWarning,
    safety_warning_policy,
)
from product_app.synthesis import (
    FinalSynthesis,
    build_agreement_and_positions,
    synthesis_stub_service,
)

router = APIRouter(prefix="/v1/query-runs", tags=["query-runs"])

logger = logging.getLogger(__name__)


#: Terminal-state TTL for finished runs. The repository evicts runs older
#: than this on every create/get. In production this would be backed by a
#: real database with a real GC; the in-memory implementation exists only
#: to make the contract observable in tests and dev.
QUERY_RUN_TERMINAL_TTL = timedelta(hours=1)
QUERY_RUN_ACTIVE_TTL = timedelta(minutes=30)


class QueryRunStatus(StrEnum):
    DRAFT = "draft"
    COST_REVIEW = "cost_review"
    ACCEPTED = "accepted"
    INITIAL_ANSWERS_RUNNING = "initial_answers_running"
    DEBATE_ROUND_1_RUNNING = "debate_round_1_running"
    DEBATE_ROUND_2_RUNNING = "debate_round_2_running"
    SYNTHESIS_RUNNING = "synthesis_running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    BLOCKED_BY_COST = "blocked_by_cost"
    CANCELLED = "cancelled"


class StageState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


TERMINAL_STATUSES = frozenset(
    {
        QueryRunStatus.COMPLETED,
        QueryRunStatus.PARTIAL,
        QueryRunStatus.FAILED,
        QueryRunStatus.TIMED_OUT,
        QueryRunStatus.BLOCKED_BY_COST,
        QueryRunStatus.CANCELLED,
    }
)

ALLOWED_TRANSITIONS: dict[QueryRunStatus, frozenset[QueryRunStatus]] = {
    QueryRunStatus.DRAFT: frozenset({QueryRunStatus.COST_REVIEW, QueryRunStatus.CANCELLED}),
    QueryRunStatus.COST_REVIEW: frozenset(
        {QueryRunStatus.ACCEPTED, QueryRunStatus.BLOCKED_BY_COST, QueryRunStatus.CANCELLED}
    ),
    QueryRunStatus.ACCEPTED: frozenset(
        {
            QueryRunStatus.INITIAL_ANSWERS_RUNNING,
            QueryRunStatus.FAILED,
            QueryRunStatus.PARTIAL,
            QueryRunStatus.TIMED_OUT,
            QueryRunStatus.CANCELLED,
        }
    ),
    QueryRunStatus.INITIAL_ANSWERS_RUNNING: frozenset(
        {
            QueryRunStatus.DEBATE_ROUND_1_RUNNING,
            QueryRunStatus.PARTIAL,
            QueryRunStatus.FAILED,
            QueryRunStatus.TIMED_OUT,
            QueryRunStatus.CANCELLED,
        }
    ),
    QueryRunStatus.DEBATE_ROUND_1_RUNNING: frozenset(
        {
            QueryRunStatus.DEBATE_ROUND_2_RUNNING,
            QueryRunStatus.PARTIAL,
            QueryRunStatus.FAILED,
            QueryRunStatus.TIMED_OUT,
            QueryRunStatus.CANCELLED,
        }
    ),
    QueryRunStatus.DEBATE_ROUND_2_RUNNING: frozenset(
        {
            QueryRunStatus.SYNTHESIS_RUNNING,
            QueryRunStatus.PARTIAL,
            QueryRunStatus.FAILED,
            QueryRunStatus.TIMED_OUT,
            QueryRunStatus.CANCELLED,
        }
    ),
    QueryRunStatus.SYNTHESIS_RUNNING: frozenset(
        {
            QueryRunStatus.COMPLETED,
            QueryRunStatus.PARTIAL,
            QueryRunStatus.FAILED,
            QueryRunStatus.TIMED_OUT,
            QueryRunStatus.CANCELLED,
        }
    ),
    QueryRunStatus.COMPLETED: frozenset(),
    QueryRunStatus.PARTIAL: frozenset(),
    QueryRunStatus.FAILED: frozenset(),
    QueryRunStatus.TIMED_OUT: frozenset(),
    QueryRunStatus.BLOCKED_BY_COST: frozenset(),
    QueryRunStatus.CANCELLED: frozenset(),
}


class QueryRunStageProgress(BaseModel):
    stage: str
    state: StageState
    detail: str | None = None


class QueryRunProgress(BaseModel):
    current_stage: str
    stages: list[QueryRunStageProgress]


class ResultProjection(BaseModel):
    model_answers: list[InitialModelAnswer]
    debate_outputs: list[DebateOutput]
    final_synthesis: FinalSynthesis | None
    #: Verdict-ring numerator/denominator (aligned of total) for screen 05.
    agreement: AgreementSummary
    #: One row per model, in slot order, for the "how positions moved" table.
    position_movements: list[PositionMovement]


# SEC-C/H7: server-side query text length must align with the frontend
# ``<textarea maxlength="20000">``. The previous 8_000 cap caused a
# silent rejection at the cost-estimation layer for legitimate
# long-form research queries (5K–20K chars). The cost guardrail
# ($0.25 hard cap) already prevents runaway spend, so a generous
# length limit is safe.
_QUERY_TEXT_MAX_LENGTH = 20_000


class QueryRunEstimateRequest(BaseModel):
    query_text: str = Field(min_length=1, max_length=_QUERY_TEXT_MAX_LENGTH)
    model_slots: list[str] = Field(min_length=1)
    # L2: optional per-slot web-search opt-in. Same length as
    # ``model_slots`` when provided. ``None`` (the default) means
    # "use the per-slot default" — which is search-enabled for the
    # default four-slot demo run.
    slot_search: list[bool] | None = None


class QueryRunEstimateResponse(BaseModel):
    correlation_id: str
    cost_estimate: CostEstimate
    model_slots: list[ModelSlot]
    reasons: list[str]


class QueryRunCreateRequest(BaseModel):
    query_text: str = Field(min_length=1, max_length=_QUERY_TEXT_MAX_LENGTH)
    model_slots: list[str] = Field(min_length=1)
    # L2: optional per-slot web-search opt-in. See
    # ``QueryRunEstimateRequest.slot_search`` for the contract.
    slot_search: list[bool] | None = None
    safety_acknowledgements: list[SafetyAcknowledgement] = Field(default_factory=list)
    cost_confirmation: CostConfirmation | None = None


class QueryRunCreateResponse(BaseModel):
    query_run_id: UUID
    status: QueryRunStatus
    correlation_id: str
    model_slots: list[ModelSlot]
    cost_estimate: CostEstimate
    progress: QueryRunProgress
    initial_answers: list[InitialModelAnswer]


class ActiveQueryRunResponse(BaseModel):
    query_run_id: UUID | None
    status: QueryRunStatus | None
    correlation_id: str | None
    progress: QueryRunProgress | None
    model_slots: list[ModelSlot]
    cost_estimate: CostEstimate | None
    initial_answers: list[InitialModelAnswer]


class QueryRunResultResponse(BaseModel):
    query_run_id: UUID
    status: QueryRunStatus
    correlation_id: str
    model_slots: list[ModelSlot]
    cost_estimate: CostEstimate
    elapsed_time_ms: int = Field(ge=0)
    failed_steps: list[str]
    missing_steps: list[str]
    progress: QueryRunProgress
    partial_failure_notice: str | None = None
    provider_failure_notices: list[str]
    result: ResultProjection
    result_generated_at_utc: datetime
    #: ``True`` when any model answer was produced by Quorum's local
    #: simulation helpers (or the fallback search stub) rather than by a
    #: live model provider. The UI uses this flag to render a prominent
    #: demo-mode banner and to render stub source links as in-app
    #: placeholders instead of navigable anchors.
    demo_mode: bool = False
    #: Number of model answers produced by a live provider on this run.
    #: The UI uses this together with ``local_count`` to render a partial
    #: demo banner ("some answers are live, others are simulated")
    #: instead of the binary banner that hides whenever
    #: ``demo_mode is False``.
    live_count: int = Field(ge=0, default=0)
    #: Number of model answers produced by Quorum's local simulation
    #: helpers (LOCAL_SIMULATION or FALLBACK_SEARCH) on this run. The
    #: sum ``live_count + local_count`` always equals the number of
    #: initial answers.
    local_count: int = Field(ge=0, default=0)
    #: Sum of the four models' ``material_claim_count`` values. The UI
    #: surfaces this alongside the citation coverage so the user can
    #: audit the denominator, not just the ratio. ``0`` for runs whose
    #: initial-answers list is empty (e.g. cost-blocked before any model
    #: was called).
    material_claim_count: int = Field(ge=0, default=0)
    #: Actual cost incurred by this run, for the receipt's est→actual
    #: reconciliation. Per-call provider-usage capture is NOT yet plumbed
    #: through the pipeline, so this value currently ALWAYS equals the
    #: estimate (``cost_estimate.estimated_cost_usd``) regardless of
    #: ``demo_mode``: for demo/simulation runs that is exact (no real usage
    #: is billed); for live runs it is the estimate standing in for measured
    #: usage until usage capture lands (a known limitation — this field does
    #: not yet reflect real provider billing on live runs). REQUIRED (no
    #: default): ``_result_response`` always supplies it, so a missing value
    #: should surface loudly rather than silently emit "0".
    actual_cost_usd: Decimal = Field(ge=Decimal("0"))
    #: Itemized actual-cost partition (mirrors ``cost_estimate.breakdown``).
    #: ``None`` when no breakdown is available (e.g. a cost estimate built
    #: without one). Like ``actual_cost_usd``, this currently reuses the
    #: estimate's breakdown verbatim on every run (demo and live) until
    #: per-call usage capture is plumbed through the pipeline.
    actual_breakdown: CostBreakdown | None = None
    #: Provenance of ``actual_cost_usd`` / ``actual_breakdown``:
    #:
    #: * ``"estimated"`` — the value is the pre-run estimate standing in for
    #:   measured usage. This is the ONLY value emitted today, because
    #:   per-call provider-usage capture is not yet plumbed through the
    #:   pipeline: on demo/simulation runs the estimate is exact (no real
    #:   usage was billed), and on live runs it is a known limitation
    #:   (the figure does not yet reflect real provider billing).
    #: * ``"measured"`` — reserved for when usage capture lands and the
    #:   value reflects real per-call provider billing.
    #:
    #: The UI MUST read this to avoid presenting an estimate as a measured
    #: "actual": an ``"estimated"`` receipt is labelled as such rather than
    #: implying the figure was reconciled against provider billing.
    cost_source: Literal["estimated", "measured"] = "estimated"


class QueryRunWarningsRequest(BaseModel):
    query_text: str = Field(min_length=1, max_length=8_000)


class QueryRunWarningsResponse(BaseModel):
    warnings: list[SafetyWarning]


class ActiveQueryRunExistsError(Exception):
    pass


class InvalidQueryRunTransitionError(ValueError):
    pass


@dataclass
class QueryRun:
    query_run_id: UUID
    account_id: UUID
    query_text: str
    status: QueryRunStatus
    correlation_id: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    model_slots: list[ModelSlot]
    cost_estimate: CostEstimate
    progress: list[QueryRunStageProgress] = field(default_factory=list)
    initial_answers: list[InitialModelAnswer] = field(default_factory=list)
    debate_outputs: list[DebateOutput] = field(default_factory=list)
    final_synthesis: FinalSynthesis | None = None
    failed_steps: list[str] = field(default_factory=list)
    missing_steps: list[str] = field(default_factory=list)
    #: Real per-call token usage captured from the live debate/synthesis calls
    #: (P2). One entry per billed live call; ``None`` inside a list means the
    #: call went live but the provider omitted its usage object. Read by
    #: ``_actual_cost`` to decide whether the run's actual cost can be measured.
    debate_call_usages: list[tuple[int, TokenUsage | None]] = field(default_factory=list)
    synthesis_call_usages: list[TokenUsage | None] = field(default_factory=list)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


class InMemoryQueryRunRepository:
    """In-memory repository, account-scoped.

    The repository is the single source of truth for the active-run rule
    (``account_id`` can have at most one non-terminal run at a time) and
    for the run state machine. It enforces the active-run rule under a
    lock so two concurrent requests from the same account cannot both
    create a run.
    """

    def __init__(self) -> None:
        self._query_runs: dict[UUID, QueryRun] = {}
        self._lock = RLock()
        self._op_counter = 0

    def create(
        self,
        *,
        account_id: UUID,
        query_text: str,
        model_slots: list[ModelSlot],
        cost_estimate: CostEstimate,
    ) -> QueryRun:
        with self._lock:
            self._purge_expired_locked()
            if self.get_active_for_account(account_id) is not None:
                raise ActiveQueryRunExistsError
            query_run_id = uuid4()
            now = datetime.now(UTC)
            query_run = QueryRun(
                query_run_id=query_run_id,
                account_id=account_id,
                query_text=query_text,
                status=QueryRunStatus.ACCEPTED,
                correlation_id=f"qr_{query_run_id.hex}",
                created_at=now,
                updated_at=now,
                started_at=None,
                model_slots=model_slots,
                cost_estimate=cost_estimate,
                progress=_initial_progress(),
            )
            self._query_runs[query_run_id] = query_run
            return query_run

    def get(self, query_run_id: UUID) -> QueryRun:
        with self._lock:
            self._purge_expired_locked()
            try:
                return self._query_runs[query_run_id]
            except KeyError as exc:
                raise KeyError(query_run_id) from exc

    def get_for_account(self, *, query_run_id: UUID, account_id: UUID) -> QueryRun | None:
        with self._lock:
            self._purge_expired_locked()
            query_run = self._query_runs.get(query_run_id)
            if query_run is None or query_run.account_id != account_id:
                return None
            return query_run

    def get_active_for_account(self, account_id: UUID) -> QueryRun | None:
        with self._lock:
            self._purge_expired_locked()
            for query_run in self._query_runs.values():
                if query_run.account_id == account_id and not query_run.is_terminal:
                    return query_run
            return None

    def transition(
        self,
        query_run_id: UUID,
        next_status: QueryRunStatus,
        *,
        failed_steps: list[str] | None = None,
        missing_steps: list[str] | None = None,
    ) -> QueryRun:
        with self._lock:
            query_run = self._query_runs[query_run_id]
            if next_status not in ALLOWED_TRANSITIONS[query_run.status]:
                msg = f"Cannot transition query run from {query_run.status} to {next_status}."
                raise InvalidQueryRunTransitionError(msg)
            query_run.status = next_status
            query_run.updated_at = datetime.now(UTC)
            if query_run.started_at is None and next_status is not QueryRunStatus.ACCEPTED:
                query_run.started_at = query_run.updated_at
            if failed_steps is not None:
                query_run.failed_steps = failed_steps
            if missing_steps is not None:
                query_run.missing_steps = missing_steps
            return query_run

    def update_status(
        self,
        query_run_id: UUID,
        *,
        status_value: QueryRunStatus | None = None,
        stage_name: str | None = None,
        stage_state: StageState | None = None,
        detail: str | None = None,
        failed_steps: list[str] | None = None,
        missing_steps: list[str] | None = None,
        mark_started: bool = False,
    ) -> QueryRun:
        with self._lock:
            query_run = self._query_runs[query_run_id]
            now = datetime.now(UTC)
            if status_value is not None:
                query_run.status = status_value
            query_run.updated_at = now
            if mark_started and query_run.started_at is None:
                query_run.started_at = now
            if stage_name and stage_state:
                _set_stage_state(query_run.progress, stage_name, stage_state, detail)
            if failed_steps is not None:
                query_run.failed_steps = failed_steps
            if missing_steps is not None:
                query_run.missing_steps = missing_steps
            return query_run

    def record_initial_answer(self, query_run_id: UUID, answer: InitialModelAnswer) -> QueryRun:
        with self._lock:
            query_run = self._query_runs[query_run_id]
            query_run.initial_answers = [
                existing
                for existing in query_run.initial_answers
                if existing.slot_number != answer.slot_number
            ] + [answer]
            query_run.initial_answers.sort(key=lambda item: item.slot_number)
            query_run.updated_at = datetime.now(UTC)
            return query_run

    def record_initial_answers(
        self,
        query_run_id: UUID,
        initial_answers: list[InitialModelAnswer],
    ) -> QueryRun:
        last: QueryRun | None = None
        for answer in initial_answers:
            last = self.record_initial_answer(query_run_id, answer)
        if last is None:
            return self._query_runs[query_run_id]
        return last

    def record_debate_outputs(
        self,
        query_run_id: UUID,
        debate_outputs: list[DebateOutput],
        live_call_usages: list[tuple[int, TokenUsage | None]] | None = None,
    ) -> QueryRun:
        with self._lock:
            query_run = self._query_runs[query_run_id]
            query_run.debate_outputs = debate_outputs
            if live_call_usages is not None:
                query_run.debate_call_usages = live_call_usages
            query_run.updated_at = datetime.now(UTC)
            return query_run

    def record_final_synthesis(
        self,
        query_run_id: UUID,
        final_synthesis: FinalSynthesis,
        live_call_usages: list[TokenUsage | None] | None = None,
    ) -> QueryRun:
        with self._lock:
            query_run = self._query_runs[query_run_id]
            query_run.final_synthesis = final_synthesis
            if live_call_usages is not None:
                query_run.synthesis_call_usages = live_call_usages
            query_run.updated_at = datetime.now(UTC)
            return query_run

    def clear(self) -> None:
        with self._lock:
            self._query_runs.clear()
            self._op_counter = 0

    def _purge_expired_locked(self) -> None:
        # SEC-H3: time-based eviction instead of counter-based.
        # The old counter-based eviction only ran every 1024 ops,
        # which meant a quiet process followed by a burst could
        # see unbounded growth until 1024 ops accumulated. A
        # 60-second wall-clock check fires promptly when needed
        # but is cheap (one datetime comparison) on the hot path.
        now = datetime.now(UTC)
        # Always check for terminal-expired runs (cheap when dict is small)
        expired: list[UUID] = []
        for query_run_id, query_run in self._query_runs.items():
            age = now - query_run.updated_at
            terminal_expired = query_run.is_terminal and age > QUERY_RUN_TERMINAL_TTL
            active_expired = not query_run.is_terminal and age > QUERY_RUN_ACTIVE_TTL
            if terminal_expired or active_expired:
                expired.append(query_run_id)
        for query_run_id in expired:
            self._query_runs.pop(query_run_id, None)


query_run_repository = InMemoryQueryRunRepository()


# --- Concurrency guardrails -------------------------------------------------
# C9: limit the number of in-flight query runs to prevent thread-exhaustion
# DoS. Each run spawns up to 11 sequential LLM calls; an unbounded number
# of concurrent runs can starve the worker pool. The cap is generous
# (16) so a small burst of legitimate users is not affected, but a
# hostile client cannot exhaust the process.
_MAX_CONCURRENT_RUNS = 16
_run_semaphore = BoundedSemaphore(_MAX_CONCURRENT_RUNS)


# PERF-P0: thread pool for parallel LLM calls. Each query run spawns
# 4 initial-answer calls + 5 synthesis calls that used to run
# serially. With 4 workers per slot and 5 for synthesis, the wall-
# clock time for the initial-answer stage drops from ~4x to ~1x the
# per-call latency. The pool size of 16 (= max concurrent runs × 4)
# gives each run its own slot without queueing under steady load.
_INITIAL_ANSWER_POOL_SIZE = 16
_SYNTHESIS_POOL_SIZE = 16
_initial_answer_pool = ThreadPoolExecutor(
    max_workers=_INITIAL_ANSWER_POOL_SIZE, thread_name_prefix="initial-answer"
)
_synthesis_pool = ThreadPoolExecutor(
    max_workers=_SYNTHESIS_POOL_SIZE, thread_name_prefix="synthesis"
)


# C9: per-IP rate limiter on ``/v1/session``. Each new session mints a
# new account id; without a limiter, a script can create thousands of
# sessions per second and bloat the in-memory ``session_repository``.
# The limiter is a simple token bucket: 30 requests per IP per minute.
# 429 is returned when the bucket is empty.
class _InMemoryIpRateLimiter:
    """Naive per-IP token bucket. Single-process only.

    For multi-instance deployments, swap this for a Redis-backed
    limiter. The interface (``allow(ip) -> bool``) is the same so the
    rest of the application does not change.
    """

    CAPACITY = 30
    REFILL_PER_MINUTE = 30
    # SEC-H3: stale buckets are evicted after 5 minutes of full
    # capacity (refill window). Without this, a /16 IPv4 scan would
    # add 65K entries that never expire.
    STALE_BUCKET_SECONDS = 300.0

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = RLock()

    def allow(self, *, ip: str, now_epoch: float) -> bool:
        with self._lock:
            tokens, last = self._buckets.get(ip, (float(self.CAPACITY), now_epoch))
            elapsed_minutes = max(0.0, (now_epoch - last) / 60.0)
            tokens = min(
                float(self.CAPACITY),
                tokens + elapsed_minutes * self.REFILL_PER_MINUTE,
            )
            # SEC-H3: evict stale buckets (full for > 5 minutes)
            if tokens >= float(self.CAPACITY) and (now_epoch - last) > self.STALE_BUCKET_SECONDS:
                self._buckets.pop(ip, None)
                return True
            if tokens < 1.0:
                self._buckets[ip] = (tokens, now_epoch)
                return False
            tokens -= 1.0
            self._buckets[ip] = (tokens, now_epoch)
            return True

    def clear(self) -> None:
        with self._lock:
            self._buckets.clear()


_ip_rate_limiter = _InMemoryIpRateLimiter()


# SEC-C3: per-account rate limiter for expensive mutating endpoints
# (estimate, create, warnings, delete). The cost guardrail already
# limits spend, but it doesn't limit request rate: an attacker with
# a valid session could still create thousands of estimate requests
# per second, each writing an audit event and consuming worker
# threads. The 16-run semaphore eventually blocks new runs, but only
# after they've all entered the pipeline. This limiter cuts off
# attackers at the door.
#
# Limits: 30 requests per account per minute (matches the IP limiter).
# This is generous for legitimate use (typing speed, polling) but
# blocks a script.
class _InMemoryAccountRateLimiter:
    """Per-account token bucket. Single-process only.

    Same shape as ``_InMemoryIpRateLimiter`` but keyed on the
    authenticated ``account_id`` rather than the source IP. This is
    the right key for the expensive endpoints because legitimate
    users share IPs (NAT, corporate networks) but not accounts.
    """

    CAPACITY = 30
    REFILL_PER_MINUTE = 30
    # SEC-H3: stale buckets are evicted after 5 minutes of full capacity
    STALE_BUCKET_SECONDS = 300.0

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = RLock()

    def allow(self, *, account_id: str, now_epoch: float) -> bool:
        with self._lock:
            tokens, last = self._buckets.get(account_id, (float(self.CAPACITY), now_epoch))
            elapsed_minutes = max(0.0, (now_epoch - last) / 60.0)
            tokens = min(
                float(self.CAPACITY),
                tokens + elapsed_minutes * self.REFILL_PER_MINUTE,
            )
            # SEC-H3: evict stale buckets
            if tokens >= float(self.CAPACITY) and (now_epoch - last) > self.STALE_BUCKET_SECONDS:
                self._buckets.pop(account_id, None)
                return True
            if tokens < 1.0:
                self._buckets[account_id] = (tokens, now_epoch)
                return False
            tokens -= 1.0
            self._buckets[account_id] = (tokens, now_epoch)
            return True

    def clear(self) -> None:
        with self._lock:
            self._buckets.clear()


_account_rate_limiter = _InMemoryAccountRateLimiter()


def _enforce_account_rate_limit(request: Request, session: SessionContext) -> None:
    """Rate-limit an authenticated request by account. Returns 429 if over.

    This is a plain helper (not a FastAPI dependency) so routes can
    call it explicitly after auth + CSRF are confirmed. Putting it
    after auth means attackers can't burn tokens by forging the
    header. Putting it after CSRF means the CSRF check (which is
    cheap) runs first and we don't count rate-limited requests
    against the bucket.
    """
    if not _account_rate_limiter.allow(
        account_id=str(session.account_id), now_epoch=_time_module.time()
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "RATE_LIMITED",
                "message": ("Too many requests for this account. Limit is 30 requests per minute."),
            },
        )


# -- routes ------------------------------------------------------------------


@router.post("/estimate", response_model=QueryRunEstimateResponse)
def estimate_query_run(
    payload: QueryRunEstimateRequest,
    request: Request,
    session: Annotated[SessionContext, Depends(require_session)],
) -> QueryRunEstimateResponse:
    # The estimate endpoint writes an audit event
    # (``record_guardrail_event``) and is therefore a state-mutating
    # action — it must enforce CSRF like the create and delete routes.
    enforce_csrf(request, session)
    # SEC-C3: per-account rate limit to prevent rapid-fire estimate spam
    _enforce_account_rate_limit(request, session)
    model_slots = _validated_model_slots(
        payload.model_slots,
        slot_search=payload.slot_search,
    )
    estimate = cost_estimation_service.estimate(
        query_text=payload.query_text,
        model_slots=model_slots,
        account_id=session.account_id,
    )
    cost_estimation_service.record_guardrail_event(
        account_id=session.account_id,
        query_run_id=None,
        estimated_cost_usd=estimate.estimated_cost_usd,
        threshold_action=estimate.threshold_action,
        confirmed=False,
    )
    return QueryRunEstimateResponse(
        correlation_id=f"estimate_{uuid4().hex}",
        cost_estimate=estimate,
        model_slots=model_slots,
        reasons=_estimate_reasons(estimate),
    )


@router.post("", response_model=QueryRunCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def create_query_run(
    payload: QueryRunCreateRequest,
    request: Request,
    session: Annotated[SessionContext, Depends(require_session)],
) -> QueryRunCreateResponse:
    enforce_csrf(request, session)
    # SEC-C3: per-account rate limit to prevent rapid-fire run creation
    _enforce_account_rate_limit(request, session)
    model_slots = _validated_model_slots(
        payload.model_slots,
        slot_search=payload.slot_search,
    )
    required_warnings = safety_warning_policy.required_warnings_for_query(payload.query_text)
    missing_acknowledgements = safety_warning_policy.missing_acknowledgements(
        required_warnings=required_warnings,
        acknowledgements=payload.safety_acknowledgements,
    )
    if missing_acknowledgements:
        safety_warning_policy.record_warning_impression(
            account_id=session.account_id,
            query_run_id=None,
            warnings=required_warnings,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "Required safety acknowledgements are missing.",
                "required_warnings": [
                    warning.model_dump(mode="json") for warning in missing_acknowledgements
                ],
            },
        )

    cost_estimate = cost_estimation_service.estimate(
        query_text=payload.query_text,
        model_slots=model_slots,
        account_id=session.account_id,
    )
    cost_decision = cost_estimation_service.evaluate_confirmation(
        estimate=cost_estimate,
        confirmation=payload.cost_confirmation,
        account_id=session.account_id,
    )
    if cost_estimate.threshold_action is CostThresholdAction.BLOCK:
        cost_estimation_service.record_guardrail_event(
            account_id=session.account_id,
            query_run_id=None,
            estimated_cost_usd=cost_estimate.estimated_cost_usd,
            threshold_action=cost_estimate.threshold_action,
            confirmed=False,
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "COST_LIMIT_EXCEEDED",
                "message": "Estimated query cost exceeds the hard ceiling for this slice.",
                "cost_estimate": cost_estimate.model_dump(mode="json"),
            },
        )
    if (
        cost_estimate.threshold_action is CostThresholdAction.REQUIRE_CONFIRMATION
        and not cost_decision.confirmed
    ):
        cost_estimation_service.record_guardrail_event(
            account_id=session.account_id,
            query_run_id=None,
            estimated_cost_usd=cost_estimate.estimated_cost_usd,
            threshold_action=cost_estimate.threshold_action,
            confirmed=False,
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "COST_CONFIRMATION_REQUIRED",
                "message": "Estimated query cost requires explicit confirmation.",
                "cost_estimate": cost_estimate.model_dump(mode="json"),
            },
        )

    try:
        query_run = query_run_repository.create(
            account_id=session.account_id,
            query_text=payload.query_text,
            model_slots=model_slots,
            cost_estimate=cost_estimate,
        )
    except ActiveQueryRunExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ACTIVE_QUERY_EXISTS",
                "message": "One query can run at a time for this account.",
            },
        ) from exc

    safety_warning_policy.record_acknowledgement(
        account_id=session.account_id,
        query_run_id=query_run.query_run_id,
        acknowledgements=payload.safety_acknowledgements,
    )
    model_slot_event_recorder.record(
        event_type="model_slot_selection_recorded",
        account_id=session.account_id,
        query_run_id=query_run.query_run_id,
        # L2: include the per-slot ``search`` flag in the audit-event
        # tuple so the on-the-wire record reflects the caller's opt-in
        # decision, not just the slot number and model id.
        model_slots=tuple(
            (slot.slot_number, slot.model_id, slot.search) for slot in query_run.model_slots
        ),
    )
    cost_estimation_service.record_guardrail_event(
        account_id=session.account_id,
        query_run_id=query_run.query_run_id,
        estimated_cost_usd=query_run.cost_estimate.estimated_cost_usd,
        threshold_action=query_run.cost_estimate.threshold_action,
        # ``confirmed`` indicates whether the caller supplied a
        # confirmation token for a require-confirmation request. For
        # ALLOW the caller never needed to confirm, so we always
        # record ``False`` in that case.
        confirmed=(
            cost_decision.confirmed
            and query_run.cost_estimate.threshold_action is CostThresholdAction.REQUIRE_CONFIRMATION
        ),
    )

    # Legacy/test path runs inline so the test suite can assert against
    # the final state synchronously. Production / cookie path runs in a
    # background thread that cannot block the request response.
    if session.legacy:
        _execute_query_run(query_run.query_run_id, session.account_id)
        query_run = query_run_repository.get(query_run.query_run_id)
    else:
        # C9: do not spawn a thread if the in-flight run cap is
        # already at capacity. Returning 503 with a clear error
        # message lets the client retry after a backoff. We hold
        # the semaphore briefly to perform this check, then release
        # it (the actual run will re-acquire it). The non-blocking
        # ``acquire(blocking=False)`` is intentional: we don't want
        # to queue requests and run them all sequentially if the
        # process is already saturated.
        if not _run_semaphore.acquire(blocking=False):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "RUN_CAPACITY_EXCEEDED",
                    "message": (
                        "Quorum is at capacity for concurrent query runs. "
                        "Retry after a short backoff."
                    ),
                },
            )
        try:
            Thread(
                target=_execute_query_run_with_semaphore_release,
                args=(query_run.query_run_id, session.account_id),
                daemon=True,
            ).start()
        except RuntimeError:
            # Threading failure (e.g. on shutdown). Release the
            # semaphore so it doesn't leak.
            _run_semaphore.release()
            raise
    return QueryRunCreateResponse(
        query_run_id=query_run.query_run_id,
        status=query_run.status,
        correlation_id=query_run.correlation_id,
        model_slots=query_run.model_slots,
        cost_estimate=query_run.cost_estimate,
        progress=_progress_model(query_run),
        initial_answers=query_run.initial_answers,
    )


@router.post("/warnings", response_model=QueryRunWarningsResponse)
def get_query_run_warnings(
    payload: QueryRunWarningsRequest,
    request: Request,
    session: Annotated[SessionContext, Depends(require_session)],
) -> QueryRunWarningsResponse:
    # The warnings endpoint writes an audit event
    # (``record_warning_impression``) and is therefore a state-mutating
    # action — it must enforce CSRF like the create and delete routes.
    enforce_csrf(request, session)
    # SEC-C3: per-account rate limit to prevent rapid-fire warning polls
    _enforce_account_rate_limit(request, session)
    warnings = safety_warning_policy.required_warnings_for_query(payload.query_text)
    safety_warning_policy.record_warning_impression(
        account_id=session.account_id,
        query_run_id=None,
        warnings=warnings,
    )
    return QueryRunWarningsResponse(warnings=warnings)


@router.get("/active", response_model=ActiveQueryRunResponse)
def get_active_query_run(
    session: Annotated[SessionContext, Depends(require_session)],
) -> ActiveQueryRunResponse:
    query_run = query_run_repository.get_active_for_account(session.account_id)
    if query_run is None:
        return ActiveQueryRunResponse(
            query_run_id=None,
            status=None,
            correlation_id=None,
            progress=None,
            model_slots=[],
            cost_estimate=None,
            initial_answers=[],
        )
    return ActiveQueryRunResponse(
        query_run_id=query_run.query_run_id,
        status=query_run.status,
        correlation_id=query_run.correlation_id,
        progress=_progress_model(query_run),
        model_slots=query_run.model_slots,
        cost_estimate=query_run.cost_estimate,
        initial_answers=query_run.initial_answers,
    )


@router.get("/{query_run_id}", response_model=QueryRunResultResponse)
def get_query_run_result(
    query_run_id: UUID,
    session: Annotated[SessionContext, Depends(require_session)],
) -> QueryRunResultResponse:
    query_run = query_run_repository.get_for_account(
        query_run_id=query_run_id,
        account_id=session.account_id,
    )
    if query_run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "QUERY_RUN_NOT_FOUND",
                "message": "Query run was not found for this account.",
            },
        )
    return _result_response(query_run)


@router.delete("/{query_run_id}", response_model=QueryRunResultResponse)
def cancel_query_run(
    query_run_id: UUID,
    request: Request,
    session: Annotated[SessionContext, Depends(require_session)],
) -> QueryRunResultResponse:
    enforce_csrf(request, session)
    # SEC-C3: per-account rate limit to prevent rapid-fire cancel spam
    _enforce_account_rate_limit(request, session)
    query_run = query_run_repository.get_for_account(
        query_run_id=query_run_id,
        account_id=session.account_id,
    )
    if query_run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "QUERY_RUN_NOT_FOUND",
                "message": "Query run was not found for this account.",
            },
        )
    if query_run.is_terminal:
        # Idempotent: cancelling an already-terminal run returns the
        # existing state (e.g. a ``COMPLETED`` run that finished a few
        # milliseconds before the DELETE arrived) rather than overwriting
        # it with ``CANCELLED``.
        return _result_response(query_run)
    # Route the state change through the repository transition so the
    # ``ALLOWED_TRANSITIONS`` guard rejects any race that promotes a
    # terminal status back to ``CANCELLED``. The previous
    # ``update_status`` path bypassed that guard and could overwrite a
    # concurrent ``COMPLETED`` state.
    try:
        cancelled = query_run_repository.transition(
            query_run_id,
            QueryRunStatus.CANCELLED,
        )
    except InvalidQueryRunTransitionError:
        # A concurrent pipeline completion won the race. Re-fetch and
        # return the existing terminal state.
        refreshed = query_run_repository.get_for_account(
            query_run_id=query_run_id,
            account_id=session.account_id,
        )
        return _result_response(refreshed or query_run)
    query_run_repository.update_status(
        query_run_id,
        stage_name=_running_stage_name(cancelled.progress),
        stage_state=StageState.SKIPPED,
        detail="Cancelled by the user.",
    )
    refreshed = query_run_repository.get(query_run_id)
    return _result_response(refreshed)


# -- pipeline ----------------------------------------------------------------


def _execute_query_run_safely(query_run_id: UUID, account_id: UUID) -> None:
    """Thread entry point that always reaches a terminal state."""
    try:
        _execute_query_run(query_run_id=query_run_id, account_id=account_id)
    except BaseException as exc:  # noqa: BLE001 - the contract is "never stuck"
        with contextlib.suppress(Exception):
            # Last resort: nothing to do if the repository itself is dead.
            query_run_repository.update_status(
                query_run_id,
                status_value=QueryRunStatus.FAILED,
                stage_name=_running_stage_name(query_run_repository.get(query_run_id).progress),
                stage_state=StageState.FAILED,
                detail=f"Unhandled pipeline error: {type(exc).__name__}.",
                failed_steps=["pipeline"],
                missing_steps=[
                    stage.stage
                    for stage in query_run_repository.get(query_run_id).progress
                    if stage.state is StageState.PENDING
                ],
            )


def _execute_query_run_with_semaphore_release(query_run_id: UUID, account_id: UUID) -> None:
    """Thread entry point that also releases the run-cap semaphore.

    The semaphore is acquired in the request handler (so the 503
    response can be returned synchronously) and released here after
    the run reaches a terminal state. Using a ``try/finally`` means
    the semaphore is released even if the run raises an unhandled
    exception, which prevents the cap from leaking on a crash.
    """
    try:
        _execute_query_run_safely(query_run_id=query_run_id, account_id=account_id)
    finally:
        _run_semaphore.release()


def _execute_query_run(query_run_id: UUID, account_id: UUID) -> None:
    query_run = query_run_repository.get(query_run_id)
    openrouter_key = settings.openrouter_api_key or ""
    credential_source = ProviderCredentialSource.APP_OWNED
    if settings.openrouter_live_execution_enabled and not settings.openrouter_api_key:
        query_run_repository.update_status(
            query_run_id,
            status_value=QueryRunStatus.FAILED,
            stage_name="initial_answers",
            stage_state=StageState.FAILED,
            detail=("Live execution is enabled but no server-side key is configured."),
            failed_steps=["initial_answers", "debate_round_1", "debate_round_2", "synthesis"],
            missing_steps=["initial_answers", "debate_round_1", "debate_round_2", "synthesis"],
        )
        _mark_remaining_stages(query_run_id, ["debate_round_1", "debate_round_2", "synthesis"])
        return
    query_run_repository.update_status(
        query_run_id,
        status_value=QueryRunStatus.INITIAL_ANSWERS_RUNNING,
        stage_name="initial_answers",
        stage_state=StageState.RUNNING,
        detail="Running four initial model calls.",
        mark_started=True,
    )

    # PERF-P0: parallelize the 4 initial-answer calls. Previously ran
    # serially (4x per-call latency); now runs concurrently via the
    # shared ThreadPoolExecutor. ``record_initial_answer`` is called
    # inside the worker because the repository lock serializes those
    # writes cheaply. ``stage_delay_ms`` is no longer applied here —
    # the parallelism already provides visible stage transitions.
    def _produce_one_initial_answer(model_slot: ModelSlot) -> InitialModelAnswer:
        if _should_stop(query_run_id):
            # Return a stub FAILED answer when cancelled mid-flight.
            # ``cancelled_answer`` mirrors the field shape of
            # ``_failed_answer`` so the downstream debate/synthesis
            # path can consume a cancelled slot identically to a
            # provider-failed one — see its docstring.
            return provider_execution_service.cancelled_answer(model_slot)
        return provider_execution_service.produce_initial_answer(
            account_id=account_id,
            query_run_id=query_run_id,
            query_text=query_run.query_text,
            model_slot=model_slot,
            credential_source=credential_source,
            openrouter_key=openrouter_key,
        )

    futures = [
        _initial_answer_pool.submit(_produce_one_initial_answer, slot)
        for slot in query_run.model_slots
    ]
    for future in futures:
        try:
            answer = future.result()
        except Exception:
            # Future failed unexpectedly; skip and continue
            continue
        if _should_stop(query_run_id):
            return
        query_run_repository.record_initial_answer(query_run_id, answer)

    refreshed = query_run_repository.get(query_run_id)
    if not any(
        answer.status is InitialAnswerStatus.COMPLETED for answer in refreshed.initial_answers
    ):
        query_run_repository.update_status(
            query_run_id,
            status_value=QueryRunStatus.PARTIAL,
            stage_name="initial_answers",
            stage_state=StageState.FAILED,
            detail="No usable initial model answers completed.",
            failed_steps=["initial_answers", "debate_round_1", "debate_round_2", "synthesis"],
            missing_steps=["debate_round_1", "debate_round_2", "synthesis"],
        )
        _mark_remaining_stages(query_run_id, ["debate_round_1", "debate_round_2", "synthesis"])
        return
    query_run_repository.update_status(
        query_run_id,
        status_value=QueryRunStatus.DEBATE_ROUND_1_RUNNING,
        stage_name="initial_answers",
        stage_state=StageState.COMPLETED,
        detail="Initial model answers collected.",
    )
    query_run_repository.update_status(
        query_run_id,
        stage_name="debate_round_1",
        stage_state=StageState.RUNNING,
        detail="Running debate round 1.",
    )
    sleep(settings.stage_delay_ms / 1000)
    if _should_stop(query_run_id):
        return
    debate_result = debate_stub_service.run_debate_rounds(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text=query_run.query_text,
        initial_answers=refreshed.initial_answers,
        openrouter_key=openrouter_key,
    )
    query_run_repository.record_debate_outputs(
        query_run_id,
        debate_result.debate_outputs,
        live_call_usages=debate_result.live_call_usages,
    )
    if not debate_result.debate_outputs:
        query_run_repository.update_status(
            query_run_id,
            status_value=QueryRunStatus.PARTIAL,
            stage_name="debate_round_1",
            stage_state=StageState.FAILED,
            detail="Debate could not start because initial answers were unavailable.",
            failed_steps=debate_result.failed_steps,
            missing_steps=debate_result.missing_steps,
        )
        _mark_remaining_stages(query_run_id, ["debate_round_2", "synthesis"])
        return
    query_run_repository.update_status(
        query_run_id,
        status_value=QueryRunStatus.DEBATE_ROUND_2_RUNNING,
        stage_name="debate_round_1",
        stage_state=StageState.COMPLETED,
        detail="Debate round 1 completed.",
    )
    if debate_result.timed_out:
        query_run_repository.update_status(
            query_run_id,
            status_value=QueryRunStatus.PARTIAL,
            stage_name="debate_round_2",
            stage_state=StageState.FAILED,
            detail="Debate round 2 timed out.",
            failed_steps=debate_result.failed_steps,
            missing_steps=debate_result.missing_steps,
        )
        _mark_remaining_stages(query_run_id, ["synthesis"])
        return
    query_run_repository.update_status(
        query_run_id,
        stage_name="debate_round_2",
        stage_state=StageState.RUNNING,
        detail="Running debate round 2.",
    )
    sleep(settings.stage_delay_ms / 1000)
    if _should_stop(query_run_id):
        return
    query_run_repository.update_status(
        query_run_id,
        status_value=QueryRunStatus.SYNTHESIS_RUNNING,
        stage_name="debate_round_2",
        stage_state=StageState.COMPLETED,
        detail="Debate round 2 completed.",
    )
    query_run_repository.update_status(
        query_run_id,
        stage_name="synthesis",
        stage_state=StageState.RUNNING,
        detail="Synthesizing consensus and disagreement.",
    )
    sleep(settings.stage_delay_ms / 1000)
    if _should_stop(query_run_id):
        return
    latest = query_run_repository.get(query_run_id)
    synthesis_result = synthesis_stub_service.produce_final_synthesis(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text=query_run.query_text,
        initial_answers=latest.initial_answers,
        debate_outputs=latest.debate_outputs,
        openrouter_key=openrouter_key,
    )
    if synthesis_result.final_synthesis is None:
        query_run_repository.update_status(
            query_run_id,
            status_value=QueryRunStatus.PARTIAL,
            stage_name="synthesis",
            stage_state=StageState.FAILED,
            detail="Synthesis could not complete from the available evidence.",
            failed_steps=synthesis_result.failed_steps,
            missing_steps=synthesis_result.missing_steps,
        )
        return
    query_run_repository.record_final_synthesis(
        query_run_id,
        synthesis_result.final_synthesis,
        live_call_usages=synthesis_result.live_call_usages,
    )
    query_run_repository.update_status(
        query_run_id,
        status_value=QueryRunStatus.COMPLETED,
        stage_name="synthesis",
        stage_state=StageState.COMPLETED,
        detail="Synthesis completed.",
    )
    # issue #16 telemetry: log the estimate/actual accuracy ONCE, at
    # completion. This is the signal that tells us whether the pre-run
    # estimate's token model tracks reality over live traffic, so the
    # ``cost_*_tokens`` constants can be recalibrated (and a regression
    # caught) without re-running the whole validation by hand.
    _log_estimate_accuracy(query_run_id)


# -- helpers -----------------------------------------------------------------


def _log_estimate_accuracy(query_run_id: UUID) -> None:
    """Emit the estimate-vs-measured ratio for a completed run (issue #16).

    Best-effort and completely side-effect-free beyond a log line: any
    failure here must never affect the run's terminal state, so the whole
    body is guarded. Only runs whose actual cost is genuinely ``measured``
    (the strict-honesty gate in :func:`_actual_cost` passed) carry a
    meaningful ratio; an ``estimated`` receipt is the estimate standing in
    for itself (ratio 1.0 by construction) and is not worth logging.
    """
    try:
        query_run = query_run_repository.get(query_run_id)
        if query_run is None:
            return
        estimated = query_run.cost_estimate.estimated_cost_usd
        actual, _breakdown, cost_source = _actual_cost(query_run)
        if cost_source != "measured" or actual <= 0:
            return
        ratio = float(estimated / actual)
        logger.info(
            "cost_estimate_accuracy query_run_id=%s estimated_usd=%s "
            "measured_usd=%s estimate_over_actual_ratio=%.3f",
            query_run_id,
            estimated,
            actual,
            ratio,
        )
    except Exception as exc:  # noqa: BLE001 — telemetry must never crash a run
        logger.debug("cost_estimate_accuracy logging failed: %s", exc)


def _validated_model_slots(
    model_ids: list[str],
    *,
    slot_search: list[bool] | None = None,
) -> list[ModelSlot]:
    # L2: thread the optional per-slot ``search`` flag from the request
    # body through validation. When ``slot_search`` is None, every slot
    # defaults to ``search=True`` (preserves the four-slot "all on"
    # default). When provided, the helper enforces length == 4 and
    # raises ``InvalidModelSlotError`` on a mismatch — caught and
    # converted to a 422 with the same ``INVALID_MODEL_SLOT`` envelope
    # the existing handler tests assert on.
    try:
        return validate_model_slots_with_search(
            model_ids,
            slot_search=slot_search,
        )
    except InvalidModelSlotError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "INVALID_MODEL_SLOT",
                "message": "Model slot count or identifier validation failed.",
                "slot_errors": [
                    {
                        "slot_number": error.slot_number,
                        "model_id": error.model_id,
                        "message": error.message,
                    }
                    for error in exc.errors
                ],
            },
        ) from exc


def _estimate_reasons(estimate: CostEstimate) -> list[str]:
    if estimate.threshold_action is CostThresholdAction.ALLOW:
        return ["Estimated cost is within the normal execution band."]
    if estimate.threshold_action is CostThresholdAction.REQUIRE_CONFIRMATION:
        return ["Estimated cost exceeds USD 0.15 and requires explicit confirmation."]
    return ["Estimated cost exceeds USD 0.25 and is blocked for this slice."]


def _result_response(query_run: QueryRun) -> QueryRunResultResponse:
    provider_failure_notices = list(
        dict.fromkeys(
            [
                answer.provider_notice
                for answer in query_run.initial_answers
                if answer.provider_notice is not None
            ]
        )
    )
    partial_failure_notice = None
    if query_run.status in {
        QueryRunStatus.PARTIAL,
        QueryRunStatus.FAILED,
        QueryRunStatus.TIMED_OUT,
    }:
        partial_failure_notice = (
            "This run finished without every planned stage. Review failed and missing steps "
            "before relying on the synthesis."
        )
    demo_mode = any(
        answer.provider_path in {ProviderPath.LOCAL_SIMULATION, ProviderPath.FALLBACK_SEARCH}
        for answer in query_run.initial_answers
    )
    local_count = sum(
        1
        for answer in query_run.initial_answers
        if answer.provider_path in {ProviderPath.LOCAL_SIMULATION, ProviderPath.FALLBACK_SEARCH}
    )
    live_count = sum(
        1
        for answer in query_run.initial_answers
        if answer.provider_path is ProviderPath.OPENROUTER_SEARCH
    )
    material_claim_count = sum(
        answer.citation_coverage.material_claim_count for answer in query_run.initial_answers
    )
    agreement, position_movements = build_agreement_and_positions(
        initial_answers=query_run.initial_answers,
        debate_outputs=query_run.debate_outputs,
        final_synthesis=query_run.final_synthesis,
    )
    actual_cost_usd, actual_breakdown, cost_source = _actual_cost(query_run)
    return QueryRunResultResponse(
        query_run_id=query_run.query_run_id,
        status=query_run.status,
        correlation_id=query_run.correlation_id,
        model_slots=query_run.model_slots,
        cost_estimate=query_run.cost_estimate,
        elapsed_time_ms=_elapsed_time_ms(query_run),
        failed_steps=query_run.failed_steps,
        missing_steps=query_run.missing_steps,
        progress=_progress_model(query_run),
        partial_failure_notice=partial_failure_notice,
        provider_failure_notices=provider_failure_notices,
        result=ResultProjection(
            model_answers=query_run.initial_answers,
            debate_outputs=query_run.debate_outputs,
            final_synthesis=query_run.final_synthesis,
            agreement=agreement,
            position_movements=position_movements,
        ),
        result_generated_at_utc=datetime.now(UTC),
        demo_mode=demo_mode,
        live_count=live_count,
        local_count=local_count,
        material_claim_count=material_claim_count,
        actual_cost_usd=actual_cost_usd,
        actual_breakdown=actual_breakdown,
        cost_source=cost_source,
    )


def _actual_cost(
    query_run: QueryRun,
) -> tuple[Decimal, CostBreakdown | None, Literal["estimated", "measured"]]:
    """Actual cost incurred, for the receipt's est→actual reconciliation.

    Returns ``cost_source="measured"`` — with a cost computed from the REAL
    per-call token usage captured from the provider (P2) — only when EVERY
    contributing live call reported usage. Otherwise it returns the pre-run
    estimate tagged ``cost_source="estimated"``, and never fabricates usage:

    * A demo/simulation run makes no live calls, so there is no captured usage
      to measure from — it stays ``estimated`` (the estimate is exact anyway,
      because nothing was billed).
    * A live run is ``measured`` only when the whole run is cleanly captured:
      EVERY one of its initial slots COMPLETED on the ``OPENROUTER_SEARCH`` path
      AND reported usage, AND every live debate/synthesis call reported usage.
      This gate is deliberately STRICT — if any slot fell back to
      simulation/fallback or failed (a state we cannot distinguish from a
      billed-but-uncaptured call), or any live call omitted its usage, the run
      stays ``estimated``. It is the only way to guarantee that no billed call
      is silently omitted from a figure the UI presents as measured billing.
    """
    estimate = query_run.cost_estimate

    # --- STRICT honesty gate -------------------------------------------------
    model_slots = query_run.model_slots
    initial_answers = query_run.initial_answers
    initial_fully_captured = (
        bool(model_slots)
        and len(initial_answers) == len(model_slots)
        and all(
            answer.provider_path is ProviderPath.OPENROUTER_SEARCH
            and answer.status is InitialAnswerStatus.COMPLETED
            and answer.token_usage is not None
            for answer in initial_answers
        )
    )
    debate_captured = all(usage is not None for _, usage in query_run.debate_call_usages)
    synthesis_captured = all(usage is not None for usage in query_run.synthesis_call_usages)
    if not (initial_fully_captured and debate_captured and synthesis_captured):
        return estimate.estimated_cost_usd, estimate.breakdown, "estimated"

    # --- measured computation (guarded) --------------------------------------
    # Past the gate, every ``token_usage`` is present; the ``is None`` skips are
    # unreachable but keep the types narrow. The whole computation is wrapped so
    # a cost-arithmetic error (e.g. a Decimal overflow from a value that somehow
    # slipped the capture-time bound) can never crash the result endpoint.
    try:
        per_model_initial_named: list[tuple[str, str, Decimal]] = []
        for answer in sorted(initial_answers, key=lambda a: a.slot_number):
            usage = answer.token_usage
            if usage is None:
                continue
            per_model_initial_named.append(
                (
                    answer.model_id,
                    answer.display_name or answer.model_id,
                    measured_call_cost_usd(
                        model_id=answer.model_id,
                        prompt_tokens=usage.prompt_tokens,
                        completion_tokens=usage.completion_tokens,
                    ),
                )
            )

        debate_by_round: dict[int, Decimal] = {}
        for round_number, debate_usage in query_run.debate_call_usages:
            if debate_usage is None:
                continue
            debate_by_round[round_number] = debate_by_round.get(
                round_number, Decimal("0")
            ) + measured_call_cost_usd(
                model_id=settings.debate_model_id,
                prompt_tokens=debate_usage.prompt_tokens,
                completion_tokens=debate_usage.completion_tokens,
            )

        synthesis_cost = sum(
            (
                measured_call_cost_usd(
                    model_id=settings.synthesis_model_id,
                    prompt_tokens=synth_usage.prompt_tokens,
                    completion_tokens=synth_usage.completion_tokens,
                )
                for synth_usage in query_run.synthesis_call_usages
                if synth_usage is not None
            ),
            Decimal("0"),
        )

        breakdown = build_measured_breakdown(
            per_model_initial=per_model_initial_named,
            debate_by_round=debate_by_round,
            synthesis_cost=synthesis_cost,
        )
        return breakdown.total, breakdown, "measured"
    except (InvalidOperation, ArithmeticError, ValueError):
        return estimate.estimated_cost_usd, estimate.breakdown, "estimated"


def _initial_progress() -> list[QueryRunStageProgress]:
    return [
        QueryRunStageProgress(
            stage="estimate", state=StageState.COMPLETED, detail="Estimate accepted."
        ),
        QueryRunStageProgress(stage="initial_answers", state=StageState.PENDING),
        QueryRunStageProgress(stage="debate_round_1", state=StageState.PENDING),
        QueryRunStageProgress(stage="debate_round_2", state=StageState.PENDING),
        QueryRunStageProgress(stage="synthesis", state=StageState.PENDING),
    ]


def _set_stage_state(
    stages: list[QueryRunStageProgress],
    stage_name: str,
    stage_state: StageState,
    detail: str | None,
) -> None:
    for stage in stages:
        if stage.stage == stage_name:
            stage.state = stage_state
            stage.detail = detail
            return


def _running_stage_name(stages: list[QueryRunStageProgress]) -> str:
    for stage in stages:
        if stage.state is StageState.RUNNING:
            return stage.stage
    return "estimate"


def _mark_remaining_stages(query_run_id: UUID, stage_names: list[str]) -> None:
    for stage_name in stage_names:
        query_run_repository.update_status(
            query_run_id,
            stage_name=stage_name,
            stage_state=StageState.SKIPPED,
            detail="Not executed because an earlier stage failed or timed out.",
        )


def _progress_model(query_run: QueryRun) -> QueryRunProgress:
    return QueryRunProgress(
        current_stage=_running_stage_name(query_run.progress),
        stages=query_run.progress,
    )


def _should_stop(query_run_id: UUID) -> bool:
    try:
        return query_run_repository.get(query_run_id).status is QueryRunStatus.CANCELLED
    except KeyError:
        return True


def _elapsed_time_ms(query_run: QueryRun) -> int:
    if query_run.started_at is None:
        return 0
    elapsed = query_run.updated_at - query_run.started_at
    return max(0, round(elapsed.total_seconds() * 1000))
