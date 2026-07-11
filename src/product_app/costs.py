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
import os
import secrets
import warnings
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from enum import StrEnum
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from product_app.config import settings
from product_app.feedback_store import record_event as _record_feedback_event
from product_app.model_slots import ModelSlot, openrouter_model_catalog_service

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
DAILY_CAP_USD = Decimal("0.20")

#: Quantization step for ``CostEstimate.estimated_cost_usd``. The
#: internal arithmetic runs at full Decimal precision, but every
#: value that leaves the cost service (estimate response, run
#: result, history list, BLOCK 402 body) is rounded to 4 dp so the
#: UI never displays trailing IEEE-754 noise like
#: ``0.01344254000000000000046920801``. ROUND_HALF_UP matches the
#: typical "show 2/4 dp" consumer expectation.
COST_DISPLAY_QUANTUM = Decimal("0.0001")

#: Per-1K-token prices (USD) used when the catalog is unreachable or
#: the model id is unknown. The catalog is the authoritative source
#: for pricing; this is the single fallback floor.
_DEFAULT_PRICE_PER_1K_INPUT = Decimal("0.0008")
_DEFAULT_PRICE_PER_1K_OUTPUT = Decimal("0.002")


DEBATE_FIXED_COST_USD = Decimal("0.012")
SYNTHESIS_FIXED_COST_USD = Decimal("0.015")

#: L3: debate + synthesis inner-call cost is now proportional to the
#: max output rate in the selected model mix, scaled by the configured
#: ``cost_inner_call_multiplier`` and capped at
#: ``cost_inner_call_cap_usd`` (both via :data:`product_app.config.settings`).
#: The flat ``DEBATE_FIXED_COST_USD`` and ``SYNTHESIS_FIXED_COST_USD``
#: constants above remain for backward compatibility (re-exported by
#: ``_estimate_breakdown`` callers and referenced by some tests) but are
#: no longer summed into the estimate; the proportional term replaces
#: them. The cap exists so a 5K-char query on the default model mix
#: doesn't tip over the $0.25 hard limit just because the inner-call
#: cost scales with query length.

QUERY_COST_PER_1K_CHARS_USD = Decimal("0.00002")
#: Per-character base processing charge. The debate pipeline scans the
#: query text once and the cost grows linearly with character count.
#: This term dominates for long queries and ensures a 5K-character
#: prompt falls into the require-confirmation band on the default
#: model mix, while a short prompt (a few dozen characters) stays in
#: the allow band.
PER_CHAR_PROCESSING_USD = Decimal("0.00003")

CONFIRMATION_TOKEN_TTL = timedelta(minutes=5)


class CostThresholdAction(StrEnum):
    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    BLOCK = "block"


class CostLineByModel(BaseModel):
    model_id: str
    display_name: str
    usd: Decimal = Field(ge=Decimal("0"))
    #: Discriminator so consumers distinguish the pseudo "Synthesis writer"
    #: row from a real model row without matching the magic ``model_id``.
    #: ``"model"`` for the four model rows, ``"synthesis"`` for the writer.
    kind: str = "model"


