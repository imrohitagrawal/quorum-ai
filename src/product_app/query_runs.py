"""Query run HTTP API: request/response schemas, routes, rate limiting.

The ``query_api`` component (``docs/20-architecture.md``): FastAPI routes,
request/response schemas, and the two in-process rate limiters. The
``orchestration`` and ``persistence`` components — the run state machine,
the in-memory repository, and the pipeline that executes a run — live in
``product_app.query_run_orchestration`` (#303) and are re-exported here so
every pre-existing ``from product_app.query_runs import ...`` keeps working
unchanged.
"""

from __future__ import annotations

import logging
import time as _time_module
from threading import BoundedSemaphore, RLock, Thread
from typing import Annotated, Self
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator

from product_app.auth import SessionContext, enforce_csrf, require_session
from product_app.config import RuntimeEnvironment, settings
from product_app.costs import (
    CostConfirmation,
    CostEstimate,
    CostGuardrailDecision,
    CostThresholdAction,
    cost_estimation_service,
)
from product_app.feedback_store import ChargeOutcome
from product_app.model_slots import ModelSlot, model_slot_event_recorder
from product_app.providers import InitialModelAnswer
from product_app.query_run_orchestration import _EVALUATION_MEMO_MAX as _EVALUATION_MEMO_MAX
from product_app.query_run_orchestration import (
    _INITIAL_ANSWER_POOL_SIZE as _INITIAL_ANSWER_POOL_SIZE,
)
from product_app.query_run_orchestration import (
    _JUDGE_INFLIGHT_WAIT_SECONDS as _JUDGE_INFLIGHT_WAIT_SECONDS,
)
from product_app.query_run_orchestration import (
    _JUDGE_VERDICT_MEMO_MAX as _JUDGE_VERDICT_MEMO_MAX,
)
from product_app.query_run_orchestration import (
    _MAX_CONCURRENT_RUNS as _MAX_CONCURRENT_RUNS,
)
from product_app.query_run_orchestration import (
    _SYNTHESIS_POOL_SIZE as _SYNTHESIS_POOL_SIZE,
)

