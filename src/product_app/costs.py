"""Cost estimation and threshold guardrails.

Three thresholds:

* ``estimated_cost_usd <= 0.15``  → ``ALLOW`` (submit freely).
* ``0.15 < estimated_cost_usd <= 0.25``  → ``REQUIRE_CONFIRMATION`` (caller
  must echo back the ``confirmation_token`` from the estimate response).
* ``estimated_cost_usd > 0.25``  → ``BLOCK`` (cannot run, regardless of
  confirmation).

Confirmation tokens are bound to the ``account_id`` that requested them
and carry an explicit expiry. Replay across accounts is rejected; replay
after expiry is rejected; replay with a mismatched ``estimated_cost_usd``
is rejected.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
import warnings
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from enum import StrEnum
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from product_app.catalog_fetcher import _FALLBACK_CATALOG
from product_app.config import settings
from product_app.feedback_store import record_event as _record_feedback_event
from product_app.model_slots import DEFAULT_MODEL_IDS, ModelSlot, openrouter_model_catalog_service

_log = logging.getLogger(__name__)

SOFT_THRESHOLD_USD = Decimal("0.15")
HARD_LIMIT_USD = Decimal("0.25")
#: Per-account daily cap (USD). Defense-in-depth: the per-call
#: thresholds catch immediate over-spend, the in-memory cumulative
#: check catches rapid-fire same-window over-spend, but neither bounds
#: long-term accumulation. A patient attacker could trickle out one
#: $0.001 query per minute and accumulate unbounded daily cost. The
#: daily cap reads from the durable SQLite feedback store (not the
#: bounded in-memory ring buffer) and rejects any estimate that, when
#: added to the account's 24h spend, would exceed this value.
#:
#: THE MONEY ENVELOPE (recorded decision, F-01).
#: Until F-01 the meter behind this cap counted every run twice — ``POST
#: /v1/query-runs/estimate`` recorded ``cost_guardrail_accepted`` for a run
#: that had not started — so the cap admitted only HALF the runs its dollar
#: value pays for. MEASURED on the default 4-slot mix ($0.0261/run):
#: 3 completed runs before the 402, against a meter reading $0.1827 of which
#: only ~$0.078 was real spend. Fixing the meter therefore MOVES the real
#: per-account 24h envelope, ~$0.078 -> ~$0.183 (3 -> 7 runs), which is a
#: money decision rather than a side effect of a bug fix.
#:
#: WP-D RE-MEASURED AND RATIFIED (operator-approved). The figures above are
#: F-01's and are kept for the audit trail; they are NOT current. The default
#: mix now prices at **$0.0317/run**, so this cap admits **6 runs**, not the
#: 7 F-01 measured. Two honest corrections moved it: the
#: ``google/gemini-2.5-flash`` fallback output price (0.0012 -> 0.0025,
#: measured against the live public catalog) and pricing the round-2 debate
#: prompt's prior-critique input, without which ``max_cost_usd`` was not a
#: true ceiling. Note the 8 -> 6 drop predates WP-D: the branch's earlier
#: ``config.py`` cap raise (700->2000, 800->3000) already put the real figure
#: at 6, and a stale test pin had been hiding it. This cap STAYS at 0.20 —
#: raising it to hold the run count constant would be counter-tuning a safety
#: weight to preserve a metric. Pinned by
#: ``tests/integration/test_query_run_cost_guardrails.py::
#: test_daily_cap_admits_the_number_of_runs_its_dollar_value_pays_for``.
#:
#: The decision that ships with F-01 is to LEAVE this at 0.20, because 0.20 was
#: never derived from watching production spend and so was never calibrated
#: against the inflated meter. ``git log -S 'DAILY_CAP_USD = Decimal("0.20")'``
#: gives commit 9c50239 ("cost: raise daily cap to $0.20 so confirmation band
#: is reachable"): the value comes from an ORDERING constraint —
#: ``SOFT_THRESHOLD_USD < DAILY_CAP_USD < HARD_LIMIT_USD``, or the
#: require-confirmation band is unreachable and the confirmation flow becomes
#: dead code. VERIFIED the other way: setting this back to 0.10 to preserve
#: the pre-fix real envelope re-breaks
#: ``test_high_cost_query_requires_confirmation_before_creation`` and
#: ``test_high_cost_query_accepts_matching_confirmation_token`` — exactly the
#: regression 9c50239 fixed. Lowering the envelope, if the operator wants that,
#: therefore has to move the whole three-threshold ladder, not this constant
#: alone.
#:
#: WHAT THIS IS NOT. The envelope above is PER ACCOUNT, and an account is a
#: free, self-issued identity: ``GET /v1/session`` mints one on demand
#: (``main.browser_session`` -> ``auth.issue_or_resume_session``), no payment
#: instrument, no email, no proof of anything. So this constant is NOT a bound
#: on what the deployment can be made to spend — the deployment-level bound is
#: (accounts an attacker can mint) x this value, and the only thing limiting
#: the first factor is the per-IP session bucket
#: (``query_runs._InMemoryIpRateLimiter.CAPACITY`` = 30/min, per IP, in-process
#: only). Read as an operator ratification, "$0.20" is the per-user blast
#: radius of an honest mistake, not the day's worst case. The deployment-level
#: bound is ``GLOBAL_DAILY_CEILING_USD`` below (issue #100) — a SEPARATE
#: control layered on top of this one, not a replacement for it.
#:
#: The envelope is now asserted, not emergent:
#: ``tests/integration/test_query_run_cost_guardrails.py::
#: test_daily_cap_admits_the_number_of_runs_its_dollar_value_pays_for``
#: fails if either the meter or this value moves.
DAILY_CAP_USD = Decimal("0.20")

#: Deployment-wide spend ceiling (USD), summed across ALL accounts, per
#: rolling 24 hours. Issue #100, operator-decided 2026-08-01 (locked, see
#: ``gh issue view 100`` comments) — this is a business-policy figure, not
#: derived from any ordering constraint the way ``DAILY_CAP_USD`` is.
#:
#: BEHAVIOUR AT THE CEILING IS A DEGRADE, NOT A BLOCK. Unlike every other
#: threshold in this module, reaching this ceiling does not change
#: ``threshold_action`` and never produces a 402 — ``CostEstimate.
#: global_ceiling_reached`` is a separate, orthogonal signal that
#: ``_execute_query_run`` (``query_runs.py``) reads to force the WHOLE run
#: into local simulation (never a per-slot substitution — see #171, whose
#: fix this reuses rather than re-implementing: forcing the local
#: ``openrouter_key`` to empty for a ceiling-tripped run routes through the
#: exact same, already-tested "no live key" path every slot already falls
#: back to when the deployment has none configured).
#:
#: METER HONESTY. A ceiling-tripped run's own cost estimate must NEVER be
#: recorded as ``cost_guardrail_accepted`` — see
#: ``record_guardrail_event``'s ``cost_guardrail_degraded_to_simulation``
#: branch and ``FeedbackStore.global_daily_spend``'s docstring. If it were,
#: every subsequent degraded run would keep pushing the meter further past
#: the ceiling with money that was never spent, and the 24h window would
#: never roll over on real spend.
#:
#: RACE, ACCEPTED BY DESIGN (same posture as the per-account cumulative
#: guard above, which has an identical unsynchronised read-then-act window):
#: two concurrent requests can both read "under $5" before either one's
#: spend is recorded, and both proceed live. Worst-case overshoot is bounded
#: by ``query_runs._MAX_CONCURRENT_RUNS`` (16) x ``HARD_LIMIT_USD`` (0.25) =
#: $4.00 in the extreme case every in-flight slot races the same instant —
#: not unbounded, and not worth a distributed lock for a demo-safety rail
#: that degrades rather than blocks.
GLOBAL_DAILY_CEILING_USD = Decimal("5.00")

#: Minimum gap between two "the daily cap is not being enforced" ERROR records
#: (P1 / issue #101).
#:
#: The bypass is re-evaluated on EVERY estimate — one per
#: ``POST /v1/query-runs/estimate`` and one per run submission — so an
#: unconditional log would emit thousands of identical lines an hour and bury
#: the signal it exists to raise. Logging only once per process fails the other
#: way: the record would land at the first request after boot and then go quiet,
#: so an operator who arrives an hour into the outage sees a *silent* log for a
#: guard that is still off. One record per minute is the middle: bounded at
#: <=1440/day (nothing, next to the request log), and frequent enough that an
#: alert rule on a multi-minute evaluation window keeps re-firing for as long as
#: the store is down.
#:
#: The window is measured against ``time.monotonic()``, NOT the wall clock. A
#: wall clock can step backwards (NTP correction, VM clock resync, snapshot
#: restore); ``now - last`` then goes negative and stays under the interval
#: until real time has caught the step back up, so the "keeps re-firing"
#: property above would not hold. MEASURED on the wall-clock version: a 1 h
#: backward step followed by 1 h of traffic emitted 1 record where 61 were due
#: — the only signal a bypassed money guard has, silenced for an hour by a
#: clock event unrelated to the fault. Cardinality (both the ordinary window
#: and the backward step) is asserted in
#: ``tests/integration/test_feedback_store_locked_database.py::
#: test_missing_store_skips_the_daily_cap_and_logs_it_once_per_window`` and
#: ``::test_a_backward_wall_clock_step_does_not_silence_the_bypass_error``.
DAILY_CAP_BYPASS_LOG_INTERVAL_S = 60.0

#: Quantization step for ``CostEstimate.estimated_cost_usd``. The
#: internal arithmetic runs at full Decimal precision, but every
#: value that leaves the cost service (estimate response, run
#: result, history list, BLOCK 402 body) is rounded to 4 dp so the
#: UI never displays trailing IEEE-754 noise like
#: ``0.01344254000000000000046920801``. ROUND_HALF_UP matches the
#: typical "show 2/4 dp" consumer expectation.
COST_DISPLAY_QUANTUM = Decimal("0.0001")

#: Per-1K-token prices (USD) used when a model id is absent from whatever
#: ``price_index()`` currently returns. That is NOT only "the catalog is
#: down": a full outage falls back to the static ``_FALLBACK_CATALOG``,
#: which has a row for every shipped default, so this floor does not fire
#: for a default model in that case. The real trigger a shipped default can
#: hit is narrower — the LIVE catalog fetch succeeds and returns a non-empty
#: list that happens not to include this id (a live id renamed or dropped
#: upstream; see ``default_model_ids()``'s own "stale" docstring in
#: ``model_slots.py``) — since a successful live fetch is used as-is, with
#: no union against the fallback catalog. A shipped default never hits this
#: via total outage, per
#: ``test_every_shipped_default_model_has_a_fallback_catalog_row``. The
#: catalog is the authoritative source for pricing; this is the last-resort
#: floor beneath it.
#:
#: #151: DERIVED, not guessed — the max real input/output price across the
#: four shipped ``DEFAULT_MODEL_IDS``, read from ``_FALLBACK_CATALOG``. A
#: hand-picked constant (the pre-#151 value was 0.0008/0.002) over-charged
#: three of the four shipped models by up to 16x while UNDER-charging
#: anthropic/claude-haiku-4.5 by 25% — the unsafe direction for a spend cap,
#: since the daily cap is enforced against this same estimate. Taking the
#: max per column is conservative in the safe direction for every model this
#: deployment actually ships, by construction rather than by tuning.
_DEFAULT_PRICE_PER_1K_INPUT = max(
    entry.input_price_per_1k for entry in _FALLBACK_CATALOG if entry.model_id in DEFAULT_MODEL_IDS
)
_DEFAULT_PRICE_PER_1K_OUTPUT = max(
    entry.output_price_per_1k for entry in _FALLBACK_CATALOG if entry.model_id in DEFAULT_MODEL_IDS
)


#: Chars-per-token conversion used to turn query text length into a
#: token count (the industry ~4-chars/token rule of thumb).
CHARS_PER_TOKEN = Decimal(4)

#: issue #16: the estimate is a realistic per-call token model. The old
#: ``QUERY_COST_PER_1K_CHARS_USD`` / ``PER_CHAR_PROCESSING_USD`` synthetic
#: per-character charges (and the flat ``DEBATE_FIXED_COST_USD`` /
#: proportional inner-call terms) are gone: they were tuned to push long
#: queries into the guardrail bands, not to model real token economics,
#: and they under-priced the debate + synthesis calls that actually
#: dominate cost. Every term is now ``price_per_1k × tokens``, where the
#: token counts come from :data:`product_app.config.settings` (see the
#: ``cost_*_tokens`` knobs). Debate is priced on
#: ``settings.debate_model_id`` and synthesis on
#: ``settings.synthesis_model_id`` — the models those calls actually use —
#: not a proxy rate borrowed from the four slot models.

CONFIRMATION_TOKEN_TTL = timedelta(minutes=5)


class CostThresholdAction(StrEnum):
    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    BLOCK = "block"


class CostLineByModel(BaseModel):
    model_id: str
    display_name: str
    usd: Decimal = Field(ge=Decimal("0"))
    #: Discriminator so consumers distinguish the pseudo "Debate + synthesis"
    #: row from a real model row without matching the magic ``model_id``.
    #: ``"model"`` for the four model rows, ``"synthesis"`` for the writer,
    #: ``"judge"`` for a fired-and-priced Layer-B judge call (issue #110).
    kind: str = "model"


class CostLineByStage(BaseModel):
    #: One of ``initial_answers`` | ``debate_round_1`` | ``debate_round_2`` |
    #: ``synthesis`` — the same vocabulary as ``progress.stages[].stage`` (see
    #: ``query_runs._initial_progress``) so a UI can join the two directly —
    #: PLUS an optional ``"judge"`` row (issue #110) that has no progress-stage
    #: counterpart: the Layer-B judge is a request-path advisory call, never a
    #: pipeline stage. Present only in a MEASURED breakdown, only when a
    #: configured judge fired and reported usage. A UI that joins ``by_stage``
    #: against ``progress.stages`` by key simply has no match for it; it must
    #: not be dropped from ``total``.
    stage: str
    usd: Decimal = Field(ge=Decimal("0"))


class CostBreakdown(BaseModel):
    """Itemized cost partition for screen 03 (cost gate) and the 05 receipt.

    The estimate is partitioned two independent ways — ``by_model`` and
    ``by_stage`` — from the *same* underlying arithmetic that produces
    ``total``. Both lists re-sum to ``total`` exactly after quantization
    (the reconciliation invariant): every line is apportioned to
    :data:`COST_DISPLAY_QUANTUM` by :meth:`_reconcile_usd_lines` using a
    sign-safe largest-remainder rule, so every line is ``>= 0`` and the
    lines sum to ``total`` exactly.
    """

    by_model: list[CostLineByModel]
    by_stage: list[CostLineByStage]
    total: Decimal = Field(ge=Decimal("0"))


class CostEstimate(BaseModel):
    #: Realistic point estimate of the typical charge — the headline "≈ $X"
    #: shown to the user. Calibrated to track measured actual (issue #16).
    estimated_cost_usd: Decimal = Field(ge=Decimal("0"))
    currency: str = "USD"
    threshold_action: CostThresholdAction
    confirmation_token: str | None
    reasons: list[str]
    #: Fail-safe upper bound — the "up to $Y" figure. Prices the initial-answer
    #: output at the enforced ``settings.initial_answer_max_tokens`` cap, so
    #: (because the live initial calls are capped at that value) real cost never
    #: exceeds it. The cost guardrail (BLOCK / REQUIRE_CONFIRMATION / daily cap)
    #: is evaluated against THIS value, not the point estimate, so the rail
    #: fails safe (issue #16 rec #2/#3). Optional with a ``None`` default so
    #: pre-existing ``CostEstimate(...)`` constructions keep working; always >=
    #: ``estimated_cost_usd`` when ``estimate()`` sets it.
    max_cost_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    #: Itemized cost partition (by model AND by stage). Optional with a
    #: ``None`` default so pre-existing ``CostEstimate(...)`` constructions
    #: (tests, cancel path) keep working; ``estimate()`` always attaches a
    #: real breakdown to every returned estimate.
    breakdown: CostBreakdown | None = None
    #: Issue #100. Whether the deployment-wide $5/24h ceiling was already
    #: reached at estimate time. Orthogonal to ``threshold_action`` — the
    #: ceiling degrades to simulation, it never blocks, so this can be
    #: ``True`` alongside ``ALLOW`` or ``REQUIRE_CONFIRMATION``. Decided
    #: ONCE here (not re-checked at execute time) and persisted on the
    #: ``QueryRun`` so the run that actually executes, and the event that
    #: gets billed for it, can never disagree about which mode this run is
    #: in. Defaults ``False`` so pre-existing ``CostEstimate(...)``
    #: constructions keep working.
    global_ceiling_reached: bool = False


class CostConfirmation(BaseModel):
    estimated_cost_usd: Decimal
    confirmation_token: str


class CostGuardrailDecision(BaseModel):
    confirmed: bool
    reasons: list[str]


@dataclass(frozen=True)
class CostGuardrailEvent:
    event_type: str
    account_id: UUID
    query_run_id: UUID | None
    estimated_cost_usd: Decimal
    threshold_action: CostThresholdAction
    confirmed: bool


class InMemoryCostEventRecorder:
    MAX_EVENTS = 1024

    def __init__(self) -> None:
        self._events: list[CostGuardrailEvent] = []
        self._lock = RLock()

    def record(
        self,
        *,
        event_type: str,
        account_id: UUID,
        query_run_id: UUID | None,
        estimated_cost_usd: Decimal,
        threshold_action: CostThresholdAction,
        confirmed: bool,
    ) -> None:
        event = CostGuardrailEvent(
            event_type=event_type,
            account_id=account_id,
            query_run_id=query_run_id,
            estimated_cost_usd=estimated_cost_usd,
            threshold_action=threshold_action,
            confirmed=confirmed,
        )
        with self._lock:
            self._events.append(event)
            if len(self._events) > self.MAX_EVENTS:
                del self._events[: len(self._events) - self.MAX_EVENTS]
        _record_feedback_event(
            recorder="cost",
            event_type=event.event_type,
            account_id=event.account_id,
            query_run_id=event.query_run_id,
            payload=asdict(event),
        )

    def list_events(self) -> list[CostGuardrailEvent]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


@dataclass(frozen=True)
class _BoundToken:
    account_id: UUID
    query_run_id: UUID | None
    estimated_cost_usd: Decimal
    expires_at: datetime
    token: str


class CostEstimationService:
    """Pure cost estimation + token binding.

    Token generation mixes a 32-byte random secret with the bound
    ``account_id``, ``query_run_id``, ``estimated_cost_usd``, and expiry
    timestamp. The token is verifiable without database access, but it is
    also stored in an in-memory table so we can reject replay across
    accounts. The bound secret is held in process memory and never logged.
    """

    def __init__(
        self,
        *,
        binding_secret: str | None = None,
        now_provider: Callable[[], datetime] | None = None,
        monotonic_provider: Callable[[], float] | None = None,
    ) -> None:
        # C13: surface a warning when the binding secret is auto-
        # generated because ``QUORUM_TOKEN_SECRET`` is not set.
        # The auto-generated secret is a per-process value: every
        # restart rotates it, which invalidates every outstanding
        # confirmation token. In production this would also break
        # any multi-instance deployment (different processes
        # generate different secrets, so a token minted by one
        # process cannot be verified by another). The warning makes
        # the misconfiguration visible at startup instead of
        # surfacing as a confusing token-invalid error later.
        env_secret = os.environ.get("QUORUM_TOKEN_SECRET")
        if env_secret is None and binding_secret is None:
            warnings.warn(
                "QUORUM_TOKEN_SECRET is not set; generating a random "
                "per-process binding secret. Confirmation tokens will "
                "not survive a restart and any multi-instance deployment "
                "will fail. Set QUORUM_TOKEN_SECRET in the environment to "
                "fix this.",
                stacklevel=2,
            )
        self._binding_secret = (binding_secret or env_secret or secrets.token_hex(32)).encode()
        self._tokens: dict[str, _BoundToken] = {}
        self._lock = RLock()
        #: Monotonic reading at the last "daily cap not enforced" ERROR, for
        #: the rate limit described on ``DAILY_CAP_BYPASS_LOG_INTERVAL_S``. A
        #: MONOTONIC float, not a wall-clock ``datetime``: a backward wall-clock
        #: step must not be able to silence a money guard's only signal. Per
        #: instance rather than module-global so the app's one singleton keeps
        #: one window while a test's throwaway service starts from silence.
        self._cap_bypass_logged_at: float | None = None
        if now_provider is None:
            self._now: Callable[[], datetime] = lambda: datetime.now(UTC)
        else:
            self._now = now_provider
        #: Separate seam from ``now_provider`` on purpose. ``_now`` drives token
        #: TTL/expiry, which needs a real calendar timestamp; the suppression
        #: window only needs elapsed seconds and must be immune to clock steps.
        #: Injectable so the cardinality tests can drive elapsed time without
        #: sleeping.
        self._monotonic: Callable[[], float] = (
            time.monotonic if monotonic_provider is None else monotonic_provider
        )

    def estimate(
        self,
        *,
        query_text: str,
        model_slots: list[ModelSlot],
        account_id: UUID | None = None,
        query_run_id: UUID | None = None,
        context: dict[str, Any] | None = None,
    ) -> CostEstimate:
        # Issue #123: the cheapest, most frequently-hit request path is where
        # a stale-store reconnect gets kicked off. Both calls are cheap on
        # the common healthy-store path (one property read under a lock the
        # store already holds) and never block THIS request: an actual
        # reopen, if one is due, runs on a background thread and is picked
        # up by a LATER call once it finishes.
        from product_app.store_reconnect import (
            maybe_reconnect_feedback_store,
            maybe_reconnect_run_history_store,
        )

        maybe_reconnect_feedback_store()
        maybe_reconnect_run_history_store()

        breakdown = self._estimate_breakdown(
            query_text=query_text,
            model_slots=model_slots,
            context=context,
        )
        # ``breakdown.total`` is the quantized grand total (same value the
        # old ``_estimate_total(...).quantize(...)`` produced). Compute the
        # breakdown ONCE and attach it to every returned estimate — including
        # the BLOCK / cumulative / daily-cap early returns — so screens 03/05
        # always have the itemized partition.
        estimated = breakdown.total
        # Fail-safe upper bound (issue #16 rec #2/#3). The cost guardrail
        # (per-call BLOCK / REQUIRE_CONFIRMATION) is evaluated against THIS,
        # not the realistic point estimate, so it can only over-protect: real
        # cost is capped at the initial-answer ``max_tokens`` this bound
        # prices, and debate/synthesis are already capped. ``max_cost_usd``
        # is >= ``estimated`` and is surfaced to the UI as the "up to $Y"
        # figure. The cumulative / daily-cap accounting below stays on the
        # realistic ``estimated`` — those track accumulated REAL spend, which
        # tracks the point estimate, not the worst case.
        bound = self._estimate_bound_usd(
            query_text=query_text, model_slots=model_slots, context=context
        )
        threshold_action, reasons = self._threshold_for(bound)
        # C8: cumulative-spend guard. A user can issue many small
        # queries that each stay below ``HARD_LIMIT_USD`` but together
        # blow the budget. The hard limit is per-account-per-window;
        # we approximate "window" as the in-memory event ring buffer
        # (capacity ``InMemoryCostEventRecorder.MAX_EVENTS``). When a
        # new estimate, added to the cumulative recorded spend for
        # this account, would push the total past the hard limit,
        # the request is BLOCKed even if the new estimate alone would
        # ALLOW. This is defense-in-depth — the upstream provider
        # also bills and rate-limits — but it prevents a single
        # client from exhausting the demo budget via repeated small
        # calls.
        if account_id is not None and cost_event_recorder is not None:
            cumulative = self._cumulative_spend_for(account_id)
            # UNITS: ``cumulative`` is a sum of RECORDED point estimates, so the
            # term added to it must be the point estimate too. ``59a4a8f``
            # switched this (and the daily cap below) to ``bound`` to "fail
            # safe", which instead compared a worst case against a realistic
            # meter — apples to oranges on a money rail, and the exact opposite
            # of what the comment 20 lines above this mandates.
            #
            # The per-call rail above KEEPS the bound: that one fails safe on a
            # single call, which is what issue #16 rec #2/#3 asked for. These
            # accumulation rails are a different question and must match their
            # meter. See tests/unit/test_cost_rail_units.py.
            if cumulative > 0 and cumulative + estimated > HARD_LIMIT_USD:
                return CostEstimate(
                    estimated_cost_usd=estimated,
                    max_cost_usd=bound,
                    threshold_action=CostThresholdAction.BLOCK,
                    confirmation_token=None,
                    breakdown=breakdown,
                    reasons=[
                        "Worst-case cost is above the USD 0.25 hard limit for this account.",
                        (
                            "Cumulative spend for this account is "
                            f"{cumulative.quantize(COST_DISPLAY_QUANTUM)} USD; "
                            "no further queries can be accepted until the window resets."
                        ),
                    ],
                )
        # Daily-cap guard. Defense-in-depth: even if a user stays
        # under the per-call thresholds AND under the in-memory
        # cumulative check, a patient attacker could trickle out one
        # $0.001 query per minute and accumulate unbounded daily
        # spend. The daily cap is the long-term safety net: a single
        # account can never spend more than ``DAILY_CAP_USD`` in any
        # 24-hour rolling window, regardless of how the cumulative
        # check behaves. Reads from the durable SQLite feedback
        # store (not the in-memory ring buffer — that is bounded to
        # ``MAX_EVENTS``).
        if account_id is not None:
            from product_app.feedback_store import get_store  # local import to avoid cycles

            store = get_store()
            # Issue #122. Two shapes of "the ledger cannot be trusted":
            # ``store is None`` (#101's boot-lock case) and a store that
            # opened fine but ``write_health()`` now reports ``"failing"``
            # (#109's read-only-volume-under-an-already-open-handle case).
            # ``getattr`` + ``callable`` guard, not a bare ``store.write_health()``
            # call: mirrors ``store_reconnect.maybe_reconnect_feedback_store``,
            # for the same reason — a duck-typed test double or any future
            # store implementation that predates #109's signal must be read
            # as "cannot report health" rather than crash the request.
            health = getattr(store, "write_health", None) if store is not None else None
            ledger_is_stale = store is None or (callable(health) and health() == "failing")
            if ledger_is_stale:
                # Pre-decided policy (issue #122, confirmed with the operator,
                # not a code guess): BLOCK, but only AFTER a reopen attempt
                # (issue #123) has actually been tried and failed — never an
                # immediate block on staleness alone (a reconnect triggered
                # earlier in THIS SAME call may still be in flight), and never
                # a bare raise (measured: an unwrapped raise here produced a
                # bare 500 with no error envelope on both routes).
                from product_app.store_reconnect import feedback_reconnect_has_failed

                if feedback_reconnect_has_failed():
                    return CostEstimate(
                        estimated_cost_usd=estimated,
                        max_cost_usd=bound,
                        threshold_action=CostThresholdAction.BLOCK,
                        confirmation_token=None,
                        breakdown=breakdown,
                        reasons=[
                            (
                                "The daily spend ledger is stale and a reconnect "
                                "attempt has already failed, so the 24h cap for "
                                "this account cannot be verified right now."
                            ),
                        ],
                    )
                # LOUD ONLY (issue #101's original decision, unchanged for the
                # first observation of staleness): the request is NOT denied
                # and ``threshold_action`` is NOT changed, because failing
                # closed on the very first sighting — before a reopen has had
                # a chance to run — would refuse every priced request on a
                # transient storage blip. What changes here is that the
                # bypass stops being invisible: before #101's fix, a spend
                # guard could be off for the whole life of a process with
                # nothing but one boot-time WARNING about "persistence".
                self._log_daily_cap_bypassed()
            else:
                # ``ledger_is_stale`` is False here, and its first disjunct
                # is ``store is None`` — so ``store`` is proven non-None.
                # Spelled out for mypy, which cannot follow narrowing through
                # an intermediate boolean.
                assert store is not None
                already_spent = store.daily_spend_for(account_id)
                # Same unit rule as the cumulative rail above: ``daily_spend_for``
                # sums ``estimated_cost_usd``, so the addend is the point
                # estimate. With ``bound`` here the cap admitted
                # ``floor((CAP - bound) / unit) + 1`` runs instead of
                # ``floor(CAP / unit)`` — one run of headroom permanently
                # unusable — and any run whose BOUND alone exceeded the cap was
                # BLOCKed with a null confirmation token even on an account that
                # had spent nothing, which killed the confirmation band outright.
                if already_spent + estimated > DAILY_CAP_USD:
                    return CostEstimate(
                        estimated_cost_usd=estimated,
                        max_cost_usd=bound,
                        threshold_action=CostThresholdAction.BLOCK,
                        confirmation_token=None,
                        breakdown=breakdown,
                        reasons=[
                            (
                                f"Worst-case cost would exceed the USD "
                                f"{DAILY_CAP_USD} daily cap for this account."
                            ),
                            (
                                "Account has spent "
                                f"{already_spent.quantize(COST_DISPLAY_QUANTUM)} "
                                "USD in the last 24 hours; no further queries "
                                "can be accepted until the window resets."
                            ),
                        ],
                    )
        # Issue #100: the deployment-wide ceiling. Independent of
        # ``account_id`` (it sums across every account) and independent of
        # ``threshold_action`` (it degrades, never blocks — see the
        # constant's docstring). Decided once, here, and persisted on the
        # returned ``CostEstimate`` / the ``QueryRun`` it gets attached to;
        # ``_execute_query_run`` reads that stored decision rather than
        # re-querying at execute time, so what got billed and what actually
        # ran can never disagree.
        global_ceiling_reached = False
        from product_app.feedback_store import get_store  # local import to avoid cycles

        global_store = get_store()
        if global_store is not None:
            global_ceiling_reached = global_store.global_daily_spend() >= GLOBAL_DAILY_CEILING_USD
        # else: fail open, same posture as the per-account bypass above —
        # a storage fault must not silently turn into "everyone gets
        # simulated answers" any more than it silently turns into "nobody
        # is capped".

        confirmation_token: str | None = None
        if threshold_action is not CostThresholdAction.BLOCK:
            # Mint a token whenever the estimate is at all confirmable. The
            # token is bound to the (account, query_run, cost) triple. The
            # account_id is optional: when it is ``None`` we still mint a
            # token using a placeholder UUID so unit tests and the
            # ``evaluate_confirmation`` round-trip work without one. The
            # route layer always provides a real ``account_id``.
            confirmation_token = self._mint_confirmation_token(
                account_id=account_id or uuid4(),
                query_run_id=query_run_id,
                estimated_cost_usd=estimated,
            )
        return CostEstimate(
            estimated_cost_usd=estimated,
            max_cost_usd=bound,
            threshold_action=threshold_action,
            confirmation_token=confirmation_token,
            reasons=reasons,
            breakdown=breakdown,
            global_ceiling_reached=global_ceiling_reached,
        )

    def _log_daily_cap_bypassed(self) -> None:
        """Announce a skipped daily cap, at most once per window.

        Emits nothing else and returns nothing: the caller's ``CostEstimate``
        must be identical with and without this call (asserted by
        ``test_the_bypass_log_does_not_change_the_returned_estimate``).

        The window bookkeeping runs under the service lock so two concurrent
        request threads cannot both decide they are the first — the point of a
        rate limit is a bounded record count, and a check-then-set race would
        emit one record per thread instead of one per window.

        Elapsed time comes from ``self._monotonic()``, never the wall clock: see
        ``DAILY_CAP_BYPASS_LOG_INTERVAL_S`` for the measured cost of getting
        that wrong. The record's own timestamp still comes from the logging
        framework's wall clock, so the line reads normally.
        """
        now = self._monotonic()
        with self._lock:
            last = self._cap_bypass_logged_at
            if last is not None and (now - last) < DAILY_CAP_BYPASS_LOG_INTERVAL_S:
                return
            self._cap_bypass_logged_at = now
        _log.error(
            "costs: feedback store unavailable, so the USD %s per-account 24h "
            "daily spend cap is NOT being enforced — every estimate is passing "
            "the cap check unmetered. A background reconnect is attempted from "
            "this same request path (issue #123, at most one attempt per %ss); "
            "if this line keeps repeating, the reopen is failing too — check "
            "/status feedback_db and restart once the database is reachable. "
            "Repeats suppressed for %ss.",
            DAILY_CAP_USD,
            settings.store_reconnect_cooldown_seconds,
            DAILY_CAP_BYPASS_LOG_INTERVAL_S,
        )

    def evaluate_confirmation(
        self,
        *,
        estimate: CostEstimate,
        confirmation: CostConfirmation | None,
        account_id: UUID | None = None,
    ) -> CostGuardrailDecision:
        reasons: list[str] = []
        if estimate.threshold_action is not CostThresholdAction.REQUIRE_CONFIRMATION:
            reasons.append("Confirmation is only required for estimates in the upper-cost band.")
            return CostGuardrailDecision(confirmed=True, reasons=reasons)
        if confirmation is None:
            reasons.append(
                "Cost estimate is in the upper-cost band and requires explicit confirmation."
            )
            return CostGuardrailDecision(confirmed=False, reasons=reasons)
        if confirmation.estimated_cost_usd != estimate.estimated_cost_usd:
            reasons.append("Confirmation cost does not match the latest estimate.")
            return CostGuardrailDecision(confirmed=False, reasons=reasons)
        if not self._verify_confirmation_token(
            token=confirmation.confirmation_token,
            account_id=account_id,
            estimated_cost_usd=estimate.estimated_cost_usd,
        ):
            reasons.append(
                "Confirmation token is invalid, expired, or was issued to a different account."
            )
            return CostGuardrailDecision(confirmed=False, reasons=reasons)
        return CostGuardrailDecision(
            confirmed=True,
            reasons=["Cost confirmation matched the estimate."],
        )

    def record_guardrail_event(
        self,
        *,
        account_id: UUID,
        query_run_id: UUID | None,
        estimated_cost_usd: Decimal,
        threshold_action: CostThresholdAction,
        confirmed: bool,
        preview: bool = False,
        global_ceiling_reached: bool = False,
        client_ip: str | None = None,
    ) -> None:
        # Map the (threshold_action, confirmed, preview, global_ceiling_reached)
        # combination to an event type.
        #  - BLOCK  → cost_guardrail_blocked (the request was refused)
        #  - REQUIRE_CONFIRMATION + confirmed=False → cost_confirmation_required
        #  - preview → cost_estimate_previewed
        #  - global_ceiling_reached → cost_guardrail_degraded_to_simulation
        #    (issue #100 — see below)
        #  - otherwise → cost_guardrail_accepted (the request was allowed,
        #    with or without confirmation)
        #
        # F-01: ``preview=True`` marks a call from ``POST /estimate``, which
        # only shows the user what a run *would* cost — nothing has been spent.
        # It must NOT record ``cost_guardrail_accepted``, because both spend
        # guards (``_cumulative_spend_for`` here and
        # ``FeedbackStore.daily_spend_for``) count exactly that type, so a
        # preview would bill the account for a run that never happened — and
        # bill it again when the user actually starts the run. The preview is
        # still recorded, under a name that says what happened, so the audit
        # trail and the estimate-time BLOCK/Sentry path are untouched.
        #
        # Issue #100: the SAME reasoning applies to a ceiling-degraded run.
        # It is about to execute as a whole-run local simulation (see
        # ``_execute_query_run``) and will spend nothing real, so counting it
        # as ``cost_guardrail_accepted`` would let the global meter this
        # branch just tripped keep climbing forever on money nobody spent —
        # the ceiling would never clear on real spend again this window.
        # Checked AFTER ``preview`` on purpose: a preview is already
        # unmetered regardless of the ceiling, so it keeps its own label.
        if threshold_action is CostThresholdAction.BLOCK:
            event_type = "cost_guardrail_blocked"
        elif threshold_action is CostThresholdAction.REQUIRE_CONFIRMATION and not confirmed:
            event_type = "cost_confirmation_required"
        elif preview:
            event_type = "cost_estimate_previewed"
        elif global_ceiling_reached:
            event_type = "cost_guardrail_degraded_to_simulation"
        else:
            event_type = "cost_guardrail_accepted"
        cost_event_recorder.record(
            event_type=event_type,
            account_id=account_id,
            query_run_id=query_run_id,
            estimated_cost_usd=estimated_cost_usd,
            threshold_action=threshold_action,
            confirmed=confirmed,
        )
        # Surface BLOCK events (rejected estimates) and the #100
        # ceiling-degrade event to Sentry so operators see both without
        # polling. ALLOW and REQUIRE_CONFIRMATION events are normal traffic
        # and would just spam the Sentry quota.
        if event_type in ("cost_guardrail_blocked", "cost_guardrail_degraded_to_simulation"):
            import sentry_sdk  # local import to avoid loading the SDK in tests

            try:
                with sentry_sdk.push_scope() as scope:
                    scope.set_tag("event_type", event_type)
                    scope.set_extra("account_id", str(account_id))
                    scope.set_extra("estimated_cost_usd", str(estimated_cost_usd))
                    if query_run_id is not None:
                        scope.set_extra("query_run_id", str(query_run_id))
                    if event_type == "cost_guardrail_degraded_to_simulation":
                        if client_ip is not None:
                            scope.set_extra("client_ip", client_ip)
                        from product_app.feedback_store import (
                            get_store,  # local import to avoid cycles
                        )

                        alert_store = get_store()
                        if alert_store is not None:
                            scope.set_extra(
                                "global_daily_spend_usd", str(alert_store.global_daily_spend())
                            )
                        scope.set_extra("global_daily_ceiling_usd", str(GLOBAL_DAILY_CEILING_USD))
                    sentry_sdk.capture_message(
                        f"{event_type}:{event_type}",
                        level="warning",
                    )
            except Exception as exc:  # noqa: BLE001 — Sentry must never crash the request
                # If Sentry isn't configured (DSN not set, network
                # down, etc.) or any other failure happens, log and
                # continue. The cost guardrail event is already
                # persisted to the feedback store; Sentry is a
                # notification channel, not the source of truth.
                import logging

                logging.getLogger(__name__).debug(
                    "Sentry capture failed for %s: %s", event_type, exc
                )

    # -- internals --------------------------------------------------------

    def _estimate_breakdown(
        self,
        *,
        query_text: str,
        model_slots: list[ModelSlot],
        context: dict[str, Any] | None = None,
    ) -> CostBreakdown:
        """Compute the itemized cost partition (by model AND by stage).

        issue #16: a realistic per-call token model. The pipeline is seven
        billed calls — four initial answers (one per slot, on the slot's
        own model), two debate rounds (on ``settings.debate_model_id``),
        and one synthesis (on ``settings.synthesis_model_id``). Each call's
        prompt is modelled as ``system-prompt overhead + web-search context
        (searching initial slots only) + the query + the upstream answers
        it consumes``; each call's output is a configured floor that grows
        modestly with query length. Every term is ``price_per_1k × tokens``
        against the cached catalog rates — no API call, no synthetic
        per-character charge. Two partitions (``by_stage`` and ``by_model``)
        are derived from the same terms; both re-sum to the quantized total
        after :meth:`_reconcile_usd_lines` distributes the rounding residual.
        """
        # An initial answer's output lengthens modestly with the query, but the
        # live call physically cannot emit more than the enforced
        # ``initial_answer_max_tokens`` cap (see
        # ``providers._call_openrouter_with_optional_search``) — so the TYPICAL
        # output is clamped to that cap too. Without the clamp the floor grows
        # unbounded with query length and, on a long-form query (the supported
        # range runs to ``_QUERY_TEXT_MAX_LENGTH`` = 20_000 chars), overtakes the
        # fixed-cap bound — printing a "typical ≈ $X" ABOVE the "up to $Y"
        # ceiling and breaking ``estimated_cost_usd <= max_cost_usd`` (issue #24;
        # the bound path :meth:`_estimate_bound_usd` uses exactly this cap, so
        # the clamp makes the point <= bound invariant hold on every term).
        query_tokens = Decimal(len(query_text)) / CHARS_PER_TOKEN
        init_output_tokens = min(
            Decimal(settings.cost_initial_output_tokens)
            + (Decimal(str(settings.cost_output_tokens_per_query_token)) * query_tokens),
            Decimal(settings.initial_answer_max_tokens),
        )
        # L4: compute extra context tokens from the optional follow-up context.
        # The context dict carries { prior_question, prior_synthesis }; when
        # present we price the prior_question as additional input tokens
        # (it is injected into the system prompt of every debate/synthesis call).
        # The prior_synthesis is re-sent as part of the user prompt and is
        # priced in the upstream_answers_tokens term below; we add its length
        # to the synthesis prompt token count explicitly.
        context_tokens = Decimal(0)
        if context:
            prior_q = (context.get("prior_question") or "").strip()
            prior_s = (context.get("prior_synthesis") or "").strip()
            if prior_q:
                context_tokens += Decimal(len(prior_q)) / CHARS_PER_TOKEN
            if prior_s:
                context_tokens += Decimal(len(prior_s)) / CHARS_PER_TOKEN
        (
            initial_per_model,
            initial_total,
            debate_round_cost,
            synthesis_cost,
            raw_total,
        ) = self._cost_components(
            query_text=query_text,
            model_slots=model_slots,
            init_output_tokens=init_output_tokens,
            # The live pipeline fans synthesis out into
            # ``cost_synthesis_sections`` independent billed calls (see
            # ``synthesis.produce_final_synthesis`` — five sections when a key
            # is configured). Model all of them in the headline, matching the
            # fail-safe bound, so the displayed typical is not ~17–38% below the
            # real bill on the common cheap-model runs where synthesis
            # dominates (issue #24; see also
            # ``config.cost_synthesis_sections``). Output is still the typical
            # per-section floor, not the enforced cap, so the point estimate
            # stays strictly <= the ``_estimate_bound_usd`` ceiling.
            synthesis_sections=Decimal(settings.cost_synthesis_sections),
            context_tokens=context_tokens,
        )
        total = raw_total.quantize(COST_DISPLAY_QUANTUM, rounding=ROUND_HALF_UP)

        # --- by_stage: initial + the two debate rounds + synthesis ------
        # Stage keys mirror ``progress.stages[].stage`` (see
        # ``query_runs._initial_progress``) so a UI can join the two.
        # Reconcile ALL FOUR raw lines against ``total`` in a single call. Their
        # raw sum IS ``raw_total`` (whose quantization is ``total``), so the
        # residual is always <= the line count and no quantum is ever dropped —
        # both partitions re-sum to ``total`` exactly. (Reconciling only a
        # subset against a derived sub-total could leak the debate-round
        # rounding slack into a residual larger than the subset can absorb,
        # silently short-summing the partition.)
        stage_names = ("initial_answers", "debate_round_1", "debate_round_2", "synthesis")
        stage_usd = self._reconcile_usd_lines(
            [initial_total, debate_round_cost, debate_round_cost, synthesis_cost], total
        )
        # The two debate rounds share one token model and must display equal,
        # but the largest-remainder tie-break can award the residual quantum to
        # ``debate_round_1`` (lower index) and not ``debate_round_2``. Equal raws
        # can only diverge by a single quantum, so move that quantum onto
        # ``initial_answers`` (the largest line): the pair is equalized AND the
        # total is preserved (a sum-neutral transfer, every line stays >= 0).
        if stage_usd[1] != stage_usd[2]:
            hi = 1 if stage_usd[1] > stage_usd[2] else 2
            stage_usd[hi] -= COST_DISPLAY_QUANTUM
            stage_usd[0] += COST_DISPLAY_QUANTUM
        by_stage = [
            CostLineByStage(stage=name, usd=usd)
            for name, usd in zip(stage_names, stage_usd, strict=True)
        ]

        # --- by_model: 4 initial-answer rows + a debate+synthesis row ----
        # Each of the four rows is its slot's own initial-answer cost. The
        # fifth row is the debate (×2) + synthesis orchestration, which runs
        # on the dedicated inner-call models, not the four slots — so it is
        # its own line rather than being smeared across the slot rows.
        # (issue #16 relabel: the old "Synthesis writer" name hid that this
        # line also includes the two debate rounds.)
        inner_call_cost = Decimal(2) * debate_round_cost + synthesis_cost
        raw_model: list[tuple[str, str, str, Decimal]] = []
        for slot, initial_i in zip(model_slots, initial_per_model, strict=True):
            display_name = (
                openrouter_model_catalog_service.lookup_short_name(slot.model_id) or slot.model_id
            )
            raw_model.append(("model", slot.model_id, display_name, initial_i))
        raw_model.append(("synthesis", "synthesis", "Debate + synthesis", inner_call_cost))
        model_usd = self._reconcile_usd_lines([v for *_, v in raw_model], total)
        by_model = [
            CostLineByModel(model_id=mid, display_name=name, usd=usd, kind=kind)
            for (kind, mid, name, _), usd in zip(raw_model, model_usd, strict=True)
        ]

        return CostBreakdown(by_model=by_model, by_stage=by_stage, total=total)

    def _cost_components(
        self,
        *,
        query_text: str,
        model_slots: list[ModelSlot],
        init_output_tokens: Decimal,
        synthesis_sections: Decimal = Decimal(1),
        debate_output_override: Decimal | None = None,
        context_tokens: Decimal = Decimal(0),
        price_round_two_prior_critique: bool = False,
    ) -> tuple[list[Decimal], Decimal, Decimal, Decimal, Decimal]:
        """The shared per-call token model, parameterised by the initial-answer
        output token count and the synthesis section count.

        Returns ``(initial_per_model, initial_total, debate_round_cost,
        synthesis_cost, raw_total)``. Used with the realistic output floor + all
        ``cost_synthesis_sections`` sections for the displayed estimate
        (:meth:`_estimate_breakdown`) and with the enforced ``max_tokens`` cap +
        the same section count for the fail-safe guardrail bound
        (:meth:`_estimate_bound_usd`) — same arithmetic and section fan-out,
        differing only in the per-call output assumption (typical floor vs
        enforced cap), so the point estimate is always <= the bound and the two
        can never drift.

        ``context_tokens`` is the extra input tokens from a follow-up context
        (prior_question + prior_synthesis). It is priced into debate and synthesis
        calls (those that receive context via the system prompt) but NOT into the
        initial-answer calls.
        """
        if not model_slots:
            raise ValueError("model_slots must not be empty")
        if len(model_slots) != 4:
            raise ValueError("model_slots must contain exactly four slots")
        # PERF-P1: use the cached price index instead of rebuilding the dict
        # on every estimate call — O(1) lookup per model id.
        prices = openrouter_model_catalog_service.price_index()

        def _price(model_id: str) -> tuple[Decimal, Decimal]:
            return prices.get(
                model_id,
                (_DEFAULT_PRICE_PER_1K_INPUT, _DEFAULT_PRICE_PER_1K_OUTPUT),
            )

        def _cost(model_id: str, prompt_tokens: Decimal, output_tokens: Decimal) -> Decimal:
            pin, pout = _price(model_id)
            return pin * prompt_tokens / Decimal(1000) + pout * output_tokens / Decimal(1000)

        query_tokens = Decimal(len(query_text)) / CHARS_PER_TOKEN
        system_tokens = Decimal(settings.cost_system_prompt_tokens)
        search_tokens = Decimal(settings.cost_web_search_context_tokens)
        # Flat per-request web-search plugin fee (issue #18) — charged once per
        # SEARCHING slot regardless of the model's token price, so a :free model
        # still incurs it. String() so a float default becomes an exact Decimal.
        search_request_fee = Decimal(str(settings.cost_web_search_request_fee_usd))
        # Point estimate uses the typical floor; the bound overrides with the
        # enforced per-round cap so it is a true ceiling on the debate stage.
        debate_output_tokens = (
            debate_output_override
            if debate_output_override is not None
            else Decimal(settings.cost_debate_output_tokens)
        )
        synthesis_output_tokens = Decimal(settings.cost_synthesis_output_tokens)

        # --- 4 initial answers (each on its own slot model) -------------
        # A searching slot's prompt carries the injected web-search context;
        # a search-disabled slot (the cheaper, training-data-only path)
        # does not. This is the term the old model missed entirely — it
        # priced ~11 query tokens instead of the ~2,300 prompt tokens a
        # searching call actually carries.
        initial_per_model: list[Decimal] = []
        for slot in model_slots:
            prompt_tokens = (
                system_tokens + (search_tokens if slot.search else Decimal(0)) + query_tokens
            )
            slot_cost = _cost(slot.model_id, prompt_tokens, init_output_tokens)
            # A searching slot also pays the flat web-search plugin fee — the
            # only web-search cost a :free-priced model carries (issue #18).
            if slot.search:
                slot_cost += search_request_fee
            initial_per_model.append(slot_cost)
        initial_total = sum(initial_per_model, Decimal("0"))

        # --- 2 debate rounds + 1 synthesis (dedicated inner-call models) -
        # These read a BOUNDED context — the four initial answers plus the
        # query — priced on the models they actually run on (debate/synthesis
        # writers), not a rate borrowed from the four slot models. Their prompt
        # scales with the initial answers they consume (``init_output_tokens``),
        # so the guardrail bound's larger initial output flows through here too.
        # L4: when a follow-up context is present, the prior_question is
        # injected into the system prompt (same for every debate + synthesis
        # call) and the prior_synthesis is re-sent in the user prompt (same
        # for every synthesis section). Both are modelled as additional
        # input tokens.
        # Same prefix for debate (system) and synthesis (user).
        context_input_tokens = context_tokens
        upstream_answers_tokens = Decimal(4) * init_output_tokens
        debate_prompt_tokens = (
            system_tokens + query_tokens + upstream_answers_tokens + context_input_tokens
            # Round 2's prompt also carries round 1's critique in full
            # (``debate._debate_user_prompt`` appends ``prior_round``, sliced
            # nowhere), so debate input is NOT the same for both rounds. Without
            # this term ``max_cost_usd`` was not a true ceiling: real debate
            # input exceeded the priced figure by up to one full critique, and
            # WP-D's 700 -> 2000 raise nearly tripled the gap. The synthesis
            # term below has always added ``2 * debate_output_tokens`` for
            # exactly this reason, which is what marks the omission an
            # oversight rather than a modelling choice.
            #
            # Added ONCE to ``raw_total`` below, NOT to this per-round figure.
            # An earlier revision charged it to both rounds "to be safe"; that
            # over-priced every estimate by one critique's input and MEASURED
            # 9 of the 495 four-slot mixes over the shipped catalog flipping
            # CONFIRM -> BLOCK on the over-charge alone. BLOCK is a HARD refusal
            # (``confirmation_token`` is ``None``), so the user cannot proceed
            # at all — "over-protective" is the wrong word for denying a run the
            # exact model says is affordable. A fail-safe bound must be a
            # ceiling, not an inflation.
        )
        # Both rounds share the same token model (the invariant the UI and the
        # breakdown tests rely on: ``by_stage`` round_1 == round_2).
        debate_round_cost = _cost(
            settings.debate_model_id, debate_prompt_tokens, debate_output_tokens
        )
        synthesis_prompt_tokens = (
            system_tokens
            + query_tokens
            + upstream_answers_tokens
            + context_input_tokens  # prior_question in system prompt
            + context_input_tokens  # prior_synthesis in user prompt (re-sent)
            + Decimal(2) * debate_output_tokens
        )
        # Synthesis fans out into ``synthesis_sections`` independent live calls,
        # each re-sending the full context. Both callers now pass the configured
        # section count: the point estimate at the typical per-section output
        # floor, the bound at the enforced per-section cap.
        synthesis_cost = synthesis_sections * _cost(
            settings.synthesis_model_id, synthesis_prompt_tokens, synthesis_output_tokens
        )
        # ROUND 2 ONLY: its prompt carries round 1's critique in full
        # (``debate._debate_user_prompt`` appends ``prior_round``, sliced
        # nowhere). Added here, once, rather than to ``debate_round_cost`` —
        # that keeps the bound EXACT (no over-charge, so no affordable run is
        # hard-refused) while leaving the displayed ``by_stage`` round_1 ==
        # round_2 invariant intact. Without the term at all, ``max_cost_usd``
        # was not a true ceiling, and WP-D's 700 -> 2000 raise nearly tripled
        # the shortfall.
        # Applied ONCE, and only for the BOUND
        # (``price_round_two_prior_critique`` is set solely by
        # :meth:`_estimate_bound_usd`, which returns a scalar and no
        # breakdown). Two earlier shapes were both wrong:
        #   * folding it into ``debate_prompt_tokens`` charged it to BOTH
        #     rounds — MEASURED 9 of the 495 shipped-catalog mixes flipping
        #     CONFIRM -> BLOCK on that over-charge alone, and BLOCK is a hard
        #     refusal with no confirmation token, so a run the exact model
        #     says is affordable became unrunnable;
        #   * adding it to ``raw_total`` on the POINT path broke the
        #     reconciliation invariant — ``by_stage`` stopped summing to
        #     ``total``, because the term belongs to no single displayed stage.
        # Bound-only keeps the ceiling EXACT and leaves both displayed
        # contracts (round_1 == round_2, and both partitions reconciling)
        # untouched.
        prior_critique_input_cost = (
            _cost(settings.debate_model_id, debate_output_tokens, Decimal(0))
            if price_round_two_prior_critique
            else Decimal(0)
        )
        raw_total = (
            initial_total
            + Decimal(2) * debate_round_cost
            + prior_critique_input_cost
            + synthesis_cost
        )
        return initial_per_model, initial_total, debate_round_cost, synthesis_cost, raw_total

    def _estimate_bound_usd(
        self,
        *,
        query_text: str,
        model_slots: list[ModelSlot],
        context: dict[str, Any] | None = None,
    ) -> Decimal:
        """Fail-safe upper bound on real cost — the "up to $Y" figure the cost
        guardrail is evaluated against (issue #16 rec #2/#3).

        Identical arithmetic to the displayed estimate, but priced at the
        worst case on every dimension the point estimate models as typical:
        initial-answer output at the enforced
        ``settings.initial_answer_max_tokens`` cap (instead of the floor),
        debate output at the enforced per-round
        ``settings.cost_debate_output_tokens_cap`` (instead of the floor), and
        synthesis as all ``settings.cost_synthesis_sections`` section calls
        (instead of one). Because the live calls are capped at exactly these
        values — initial (see ``providers._call_openrouter_with_optional_search``),
        debate (``debate.DEBATE_ROUND_MAX_TOKENS``), synthesis
        (``synthesis.SYNTHESIS_SECTION_MAX_TOKENS`` × section count) — this
        total is a true ceiling on real cost: the guardrail keying off it can
        only ever over-protect, never wave through a run that then bills more.
        """
        # Compute context tokens once; both the point estimate and the bound
        # must model the same context so the point <= bound invariant holds.
        context_tokens = Decimal(0)
        if context:
            prior_q = (context.get("prior_question") or "").strip()
            prior_s = (context.get("prior_synthesis") or "").strip()
            if prior_q:
                context_tokens += Decimal(len(prior_q)) / CHARS_PER_TOKEN
            if prior_s:
                context_tokens += Decimal(len(prior_s)) / CHARS_PER_TOKEN
        init_output_tokens = Decimal(settings.initial_answer_max_tokens)
        *_, raw_total = self._cost_components(
            query_text=query_text,
            model_slots=model_slots,
            init_output_tokens=init_output_tokens,
            synthesis_sections=Decimal(settings.cost_synthesis_sections),
            debate_output_override=Decimal(settings.cost_debate_output_tokens_cap),
            context_tokens=context_tokens,
            # The bound is the only caller that must be a true CEILING, and the
            # only one with no breakdown to reconcile.
            price_round_two_prior_critique=True,
        )
        return raw_total.quantize(COST_DISPLAY_QUANTUM, rounding=ROUND_HALF_UP)

    @staticmethod
    def _reconcile_usd_lines(raw: list[Decimal], total: Decimal) -> list[Decimal]:
        """Apportion ``raw`` to whole ``COST_DISPLAY_QUANTUM`` units that sum
        to ``total`` EXACTLY, sign-safely (largest-remainder / Hamilton).

        ``total`` is assumed already quantized to the quantum. The rule:

        * Floor each raw line DOWN to the quantum (``raw >= 0`` ⇒ floor
          ``>= 0``), giving the guaranteed-minimum quanta per line.
        * ``residual_steps = round((total - Σfloors) / quantum)``. If
          positive, hand out one extra quantum to each of the
          ``residual_steps`` lines with the LARGEST fractional remainders
          (ties break to the lowest index). If negative (a rare half-up
          overshoot upstream), take one quantum back from each of that many
          lines with the SMALLEST remainders *among lines still > 0*, so no
          line is ever driven negative.

        The result therefore satisfies both invariants unconditionally:
        every returned line is ``>= 0`` and ``sum(result) == total``.
        """
        quantum = COST_DISPLAY_QUANTUM
        if not raw:
            if total != 0:
                raise ValueError(f"cannot reconcile an empty line list to non-zero total {total}")
            return []
        # Floor each line to a whole number of quanta; keep the fractional
        # remainder (in [0, 1) for raw >= 0) to rank apportionment.
        floor_steps = [(v / quantum).to_integral_value(rounding=ROUND_FLOOR) for v in raw]
        remainders = [(v / quantum) - fs for v, fs in zip(raw, floor_steps, strict=True)]
        residual = total - sum(fs * quantum for fs in floor_steps)
        residual_steps = int((residual / quantum).to_integral_value(rounding=ROUND_HALF_UP))
        steps = list(floor_steps)
        if residual_steps > 0:
            # Largest remainder first; tie → lowest index.
            order = sorted(range(len(steps)), key=lambda i: (-remainders[i], i))
            for i in order[:residual_steps]:
                steps[i] += 1
        elif residual_steps < 0:
            # Smallest remainder first, only lines still strictly positive.
            order = sorted(
                (i for i in range(len(steps)) if steps[i] > 0),
                key=lambda i: (remainders[i], i),
            )
            needed = -residual_steps
            if needed > len(order):
                raise ValueError("cannot reconcile lines without driving a line negative")
            for i in order[:needed]:
                steps[i] -= 1
        return [s * quantum for s in steps]

    def _cumulative_spend_for(self, account_id: UUID) -> Decimal:
        """Sum the ``estimated_cost_usd`` of every cost event recorded
        for ``account_id``. The recorder holds at most
        ``MAX_EVENTS`` events, so this is a sliding-window total,
        not an unbounded account lifetime. The intent is to detect
        the immediate-budget-exhaustion case (a user issuing many
        queries in quick succession), not to enforce a monthly cap.

        Only ``cost_guardrail_accepted`` events count — these are
        the events where the estimate was charged. ``BLOCK`` events
        were never billed, ``cost_estimate_previewed`` events are a
        ``POST /estimate`` preview of a run that has not started
        (F-01), and ``REQUIRE_CONFIRMATION`` events are
        also not charged because the request was abandoned or the
        user cancelled.
        """
        total = Decimal("0")
        if cost_event_recorder is None:
            return total
        for event in cost_event_recorder.list_events():
            if event.account_id != account_id:
                continue
            if event.event_type != "cost_guardrail_accepted":
                continue
            total += event.estimated_cost_usd
        return total

    def _threshold_for(self, bound: Decimal) -> tuple[CostThresholdAction, list[str]]:
        # ``bound`` is the fail-safe ``max_cost_usd`` (the "up to $Y" figure),
        # NOT the realistic point estimate — the rail keys off the worst case so
        # a run can never bill past a limit it was waved through under.
        if bound > HARD_LIMIT_USD:
            return (
                CostThresholdAction.BLOCK,
                [
                    "Worst-case cost could exceed the USD 0.25 hard limit for this account.",
                ],
            )
        if bound > SOFT_THRESHOLD_USD:
            return (
                CostThresholdAction.REQUIRE_CONFIRMATION,
                [
                    "Worst-case cost could exceed USD 0.15 and requires explicit confirmation.",
                ],
            )
        return (
            CostThresholdAction.ALLOW,
            ["Worst-case cost is within the no-confirmation band."],
        )

    def _mint_confirmation_token(
        self,
        *,
        account_id: UUID,
        query_run_id: UUID | None,
        estimated_cost_usd: Decimal,
    ) -> str:
        expires_at = self._now() + CONFIRMATION_TOKEN_TTL
        nonce = secrets.token_hex(16)
        token = self._format_token(
            account_id=account_id,
            query_run_id=query_run_id,
            estimated_cost_usd=estimated_cost_usd,
            expires_at=expires_at,
            nonce=nonce,
        )
        with self._lock:
            self._tokens[token] = _BoundToken(
                account_id=account_id,
                query_run_id=query_run_id,
                estimated_cost_usd=estimated_cost_usd,
                expires_at=expires_at,
                token=token,
            )
            self._purge_expired_tokens_locked()
        return token

    def _verify_confirmation_token(
        self,
        *,
        token: str,
        account_id: UUID | None,
        estimated_cost_usd: Decimal,
    ) -> bool:
        with self._lock:
            record = self._tokens.get(token)
            if record is None:
                return False
            # When the caller does not provide an account_id we are
            # operating in a unit-test / round-trip path: skip the
            # account-id binding check but still verify the cost and
            # token validity.
            if account_id is not None and record.account_id != account_id:
                return False
            if record.estimated_cost_usd != estimated_cost_usd:
                return False
            if record.expires_at < self._now():
                # Drop the expired token so a follow-up attempt with the
                # same value also fails. Idempotent and cheap.
                self._tokens.pop(token, None)
                return False
            # Tokens are single-use. The estimate flow validates the
            # confirmation once per query run; once consumed we drop it.
            self._tokens.pop(token, None)
            return True

    def _purge_expired_tokens_locked(self) -> None:
        current = self._now()
        expired = [token for token, record in self._tokens.items() if record.expires_at < current]
        for token in expired:
            self._tokens.pop(token, None)
        if len(self._tokens) > 4096:
            # Bounded so memory cannot grow unbounded even if TTL never fires.
            sorted_items = sorted(self._tokens.items(), key=lambda pair: pair[1].expires_at)
            for token, _ in sorted_items[: len(sorted_items) - 4096]:
                self._tokens.pop(token, None)

    def _format_token(
        self,
        *,
        account_id: UUID,
        query_run_id: UUID | None,
        estimated_cost_usd: Decimal,
        expires_at: datetime,
        nonce: str,
    ) -> str:
        message = (
            f"{account_id}|{query_run_id or ''}|{estimated_cost_usd}|"
            f"{expires_at.isoformat()}|{nonce}"
        ).encode()
        digest = hmac.new(self._binding_secret, message, hashlib.sha256).hexdigest()
        # The token embeds the expiry timestamp, the nonce, and a 64-hex-char
        # HMAC digest. The expiry makes replay outside the TTL window
        # impossible. The account binding is enforced by the in-memory table.
        return f"{int(expires_at.timestamp())}.{nonce}.{digest}"


cost_event_recorder = InMemoryCostEventRecorder()
cost_estimation_service = CostEstimationService()


# ---------------------------------------------------------------------------
# Measured actual cost (P2). Computed from REAL per-call token usage captured
# from the provider, priced on the SAME per-1K-token catalog basis as the
# pre-run estimate. These are only ever used when every contributing live call
# reported usage (the honesty gate lives in ``query_runs._actual_cost``); the
# functions themselves never fabricate a token count.
# ---------------------------------------------------------------------------


def _price_per_1k(model_id: str) -> tuple[Decimal, Decimal]:
    """``(input, output)`` per-1K-token price for a model, with the default floor."""
    prices = openrouter_model_catalog_service.price_index()
    return prices.get(model_id, (_DEFAULT_PRICE_PER_1K_INPUT, _DEFAULT_PRICE_PER_1K_OUTPUT))


def measured_call_cost_usd(*, model_id: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    """Full-precision measured USD cost of one provider call from real tokens.

    Uses the same per-1K-token catalog prices (with the same default floor) as
    the pre-run estimate, so a measured actual and its estimate are priced on
    one basis. Not quantized — callers sum several of these and quantize the
    grand total once (see :func:`build_measured_breakdown`).
    """
    in_price, out_price = _price_per_1k(model_id)
    return in_price * Decimal(prompt_tokens) / Decimal(1000) + out_price * Decimal(
        completion_tokens
    ) / Decimal(1000)


def build_measured_breakdown(
    *,
    per_model_initial: list[tuple[str, str, Decimal]],
    debate_by_round: dict[int, Decimal],
    synthesis_cost: Decimal,
    judge: tuple[str, Decimal] | None = None,
) -> CostBreakdown:
    """Assemble a measured :class:`CostBreakdown` that re-sums to the total.

    * ``per_model_initial`` — ``(model_id, display_name, measured_initial_cost)``
      per model slot (``0`` for a slot that ran simulated / was not billed).
    * ``debate_by_round`` — measured cost keyed by round number (``1`` and/or
      ``2``); a round that ran templated / was skipped is simply absent, so its
      ``by_stage`` line is ``0``. Keying by round (rather than positionally)
      keeps ``debate_round_1`` / ``debate_round_2`` attributed to the round the
      money was actually spent on.
    * ``synthesis_cost`` — summed measured cost of the live synthesis section
      calls.
    * ``judge`` — ``(model_id, measured_cost)`` for a Layer-B judge call that
      fired AND reported usage (issue #110), or ``None`` when no judge fired
      for this run. A PRESENT-but-``None``-usage judge call must never reach
      here — the caller (``query_runs._actual_cost``) demotes the whole run
      to ``estimated`` first, so a possibly-billed, unpriced call is never
      silently absent from a ``"measured"`` total.

    Debate + synthesis are attributed to a single ``"Debate + synthesis"``
    ``by_model`` row because they use the dedicated debate/synthesis writer
    models, not the four slot models. (issue #16 relabel: the old
    ``"Synthesis writer"`` name hid that this line also folds in the two
    debate rounds — which are the bulk of the inner-call cost.) The judge, when
    present, gets its OWN ``by_model``/``by_stage`` row (``kind="judge"``) —
    folding it into the writer row would mislabel spend on a different model as
    synthesis spend. Both partitions
    are reconciled to the quantized grand total with the same rule as the estimate,
    so every line is ``>= 0`` and the lines sum to the total exactly (the UI's
    reconciliation invariant).
    """
    judge_cost = judge[1] if judge is not None else Decimal("0")
    initial_total = sum((cost for _, _, cost in per_model_initial), Decimal("0"))
    debate_total = sum(debate_by_round.values(), Decimal("0"))
    raw_total = initial_total + debate_total + synthesis_cost + judge_cost
    total = raw_total.quantize(COST_DISPLAY_QUANTUM, rounding=ROUND_HALF_UP)

    debate_round_1 = debate_by_round.get(1, Decimal("0"))
    debate_round_2 = debate_by_round.get(2, Decimal("0"))
    raw_stage: list[tuple[str, Decimal]] = [
        ("initial_answers", initial_total),
        ("debate_round_1", debate_round_1),
        ("debate_round_2", debate_round_2),
        ("synthesis", synthesis_cost),
    ]
    if judge is not None:
        raw_stage.append(("judge", judge_cost))
    stage_usd = CostEstimationService._reconcile_usd_lines([v for _, v in raw_stage], total)
    by_stage = [
        CostLineByStage(stage=name, usd=usd)
        for (name, _), usd in zip(raw_stage, stage_usd, strict=True)
    ]

    writer_cost = debate_total + synthesis_cost
    raw_model: list[tuple[str, str, Decimal, str]] = [
        (mid, name, cost, "model") for mid, name, cost in per_model_initial
    ]
    raw_model.append(("synthesis", "Debate + synthesis", writer_cost, "synthesis"))
    if judge is not None:
        judge_model_id, _cost = judge
        raw_model.append((judge_model_id, "Layer-B judge", judge_cost, "judge"))
    model_usd = CostEstimationService._reconcile_usd_lines(
        [cost for _, _, cost, _ in raw_model], total
    )
    by_model = [
        CostLineByModel(model_id=mid, display_name=name, usd=usd, kind=kind)
        for (mid, name, _cost, kind), usd in zip(raw_model, model_usd, strict=True)
    ]
    return CostBreakdown(by_model=by_model, by_stage=by_stage, total=total)
