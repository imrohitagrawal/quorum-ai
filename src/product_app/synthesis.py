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

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from enum import StrEnum
from threading import RLock
from time import perf_counter
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from product_app.config import settings
from product_app.costs import CHARS_PER_TOKEN
from product_app.debate import (
    DEBATE_ROUND_MAX_TOKENS,
    AgreementSummary,
    DebateOutput,
    PositionMovement,
    build_position_movements,
    summarize_agreement,
)
from product_app.feedback_store import record_event as _record_feedback_event
from product_app.providers import (
    _MAX_SOURCE_TITLE_LEN,
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    LiveProviderResult,
    ProviderPath,
    TokenUsage,
    calculate_citation_coverage,
    provider_execution_service,
)
from product_app.safety import (
    HIGH_STAKES_PATTERN,
    SafetyAcknowledgement,
    WarningType,
    safety_warning_policy,
)
from product_app.synthesis_consensus import (
    ConsensusStrength,
    classify_model_alignment,
    compute_consensus_strength,
)
from product_app.synthesis_length import (
    truncate_recommendation,
    truncate_section,
)
from product_app.untrusted_text import UNTRUSTED_DATA_SYSTEM_RULE, fence

#: PR6/#8/#15: templated-section provenance is now carried STRUCTURALLY by
#: ``FinalSynthesis.synthesis_mode`` and rendered as an "Automated summary"
#: badge, not smuggled into the prose as a text prefix. The old prefixes
#: ("Heuristic fallback: ", then "[Template] ") leaked internal jargon into
#: the user-visible recommendation — the exact complaint in issues #8/#15.
#:
#: Kept as an empty string rather than deleted so the concatenation sites read
#: unchanged and a future reviewer can see where provenance USED to be encoded.
#: If you are tempted to put text back here, add a ``synthesis_mode`` value and
#: badge it instead — prose is not a metadata channel.
TEMPLATED_FALLBACK_PREFIX = ""

#: The three values ``FinalSynthesis.synthesis_mode`` can take. Named constants
#: rather than bare literals because since #171 finding 5 the value is READ as
#: well as written — ``_final_synthesis_alignment_text`` refuses a synthesis
#: this product wrote — and a producer/consumer drift on a spelling would
#: silently restore the defect rather than fail. Both sites now spell it once,
#: here. The strings themselves are part of the served API
#: (``openapi.yaml``) and the browser reads them (``app.js`` compares against
#: ``"live"`` and ``"fallback"``), so their VALUES are fixed even though the
#: names are new.
#:
#: ``"live"`` = all five sections came back from the model with usable text.
#: ``"fallback"`` = 1 to 4 did (a MIXED run; it does not record which).
#: ``"simulated"`` = none did, so every section is this product's template.
SYNTHESIS_MODE_LIVE = "live"
SYNTHESIS_MODE_FALLBACK = "fallback"
SYNTHESIS_MODE_SIMULATED = "simulated"

#: Every value :data:`FinalSynthesis.synthesis_mode` can hold, as a set, so a
#: test can cover all of them without retyping the members (``AGENTS.md`` rule
#: 7a). Derived from the three constants above, never listed independently.
SYNTHESIS_MODES: frozenset[str] = frozenset(
    {SYNTHESIS_MODE_LIVE, SYNTHESIS_MODE_FALLBACK, SYNTHESIS_MODE_SIMULATED}
)

HIGH_STAKES_NOTICE_FRAGMENT = (
    "This summary is decision support only and is not medical, legal, "
    "financial, safety, or regulated professional advice."
)

#: Token cap per synthesis section. Workstream-2 raised this from 500
#: to 800; WP-D (F-07) raises it again to 3000 so a section can carry a
#: full multi-model reconciliation rather than stopping mid-sentence.
#:
#: This MUST stay in sync with ``settings.cost_synthesis_output_tokens``
#: (``config.py``), which is what both the point estimate and the
#: fail-safe ``max_cost_usd`` bound price each of the
#: ``cost_synthesis_sections`` section calls at. Pinned by
#: ``tests/unit/test_estimate_token_model.py::
#: test_bound_cap_assumptions_match_the_enforced_caps``.
#:
SYNTHESIS_SECTION_MAX_TOKENS = 3000

#: How much of a generated section actually survives to the user.
#:
#: DERIVED, never hardcoded — the same discipline the excerpt sizes below
#: follow. It was previously an unrelated literal
#: (``synthesis_length.DEFAULT_SECTION_MAX_CHARS = 4000``) sitting downstream
#: of a 3000-token ceiling worth ~12_000 chars, so roughly two thirds of the
#: output this run is BILLED for was generated, charged, and then thrown away
#: before anyone could read it, leaving a "…" as the only trace. Two constants
#: describing one quantity drift; one derived constant cannot.
#:
#: The Recommendation keeps its own, tighter ``RECOMMENDATION_MAX_CHARS`` —
#: that cap exists to protect the mandatory decision-support caveat from being
#: truncated away, which is a different job from this one.
SYNTHESIS_SECTION_MAX_CHARS = int(SYNTHESIS_SECTION_MAX_TOKENS * CHARS_PER_TOKEN)