# NOTE ON THE BLOCK BELOW (#303): every name is imported from
# ``query_run_orchestration`` using the ``import NAME as NAME`` form — the
# explicit PEP 484 re-export idiom ruff's F401 and mypy's
# ``--no-implicit-reexport`` both treat as intentional. Some of these ARE
# called directly by the route handlers further down this file (e.g.
# ``query_run_repository``, ``_result_response``, ``_run_semaphore``); most
# are NOT referenced anywhere in this module's own code and exist purely so
# every pre-existing ``from product_app.query_runs import <name>`` /
# ``query_runs.<name>`` (55 files at the time of the split) keeps resolving
# without an import-path change. Deliberately not split into two commented
# sub-blocks by usage: ``ruff --fix`` (isort) re-merges same-module imports
# into one alphabetical group on every run regardless of blank lines or
# comments between them, so a positional split does not survive `make
# format` — an earlier version of this file tried exactly that and the next
# format run silently interleaved the two groups.
from product_app.query_run_orchestration import ALLOWED_TRANSITIONS as ALLOWED_TRANSITIONS
from product_app.query_run_orchestration import (
    QUERY_RUN_ACTIVE_TTL as QUERY_RUN_ACTIVE_TTL,
)
from product_app.query_run_orchestration import (
    QUERY_RUN_TERMINAL_TTL as QUERY_RUN_TERMINAL_TTL,
)
from product_app.query_run_orchestration import TERMINAL_STATUSES as TERMINAL_STATUSES
from product_app.query_run_orchestration import (
    ActiveQueryRunExistsError as ActiveQueryRunExistsError,
)
from product_app.query_run_orchestration import BillableStage as BillableStage
from product_app.query_run_orchestration import BillingSnapshot as BillingSnapshot
from product_app.query_run_orchestration import (
    InMemoryQueryRunRepository as InMemoryQueryRunRepository,
)
from product_app.query_run_orchestration import (
    InvalidQueryRunTransitionError as InvalidQueryRunTransitionError,
)
from product_app.query_run_orchestration import QueryRun as QueryRun
from product_app.query_run_orchestration import (
    QueryRunEvaluationProjection as QueryRunEvaluationProjection,
)
from product_app.query_run_orchestration import QueryRunProgress as QueryRunProgress
from product_app.query_run_orchestration import (
    QueryRunResultResponse as QueryRunResultResponse,
)
from product_app.query_run_orchestration import (
    QueryRunStageProgress as QueryRunStageProgress,
)
from product_app.query_run_orchestration import QueryRunStatus as QueryRunStatus
from product_app.query_run_orchestration import ResultProjection as ResultProjection
from product_app.query_run_orchestration import StageBillingState as StageBillingState
from product_app.query_run_orchestration import StageState as StageState
from product_app.query_run_orchestration import (
    _abandon_unstarted_run as _abandon_unstarted_run,
)
from product_app.query_run_orchestration import _actual_cost as _actual_cost
from product_app.query_run_orchestration import (
    _degrade_run_for_deadline as _degrade_run_for_deadline,
)
from product_app.query_run_orchestration import (
    _elapsed_time_ms as _elapsed_time_ms,
)
from product_app.query_run_orchestration import _estimate_reasons as _estimate_reasons
from product_app.query_run_orchestration import (
    _evaluate_terminal_run as _evaluate_terminal_run,
)
from product_app.query_run_orchestration import _evaluation_memo as _evaluation_memo
from product_app.query_run_orchestration import (
    _evaluation_memo_clear_for_tests as _evaluation_memo_clear_for_tests,
)
from product_app.query_run_orchestration import (
    _evaluation_memo_lock as _evaluation_memo_lock,
)
from product_app.query_run_orchestration import (
    _evaluation_memo_store as _evaluation_memo_store,
)
from product_app.query_run_orchestration import (
    _evaluation_projection as _evaluation_projection,
)
from product_app.query_run_orchestration import (
    _EvaluationMemoKey as _EvaluationMemoKey,
)
from product_app.query_run_orchestration import _execute_query_run as _execute_query_run
from product_app.query_run_orchestration import (
    _execute_query_run_safely as _execute_query_run_safely,
)
from product_app.query_run_orchestration import (
    _execute_query_run_with_semaphore_release as _execute_query_run_with_semaphore_release,
)
from product_app.query_run_orchestration import (
    _initial_answer_pool as _initial_answer_pool,
)
from product_app.query_run_orchestration import _initial_progress as _initial_progress
from product_app.query_run_orchestration import _judge_inflight as _judge_inflight
from product_app.query_run_orchestration import _judge_memo_lock as _judge_memo_lock
from product_app.query_run_orchestration import (
    _judge_memo_touch as _judge_memo_touch,
)
from product_app.query_run_orchestration import (
    _judge_status_for as _judge_status_for,
)
from product_app.query_run_orchestration import (
    _judge_verdict_memo as _judge_verdict_memo,
)
from product_app.query_run_orchestration import (
    _judge_verdict_memo_clear_for_tests as _judge_verdict_memo_clear_for_tests,
)
from product_app.query_run_orchestration import _JudgeOutcome as _JudgeOutcome
from product_app.query_run_orchestration import (
    _log_estimate_accuracy as _log_estimate_accuracy,
)
from product_app.query_run_orchestration import (
    _mark_remaining_stages as _mark_remaining_stages,
)
from product_app.query_run_orchestration import _MemoisedRunJudge as _MemoisedRunJudge
from product_app.query_run_orchestration import (
    _persist_run_evaluation as _persist_run_evaluation,
)
from product_app.query_run_orchestration import (
    _persist_terminal_run as _persist_terminal_run,
)
from product_app.query_run_orchestration import _progress_model as _progress_model
from product_app.query_run_orchestration import (
    _reconcile_run_billing as _reconcile_run_billing,
)
from product_app.query_run_orchestration import _record_run_billing as _record_run_billing
from product_app.query_run_orchestration import (
    _request_path_judge as _request_path_judge,
)
from product_app.query_run_orchestration import _result_response as _result_response
from product_app.query_run_orchestration import _run_semaphore as _run_semaphore
from product_app.query_run_orchestration import (
    _running_stage_name as _running_stage_name,
)
from product_app.query_run_orchestration import (
    _set_stage_state as _set_stage_state,
)
from product_app.query_run_orchestration import _should_stop as _should_stop
from product_app.query_run_orchestration import (
    _stage_captured as _stage_captured,
)
from product_app.query_run_orchestration import (
    _synthesis_pool as _synthesis_pool,
)
from product_app.query_run_orchestration import (
    _validated_model_slots as _validated_model_slots,
)
from product_app.query_run_orchestration import _void_run_billing as _void_run_billing
from product_app.query_run_orchestration import (
    provider_execution_service as provider_execution_service,
)
from product_app.query_run_orchestration import (
    query_run_repository as query_run_repository,
)
from product_app.safety import SafetyAcknowledgement, SafetyWarning, safety_warning_policy
from product_app.synthesis import FINAL_SYNTHESIS_MAX_CHARS

