"""Structured debate orchestration.

The debate is a two-round audit pass over the initial model answers. Each
round writes a short critique focused on three dimensions: explicit
disagreement, weak source support, and missing reasoning. The orchestrator
records per-round events with the ``account_id`` and ``query_run_id`` so
they can be observed without leaking the user query text.

Starting in L4, each round is produced by a live LLM call (using the
``debate_model_id`` setting — Haiku 4.5 by default) when a key is
configured; otherwise the round falls back to the templated critique.
The fallback path is also used when the live call fails for any reason.
This keeps the run usable end-to-end while the headline feature is the
real LLM-driven critique.

Anti-goals: no round may include the raw provider API key, the user query
text, or any other secret. The orchestrator also never blocks the request
thread — debate failures degrade gracefully to a partial result.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from threading import RLock
from time import perf_counter
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from product_app.config import RuntimeEnvironment, settings
from product_app.costs import CHARS_PER_TOKEN
from product_app.feedback_store import record_event as _record_feedback_event
from product_app.model_slots import ModelSlot
from product_app.providers import (
    InitialAnswerStatus,
    InitialModelAnswer,
    LiveProviderResult,
    ProviderPath,
    TokenUsage,
    provider_execution_service,
)
from product_app.safety import (
    SafetyAcknowledgement,
)
from product_app.untrusted_text import UNTRUSTED_DATA_SYSTEM_RULE, fence
from product_app.visible_text import is_visible

DEBATE_HARD_TIMEOUT_MS = 180_000

#: Token cap per debate round. WP-D (F-07) raised this from 700 to
#: 2000: at 700 the moderator was clipping substantive critiques
#: mid-sentence, and the critique text is what the synthesis
#: uncertainty section leans on, so the truncation propagated.
#:
#: This MUST stay in sync with ``settings.cost_debate_output_tokens_cap``
#: (``config.py``), which is what the fail-safe ``max_cost_usd`` bound
#: prices the debate stage at. If the enforced cap here exceeds the
#: priced cap there, the "bound" stops being a true ceiling and the
#: cost rails silently under-protect. ``tests/unit/
#: test_estimate_token_model.py::test_bound_cap_assumptions_match_the_
#: enforced_caps`` pins the two together.
DEBATE_ROUND_MAX_TOKENS = 2000

#: How much of each initial answer the debate moderator gets to see.
#:
#: WP-D (F-08) replaced a hardcoded ``[:200]`` here. 200 chars is roughly one
#: sentence: the moderator was being asked to find "specific points of
#: disagreement" while seeing only each model's opening clause, so it could
#: only ever critique the framing, never the substance.
#:
#: DERIVED, not a literal. An initial answer's length is bounded by the token
#: cap on the call that produced it (``settings.initial_answer_max_tokens``,
#: enforced in ``providers.py``), so this is exactly "as much as can exist"
#: and it tracks that cap automatically. Hardcoding 8000 would silently
#: decouple the next time the answer cap moves.
DEBATE_ANSWER_EXCERPT_MAX_CHARS = int(settings.initial_answer_max_tokens * CHARS_PER_TOKEN)

FOCUS_AREAS: tuple[str, ...] = ("disagreement", "weak_support", "missing_reasoning")
HIGH_STAKES_NOTICE_FRAGMENT = (
    "This summary is decision support only and is not medical, legal, "
    "financial, safety, or regulated professional advice."
)


# System prompts for the two rounds. Each one is intentionally narrow:
# the model is told to read the four answers, focus on one round's
# lens, and produce a short structured critique. Keeping the prompt
# focused is the difference between a useful critique and the model
# padding the response with hedging.
ROUND_ONE_SYSTEM_PROMPT = (
    "You are a debate moderator. Read the four model answers below. "
    "Identify specific points of disagreement and specific points of "
    "weak or missing source support. Cite the model names and quote "
    "the specific passage. Be concrete; do not write generic 'they "
    "differ on X' phrasing. The output is for a human reviewer, not "
    "the user.\n\n" + UNTRUSTED_DATA_SYSTEM_RULE
)

ROUND_TWO_SYSTEM_PROMPT = (
    "You are a debate moderator refining the round 1 critique. Focus "
    "specifically on (a) the strongest residual disagreements after "
    "round 1, and (b) reasoning the round 1 critique flagged as "
    "missing. Cite the model names and quote the specific passage. "
    "Be concrete. The output is for a human reviewer, not the user.\n\n"
    + UNTRUSTED_DATA_SYSTEM_RULE
)


class DebateRoundStatus(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"


#: The two values ``DebateOutput.debate_mode`` can take. Named constants for the
#: same reason ``synthesis.py`` names ``SYNTHESIS_MODE_LIVE`` /
#: ``SYNTHESIS_MODE_FALLBACK``: since #171 finding 5 the value is READ, not just
#: written, so a producer/consumer spelling drift must fail loudly rather than
#: silently restore the defect this field exists to close.
#:
#: ``"live"`` = the round's critique came from the configured debate moderator's
#: own response. ``"fallback"`` = the moderator was not configured, or its call
#: made no usable text, and the critique is this product's own template
#: (:meth:`DebateOrchestrationService._build_round_one_text` /
#: ``_build_round_two_text``).
DEBATE_MODE_LIVE = "live"
DEBATE_MODE_FALLBACK = "fallback"

#: Every value :data:`DebateOutput.debate_mode` can hold, as a set, so a test can
#: cover both without retyping the members (``AGENTS.md`` rule 7a).
DEBATE_MODES: frozenset[str] = frozenset({DEBATE_MODE_LIVE, DEBATE_MODE_FALLBACK})


class DebateOutput(BaseModel):
    round_number: int = Field(ge=1, le=2)
    focus_areas: list[str]
    critique_text: str
    status: DebateRoundStatus
    #: Structural provenance for this ONE round — see :data:`DEBATE_MODE_LIVE` /
    #: :data:`DEBATE_MODE_FALLBACK`. Defaults to the fallback value: a caller
    #: that constructs a ``DebateOutput`` without stating otherwise gets the
    #: conservative reading (assume templated, not live), matching
    #: ``FinalSynthesis.synthesis_mode``'s default of
    #: ``SYNTHESIS_MODE_SIMULATED``.
    debate_mode: str = DEBATE_MODE_FALLBACK


@dataclass(frozen=True)
class DebateRoundEvent:
    event_type: str
    account_id: UUID
    query_run_id: UUID
    round_number: int
    focus_areas: tuple[str, ...]
    duration_ms: int
    status: DebateRoundStatus
    timed_out: bool


class InMemoryDebateEventRecorder:
    """Bounded recorder for debate round events."""

    MAX_EVENTS = 512

    def __init__(self) -> None:
        self._events: list[DebateRoundEvent] = []
        self._lock = RLock()

    def record(
        self,
        *,
        event_type: str,
        account_id: UUID,
        query_run_id: UUID,
        round_number: int,
        focus_areas: tuple[str, ...],
        duration_ms: int,
        status: DebateRoundStatus,
        timed_out: bool,
    ) -> None:
        event = DebateRoundEvent(
            event_type=event_type,
            account_id=account_id,
            query_run_id=query_run_id,
            round_number=round_number,
            focus_areas=focus_areas,
            duration_ms=duration_ms,
            status=status,
            timed_out=timed_out,
        )
        with self._lock:
            self._events.append(event)
            if len(self._events) > self.MAX_EVENTS:
                del self._events[: len(self._events) - self.MAX_EVENTS]
        _record_feedback_event(
            recorder="debate",
            event_type=event.event_type,
            account_id=event.account_id,
            query_run_id=event.query_run_id,
            payload=asdict(event),
        )

    def list_events(self) -> list[DebateRoundEvent]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


@dataclass(frozen=True)
class DebateResult:
    debate_outputs: list[DebateOutput]
    failed_steps: list[str]
    missing_steps: list[str]
    timed_out: bool
    round_timings_ms: dict[int, int]
    #: One entry per debate round that actually made a live moderator call
    #: (a templated/skipped round contributes NO entry — it was not billed).
    #: Each entry is ``(round_number, usage)``; ``usage`` is the call's
    #: captured :class:`TokenUsage`, or ``None`` when the live call succeeded
    #: but the provider omitted the usage object. The round number is carried
    #: so the cost layer attributes each cost to the RIGHT ``by_stage`` round
    #: (a round-2-only live run must not be labelled ``debate_round_1``).
    live_call_usages: list[tuple[int, TokenUsage | None]] = field(default_factory=list)


class DebateOrchestrationService:
    """Produces structured two-round debate output from initial answers.

    Round two is the budget-checked step: if the request has been running
    for more than ``DEBATE_HARD_TIMEOUT_MS`` since round one started, the
    second round is reported as ``SKIPPED`` with the budget exceeded reason
    and the run degrades to a partial result.

    L4: each round's critique text is produced by a live LLM call when
    a key is configured; otherwise the templated critique is used. The
    LLM call is opt-in: a missing key or a hard LLM failure both fall
    back to the template. A failed round is NOT treated as a pipeline
    failure — the run still produces a useful synthesis from the
    templated text.

    Which happened is recorded STRUCTURALLY on each round
    (:attr:`DebateOutput.debate_mode`), not narrated in prose. #171
    finding 5 measured that an earlier version of this docstring claimed
    the fallback added a notice to the response-level
    ``provider_failure_notices`` — it never did; the notice text was
    built and discarded. That shared list is populated only from
    initial-answer failures, and folding a per-round debate signal into
    it would conflate two different things and, since live execution
    defaults off, surface on nearly every existing demo-mode run.
    ``debate_mode`` is the honest, scoped fix: a queryable field, not a
    notice competing for space in an unrelated list.
    """

    def __init__(self, *, hard_timeout_ms: int = DEBATE_HARD_TIMEOUT_MS) -> None:
        self._hard_timeout_ms = hard_timeout_ms

    def run_debate_rounds(
        self,
        *,
        account_id: UUID,
        query_run_id: UUID,
        query_text: str,
        initial_answers: list[InitialModelAnswer],
        model_slots: list[ModelSlot] | None = None,
        safety_acknowledgements: list[SafetyAcknowledgement] | None = None,
        openrouter_key: str = "",
        context: dict[str, Any] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> DebateResult:
        if model_slots is None:
            model_slots = []
        if safety_acknowledgements is None:
            safety_acknowledgements = []
        started_at = perf_counter()
        debate_outputs: list[DebateOutput] = []
        failed_steps: list[str] = []
        missing_steps: list[str] = []
        round_timings_ms: dict[int, int] = {}
        live_call_usages: list[tuple[int, TokenUsage | None]] = []

        # Round 1 always runs. The orchestrator pulls disagreement, weak
        # support, and missing reasoning signals from the initial answers
        # to produce a critique text that the synthesis step can build on.
        round_one_started = perf_counter()
        round_one_text, round_one_fallback, round_one_live = self._build_round_one_text(
            initial_answers=initial_answers,
            query_text=query_text,
            openrouter_key=openrouter_key,
            context=context,
            should_stop=should_stop,
        )
        round_one_ms = max(1, round((perf_counter() - round_one_started) * 1000))
        round_timings_ms[1] = round_one_ms
        round_one_mode = (
            DEBATE_MODE_FALLBACK if round_one_fallback is not None else DEBATE_MODE_LIVE
        )
        # A non-None live result means a billed moderator call happened; record
        # it against round 1 (usage may itself be None if the provider omitted it).
        if round_one_live is not None:
            live_call_usages.append((1, round_one_live.usage))
        debate_event_recorder.record(
            event_type="debate_round_completed",
            account_id=account_id,
            query_run_id=query_run_id,
            round_number=1,
            focus_areas=FOCUS_AREAS,
            duration_ms=round_one_ms,
            status=DebateRoundStatus.COMPLETED,
            timed_out=False,
        )
        debate_outputs.append(
            DebateOutput(
                round_number=1,
                focus_areas=list(FOCUS_AREAS),
                critique_text=round_one_text,
                status=DebateRoundStatus.COMPLETED,
                debate_mode=round_one_mode,
            ),
        )

        # Round 2 is skipped if the per-run debate budget has been
        # exhausted, or if the developer trigger phrase is present in the
        # query (used by the test suite to assert partial results).
        elapsed_ms = (perf_counter() - started_at) * 1000
        budget_exceeded = self._should_skip_round_two(
            elapsed_ms=elapsed_ms,
            query_text=query_text,
        )
        if budget_exceeded:
            round_timings_ms[2] = max(1, int(elapsed_ms))
            debate_event_recorder.record(
                event_type="debate_round_skipped",
                account_id=account_id,
                query_run_id=query_run_id,
                round_number=2,
                focus_areas=FOCUS_AREAS,
                duration_ms=round_timings_ms[2],
                status=DebateRoundStatus.SKIPPED,
                timed_out=True,
            )
            failed_steps.append("debate_round_2")
            missing_steps.extend(["debate_round_2", "synthesis"])
            return DebateResult(
                debate_outputs=debate_outputs,
                failed_steps=failed_steps,
                missing_steps=missing_steps,
                timed_out=True,
                round_timings_ms=round_timings_ms,
                live_call_usages=live_call_usages,
            )

        round_two_started = perf_counter()
        round_two_text, round_two_fallback, round_two_live = self._build_round_two_text(
            initial_answers=initial_answers,
            query_text=query_text,
            round_one_text=round_one_text,
            openrouter_key=openrouter_key,
            context=context,
            should_stop=should_stop,
        )
        round_two_ms = max(1, round((perf_counter() - round_two_started) * 1000))
        round_timings_ms[2] = round_two_ms
        round_two_mode = (
            DEBATE_MODE_FALLBACK if round_two_fallback is not None else DEBATE_MODE_LIVE
        )
        if round_two_live is not None:
            live_call_usages.append((2, round_two_live.usage))
        debate_event_recorder.record(
            event_type="debate_round_completed",
            account_id=account_id,
            query_run_id=query_run_id,
            round_number=2,
            focus_areas=FOCUS_AREAS,
            duration_ms=round_two_ms,
            status=DebateRoundStatus.COMPLETED,
            timed_out=False,
        )
        debate_outputs.append(
            DebateOutput(
                round_number=2,
                focus_areas=list(FOCUS_AREAS),
                critique_text=round_two_text,
                status=DebateRoundStatus.COMPLETED,
                debate_mode=round_two_mode,
            ),
        )

        return DebateResult(
            debate_outputs=debate_outputs,
            failed_steps=failed_steps,
            missing_steps=missing_steps,
            timed_out=False,
            round_timings_ms=round_timings_ms,
            live_call_usages=live_call_usages,
        )

    def _should_skip_round_two(self, *, elapsed_ms: float, query_text: str) -> bool:
        if elapsed_ms > self._hard_timeout_ms:
            return True
        # Magic phrase ``"force debate timeout"`` is a test-only knob.
        # See ``providers._should_force_provider_failure`` for the
        # rationale on gating the user-query phrase to
        # ``runtime_environment=LOCAL``. The hard-timeout path is not
        # gated — it is a real production safety.
        if settings.runtime_environment is not RuntimeEnvironment.LOCAL:
            return False
        return "force debate timeout" in query_text.lower()

    def _build_round_one_text(
        self,
        *,
        initial_answers: list[InitialModelAnswer],
        query_text: str,
        openrouter_key: str,
        context: dict[str, Any] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> tuple[str, str | None, LiveProviderResult | None]:
        disagreement = self._extract_disagreement(initial_answers=initial_answers)
        weak_support = self._extract_weak_support(initial_answers=initial_answers)
        missing = self._extract_missing_reasoning(initial_answers=initial_answers)
        templated = (
            "Round 1 critique.\n"
            f"Disagreement: {disagreement}\n"
            f"Weak support: {weak_support}\n"
            f"Missing reasoning: {missing}\n"
            "Query context preserved without re-quoting the user prompt."
        )
        live = self._call_debate_model(
            openrouter_key=openrouter_key,
            system_prompt=ROUND_ONE_SYSTEM_PROMPT,
            user_prompt=self._debate_user_prompt(
                query_text=query_text,
                initial_answers=initial_answers,
                prior_round=None,
            ),
            context=context,
            should_stop=should_stop,
        )
        # F-06: ``live`` is non-None whenever the call MAY HAVE BEEN BILLED,
        # even if its output was unusable — a request the provider refused
        # before inference (404, bad key, rate limit) arrives as ``None``
        # instead, with nothing to record. Blank text therefore means "fall
        # back to the templated critique" while STILL returning the result, so
        # its usage is recorded and a billed call cannot vanish.
        text = "" if live is None else live.answer_text.strip()
        if not is_visible(text):
            return templated, self._debate_fallback_notice(round_number=1), live
        return text, None, live

    def _build_round_two_text(
        self,
        *,
        initial_answers: list[InitialModelAnswer],
        query_text: str,
        round_one_text: str,
        openrouter_key: str,
        context: dict[str, Any] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> tuple[str, str | None, LiveProviderResult | None]:
        disagreement = self._extract_disagreement(initial_answers=initial_answers)
        weak_support = self._extract_weak_support(initial_answers=initial_answers)
        missing = self._extract_missing_reasoning(initial_answers=initial_answers)
        templated = (
            "Round 2 critique, refining round 1.\n"
            f"Refined disagreement: {disagreement}\n"
            f"Refined weak support: {weak_support}\n"
            f"Refined missing reasoning: {missing}\n"
            "Round 2 narrows to the strongest residual concerns without re-quoting the user prompt."
        )
        live = self._call_debate_model(
            openrouter_key=openrouter_key,
            system_prompt=ROUND_TWO_SYSTEM_PROMPT,
            user_prompt=self._debate_user_prompt(
                query_text=query_text,
                initial_answers=initial_answers,
                prior_round=round_one_text,
            ),
            context=context,
            should_stop=should_stop,
        )
        # F-06: see ``_build_round_one_text`` — blank text means a call that may
        # have been billed came back unusable, not that no call was made.
        text = "" if live is None else live.answer_text.strip()
        if not is_visible(text):
            return templated, self._debate_fallback_notice(round_number=2), live
        return text, None, live

    def _call_debate_model(
        self,
        *,
        openrouter_key: str,
        system_prompt: str,
        user_prompt: str,
        context: dict[str, Any] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> LiveProviderResult | None:
        """Call the configured debate model.

        Returns exactly what ``call_with_prompt`` returned, and its F-06
        billing contract is the reason this method adds nothing of its own:

        * ``None`` — nothing was billed. Either an opt-in guard below stopped
          us before any request left the process, or the provider refused the
          request before inference. The caller records NO usage entry.
        * a result with BLANK ``answer_text`` — a request was dispatched and
          may have been billed (an empty completion that still consumed
          tokens, a 5xx, a read timeout, a torn body). The caller falls back
          to the templated critique but STILL records the entry, so an
          unmeasurable charge downgrades the receipt to ``estimated`` instead
          of vanishing through ``_actual_cost``'s ``all([])`` gate.
        * a result with text — the normal case.

        The four model answers are summarised, not re-quoted, to keep the
        prompt within budget.
        """
        # The live-execution flag is the operator's opt-in switch;
        # we honour it here the same way ``provider_execution_service``
        # does for the initial model answers. Without this guard the
        # debate would call out to the network even when the operator
        # explicitly disabled live execution for the run.
        if not settings.openrouter_live_execution_enabled:
            return None
        if not openrouter_key or not settings.debate_model_id:
            return None
        # F-05 Layer 2 (#106): a cancel that lands between rounds must stop
        # the NEXT round from billing at all. Checked here rather than in
        # ``run_debate_rounds`` because this is the one seam both rounds
        # dispatch through — round 1's own in-flight call cannot be un-billed
        # by this check, only the round that has not yet been dispatched.
        if should_stop is not None and should_stop():
            return None
        # No post-processing: the provider seam already encodes "not billed"
        # (``None``) versus "dispatched, maybe billed, unusable" (blank text).
        # Collapsing the two here is precisely the F-06 defect.
        result = provider_execution_service.call_with_prompt(
            openrouter_key=openrouter_key,
            model_id=settings.debate_model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=DEBATE_ROUND_MAX_TOKENS,
            context=context,
        )
        # Issue #290: stamp the model actually dispatched onto the usage
        # record, at the one seam that knows both. Today ``model_id`` above
        # is always ``settings.debate_model_id`` (there is only ever one
        # debate caller), so this carries no visible change in production
        # yet. The billing layer (``query_run_orchestration._actual_cost``)
        # now prices each debate usage record from THIS field, falling back
        # to ``settings.debate_model_id`` only when it is absent (a record
        # from before this field existed). That is the fix: pricing no
        # longer blanket-assumes every debate call in a run was billed at
        # one model id, which is false the moment a debate call dispatches
        # a model other than the configured moderator (peer critique, #290's
        # own follow-on work, is exactly that case).
        if result is not None and result.usage is not None:
            result = replace(
                result, usage=result.usage.model_copy(update={"model_id": settings.debate_model_id})
            )
        return result

    def _debate_user_prompt(
        self,
        *,
        query_text: str,
        initial_answers: list[InitialModelAnswer],
        prior_round: str | None,
    ) -> str:
        # WP-D (F-08): the moderator now sees each answer in full rather than
        # its first 200 chars. The old comment here ("we summarise each model
        # answer rather than re-quoting it in full") described a deliberate
        # design that turned out to defeat the stage's purpose — a moderator
        # asked to quote "the specific passage" that disagrees cannot do so
        # from an opening clause.
        #
        # The prompt has TWO parts, and the split is the point. Our own
        # directives stay OUTSIDE the fence; only provider- and user-originated
        # text goes inside it. Fencing the whole message would put our own
        # instructions ("do NOT repeat the query") inside a block whose system
        # rule tells the model to ignore instructions — self-defeating.
        directives: list[str] = [
            "The user's question and the four model answers are in the evidence "
            "block below. Do NOT repeat the question verbatim in your response.",
        ]
        if prior_round is not None:
            directives.append(
                "The block also carries the round 1 critique, for context. Do NOT repeat it."
            )

        # Untrusted from here down.
        lines: list[str] = []
        lines.append("User query:")
        lines.append(query_text)
        lines.append("")
        lines.append(
            "Four model answers (model name, status, first "
            f"{DEBATE_ANSWER_EXCERPT_MAX_CHARS} chars):"
        )
        for answer in initial_answers:
            excerpt = (
                (answer.answer_text or "")
                .strip()
                .replace("\n", " ")[:DEBATE_ANSWER_EXCERPT_MAX_CHARS]
            )
            # ``display_name`` is the catalog's short label
            # ("Claude Haiku 4.5"). Falling back to ``model_id`` keeps
            # the prompt well-formed even if the catalog is unaware
            # of the model.
            label = answer.display_name or answer.model_id
            lines.append(f"- {label} ({answer.status.value}): {excerpt}")
        if prior_round is not None:
            lines.append("")
            lines.append("Round 1 critique:")
            lines.append(prior_round)
        return "\n".join(directives) + "\n\n" + fence("\n".join(lines))

    def _debate_fallback_notice(self, *, round_number: int) -> str:
        return (
            f"Debate round {round_number} used a local heuristic because the "
            f"live moderator call failed or was not configured."
        )

    def _extract_disagreement(self, *, initial_answers: list[InitialModelAnswer]) -> str:
        fallback_paths = {answer.provider_path for answer in initial_answers}
        if ProviderPath.FALLBACK_SEARCH in fallback_paths and len(fallback_paths) > 1:
            return (
                "Models disagree on whether to rely on the primary provider or the fallback "
                "search path; treat the divergence as material and surface both to the user."
            )
        return (
            "Models largely agree on the top-level conclusion but disagree on the supporting "
            "evidence; surface the difference so the user can audit it."
        )

    def _extract_weak_support(self, *, initial_answers: list[InitialModelAnswer]) -> str:
        weak = [answer for answer in initial_answers if not answer.sources]
        if weak:
            return (
                f"{len(weak)} model(s) returned no visible source references; treat their claims "
                "as unsupported."
            )
        return (
            "All four models returned at least one source reference; the relative strength of "
            "those references still varies."
        )

    def _extract_missing_reasoning(self, *, initial_answers: list[InitialModelAnswer]) -> str:
        failed = [
            answer for answer in initial_answers if answer.status is InitialAnswerStatus.FAILED
        ]
        if failed:
            return (
                f"{len(failed)} model(s) failed to return a usable response; do not fill the gap "
                "with speculation."
            )
        return (
            "No model failed outright, but the explicit decision-support framing is missing from "
            "the raw output and should be re-introduced in the synthesis."
        )


# ---------------------------------------------------------------------------
# Agreement summary + per-model position movements (Slice B2).
#
# The debate is ROUND-scoped: each ``DebateOutput`` critiques the whole panel,
# with NO per-model attribution. Screen 05 wants a *per-model* view — how each
# model's stance opened and how it relates to the final synthesis — plus the
# verdict ring's N/4 agreement count.
#
# HONESTY CONTRACT: because the transcript carries no per-model movement, the
# "position movement" below is an INFERENCE, not an observation — in BOTH demo
# AND live runs. We compute it deterministically from two things we *can*
# observe: (1) how each model's OPENING answer clusters against the others, and
# (2) the panel's FINAL consensus. We NEVER observe what a model did mid-debate,
# so no stance string may assert a mid-debate action (no "conceded",
# "converged during debate", "moved toward"). ``demo_mode`` is orthogonal: it
# flags answer-content provenance (simulated vs live), NOT whether the stance
# narration is inferred — the narration is always inferred, so the UI must
# ALWAYS caption this table as inferred, independent of ``demo_mode``.
# ---------------------------------------------------------------------------


class AlignmentState(StrEnum):
    """The five mutually exclusive alignment cases a model can land in.

    Single source of truth shared by the classifier and the stance copy: the
    ``final_aligned`` derivation in
    :func:`product_app.synthesis_consensus.classify_model_alignment` and the
    per-model narration in :func:`_stance_texts` both key off this state
    (via :attr:`ModelAlignment.state`) instead of duplicating parallel
    if-chains. Every state is an INFERENCE from opening-vs-final, never an
    observed mid-debate action.

    This enum is INTERNAL. It is not a field on :class:`PositionMovement` and
    never crosses the API boundary — the served payload carries only the
    narrated strings — so adding a member costs no OpenAPI or contract change.
    """

    #: #247: no model was ever sent the question for this slot, so its text is
    #: this product's own (``providers.NOT_INVOKED_PATHS``). It is evidence of
    #: neither agreement nor disagreement.
    #:
    #: A SEPARATE state from ``NO_ANSWER`` on purpose, and the difference is not
    #: cosmetic. Both mean "nothing here to count", but a not-invoked slot DID
    #: produce text and the user can read it on screen. Routing it to
    #: ``NO_ANSWER`` narrates "No usable answer was returned" over a visible
    #: answer, and routing it to ``HELD_MINORITY`` narrates "Opening clustered as
    #: a minority reading" about a stance no model took. Both were measured on
    #: 2026-08-04; each replaces #247's lie with a smaller one.
    NOT_INVOKED = "not_invoked"
    #: Model returned no usable answer; there is no stance to place.
    NO_ANSWER = "no_answer"
    #: Opening clustered with the majority, and it is counted inside the
    #: consensus.
    HELD_WITH_CONSENSUS = "held_with_consensus"
    #: Opening clustered as a minority, and it is counted inside the consensus
    #: anyway (``revised``).
    MOVED_TO_CONSENSUS = "moved_to_consensus"
    #: Opening clustered as a minority, and it stays outside the consensus.
    HELD_MINORITY = "held_minority"


class FinalAnswerProvenance(StrEnum):
    """Did a model-written final answer go into placing this row?

    The stance copy may only say what "the final synthesis" did with a model's
    position when a model wrote that synthesis. This enum is the second key of
    :data:`_STANCE_COPY`, alongside :class:`AlignmentState`.

    That condition is NECESSARY, NOT SUFFICIENT, and this docstring claimed
    otherwise for one review round. ``MODEL_AUTHORED`` does not mean every
    opening was compared against the final answer:
    :func:`~product_app.synthesis_consensus.classify_model_alignment`
    short-circuits ``final_aligned = True`` for a MAJORITY opener before the
    containment test runs. Measured 2026-07-30 — four agreeing openers about a
    bridge, against a model-written synthesis about sourdough, invoked
    ``_opening_reflected_in_final`` **zero** times and served "the final
    synthesis keeps it in" four times. That door is pre-existing and byte-for-
    byte what ``main`` serves; its number side is filed as #180 and its
    narration side is recorded there too. Nothing here closes it — this enum
    only stops the narration on runs where no model wrote the text at all.

    It is NOT a new source of truth. It restates the branch
    :func:`product_app.synthesis_consensus.classify_model_alignment` already
    takes for a minority opener: it aligns against final-answer CONTENT only
    when ``model_authored_final_text`` is non-empty, and otherwise infers from
    the panel. :func:`product_app.synthesis.build_agreement_and_positions`
    derives this value from that same expression, so the sentence and the
    number are read off one value rather than two.
    """

    #: A model wrote the final answer, so the narration may name it. See the
    #: class docstring for why this does NOT mean the opening was compared
    #: against it.
    MODEL_AUTHORED = "model_authored"
    #: No model-written final answer went into the placement. FOUR shapes land
    #: here, not the three an earlier draft of this docstring listed:
    #:
    #: * missing — no synthesis on the run at all;
    #: * failed — a synthesis exists but its status is not COMPLETED;
    #: * ``"simulated"`` — this product templated all five sections;
    #: * ``"fallback"`` — a MIXED run, 1 to 4 of 5 sections live. It does not
    #:   record WHICH, so ``_final_synthesis_alignment_text`` refuses it whole.
    #:
    #: The fourth is why the copy below describes the PLACEMENT and not the
    #: synthesis. A mixed run's consensus and recommendation can be entirely the
    #: model's words: a fully-live run in which no answer carried a primary
    #: source is one, because ``_build_source_support`` returns early WITHOUT
    #: dispatching its call, capping the live-section count at four. Measured
    #: 2026-07-30 through the real orchestrator — four calls dispatched,
    #: ``synthesis_mode`` ``"fallback"``, consensus and recommendation both the
    #: model's. A sentence claiming no model-written final answer EXISTS would
    #: be false on that run. What is true on all four shapes is that no
    #: model-written final answer was used to place the row.
    NOT_MODEL_AUTHORED = "not_model_authored"


@dataclass(frozen=True)
class ModelAlignment:
    """Deterministic per-model alignment record.

    Computed by :func:`product_app.synthesis_consensus.classify_model_alignment`
    from the initial answers + the debate outputs. ``opening_majority`` is the
    model's opening stance relative to the majority cluster; ``final_aligned``
    is whether it lands in the panel's final consensus. ``revised`` is the
    OBSERVABLE INFERENCE that the two differ — the model opened clustered as a
    minority AND the final synthesis aligns with the consensus. Because the
    debate is round-scoped (no per-model transcript), none of these observe a
    mid-debate action; they are inferred from opening-vs-final alignment alone.
    """

    slot_number: int
    completed: bool
    opening_majority: bool
    final_aligned: bool
    revised: bool
    #: #247: was the question actually sent to a model for this slot? ``False``
    #: for a simulated slot, whose text this product wrote. Defaulted ``True`` so
    #: that the many fixtures constructing a genuinely-live alignment need no
    #: change — the default is the safe direction ONLY because the sole producer
    #: (:func:`product_app.synthesis_consensus.classify_model_alignment`) always
    #: passes it explicitly, which
    #: ``test_classify_model_alignment_always_sets_invoked_explicitly`` pins.
    invoked: bool = True

    @property
    def state(self) -> AlignmentState:
        """Map the alignment booleans onto the single :class:`AlignmentState`.

        This is the ONLY place the boolean tuple is collapsed into a case;
        the stance copy table then keys off the state, so the narration and
        the honesty of the revision note derive from one source of truth.

        ``completed`` is tested before ``invoked``, and the order is load-bearing
        for the one combination where both are ``False``. "No usable answer was
        returned" is the more informative of the two true sentences when there is
        no text at all; ``NOT_INVOKED``'s copy says "this answer", which reads
        oddly about an answer that does not exist. (That combination needs a
        FAILED slot on a simulated path; ``providers._failed_answer`` stamps
        ``OPENROUTER_SEARCH`` on every failure, so it is not reachable today —
        the ordering is defensive, not a live path.)

        An ordinary simulated slot is ``completed=True`` and falls through to
        ``invoked``, which is what routes it to ``NOT_INVOKED`` instead of
        ``HELD_MINORITY``.
        """
        if not self.completed:
            return AlignmentState.NO_ANSWER
        if not self.invoked:
            return AlignmentState.NOT_INVOKED
        if self.revised:
            return AlignmentState.MOVED_TO_CONSENSUS
        if self.final_aligned:
            return AlignmentState.HELD_WITH_CONSENSUS
        return AlignmentState.HELD_MINORITY


class AgreementSummary(BaseModel):
    """Verdict-ring numerator/denominator for screen 05 (``aligned`` of
    ``total``).

    ``total`` is the number of initial answers on the run — INCLUDING
    failed/empty ones (matching :func:`summarize_agreement`, which uses
    ``len(initial_answers)``).

    ``aligned`` counts the models whose OPENING POSITION IS CARRIED INTO THE
    FINAL ANSWER. It is NOT a count of models that agree with each other, and
    the served captions no longer say that it is: for a minority opener the
    test is a 4-gram containment of its own opening against the model-written
    final synthesis (``synthesis_consensus._opening_reflected_in_final``). A
    run served "0 of 4 models aligned" above a consensus section reading "All
    agree seat-based is the more predictable revenue model" — both true of what
    they measured, only one captioned honestly. ADR-0062.

    A failed answer can never be counted. Neither can any model when there is
    no final answer at all: nothing was produced for a position to be carried
    into.
    """

    aligned: int = Field(ge=0)
    total: int = Field(ge=0)


class PositionMovement(BaseModel):
    """One row of the "how positions moved" table — a single model's opening
    synopsis and how it relates to the final synthesis.

    All movement here is INFERRED (the debate is round-scoped, no per-model
    transcript): ``after_round_1`` and ``final`` describe opening-vs-final
    alignment, never an observed mid-debate action.
    """

    slot_number: int = Field(ge=1, le=4)
    model_id: str
    display_name: str
    opening: str
    after_round_1: str
    final: str
    #: OBSERVABLE-INFERENCE definition (design chip "✓ Revised"): the model's
    #: opening clustered as a minority AND the final synthesis aligns with the
    #: group consensus. NOT a claim that the model changed its mind mid-debate
    #: (unobservable — the transcript has no per-model attribution).
    revised: bool
    revision_note: str | None = None


#: Friendly phrasing for each debate focus area, used in the templated stance
#: narration so the per-model text names the lens the round examined.
_FOCUS_PHRASES: dict[str, str] = {
    "disagreement": "the points of disagreement",
    "weak_support": "weak source support",
    "missing_reasoning": "missing reasoning",
}


def _focus_phrase(debate_outputs: list[DebateOutput]) -> str:
    for output in debate_outputs:
        for area in output.focus_areas:
            phrase = _FOCUS_PHRASES.get(area)
            if phrase is not None:
                return phrase
    return "the points of disagreement"


#: A GFM table separator row: pipes, dashes, colons and spaces, nothing else,
#: and at least one dash so a bare "| |" is not mistaken for one.
_TABLE_SEPARATOR = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")
#: An ATX heading marker. The space is required, so "#hashtag" and "#257" are
#: prose and are left alone.
_ATX_HEADING = re.compile(r"^\s*#{1,6}\s+")
#: A fence opener/closer: three or more backticks or tildes at a line start.
_FENCE = re.compile(r"^\s*(?:```|~~~)")
#: A MATCHED pair of bold markers. Non-greedy, so "**a** and **b**" is two
#: pairs rather than one span swallowing the middle. An UNMATCHED "**" —
#: Python's ``**kwargs`` — has no partner and is therefore never touched.
_BOLD_PAIR = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
#: An inline code span. Its contents are verbatim by contract, so the bold rule
#: must not fire inside one.
_CODE_SPAN = re.compile(r"`[^`]*`")


def _strip_block_markup(answer_text: str) -> str:
    """Turn a model's raw Markdown answer into plain prose.

    This exists because of the ORDER the old code used: it truncated first and
    let the client render whatever was left. A cut can always sever a span, so
    an orphan ``**`` reached a real screen (#257 §2) — and ADR-0014 measured
    that an orphan renders literally in BOTH candidate parsers, because that is
    correct CommonMark rather than a parser bug. Stripping BEFORE truncating
    removes the class of defect instead of one instance: afterwards there is
    nothing left to sever.

    Every rule here is deliberately narrower than "remove Markdown", because
    the abandoned attempt at this was destroyed in review for over-reach. Each
    of its defects is a test in
    ``tests/unit/test_opening_synopsis_is_plain_prose.py``:

    * **No underscore is ever touched.** ``__init__`` became ``init``, which is
      the product stating a fact the model did not. This also protects
      ``snake_case`` and ``retention_flag`` for free.
    * **Only MATCHED ``**`` pairs are removed.** ``**kwargs`` is unpaired Python
      syntax; deleting its markers deletes content.
    * **A single ``*`` is never touched.** In this product's domain it is
      multiplication (``5 * 3``, ``3*40``) far more often than emphasis.
    * **A pipe is table syntax only when a SEPARATOR row says so.** "The line
      has pipes" flattened ``cat access.log | grep 500 | wc -l`` into a command
      that does something else entirely.
    * **Fenced code is left alone**, separator rows included — an answer showing
      how to WRITE a table is the one place those rows are content.
    """
    lines = (answer_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kept: list[str] = []
    in_fence = False
    previous_had_pipe = False
    for line in lines:
        if _FENCE.match(line):
            in_fence = not in_fence
            # The fence markers are syntax; their CONTENTS are kept verbatim.
            previous_had_pipe = False
            continue
        if in_fence:
            kept.append(line)
            continue
        # A separator row, but only where a header row precedes it. Without that
        # guard a thematic break ("---") or a model's decorative dash rule would
        # be eaten as table syntax.
        if previous_had_pipe and _TABLE_SEPARATOR.match(line):
            continue
        previous_had_pipe = "|" in line
        kept.append(_ATX_HEADING.sub("", line))

    text = "\n".join(kept)

    # Matched bold pairs, everywhere EXCEPT inside an inline code span. Done by
    # splitting on code spans and rewriting only the segments between them, so
    # `` `a**b**c` `` is untouched — the same discipline the client renderer
    # applies, for the same reason.
    parts = _CODE_SPAN.split(text)
    spans = _CODE_SPAN.findall(text)
    out: list[str] = []
    for index, part in enumerate(parts):
        out.append(_BOLD_PAIR.sub(r"\1", part))
        if index < len(spans):
            out.append(spans[index])
    return "".join(out)


def _opening_synopsis(answer_text: str, *, limit: int = 140) -> str:
    """First-sentence / ~``limit``-char synopsis of a model's answer, as PLAIN
    PROSE.

    Deterministic and always non-empty: a failed/empty answer yields a fixed
    stand-in string rather than "".

    The ORDER is the fix for #257 §2: strip the markup FIRST, truncate SECOND.
    Reversed — which is what this did until 2026-08-05 — a cut at 140 characters
    can sever an inline span, and the orphan marker it leaves renders literally
    on the "How positions moved" opening cell. No renderer can pair a marker
    whose partner the cut removed.
    """
    stripped = _strip_block_markup(answer_text)
    text = stripped.strip().replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    # Visibility is judged on the STRIPPED text. An answer that was nothing but
    # markup ("###", "**") has no words in it, and the stand-in is the honest
    # thing to show; judged on the raw text it would have passed as a real one.
    if not is_visible(text):
        return "No usable answer was returned for this model."
    first_sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    if len(first_sentence) <= limit:
        return first_sentence
    return text[:limit].rstrip() + "…"


def summarize_agreement(
    *,
    initial_answers: list[InitialModelAnswer],
    alignments: list[ModelAlignment],
) -> AgreementSummary:
    """Count how many models land in the final consensus. ``total`` is the
    number of initial answers; ``aligned`` is clamped to ``<= total``.
    """
    total = len(initial_answers)
    aligned = sum(1 for alignment in alignments if alignment.final_aligned)
    return AgreementSummary(aligned=min(aligned, total), total=total)


def build_position_movements(
    *,
    initial_answers: list[InitialModelAnswer],
    debate_outputs: list[DebateOutput],
    alignments: list[ModelAlignment],
    final_answer_provenance: FinalAnswerProvenance,
) -> list[PositionMovement]:
    """One :class:`PositionMovement` per model, in slot order.

    Fully deterministic. The opening is a synopsis of the model's own initial
    answer (observed); the round-1 and final stances are INFERRED from the
    model's alignment (opening majority/minority vs final consensus) and the
    debate focus lens — never from an observed per-model transcript.

    ``final_answer_provenance`` is REQUIRED, with no default, because the
    narration is false when it is guessed: a caller that let it default to
    ``MODEL_AUTHORED`` would go back to telling users what "the final synthesis"
    did on runs where no model wrote one (#176). The caller is the layer that
    knows — see
    :func:`product_app.synthesis.build_agreement_and_positions`.
    """
    focus = _focus_phrase(debate_outputs)
    by_slot = {alignment.slot_number: alignment for alignment in alignments}
    movements: list[PositionMovement] = []
    for answer in initial_answers:
        alignment = by_slot.get(answer.slot_number)
        opening = _opening_synopsis(answer.answer_text)
        after_round_1, final, revised, revision_note = _stance_texts(
            alignment=alignment,
            focus=focus,
            final_answer_provenance=final_answer_provenance,
        )
        movements.append(
            PositionMovement(
                slot_number=answer.slot_number,
                model_id=answer.model_id,
                display_name=answer.display_name or answer.model_id,
                opening=opening,
                after_round_1=after_round_1,
                final=final,
                revised=revised,
                revision_note=revision_note,
            )
        )
    return movements


@dataclass(frozen=True)
class _StanceCopy:
    """Templated stance copy for one :class:`AlignmentState`.

    ``after_round_1`` may contain a ``{focus}`` placeholder (the debate lens).
    Every string describes OPENING-vs-FINAL alignment — none asserts a
    mid-debate action, because the round-scoped transcript can't observe one.
    ``revision_note`` is non-None iff ``revised`` is True.
    """

    after_round_1: str
    final: str
    revised: bool
    revision_note: str | None


#: The opening-side narration. It describes how the model's OWN answer
#: clustered against the other openings, which is observed the same way however
#: the final answer was produced — so it is keyed by state alone and shared by
#: both provenances rather than written out twice.
_OPENING_COPY: dict[AlignmentState, str] = {
    AlignmentState.NOT_INVOKED: (
        "This answer was not produced by a model, so there is no round-1 stance to place."
    ),
    AlignmentState.NO_ANSWER: (
        "No usable answer was returned, so there is no round-1 stance to place."
    ),
    AlignmentState.HELD_WITH_CONSENSUS: "Opening clustered with the majority reading on {focus}.",
    AlignmentState.MOVED_TO_CONSENSUS: "Opening clustered as a minority reading on {focus}.",
    AlignmentState.HELD_MINORITY: "Opening clustered as a minority reading on {focus}.",
}

#: A model that returned nothing has no stance to place, and this copy asserts
#: nothing about a final answer — so it is the same row under both
#: provenances rather than two identical literals that could drift apart.
_NO_ANSWER_COPY = _StanceCopy(
    after_round_1=_OPENING_COPY[AlignmentState.NO_ANSWER],
    final="No final stance; this model's answer was unavailable.",
    revised=False,
    revision_note=None,
)

#: #247. A slot nobody asked has no position to place and no position to move,
#: and this copy claims neither. It says the ONE thing that is observed — the
#: text did not come from a model — and then states the consequence the verdict
#: ring acts on, so the row and the "N of 4 aligned" number explain each other
#: instead of contradicting.
#:
#: The same row under both provenances: it asserts nothing about a final answer,
#: so it cannot be made false by how that answer was produced. Written once
#: rather than as two identical literals that could drift apart, matching
#: ``_NO_ANSWER_COPY`` above.
#:
#: ``revised=False`` is load-bearing, not incidental. ``revised`` drives the
#: "✓ Revised" chip and the UI's ``revisedCount``; a slot that was never asked
#: can never have changed its mind.
_NOT_INVOKED_COPY = _StanceCopy(
    after_round_1=_OPENING_COPY[AlignmentState.NOT_INVOKED],
    final=(
        "This answer was not produced by a model, so it is counted as neither "
        "agreement nor disagreement."
    ),
    revised=False,
    revision_note=None,
)

#: One row of honest copy per (provenance, alignment state) — the single source
#: of truth for the stance narration. The classifier's booleans collapse to an
#: :class:`AlignmentState` (via :attr:`ModelAlignment.state`), and the caller
#: supplies the :class:`FinalAnswerProvenance` from the same expression the
#: classifier branches on, so the copy can never drift from the classification.
#:
#: WHY the second key exists (#176, measured 2026-07-30 at ``12cf402``). Every
#: string below used to name "the final synthesis" as the thing that kept a
#: model in the consensus or left it out. On a run where NO model wrote a final
#: answer, that sentence is false, and it was served on two shapes reachable in
#: production:
#:
#: * a TEMPLATED synthesis — this product wrote all five sections after the
#:   synthesis model failed. Since #171 finding 5 alignment is explicitly NOT
#:   derived from that text; the narration claimed it anyway, once per model.
#: * NO synthesis at all — missing or failed. Here the old copy was worse: with
#:   a "strong" panel the minority row read "Aligns with the group consensus in
#:   the final synthesis", naming a final synthesis that does not exist.
#:
#: The replacement narrates only what IS observed — how the opening clustered,
#: whether the row is counted inside the consensus, and that the final answer
#: was not what placed it. It describes the PLACEMENT, not the synthesis: see
#: :class:`FinalAnswerProvenance` for the mixed (``"fallback"``) run on which a
#: sentence about the synthesis's authorship would itself be false.
#:
#: All ten rows exist (eight, plus the two #247 ``NOT_INVOKED`` rows).
#: ``(NOT_MODEL_AUTHORED, MOVED_TO_CONSENSUS)`` is NO LONGER REACHABLE, and the
#: row is kept deliberately. Until ADR-0062 the no-synthesis strong panel
#: reached it via the panel-strength inference; that inference is gone, so a
#: minority opener is only counted when its opening is found in a MODEL-WRITTEN
#: final answer — which implies ``MODEL_AUTHORED``. The row stays because
#: ``_stance_texts`` looks copy up by key and
#: ``test_stance_copy_covers_every_provenance_and_alignment_state`` asserts this
#: table is the complete cartesian product, so a total function is the safe
#: shape. ``test_a_revised_row_still_carries_a_note`` exercises the reachable
#: ``MODEL_AUTHORED`` row instead. An earlier draft
#: of this comment called the row itself "measured unreachable", which its own
#: parenthesis contradicted — a reachability claim is a measurement and this
#: one was written from memory.
#: ``test_stance_copy_covers_every_provenance_and_alignment_state`` pins the
#: count, so the lookup cannot raise ``KeyError`` in a served path.
_STANCE_COPY: dict[tuple[FinalAnswerProvenance, AlignmentState], _StanceCopy] = {
    (FinalAnswerProvenance.MODEL_AUTHORED, AlignmentState.NOT_INVOKED): _NOT_INVOKED_COPY,
    (FinalAnswerProvenance.NOT_MODEL_AUTHORED, AlignmentState.NOT_INVOKED): _NOT_INVOKED_COPY,
    (FinalAnswerProvenance.MODEL_AUTHORED, AlignmentState.NO_ANSWER): _NO_ANSWER_COPY,
    (FinalAnswerProvenance.NOT_MODEL_AUTHORED, AlignmentState.NO_ANSWER): _NO_ANSWER_COPY,
    # --- a model wrote the final answer: the narration may describe it -------
    (FinalAnswerProvenance.MODEL_AUTHORED, AlignmentState.HELD_WITH_CONSENSUS): _StanceCopy(
        after_round_1=_OPENING_COPY[AlignmentState.HELD_WITH_CONSENSUS],
        final="Opened with, and the final synthesis keeps it in, the group consensus.",
        revised=False,
        revision_note=None,
    ),
    (FinalAnswerProvenance.MODEL_AUTHORED, AlignmentState.MOVED_TO_CONSENSUS): _StanceCopy(
        after_round_1=_OPENING_COPY[AlignmentState.MOVED_TO_CONSENSUS],
        final="Aligns with the group consensus in the final synthesis.",
        revised=True,
        revision_note=(
            "Opened as a minority view; the final synthesis reflects the group consensus."
        ),
    ),
    (FinalAnswerProvenance.MODEL_AUTHORED, AlignmentState.HELD_MINORITY): _StanceCopy(
        after_round_1=_OPENING_COPY[AlignmentState.HELD_MINORITY],
        final=(
            "Opened in the minority; the final synthesis leaves it outside the group consensus."
        ),
        revised=False,
        revision_note=None,
    ),
    # --- no model-written final answer: narrate the opening and the count ----
    (FinalAnswerProvenance.NOT_MODEL_AUTHORED, AlignmentState.HELD_WITH_CONSENSUS): _StanceCopy(
        after_round_1=_OPENING_COPY[AlignmentState.HELD_WITH_CONSENSUS],
        final=(
            "Opened with, and is counted inside, the group consensus. That placement "
            "reads the panel's own answers; no model-written final answer was used to "
            "make it."
        ),
        revised=False,
        revision_note=None,
    ),
    (FinalAnswerProvenance.NOT_MODEL_AUTHORED, AlignmentState.MOVED_TO_CONSENSUS): _StanceCopy(
        after_round_1=_OPENING_COPY[AlignmentState.MOVED_TO_CONSENSUS],
        final=(
            "Opened in the minority, and is counted inside the group consensus. That "
            "placement reads the panel's own answers; no model-written final answer was "
            "used to make it."
        ),
        revised=True,
        revision_note=(
            "Opened as a minority view and is counted inside the group consensus. That "
            "placement reads the panel's own answers; no model-written final answer was "
            "used to make it."
        ),
    ),
    (FinalAnswerProvenance.NOT_MODEL_AUTHORED, AlignmentState.HELD_MINORITY): _StanceCopy(
        after_round_1=_OPENING_COPY[AlignmentState.HELD_MINORITY],
        final=(
            "Opened in the minority, and is counted outside the group consensus. No "
            "model-written final answer was used to make that placement."
        ),
        revised=False,
        revision_note=None,
    ),
}


def _stance_texts(
    *,
    alignment: ModelAlignment | None,
    focus: str,
    final_answer_provenance: FinalAnswerProvenance,
) -> tuple[str, str, bool, str | None]:
    """Return ``(after_round_1, final, revised, revision_note)`` for one model.

    Pure lookup on the model's :class:`AlignmentState` and the run's
    :class:`FinalAnswerProvenance` — no branching logic lives here, so the copy
    stays in lockstep with the classification. Every string is an inference
    from opening-vs-final alignment; none claims a mid-debate action, and none
    claims what a final synthesis did unless a model wrote one.
    """
    state = alignment.state if alignment is not None else AlignmentState.NO_ANSWER
    copy = _STANCE_COPY[(final_answer_provenance, state)]
    return (
        copy.after_round_1.format(focus=focus),
        copy.final,
        copy.revised,
        copy.revision_note,
    )


debate_event_recorder = InMemoryDebateEventRecorder()
debate_stub_service = DebateOrchestrationService()
debate_orchestration_service = debate_stub_service

# Public re-export so tests that referenced the old `safety.HIGH_STAKES_PATTERN`
# keep working without importing two modules.
__all__ = [
    "DEBATE_HARD_TIMEOUT_MS",
    "DEBATE_MODE_FALLBACK",
    "DEBATE_MODE_LIVE",
    "DEBATE_MODES",
    "AgreementSummary",
    "AlignmentState",
    "DebateOrchestrationService",
    "DebateResult",
    "DebateOutput",
    "DebateRoundEvent",
    "DebateRoundStatus",
    "FOCUS_AREAS",
    "FinalAnswerProvenance",
    "InMemoryDebateEventRecorder",
    "ModelAlignment",
    "PositionMovement",
    "build_position_movements",
    "debate_event_recorder",
    "debate_orchestration_service",
    "debate_stub_service",
    "summarize_agreement",
]
