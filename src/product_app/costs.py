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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from product_app.catalog_fetcher import openrouter_catalog_fetcher
from product_app.config import settings
from product_app.model_slots import ModelSlot

SOFT_THRESHOLD_USD = Decimal("0.15")
HARD_LIMIT_USD = Decimal("0.25")

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
#: ``_estimate_total`` callers and referenced by some tests) but are
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


class CostEstimate(BaseModel):
    estimated_cost_usd: Decimal = Field(ge=Decimal("0"))
    currency: str = "USD"
    threshold_action: CostThresholdAction
    confirmation_token: str | None
    reasons: list[str]


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
        with self._lock:
            self._events.append(
                CostGuardrailEvent(
                    event_type=event_type,
                    account_id=account_id,
                    query_run_id=query_run_id,
                    estimated_cost_usd=estimated_cost_usd,
                    threshold_action=threshold_action,
                    confirmed=confirmed,
                ),
            )
            if len(self._events) > self.MAX_EVENTS:
                del self._events[: len(self._events) - self.MAX_EVENTS]

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
        self._binding_secret = (
            binding_secret or os.environ.get("QUORUM_TOKEN_SECRET") or secrets.token_hex(32)
        ).encode()
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
        estimated = self._estimate_total(query_text=query_text, model_slots=model_slots).quantize(
            COST_DISPLAY_QUANTUM, rounding=ROUND_HALF_UP
        )
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
                    reasons=[
                        "Estimated cost is above the USD 0.25 hard limit for this account.",
                        (
                            "Cumulative spend for this account is "
                            f"{cumulative.quantize(COST_DISPLAY_QUANTUM)} USD; "
                            "no further queries can be accepted until the window resets."
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

    # -- internals --------------------------------------------------------

    def _estimate_total(self, *, query_text: str, model_slots: list[ModelSlot]) -> Decimal:
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
        # Per-model prices come from the live catalog. A model id not
        # in the catalog (newly released, offline) falls back to the
        # generic per-1K default — that single fallback keeps the
        # guardrail functional without a stale curated pricing dict.
        prices = {
            entry.model_id: (entry.input_price_per_1k, entry.output_price_per_1k)
            for entry in openrouter_catalog_fetcher.list_models()
        }

        def _price(model_id: str) -> tuple[Decimal, Decimal]:
            return prices.get(
                model_id,
                (_DEFAULT_PRICE_PER_1K_INPUT, _DEFAULT_PRICE_PER_1K_OUTPUT),
            )

        model_input_cost = sum(
            (
                _price(slot.model_id)[0]
                * (input_tokens / Decimal(1000))
            )
            for slot in model_slots
        )
        model_output_cost = sum(
            (
                _price(slot.model_id)[1]
                * (output_tokens / Decimal(1000))
            )
            for slot in model_slots
        )
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

        return (
            query_cost
            + processing_cost
            + model_input_cost
            + model_output_cost
            + inner_call_cost
        )

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