router = APIRouter(prefix="/v1/query-runs", tags=["query-runs"])

logger = logging.getLogger(__name__)


# SEC-C/H7: server-side query text length must align with the frontend
# ``<textarea maxlength="20000">``. The previous 8_000 cap caused a
# silent rejection at the cost-estimation layer for legitimate
# long-form research queries (5K–20K chars). The cost guardrail
# ($0.25 hard cap) already prevents runaway spend, so a generous
# length limit is safe.
_QUERY_TEXT_MAX_LENGTH = 20_000


#: WP-G2 (F-10): how long each ``context`` value may be. Both are DERIVED from
#: what this application itself can have produced, not picked:
#:
#:  * ``prior_question`` IS a previous ``query_text``, so nothing longer than
#:    the query-text cap could ever have been accepted in the first place;
#:  * ``prior_synthesis`` IS a previous final synthesis, so its ceiling is
#:    ``FINAL_SYNTHESIS_MAX_CHARS`` — owned by ``synthesis.py``, which is where
#:    the caps that bound it live. It is deliberately NOT derived from
#:    ``settings.cost_synthesis_sections``: that is an env-overridable PRICING
#:    knob, and retuning it would silently narrow this public field below what
#:    the synthesis stage can still emit.
#:
#: Before this, both were ``Any`` and unbounded (#125): a non-string raised
#: ``AttributeError`` inside ``costs.py`` — an unhandled 500 on the public API —
#: and an arbitrarily long string was concatenated into the system prompt and
#: priced into the guardrail bound.
_CONTEXT_PRIOR_QUESTION_MAX_LENGTH = _QUERY_TEXT_MAX_LENGTH
_CONTEXT_PRIOR_SYNTHESIS_MAX_LENGTH = FINAL_SYNTHESIS_MAX_CHARS
_CONTEXT_MAX_LENGTHS = {
    "prior_question": _CONTEXT_PRIOR_QUESTION_MAX_LENGTH,
    "prior_synthesis": _CONTEXT_PRIOR_SYNTHESIS_MAX_LENGTH,
}


def _check_context(ctx: dict[str, str | None] | None) -> None:
    """Validate a ``context`` mapping, or raise ``ValueError``.

    A module-level function rather than a base-class method because the
    ``/warnings`` probe (``QueryRunWarningsRequest``) is NOT a
    ``_QueryRunRequestBase`` and must apply exactly these rules (issue #155):
    a probe that accepts what create rejects hands the client advice it
    cannot act on. Pydantic v2 validators are not inherited by assignment,
    so sharing the callable is the only way to guarantee one implementation
    rather than two copies that drift.
    """
    if ctx is None:
        return
    allowed = set(_CONTEXT_MAX_LENGTHS)
    extra = set(ctx.keys()) - allowed
    if extra:
        raise ValueError(
            f"context may only contain {sorted(allowed)}; unexpected keys: {sorted(extra)}"
        )
    for key, value in ctx.items():
        if value is None:
            continue
        limit = _CONTEXT_MAX_LENGTHS[key]
        if len(value) > limit:
            raise ValueError(f"context.{key} may be at most {limit} characters; got {len(value)}")