#: The largest final synthesis this application can emit, in characters.
#:
#: WP-G2 (F-10) needs this to bound ``context["prior_synthesis"]`` — a value a
#: client re-sends from a PREVIOUS run, so "as large as we can produce" is the
#: only honest ceiling. It is summed from the caps that actually bound the
#: five ``FinalSynthesis`` prose fields plus the notice, NOT from
#: ``settings.cost_synthesis_sections``: that one is a PRICING knob, is
#: env-overridable, and retuning it would silently narrow a public request
#: field below what this file can still emit (adversarial review, WP-G2).
#:
#: All FIVE sections are counted at ``SYNTHESIS_SECTION_MAX_CHARS``, including
#: Recommendation. Its tighter ``RECOMMENDATION_MAX_CHARS`` reads like the real
#: bound and is NOT one: when the caveat already appears early in the text,
#: ``truncate_recommendation`` returns everything from the caveat onward
#: untruncated (``synthesis_length.py``, the ``body_budget <= 0`` path).
#: Measured: a 27_732-char recommendation came back at 27_701 against a 2_000
#: "cap". The only thing that really bounds that section is the token cap on
#: the call that produced it — which is ``SYNTHESIS_SECTION_MAX_CHARS``.
#: Using 2_000 here made this constant 50_117 while the stage could emit
#: 59_924, so a legitimate follow-up on this app's own output was rejected
#: with a 422 (demonstrated in adversarial review).
FINAL_SYNTHESIS_MAX_CHARS = 5 * SYNTHESIS_SECTION_MAX_CHARS + len(HIGH_STAKES_NOTICE_FRAGMENT)

#: How much of each initial answer the synthesis sections get to see.
#: WP-D (F-08) replaced a hardcoded ``[:600]``. Bounded by the token cap on
#: the call that produced the answer, so it is "as much as can exist".
SYNTHESIS_ANSWER_EXCERPT_MAX_CHARS = int(settings.initial_answer_max_tokens * CHARS_PER_TOKEN)

#: How much of each debate-round critique the synthesis sections get to see.
#: WP-D (F-08) replaced a hardcoded ``[:700]``.
#:
#: DERIVED FROM ``DEBATE_ROUND_MAX_TOKENS`` — and that derivation, not the
#: number it currently produces, is the point. A critique cannot be longer
#: than the debate call that produced it was allowed to be, so the ordering
#: matters: at the old 700-token debate cap the correct value here was 2800,
#: and only because F-07 raised that cap to 2000 is it now 8000. Hardcoding
#: 8000 would have been wrong before F-07 landed and would silently decouple
#: the next time the debate cap moves. The plan's blanket "→ 8000 chars" is
#: right for the answer excerpts above and wrong for this one.
SYNTHESIS_DEBATE_EXCERPT_MAX_CHARS = int(DEBATE_ROUND_MAX_TOKENS * CHARS_PER_TOKEN)


# System prompts for the five synthesis sections. Each prompt is
# intentionally narrow so the model stays on task and produces
# quotable, falsifiable output rather than hedging.
#
# Every one of them is built through ``_section_prompt``, which appends the
# untrusted-data rule. That is deliberate: the user prompt these accompany is
# fenced (``fence(...)`` in ``_synthesis_user_prompt``), and fencing without
# the rule protects nothing. Routing all five through one constructor means a
# sixth section cannot be added that silently omits it.


def _section_prompt(instruction: str) -> str:
    """A section's system prompt: its instruction, plus the untrusted-data rule."""
    return f"{instruction}\n\n{UNTRUSTED_DATA_SYSTEM_RULE}"


#: Longest source URL inlined into a prompt. Bounds a hostile URL's ability to
#: blow the char budget the rest of the prompt is sized against.
_MAX_SOURCE_URL_LEN = 500

#: Line separators a hostile string can use to forge its own prompt line.
#: ``\n``/``\r`` are the obvious ones; U+2028/U+2029/U+0085 are line breaks to
#: many renderers and tokenizers, and ``\v``/``\f`` end a line in others.
_LINE_BREAKING_CHARS = "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"


def _flatten_for_prompt(value: str, *, max_chars: int) -> str:
    """Make a provider-controlled string safe to inline on one prompt line.

    Applied to BOTH the source title and the source URL. They render on the
    same line, so flattening only one leaves the line forgeable through the
    other — which is exactly the gap the first version of this helper had.

    Belt and braces with ``providers._sanitize_source_url``, which now rejects
    a URL carrying any whitespace or control character at the producer. This
    is the consumer-side half: it holds even for a ``SourceReference``
    constructed by some future path that skips that sanitizer.
    """
    flattened = value or ""
    for ch in _LINE_BREAKING_CHARS:
        flattened = flattened.replace(ch, " ")
    return flattened[:max_chars]


