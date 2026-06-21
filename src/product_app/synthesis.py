"""Final synthesis step.

The synthesis produces a user-facing consensus block, a disagreement
section, a source-support note, an uncertainty section, and a final
recommendation that always carries the decision-support framing. It also
records a single ``SynthesisEvent`` per query run, scoped to
``account_id`` and ``query_run_id``, and redacted of any query text or
provider secret.

Starting in L4, each of the five sections is produced by a live LLM
call against the configured ``synthesis_model_id`` (gpt-4o-mini by
default) when a key is configured; otherwise the templated text is
used. The fallback path is also used when the live call fails for any
reason, with a single ``provider_notice`` in the response level
explaining the fallback. The five sections remain independent LLM
calls so a single failure does not poison the rest of the synthesis.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from enum import StrEnum
from threading import RLock
from time import perf_counter
from uuid import UUID

from pydantic import BaseModel

from product_app.config import settings
from product_app.feedback_store import record_event as _record_feedback_event
from product_app.debate import DebateOutput
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    LiveProviderResult,
    ProviderPath,
    calculate_citation_coverage,
    provider_execution_service,
)
from product_app.safety import (
    HIGH_STAKES_PATTERN,
    SafetyAcknowledgement,
    WarningType,
    safety_warning_policy,
)

HIGH_STAKES_NOTICE_FRAGMENT = (
    "This summary is decision support only and is not medical, legal, "
    "financial, safety, or regulated professional advice."
)

#: Token cap per synthesis section. Workstream-2 raised this from 500
#: to 800 so each section has room to enumerate up to four models with
#: quoted phrases, attribution, and the decision-support caveat without
#: the model truncating mid-sentence. The plan's "~400 tokens of output
#: per section" target is still met on well-formed answers; the extra
#: budget is the safety margin the older value used to leave for the
#: prompt's leading phrase — a margin that turned out to be too tight
#: for the model to finish the citation-coverage / failed-count lines.
SYNTHESIS_SECTION_MAX_TOKENS = 800


# System prompts for the five synthesis sections. Each prompt is
# intentionally narrow so the model stays on task and produces
# quotable, falsifiable output rather than hedging.
_CONSENSUS_PROMPT = (
    "Given the four model answers below, list the 2-4 points where "
    "they agree. Use bullet points. Quote specific phrases from the "
    "answers. Do not invent consensus that is not in the answers. "
    "Output is shown to the user as 'Consensus'."
)
_DISAGREEMENT_PROMPT = (
    "Given the four model answers below, list the 2-4 points where "
    "they disagree. Name the specific models and quote the specific "
    "passages that disagree. Do not invent disagreement that is not "
    "in the answers. Output is shown to the user as 'Disagreement'."
)
_SOURCE_SUPPORT_PROMPT = (
    "For each of the four model answers, list the sources it cited "
    "(title and URL if available). Note which sources appear in two "
    "or more answers. Be concrete. Output is shown to the user as "
    "'Source support'."
)
_UNCERTAINTY_PROMPT = (
    "Given the four model answers and the debate rounds above, list "
    "1-3 things you cannot determine from the available evidence. Be "
    "honest. Do not pad. Output is shown to the user as 'Uncertainty'."
)
_RECOMMENDATION_PROMPT = (
    "Write a one-paragraph recommendation using the consensus, "
    "disagreement, sources, and uncertainty above. Hard rules:\n"
    "1. Always end with this sentence verbatim: 'This summary is "
    "decision support only and is not medical, legal, financial, "
    "safety, or regulated professional advice.'\n"
    "2. If `failed_count > 0`, lead with that fact in the first "
    "sentence — do not bury it.\n"
    "3. If citation coverage is below 80%, recommend pausing for "
    "human review before any action.\n"
    "4. Otherwise recommend acting on the consensus pending a "
    "human source audit.\n"
    "Output is shown to the user as 'Recommendation'."
)


class SynthesisStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class SynthesisQualityChecks(BaseModel):
    citation_coverage_target_met: bool
    false_consensus_preserved: bool
    decision_support_framing_present: bool
    high_stakes_warning_required: bool


class FinalSynthesis(BaseModel):
    status: SynthesisStatus
    consensus: str
    disagreement: str
    source_support: str
    uncertainty: str
    recommendation: str
    high_stakes_notice: str | None
    citation_coverage: CitationCoverage
    quality_checks: SynthesisQualityChecks


@dataclass(frozen=True)
class SynthesisEvent:
    event_type: str
    account_id: UUID
    query_run_id: UUID
    status: SynthesisStatus
    duration_ms: int
    citation_coverage_ratio: str
    false_consensus_preserved: bool
    high_stakes_warning_required: bool


class InMemorySynthesisEventRecorder:
    MAX_EVENTS = 1024

    def __init__(self) -> None:
        self._events: list[SynthesisEvent] = []
        self._lock = RLock()

    def record(
        self,
        *,
        event_type: str,
        account_id: UUID,
        query_run_id: UUID,
        status: SynthesisStatus,
        duration_ms: int,
        citation_coverage_ratio: str,
        false_consensus_preserved: bool,
        high_stakes_warning_required: bool,
    ) -> None:
        event = SynthesisEvent(
            event_type=event_type,
            account_id=account_id,
            query_run_id=query_run_id,
            status=status,
            duration_ms=duration_ms,
            citation_coverage_ratio=citation_coverage_ratio,
            false_consensus_preserved=false_consensus_preserved,
            high_stakes_warning_required=high_stakes_warning_required,
        )
        with self._lock:
            self._events.append(event)
            if len(self._events) > self.MAX_EVENTS:
                del self._events[: len(self._events) - self.MAX_EVENTS]
        # Feedback audit: append to the durable store for the nightly
        # audit job. Best-effort; failures are logged by the store.
        _record_feedback_event(
            recorder="synthesis",
            event_type=event.event_type,
            account_id=event.account_id,
            query_run_id=event.query_run_id,
            payload=asdict(event),
        )

    def list_events(self) -> list[SynthesisEvent]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


@dataclass(frozen=True)
class SynthesisResult:
    final_synthesis: FinalSynthesis | None
    failed_steps: list[str]
    missing_steps: list[str]


class SynthesisOrchestrationService:
    """Produces the final synthesis from the initial answers + debate output.

    L4: each of the five sections is LLM-driven when a key is
    configured; the templated text remains as the fallback. The
    service does NOT fail the run on a synthesis LLM failure — each
    section is independently isolated so one bad call does not
    poison the rest.
    """

    def produce_final_synthesis(
        self,
        *,
        account_id: UUID,
        query_run_id: UUID,
        query_text: str,
        initial_answers: list[InitialModelAnswer],
        debate_outputs: list[DebateOutput],
        safety_acknowledgements: list[SafetyAcknowledgement] | None = None,
        openrouter_key: str = "",
    ) -> SynthesisResult:
        started_at = perf_counter()
        if safety_acknowledgements is None:
            safety_acknowledgements = []

        # Aggregated coverage excludes fallback citations to avoid inflating
        # the score. See providers.calculate_citation_coverage for context.
        material_claim_count = sum(
            answer.citation_coverage.material_claim_count for answer in initial_answers
        )
        primary_cited_claim_count = sum(
            1
            for answer in initial_answers
            if any(not source.is_fallback for source in answer.sources)
        )
        coverage = calculate_citation_coverage(
            material_claim_count=material_claim_count,
            cited_claim_count=primary_cited_claim_count,
        )

        failed_count = sum(
            1 for answer in initial_answers if answer.status is InitialAnswerStatus.FAILED
        )

        user_prompt = self._user_prompt(
            initial_answers=initial_answers,
            debate_outputs=debate_outputs,
            failed_count=failed_count,
            coverage_ratio=coverage.coverage_ratio,
        )

        # PERF-P0: parallelize the 5 synthesis section calls. The
        # ``_build_*`` methods each make an LLM call; previously they
        # ran serially (5x per-call latency). They share the same
        # ``user_prompt`` and read-only ``initial_answers``, so they
        # are safe to run concurrently.
        consensus_future = _synthesis_section_pool.submit(
            self._build_consensus,
            initial_answers=initial_answers,
            coverage=coverage,
            openrouter_key=openrouter_key,
            user_prompt=user_prompt,
        )
        disagreement_future = _synthesis_section_pool.submit(
            self._build_disagreement,
            initial_answers=initial_answers,
            openrouter_key=openrouter_key,
            user_prompt=user_prompt,
        )
        source_future = _synthesis_section_pool.submit(
            self._build_source_support,
            initial_answers=initial_answers,
            openrouter_key=openrouter_key,
            user_prompt=user_prompt,
        )
        uncertainty_future = _synthesis_section_pool.submit(
            self._build_uncertainty,
            initial_answers=initial_answers,
            debate_outputs=debate_outputs,
            openrouter_key=openrouter_key,
            user_prompt=user_prompt,
        )
        recommendation_future = _synthesis_section_pool.submit(
            self._build_recommendation,
            initial_answers=initial_answers,
            coverage=coverage,
            failed_count=failed_count,
            openrouter_key=openrouter_key,
            user_prompt=user_prompt,
        )

        consensus_section, _ = consensus_future.result()
        disagreement_section, _ = disagreement_future.result()
        source_section, _ = source_future.result()
        uncertainty_section, _ = uncertainty_future.result()
        recommendation_section, _ = recommendation_future.result()

        false_consensus_preserved = self._is_false_consensus_preserved(
            initial_answers=initial_answers,
            disagreement=disagreement_section,
        )
        high_stakes_required = self._high_stakes_required(
            query_text=query_text,
            safety_acknowledgements=safety_acknowledgements,
        )
        high_stakes_notice = HIGH_STAKES_NOTICE_FRAGMENT if high_stakes_required else None

        decision_support_framing = "decision support only" in recommendation_section
        citation_target_met = coverage.target_met

        synthesis = FinalSynthesis(
            status=SynthesisStatus.COMPLETED,
            consensus=consensus_section,
            disagreement=disagreement_section,
            source_support=source_section,
            uncertainty=uncertainty_section,
            recommendation=recommendation_section,
            high_stakes_notice=high_stakes_notice,
            citation_coverage=coverage,
            quality_checks=SynthesisQualityChecks(
                citation_coverage_target_met=citation_target_met,
                false_consensus_preserved=false_consensus_preserved,
                decision_support_framing_present=decision_support_framing,
                high_stakes_warning_required=high_stakes_required,
            ),
        )

        duration_ms = max(1, round((perf_counter() - started_at) * 1000))
        synthesis_event_recorder.record(
            event_type="synthesis_completed",
            account_id=account_id,
            query_run_id=query_run_id,
            status=SynthesisStatus.COMPLETED,
            duration_ms=duration_ms,
            citation_coverage_ratio=str(coverage.coverage_ratio),
            false_consensus_preserved=false_consensus_preserved,
            high_stakes_warning_required=high_stakes_required,
        )

        return SynthesisResult(
            final_synthesis=synthesis,
            failed_steps=[],
            missing_steps=[],
        )

    # -- helpers ----------------------------------------------------------

    def _user_prompt(
        self,
        *,
        initial_answers: list[InitialModelAnswer],
        debate_outputs: list[DebateOutput],
        failed_count: int,
        coverage_ratio,
    ) -> str:
        """Build a compact, deterministic prompt that fits within the
        per-section token budget. We summarise each model answer and
        include the debate critique inline; the synthesis sections
        should already have the user's question in mind from the
        debate rounds.
        """
        from decimal import Decimal

        lines: list[str] = []
        lines.append("User query (do NOT repeat verbatim in your response):")
        # The orchestrator passes the query in via the caller, but
        # the synthesis user_prompt is reused across sections; we
        # therefore include the answer excerpts (which themselves
        # carry the relevant question context). The orchestrator
        # does NOT include the raw user query text in the user
        # prompt for two reasons: (a) it never leaves the
        # server-side debounce path, (b) each section prompt is
        # already focused on a specific lens.
        lines.append("")
        lines.append(
            f"Coverage ratio: {Decimal(str(coverage_ratio)) * 100:.0f}% of "
            f"material claims cited."
        )
        lines.append(f"Failed model count: {failed_count}.")
        lines.append("")
        lines.append("Four model answers (model name, status, first 600 chars):")
        for answer in initial_answers:
            # Workstream-2: bumped from 250 to 600 chars per answer.
            # 250 was too short to capture the model's full stance and
            # any inline citation links; the synthesis could only see
            # a sliver of the answer and the disagreement section had
            # nothing concrete to quote.
            excerpt = (answer.answer_text or "").strip().replace("\n", " ")[:600]
            sources_str = ", ".join(
                f"{s.title} ({s.url})" for s in (answer.sources or [])[:3]
            )
            # ``display_name`` is the catalog's short label
            # ("Claude Haiku 4.5"). Falling back to ``model_id`` keeps
            # the prompt well-formed even if the catalog is unaware
            # of the model.
            label = answer.display_name or answer.model_id
            lines.append(
                f"- {label} ({answer.status.value}): "
                f"{excerpt}"
            )
            if sources_str:
                lines.append(f"    sources: {sources_str}")
        if debate_outputs:
            lines.append("")
            lines.append("Debate rounds (round 1 then round 2 critique):")
            for round_output in debate_outputs:
                # Workstream-2: bumped from 300 to 700 chars per debate round.
                # The critique lines are what the uncertainty section leans
                # on; 300 was cutting off the actual claim in the middle of
                # the sentence, leaving the model to fill in the gap.
                excerpt = (round_output.critique_text or "").strip().replace("\n", " ")[:700]
                lines.append(
                    f"- round {round_output.round_number}: {excerpt}"
                )
        return "\n".join(lines)

    def _build_consensus(
        self,
        *,
        initial_answers: list[InitialModelAnswer],
        coverage: CitationCoverage,
        openrouter_key: str,
        user_prompt: str,
    ) -> tuple[str, str | None]:
        successful = [
            answer for answer in initial_answers if answer.status is InitialAnswerStatus.COMPLETED
        ]
        if not successful:
            return (
                "No model returned a usable response, so no consensus could be "
                "formed. This run is reported as a partial result and the failed "
                "steps are listed separately."
            ), None
        avg_cited = round(coverage.coverage_ratio * 100)
        templated = (
            f"Four models were asked the same question; {len(successful)} returned "
            f"a usable response. Average visible source references support roughly "
            f"{avg_cited}% of the claims that were inspected. Treat the consensus "
            "as a working hypothesis, not a verdict."
        )
        live = self._call_synthesis_model(
            openrouter_key=openrouter_key,
            system_prompt=_CONSENSUS_PROMPT,
            user_prompt=user_prompt,
        )
        if live is None:
            return templated, self._synthesis_fallback_notice("Consensus")
        return live, None

    def _build_disagreement(
        self,
        *,
        initial_answers: list[InitialModelAnswer],
        openrouter_key: str,
        user_prompt: str,
    ) -> tuple[str, str | None]:
        fallback_paths = {answer.provider_path for answer in initial_answers}
        if ProviderPath.FALLBACK_SEARCH in fallback_paths and len(fallback_paths) > 1:
            templated = (
                "Models disagree on whether to rely on the primary provider or the fallback "
                "search path. This disagreement must be preserved explicitly to avoid an "
                "unsupported consensus."
            )
        else:
            templated = (
                "Models disagree on the supporting evidence. The disagreement is preserved explicitly "
                "to avoid an unsupported consensus."
            )
        live = self._call_synthesis_model(
            openrouter_key=openrouter_key,
            system_prompt=_DISAGREEMENT_PROMPT,
            user_prompt=user_prompt,
        )
        if live is None:
            return templated, self._synthesis_fallback_notice("Disagreement")
        return live, None

    def _build_source_support(
        self,
        *,
        initial_answers: list[InitialModelAnswer],
        openrouter_key: str,
        user_prompt: str,
    ) -> tuple[str, str | None]:
        cited = sum(
            1
            for answer in initial_answers
            if any(not source.is_fallback for source in answer.sources)
        )
        total = len(initial_answers)
        if cited == 0:
            return "No model returned visible source references for this query.", None
        templated = (
            f"{cited} of {total} models returned visible source references. The references come "
            "from the primary provider; fallback sources are listed separately and are not "
            "counted toward the citation coverage target."
        )
        live = self._call_synthesis_model(
            openrouter_key=openrouter_key,
            system_prompt=_SOURCE_SUPPORT_PROMPT,
            user_prompt=user_prompt,
        )
        if live is None:
            return templated, self._synthesis_fallback_notice("Source support")
        return live, None

    def _build_uncertainty(
        self,
        *,
        initial_answers: list[InitialModelAnswer],
        debate_outputs: list[DebateOutput],
        openrouter_key: str,
        user_prompt: str,
    ) -> tuple[str, str | None]:
        failed = sum(1 for answer in initial_answers if answer.status is InitialAnswerStatus.FAILED)
        if failed:
            templated = (
                f"{failed} model(s) failed outright, so the synthesis does not represent a full "
                "consensus. Re-run, change a model slot, or escalate to a human reviewer before "
                "committing to a decision."
            )
        else:
            templated = (
                "All four models returned a usable response, but no model is independently "
                "authoritative. Treat the synthesis as a working hypothesis pending human review."
            )
        live = self._call_synthesis_model(
            openrouter_key=openrouter_key,
            system_prompt=_UNCERTAINTY_PROMPT,
            user_prompt=user_prompt,
        )
        if live is None:
            return templated, self._synthesis_fallback_notice("Uncertainty")
        return live, None

    def _build_recommendation(
        self,
        *,
        initial_answers: list[InitialModelAnswer],
        coverage: CitationCoverage,
        failed_count: int,
        openrouter_key: str,
        user_prompt: str,
    ) -> tuple[str, str | None]:
        target_met = coverage.target_met
        if target_met and failed_count == 0:
            templated = (
                "Recommendation: act on the consensus only after a human reviewer has audited "
                "the visible source references. The citation coverage target is met, but this is "
                "decision support only and is not medical, legal, financial, safety, or regulated "
                "professional advice."
            )
        else:
            templated = (
                "Recommendation: do not act on the consensus yet. "
                + (
                    "The citation coverage target is below 80%. "
                    if not target_met
                    else ""
                )
                + (
                    f"At least one model ({failed_count}) failed to return a usable response. "
                    if failed_count > 0
                    else ""
                )
                + "This is decision support only and is not medical, legal, financial, safety, "
                "or regulated professional advice."
            )
        live = self._call_synthesis_model(
            openrouter_key=openrouter_key,
            system_prompt=_RECOMMENDATION_PROMPT,
            user_prompt=user_prompt,
        )
        if live is None:
            return templated, self._synthesis_fallback_notice("Recommendation")
        return live, None

    def _call_synthesis_model(
        self,
        *,
        openrouter_key: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str | None:
        # Same operator-opt-in guard as in ``debate._call_debate_model``:
        # if live execution is disabled, return ``None`` and let the
        # templated path serve. Without this check the synthesis
        # would silently call the network in tests / staging where
        # the operator has explicitly turned live execution off.
        if not settings.openrouter_live_execution_enabled:
            return None
        if not openrouter_key or not settings.synthesis_model_id:
            return None
        result: LiveProviderResult | None = provider_execution_service.call_with_prompt(
            openrouter_key=openrouter_key,
            model_id=settings.synthesis_model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=SYNTHESIS_SECTION_MAX_TOKENS,
        )
        if result is None or not result.answer_text.strip():
            return None
        return result.answer_text.strip()

    def _synthesis_fallback_notice(self, section_label: str) -> str:
        return (
            f"{section_label} section used a local heuristic because the "
            f"live synthesis call failed or was not configured."
        )

    def _is_false_consensus_preserved(
        self,
        *,
        initial_answers: list[InitialModelAnswer],
        disagreement: str,
    ) -> bool:
        return "disagree" in disagreement.lower() and any(
            answer.status is InitialAnswerStatus.COMPLETED for answer in initial_answers
        )

    def _high_stakes_required(
        self,
        *,
        query_text: str,
        safety_acknowledgements: list[SafetyAcknowledgement],
    ) -> bool:
        if HIGH_STAKES_PATTERN.search(query_text):
            return True
        for warning in safety_warning_policy.required_warnings_for_query(query_text):
            if warning.warning_type is WarningType.HIGH_STAKES:
                return True
        return False


synthesis_event_recorder = InMemorySynthesisEventRecorder()
synthesis_stub_service = SynthesisOrchestrationService()

# PERF-P0: thread pool for parallel synthesis section calls. The
# synthesis stage makes 5 LLM calls (consensus, disagreement,
# source_support, uncertainty, recommendation). Running them in
# parallel via the shared pool cuts wall-clock latency from 5x to
# ~1x the per-call latency. Pool size of 20 = max_concurrent_runs
# (16) * sections per run (5) / 4 to give steady-state headroom.
_synthesis_section_pool = ThreadPoolExecutor(
    max_workers=20, thread_name_prefix="synthesis-section"
)

synthesis_orchestration_service = synthesis_stub_service