class _QueryRunRequestBase(BaseModel):
    """The fields that decide what a run COSTS.

    WP-G2 (F-10): the estimate body and the create body must carry every one of
    these, or ``/estimate`` quotes a price that ``POST /v1/query-runs`` does not
    charge. The user then confirms a number that never matches what the run
    reserves, and the confirmation loop cannot be escaped. They drifted exactly
    that way — ``context`` was on create only — so they now share one base and
    a drift test pins it (``tests/unit/test_context_carry.py``).
    """

    query_text: str = Field(min_length=1, max_length=_QUERY_TEXT_MAX_LENGTH)
    model_slots: list[str] = Field(min_length=1)
    # L2: optional per-slot web-search opt-in. Same length as
    # ``model_slots`` when provided. ``None`` (the default) means
    # "use the per-slot default" — which is search-enabled for the
    # default four-slot demo run.
    slot_search: list[bool] | None = None
    # L4: optional follow-up context from a previous query run. ``None``
    # (default) means no prior context — a fresh query. Values are ``str``,
    # not ``Any``: a wrong type is a 422 from the edge, never a 500 from
    # deep inside the cost model (#125).
    #
    # A per-key ``None`` stays accepted. It parsed before this change and every
    # consumer is already None-safe (``costs.py`` does ``or ""``,
    # ``providers.py`` guards on truthiness), so rejecting it would break a
    # working client to fix a different bug (adversarial review, WP-G2).
    context: dict[str, str | None] | None = Field(default=None)

    @model_validator(mode="after")
    def _validate_context(self) -> Self:
        _check_context(self.context)
        return self


class QueryRunEstimateRequest(_QueryRunRequestBase):
    pass


class QueryRunEstimateResponse(BaseModel):
    correlation_id: str
    cost_estimate: CostEstimate
    model_slots: list[ModelSlot]
    reasons: list[str]


class QueryRunCreateRequest(_QueryRunRequestBase):
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


class QueryRunWarningsRequest(BaseModel):
    """The probe half of the documented probe-then-create flow.

    Every constraint here MUST match ``_QueryRunRequestBase``'s. A field the
    probe is STRICTER about is a request the client cannot ask about but can
    submit; one it is LAXER about is advice the create route will refuse.
    Both are the same "unbreakable loop" defect issue #155 exists to close,
    and adversarial review found two of them still open here:

    * ``query_text`` was capped at 8,000 while create allows
      ``_QUERY_TEXT_MAX_LENGTH`` (20,000). Measured: a benign 9,600-character
      query got 422 from the probe and 202 from create, so a client in that
      range could not probe at all.
    * ``context`` had no validator, so the probe answered 200 for unknown keys
      and over-long values that create rejects — and accepted a 20 MB body.
    """

    query_text: str = Field(min_length=1, max_length=_QUERY_TEXT_MAX_LENGTH)
    #: Issue #155. Same shape as ``QueryRunCreateRequest.context`` on purpose:
    #: the probe must be able to describe the SAME request the client is about
    #: to create.
    #:
    #: Optional and defaulted, so a pre-#155 client that omits it is
    #: unaffected — it simply gets the query-text-only answer it got before.
    context: dict[str, str | None] | None = Field(default=None)

    @model_validator(mode="after")
    def _validate_context(self) -> Self:
        # The SAME callable the create route validates with, not a copy of
        # its rules — a copy is what drifts.
        _check_context(self.context)
        return self


class QueryRunWarningsResponse(BaseModel):
    warnings: list[SafetyWarning]


# C9: per-IP rate limiter on ``/v1/session``. Each new session mints a
# new account id; without a limiter, a script can create thousands of
# sessions per second and bloat the in-memory ``session_repository``.
# The limiter is a simple token bucket: 10 requests per IP per minute
# (tightened from 30, issue #100 §2.4 — server-load/availability
# protection against a scripted flood; a DIFFERENT concern from the
# durable per-IP daily session-MINT cap in ``auth.py``, which closes
# the dollar-drain problem this limiter never addressed). 429 is
# returned when the bucket is empty.
class _InMemoryIpRateLimiter:
    """Naive per-IP token bucket. Single-process only.

    For multi-instance deployments, swap this for a Redis-backed
    limiter. The interface (``allow(ip) -> bool``) is the same so the
    rest of the application does not change.
    """

    #: Default per-IP capacity/refill. Kept as class constants so the
    #: production posture (10/min) is pinned and greppable, but the
    #: instance seeds ``self.CAPACITY``/``self.REFILL_PER_MINUTE`` from
    #: them so a LOCAL-only override (Stage B / D0) can raise the bucket
    #: for the hermetic e2e lanes without touching production.
    CAPACITY = 10
    REFILL_PER_MINUTE = 10
    # SEC-H3: stale buckets are evicted after 5 minutes of full
    # capacity (refill window). Without this, a /16 IPv4 scan would
    # add 65K entries that never expire.
    STALE_BUCKET_SECONDS = 300.0

    def __init__(
        self,
        *,
        capacity: int | None = None,
        refill_per_minute: int | None = None,
    ) -> None:
        # Instance attributes shadow the class constants. ``allow()`` reads
        # ``self.CAPACITY``/``self.REFILL_PER_MINUTE``, so seeding these here
        # is what makes the override effective.
        self.CAPACITY = self.CAPACITY if capacity is None else capacity
        self.REFILL_PER_MINUTE = (
            self.REFILL_PER_MINUTE if refill_per_minute is None else refill_per_minute
        )
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


