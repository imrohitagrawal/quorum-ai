"""Provider execution service.

The MVP supports two execution modes selected at request time:

* ``local_simulation`` (the default when no API key is configured) generates
  deterministic, well-shaped stub answers and citations. These answers are
  clearly marked as simulated so end users cannot mistake them for live model
  output. They are suitable for demos, tests, and the offline-safe default
  documented in ``docs/03-source-of-truth.md``.
* ``openrouter_search`` is used when ``OPENROUTER_API_KEY`` is set and
  ``OPENROUTER_LIVE_EXECUTION_ENABLED=true``. We POST to the configured provider's
  ``/chat/completions`` endpoint with the configured model id and parse the
  response. If the provider call returns no usable citations, the service falls back
  to a ``fallback_search`` path with a user-safe notice.

The service is responsible for:

1. Building the request payload and validating the response shape.
2. Keeping a per-call event record on the in-memory recorder. Events are
   ``account_id``-scoped (no session-id indirection) and never contain the
   raw API key, the full prompt, or any other secret material.
3. Returning a Pydantic ``InitialModelAnswer`` that the API can serialise
   directly without further mutation.

Anti-goals: this module never logs the configured API key, the user query
text, or any model output that the user did not consent to expose.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import StrEnum
from http.client import HTTPException
from math import ceil
from threading import RLock
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from product_app.config import RuntimeEnvironment, settings
from product_app.feedback_store import record_event as _record_feedback_event
from product_app.model_slots import ModelSlot, openrouter_model_catalog_service
from product_app.provider_keys import ProviderCredentialSource
from product_app.untrusted_text import fence

_LOGGER = logging.getLogger(__name__)

CITATION_COVERAGE_TARGET = Decimal("0.80")


def _resolve_display_name(model_id: str) -> str:
    """Resolve a model_id to its catalog short_name; fall back to the id.

    The short_name ("Claude Haiku 4.5") is what the UI's model-card
    headers, synthesis prompts, and synthesis output text use — much
    friendlier than the raw "anthropic/claude-haiku-4.5" id. When the
    catalog does not know the model (live-fetch failed AND it isn't in
    the static fallback), we return the model_id verbatim so the user
    still sees something.
    """
    return openrouter_model_catalog_service.lookup_short_name(model_id) or model_id


#: Stable prefix used for the stub citation URLs that ship with the local
#: simulation mode. Lives under example.test (an IANA-reserved domain) so it
#: cannot accidentally resolve to a real host.
LOCAL_SIMULATION_URL_PREFIX = "https://example.test/local-demo/"


class ProviderPath(StrEnum):
    LOCAL_SIMULATION = "local_simulation"
    OPENROUTER_SEARCH = "openrouter_search"
    FALLBACK_SEARCH = "fallback_search"


class InitialAnswerStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class SourceReference(BaseModel):
    title: str
    url: str
    provider: ProviderPath
    is_fallback: bool = False


class CitationCoverage(BaseModel):
    """How much of the panel's output carries a primary source.

    WP-C / F-03. The metric is **the fraction of answers that carry at least
    one primary (non-fallback) source** — nothing more, and the field names say
    so. It used to divide a per-answer BOOLEAN by a characters-based estimate
    of "material claims", so the numerator and denominator did not share units
    and a run of four long, fully-sourced answers scored ~12% against an 80%
    target. Every run was therefore labelled provisional and the recommendation
    always said "pause for human review".

    What this metric does NOT claim: that each individual assertion inside an
    answer is supported. Counting sources says a citation is present; it says
    nothing about whether the citation supports the claim. The signal that
    checks whether a citation marker resolves to a real source is
    ``citation_marker_grounding`` in :mod:`product_app.evaluation` — a
    different, host-keyed authority. Do not conflate the two.
    """

    #: Answers in scope. ``1`` for a completed answer; ``0`` for a failed,
    #: cancelled or deadline-exceeded answer, which produced no text to source.
    #: At run level this is the number of answers that produced text.
    answer_count: int = Field(ge=0)
    #: Of those, how many carried at least one ``is_fallback=False`` source.
    #: Fallback sources are real pages, but they are not the model's own
    #: research, so they deliberately do not count toward the target.
    sourced_answer_count: int = Field(ge=0)
    #: ``sourced_answer_count / answer_count``, quantized to 2dp.
    sourced_answer_ratio: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    target_ratio: Decimal = CITATION_COVERAGE_TARGET
    target_met: bool

    @model_validator(mode="after")
    def _numerator_cannot_outrun_denominator(self) -> CitationCoverage:
        """More sourced answers than answers is not a number, it is a bug.

        Reachable only by a caller that gates the numerator on a different
        predicate than the denominator — which is exactly the class of defect
        WP-C removed. Without this the failure surfaces as ``sourced_answer_ratio
        Input should be <= 1``, an opaque Decimal-range error that names neither
        field. Say what actually went wrong instead.
        """
        if self.sourced_answer_count > self.answer_count:
            raise ValueError(
                f"sourced_answer_count ({self.sourced_answer_count}) exceeds "
                f"answer_count ({self.answer_count}): the numerator and the "
                "denominator must be gated on the same predicate"
            )
        return self


#: Upper bound on a plausible per-call token count. Real completions are far
#: below this (the largest model context windows are a few million tokens); a
#: value above it is treated as a malformed/hostile payload and the usage is
#: dropped (the run stays ``estimated``). The bound also keeps the downstream
#: Decimal cost arithmetic well within the default 28-digit precision, so a
#: crafted huge count cannot raise ``decimal.InvalidOperation`` on the result
#: endpoint.
_MAX_PLAUSIBLE_TOKENS = 100_000_000


# ---------------------------------------------------------------------------
# F-09 — the closed set of user-facing provider notices.
#
# These render on the model cards, the run-notices list, and the provider-
# failure detail row (``app.js`` ``renderLiveNotices`` / ``showProviderFailure``
# / the per-card notice), through ``textContent`` — so they are plain prose
# read by a user, not a log line read by us.
#
# They live here, together and named, for the reason ``readiness`` keeps its
# reason vocabulary together: copy that is scattered across branch arms drifts
# into developer shorthand one branch at a time. That is exactly how ":online"
# and "citation annotations" reached the screen (triage issue #2).
# ``tests/unit/test_provider_notice_copy.py`` walks this registry.
# ---------------------------------------------------------------------------

# Each notice states what was OBSERVED, never an unobserved cause, and
# never a direction ("below") that depends on where it happens to be
# rendered — these strings appear on the model card (BELOW the answer
# text), in the run-notices list, and in the live-run fallback panel,
# which has no source list in it at all.
NOTICE_SEARCH_DISABLED = (
    "Web search was turned off for this model, so its answer comes "
    "from what it learned during training."
)
NOTICE_SOURCES_FROM_BACKUP_SEARCH = (
    "This model did not return any sources of its own. The sources "
    "shown here came from a separate web search, so they do not count "
    "toward this run's source support."
)
NOTICE_NO_SOURCES_FOUND = (
    "This model's answer came back without any linked sources, so it "
    "does not count toward this run's source support."
)
NOTICE_FALLBACK_SOURCE_SUPPORT = (
    "The sources shown here did not come from this model, so they do "
    "not count toward this run's source support."
)
# #171 deleted ``NOTICE_LIVE_RETURNED_NOTHING`` — "No usable answer came back
# for this model, so the text shown here was produced by Quorum's local
# simulation." Nothing can emit it any more: when live execution is on and a
# model returns nothing usable, the slot is now REPORTED MISSING rather than
# filled with simulated text, so it carries ``NOTICE_PROVIDER_UNAVAILABLE``
# instead. The copy guard
# (``test_every_registered_notice_is_reachable_from_the_provider_layer``)
# reds on a registered-but-unemitted notice, which is how this deletion was
# forced rather than remembered.
#
# "not active" rather than "turned off": this also fires when live
# execution IS enabled but no key is set, where "turned off" would send
# the operator to the wrong switch.
NOTICE_DEMO_MODE = (
    "Live model calls are not active for this deployment, so the text "
    "shown here was produced by Quorum's local simulation. It is not a "
    "real model answer."
)
NOTICE_PROVIDER_UNAVAILABLE = (
    "This model's answer is unavailable because the provider did not return a usable response."
)
NOTICE_CANCELLED = "Cancelled before this model was asked for an answer."
NOTICE_RUN_DEADLINE = "The run reached its time limit before this model answered."

#: Every notice the provider layer may show a user. Adding a branch that
#: invents its own string bypasses the copy guard, so add it HERE.
PROVIDER_NOTICES: tuple[str, ...] = (
    NOTICE_SEARCH_DISABLED,
    NOTICE_SOURCES_FROM_BACKUP_SEARCH,
    NOTICE_NO_SOURCES_FOUND,
    NOTICE_FALLBACK_SOURCE_SUPPORT,
    NOTICE_DEMO_MODE,
    NOTICE_PROVIDER_UNAVAILABLE,
    NOTICE_CANCELLED,
    NOTICE_RUN_DEADLINE,
)


class TokenUsage(BaseModel):
    """Real per-call token usage as reported by the provider.

    Parsed from the ``usage`` object OpenRouter returns on a completed
    ``/chat/completions`` response. Captured so a run's actual cost can be
    computed from measured tokens rather than the pre-run estimate. Absent
    (``None``) whenever the provider omitted the object or a call did not go
    live — the cost layer treats a missing record as "cannot measure this
    call" and keeps the run tagged ``estimated`` (never fabricates usage).
    """

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class InitialModelAnswer(BaseModel):
    slot_number: int = Field(ge=1, le=4)
    model_id: str
    display_name: str = ""
    answer_text: str
    sources: list[SourceReference]
    provider_attempt_order: list[ProviderPath]
    provider_path: ProviderPath
    fallback_used: bool
    status: InitialAnswerStatus
    latency_ms: int = Field(ge=0)
    citation_coverage: CitationCoverage
    error_code: str | None = None
    provider_notice: str | None = None
    #: Real per-call token usage when this answer came from a live provider
    #: call that reported it; ``None`` for simulated/fallback/failed slots
    #: (no real billing) or when the provider omitted the usage object. Read
    #: by the cost layer to compute a measured actual cost.
    token_usage: TokenUsage | None = None
    #: WP-D (F-07): this answer was cut short by the provider's token ceiling
    #: (``finish_reason == "length"``), so the text below is incomplete. Only
    #: a live provider call can set this — simulated, fallback, failed,
    #: cancelled and deadline-exceeded answers all keep the ``False`` default,
    #: because none of them was truncated BY A MODEL.
    #:
    #: This crosses the API boundary so the UI can mark the answer
    #: "(shortened)" instead of presenting a mid-sentence stop as the model's
    #: complete view. It is INERT until that surface exists (WP-F).
    shortened: bool = False


@dataclass(frozen=True)
class ProviderCallEvent:
    event_type: str
    account_id: UUID
    query_run_id: UUID
    model_id: str
    provider_path: ProviderPath
    duration_ms: int
    fallback_used: bool
    source_count: int
    credential_source: ProviderCredentialSource


class InMemoryProviderEventRecorder:
    """In-memory recorder for provider call events.

    Bounded for production safety: once the buffer exceeds ``MAX_EVENTS``
    the oldest half is dropped. The recorder is never the source of truth
    for any business decision; it exists only for observability.
    """

    MAX_EVENTS = 1024

    def __init__(self) -> None:
        self._events: list[ProviderCallEvent] = []
        self._lock = RLock()

    def record(
        self,
        *,
        event_type: str,
        account_id: UUID,
        query_run_id: UUID,
        model_id: str,
        provider_path: ProviderPath,
        duration_ms: int,
        fallback_used: bool,
        source_count: int,
        credential_source: ProviderCredentialSource,
    ) -> None:
        event = ProviderCallEvent(
            event_type=event_type,
            account_id=account_id,
            query_run_id=query_run_id,
            model_id=model_id,
            provider_path=provider_path,
            duration_ms=duration_ms,
            fallback_used=fallback_used,
            source_count=source_count,
            credential_source=credential_source,
        )
        with self._lock:
            self._events.append(event)
            if len(self._events) > self.MAX_EVENTS:
                del self._events[: len(self._events) - self.MAX_EVENTS]
        _record_feedback_event(
            recorder="provider",
            event_type=event.event_type,
            account_id=event.account_id,
            query_run_id=event.query_run_id,
            payload=asdict(event),
        )

    def list_events(self) -> list[ProviderCallEvent]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


class ProviderExecutionService:
    """Executes (or simulates) a single model call.

    The service is stateless across calls; all collaborators are passed in
    explicitly. The service deliberately keeps the surface small so it can
    be reused by tests, the e2e pipeline, and any future background runner.
    """

    # Developer-only hooks used by integration tests to force specific paths.
    # The hooks match against the user query text and the model id; the only
    # way to flip them is to literally type the magic phrase in the query.
    _FORCE_PROVIDER_FAILURE_PHRASE = "force provider failure"
    _FORCE_FALLBACK_PHRASE = "force fallback search"
    _PROVIDER_FAILURE_MODEL_MARKER = "provider-failure"
    _FALLBACK_MODEL_MARKER = "fallback"

    def produce_initial_answers(
        self,
        *,
        account_id: UUID,
        query_run_id: UUID,
        query_text: str,
        model_slots: list[ModelSlot],
        credential_source: ProviderCredentialSource = ProviderCredentialSource.APP_OWNED,
        openrouter_key: str = "",
    ) -> list[InitialModelAnswer]:
        return [
            self.produce_initial_answer(
                account_id=account_id,
                query_run_id=query_run_id,
                query_text=query_text,
                model_slot=model_slot,
                credential_source=credential_source,
                openrouter_key=openrouter_key,
            )
            for model_slot in model_slots
        ]

    def produce_initial_answer(
        self,
        *,
        account_id: UUID,
        query_run_id: UUID,
        query_text: str,
        model_slot: ModelSlot,
        credential_source: ProviderCredentialSource,
        openrouter_key: str,
    ) -> InitialModelAnswer:
        started_at = perf_counter()
        provider_attempt_order: list[ProviderPath] = [ProviderPath.LOCAL_SIMULATION]

        if self._should_force_provider_failure(query_text=query_text, model_slot=model_slot):
            return self._failed_answer(
                account_id=account_id,
                query_run_id=query_run_id,
                model_slot=model_slot,
                credential_source=credential_source,
                started_at=started_at,
            )

        # Default path: local simulation. We always return a deterministic,
        # well-shaped stub answer. Live  is only attempted when the
        # operator has explicitly opted in AND supplied a key.
        live_response: LiveProviderResult | None = None
        if self._live_execution_enabled(openrouter_key=openrouter_key):
            live_response = self._live_openrouter_response(
                openrouter_key=openrouter_key,
                query_text=query_text,
                model_slot=model_slot,
            )
            if live_response is not None:
                provider_attempt_order = [ProviderPath.OPENROUTER_SEARCH]

        # A live response with any answer text counts as a successful
        # primary-provider call. The plan relaxed the prior ``sources``
        # gate (line 235 in the original code) so that a model answering
        # from training data still produces an ``OPENROUTER_SEARCH``
        # result — its citations may simply be missing because :online
        # was rejected, but the answer itself is real.
        if live_response is not None and live_response.answer_text:
            sources = live_response.sources or []
            # #31: the ``:online`` variant frequently returns an answer with
            # NO citation annotations (~0-3% coverage in the live run). When
            # search was enabled for this slot but the model returned no
            # sources, run a REAL web search (Tavily) on the query and attach
            # its results — so the user gets real, clickable evidence rather
            # than an empty source list. Gated on ``TAVILY_API_KEY`` (absent →
            # no-op), so hermetic CI behaviour is unchanged. These sources are
            # ``is_fallback=True`` and therefore do NOT inflate the model's own
            # citation-coverage metric; the answer text is still the model's,
            # so ``provider_path`` stays ``OPENROUTER_SEARCH`` and
            # ``fallback_used`` stays ``False``.
            supplemented_sources: list[SourceReference] = []
            if model_slot.search and not sources and self._tavily_enabled():
                supplemented_sources = self._tavily_search(query_text=query_text)
                if supplemented_sources:
                    sources = supplemented_sources
            # L2: the ``provider_notice`` branches in priority order.
            # 1) If the caller opted this slot out of web search, the
            #    search-disabled fact is the most important for the user
            #    to know — even if the bare-id POST returned citations.
            # 2) Otherwise, if a real web-search fallback supplied the
            #    sources, say so plainly (they are not the model's own
            #    :online citations).
            # 3) Otherwise, the existing "missing citations, :online was
            #    unavailable" notice fires when sources are still empty.
            # 4) Otherwise, no notice (clean search hit with sources).
            if not model_slot.search:
                search_disabled_notice = NOTICE_SEARCH_DISABLED
            elif supplemented_sources:
                search_disabled_notice = NOTICE_SOURCES_FROM_BACKUP_SEARCH
            elif not sources:
                search_disabled_notice = NOTICE_NO_SOURCES_FOUND
            else:
                search_disabled_notice = None
            return self._completed_answer(
                account_id=account_id,
                query_run_id=query_run_id,
                model_slot=model_slot,
                credential_source=credential_source,
                started_at=started_at,
                answer_text=live_response.answer_text,
                sources=sources,
                provider_path=ProviderPath.OPENROUTER_SEARCH,
                provider_attempt_order=provider_attempt_order,
                fallback_used=False,
                provider_notice=search_disabled_notice,
                token_usage=live_response.usage,
                shortened=live_response.is_truncated,
            )

        # #171: live execution is ON and this slot produced no usable live
        # text. REPORT THE SLOT MISSING; never substitute locally simulated
        # text for it. A fabricated answer stamped ``completed`` is handed to
        # the debate, the synthesis, the agreement count and the
        # source-coverage figure as though a model had produced it — and its
        # ``is_fallback=False`` demo source is what makes it count as PRIMARY,
        # so a run with one real answer and three simulated ones reported 100%
        # source coverage, three quarters of it invented. Simulation is a
        # WHOLE-RUN mode (live execution off, or no key), never a per-model
        # substitute; this is the branch that made it per-model.
        #
        # Placed above the ``use_fallback`` branch on purpose: that branch also
        # emits ``_local_simulation_text`` when there is no live text, so
        # guarding only the tail would leave the same fabrication reachable
        # through it.
        if self._live_execution_enabled(openrouter_key=openrouter_key):
            return self._failed_answer(
                account_id=account_id,
                query_run_id=query_run_id,
                model_slot=model_slot,
                credential_source=credential_source,
                started_at=started_at,
            )

        # No live response, or live response returned no usable text.
        # Decide between a clean local-simulation answer and a
        # fallback_search answer. The trigger phrases let the test suite
        # force either path; the prior ``or live_response is not None``
        # clause was a bug — it misclassified every successful live call
        # as fallback_search, which cascaded into the wrong demo-banner
        # state and the wrong provider_path on the response.
        use_fallback = self._should_force_fallback(query_text=query_text, model_slot=model_slot)
        if use_fallback:
            provider_attempt_order = [ProviderPath.LOCAL_SIMULATION, ProviderPath.FALLBACK_SEARCH]
            # NOTE: the ``live_response.answer_text`` arm here is unreachable —
            # the ``openrouter_search`` branch above returns whenever there IS
            # usable live text, so control only arrives here when there is
            # none. Kept as-is (pre-existing) rather than "simplified" inside
            # WP-D, but it is why this branch needs no ``shortened=``: the text
            # it emits is always locally simulated, and simulated text was
            # never truncated by a model. Pinned by
            # ``TestTruncationPropagation::test_demo_mode_still_simulates_the_
            # slot_and_never_marks_it_shortened`` (renamed in #171; this comment
            # cited the old name, which no longer exists).
            #
            # #171: with live execution ON this whole branch is unreachable —
            # the guard above returns a missing slot first. It is now the DEMO
            # path only, which is why the pin above drives it with live
            # execution off.
            answer_text = (
                live_response.answer_text
                if live_response is not None and live_response.answer_text
                else self._local_simulation_text(model_slot=model_slot)
            )
            return self._completed_answer(
                account_id=account_id,
                query_run_id=query_run_id,
                model_slot=model_slot,
                credential_source=credential_source,
                started_at=started_at,
                answer_text=answer_text,
                sources=self._fallback_sources(model_slot=model_slot, query_text=query_text),
                provider_path=ProviderPath.FALLBACK_SEARCH,
                provider_attempt_order=provider_attempt_order,
                fallback_used=True,
                provider_notice=NOTICE_FALLBACK_SOURCE_SUPPORT,
            )

        return self._completed_answer(
            account_id=account_id,
            query_run_id=query_run_id,
            model_slot=model_slot,
            credential_source=credential_source,
            started_at=started_at,
            answer_text=self._local_simulation_text(model_slot=model_slot),
            sources=self._local_simulation_sources(model_slot=model_slot),
            provider_path=ProviderPath.LOCAL_SIMULATION,
            provider_attempt_order=provider_attempt_order,
            fallback_used=False,
            # #171: this branch is now reached ONLY with live execution off or
            # no key — the guard above returns a missing slot in every live
            # case — so there is exactly one honest thing left to say, and the
            # old "live was attempted but returned nothing" arm is dead. The
            # situation it described is now a FAILED slot carrying
            # ``NOTICE_PROVIDER_UNAVAILABLE``.
            provider_notice=NOTICE_DEMO_MODE,
        )

    # -- internal helpers -------------------------------------------------

    def _live_execution_enabled(self, *, openrouter_key: str) -> bool:
        return bool(settings.openrouter_live_execution_enabled and openrouter_key)

    def _completed_answer(
        self,
        *,
        account_id: UUID,
        query_run_id: UUID,
        model_slot: ModelSlot,
        credential_source: ProviderCredentialSource,
        started_at: float,
        answer_text: str,
        sources: list[SourceReference],
        provider_path: ProviderPath,
        provider_attempt_order: list[ProviderPath],
        fallback_used: bool,
        provider_notice: str | None = None,
        token_usage: TokenUsage | None = None,
        shortened: bool = False,
    ) -> InitialModelAnswer:
        duration_ms = max(1, round((perf_counter() - started_at) * 1000))
        provider_event_recorder.record(
            event_type="provider_initial_answer_completed",
            account_id=account_id,
            query_run_id=query_run_id,
            model_id=model_slot.model_id,
            provider_path=provider_path,
            duration_ms=duration_ms,
            fallback_used=fallback_used,
            source_count=len(sources),
            credential_source=credential_source,
        )
        # Citation coverage counts only citations that come from a primary
        # provider. Fallback citations are real sources, but they are not
        # the model's own research, so we exclude them from the coverage
        # metric to avoid inflating the score.
        #
        # WP-C / F-03: one completed answer is exactly ONE unit of coverage,
        # and it either carries a primary source or it does not. The previous
        # denominator was ``estimate_material_claim_count(answer_text)`` — a
        # characters-based figure — against this same boolean numerator, so a
        # long, fully-sourced answer scored a low ratio purely for being long.
        primary_source_count = sum(1 for source in sources if not source.is_fallback)
        answer_count = 1
        sourced_answer_count = 1 if primary_source_count > 0 else 0
        return InitialModelAnswer(
            slot_number=model_slot.slot_number,
            model_id=model_slot.model_id,
            display_name=_resolve_display_name(model_slot.model_id),
            answer_text=answer_text,
            sources=sources,
            provider_attempt_order=provider_attempt_order,
            provider_path=provider_path,
            fallback_used=fallback_used,
            status=InitialAnswerStatus.COMPLETED,
            latency_ms=duration_ms,
            citation_coverage=calculate_citation_coverage(
                answer_count=answer_count,
                sourced_answer_count=sourced_answer_count,
            ),
            provider_notice=provider_notice,
            token_usage=token_usage,
            shortened=shortened,
        )

    def _failed_answer(
        self,
        *,
        account_id: UUID,
        query_run_id: UUID,
        model_slot: ModelSlot,
        credential_source: ProviderCredentialSource,
        started_at: float,
    ) -> InitialModelAnswer:
        """Report the slot MISSING. It carries no ``token_usage`` — deliberately.

        #175, the money decision, stated where the code makes it. A slot can
        reach here after a call that really was billed: a whitespace-only (or
        empty) completion arrives with the provider's own ``usage`` object, and
        dropping it means those dollars stop being itemised.

        The alternative — a missing slot that still carries its usage — was
        measured and rejected, for four reasons:

        * It would change no receipt. ``initial_fully_captured``
          (``query_runs.py``) requires ``status is COMPLETED``, so the summing
          loop behind that gate is unreachable while any slot is FAILED.
          Measured: a FAILED slot carrying usage still yields ``estimated``.
          The value would be recorded, serialised into the API response, and
          read by nothing.
        * The spend is not silently lost. It is loudly marked UNMEASURABLE —
          the receipt drops to ``estimated``, which is exactly the F-06
          contract (see ``_DISPATCH_UNMEASURED``): a billed call must never
          VANISH, but it does not have to be SUMMED. The run stops claiming a
          measured figure it cannot support.
        * It is what this path already does for the identical class of call.
          An empty completion has arrived here carrying usage since F-06 and
          has always been reported with none.
        * On the debate/synthesis path usage lives in a SEPARATE list from the
          output, so recording it cannot imply the output was good. Here it
          lives ON the answer, so carrying it would make one field's honesty
          depend on another's.

        What would change this decision: a consumer that reads per-answer
        ``token_usage`` independently of ``initial_fully_captured`` — a
        per-slot spend breakdown, or a counter of billed-but-unusable calls.
        There is none today (#177 would add the nearest thing).
        """
        duration_ms = max(1, round((perf_counter() - started_at) * 1000))
        provider_event_recorder.record(
            event_type="provider_initial_answer_failed",
            account_id=account_id,
            query_run_id=query_run_id,
            model_id=model_slot.model_id,
            provider_path=ProviderPath.OPENROUTER_SEARCH,
            duration_ms=duration_ms,
            fallback_used=False,
            source_count=0,
            credential_source=credential_source,
        )
        return InitialModelAnswer(
            slot_number=model_slot.slot_number,
            model_id=model_slot.model_id,
            display_name=_resolve_display_name(model_slot.model_id),
            answer_text="",
            sources=[],
            provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
            provider_path=ProviderPath.OPENROUTER_SEARCH,
            fallback_used=False,
            status=InitialAnswerStatus.FAILED,
            latency_ms=duration_ms,
            # WP-C / F-03: a FAILED answer produced no text to source, so it
            # is out of the coverage denominator entirely — the same treatment
            # the cancelled and deadline-exceeded paths below already had. A
            # missing slot is penalised by the ``completeness`` signal; charging
            # it against coverage too would re-create a floor the metric cannot
            # reach. (It previously passed ``estimate_material_claim_count("")``
            # == 1, so a failed answer silently diluted the run's ratio.)
            citation_coverage=calculate_citation_coverage(
                answer_count=0,
                sourced_answer_count=0,
            ),
            error_code="PROVIDER_UNAVAILABLE",
            provider_notice=NOTICE_PROVIDER_UNAVAILABLE,
        )

    def cancelled_answer(self, model_slot: ModelSlot) -> InitialModelAnswer:
        """Build a stub ``InitialModelAnswer`` for a slot cancelled before
        the model call started.

        Mirrors the shape of ``_failed_answer`` (same field set, same
        empty ``sources``, same ``OPENROUTER_SEARCH`` provider path) so
        downstream debate/synthesis code can consume a cancelled answer
        identically to a provider-failed one. The differences are:

        * ``error_code="CANCELLED"`` lets the audit / drift layer
          distinguish "user clicked cancel" from "provider returned 5xx".
        * ``latency_ms=0`` — no work was attempted, so no time elapsed.
        * ``provider_notice`` is a short cancellation string rather than
          the provider-failure boilerplate.

        Kept as a thin helper so the call site in ``query_runs.py`` does
        not have to hand-roll an ``InitialModelAnswer`` constructor —
        field drift between the two failure constructors is a known
        footgun (each new ``InitialModelAnswer`` field would otherwise
        have to be added in two places).
        """
        return InitialModelAnswer(
            slot_number=model_slot.slot_number,
            model_id=model_slot.model_id,
            display_name=_resolve_display_name(model_slot.model_id),
            answer_text="",
            sources=[],
            provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
            provider_path=ProviderPath.OPENROUTER_SEARCH,
            fallback_used=False,
            status=InitialAnswerStatus.FAILED,
            latency_ms=0,
            citation_coverage=calculate_citation_coverage(
                answer_count=0,
                sourced_answer_count=0,
            ),
            error_code="CANCELLED",
            provider_notice=NOTICE_CANCELLED,
        )

    def deadline_exceeded_answer(self, model_slot: ModelSlot) -> InitialModelAnswer:
        """Build a stub ``InitialModelAnswer`` for a slot cut by the run-level
        wall-clock deadline (NFR-004 / P3).

        Sibling of :meth:`cancelled_answer` — same field set, same FAILED
        status, same rationale for existing as a thin helper (field drift
        between failure constructors is a known footgun). The differences:

        * ``error_code="RUN_DEADLINE_EXCEEDED"`` — the run's budget expired,
          which is neither a user cancel nor a provider failure; the audit /
          drift layer and the served payload must not misattribute it.
        * ``provider_notice`` names the deadline so the UI's failure notice
          is honest about WHY the slot has no answer.

        FAILED status keeps the RB-5 rule automatic: a cut slot is never a
        live answer, so it can never inflate the served ``live_count``.
        """
        return InitialModelAnswer(
            slot_number=model_slot.slot_number,
            model_id=model_slot.model_id,
            display_name=_resolve_display_name(model_slot.model_id),
            answer_text="",
            sources=[],
            provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
            provider_path=ProviderPath.OPENROUTER_SEARCH,
            fallback_used=False,
            status=InitialAnswerStatus.FAILED,
            latency_ms=0,
            citation_coverage=calculate_citation_coverage(
                answer_count=0,
                sourced_answer_count=0,
            ),
            error_code="RUN_DEADLINE_EXCEEDED",
            provider_notice=NOTICE_RUN_DEADLINE,
        )

    def _live_openrouter_response(
        self,
        *,
        openrouter_key: str,
        query_text: str,
        model_slot: ModelSlot,
    ) -> LiveProviderResult | None:
        """Call ``/chat/completions`` with web search enabled.

        Search contract: the model id we send is
        ``f"{model_slot.model_id}:online"`` — the ``:online`` suffix is
        the supported way to opt into  web search. ``:online``
        returns ``annotations`` with source URLs on the message
        object; those are extracted by ``_extract_citations``.

        If  rejects the ``:online`` variant (404 / 400) for a
        given model, we retry once with the bare model id. The retry
        path accepts that ``citations`` may be missing — the
        L1-relaxed gate in ``produce_initial_answer`` already handles
        that case (an answer with no citations is still a valid
        ``OPENROUTER_SEARCH`` result; the user sees a
        ``provider_notice`` explaining the missing citations). If both
        attempts fail, ``None`` is returned and the caller falls back
        to local simulation.

        The retry is one-shot only; we do not loop across many model
        variants. That keeps the per-call latency bounded and makes the
        failure mode predictable.
        """
        result = self._call_openrouter_with_optional_search(
            openrouter_key=openrouter_key,
            query_text=query_text,
            model_slot=model_slot,
        )
        if result is None or isinstance(result, _SearchRejected | _DispatchedUnmeasured):
            return None
        # F-06: ``_post_openrouter`` returns a real result for an EMPTY
        # completion so the debate/synthesis path can record the usage the
        # provider charged for. The initial-answer path must NOT treat that as
        # an answer: a non-``None`` result flips ``provider_attempt_order`` to
        # OPENROUTER_SEARCH in ``produce_initial_answer``, so an empty slot
        # would report a live attempt it never usefully made.
        # ``provider_attempt_order`` is a user-visible response field
        # (openapi.yaml).
        #
        # #175: this guard is ``.strip()``. It did NOT used to be, and the
        # difference was a defect, not a decision. A completion of ``"   \n\t "``
        # is truthy, so a whitespace-only answer was served as a COMPLETED live
        # slot: it counted toward ``live_count``, sat in the citation-coverage
        # DENOMINATOR, and — carrying its own ``token_usage`` — satisfied
        # ``initial_fully_captured``, so a run in which no model produced a
        # single character reported "4 of 4 answered live", status
        # ``completed``, no failed steps and a ``measured`` (billed) receipt.
        # With one slot returning a citation annotation and no prose it
        # reported 100% source coverage over an answer with no text.
        #
        # This inverted NOTHING about F-06 and invented no threshold. Emptiness
        # after ``.strip()`` is the predicate the rest of the product already
        # uses on model-produced text — ``evaluation._substantive``,
        # ``synthesis_consensus``, ``query_runs`` (twice: directly, when
        # choosing which answers count toward the material-claim total, and
        # again inside ``estimate_material_claim_count``), and every debate and
        # synthesis site that tests a live provider response. The initial-answer
        # path was the only dissenter, which is why the SAME payload could serve
        # ``agreement 3 of 4`` next to ``live_count 4``.
        #
        # That parenthesis is deliberate. Review reported this attribution as
        # "true but indirect — the strip is not in ``query_runs``". REFUTED on
        # inspection: there are two, and one is a direct ``.strip()`` filter in
        # ``_result_response``. A reviewer claim gets checked before it is acted
        # on; this one did not survive the check, and the wording it would have
        # produced was vaguer than the truth.
        #
        # No count is quoted above, on purpose. An earlier draft of this comment
        # said "all ten ... sites"; review could not re-derive ten under any
        # reading — eight ``live.answer_text.strip()`` calls, eleven counting
        # the excerpt and synopsis helpers, thirteen counting every ``.strip()``
        # in the two files. A count in prose is a claim, it goes stale silently,
        # and that one was simply wrong. The sentence names the SET so a reader
        # greps for it instead of trusting a number.
        #
        # KNOWN RESIDUAL (#178): ``str.strip()`` removes only characters where
        # ``str.isspace()`` is true. A completion of zero-width or invisible
        # characters (U+200B, U+FEFF, U+00AD, U+2800 ...) is still served as an
        # answer, with the same wrong numbers described above. Filed rather than
        # fixed here: closing it means deciding which Unicode categories count
        # as invisible, and applying that one predicate at every site named
        # above so they do not start disagreeing again.
        #
        # The correction to the note this replaced, which is the reason the
        # defect looked safe: it quoted ``initial_fully_captured`` as requiring
        # ``provider_path is OPENROUTER_SEARCH`` and ``token_usage is not
        # None``. The gate (``query_runs.py``) has a THIRD conjunct — ``status
        # is COMPLETED`` — and that omission is load-bearing. It is what makes
        # a whitespace slot's usage reach a measured receipt while a failed
        # slot's cannot, and it is why the fix costs the run its ``measured``
        # label: see ``_failed_answer`` for the money decision (#175).
        if not result.answer_text.strip():
            return None
        return result

    def _call_openrouter_with_optional_search(
        self,
        *,
        openrouter_key: str,
        query_text: str,
        model_slot: ModelSlot,
    ) -> LiveProviderResult | _SearchRejected | _DispatchedUnmeasured | None:
        bare_model_id = model_slot.model_id

        # L2: per-slot search opt-out. When ``model_slot.search`` is
        # False, we skip the ``:online`` attempt entirely — one bare-id
        # POST, no retry on failure. The result still records as
        # ``OPENROUTER_SEARCH`` (see ``produce_initial_answer``), with
        # a ``provider_notice`` that tells the user web search was
        # disabled. This is the "cheaper, faster, training-data only"
        # path some users will pick for cost control.
        # Cap initial-answer output (like debate/synthesis already are). Without
        # this, initial-answer output is unbounded, so a verbose prompt on an
        # expensive model mix can bill far above any pre-run estimate and slip
        # the cost guardrail. The cap is generous (see
        # ``settings.initial_answer_max_tokens``) so real answers are not
        # truncated in practice.
        max_tokens = settings.initial_answer_max_tokens
        if not model_slot.search:
            return self._post_openrouter(
                openrouter_key=openrouter_key,
                query_text=query_text,
                model_id=bare_model_id,
                max_tokens=max_tokens,
            )

        online_model_id = f"{bare_model_id}:online"

        # First attempt: with ``:online`` for web search.
        online_result = self._post_openrouter(
            openrouter_key=openrouter_key,
            query_text=query_text,
            model_id=online_model_id,
            max_tokens=max_tokens,
        )
        if online_result is _SEARCH_REJECTED:
            #  re-try without the ``:online`` suffix.
            return self._post_openrouter(
                openrouter_key=openrouter_key,
                query_text=query_text,
                model_id=bare_model_id,
                max_tokens=max_tokens,
            )
        return online_result

    def _post_openrouter(
        self,
        *,
        openrouter_key: str,
        query_text: str,
        model_id: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> LiveProviderResult | _SearchRejected | _DispatchedUnmeasured | None:
        # ``_post_openrouter`` accepts a custom system prompt and
        # ``max_tokens`` cap. The debate and synthesis services pass their
        # own caps; the initial-answer search path now passes
        # ``settings.initial_answer_max_tokens`` too (previously uncapped).
        # The default here stays ``None`` for any other caller.
        # L4: when context is provided (a follow-up query), inject the
        # prior question into the system prompt so the model is aware
        # of the conversation history without re-quoting the user query.
        # WP-D (F-08): ``prior_question`` is CLIENT-SUPPLIED and lands in the
        # SYSTEM message, so it is the one untrusted channel the user-message
        # fence cannot cover. Two rules therefore apply to it:
        #
        #   1. It goes AFTER the caller's system prompt, never before. Prepended,
        #      an attacker-authored follow-up was literally the first instruction
        #      the model read — above the untrusted-data rule — and could
        #      countermand the entire fencing scheme.
        #   2. Its delimiters are neutralized, so it cannot forge a decoy
        #      evidence block inside the trusted half of the prompt.
        #
        # It is still labelled so the model knows it is quoted user input rather
        # than an instruction from us.
        base_system_prompt = system_prompt or (
            "Answer the user query with explicit source-backed reasoning. "
            "Include citations or source URLs where possible, and explain "
            "uncertainty instead of fabricating support."
        )
        context_suffix = ""
        if context and context.get("prior_question"):
            # FENCED, not merely neutralized and repositioned. Position alone
            # cannot solve this: before the untrusted-data rule the client text
            # reads as a governing instruction, and after it, it is the last
            # thing the model sees and can pose as an amendment to the rule
            # ("the paragraph above no longer applies"). Wrapping it in the
            # same delimiters the rule already governs makes it unambiguously
            # DATA wherever it sits — the same treatment the answers get in the
            # user message.
            context_suffix = "\n\nThe user's previous question, as data:\n" + fence(
                str(context["prior_question"])
            )
        system_message = base_system_prompt + context_suffix
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": query_text},
        ]
        return self._post_messages(
            openrouter_key=openrouter_key,
            model_id=model_id,
            messages=messages,
            max_tokens=max_tokens,
        )

    def _post_messages(
        self,
        *,
        openrouter_key: str,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> LiveProviderResult | _SearchRejected | _DispatchedUnmeasured | None:
        payload: dict[str, object] = {
            "model": model_id,
            "messages": messages,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        request = Request(
            url=f"{settings.openrouter_api_base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {openrouter_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": settings.openrouter_app_url,
                "X-Title": settings.openrouter_app_title,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=settings.openrouter_timeout_seconds) as response:
                raw_body = response.read().decode()
        except HTTPError as exc:
            # 404 / 400 on the ``:online`` variant is the documented
            # signal that this model does not support the search
            # suffix; the caller retries with the bare model id.
            # Log non-benign errors at WARNING so a revoked key or
            # rate limit is visible to operators (detection gap if
            # we silently return).
            if exc.code in (400, 404) and model_id.endswith(":online"):
                return _SEARCH_REJECTED
            _LOGGER.warning(
                "upstream_provider_http_error",
                extra={
                    "status_code": exc.code,
                    "url": exc.url,
                    "model_id": model_id,
                },
            )
            # F-06 billing classification. A rejected REQUEST (bad JSON body,
            # bad/insufficient credentials, unknown model, rate limit) is
            # refused before any token is generated, so nothing was billed and
            # the caller must be free to keep the run ``measured``. Any other
            # status — 5xx above all — can follow a generation that already
            # consumed tokens, so it is reported as dispatched-but-unmeasured.
            if exc.code in _UNBILLED_HTTP_STATUSES:
                return None
            return _DISPATCH_UNMEASURED
        except URLError as exc:
            # ``URLError`` is CPython's own signal that the OPENER failed, i.e.
            # before the request reached the model: DNS failure, connection
            # refused, TLS handshake failure. Nothing was billed.
            #
            # A CONNECT timeout arrives here as ``URLError(reason=TimeoutError())``
            # and demonstrably never reached the model, so on the evidence it is
            # unbilled. It is nevertheless classified as possibly-billed: the
            # opener does not tell us which phase timed out, and misreading a
            # post-generation timeout as unbilled would understate a CHARGE.
            # Erring the other way only overstates a receipt's uncertainty.
            # (The timeout that genuinely cannot be told apart from a slow
            # generation is the one out of ``getresponse()``, which arrives as a
            # BARE ``TimeoutError`` and is handled by the catch-all below.)
            if isinstance(exc.reason, TimeoutError):
                return _DISPATCH_UNMEASURED
            return None
        except Exception as exc:
            # F-06 (finding A): the catch-all is the point. A torn body
            # (``http.client.IncompleteRead``), a dropped keep-alive
            # (``RemoteDisconnected``), a TLS record error (``ssl.SSLError``) or
            # a non-UTF-8 body (``UnicodeDecodeError``) are none of the classes
            # above, so before this clause they escaped the whole provider stack
            # — and ``_safe_section_result`` swallowed them into ``live=None``,
            # leaving a BILLED call with no usage entry at all. The invariant
            # this establishes: once ``urlopen`` has been called, this method
            # RETURNS; it never raises.
            #
            # The classification is deliberately ASYMMETRIC. A handful of
            # PRE-dispatch failures are not ``URLError`` and land here too — a
            # non-latin-1 header value raises ``UnicodeEncodeError`` out of
            # ``http.client.putheader`` before a byte leaves the process — and
            # they are reported as possibly-billed. That errs toward
            # ``estimated``, which overstates a receipt's uncertainty; the
            # opposite error understates a CHARGE, which is the dishonesty this
            # whole change exists to prevent. When in doubt, assume billed.
            #
            # NOTE for test authors: an ``AssertionError`` raised inside a
            # ``urlopen`` double is an ``Exception`` and is swallowed here. To
            # assert that no request is dispatched, count calls and assert the
            # count — do not rely on an assertion inside the double.
            _log_post_dispatch_failure(
                "upstream_provider_transport_error",
                exc=exc,
                model_id=model_id,
                expected=_EXPECTED_TRANSPORT_ERRORS,
            )
            return _DISPATCH_UNMEASURED

        try:
            parsed = json.loads(raw_body)
            content = _extract_message_content(parsed)
            # Pass ``content`` in so ``_extract_citations`` reuses the already
            # extracted message text for its inline-link fallback instead of
            # walking the choices/message tree a second time.
            citations = _extract_citations(parsed, content=content)
            # Capture the provider-reported token usage (``None`` if the response
            # omitted it). Threaded up so the run's actual cost can be measured
            # rather than estimated when every contributing call reported usage.
            #
            # F-06 (finding C): this used to sit BELOW an ``if not content:
            # return None`` guard, so an HTTP 200 whose completion was empty
            # (``finish_reason="length"`` against a tight token cap) threw away
            # the provider's own statement of what it had just charged. The
            # usage is now extracted first and an empty completion is returned
            # as a real result carrying it; deciding what an empty answer MEANS
            # belongs to the caller, not here.
            usage = _extract_usage(parsed)
            # WP-D (F-07): did the provider stop because it hit the token
            # ceiling? Extracted INSIDE this try alongside ``usage``, not after
            # it — the two are read from the same payload, and if reading this
            # one somehow raises, the call still billed and must be classified
            # ``_DISPATCH_UNMEASURED`` like any other post-dispatch failure.
            #
            # It pairs especially closely with F-06's finding C above: an HTTP
            # 200 whose completion is EMPTY because ``finish_reason="length"``
            # hit a tight cap is exactly the case that used to be thrown away.
            # It now returns as a real result carrying both the usage that was
            # billed and the reason the text is missing.
            is_truncated = _finish_reason_indicates_truncation(parsed)
        except Exception as exc:
            # A body arrived, so the call billed. This clause spans json.loads
            # AND the three extractors, so it covers two different situations:
            # an unreadable body, and OUR OWN code failing on a perfectly good,
            # priceable response (a RecursionError out of ``json.loads`` on a
            # pathologically nested body; a bug in ``_extract_usage``). The
            # second silently degrades a measurable run to ``estimated``, which
            # is the safe direction but is a real cost of the breadth — so the
            # log event is the signal to watch. The breadth is deliberate: on
            # the DEBATE path there is no ``_safe_section_result`` to swallow an
            # escaping exception, so anything raised here would otherwise take
            # the billed call's usage down with it.
            _log_post_dispatch_failure(
                "upstream_provider_body_unreadable",
                exc=exc,
                model_id=model_id,
                expected=_EXPECTED_BODY_ERRORS,
            )
            return _DISPATCH_UNMEASURED
        return LiveProviderResult(
            answer_text=content,
            sources=citations,
            usage=usage,
            is_truncated=is_truncated,
        )

    def call_with_prompt(
        self,
        *,
        openrouter_key: str,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> LiveProviderResult | None:
        """Public entry point for internal callers (debate, synthesis)
        that need to call a specific model with a custom system prompt
        and an optional token cap.

        Unlike the per-slot ``_live_openrouter_response``, this method
        does NOT attempt the ``:online`` suffix — the debate and
        synthesis stages are second-pass analysis over the model
        answers already gathered, and a fresh web search is not what
        we want at that point. It also does not retry on 404.

        F-06 — the return value carries BILLING provenance, and callers
        depend on the distinction:

        * ``None`` — no charge is possible. Either no request left this
          process, or the provider refused it before inference (see
          :data:`_UNBILLED_HTTP_STATUSES`, or a connection that never
          landed). The caller must record NO usage entry, so a run whose
          only failure was an unbilled 404 stays honestly ``measured``.
        * a result with BLANK ``answer_text`` — a request was dispatched and
          may have been billed. ``usage`` is the provider's own statement of
          the charge when the response body reached us (an empty completion),
          and ``None`` when it did not (5xx, timeout, torn body). The caller
          must record an entry, so an unmeasurable charge forces
          ``estimated`` instead of vanishing from an ``all([])`` gate.
        * a result with text — the normal case.
        """
        if not openrouter_key or not model_id:
            return None
        result = self._post_openrouter(
            openrouter_key=openrouter_key,
            query_text=user_prompt,
            model_id=model_id,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            context=context,
        )
        if isinstance(result, _DispatchedUnmeasured):
            return LiveProviderResult(answer_text="", sources=[], usage=None)
        if result is None or isinstance(result, _SearchRejected):
            return None
        return result

    def _should_force_provider_failure(
        self,
        *,
        query_text: str,
        model_slot: ModelSlot,
    ) -> bool:
        # Magic phrases (``"force provider failure"`` etc.) are test-only
        # knobs. They are gated on ``runtime_environment == LOCAL`` so a
        # production or staging deployment cannot have its results
        # degraded by a user submitting a query that happens to contain
        # the phrase. The ``model_id`` marker path is not gated because
        # callers cannot influence ``model_id`` — it is operator-curated
        # via the slot picker.
        if settings.runtime_environment is not RuntimeEnvironment.LOCAL:
            return self._PROVIDER_FAILURE_MODEL_MARKER in model_slot.model_id
        lowered_query = query_text.lower()
        return (
            self._FORCE_PROVIDER_FAILURE_PHRASE in lowered_query
            or self._PROVIDER_FAILURE_MODEL_MARKER in model_slot.model_id
        )

    def _should_force_fallback(self, *, query_text: str, model_slot: ModelSlot) -> bool:
        # See ``_should_force_provider_failure`` for the rationale on
        # gating the user-query phrase to ``runtime_environment=LOCAL``.
        if settings.runtime_environment is not RuntimeEnvironment.LOCAL:
            return self._FALLBACK_MODEL_MARKER in model_slot.model_id
        lowered_query = query_text.lower()
        return (
            self._FORCE_FALLBACK_PHRASE in lowered_query
            or self._FALLBACK_MODEL_MARKER in model_slot.model_id
        )

    def _local_simulation_text(self, *, model_slot: ModelSlot) -> str:
        return (
            f"Cross-check summary for {model_slot.model_id}: compare the cited evidence, "
            "preserve disagreement, and verify important claims before acting. "
            "This answer is simulated in local demo mode; the model was not actually "
            "invoked."
        )

    def _local_simulation_sources(self, *, model_slot: ModelSlot) -> list[SourceReference]:
        return [
            SourceReference(
                title=f"Local demo evidence for slot {model_slot.slot_number}",
                url=f"{LOCAL_SIMULATION_URL_PREFIX}{model_slot.slot_number}",
                provider=ProviderPath.LOCAL_SIMULATION,
                is_fallback=False,
            ),
        ]

    def _fallback_sources(self, *, model_slot: ModelSlot, query_text: str) -> list[SourceReference]:
        """Sources for the fallback path.

        When ``TAVILY_API_KEY`` is configured we run a REAL web search
        (Tavily) on the user's query and return its results as
        ``is_fallback=True`` sources — replacing the fabricated
        ``example.test`` stub that used to ship here (issues #31 / #32).
        When the key is absent, or the search returns nothing / errors,
        we fall back to the deterministic local-simulation stub so the
        offline-safe default and the hermetic test suite are unchanged.
        """
        if self._tavily_enabled():
            real_sources = self._tavily_search(query_text=query_text)
            if real_sources:
                return real_sources
        return [
            SourceReference(
                title=f"Fallback search evidence for slot {model_slot.slot_number}",
                url=f"{LOCAL_SIMULATION_URL_PREFIX}fallback/{model_slot.slot_number}",
                provider=ProviderPath.FALLBACK_SEARCH,
                is_fallback=True,
            ),
        ]

    def _tavily_enabled(self) -> bool:
        """Whether a real Tavily web search should be attempted.

        Gated solely on the presence of ``TAVILY_API_KEY``. Absent → the
        fallback keeps the local-simulation stub, so CI stays hermetic and
        no live key is needed to merge.
        """
        return bool(settings.tavily_api_key)

    def _tavily_search(self, *, query_text: str) -> list[SourceReference]:
        """Run a real web search via the Tavily API.

        POSTs the user query to Tavily's ``/search`` endpoint and maps the
        returned ``results[]`` into ``FALLBACK_SEARCH`` / ``is_fallback=True``
        ``SourceReference``s. Every result URL is passed through
        :func:`_sanitize_source_url` (http(s) scheme + host denylist), so a
        malicious or malformed result cannot smuggle a ``javascript:`` or
        metadata-service URL into the response. Returns ``[]`` — never
        raises — on any transport error, non-JSON body, or empty result set,
        so the caller cleanly degrades to the local-simulation stub.

        The Tavily key is sent only in the ``Authorization`` header; it is
        never logged nor echoed into a source title.
        """
        query = (query_text or "").strip()
        if not query:
            return []
        payload = json.dumps(
            {
                "query": query,
                "max_results": settings.tavily_max_results,
            }
        ).encode()
        request = Request(
            url=f"{settings.tavily_api_base_url.rstrip('/')}/search",
            data=payload,
            headers={
                "Authorization": f"Bearer {settings.tavily_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=settings.tavily_timeout_seconds) as response:
                raw_body = response.read().decode()
            parsed = json.loads(raw_body)
        except HTTPError as exc:
            _LOGGER.warning(
                "tavily_search_http_error",
                extra={"status_code": exc.code},
            )
            return []
        except (URLError, TimeoutError, OSError, ValueError, RecursionError):
            # Degrade to the local stub — never raise — on ANY hostile /
            # transport failure: a socket error or truncated body
            # (``URLError`` / ``OSError`` incl. ``http.client.IncompleteRead``,
            # ``ConnectionResetError``), a non-UTF-8 body
            # (``UnicodeDecodeError`` ⊂ ``ValueError``), malformed JSON
            # (``json.JSONDecodeError`` ⊂ ``ValueError``), or pathologically
            # nested JSON (``RecursionError``). ``HTTPError`` ⊂ ``URLError`` ⊂
            # ``OSError`` is caught above first so its status code is logged.
            return []
        return _parse_tavily_results(parsed)


@dataclass(frozen=True)
class LiveProviderResult:
    answer_text: str
    sources: list[SourceReference]
    #: Real token usage reported by the provider for this call, or ``None``
    #: when the response omitted the ``usage`` object. Threaded up to the
    #: cost layer so a fully-captured run can report a measured actual cost.
    usage: TokenUsage | None = None
    #: WP-D (F-07): the provider told us it stopped because it hit the
    #: ``max_tokens`` ceiling (``finish_reason == "length"``), so this answer
    #: is the model's output CUT SHORT, not its complete one. Defaults to
    #: ``False`` — the honest reading of a response that carried no signal is
    #: "no evidence of truncation", never "definitely truncated".
    is_truncated: bool = False


#: Internal sentinel returned by ``_post_openrouter`` when ````
#: rejected the ``:online`` variant (HTTP 400 / 404). The caller
#: interprets this as "retry with the bare model id" — distinct from
#: ``None`` ("treat the call as a hard failure") and from a real
#: ``LiveProviderResult`` ("accept the response").
class _SearchRejected:
    """Sentinel class; the module exports a single instance below."""


_SEARCH_REJECTED: _SearchRejected = _SearchRejected()


#: Internal sentinel returned by ``_post_openrouter`` when a request WAS
#: dispatched — so the provider may already have generated (and billed for) a
#: completion — and we captured no usage for it. Distinct from ``None``, which
#: after F-06 means the strictly stronger "the request was refused before
#: inference, so nothing was billed". The distinction is what lets a run whose
#: only failure was an unbilled 404 stay ``measured`` while a run with a torn
#: body, a read timeout or a 5xx is correctly downgraded to ``estimated``.
class _DispatchedUnmeasured:
    """Sentinel class; the module exports a single instance below."""


_DISPATCH_UNMEASURED: _DispatchedUnmeasured = _DispatchedUnmeasured()


#: HTTP statuses OpenRouter returns by REJECTING the request outright: a
#: malformed body (400), a missing/invalid/revoked key (401), no credit (402),
#: a forbidden model or region (403), an unknown model id (404), and a rate
#: limit (429). Each is decided before any token is generated, so no charge is
#: possible. Every other status is treated as possibly-billed.
_UNBILLED_HTTP_STATUSES: frozenset[int] = frozenset({400, 401, 402, 403, 404, 429})


#: Post-dispatch failures a healthy deployment genuinely produces: a torn or
#: truncated body and a dropped keep-alive (``http.client.HTTPException``), a
#: TLS record error or reset socket (``OSError``, which ``ssl.SSLError``
#: subclasses), and a non-UTF-8 body (``UnicodeDecodeError``).
_EXPECTED_TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
    HTTPException,
    OSError,
    UnicodeDecodeError,
)

#: Post-dispatch failures that are genuinely the BODY's fault rather than ours:
#: malformed JSON (``JSONDecodeError`` ⊂ ``ValueError``) and pathologically
#: nested JSON (``RecursionError``).
_EXPECTED_BODY_ERRORS: tuple[type[BaseException], ...] = (ValueError, RecursionError)


def _log_post_dispatch_failure(
    event: str,
    *,
    exc: BaseException,
    model_id: str,
    expected: tuple[type[BaseException], ...],
) -> None:
    """Log a failure that reached us AFTER the request was dispatched.

    ``expected`` selects the LEVEL ONLY — every exception, recognised or not,
    is classified ``_DISPATCH_UNMEASURED`` by the caller regardless. Guessing a
    RETURN VALUE from an exception class is exactly what F-06 finding A was, so
    the classification stays a catch-all; but an unrecognised class is far more
    likely to be a bug in our own response handling than a real network event,
    and it now degrades a receipt to ``estimated``, so it is logged at ERROR
    rather than lost among transient WARNINGs.

    Only the exception's CLASS NAME is recorded — never ``str(exc)`` and never
    a traceback. An exception message here can carry key material verbatim: a
    non-latin-1 character in an ``Authorization`` header raises
    ``UnicodeEncodeError`` whose payload is the header value.
    """
    _LOGGER.log(
        logging.WARNING if isinstance(exc, expected) else logging.ERROR,
        event,
        extra={"error_type": type(exc).__name__, "model_id": model_id},
    )


def _finish_reason_indicates_truncation(payload: object) -> bool:
    """Did the provider stop because it hit the token ceiling?

    Reads ``choices[0].finish_reason`` and reports ``True`` only for the
    documented ``"length"`` value. Every other shape — a payload that is not
    a mapping, a missing/empty/non-list ``choices``, a non-mapping element,
    an absent ``finish_reason``, or any other reason (``"stop"``,
    ``"content_filter"``, a provider-specific string) — reports ``False``.

    The asymmetry is deliberate and is the whole point: ``shortened`` becomes
    a "(shortened)" marker on a user-visible answer, so a malformed or
    unfamiliar response must never be able to *assert* truncation. Absence of
    evidence is reported as absence, not as a defect we invented.
    """
    if not isinstance(payload, dict):
        return False
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    first = choices[0]
    if not isinstance(first, dict):
        return False
    return first.get("finish_reason") == "length"


def _extract_usage(payload: object) -> TokenUsage | None:
    """Parse the OpenRouter ``usage`` object into a :class:`TokenUsage`.

    Returns ``None`` — never a fabricated record — when the object is
    missing, is not a mapping, or lacks the three integer token counts. A
    non-integer, negative, or implausibly large value (see
    :data:`_MAX_PLAUSIBLE_TOKENS`) is treated as absent so the cost layer
    never measures from a malformed or hostile payload — the run stays
    ``estimated`` instead of crashing on a Decimal overflow downstream.
    ``total_tokens`` falls back to ``prompt + completion`` when the provider
    omits it but reports the parts.
    """
    if not isinstance(payload, dict):
        return None
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None

    def _count(key: str) -> int | None:
        value = usage.get(key)
        # Reject bools (``isinstance(True, int)`` is True), non-integers,
        # negatives, and implausibly large counts. The upper bound both
        # guards against a Decimal-precision overflow in the downstream cost
        # arithmetic and refuses to trust an absurd provider-supplied value —
        # either way the call is treated as unmeasurable, not fatal.
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            or value > _MAX_PLAUSIBLE_TOKENS
        ):
            return None
        return value

    prompt_tokens = _count("prompt_tokens")
    completion_tokens = _count("completion_tokens")
    if prompt_tokens is None or completion_tokens is None:
        return None
    total_tokens = _count("total_tokens")
    if total_tokens is None:
        total_tokens = prompt_tokens + completion_tokens
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


#: Upper bound on a citation title we store/echo to the client. A hostile or
#: MITM'd search response could carry a multi-megabyte ``title``; we truncate
#: rather than trust the provider's length (defense-in-depth against an
#: oversized-payload DoS on the result endpoint).
_MAX_SOURCE_TITLE_LEN = 300


def _parse_tavily_results(payload: object) -> list[SourceReference]:
    """Map a parsed Tavily ``/search`` response into fallback sources.

    Reads the top-level ``results`` array; each result contributes one
    ``FALLBACK_SEARCH`` / ``is_fallback=True`` ``SourceReference`` whose URL
    survives :func:`_sanitize_source_url`. Malformed entries (non-dict,
    missing/blocked URL) are skipped rather than fatal, and duplicate URLs
    are de-duplicated so the same host cited twice appears once. A missing
    or non-string title falls back to the URL's host so the UI always has a
    label; an over-long title is truncated to :data:`_MAX_SOURCE_TITLE_LEN`.
    Returns ``[]`` for any shape that is not a mapping with a list of results.

    Only the first ``settings.tavily_max_results`` entries are processed —
    ``max_results`` is a request *hint* Tavily is free to exceed (or a hostile
    proxy could inflate), so the cap is re-enforced here to bound both server
    memory and the client payload.
    """
    if not isinstance(payload, dict):
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    references: list[SourceReference] = []
    seen: set[str] = set()
    for result in results[: max(0, settings.tavily_max_results)]:
        if not isinstance(result, dict):
            continue
        sanitized = _sanitize_source_url(result.get("url") or "")
        if sanitized is None or sanitized in seen:
            continue
        seen.add(sanitized)
        title = result.get("title")
        if not isinstance(title, str) or not title.strip():
            title = urlparse(sanitized).hostname or sanitized
        references.append(
            SourceReference(
                title=title[:_MAX_SOURCE_TITLE_LEN],
                url=sanitized,
                provider=ProviderPath.FALLBACK_SEARCH,
                is_fallback=True,
            ),
        )
    return references


def _extract_message_content(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return ""
    message = first_choice.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        return "\n".join(part for part in parts if part)
    return ""


#: C7: hosts that must never appear in a citation URL. The list is
#: read at import time and is intentionally small — these are the
#: hosts that would either (a) reflect content back to the user in a
#: way that confuses the source-support display, or (b) point at
#: internal network resources that the demo deployment is not
#: supposed to expose via the public response.
_SOURCE_URL_HOST_DENYLIST: frozenset[str] = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "169.254.169.254",  # AWS / GCP metadata service
        "metadata.google.internal",
        "::1",
    }
)


def _sanitize_source_url(url: str) -> str | None:
    """Return ``url`` with its fragment stripped and a permissive
    host check applied. Returns ``None`` if the URL must be dropped.

    The fragment strip is for two reasons:

    1. ``#`` is the route hash on the SPA; if it leaks into a
       citation URL the browser will scroll the iframe/page to a
       non-existent anchor.
    2. Fragments can be used to smuggle javascript: into a
       previously-validated URL when the consumer does not expect
       them (e.g. a downstream tab opens the URL and the fragment
       is interpreted as a script).

    The host denylist is defense-in-depth: a crafted LLM response
    that includes a metadata-service URL would otherwise let a
    user click through to a privileged resource. Citations are
    always public web sources; anything pointing at loopback or
    metadata services is not a real citation.
    """
    if not isinstance(url, str) or not url:
        return None
    # Strip the ends FIRST, then judge what remains. Providers routinely emit a
    # trailing newline or surrounding spaces on an otherwise perfectly good
    # citation, and the inline-markdown path already strips before validating —
    # rejecting those outright would silently DROP real sources and depress
    # citation coverage, which is a product defect in a tool whose claim is
    # source-backed answers. Reject injection, not sloppiness.
    url = url.strip()
    if not url:
        return None
    # A URL is a single token. One carrying a line break — or any other
    # whitespace/control character — is not a URL, it is a payload: inlined
    # into a prompt it forges its own line, and every downstream consumer
    # (debate, synthesis, the evaluation judge) inlines sources this way.
    # ``urlparse`` strips these for its own host check and then hands the
    # ORIGINAL string back, so the host check passing says nothing about what
    # the rest of the string will do. Reject here, at the producer, rather
    # than flattening at each consumer — three consumers means the next one
    # forgets. Unicode line separators (U+2028/U+2029/U+0085) count too.
    if any(ch.isspace() or ord(ch) < 0x20 or ch in "  " for ch in url):
        return None
    if not url.startswith(("http://", "https://")):
        return None
    # Strip fragment — everything after the first '#'.
    fragment_idx = url.find("#")
    if fragment_idx != -1:
        url = url[:fragment_idx]
    # Host check on the netloc.
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = parsed.hostname or ""
    if host.lower() in _SOURCE_URL_HOST_DENYLIST:
        return None
    return url


def _extract_citations(
    payload: object,
    *,
    content: str | None = None,
) -> list[SourceReference]:
    """Pull SourceReferences from a parsed chat-completions response.

    ``content`` is the already-extracted message text. When supplied it is
    used for the inline-markdown-link fallback; otherwise
    ``_extract_message_content`` is called on ``payload``. Callers that
    already extracted the content for the answer text (i.e.
    ``_post_openrouter``) should pass it in to avoid walking the
    choices/message tree twice per live call.
    """
    if not isinstance(payload, dict):
        return []
    references: list[SourceReference] = []
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return references
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return references
    message = first_choice.get("message")
    if not isinstance(message, dict):
        return references
    annotations = message.get("annotations") or message.get("citations") or []
    if not isinstance(annotations, list):
        annotations = []
    for index, annotation in enumerate(annotations, start=1):
        if not isinstance(annotation, dict):
            continue
        raw_url = annotation.get("url") or annotation.get("source") or ""
        title = annotation.get("title") or f" citation {index}"
        sanitized = _sanitize_source_url(raw_url)
        if sanitized is None:
            continue
        if not isinstance(title, str):
            title = f" citation {index}"
        references.append(
            SourceReference(
                title=title,
                url=sanitized,
                provider=ProviderPath.OPENROUTER_SEARCH,
                is_fallback=False,
            ),
        )
    # Workstream-2: parse inline markdown links from the message content as
    # a fallback. Some providers (and bare-id POSTs without :online) emit
    # sources only as ``[anchor text](https://...)`` in the answer rather
    # than in the ``annotations`` block. Without this fallback those
    # citations would be invisible to the synthesis / source-support UI.
    # Skip when the annotations block already produced citations: a
    # second scan over the full content would just re-discover URLs the
    # ``seen_urls`` dedup would then drop, and per-match sanitization is
    # wasted work.
    if not references:
        content_text = content if content is not None else _extract_message_content(payload)
        seen: set[str] = set()
        for match in _INLINE_MARKDOWN_LINK_RE.finditer(content_text):
            anchor, raw_url = match.group(1).strip(), match.group(2).strip()
            sanitized = _sanitize_source_url(raw_url)
            if sanitized is None or sanitized in seen:
                continue
            seen.add(sanitized)
            references.append(
                SourceReference(
                    title=anchor,
                    url=sanitized,
                    provider=ProviderPath.OPENROUTER_SEARCH,
                    is_fallback=False,
                ),
            )
    return references


#: Workstream-2: capture ``[anchor](https://...)`` style inline markdown
#: links. The URL class is ``[^\s)]+`` — non-whitespace, non-``)`` — so
#: the first ``)`` in the URL stops the capture and the closing
#: ``)`` of the markdown link syntax matches literally. This mirrors
#: the behaviour of most markdown renderers for raw URLs: a URL with
#: unbalanced ``)`` (e.g. a Wikipedia ``/wiki/Python_(programming_language)``
#: written without ``%29`` escaping) will be truncated at the first
#: ``)``; URLs with balanced parens that are *themselves* wrapped in
#: extra parens (e.g. ``[Foo](https://example.com/foo_(bar))``) are
#: also captured up to the inner ``)``. The single source of truth
#: for "is this URL allowed?" is ``_sanitize_source_url`` (http(s)
#: scheme + host denylist) — the regex only governs the
#: shape of the markdown link, not the URL semantics.
_INLINE_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")


#: Characters-per-material-claim heuristic. Industry rule of thumb is one
#: factual assertion per ~150-250 characters of generated text (i.e. one per
#: short paragraph); 200 is a defensible mid-point.
#:
#: WP-C / F-03: this is a LENGTH ESTIMATE, not the citation-coverage
#: denominator. It used to be, and that was the defect — dividing a per-answer
#: boolean by it made the 80% target unreachable at any realistic answer
#: length. Its only remaining job is the informational
#: ``QueryRunResultResponse.material_claim_count`` figure. Do not reintroduce
#: it into :func:`calculate_citation_coverage`.
MATERIAL_CLAIM_CHAR_DENOMINATOR = 200


def estimate_material_claim_count(answer_text: str) -> int:
    """Roughly how many material claims ``answer_text`` is long enough to hold.

    A length heuristic, not claim extraction — true extraction would need its
    own LLM call. Reported for information only; see
    :data:`MATERIAL_CLAIM_CHAR_DENOMINATOR` for why it is NOT the coverage
    denominator.
    """
    text = (answer_text or "").strip()
    if not text:
        return 1
    return max(1, ceil(len(text) / MATERIAL_CLAIM_CHAR_DENOMINATOR))


def calculate_citation_coverage(
    *,
    answer_count: int,
    sourced_answer_count: int,
) -> CitationCoverage:
    """Coverage = the share of answers carrying at least one primary source.

    Both arguments are counted in the SAME unit — answers. That is the whole
    point of WP-C / F-03: the previous signature took a boolean numerator and a
    characters-derived denominator, so the ratio fell as answers got longer
    even when every one of them was sourced.
    """
    if answer_count <= 0:
        return CitationCoverage(
            answer_count=0,
            sourced_answer_count=0,
            sourced_answer_ratio=Decimal("0"),
            target_met=False,
        )
    sourced_answer_ratio = (Decimal(sourced_answer_count) / Decimal(answer_count)).quantize(
        Decimal("0.01")
    )
    return CitationCoverage(
        answer_count=answer_count,
        sourced_answer_count=sourced_answer_count,
        sourced_answer_ratio=sourced_answer_ratio,
        target_met=sourced_answer_ratio >= CITATION_COVERAGE_TARGET,
    )


provider_event_recorder = InMemoryProviderEventRecorder()
provider_execution_service = ProviderExecutionService()
provider_stub_service = provider_execution_service