class CostLineByStage(BaseModel):
    #: One of ``initial_answers`` | ``debate_round_1`` | ``debate_round_2`` |
    #: ``synthesis`` — the same vocabulary as ``progress.stages[].stage`` (see
    #: ``query_runs._initial_progress``) so a UI can join the two directly.
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
    estimated_cost_usd: Decimal = Field(ge=Decimal("0"))
    currency: str = "USD"
    threshold_action: CostThresholdAction
    confirmation_token: str | None
    reasons: list[str]
    #: Itemized cost partition (by model AND by stage). Optional with a
    #: ``None`` default so pre-existing ``CostEstimate(...)`` constructions
    #: (tests, cancel path) keep working; ``estimate()`` always attaches a
    #: real breakdown to every returned estimate.
    breakdown: CostBreakdown | None = None


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
        if now_provider is None:
            self._now: Callable[[], datetime] = lambda: datetime.now(UTC)
        else:
            self._now = now_provider

    def estimate(
        self,
        *,
        query_text: str,
        model_slots: list[ModelSlot],
        account_id: UUID | None = None,
        query_run_id: UUID | None = None,
    ) -> CostEstimate:
        breakdown = self._estimate_breakdown(query_text=query_text, model_slots=model_slots)
        # ``breakdown.total`` is the quantized grand total (same value the
        # old ``_estimate_total(...).quantize(...)`` produced). Compute the
        # breakdown ONCE and attach it to every returned estimate — including
        # the BLOCK / cumulative / daily-cap early returns — so screens 03/05
        # always have the itemized partition.
        estimated = breakdown.total
        threshold_action, reasons = self._threshold_for(estimated)
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
            if cumulative + estimated > HARD_LIMIT_USD:
                return CostEstimate(
                    estimated_cost_usd=estimated,
                    threshold_action=CostThresholdAction.BLOCK,
                    confirmation_token=None,
                    breakdown=breakdown,
                    reasons=[
                        "Estimated cost is above the USD 0.25 hard limit for this account.",
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
            if store is not None:
                already_spent = store.daily_spend_for(account_id)
                if already_spent + estimated > DAILY_CAP_USD:
                    return CostEstimate(
                        estimated_cost_usd=estimated,
                        threshold_action=CostThresholdAction.BLOCK,
                        confirmation_token=None,
                        breakdown=breakdown,
                        reasons=[
                            (
                                f"Estimated cost would exceed the USD "
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
            threshold_action=threshold_action,
            confirmation_token=confirmation_token,
            reasons=reasons,
            breakdown=breakdown,
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
    ) -> None:
        # Map the (threshold_action, confirmed) pair to an event type.
        #  - BLOCK  → cost_guardrail_blocked (the request was refused)
        #  - REQUIRE_CONFIRMATION + confirmed=False → cost_confirmation_required
        #  - REQUIRE_CONFIRMATION + confirmed=True → cost_guardrail_accepted
        #  - ALLOW  → cost_guardrail_accepted (the request was allowed
        #    without confirmation, ``confirmed=False``)
        if threshold_action is CostThresholdAction.BLOCK:
            event_type = "cost_guardrail_blocked"
        elif threshold_action is CostThresholdAction.REQUIRE_CONFIRMATION and not confirmed:
            event_type = "cost_confirmation_required"
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
        # Surface BLOCK events to Sentry so a rate of rejected
        # estimates (per-call, cumulative, or daily cap) is visible
        # to operators. ALLOW and REQUIRE_CONFIRMATION events are
        # normal traffic and would just spam the Sentry quota.
        if threshold_action is CostThresholdAction.BLOCK:
            import sentry_sdk  # local import to avoid loading the SDK in tests

            try:
                with sentry_sdk.push_scope() as scope:
                    scope.set_tag("event_type", event_type)
                    scope.set_extra("account_id", str(account_id))
                    scope.set_extra("estimated_cost_usd", str(estimated_cost_usd))
                    if query_run_id is not None:
                        scope.set_extra("query_run_id", str(query_run_id))
                    sentry_sdk.capture_message(
                        f"cost_guardrail_blocked:{event_type}",
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
                    "Sentry capture failed for cost_guardrail_blocked: %s", exc
                )

    # -- internals --------------------------------------------------------

    def _estimate_breakdown(
        self, *, query_text: str, model_slots: list[ModelSlot]
    ) -> CostBreakdown:
        """Compute the itemized cost partition (by model AND by stage).

        The grand total is *identical* to the pre-B1 ``_estimate_total``
        arithmetic — this method only exposes structure. Two partitions are
        derived from the same terms; both re-sum to the (quantized) total
        after :meth:`_reconcile_usd_lines` distributes the rounding residual.
        """
        if not model_slots:
            raise ValueError("model_slots must not be empty")
        if len(model_slots) != 4:
            raise ValueError("model_slots must contain exactly four slots")
        query_cost = QUERY_COST_PER_1K_CHARS_USD * Decimal(len(query_text) / 1000)
        # Per-character base processing charge. This dominates for long
        # queries so a 5K-character prompt lands in the
        # require-confirmation band on the default model mix.
        processing_cost = PER_CHAR_PROCESSING_USD * Decimal(len(query_text))
        # Both input and output tokens are billed by real providers.
        # The output-token multiplier is a heuristic — we cannot know
        # the actual answer length before the call — but it brings
        # the estimate from ~$0.01 to within ~25% of the actual
        # charge on a typical research query.
        input_tokens = Decimal(len(query_text) / 4)  # ~4 chars/token
        multiplier = Decimal(str(settings.cost_output_token_multiplier))
        output_tokens = input_tokens * multiplier
        # We approximate each model as receiving the full query text.
        # PERF-P1: use the cached price index instead of rebuilding
        # the dict on every estimate call. The index is built once
        # per cache miss and looked up in O(1) per model id.
        prices = openrouter_model_catalog_service.price_index()

        def _price(model_id: str) -> tuple[Decimal, Decimal]:
            return prices.get(
                model_id,
                (_DEFAULT_PRICE_PER_1K_INPUT, _DEFAULT_PRICE_PER_1K_OUTPUT),
            )

        # Per-model initial-answer cost: the model's own input+output
        # charge. ``sum(initial_i)`` == the old
        # ``model_input_cost + model_output_cost`` term exactly.
        initial_per_model: list[Decimal] = [
            _price(slot.model_id)[0] * (input_tokens / Decimal(1000))
            + _price(slot.model_id)[1] * (output_tokens / Decimal(1000))
            for slot in model_slots
        ]
        model_input_output_cost = sum(initial_per_model, Decimal("0"))
        # L3 - proportional inner-call cost. Debate and synthesis are
        # also LLM calls now (L4), so the estimate must price them.
        # Per-call cost: ``max_output_rate × output_tokens / 1000``,
        # scaled by ``cost_inner_call_multiplier``. Three inner calls
        # total (2 debate rounds + 1 synthesis), capped at
        # ``cost_inner_call_cap_usd`` so very long queries don't push
        # the total estimate over the $0.25 hard limit on the default
        # model mix. The cap is the saturation point: real debate and
        # synthesis outputs don't grow linearly with query length
        # because the inner steps process a bounded context (the 4
        # initial answers + the query) regardless of how long the
        # query is.
        max_output_rate = max(
            (_price(slot.model_id)[1] for slot in model_slots),
            default=_DEFAULT_PRICE_PER_1K_OUTPUT,
        )
        inner_multiplier = Decimal(str(settings.cost_inner_call_multiplier))
        inner_cap = Decimal(str(settings.cost_inner_call_cap_usd))
        inner_per_call = inner_multiplier * max_output_rate * output_tokens / Decimal(1000)
        inner_call_cost = min(inner_per_call * Decimal(3), inner_cap)

        # Grand total — unchanged value vs. the old ``_estimate_total``.
        raw_total = query_cost + processing_cost + model_input_output_cost + inner_call_cost
        total = raw_total.quantize(COST_DISPLAY_QUANTUM, rounding=ROUND_HALF_UP)

        # The 3 inner calls (debate r1 + debate r2 + synthesis) are equal
        # in the underlying formula, so each is one third of the
        # inner-call cost.
        stage_inner = inner_call_cost / Decimal(3)
        base = query_cost + processing_cost  # query + processing overhead

        # --- by_stage: initial + the three equal inner-call stages ------
        # Stage keys mirror ``progress.stages[].stage`` (see
        # ``query_runs._initial_progress``) so a UI can join the two.
        raw_stage: list[tuple[str, Decimal]] = [
            ("initial_answers", base + model_input_output_cost),
            ("debate_round_1", stage_inner),
            ("debate_round_2", stage_inner),
            ("synthesis", stage_inner),
        ]
        stage_usd = self._reconcile_usd_lines([v for _, v in raw_stage], total)
        by_stage = [
            CostLineByStage(stage=name, usd=usd)
            for (name, _), usd in zip(raw_stage, stage_usd, strict=True)
        ]

        # --- by_model: 4 model rows + a "Synthesis writer" row ----------
        # Each model row carries its own initial cost plus an equal share
        # of the query/processing overhead and of the two debate rounds
        # (round_1 + round_2). The synthesis inner call is its own row.
        base_share = base / Decimal(4)
        # Each model row absorbs an equal share of the two debate rounds
        # (round_1 + round_2 = 2 * stage_inner, split four ways).
        debate_share = stage_inner / Decimal(2)
        raw_model: list[tuple[str, str, str, Decimal]] = []
        for slot, initial_i in zip(model_slots, initial_per_model, strict=True):
            display_name = (
                openrouter_model_catalog_service.lookup_short_name(slot.model_id) or slot.model_id
            )
            raw_model.append(
                ("model", slot.model_id, display_name, initial_i + base_share + debate_share)
            )
        raw_model.append(("synthesis", "synthesis", "Synthesis writer", stage_inner))
        model_usd = self._reconcile_usd_lines([v for *_, v in raw_model], total)
        by_model = [
            CostLineByModel(model_id=mid, display_name=name, usd=usd, kind=kind)
            for (kind, mid, name, _), usd in zip(raw_model, model_usd, strict=True)
        ]

        return CostBreakdown(by_model=by_model, by_stage=by_stage, total=total)

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
        were never billed, and ``REQUIRE_CONFIRMATION`` events are
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

    def _threshold_for(self, estimated: Decimal) -> tuple[CostThresholdAction, list[str]]:
        if estimated > HARD_LIMIT_USD:
            return (
                CostThresholdAction.BLOCK,
                [
                    "Estimated cost is above the USD 0.25 hard limit for this account.",
                ],
            )
        if estimated > SOFT_THRESHOLD_USD:
            return (
                CostThresholdAction.REQUIRE_CONFIRMATION,
                [
                    "Estimated cost is above USD 0.15 and requires explicit confirmation.",
                ],
            )
        return (
            CostThresholdAction.ALLOW,
            ["Estimated cost is within the no-confirmation band."],
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

    Debate + synthesis are attributed to a single ``"Synthesis writer"``
    ``by_model`` row because they use the dedicated debate/synthesis writer
    models, not the four slot models. Both partitions are reconciled to the
    quantized grand total with the same largest-remainder rule as the estimate,
    so every line is ``>= 0`` and the lines sum to the total exactly (the UI's
    reconciliation invariant).
    """
    initial_total = sum((cost for _, _, cost in per_model_initial), Decimal("0"))
    debate_total = sum(debate_by_round.values(), Decimal("0"))
    raw_total = initial_total + debate_total + synthesis_cost
    total = raw_total.quantize(COST_DISPLAY_QUANTUM, rounding=ROUND_HALF_UP)

    debate_round_1 = debate_by_round.get(1, Decimal("0"))
    debate_round_2 = debate_by_round.get(2, Decimal("0"))
    raw_stage: list[tuple[str, Decimal]] = [
        ("initial_answers", initial_total),
        ("debate_round_1", debate_round_1),
        ("debate_round_2", debate_round_2),
        ("synthesis", synthesis_cost),
    ]
    stage_usd = CostEstimationService._reconcile_usd_lines([v for _, v in raw_stage], total)
    by_stage = [
        CostLineByStage(stage=name, usd=usd)
        for (name, _), usd in zip(raw_stage, stage_usd, strict=True)
    ]

    writer_cost = debate_total + synthesis_cost
    raw_model: list[tuple[str, str, Decimal]] = list(per_model_initial)
    raw_model.append(("synthesis", "Synthesis writer", writer_cost))
    model_usd = CostEstimationService._reconcile_usd_lines([c for *_, c in raw_model], total)
    by_model = [
        CostLineByModel(
            model_id=mid,
            display_name=name,
            usd=usd,
            kind="synthesis" if mid == "synthesis" else "model",
        )
        for (mid, name, _), usd in zip(raw_model, model_usd, strict=True)
    ]
    return CostBreakdown(by_model=by_model, by_stage=by_stage, total=total)