# Stage B / D0: seed the per-IP limiter from the LOCAL-only override when
# set, else keep the pinned production default (30/min). Both capacity and
# refill move together so an overridden bucket does not refill to N but cap
# at 30. The override is applied ONLY in LOCAL — belt-and-suspenders behind
# ``validate_production_environment()``, which additionally REFUSES TO START
# if the override is set in any non-LOCAL environment. So even if that
# startup guard were bypassed, a deployed limiter stays at 30/min.
_session_limit = (
    settings.session_rate_limit_per_minute
    if settings.runtime_environment is RuntimeEnvironment.LOCAL
    else None
)
_ip_rate_limiter = _InMemoryIpRateLimiter(
    capacity=_session_limit,
    refill_per_minute=_session_limit,
)


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
        # WP-G2 (F-10): the fix here is the ``context`` field on the shared
        # request base, NOT this line — with the field present, the old
        # ``getattr(payload, "context", None)`` would read the same value. It
        # is spelled as a plain attribute so the next reader cannot mistake a
        # defaulted lookup for a deliberate opt-out: that defaulted lookup is
        # what silently returned ``None`` for as long as the estimate body had
        # no such field, quoting a follow-up at the price of a fresh query.
        context=payload.context,
    )
    cost_estimation_service.record_guardrail_event(
        account_id=session.account_id,
        query_run_id=None,
        estimated_cost_usd=estimate.estimated_cost_usd,
        threshold_action=estimate.threshold_action,
        confirmed=False,
        # F-01: this is a preview, not a charge. Without this flag an
        # ALLOW-band estimate records an opening-charge type — since #376 that
        # is ``cost_guardrail_accepted_simulated`` on a live-execution-off
        # deployment, i.e. production, and ``cost_guardrail_accepted`` otherwise
        # — and both per-account spend guards count either. So one logical run
        # would be billed twice (once here, once at create) and an abandoned
        # preview billed for nothing.
        preview=True,
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
    # Issue #155: ``context`` reaches provider prompts, so it is scanned too.
    required_warnings = safety_warning_policy.required_warnings_for_query(
        payload.query_text, context=payload.context
    )
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
        context=payload.context,
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

    # C9 + F-01: reserve the in-flight run slot BEFORE anything that charges
    # the account or claims the account's single active-run slot. The capacity
    # check used to sit after ``query_run_repository.create`` and after the
    # ``cost_guardrail_accepted`` record, so a 503 left the caller billed for a
    # run whose worker was never started AND holding a non-terminal run that
    # nothing would ever finish — a permanent ACTIVE_QUERY_EXISTS lockout on
    # top of the phantom charge (both MEASURED). The non-blocking
    # ``acquire(blocking=False)`` is intentional: we don't want to queue
    # requests and run them all sequentially if the process is already
    # saturated. The permit is held from here until
    # ``_execute_query_run_with_semaphore_release`` releases it at the end of
    # the run; every path that fails before the worker owns it releases it.
    #
    # The legacy/test path is synchronous and deliberately bypasses the
    # semaphore to keep unit-test determinism, so it reserves nothing.
    #
    # The permit is taken from a captured REFERENCE to the semaphore, not by
    # re-reading the module global at release time. A permit must always be
    # returned to the object it was taken from: if the global is ever swapped
    # (a test installing an isolated semaphore is the only real case), an
    # in-flight worker that re-read the global would credit its permit to the
    # wrong object — over-releasing one and permanently shrinking the other.
    capacity_permit: BoundedSemaphore | None = None
    if not session.legacy:
        semaphore = _run_semaphore
        if not semaphore.acquire(blocking=False):
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
        capacity_permit = semaphore

    try:
        return _start_reserved_query_run(
            payload=payload,
            session=session,
            model_slots=model_slots,
            cost_estimate=cost_estimate,
            cost_decision=cost_decision,
            capacity_permit=capacity_permit,
            # Issue #100 §2.8: the global-ceiling Sentry alert wants an
            # IP breakdown alongside account_id. Same extraction as
            # ``main.browser_session`` — no shared helper existed before
            # this, and adding one is out of scope for a one-field alert
            # payload.
            client_ip=(request.client.host if request.client else None),
        )
    except BaseException:
        # Nothing below took ownership of the permit (the worker thread only
        # owns it once ``Thread.start()`` has returned, and that is the last
        # statement in the helper), so release it here. ``BoundedSemaphore``
        # raises on an over-release, so a double release cannot pass silently.
        if capacity_permit is not None:
            capacity_permit.release()
        raise


def _start_reserved_query_run(
    *,
    payload: QueryRunCreateRequest,
    session: SessionContext,
    model_slots: list[ModelSlot],
    cost_estimate: CostEstimate,
    cost_decision: CostGuardrailDecision,
    capacity_permit: BoundedSemaphore | None,
    client_ip: str | None = None,
) -> QueryRunCreateResponse:
    """Create, bill and launch a run whose capacity permit is already held.

    Split out of :func:`create_query_run` so that ONE ``except BaseException``
    there covers every step between reserving the permit and handing it to the
    worker thread — including the 409 and the audit/billing writes — instead of
    a per-step ``try/finally`` ladder that a later edit can fall out of.

    ``capacity_permit`` is the semaphore the caller reserved from, or ``None``
    on the legacy/test path which reserves nothing. It is handed to the worker
    thread so the permit is returned to the object it came from.
    """
    try:
        query_run = query_run_repository.create(
            account_id=session.account_id,
            query_text=payload.query_text,
            model_slots=model_slots,
            cost_estimate=cost_estimate,
            context=payload.context,
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
    # Legacy/test path runs inline so the test suite can assert against
    # the final state synchronously. Production / cookie path runs in a
    # background thread that cannot block the request response.
    if session.legacy:
        charge = _record_run_billing(
            session=session, query_run=query_run, cost_decision=cost_decision, client_ip=client_ip
        )
        # Same three-way decision as the production path below. Kept in step
        # deliberately: a rail that only holds on one of the two paths is a rail
        # whose tests can pass while production overspends.
        if charge is ChargeOutcome.OVER_DAILY_CAP:
            _abandon_unstarted_run(query_run.query_run_id)
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "code": "COST_LIMIT_EXCEEDED",
                    "message": (
                        "Account has reached its daily spend cap; no further "
                        "queries can be accepted until the window resets."
                    ),
                },
            )
        if charge is ChargeOutcome.OVER_GLOBAL_CEILING:
            query_run = query_run_repository.mark_global_ceiling_reached(query_run.query_run_id)
        elif charge is ChargeOutcome.METERING_UNAVAILABLE:
            query_run = query_run_repository.mark_spend_metering_unavailable(query_run.query_run_id)
        _execute_query_run(query_run.query_run_id, session.account_id)
        query_run = query_run_repository.get(query_run.query_run_id)
        # Legacy/test path runs inline (no safety wrapper), so persist the
        # terminal run here. Idempotent with the production choke point.
        _persist_terminal_run(query_run.query_run_id)
        return _create_response_for(query_run)

    # The capacity permit was reserved by the caller. ``Thread.start()`` is the
    # ownership handover: until it returns nobody but this function can free
    # the permit, and once it returns the worker owns it and releases it in its
    # ``finally``. So everything that can fail is arranged around that one
    # statement — the response is built before it (a failure there must not
    # leave a running worker unaccounted for). Anything raising before the
    # handover propagates to the caller's handler, which returns the permit;
    # nothing after it can leak or double-release.
    #
    # WHY THE CHARGE MOVED AHEAD OF ``start()`` (issue #255, the spend race).
    # It used to be recorded strictly AFTER the handover, so that a run whose
    # worker never started could not be billed (F-01). But the worker is what
    # SPENDS, so a charge written after it starts cannot gate anything: the two
    # rails were read a whole request earlier in ``costs.estimate`` and nothing
    # re-tested them at the moment money was committed. MEASURED: 32 concurrent
    # runs booked 4.69x the $0.20 daily cap. The charge is now an ATOMIC
    # check-and-record (``try_record_run_charge``) placed BEFORE the handover,
    # so it precedes every dollar the worker can spend. F-01 is preserved by
    # the ``except`` below, which VOIDS the charge if the handover fails —
    # a compensating event, because the sink is append-only.
    response = _create_response_for(query_run)
    # The charge is INSIDE the try, not before it. Adversarial review pointed
    # out that everything between the durable insert and ``Thread.start()``
    # runs unprotected otherwise — including the in-memory ring append inside
    # ``try_record_run_charge`` — so an exception there would leave a charge on
    # the books for a run that never started, with nothing to void it. Not
    # demonstrated reachable; closed anyway, because it costs one indent.
    try:
        charge = _record_run_billing(
            session=session, query_run=query_run, cost_decision=cost_decision, client_ip=client_ip
        )
        if charge is ChargeOutcome.OVER_DAILY_CAP:
            # The cap was crossed between this run's estimate and its charge —
            # by another request for the same account that got there first.
            # Nothing was written and nothing has run, so refuse with the same
            # 402 the estimate-time check would have produced.
            _abandon_unstarted_run(query_run.query_run_id)
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "code": "COST_LIMIT_EXCEEDED",
                    "message": (
                        "Account has reached its daily spend cap; no further "
                        "queries can be accepted until the window resets."
                    ),
                },
            )
        if charge is ChargeOutcome.OVER_GLOBAL_CEILING:
            # The deployment-wide ceiling degrades rather than blocks. Mark the
            # stored run so the worker simulates the whole thing — the same
            # signal ``estimate`` sets when it sees the ceiling, read at the one
            # place that acts on it (``_execute_query_run``).
            query_run = query_run_repository.mark_global_ceiling_reached(query_run.query_run_id)
            response = _create_response_for(query_run)
        elif charge is ChargeOutcome.METERING_UNAVAILABLE:
            # ADR-0016: the ledger went untrustworthy between this run's
            # estimate and its charge. Same degrade, different cause — and a
            # separate flag, so the run is never reported as having hit the
            # spend ceiling.
            query_run = query_run_repository.mark_spend_metering_unavailable(query_run.query_run_id)
            response = _create_response_for(query_run)
        Thread(
            target=_execute_query_run_with_semaphore_release,
            args=(query_run.query_run_id, session.account_id, capacity_permit),
            daemon=True,
        ).start()
    except HTTPException:
        # The 402 above. Nothing was charged on that path, so there is nothing
        # to void — and voiding would write a compensating event for a charge
        # that does not exist.
        raise
    except BaseException:
        # F-01: a run whose worker was never started must not be billed and
        # must not keep the account's single active-run slot — the same
        # failure class the 503 path above closes. ``Thread.start()`` raises
        # ``RuntimeError`` under thread exhaustion and during interpreter
        # shutdown. The charge is now written BEFORE this point, so there IS
        # something to un-bill: void it. The caller's handler returns the
        # capacity permit.
        _void_run_billing(session=session, query_run=query_run, reason="worker_never_started")
        _abandon_unstarted_run(query_run.query_run_id)
        raise
    return response


def _create_response_for(query_run: QueryRun) -> QueryRunCreateResponse:
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
    # Issue #155: discovery and enforcement MUST agree. Without ``context``
    # here, a client following the documented probe-then-create flow gets a
    # warning list that omits ``high_stakes``, acknowledges exactly what it
    # was told to, and is then refused 422 by the create route on a warning
    # it was never shown — an unbreakable loop.
    warnings = safety_warning_policy.required_warnings_for_query(
        payload.query_text, context=payload.context
    )
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
    # ``allow_terminal``: this handler is the party that just made the run
    # terminal, so its own stage stamp is the one post-terminal write that
    # belongs. Everything else the pipeline still tries to write is refused.
    query_run_repository.update_status(
        query_run_id,
        stage_name=_running_stage_name(cancelled.progress),
        stage_state=StageState.SKIPPED,
        detail="Cancelled by the user.",
        allow_terminal=True,
    )
    refreshed = query_run_repository.get(query_run_id)
    return _result_response(refreshed)


# -- pipeline ----------------------------------------------------------------
