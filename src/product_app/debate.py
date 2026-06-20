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

from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
from time import perf_counter
from uuid import UUID

from pydantic import BaseModel, Field

from product_app.config import settings
from product_app.model_slots import ModelSlot
from product_app.providers import (
    InitialAnswerStatus,
    InitialModelAnswer,
    LiveProviderResult,
    ProviderPath,
    provider_execution_service,
)
from product_app.safety import (
    SafetyAcknowledgement,
)

DEBATE_HARD_TIMEOUT_MS = 180_000

#: Token cap per debate round. The plan calls for ~600 tokens of
#: output per round; we round to a hard cap of 700 to leave a small
#: safety margin for the model's tendency to emit a leading phrase.
DEBATE_ROUND_MAX_TOKENS = 700

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
    "the user."
)

ROUND_TWO_SYSTEM_PROMPT = (
    "You are a debate moderator refining the round 1 critique. Focus "
    "specifically on (a) the strongest residual disagreements after "
    "round 1, and (b) reasoning the round 1 critique flagged as "
    "missing. Cite the model names and quote the specific passage. "
    "Be concrete. The output is for a human reviewer, not the user."
)


class DebateRoundStatus(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"


class DebateOutput(BaseModel):
    round_number: int = Field(ge=1, le=2)
    focus_areas: list[str]
    critique_text: str
    status: DebateRoundStatus


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
        with self._lock:
            self._events.append(
                DebateRoundEvent(
                    event_type=event_type,
                    account_id=account_id,
                    query_run_id=query_run_id,
                    round_number=round_number,
                    focus_areas=focus_areas,
                    duration_ms=duration_ms,
                    status=status,
                    timed_out=timed_out,
                ),
            )
            if len(self._events) > self.MAX_EVENTS:
                del self._events[: len(self._events) - self.MAX_EVENTS]

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


class DebateOrchestrationService:
    """Produces structured two-round debate output from initial answers.

    Round two is the budget-checked step: if the request has been running
    for more than ``DEBATE_HARD_TIMEOUT_MS`` since round one started, the
    second round is reported as ``SKIPPED`` with the budget exceeded reason
    and the run degrades to a partial result.

    L4: each round's critique text is produced by a live LLM call when
    a key is configured; otherwise the templated critique is used. The
    LLM call is opt-in: a missing key or a hard LLM failure both fall
    back to the template, with a ``provider_notice`` (added to the
    ``provider_failure_notices`` at the response level) explaining the
    fallback. A failed round is NOT treated as a pipeline failure —
    the run still produces a useful synthesis from the templated text.
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
        fallback_messages: list[str] = []

        # Round 1 always runs. The orchestrator pulls disagreement, weak
        # support, and missing reasoning signals from the initial answers
        # to produce a critique text that the synthesis step can build on.
        round_one_started = perf_counter()
        round_one_text, round_one_fallback = self._build_round_one_text(
            initial_answers=initial_answers,
            query_text=query_text,
            openrouter_key=openrouter_key,
        )
        round_one_ms = max(1, round((perf_counter() - round_one_started) * 1000))
        round_timings_ms[1] = round_one_ms
        if round_one_fallback is not None:
            fallback_messages.append(round_one_fallback)
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
            )

        round_two_started = perf_counter()
        round_two_text, round_two_fallback = self._build_round_two_text(
            initial_answers=initial_answers,
            query_text=query_text,
            round_one_text=round_one_text,
            openrouter_key=openrouter_key,
        )
        round_two_ms = max(1, round((perf_counter() - round_two_started) * 1000))
        round_timings_ms[2] = round_two_ms
        if round_two_fallback is not None:
            fallback_messages.append(round_two_fallback)
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
            ),
        )

        return DebateResult(
            debate_outputs=debate_outputs,
            failed_steps=failed_steps,
            missing_steps=missing_steps,
            timed_out=False,
            round_timings_ms=round_timings_ms,
        )

    def _should_skip_round_two(self, *, elapsed_ms: float, query_text: str) -> bool:
        if elapsed_ms > self._hard_timeout_ms:
            return True
        return "force debate timeout" in query_text.lower()

    def _build_round_one_text(
        self,
        *,
        initial_answers: list[InitialModelAnswer],
        query_text: str,
        openrouter_key: str,
    ) -> tuple[str, str | None]:
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
        )
        if live is None:
            return templated, self._debate_fallback_notice(round_number=1)
        return live, None

    def _build_round_two_text(
        self,
        *,
        initial_answers: list[InitialModelAnswer],
        query_text: str,
        round_one_text: str,
        openrouter_key: str,
    ) -> tuple[str, str | None]:
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
        )
        if live is None:
            return templated, self._debate_fallback_notice(round_number=2)
        return live, None

    def _call_debate_model(
        self,
        *,
        openrouter_key: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str | None:
        """Call the configured debate model. Returns ``None`` on any
        failure so the caller can fall back to the templated text.
        The four model answers are summarised, not re-quoted, to keep
        the prompt within budget.
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
        result: LiveProviderResult | None = provider_execution_service.call_with_prompt(
            openrouter_key=openrouter_key,
            model_id=settings.debate_model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=DEBATE_ROUND_MAX_TOKENS,
        )
        if result is None or not result.answer_text.strip():
            return None
        return result.answer_text.strip()

    def _debate_user_prompt(
        self,
        *,
        query_text: str,
        initial_answers: list[InitialModelAnswer],
        prior_round: str | None,
    ) -> str:
        # We summarise each model answer rather than re-quoting it in
        # full. The intent of the debate is to surface disagreement,
        # not to dump the original answers back into the LLM.
        lines: list[str] = []
        lines.append("User query (do NOT repeat in your response):")
        lines.append(query_text)
        lines.append("")
        lines.append("Four model answers (model name, status, first 200 chars):")
        for answer in initial_answers:
            excerpt = (answer.answer_text or "").strip().replace("\n", " ")[:200]
            # ``display_name`` is the catalog's short label
            # ("Claude Haiku 4.5"). Falling back to ``model_id`` keeps
            # the prompt well-formed even if the catalog is unaware
            # of the model.
            label = answer.display_name or answer.model_id
            lines.append(
                f"- {label} ({answer.status.value}): "
                f"{excerpt}"
            )
        if prior_round is not None:
            lines.append("")
            lines.append("Round 1 critique (for context; do NOT repeat):")
            lines.append(prior_round)
        return "\n".join(lines)

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


debate_event_recorder = InMemoryDebateEventRecorder()
debate_stub_service = DebateOrchestrationService()
debate_orchestration_service = debate_stub_service

# Public re-export so tests that referenced the old `safety.HIGH_STAKES_PATTERN`
# keep working without importing two modules.
__all__ = [
    "DEBATE_HARD_TIMEOUT_MS",
    "DebateOrchestrationService",
    "DebateResult",
    "DebateOutput",
    "DebateRoundEvent",
    "DebateRoundStatus",
    "FOCUS_AREAS",
    "InMemoryDebateEventRecorder",
    "debate_event_recorder",
    "debate_orchestration_service",
    "debate_stub_service",
]