_CONSENSUS_PROMPT = _section_prompt(
    "Given the four model answers below, list the 2-4 points where "
    "they agree. Use bullet points. Quote specific phrases from the "
    "answers. Do not invent consensus that is not in the answers. "
    "Output is shown to the user as 'Consensus'."
)
_DISAGREEMENT_PROMPT = _section_prompt(
    "Given the four model answers below, list the 2-4 points where "
    "they disagree. Name the specific models and quote the specific "
    "passages that disagree. Do not invent disagreement that is not "
    "in the answers. Output is shown to the user as 'Disagreement'."
)
_SOURCE_SUPPORT_PROMPT = _section_prompt(
    "For each of the four model answers, list the sources it cited "
    "(title and URL if available). Note which sources appear in two "
    "or more answers. Be concrete. Output is shown to the user as "
    "'Source support'."
)
_UNCERTAINTY_PROMPT = _section_prompt(
    "Given the four model answers and the debate rounds above, list "
    "1-3 things you cannot determine from the available evidence. Be "
    "honest. Do not pad. Output is shown to the user as 'Uncertainty'."
)
_RECOMMENDATION_PROMPT = _section_prompt(
    "Write a one-paragraph recommendation using the consensus, "
    "disagreement, sources, and uncertainty above. Hard rules:\n"
    "1. Always end with this sentence verbatim: 'This summary is "
    "decision support only and is not medical, legal, financial, "
    "safety, or regulated professional advice.'\n"
    "2. If `failed_count > 0`, lead with that fact in the first "
    "sentence — do not bury it.\n"
    "3. If source coverage — the share of answers carrying a primary "
    "source — is below 80%, recommend pausing for "
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
    synthesis_mode: str = SYNTHESIS_MODE_SIMULATED


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
    #: One entry per synthesis section that actually made a live LLM call (a
    #: templated section contributes NO entry — it was not billed). Each entry
    #: is the call's captured :class:`TokenUsage`, or ``None`` when the live
    #: call succeeded but the provider omitted the usage object. The cost layer
    #: reads this to measure the synthesis stage's real cost.
    live_call_usages: list[TokenUsage | None] = field(default_factory=list)


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
        context: dict[str, Any] | None = None,
    ) -> SynthesisResult:
        started_at = perf_counter()
        if safety_acknowledgements is None:
            safety_acknowledgements = []

        # WP-C / F-03: coverage is the share of ANSWERS carrying at least one
        # primary source. Both terms are counted in answers. The denominator
        # sums the per-answer ``answer_count``, so failed / cancelled /
        # deadline-exceeded slots (which carry 0) are out of scope — they
        # produced no text to source, and ``completeness`` already penalises
        # them. Aggregated coverage still excludes fallback citations, so a
        # fallback-sourced answer counts in the denominator but not the
        # numerator. See providers.calculate_citation_coverage.
        answer_count = sum(answer.citation_coverage.answer_count for answer in initial_answers)
        sourced_answer_count = sum(
            1
            for answer in initial_answers
            # Gated on the SAME field as the denominator (review A4): an answer
            # that produced no text cannot contribute to the numerator, even if
            # a caller hands one sources. Ungated, the ratio could exceed 1 and
            # fail CitationCoverage's ``le=1`` bound with an opaque Decimal error.
            if answer.citation_coverage.answer_count
            and any(not source.is_fallback for source in answer.sources)
        )
        coverage = calculate_citation_coverage(
            answer_count=answer_count,
            sourced_answer_count=sourced_answer_count,
        )

        failed_count = sum(
            1 for answer in initial_answers if answer.status is InitialAnswerStatus.FAILED
        )

        # PR-2: compute the consensus strength once and pass it
        # into the section builders. The previous implementation
        # used a substring check on the templated disagreement
        # text to set ``false_consensus_preserved`` — a
        # substring check that flipped to ``True`` on every
        # templated run (see Defect 3 in
        # ``docs/SYNTHESIS_AUDIT.md``). Computing the strength
        # explicitly makes the gate correct.
        consensus_strength = compute_consensus_strength(
            initial_answers=initial_answers,
            debate_outputs=debate_outputs,
        )

        user_prompt = self._user_prompt(
            initial_answers=initial_answers,
            debate_outputs=debate_outputs,
            failed_count=failed_count,
            coverage_ratio=coverage.sourced_answer_ratio,
            context=context,
        )

        # PERF-P0: parallelize the 5 synthesis section calls. The
        # ``_build_*`` methods each make an LLM call; previously they
        # ran serially (5x per-call latency). They share the same
        # ``user_prompt`` and read-only ``initial_answers``, so they
        # are safe to run concurrently.
        # PR-2 Item 3: each section builder is also wrapped in
        # its own try/except inside ``_submit_section`` so that a
        # single section's exception (e.g. an LLM call that
        # raises instead of returning None) is logged as a
        # failed step and the templated fallback is returned
        # instead of letting the whole synthesis raise.
        consensus_future = _submit_section(
            "Consensus",
            self._build_consensus,
            initial_answers=initial_answers,
            coverage=coverage,
            consensus_strength=consensus_strength,
            openrouter_key=openrouter_key,
            user_prompt=user_prompt,
            context=context,
        )
        disagreement_future = _submit_section(
            "Disagreement",
            self._build_disagreement,
            initial_answers=initial_answers,
            consensus_strength=consensus_strength,
            openrouter_key=openrouter_key,
            user_prompt=user_prompt,
            context=context,
        )
        source_future = _submit_section(
            "Source support",
            self._build_source_support,
            initial_answers=initial_answers,
            openrouter_key=openrouter_key,
            user_prompt=user_prompt,
            context=context,
        )
        uncertainty_future = _submit_section(
            "Uncertainty",
            self._build_uncertainty,
            initial_answers=initial_answers,
            debate_outputs=debate_outputs,
            openrouter_key=openrouter_key,
            user_prompt=user_prompt,
            context=context,
        )
        recommendation_future = _submit_section(
            "Recommendation",
            self._build_recommendation,
            initial_answers=initial_answers,
            coverage=coverage,
            failed_count=failed_count,
            openrouter_key=openrouter_key,
            user_prompt=user_prompt,
            context=context,
        )

        # PR-2 Item 3: per-section failure isolation. The
        # ``_safe_section_result`` wrapper catches exceptions
        # in the worker thread and returns
        # ``(text, exception_failed_step)``. The normal
        # templated path returns ``(text, None)``. The
        # orchestrator aggregates the exception steps into
        # ``SynthesisResult.failed_steps`` so a single
        # section raising no longer aborts the whole run.
        consensus_section, _consensus_failed, _consensus_live = _safe_section_result(
            consensus_future,
            "Consensus",
        )
        disagreement_section, _disagreement_failed, _disagreement_live = _safe_section_result(
            disagreement_future,
            "Disagreement",
        )
        source_section, _source_failed, _source_live = _safe_section_result(
            source_future,
            "Source support",
        )
        uncertainty_section, _uncertainty_failed, _uncertainty_live = _safe_section_result(
            uncertainty_future,
            "Uncertainty",
        )
        recommendation_section, _recommendation_failed, _recommendation_live = _safe_section_result(
            recommendation_future,
            "Recommendation",
        )
        failed_steps: list[str] = [
            step
            for step in (
                _consensus_failed,
                _disagreement_failed,
                _source_failed,
                _uncertainty_failed,
                _recommendation_failed,
            )
            if step is not None
        ]
        # One usage entry per section whose request was DISPATCHED, billed or
        # not knowable. ``live is None`` now means "provably not billed" (live
        # execution off, no key/model, or a pre-inference provider refusal) and
        # is the only case skipped. A section that fell back to templated TEXT
        # may still have a non-``None`` ``live`` — that is the F-06 fix, and it
        # is what stops a billed call vanishing from the receipt. The entry is
        # the call's captured usage, which may itself be ``None`` when the
        # response never reached us; the cost layer treats that as unmeasurable
        # and downgrades the run to ``estimated``.
        live_call_usages: list[TokenUsage | None] = [
            live.usage
            for live in (
                _consensus_live,
                _disagreement_live,
                _source_live,
                _uncertainty_live,
                _recommendation_live,
            )
            if live is not None
        ]

        false_consensus_preserved = self._is_false_consensus_preserved(
            initial_answers=initial_answers,
            consensus_strength=consensus_strength,
            disagreement=disagreement_section,
        )
        high_stakes_required = self._high_stakes_required(
            query_text=query_text,
            safety_acknowledgements=safety_acknowledgements,
        )
        high_stakes_notice = HIGH_STAKES_NOTICE_FRAGMENT if high_stakes_required else None

        decision_support_framing = "decision support only" in recommendation_section
        citation_target_met = coverage.target_met

        # PROVENANCE counts sections whose text the user is ACTUALLY READING
        # from the model — NOT ``len(live_call_usages)``, which counts billed
        # calls. The two diverge, and the divergence is a product-honesty bug:
        #
        # F-06 deliberately returns a non-``None`` live result even when the
        # completion is blank, so a billed call cannot vanish from the receipt.
        # WP-A moved provenance out of the prose (``TEMPLATED_FALLBACK_PREFIX``
        # is now "") and into this field. Combine the two and a run where all
        # five calls returned HTTP 200 with an EMPTY completion is billed five
        # times, falls back to templated text in every section, and was
        # labelled ``"live"`` — templated prose presented as model output,
        # exactly what the degraded-banner contract exists to prevent.
        #
        # ``live_call_usages`` is untouched above: cost still counts every
        # billed call. Only the label keys off usable text.
        live_text_sections = sum(
            1
            for live in (
                _consensus_live,
                _disagreement_live,
                _source_live,
                _uncertainty_live,
                _recommendation_live,
            )
            if live is not None and live.answer_text.strip()
        )
        synthesis_mode = (
            SYNTHESIS_MODE_LIVE
            if live_text_sections == 5
            else SYNTHESIS_MODE_FALLBACK
            if live_text_sections > 0
            else SYNTHESIS_MODE_SIMULATED
        )

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
            synthesis_mode=synthesis_mode,
        )

        duration_ms = max(1, round((perf_counter() - started_at) * 1000))
        synthesis_event_recorder.record(
            event_type="synthesis_completed",
            account_id=account_id,
            query_run_id=query_run_id,
            status=SynthesisStatus.COMPLETED,
            duration_ms=duration_ms,
            citation_coverage_ratio=str(coverage.sourced_answer_ratio),
            false_consensus_preserved=false_consensus_preserved,
            high_stakes_warning_required=high_stakes_required,
        )

        return SynthesisResult(
            final_synthesis=synthesis,
            failed_steps=failed_steps,
            missing_steps=[],
            live_call_usages=live_call_usages,
        )

    # -- helpers ----------------------------------------------------------

    def _user_prompt(
        self,
        *,
        initial_answers: list[InitialModelAnswer],
        debate_outputs: list[DebateOutput],
        failed_count: int,
        coverage_ratio: Decimal,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Build a compact, deterministic prompt that fits within the
        per-section token budget. We summarise each model answer and
        include the debate critique inline; the synthesis sections
        should already have the user's question in mind from the
        debate rounds.
        """
        # TWO parts. Our own directives and OUR OWN COMPUTED FACTS stay outside
        # the fence; only provider-originated text goes inside. The coverage
        # ratio and failed-model count are computed by this application from
        # its own run data — putting them inside a block the system rule labels
        # untrusted would invite the model to discount the very figures the
        # Recommendation prompt requires it to act on.
        #
        # The orchestrator does NOT include the raw user query text in the
        # synthesis user prompt for two reasons: (a) it never leaves the
        # server-side debounce path, (b) each section prompt is already focused
        # on a specific lens. The answer excerpts carry the question context.
        directives: list[str] = [
            "Do NOT repeat the user's question verbatim in your response.",
            f"Source coverage: {Decimal(str(coverage_ratio)) * 100:.0f}% of the answers "
            "carried at least one primary source.",
            f"Failed model count: {failed_count}.",
        ]

        # Untrusted from here down.
        lines: list[str] = []
        # WP-G2 (F-10): the follow-up context. ``prior_question`` already
        # reaches every synthesis call through the SYSTEM prompt
        # (``providers._post_openrouter``); ``prior_synthesis`` belongs in the
        # USER prompt, which is what ``costs.py`` has always priced it as and
        # what nothing sent. It is client-supplied text from a previous run, so
        # it goes INSIDE the fence with everything else provider-originated —
        # never into the directives above it.
        #
        # FLATTENED, like every other untrusted value in this prompt. The fence
        # stops it forging the evidence BOUNDARY, but not the prompt's internal
        # structure: with its newlines intact it can open its own
        # "Four model answers…" or "- round 1:" line and manufacture a
        # consensus no model produced (demonstrated in adversarial review).
        # It also carries a consumer-side cap, so the prompt stays sized even
        # if the request-level bound is ever loosened.
        prior_synthesis = _flatten_for_prompt(
            (context or {}).get("prior_synthesis") or "",
            max_chars=FINAL_SYNTHESIS_MAX_CHARS,
        ).strip()
        if prior_synthesis:
            directives.append(
                "The evidence block opens with the synthesis from the user's previous "
                "question. Treat it as prior context for this follow-up, not as an "
                "answer to restate."
            )
            lines.append("Synthesis of the user's previous question:")
            lines.append(prior_synthesis)
            lines.append("")
        lines.append(
            "Four model answers (model name, status, first "
            f"{SYNTHESIS_ANSWER_EXCERPT_MAX_CHARS} chars):"
        )
        for answer in initial_answers:
            # Workstream-2 bumped this 250 -> 600; WP-D (F-08) takes it to the
            # full answer. Even 600 chars left the disagreement section quoting
            # from a fragment, which is the same defect at a larger size.
            excerpt = (
                (answer.answer_text or "")
                .strip()
                .replace("\n", " ")[:SYNTHESIS_ANSWER_EXCERPT_MAX_CHARS]
            )
            # Source titles are provider-controlled (`:online` annotations, and
            # the title of whatever page a web search returned), so they get the
            # SAME treatment as every other untrusted value here: newlines
            # flattened so a title cannot forge its own prompt lines, and a
            # length cap so it cannot blow the char budget the rest of this
            # prompt is sized against. `_MAX_SOURCE_TITLE_LEN` already bounds
            # the Tavily path at the producer; the annotation path has no such
            # cap, so bound it at the consumer too.
            sources_str = ", ".join(
                f"{_flatten_for_prompt(s.title, max_chars=_MAX_SOURCE_TITLE_LEN)}"
                f" ({_flatten_for_prompt(s.url, max_chars=_MAX_SOURCE_URL_LEN)})"
                for s in (answer.sources or [])[:3]
            )
            # ``display_name`` is the catalog's short label
            # ("Claude Haiku 4.5"). Falling back to ``model_id`` keeps
            # the prompt well-formed even if the catalog is unaware
            # of the model.
            label = answer.display_name or answer.model_id
            lines.append(f"- {label} ({answer.status.value}): {excerpt}")
            if sources_str:
                lines.append(f"    sources: {sources_str}")
        if debate_outputs:
            lines.append("")
            lines.append("Debate rounds (round 1 then round 2 critique):")
            for round_output in debate_outputs:
                # Workstream-2 bumped this 300 -> 700; WP-D (F-08) derives it
                # from the debate round's own token cap instead. The critique
                # lines are what the uncertainty section leans on, and a
                # critique cut mid-claim left the model to fill in the gap.
                excerpt = (
                    (round_output.critique_text or "")
                    .strip()
                    .replace("\n", " ")[:SYNTHESIS_DEBATE_EXCERPT_MAX_CHARS]
                )
                lines.append(f"- round {round_output.round_number}: {excerpt}")
        # Provider-originated text throughout — fenced as untrusted evidence,
        # with the matching rule carried on each section's system prompt. See
        # ``untrusted_text``.
        return "\n".join(directives) + "\n\n" + fence("\n".join(lines))

    def _build_consensus(
        self,
        *,
        initial_answers: list[InitialModelAnswer],
        coverage: CitationCoverage,
        consensus_strength: ConsensusStrength,
        openrouter_key: str,
        user_prompt: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[str, str | None, LiveProviderResult | None]:
        successful = [
            answer for answer in initial_answers if answer.status is InitialAnswerStatus.COMPLETED
        ]
        if not successful:
            # No completed answers at all — the templated text
            # does NOT get the heuristic prefix because the
            # message already names the situation explicitly.
            # The orchestrator's "0 completed" path is rare and
            # the user can read the message and infer it's a
            # fallback.
            return (
                (
                    "No model returned a usable response, so no consensus could be "
                    "formed. This run is reported as a partial result and the failed "
                    "steps are listed separately."
                ),
                None,
                None,
            )
        sourced_pct = round(coverage.sourced_answer_ratio * 100)
        # PR-2: the templated consensus text now varies by
        # strength. "strong" and "weak" both describe a real
        # signal; "divided" frames the section as "the models
        # do not agree". The audit pins the boundary.
        if consensus_strength == "strong":
            base = (
                f"Four models were asked the same question; {len(successful)} returned "
                f"a usable response and broadly agree. Roughly {sourced_pct}% of those "
                "answers carried at least one visible source reference. "
                "Treat the consensus as a working hypothesis, not a verdict."
            )
        elif consensus_strength == "divided":
            base = (
                f"Four models were asked the same question; {len(successful)} returned "
                f"a usable response but did not agree. Roughly {sourced_pct}% of those "
                "answers carried at least one visible source reference. "
                "Disagreement is preserved as the dominant signal — do not treat the "
                "consensus as a verdict."
            )
        else:
            base = (
                f"Four models were asked the same question; {len(successful)} returned "
                f"a usable response. Roughly {sourced_pct}% of those answers carried at "
                "least one visible source reference. Some models disagreed "
                "on points; treat the consensus as a working hypothesis, not a verdict."
            )
        templated = TEMPLATED_FALLBACK_PREFIX + base
        live = self._call_synthesis_model(
            openrouter_key=openrouter_key,
            system_prompt=_CONSENSUS_PROMPT,
            user_prompt=user_prompt,
            context=context,
        )
        # F-06: ``live`` is non-None whenever the call MAY HAVE BEEN BILLED,
        # even if its output was unusable — a request the provider refused
        # before inference (404, bad key, rate limit) arrives as ``None``
        # instead, with nothing to record. Blank text therefore means "use the
        # templated section" while STILL returning the result, so its usage is
        # recorded and a billed call cannot vanish from the receipt.
        text = "" if live is None else live.answer_text.strip()
        if not text:
            return truncate_section(templated, max_chars=SYNTHESIS_SECTION_MAX_CHARS), None, live
        return (
            truncate_section(text, max_chars=SYNTHESIS_SECTION_MAX_CHARS),
            None,
            live,
        )

    def _build_disagreement(
        self,
        *,
        initial_answers: list[InitialModelAnswer],
        consensus_strength: ConsensusStrength,
        openrouter_key: str,
        user_prompt: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[str, str | None, LiveProviderResult | None]:
        fallback_paths = {answer.provider_path for answer in initial_answers}
        if ProviderPath.FALLBACK_SEARCH in fallback_paths and len(fallback_paths) > 1:
            base = (
                "Models disagree on whether to rely on the primary provider or the fallback "
                "search path. This disagreement must be preserved explicitly to avoid an "
                "unsupported consensus."
            )
        elif consensus_strength == "divided":
            base = (
                "Models do not agree. The disagreement is preserved as the dominant signal — "
                "do not collapse the four answers into a single consensus claim."
            )
        else:
            base = (
                "Models disagree on the supporting evidence. The disagreement is preserved "
                "explicitly to avoid an unsupported consensus."
            )
        templated = TEMPLATED_FALLBACK_PREFIX + base
        live = self._call_synthesis_model(
            openrouter_key=openrouter_key,
            system_prompt=_DISAGREEMENT_PROMPT,
            user_prompt=user_prompt,
            context=context,
        )
        # F-06: ``live`` is non-None whenever the call MAY HAVE BEEN BILLED,
        # even if its output was unusable — a request the provider refused
        # before inference (404, bad key, rate limit) arrives as ``None``
        # instead, with nothing to record. Blank text therefore means "use the
        # templated section" while STILL returning the result, so its usage is
        # recorded and a billed call cannot vanish from the receipt.
        text = "" if live is None else live.answer_text.strip()
        if not text:
            return truncate_section(templated, max_chars=SYNTHESIS_SECTION_MAX_CHARS), None, live
        return (
            truncate_section(text, max_chars=SYNTHESIS_SECTION_MAX_CHARS),
            None,
            live,
        )

    def _build_source_support(
        self,
        *,
        initial_answers: list[InitialModelAnswer],
        openrouter_key: str,
        user_prompt: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[str, str | None, LiveProviderResult | None]:
        # WP-C review A1/A4: this prose sits directly under the "Source support"
        # tile that renders ``sourced_answer_ratio``. It MUST use the same
        # denominator, or a run with a failed slot shows "100%" above "3 of 4
        # models" — two different denominators on one screen, which is the exact
        # misreading WP-C exists to remove. ``answer_count`` is 1 for an answer
        # that produced text and 0 otherwise, so this counts answers that came
        # back. The numerator is gated on the same field so it can never exceed
        # the denominator.
        cited = sum(
            1
            for answer in initial_answers
            if answer.citation_coverage.answer_count
            and any(not source.is_fallback for source in answer.sources)
        )
        total = sum(answer.citation_coverage.answer_count for answer in initial_answers)
        if cited == 0:
            return "No model returned visible source references for this query.", None, None
        base = (
            f"{cited} of {total} responding model{'' if total == 1 else 's'} returned visible "
            "source references. The references come "
            "from the primary provider; fallback sources are listed separately and are not "
            "counted toward the source coverage target."
        )
        templated = TEMPLATED_FALLBACK_PREFIX + base
        live = self._call_synthesis_model(
            openrouter_key=openrouter_key,
            system_prompt=_SOURCE_SUPPORT_PROMPT,
            user_prompt=user_prompt,
            # WP-G2 (F-10): this was the one section of five that accepted
            # ``context`` and then dropped it, so ``prior_question`` never
            # reached its system prompt while every run paid for it.
            context=context,
        )
        # F-06: ``live`` is non-None whenever the call MAY HAVE BEEN BILLED,
        # even if its output was unusable — a request the provider refused
        # before inference (404, bad key, rate limit) arrives as ``None``
        # instead, with nothing to record. Blank text therefore means "use the
        # templated section" while STILL returning the result, so its usage is
        # recorded and a billed call cannot vanish from the receipt.
        text = "" if live is None else live.answer_text.strip()
        if not text:
            return truncate_section(templated, max_chars=SYNTHESIS_SECTION_MAX_CHARS), None, live
        return (
            truncate_section(text, max_chars=SYNTHESIS_SECTION_MAX_CHARS),
            None,
            live,
        )

    def _build_uncertainty(
        self,
        *,
        initial_answers: list[InitialModelAnswer],
        debate_outputs: list[DebateOutput],
        openrouter_key: str,
        user_prompt: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[str, str | None, LiveProviderResult | None]:
        failed = sum(1 for answer in initial_answers if answer.status is InitialAnswerStatus.FAILED)
        if failed:
            base = (
                f"{failed} model(s) failed outright, so the synthesis does not represent a full "
                "consensus. Re-run, change a model slot, or escalate to a human reviewer before "
                "committing to a decision."
            )
        else:
            # PR-2: add "(debate was skipped)" marker when the
            # orchestrator was given an empty debate_outputs list
            # (defense-in-depth — query_runs.py short-circuits
            # before reaching here when debate is missing, but
            # the orchestrator could be called directly with an
            # empty list).
            debate_marker = " (debate was skipped)" if not debate_outputs else ""
            base = (
                "All four models returned a usable response, but no model is independently "
                f"authoritative{debate_marker}. Treat the synthesis as a working hypothesis "
                "pending human review."
            )
        templated = TEMPLATED_FALLBACK_PREFIX + base
        live = self._call_synthesis_model(
            openrouter_key=openrouter_key,
            system_prompt=_UNCERTAINTY_PROMPT,
            user_prompt=user_prompt,
            context=context,
        )
        # F-06: ``live`` is non-None whenever the call MAY HAVE BEEN BILLED,
        # even if its output was unusable — a request the provider refused
        # before inference (404, bad key, rate limit) arrives as ``None``
        # instead, with nothing to record. Blank text therefore means "use the
        # templated section" while STILL returning the result, so its usage is
        # recorded and a billed call cannot vanish from the receipt.
        text = "" if live is None else live.answer_text.strip()
        if not text:
            return truncate_section(templated, max_chars=SYNTHESIS_SECTION_MAX_CHARS), None, live
        return (
            truncate_section(text, max_chars=SYNTHESIS_SECTION_MAX_CHARS),
            None,
            live,
        )

    def _build_recommendation(
        self,
        *,
        initial_answers: list[InitialModelAnswer],
        coverage: CitationCoverage,
        failed_count: int,
        openrouter_key: str,
        user_prompt: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[str, str | None, LiveProviderResult | None]:
        target_met = coverage.target_met
        if target_met and failed_count == 0:
            base = (
                "Recommendation: act on the consensus only after a human reviewer has audited "
                "the visible source references. The source coverage target is met, but this is "
                "decision support only and is not medical, legal, financial, safety, or regulated "
                "professional advice."
            )
        else:
            base = (
                "Recommendation: do not act on the consensus yet. "
                + (
                    "Fewer than 80% of the answers carried a primary source. "
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
        templated = TEMPLATED_FALLBACK_PREFIX + base
        live = self._call_synthesis_model(
            openrouter_key=openrouter_key,
            system_prompt=_RECOMMENDATION_PROMPT,
            user_prompt=user_prompt,
            context=context,
        )
        # F-06: see the other section builders — blank text means a call that
        # may have been billed came back unusable, not that no call was made.
        text = "" if live is None else live.answer_text.strip()
        if not text:
            return truncate_recommendation(templated), None, live
        return truncate_recommendation(text), None, live

    def _call_synthesis_model(
        self,
        *,
        openrouter_key: str,
        system_prompt: str,
        user_prompt: str,
        context: dict[str, Any] | None = None,
    ) -> LiveProviderResult | None:
        # Same operator-opt-in guard as in ``debate._call_debate_model``:
        # if live execution is disabled, return ``None`` and let the
        # templated path serve. Without this check the synthesis
        # would silently call the network in tests / staging where
        # the operator has explicitly turned live execution off.
        if not settings.openrouter_live_execution_enabled:
            return None
        if not openrouter_key or not settings.synthesis_model_id:
            return None
        # No post-processing — see ``debate._call_debate_model`` for the F-06
        # billing contract this preserves. ``None`` means nothing was billed
        # (so the section records no usage entry and the run may stay
        # ``measured``); a blank-text result means a request was dispatched and
        # may have been billed (so the section serves the templated text but
        # still records the entry).
        return provider_execution_service.call_with_prompt(
            openrouter_key=openrouter_key,
            model_id=settings.synthesis_model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=SYNTHESIS_SECTION_MAX_TOKENS,
            context=context,
        )

    def _synthesis_fallback_notice(self, section_label: str) -> str:
        return (
            f"{section_label} section used a local heuristic because the "
            f"live synthesis call failed or was not configured."
        )

    def _is_false_consensus_preserved(
        self,
        *,
        initial_answers: list[InitialModelAnswer],
        consensus_strength: ConsensusStrength,
        disagreement: str,
    ) -> bool:
        # PR-2 Defect 3 fix: the previous implementation
        # returned ``"disagree" in disagreement.lower() and any(...)
        # — a substring check that flipped to ``True`` on every
        # templated run because the templated disagreement
        # branch always contains the word "disagree" (see
        # ``docs/SYNTHESIS_AUDIT.md`` Defect 3). The new
        # implementation uses the precomputed ``consensus_strength``
        # instead, so the flag is set from the underlying signal
        # rather than from a keyword search in the section text.
        #
        # The ``disagreement`` arg is kept in the signature for
        # backwards-compatibility with existing tests that
        # import this helper. It is not used in the new logic.
        del disagreement
        if not any(answer.status is InitialAnswerStatus.COMPLETED for answer in initial_answers):
            return False
        return consensus_strength in {"weak", "divided"}

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


def _final_synthesis_alignment_text(final_synthesis: FinalSynthesis | None) -> str | None:
    """The substantive final-answer text used to test per-model alignment: the
    consensus plus the recommendation of a COMPLETED synthesis, **and only when
    a model wrote them.**

    Returns ``None`` when there is nothing model-authored to compare against, in
    which case alignment falls back to the panel-strength inference (derived
    from the models' own openings and the debate critiques) rather than
    comparing openings to text this product wrote. Three cases return ``None``:
    a missing synthesis, one whose ``status != COMPLETED``, and — since #171
    finding 5 — one whose sections are Quorum's own template.

    ``synthesis_mode`` is the orchestrator's own account of who wrote the five
    sections (``synthesis.py`` computes it from which sections came back with
    usable live text). Only ``"live"`` means every section is the model's, so
    only ``"live"`` yields a text a model authored. ``"fallback"`` is a MIXED
    run — 1 to 4 sections live — and it does not say WHICH, so it cannot
    establish that the consensus and the recommendation specifically are the
    model's; a mixed text is contaminated evidence, not partial evidence, so it
    is refused whole.

    Why this is not cosmetic (#171 finding 5, reproduced at ``9c60bc3``): with
    a templated synthesis this function handed ``classify_model_alignment``
    Quorum's own weak-consensus boilerplate, which ends "Some models disagreed
    on points; treat the consensus as a working hypothesis, not a verdict." A
    minority answer whose own prose echoed that generic advisory language
    matched 12 of its 25 opening 4-grams against it — 48%, against a 10%
    containment threshold — and was counted as landing in the final answer. The
    served run read ``live_count`` 4, ``failed_steps`` empty, ``demo_mode``
    false and ``agreement`` 3 of 4, and the third of those three was granted by
    this product's own words about an outlier it had never read.
    """
    if final_synthesis is None or final_synthesis.status is not SynthesisStatus.COMPLETED:
        return None
    if final_synthesis.synthesis_mode != SYNTHESIS_MODE_LIVE:
        return None
    # NOTE — "live" does NOT mean every word here is the model's. Rule 1 of
    # ``_RECOMMENDATION_PROMPT`` dictates the decision-support caveat verbatim,
    # ``_CaveatEnforcer`` appends it when the model omits it, and
    # ``_CONSENSUS_PROMPT`` invites the model to quote phrases from answers that
    # may themselves carry it. That dictated sentence alone clears the
    # containment threshold, so it is removed from the COMPARISON rather than
    # from this text: ``synthesis_consensus`` subtracts its 4-grams from both
    # sides (see ``_DICTATED_CAVEAT_NGRAMS``). Doing it there and not here is
    # deliberate — it covers the consensus as well as the recommendation, it
    # uses the same tokenisation as the comparison so punctuation variants
    # cannot slip past, and it deletes none of the model's prose. Three
    # string-surgery drafts of a strip-it-here version each left a way in.
    text = " ".join(p for p in (final_synthesis.consensus, final_synthesis.recommendation) if p)
    return text or None


def _final_synthesis_was_templated(final_synthesis: FinalSynthesis | None) -> bool:
    """Is there a COMPLETED final answer on the screen that a model did NOT write?

    Distinct from ``_final_synthesis_alignment_text(...) is None``, which is
    also true when there is no final answer at all. ``classify_model_alignment``
    needs the two apart: a failed synthesis keeps the pre-existing
    panel-strength inference, while a templated one must not align a minority,
    because the inference says yes to every minority on a ``"strong"`` panel and
    would report a model as having moved to a consensus no model authored.
    """
    if final_synthesis is None or final_synthesis.status is not SynthesisStatus.COMPLETED:
        return False
    return final_synthesis.synthesis_mode != SYNTHESIS_MODE_LIVE


def build_agreement_and_positions(
    *,
    initial_answers: list[InitialModelAnswer],
    debate_outputs: list[DebateOutput],
    final_synthesis: FinalSynthesis | None = None,
) -> tuple[AgreementSummary, list[PositionMovement]]:
    """Single deterministic entry point for the screen-05 verdict ring and the
    "how positions moved" table.

    Classifies each model's alignment once (:func:`classify_model_alignment`),
    then derives the agreement count and the per-model position movements from
    that shared classification so the ring and the table can never disagree.
    When ``final_synthesis`` is supplied, per-model alignment is derived by
    comparing each opening against the actual final-answer content rather than
    blanket-aligning the whole panel; without it, alignment falls back to the
    panel-strength inference. Pure and deterministic: same inputs → same
    output, no randomness, no wall-clock. Whether the underlying content is
    live or simulated is already surfaced by
    ``QueryRunResultResponse.demo_mode``.
    """
    alignments = classify_model_alignment(
        initial_answers,
        debate_outputs,
        model_authored_final_text=_final_synthesis_alignment_text(final_synthesis),
        final_answer_was_templated=_final_synthesis_was_templated(final_synthesis),
    )
    agreement = summarize_agreement(initial_answers=initial_answers, alignments=alignments)
    positions = build_position_movements(
        initial_answers=initial_answers,
        debate_outputs=debate_outputs,
        alignments=alignments,
    )
    return agreement, positions


synthesis_event_recorder = InMemorySynthesisEventRecorder()
synthesis_stub_service = SynthesisOrchestrationService()

# PERF-P0: thread pool for parallel synthesis section calls. The
# synthesis stage makes 5 LLM calls (consensus, disagreement,
# source_support, uncertainty, recommendation). Running them in
# parallel via the shared pool cuts wall-clock latency from 5x to
# ~1x the per-call latency. Pool size of 20 = max_concurrent_runs
# (16) * sections per run (5) / 4 to give steady-state headroom.
_synthesis_section_pool = ThreadPoolExecutor(max_workers=20, thread_name_prefix="synthesis-section")


#: A built section: ``(section_text, failed_step, live_result)``. ``live_result``
#: is the :class:`LiveProviderResult` whenever the section's request was
#: DISPATCHED — including when it came back unusable and the section text fell
#: back to the template — and carries the captured token usage. ``None`` means
#: provably NOT billed (live execution off, no key/model, or a pre-inference
#: provider refusal), which is the only case the cost layer may ignore.
SectionResult = tuple[str, str | None, LiveProviderResult | None]
SectionFuture = Future[SectionResult]
SectionBuilder = Callable[..., SectionResult]


def _submit_section(label: str, builder: SectionBuilder, **kwargs: Any) -> SectionFuture:
    """PR-2 Item 3: per-section failure isolation.

    Submits a section builder to the shared thread pool. The
    pool's ``.submit()`` returns a ``Future`` whose ``.result()``
    will re-raise any exception in the worker; we keep the
    raising behavior on the future side (so the worker can
    finish cleanly) and let ``_safe_section_result`` catch the
    exception in the orchestrator thread. This split lets the
    pool worker do its work in parallel with the other
    sections, which is the perf-P0 win; the orchestrator only
    waits on the futures at the join point.
    """
    return _synthesis_section_pool.submit(builder, **kwargs)


def _safe_section_result(future: SectionFuture, label: str) -> SectionResult:
    """PR-2 Item 3: catch per-section builder exceptions.

    Returns ``(section_text, failed_step, live_result)``. If the section
    builder raised, we log a structured event, return a templated fallback
    string with the ``TEMPLATED_FALLBACK_PREFIX``, a failed-step string the
    orchestrator aggregates into ``SynthesisResult.failed_steps``, and a
    ``None`` live result (a failed section made no billed call).

    INVARIANT for measured-cost honesty: a raised section is reported here as
    ``live_result=None`` (not billed). This is only honest because a builder
    never bills and *then* raises — after ``_call_synthesis_model`` returns a
    live result the remaining builder code is pure string trimming that does
    not raise. If a future change introduces a fallible step AFTER the live
    call, this ``None`` would drop a billed call's usage and could yield a
    dishonest ``measured`` undercount; such a step must instead surface the
    ``LiveProviderResult`` so ``_actual_cost`` can fall back to ``estimated``.
    """
    try:
        text, notice, live = future.result()
    except Exception as exc:
        logging.getLogger(__name__).error(
            "synthesis_section_failed",
            extra={"section": label, "error": str(exc), "error_type": type(exc).__name__},
        )
        return (
            f"The {label.lower()} section could not be produced for this run.",
            f"{label} section raised an exception: {type(exc).__name__}",
            None,
        )
    return (text, notice, live)


synthesis_orchestration_service = synthesis_stub_service
