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

import contextlib
import json
import logging
import re
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import StrEnum
from http.client import HTTPException, IncompleteRead
from math import ceil
from threading import RLock
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from product_app.config import RuntimeEnvironment, settings
from product_app.credentialed_url import (
    CREDENTIAL_OPENER,
    base_url_provenance,
    chat_completions_url,
    tavily_search_url,
)
from product_app.feedback_store import record_event as _record_feedback_event
from product_app.model_slots import ModelSlot, openrouter_model_catalog_service
from product_app.provider_keys import ProviderCredentialSource
from product_app.telemetry_sink import TOKEN_TELEMETRY_LOGGER
from product_app.untrusted_text import fence
from product_app.visible_text import is_visible

_LOGGER = logging.getLogger(__name__)

# W21/W22 (ADR-0090). Both credentialed calls below dial through
# ``CREDENTIAL_OPENER`` -- which refuses to follow a redirect -- rather than
# through the bare ``urlopen`` free function, so a base that answers its
# first request with a 302 cannot hand ``Authorization: Bearer <key>`` to an
# unvalidated host. Bound under the name ``urlopen`` (not e.g.
# ``_urlopen``) so every existing ``monkeypatch.setattr(providers_module,
# "urlopen", double)`` in the test suite keeps intercepting the call: those
# doubles replace whatever this module attribute is bound to, not a snapshot
# of the stdlib function, and both ``_post_messages`` and ``_tavily_search``
# look the name up from this module's globals on every call.
urlopen = CREDENTIAL_OPENER.open

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


#: The provider paths on which NO model was ever sent the question. A COMPLETED
#: answer on one of these carries ``_local_simulation_text`` — this product's own
#: words, not a model's.
#:
#: BOTH members belong here, and the second is easy to miss. #247 was filed
#: naming ``LOCAL_SIMULATION`` alone; measured 2026-08-04, a fallback-forced demo
#: run produces four ``FALLBACK_SEARCH`` slots carrying the same template and
#: rendered the same "4 of 4 models aligned". A ``LOCAL_SIMULATION``-only set
#: fixes half the defect.
#:
#: Why the PATH is a sound discriminator, when the ``use_fallback`` branch of
#: ``produce_initial_answer`` appears to let ``FALLBACK_SEARCH`` carry live text:
#: that arm is dead. The ``OPENROUTER_SEARCH`` branch above it returns whenever
#: ``live_response is not None and live_response.answer_text``, and
#: ``live_response`` is not reassigned in between, so the condition is provably
#: ``False`` there. Proved by execution as well as by reading: replacing that arm
#: with ``raise AssertionError`` and running the whole suite left it green — the
#: assertion never fired.
#:
#: No pass-count is quoted, deliberately. The first draft said "2279 passed, 0
#: failed", which was the total on ``9981bab`` BEFORE this change added its own
#: tests; re-running the same experiment on HEAD gives a different total, so a
#: reviewer who checked the figure found it irreproducible and was right to. The
#: claim that matters reproduces on any tree: the assertion never fires.
#:
#: Line numbers are deliberately not cited either — they shift with every edit to
#: the file and go stale silently.
#:
#: ``query_runs`` derives ``demo_mode`` and ``local_count`` from this same pair
#: and now READS this constant to do it. It spelled the pair out inline twice
#: until #247; adversarial review caught this comment claiming "expressed ONCE"
#: while a second and third copy sat in ``query_runs``. One definition, because
#: two matchers built from one constant drift.
NOT_INVOKED_PATHS = frozenset({ProviderPath.LOCAL_SIMULATION, ProviderPath.FALLBACK_SEARCH})

#: The complement. Written out rather than derived so that
#: ``test_every_provider_path_is_classified_as_invoked_or_not`` can prove the two
#: sets PARTITION :class:`ProviderPath`. A new enum member added to neither set
#: would otherwise default silently to "a model was invoked" and re-open #247 on
#: the new path.
INVOKED_PATHS = frozenset({ProviderPath.OPENROUTER_SEARCH})


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
# #176: "did not return a usable response" claimed the provider responded.
# It is the production copy for at least SIX distinct shapes, and no single
# causal clause is true of all of them: DNS failure and connection refused
# (the request never reached the provider at all); 401, 402 and 429 (the
# provider refused it before any generation happened); AND a whitespace-only
# completion (``_live_openrouter_response``, guarded by ``.strip()`` — a REAL
# response the provider generated and billed for, see ``_failed_answer``'s own
# docstring). A first replacement said "the request to the provider did not
# succeed" — true for the first five, false for the sixth, where the request
# succeeded and only the content was unusable. Round-1 review caught this by
# reproducing the whitespace-completion path directly, not by reasoning about
# the fix. The only sentence true of all six says nothing about whether a
# request or a response happened at all. Its deleted predecessor's own comment
# said explicitly: "it must not claim the model was asked." Neither must this
# one claim a response arrived, and now neither must it claim one didn't.
NOTICE_PROVIDER_UNAVAILABLE = "This model's answer is unavailable."
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
    #: The model this usage was actually billed against, when the caller
    #: knows it at capture time (issue #290). ``None`` for a record built
    #: before this field existed, or wherever the caller has not been
    #: updated to stamp it — the pricing layer falls back to its own
    #: default (the moderator/writer model id) in that case, so an absent
    #: value never changes existing behaviour. Not populated by
    #: ``_extract_usage`` itself, which only sees the response body, not
    #: which model the request targeted; callers that know the model
    #: (``debate.py``, ``synthesis.py``) stamp it after the call returns.
    model_id: str | None = None


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
    #: WP-D (F-07): this answer is NOT the model's complete view, so the text
    #: below is incomplete. Two causes set it, and the field deliberately does
    #: not distinguish them — see :data:`_UNCLEAN_FINISH_REASONS`:
    #:
    #: * ``finish_reason == "length"`` — the provider's token ceiling cut it
    #:   off. The original and, until 2026-08-26, the only cause.
    #: * ``finish_reason == "error"`` — the provider broke part-way through.
    #:
    #: Anything user-visible that renders this must therefore describe the
    #: EFFECT ("ends mid-thought", "not the model's complete view") and never
    #: assert the CAUSE, because it cannot tell which one applied. Two strings
    #: in ``app.js`` said "hit the length limit Quorum sets on each call" and
    #: were corrected when the second cause was added.
    #:
    #: Only a live provider call can set this — simulated, fallback, failed,
    #: cancelled and deadline-exceeded answers all keep the ``False`` default,
    #: because none of them was truncated BY A MODEL.
    #:
    #: This crosses the API boundary so the UI can mark the answer
    #: "(shortened)" instead of presenting a mid-sentence stop as the model's
    #: complete view. It is INERT until that surface exists (WP-F).
    shortened: bool = False


def model_was_invoked(answer: InitialModelAnswer) -> bool:
    """Was this answer's text produced by actually sending the question to a
    model?

    ``False`` for the two simulated paths (:data:`NOT_INVOKED_PATHS`), whose
    text this product wrote. The distinction matters wherever an answer is read
    as EVIDENCE — #247: four simulated slots differ only by the model id, score
    pairwise 4-gram Jaccard 0.500-0.579 against a 0.1 threshold, and were
    reported as "4 of 4 models aligned" on a run that asked nobody.

    Deliberately keyed on ``provider_path`` and not on matching the template
    text: a second matcher built from the same constant drifts the moment the
    template is reworded, and drifts silently. Deliberately not a new field on
    :class:`InitialModelAnswer` either — that model crosses the API boundary, so
    a field costs an OpenAPI change and a contract change to express what the
    path already determines.

    Says NOTHING about whether the slot produced text. A simulated slot did
    produce text and it is shown on screen; callers that need "did this slot
    come up empty?" must still test ``status`` / ``is_visible``. Conflating the
    two makes the stance table narrate "No usable answer was returned" over an
    answer the user can read.
    """
    return answer.provider_path not in NOT_INVOKED_PATHS


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

    def cancelled_answer(
        self,
        *,
        model_slot: ModelSlot,
        account_id: UUID,
        query_run_id: UUID,
        credential_source: ProviderCredentialSource,
    ) -> InitialModelAnswer:
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

        #188: also records a ``provider_initial_answer_cancelled`` event —
        before this, a cancelled slot contributed to neither
        ``total_calls`` nor ``failed_count`` in the ops audit; it was
        entirely absent, not merely miscounted.
        """
        provider_event_recorder.record(
            event_type="provider_initial_answer_cancelled",
            account_id=account_id,
            query_run_id=query_run_id,
            model_id=model_slot.model_id,
            provider_path=ProviderPath.OPENROUTER_SEARCH,
            duration_ms=0,
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
            latency_ms=0,
            citation_coverage=calculate_citation_coverage(
                answer_count=0,
                sourced_answer_count=0,
            ),
            error_code="CANCELLED",
            provider_notice=NOTICE_CANCELLED,
        )

    def deadline_exceeded_answer(
        self,
        *,
        model_slot: ModelSlot,
        account_id: UUID,
        query_run_id: UUID,
        credential_source: ProviderCredentialSource,
    ) -> InitialModelAnswer:
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

        #188: also records a ``provider_initial_answer_deadline_exceeded``
        event — mirrors :meth:`cancelled_answer`'s fix, for the sibling gap.
        """
        provider_event_recorder.record(
            event_type="provider_initial_answer_deadline_exceeded",
            account_id=account_id,
            query_run_id=query_run_id,
            model_id=model_slot.model_id,
            provider_path=ProviderPath.OPENROUTER_SEARCH,
            duration_ms=0,
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
        # No count is quoted above, on purpose. An earlier draft said "all ten
        # ... sites" and review could not re-derive ten under any reading. Two
        # figures ARE re-derivable in ``debate.py`` + ``synthesis.py``: EIGHT
        # ``live.answer_text.strip()`` call sites, and THIRTEEN occurrences of
        # ``.strip()`` in total. Anything between them depends on which helpers
        # you elect to count, so no such number appears here — a first repair of
        # this comment quoted "eleven" for that middle reading and review could
        # not reproduce that either. A count in prose is a claim; this sentence
        # names the SET so a reader greps it instead of trusting a figure.
        #
        # #178 FIXED: ``str.strip()`` removed only characters where
        # ``str.isspace()`` is true, so a completion of zero-width or
        # invisible characters (U+200B, U+FEFF, U+00AD, U+2800 ...) was still
        # served as an answer, with the same wrong numbers described above.
        # ``visible_text.is_visible`` extends the predicate to Unicode format
        # (Cf) and control (Cc) characters plus two named outliers, and is
        # applied at every site named above so they do not disagree again.
        #
        # The correction to the note this replaced, which is the reason the
        # defect looked safe: it quoted ``initial_fully_captured`` as requiring
        # ``provider_path is OPENROUTER_SEARCH`` and ``token_usage is not
        # None``. The gate (``query_runs.py``) has a THIRD conjunct — ``status
        # is COMPLETED`` — and that omission is load-bearing. It is what makes
        # a whitespace slot's usage reach a measured receipt while a failed
        # slot's cannot, and it is why the fix costs the run its ``measured``
        # label: see ``_failed_answer`` for the money decision (#175).
        if not is_visible(result.answer_text):
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
        response_format: dict[str, object] | None = None,
        reasoning: dict[str, object] | None = None,
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
        # Forwarded ONLY when set. Passing ``response_format=None`` explicitly
        # would be semantically identical for the real implementation, but it
        # changes the CALL, and ``_post_messages`` is doubled in several
        # pre-existing tests whose fakes take a fixed signature. Keeping the
        # call byte-identical for every non-judge caller is the strongest form
        # of "debate and synthesis are untouched" — it holds for their test
        # doubles too, not just for the wire payload.
        extra: dict[str, Any] = {}
        if response_format is not None:
            extra["response_format"] = response_format
        if reasoning is not None:
            extra["reasoning"] = reasoning
        return self._post_messages(
            openrouter_key=openrouter_key,
            model_id=model_id,
            messages=messages,
            max_tokens=max_tokens,
            **extra,
        )

    def _post_messages(
        self,
        *,
        openrouter_key: str,
        model_id: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        response_format: dict[str, object] | None = None,
        reasoning: dict[str, object] | None = None,
    ) -> LiveProviderResult | _SearchRejected | _DispatchedUnmeasured | None:
        # ``response_format`` and ``reasoning`` are EXPLICIT named parameters
        # rather than a ``**extra`` passthrough, and both default to ``None``.
        # Two reasons, both deliberate:
        #
        #   * a dict passthrough would let any caller put anything on the wire,
        #     which is a poor property for the one function that talks to a paid
        #     upstream. Note the ``**extra`` splat in ``_post_openrouter`` is
        #     itself untyped at that one boundary — review demonstrated that
        #     misspelling a key there passes ``mypy`` and is caught only by the
        #     tests. Two literal keys, so the blast radius is small, but the
        #     named parameters do not buy STATIC safety all the way down; and
        #   * defaulting to ``None`` means a caller that wants neither gets a
        #     BYTE-IDENTICAL payload and, more importantly, an unchanged CALL —
        #     ``_post_messages`` is doubled by several tests whose fakes take a
        #     fixed keyword signature. Pinned by
        #     ``test_a_non_judge_call_sends_neither_parameter``, which asserts on
        #     a ``call_with_prompt`` that passes neither.
        #
        #     This paragraph used to say the default kept "the debate and
        #     synthesis payloads BYTE-IDENTICAL" because those stages "feed the
        #     visual-baseline lane". Both halves are now wrong and the correction
        #     is worth stating rather than deleting. #354 gives the DEBATE call a
        #     ``response_format``, so its payload has moved. And the visual lane
        #     never saw these payloads in the first place: ``e2e.yml`` runs
        #     Playwright against route-mocked fixtures, so no provider request is
        #     made on that lane at all. What the default really protects is the
        #     fixed-signature test doubles — which is a real cost (one went red
        #     on #354 and had to be widened) but not a pixel one.
        payload: dict[str, object] = {
            "model": model_id,
            "messages": messages,
            # Every call THIS SERVICE makes streams (ADR-0084). Not a mode and
            # not a flag. Probed against the live API on 2026-08-26 --
            # ``openai/gpt-4o-mini``, same model and endpoint, non-streamed at
            # ``max_tokens=2000`` (the "spike" run) against streamed at
            # ``max_tokens=3000``: worst inter-chunk gap 22.440 / 25.055 s
            # against 0.478 / 0.208 s. The caps differ, so read it as the
            # comparison its own source calls it and not as a controlled one.
            # ``openrouter_timeout_seconds`` (8.0) therefore fires on a HEALTHY
            # non-streamed call, which is billed, answers nothing, and degrades
            # the run's receipt to ``estimated``.
            #
            # Scope, stated because the obvious sentence is false: the probe
            # measured that bite on ONE of the four shipped answer models, and
            # the probe itself calls the per-``recv`` bite a property of the
            # MODEL rather than of the endpoint -- ``nvidia/nemotron`` was
            # 5.722 / 7.589 s, under the cap. Streaming is chosen because it
            # removes the failure mode wherever a model has it, not because
            # every model has it. Keeping a non-streaming path as well would
            # keep a second, unexercised reader on the paid seam.
            #
            # ``stream_options: {"include_usage": true}`` is deliberately NOT
            # sent; ADR-0084 records why, and the reader takes usage from
            # whichever frame carries it either way.
            "stream": True,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format is not None:
            payload["response_format"] = response_format
        if reasoning is not None:
            payload["reasoning"] = reasoning
        # W18 / ADR-0085. ``OPENROUTER_API_BASE_URL`` is operator-settable and
        # the headers below carry ``Authorization: Bearer <the operator's
        # key>``. ``chat_completions_url`` returns ``None`` rather than an
        # endpoint when that base must not carry a credential -- cleartext to
        # anything that is not this machine, or a scheme ``urlopen`` speaks
        # that is not a chat endpoint at all. Building the URL through the
        # guard rather than checking a flag beside it is the point: the
        # endpoint cannot be obtained without the check.
        #
        # ``None``, not ``_DISPATCH_UNMEASURED``. Nothing left the process, so
        # nothing can have been billed, and this method's own contract already
        # gives ``None`` exactly that meaning.
        #
        # Stated as a CONTRACT and not as an observed difference, because
        # review measured the difference and could not find one: mutating this
        # to ``_DISPATCH_UNMEASURED`` and diffing every run-level field
        # (``status``, ``live_count``, ``local_count``, ``cost_source``,
        # ``actual_cost_usd``, ``failed_steps``, the daily meter) left them
        # identical. A refused base refuses EVERY call in the run, so no
        # measured slot survives for the distinction to protect. It is still
        # the right return -- a run that mixes a refused base with some other
        # dispatch path would need it, and lying about billing is not
        # something to do only when it is observable.
        #
        # What IS measured on ``origin/main``, with a recording ``urlopen``
        # over one full query run against a cleartext base: 11 dispatched
        # requests, every one carrying ``Authorization: Bearer``, and the run
        # reporting ``live_count 4`` and a ``measured`` receipt. The leak was
        # per-call, not per-run, and nothing looked wrong.
        url = chat_completions_url(settings.openrouter_api_base_url)
        if url is None:
            base_scheme, base_host = base_url_provenance(settings.openrouter_api_base_url)
            # Scheme and host only, NEVER the configured URL: a base URL can
            # carry userinfo (``https://user:pass@host``) and that is
            # credential material. ``urlsplit(...).hostname`` excludes it.
            _LOGGER.warning(
                "provider_base_url_refused",
                extra={
                    "model_id": model_id,
                    "billing_class": "not_billed",
                    "base_url_scheme": base_scheme,
                    "base_url_host": base_host,
                },
            )
            return None
        request = Request(
            url=url,
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
            # The budget clock starts HERE, before ``urlopen``, not after it.
            # ``urlopen`` returns only once the status line and the whole
            # header block have been read, and that phase is bounded
            # per-``recv`` exactly like the body was -- so a header block
            # dribbled a byte at a time is unbounded in wall clock. Starting
            # the clock before the call makes the BUDGET cover connect,
            # request, headers and body together, which is what
            # ``openrouter_call_budget_seconds`` claims to be. Without this the
            # claim was false, and a review measured the header phase alone
            # reaching several times the budget.
            call_started = time.monotonic()
            with urlopen(request, timeout=settings.openrouter_timeout_seconds) as response:
                # NOT ``response.read()``. That is bounded per-``recv`` and
                # therefore not bounded at all in wall clock; see
                # ``_iter_body_within_budget``. A ``TimeoutError`` from here
                # lands in the catch-all below and is classified
                # ``_DISPATCH_UNMEASURED``, which is correct: the request was
                # dispatched and may have been billed.
                #
                # The budget matters MORE now, not less. SSE keep-alive
                # comments reset the per-``recv`` timer, so
                # ``openrouter_timeout_seconds`` stops bounding a streamed call
                # at all -- reproduced on loopback, a comment every 1.0s under
                # an 8.0s socket timeout read to completion in 12.044s with the
                # timeout never firing. ``openrouter_call_budget_seconds`` is
                # now the ONLY wall-clock brake on a paid call.
                # Retained for every call up to _NON_SSE_BODY_LIMIT_BYTES, so
                # a response that is not a stream at all can still be read as
                # the completion it is. The tee cannot see frames, so this is a
                # bounded cost on the happy path too -- which is why the bound
                # is small. See that constant for the measurement.
                head: list[bytes] = []
                head_bytes = 0

                def _tee(source: Iterator[bytes]) -> Iterator[bytes]:
                    nonlocal head_bytes
                    for piece in source:
                        # Truncate EXACTLY at the limit. Checking the total
                        # before appending the whole piece let the chunk that
                        # crossed the bound through in full, so the real
                        # ceiling was the limit plus one 64 KiB read -- a bound
                        # that can overshoot by a whole chunk is not a bound,
                        # and it let an oversized body through intact.
                        #
                        # Two mutants of these two lines survive the suite and
                        # are EQUIVALENT, checked rather than assumed: with
                        # ``>= 0`` the extra pass appends ``b""`` and adds 0,
                        # and with ``len(piece)`` in place of ``min(...)`` only
                        # the counter moves -- and nothing reads that counter.
                        # Verified byte-identical across exact-fill,
                        # overshoot-by-one, cross-mid-piece, many-small and
                        # empty-piece inputs, with the retained bytes never
                        # exceeding the limit in any of them.
                        allowance = _NON_SSE_BODY_LIMIT_BYTES - head_bytes
                        if allowance > 0:
                            head.append(piece[:allowance])
                            head_bytes += min(len(piece), allowance)
                        yield piece

                streamed = _reassemble_streamed_completion(
                    _iter_sse_data(
                        _tee(
                            _iter_body_within_budget(
                                response,
                                settings.openrouter_call_budget_seconds
                                - (time.monotonic() - call_started),
                                settings.openrouter_timeout_seconds,
                            )
                        )
                    )
                )
                if streamed.frame_count == 0 and streamed.body_error is None:
                    # Nothing parsed as a stream. Before assuming the call
                    # failed, read the body as the ordinary completion it may
                    # be: an upstream that ignores ``stream: true``, or a proxy
                    # that buffers the stream, returns exactly that. Measured
                    # against ``origin/main``, such a body produced a real
                    # answer with its usage; refusing it here would have thrown
                    # away a complete PAID answer and degraded the run to
                    # ``estimated``.
                    #
                    # Deliberately narrow: only when NOT ONE frame parsed, so a
                    # real stream can never reach it, and gated on the body
                    # actually being a completion-shaped mapping.
                    #
                    # Widening the count to ``<= 1`` survives the suite, and an
                    # earlier version of this comment called that EQUIVALENT on
                    # the argument that a body yielding a parsed frame cannot
                    # also parse whole as a JSON completion. **That argument is
                    # false and the mutant is not equivalent.** The fallback
                    # parses the retained HEAD, not the whole body, so a body
                    # whose first 64 KiB are a complete completion followed by
                    # newlines -- ``json.loads`` tolerates trailing whitespace
                    # -- and whose TAIL carries SSE frames satisfies both
                    # halves at once. Measured: ``frame_count = 1`` with the
                    # head parsing as a completion mapping, and widening the
                    # guard turned a refusal into a SERVED, usage-bearing
                    # answer end to end.
                    #
                    # So the count stays at zero because widening it is a
                    # demonstrated hole, not because the difference is
                    # unobservable. The surviving mutant is a real gap in the
                    # tests, recorded rather than papered over: constructing
                    # that body is four lines (pad a completion to 64 KiB with
                    # newlines, then append frames), so the cost is low -- it
                    # is simply not worth a 64 KiB fixture while the guard is
                    # correct and this comment records the counterexample.
                    with contextlib.suppress(*_EXPECTED_BODY_ERRORS, UnicodeDecodeError):
                        whole = json.loads(b"".join(head).decode())
                        if isinstance(whole, dict) and "choices" in whole:
                            streamed = _StreamedCompletion(
                                payload=whole,
                                terminator=_STREAM_TERMINATOR_NOT_A_STREAM,
                                frame_count=0,
                                unrecognised_lines=0,
                                body_error=None,
                            )
        except HTTPError as exc:
            # 404 / 400 on the ``:online`` variant is the documented
            # signal that this model does not support the search
            # suffix; the caller retries with the bare model id.
            # Log non-benign errors at WARNING so a revoked key or
            # rate limit is visible to operators (detection gap if
            # we silently return).
            if exc.code in (400, 404) and model_id.endswith(":online"):
                return _SEARCH_REJECTED
            # F-06 billing classification. A rejected REQUEST (bad JSON body,
            # bad/insufficient credentials, unknown model, rate limit) is
            # refused before any token is generated, so nothing was billed and
            # the caller must be free to keep the run ``measured``. Any other
            # status — 5xx above all — can follow a generation that already
            # consumed tokens, so it is reported as dispatched-but-unmeasured.
            #
            # Issue #105: that 5xx premise has NO evidence behind it, and a
            # router-level 503 ("no allowed providers") is decided before any
            # provider is engaged — measured overstating one run's served cost
            # by 5.27x. The classification is deliberately NOT changed here on
            # a guess about an external API's semantics. Instead the evidence
            # that decides it is recorded, so the question can be settled from
            # a week of production logs. ``billed`` is computed once and feeds
            # both the log and the return, so the record can never disagree
            # with the decision it describes.
            billed = exc.code not in _UNBILLED_HTTP_STATUSES
            _LOGGER.warning(
                "upstream_provider_http_error",
                extra={
                    "status_code": exc.code,
                    "url": exc.url,
                    "model_id": model_id,
                    "billing_class": "possibly_billed" if billed else "not_billed",
                    **_billing_evidence_shape(exc),
                },
            )
            if not billed:
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
            #
            # Issue #105 folds this branch into the same review, and measured
            # on 56edd1b it logged NOTHING AT ALL — so the conservative
            # possibly-billed call above produced no evidence to review later.
            # Only the reason's CLASS NAME is recorded, never ``str(exc)``: a
            # ``URLError`` reason can carry a header value verbatim and a
            # header value can be key material (the same lesson
            # ``_log_post_dispatch_failure`` records).
            billed = isinstance(exc.reason, TimeoutError)
            _LOGGER.warning(
                "upstream_provider_opener_error",
                extra={
                    "error_type": type(exc.reason).__name__,
                    "model_id": model_id,
                    "billing_class": "possibly_billed" if billed else "not_billed",
                },
            )
            if billed:
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

        if streamed.body_error is None and (
            streamed.terminator == _STREAM_TERMINATOR_NONE or streamed.unrecognised_lines
        ):
            # The stream stopped without ever saying it had finished: no
            # ``[DONE]``, no ``finish_reason``, no error frame. Under chunked
            # framing -- which every streamed response uses -- that is
            # indistinguishable at the transport layer from a complete one, so
            # nothing above raised. Serving what arrived would price a cut
            # answer as a whole one and report ``is_truncated=False``.
            #
            # ``_DISPATCH_UNMEASURED`` is the honest reading: the request was
            # dispatched, tokens were generated, and we cannot say what we got.
            # ``stream_frames`` separates "the upstream sent nothing that
            # parsed as a stream" (0) from "it stopped part-way" (>0), which is
            # the distinction anyone reading the #105 dataset will need.
            # ``usage_absent`` is carried for the same reason
            # ``upstream_provider_empty_answer`` carries it: without it the
            # record cannot tell a billed dead end from an unbilled one, which
            # is the whole question #105 exists to settle.
            #
            # The usage this DISCARDS is deliberate and is a real cost, so it
            # is stated rather than buried: unlike the empty-answer path, which
            # keeps the provider's stated charge because the response was
            # complete, here the response was NOT complete. Serving a cut
            # answer to keep its usage would price a fragment as a whole
            # answer, and that is the dishonesty the whole design exists to
            # prevent. The record preserves the fact that a charge may exist.
            _LOGGER.warning(
                "upstream_provider_stream_incomplete",
                extra={
                    "model_id": model_id,
                    "billing_class": "possibly_billed",
                    "stream_frames": streamed.frame_count,
                    "unrecognised_lines": streamed.unrecognised_lines,
                    "usage_absent": _extract_usage(streamed.payload) is None,
                },
            )
            return _DISPATCH_UNMEASURED

        try:
            if streamed.body_error is not None:
                # Raised HERE rather than inside the ``urlopen`` block so a
                # malformed frame is logged as a BODY failure at WARNING, not
                # as a transport failure at ERROR. See ``_StreamedCompletion``.
                raise streamed.body_error
            parsed = streamed.payload
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
        if not is_visible(content):
            # The ONE dispatched-failure path that used to record nothing at
            # all. A 200 whose body parses but yields no usable answer — an
            # error envelope with no ``choices``, an empty completion against a
            # tight cap, a proxy's JSON denial page, a bare ``{}`` — reached
            # this point silently, so it could not be counted in the dataset
            # issue 105 is to be settled from, while every other failure path
            # logged.
            #
            # The RETURN is deliberately unchanged. F-06 finding C: the
            # provider's own statement of what it charged is extracted above
            # any emptiness guard and must survive it, so collapsing this to
            # ``_DISPATCH_UNMEASURED`` would tidily throw away a known charge
            # and force ``estimated`` on a call whose cost is measured. The
            # defect here was the silence, not the classification.
            #
            # The predicate is ``is_visible``, matching the gate that actually
            # fails the slot in ``_live_openrouter_response`` — a narrower
            # ``not content`` would let a whitespace-only completion be dropped
            # downstream while leaving no record of why.
            #
            # No part of the body reaches the record. A provider error string
            # is upstream-controlled text of unbounded length; ``usage_absent``
            # carries everything a reader needs to tell a billed dead end from
            # an unbilled one.
            _LOGGER.warning(
                "upstream_provider_empty_answer",
                extra={
                    "model_id": model_id,
                    "billing_class": "possibly_billed",
                    "usage_absent": usage is None,
                },
            )
        # Issue #268's measurement. Emitted OUTSIDE the parsing ``try`` above
        # on purpose: that clause returns ``_DISPATCH_UNMEASURED`` for anything
        # it catches, so an exception raised by instrumentation inside it would
        # silently downgrade a perfectly measurable, already-billed call to
        # ``estimated``. Instrumentation must never be able to move money, so
        # it is suppressed HERE, at the call site, rather than only inside the
        # helper — pinned by
        # ``test_a_telemetry_failure_cannot_change_what_the_provider_call_returns``.
        with contextlib.suppress(Exception):
            _log_call_token_shape(
                model_id=model_id,
                messages=messages,
                max_tokens=max_tokens,
                usage=usage,
                stream_terminator=streamed.terminator,
            )
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
        response_format: dict[str, object] | None = None,
        reasoning: dict[str, object] | None = None,
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
            response_format=response_format,
            reasoning=reasoning,
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
        """The demo placeholder "source" for a slot no model was asked.

        ``is_fallback=True``, and that single flag is the whole fix for the
        second half of #247. It was ``False``, which is what made a citation this
        product invented count as a PRIMARY source: on a keyless run all four
        slots carried one, so ``citation_coverage`` reported **4 of 4, 100%**,
        and the Source-support section read "4 of 4 responding models returned
        visible source references" — about four answers this product wrote
        itself, citing ``example.test/local-demo/N``, an IANA-reserved domain
        that resolves to nothing.

        The flag means "not the model's own citation", which is exactly what this
        is, so no new concept is needed. Both consumers already key on it —
        ``synthesis._build_source_support`` and the aggregated
        ``calculate_citation_coverage`` numerator both test
        ``any(not source.is_fallback ...)`` — so correcting it here corrects the
        metric and the prose at once rather than in two places that could drift.

        #171 diagnosed this exact mechanism in ``produce_initial_answer`` ("its
        ``is_fallback=False`` demo source is what makes it count as PRIMARY") and
        closed the PER-MODEL route by making a live failure a FAILED slot. The
        WHOLE-RUN demo route it named was left open; this closes it.

        The source is still RETURNED, not dropped: the slot really does show the
        user a reference, and hiding it would be its own dishonesty. It simply no
        longer counts toward a coverage figure that claims model-cited evidence.
        """
        return [
            SourceReference(
                title=f"Local demo evidence for slot {model_slot.slot_number}",
                url=f"{LOCAL_SIMULATION_URL_PREFIX}{model_slot.slot_number}",
                provider=ProviderPath.LOCAL_SIMULATION,
                is_fallback=True,
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

        W22 (ADR-0090). ``tavily_search_url`` refuses a base that would put
        the key in clear or hand it to something that is not this endpoint at
        all -- ``None`` means "do not dial this, and do not report a charge",
        the same contract ``chat_completions_url`` gives ``_post_messages``.
        """
        query = (query_text or "").strip()
        if not query:
            return []
        url = tavily_search_url(settings.tavily_api_base_url)
        if url is None:
            base_scheme, base_host = base_url_provenance(settings.tavily_api_base_url)
            # Scheme and host only, never the configured URL: it can carry
            # userinfo, which is credential material.
            _LOGGER.warning(
                "tavily_base_url_refused",
                extra={
                    "billing_class": "not_billed",
                    "base_url_scheme": base_scheme,
                    "base_url_host": base_host,
                },
            )
            return []
        payload = json.dumps(
            {
                "query": query,
                "max_results": settings.tavily_max_results,
            }
        ).encode()
        request = Request(
            url=url,
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


#: Issue #105 step 1. Bound on how much of a provider ERROR body is read to
#: describe its shape. The two error envelopes this repo has fixtures for are
#: 96 and 133 bytes (no real captured OpenRouter body exists here, so treat the
#: typical size as ASSUMED, not measured); a corporate proxy's HTML denial can
#: be arbitrarily large, and this code runs on the failure path, where the
#: upstream is already misbehaving. A body whose DECLARED length exceeds this
#: is reported ``too_large`` and never read, so the evidence stays honestly
#: unknown instead of being guessed from a fragment.
_ERROR_BODY_SNIFF_LIMIT_BYTES: int = 8192

#: Issue #105. How long the evidence read may block, in seconds. The
#: connection carries ``openrouter_timeout_seconds`` (8.0), and a 503 whose
#: body never arrives was measured blocking this branch for the whole of it —
#: 0.008-0.013s (5 reps on main) to 8.009s on the error path — before raising
#: ``TimeoutError`` and learning nothing. A real OpenRouter error is answered
#: by Cloudflare in about 13ms (its own ``Server-Timing: cfWorker;dur=13``), so
#: two seconds is generous by two orders of magnitude while capping the damage
#: a misbehaving upstream can do.
_ERROR_BODY_SNIFF_TIMEOUT_SECONDS: float = 2.0

#: Chunk size for the budgeted read. Small enough that the deadline is checked
#: often; large enough that a normal ~50-byte error body arrives in one pass.
_ERROR_BODY_SNIFF_CHUNK_BYTES: int = 2048


def _billing_evidence_shape(exc: HTTPError) -> dict[str, object]:
    """Describe a provider error body's SHAPE — never its content (issue #105).

    ``_UNBILLED_HTTP_STATUSES`` treats every 5xx as possibly-billed on the
    premise that a 5xx can follow a generation that already consumed tokens.
    Issue #105's finding is that no evidence for that premise exists anywhere
    in this repo, and its instruction is to gather the evidence rather than
    guess: OpenRouter names the provider it engaged at
    ``error.metadata.provider_name``, so that key's ABSENCE from a well-formed
    error envelope means the router refused before any provider ran, and
    nothing could have been billed.

    ``provider_name_present`` is deliberately THREE-VALUED, and collapsing it
    is the specific defect this function exists to avoid:

    * ``True``  — a provider was named; a charge is possible.
    * ``False`` — an error envelope arrived and named no provider. Read it
      together with ``error_metadata_present``: ``False``/``False`` is the
      router refusal issue #105 is about, while ``False``/``True`` means the
      provider block existed but carried no name, which is NOT the same
      evidence and must not be counted as one.
    * ``None``  — unknown: unreadable, too large, empty, not JSON, or JSON
      carrying no ``error`` mapping to read.

    A ``False`` that also meant "we could not tell" would make the production
    log sample this exists to produce unreadable, because the router refusal
    and a parse failure would be the same record.

    THE READ IS BOUNDED IN TIME, and that matters more than bytes.
    ``exc.read()`` is a socket read carrying the connection's
    ``openrouter_timeout_seconds`` (8.0s): measured on a real loopback server,
    a 503 with the socket held open and the body withheld blocked this branch
    for the whole 8.009s, against 0.008-0.013s on ``main``, and then raised
    ``TimeoutError``,
    paying the entire timeout to learn nothing. So
    :func:`_read_within_budget` enforces ``_ERROR_BODY_SNIFF_TIMEOUT_SECONDS``
    as a DEADLINE, lowering the socket timeout to whatever remains of it before
    every chunk, capping the worst case at about 2s; it returns whether it
    could reach the socket at all, and ``sniff_time_bounded`` records that — it is
    best-effort, and a platform where it fails must say so rather than read as
    "no problem".

    It is NOT gated on ``Content-Length``. An earlier version was, and that was
    measured fatal against the real API: OpenRouter is behind Cloudflare and
    answers errors with ``Transfer-Encoding: chunked`` and no
    ``Content-Length``, so such a gate collects nothing in production while
    every local gate stays green. See :func:`_read_within_budget` and AGENTS.md
    rule 8c.

    NEVER returns body content. The values are two shape names, an integer and
    two tri-state flags. An error body can echo the user's query text back
    verbatim — and a proxy's HTML denial page routinely echoes the request
    headers, including ``Authorization`` — so logging any of it would be a data
    leak on an error path. Same lesson :func:`_log_post_dispatch_failure`
    records about exception messages carrying key material.

    NEVER raises. ``_post_messages`` guarantees that once ``urlopen`` has been
    called it RETURNS rather than raises; an instrumentation read that escaped
    would break that invariant on the very path it is measuring, turning a
    priced-but-unmeasured call into one that vanished entirely.
    """
    shape: dict[str, object] = {
        "body_shape": "unreadable",
        "body_bytes": 0,
        "error_metadata_present": None,
        "provider_name_present": None,
        "provider_name_header": _provider_name_header_present(exc),
        "sniff_time_bounded": False,
    }
    try:
        # One byte past the bound, purely so an over-large body is detectable;
        # the extra byte is dropped and never reported or parsed.
        raw, bounded = _read_within_budget(
            exc, _ERROR_BODY_SNIFF_LIMIT_BYTES, _ERROR_BODY_SNIFF_TIMEOUT_SECONDS
        )
        shape["sniff_time_bounded"] = bounded
        over = len(raw) > _ERROR_BODY_SNIFF_LIMIT_BYTES
        raw = raw[:_ERROR_BODY_SNIFF_LIMIT_BYTES]
        body_bytes = len(raw)
    except Exception:
        # Any failure to read at all — a dead socket, a consumed body, a
        # double whose ``read`` returns something that is not bytes — is
        # reported as "unreadable" and nothing more. ``len`` sits INSIDE the
        # try deliberately: it was outside at first, and a body object
        # returning ``None`` then raised ``TypeError`` straight through this
        # function, making the "never raises" promise above false.
        return shape
    shape["body_bytes"] = body_bytes
    if not raw:
        shape["body_shape"] = "empty"
        return shape
    if over:
        shape["body_shape"] = "too_large"
        return shape
    try:
        parsed = json.loads(raw)
    except Exception:
        shape["body_shape"] = "not_json"
        return shape
    shape["body_shape"] = "json"
    if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
        metadata = parsed["error"].get("metadata")
        has_metadata = isinstance(metadata, dict)
        shape["error_metadata_present"] = has_metadata
        provider_name = metadata.get("provider_name") if has_metadata else None
        shape["provider_name_present"] = bool(provider_name)
    return shape


#: One ``recv``'s worth of body. Large enough that a healthy response finishes
#: in a handful of iterations, small enough that ``read1`` returns promptly on a
#: dribble instead of blocking for a full buffer.
_BODY_READ_CHUNK_BYTES: int = 65536


def _iter_body_within_budget(response: Any, budget: float, per_recv: float) -> Iterator[bytes]:
    """Yield a SUCCESS response body in chunks, in at most ``budget`` seconds total.

    Raises ``TimeoutError`` when the deadline passes with the body incomplete.
    That is deliberate and is the whole point: ``_post_messages``' catch-all
    already classifies a post-dispatch exception as ``_DISPATCH_UNMEASURED``,
    which is the correct reading — tokens were generated and the call may well
    have been billed, we simply cannot say how much.

    **A socket timeout is per-``recv``, not cumulative.** Before this existed,
    ``response.read()`` was unbounded in wall clock no matter how small
    ``openrouter_timeout_seconds`` was set. Measured on loopback, a body
    dribbled 512 bytes per second through an 8.0s socket timeout that never
    fired: **12.042 s**. Measured against the live API, 6 paid reps of
    ``openai/gpt-5-mini`` at ``max_tokens=3000``: wall 25.072-40.170s with a
    maximum inter-chunk gap of 0.643s, so **0 of 6 could have tripped the 8s
    cap and 6 of 6 exceeded it on wall clock**.

    Two details are inherited from ``_read_within_budget``, which learned them
    the expensive way, and one is new:

    * the budget is a DEADLINE re-applied before every chunk, not a single
      lowered timeout — that sibling's docstring measures the single-timeout
      version taking 16.051s against a 2s cap;
    * ``read1`` returns after ONE ``recv`` rather than looping until it has the
      requested count, which is what stops a slow dribble overrunning inside a
      single call;
    * the socket hop is ``response.fp.raw._sock`` — one level shallower than
      the ``HTTPError`` path's ``exc.fp.fp.raw._sock``. Measured, not assumed:
      on CPython 3.12 ``fp.raw._sock`` resolves to a ``socket`` on a success
      response while ``fp.fp.raw._sock`` raises ``AttributeError``.

    The per-chunk timeout is ``min(per_recv, remaining)`` so the existing
    stall detector keeps working inside the budget rather than being replaced
    by it. If the socket cannot be reached at all the deadline check between
    chunks still bounds the total, at the cost of one already-started ``recv``.

    ``budget`` is what REMAINS of the call's budget, not the whole of it: the
    caller starts the clock before ``urlopen`` so that connect, request,
    headers and body share one allowance. Passing the full budget here would
    leave the header phase unbounded, which is the same defect one layer up.

    **It YIELDS rather than returning one ``bytes``**, so the reader above it
    parses an SSE body without holding the whole of it -- with two measured
    exceptions, stated below, that make the unqualified version of that
    sentence false.

    Why it matters at the sizes streaming produces: the B3 probe recorded a
    2,594-token answer arriving in **4,194 frames**. That frame count is
    measured; the WIRE BYTES are not -- the probe kept no byte column and its
    script was not retained -- so any figure for them is a MODEL, at roughly
    300 bytes per frame, not a measurement. Order of magnitude: about 1.2 MB
    on the wire against roughly 10 KB for the same answer non-streamed, on a
    512 MB machine (``fly.toml``) running up to 16 initial-answer workers.
    Treat the ratio as "one to two orders of magnitude", not as a figure
    anybody can re-derive.

    **Two shapes still buffer without bound, and neither is hypothetical.** A
    ``data:`` line that never ends grows the reader's line buffer, and data
    lines never dispatched by a blank line grow its pending list. Measured,
    a 0.5 s budget against a newline-free body took resident memory up by
    about 1.2 GB -- better than the 3.4 GB the non-generator version took on
    the same body, but not bounded. Only ``openrouter_call_budget_seconds``
    caps it. There is no byte cap on the success path; the error path has
    ``_ERROR_BODY_SNIFF_LIMIT_BYTES`` and this does not.

    Exactly one loop still touches the socket, so the deadline, the
    ``min(per_recv, remaining)`` per-chunk timeout, the non-bytes guard and the
    ``IncompleteRead`` restore below are shared by every caller rather than
    reimplemented per body shape.

    One deliberate loss comes with that: ``IncompleteRead`` is raised carrying
    an EMPTY ``partial`` instead of the bytes so far, because keeping them
    would reintroduce the buffer this generator exists to avoid. Nothing reads
    ``.partial`` — the catch-all in ``_post_messages`` records only
    ``type(exc).__name__`` — and stuffing a megabyte of provider output into an
    exception was never a good idea on a path that logs.
    """
    deadline = time.monotonic() + budget
    received = 0
    reader = getattr(response, "read1", None)
    if not callable(reader):
        reader = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                "provider call exceeded its total time budget while reading the body"
            )
        with contextlib.suppress(Exception):
            # Best-effort: the hop is CPython-implementation-specific, and the
            # deadline check above is what makes the bound total either way.
            response.fp.raw._sock.settimeout(min(per_recv, remaining))
        chunk = reader(_BODY_READ_CHUNK_BYTES) if reader is not None else response.read()
        if not isinstance(chunk, (bytes, bytearray)):
            # NOT an end condition. ``if not chunk`` would be False for any
            # truthy non-bytes object, so treating this as EOF is how the first
            # version of this loop span forever against a ``MagicMock``
            # response — whose auto-generated ``read1`` returns another
            # ``MagicMock``, truthy, never empty. The sibling
            # ``_read_within_budget`` records the same class of hazard: a
            # transport handing back something other than bytes is BROKEN, not
            # finished, and calling it "empty" asserts something about the
            # upstream that is not true.
            #
            # Before rejecting it, fall back ONCE to the whole-body ``read``.
            # A real ``HTTPResponse.read1`` always returns bytes, so this path
            # is unreachable in production; it exists because a test double may
            # implement only ``read``, and refusing those would be this
            # function making a statement about the doubles rather than about
            # the wire.
            if reader is not None and received == 0:
                reader = None
                continue
            raise TypeError(
                f"provider response body read returned {type(chunk).__name__}, not bytes"
            )
        if not chunk:
            # EOF. That is only the END of the body if the framing agrees.
            #
            # ``read()`` -- the call this replaced -- runs ``_safe_read`` and
            # raises ``IncompleteRead`` when a ``Content-Length`` response ends
            # early. ``read1`` does not: it returns ``b""`` at EOF whether or
            # not the declared bytes arrived, so reading in a loop SILENTLY
            # DROPPED that check. Measured against a loopback server declaring
            # 4220 bytes and sending 124 before a graceful close:
            #
            #     OLD read():  RAISED IncompleteRead
            #     NEW (before this guard): RETURNED 124 bytes, resp.length=4096
            #
            # The delivered prefix was valid JSON, so the pipeline would have
            # served a truncated answer as complete, priced it, and reported
            # ``is_truncated=False``. Restoring the check is not optional: it
            # is the difference between a torn body being classified
            # ``_DISPATCH_UNMEASURED`` and being billed as a real answer.
            #
            # ``HTTPResponse.length`` is the bytes still expected under
            # ``Content-Length`` framing; it is ``None`` for chunked responses,
            # which do their own framing check inside ``read1`` and raise there
            # (verified: a torn chunked body raises ``IncompleteRead`` on both
            # the old and the new path).
            remaining_bytes = getattr(response, "length", None)
            if isinstance(remaining_bytes, int) and remaining_bytes > 0:
                raise IncompleteRead(b"", remaining_bytes)
            return
        received += len(chunk)
        yield bytes(chunk)
        if reader is None:
            # ``read()`` returns the whole body in one go, so there is nothing
            # left to loop for. Looping would call it again on an exhausted
            # stream.
            return


#: The SSE field carrying a chat-completion frame. Every other field the
#: specification defines -- ``event:``, ``id:``, ``retry:`` -- and every comment
#: line (one beginning ``:``) is discarded unread.
_SSE_DATA_FIELD = "data:"

#: The OpenAI-compatible sentinel that closes a stream.
_SSE_DONE_SENTINEL = "[DONE]"

#: The SSE fields that carry no completion data and are ignored by name. The
#: specification says to ignore an UNKNOWN field too -- this code deliberately
#: does not, because it cannot tell "a field we do not need" from "a data frame
#: we failed to recognise", and on a paid path the second is content silently
#: lost. See :data:`_UNRECOGNISED_LINE`.
_SSE_IGNORED_FIELDS: tuple[str, ...] = ("event:", "id:", "retry:")

#: A UTF-8 byte-order mark at the very start of a stream. The specification
#: says to strip one, and a BOM'd stream is otherwise a stream whose FIRST
#: frame silently vanishes -- measured, not theorised.
_SSE_BOM = b"\xef\xbb\xbf"

#: How much of a body to retain so a response that is not a stream at all can
#: still be read as the completion it is.
#:
#: **It is retained for EVERY call, not only for a non-stream**, and an earlier
#: version of this comment claimed the opposite -- that it was "dropped the
#: moment the first frame parses". The tee that fills it cannot see frames, so
#: that was false. This is a per-call memory cost paid on the happy path, and
#: the number is a bound on that cost rather than a generous allowance.
#:
#: **Every size below is DERIVED, not measured, and an earlier version of this
#: comment said "measured" for both.** The B3 probe recorded frame COUNTS and
#: kept no byte column, and its script was not retained, so the byte figures
#: are a model at ~300 bytes per frame -- the same per-frame figure used
#: above, deliberately, because two different ones in one file is how a model
#: starts reading as a measurement. What the model says:
#:
#: * at the old 1 MiB cap, a synthesis-leg answer (4,194-4,908 frames, so
#:   ~1.3-1.5 MB on the wire) would have filled the whole cap. An earlier
#:   version of this note added that a slot-1 answer "would NOT", on the
#:   probe's 1,736-1,794 frame rows -- **that was wrong, and wrong by
#:   generalising from length to call class**. Those two samples produced 845
#:   and 893 completion tokens against a 3,000 cap: they stopped early. Per
#:   TOKEN the slot model emits MORE frames than the synthesis model (2.05 and
#:   2.01 against 1.62 and 1.67), so a full-length slot answer at the shipped
#:   ``initial_answer_max_tokens = 2000`` extrapolates to ~4,000-4,100 frames,
#:   about 1.2 MB -- over the old cap, not under it. What the samples show is
#:   short ANSWERS, not a smaller call class;
#: * a non-streamed completion at ``initial_answer_max_tokens = 2000`` is
#:   ~8.3 KB (2000 tokens x ``CHARS_PER_TOKEN`` plus an envelope). The largest
#:   body anyone has CONSTRUCTED is ~45 KB -- an ``:online`` answer carrying 20
#:   citations -- so the headroom against 64 KiB is about 7x for the smallest
#:   call class and about 1.5x for the largest built one. Nobody has weighed a
#:   real ``:online`` response, so 1.5x is the honest floor, not a ceiling.
#:
#: A body above the cap is truncated, so ``json.loads`` fails and the call is
#: refused exactly as it would have been without the fallback: the safe
#: direction, and the same outcome as before the fallback existed. What is not
#: known is the true size of an ``:online`` response with real annotations --
#: ADR-0084 records that shape as unmeasured, and it is the one that would eat
#: this margin.
_NON_SSE_BODY_LIMIT_BYTES: int = 65_536


class _UnrecognisedLine:
    """A non-blank line that is neither a comment nor a field we know.

    Yielded rather than dropped because dropping is what made a BOM, a leading
    space, or ``Data:`` with a capital D delete a frame in silence -- and the
    short answer was then served as complete, priced, and reported
    ``is_truncated=False``. Measured on this tree before the guard existed, and
    a REGRESSION against the non-streaming reader, which failed loudly on the
    same bodies with ``JSONDecodeError``.
    """


_UNRECOGNISED_LINE: _UnrecognisedLine = _UnrecognisedLine()

#: How a stream ENDED. Recorded on the token-telemetry record so the question
#: "does this upstream actually send ``[DONE]``?" is answered from production
#: data rather than from documentation -- it is not measured anywhere in this
#: repository today (see :func:`_reassemble_streamed_completion`).
_STREAM_TERMINATOR_DONE = "done"
_STREAM_TERMINATOR_FINISH_REASON = "finish_reason"
_STREAM_TERMINATOR_ERROR = "error"
_STREAM_TERMINATOR_NONE = "none"
#: The body was not a stream at all and was read as an ordinary completion.
_STREAM_TERMINATOR_NOT_A_STREAM = "not_a_stream"


def _iter_sse_data(chunks: Iterator[bytes]) -> Iterator[str | _UnrecognisedLine]:
    """Yield the ``data:`` payload of each SSE event, in arrival order.

    **Splits on BYTES and decodes whole lines.** That is what makes a multi-byte
    character torn across two ``recv`` calls a non-event, and it is not a
    stylistic preference: measured on CPython 3.12, a frame containing
    ``caf\u00e9 \u2014 \U0001f600`` cut at the em-dash raises
    ``UnicodeDecodeError`` on BOTH halves when each chunk is decoded as it
    arrives. ``UnicodeDecodeError`` is in :data:`_EXPECTED_TRANSPORT_ERRORS`,
    so a complete, healthy, fully PAID answer would have been logged at WARNING
    and thrown away. Every UTF-8 continuation byte is ``>= 0x80``, so ``0x0A``
    appears only as a real line break and splitting before decoding is safe.

    Framing follows the SSE specification rather than "one line, one event":
    ``data:`` values accumulate and are dispatched at a BLANK line, joined with
    ``\n``. A byte-counting reader is what tears frames -- measured, a 68-byte
    frame cut at byte 40 yields one ``JSONDecodeError`` and zero events -- so
    the unterminated tail is carried across chunks and only a complete line is
    ever parsed.

    Anything left pending at end of stream is dispatched, because a server that
    omits the final blank line has still delivered the frame.

    **Known limit, stated rather than silently absent:** a stream separated by
    BARE ``\r`` (which the specification permits and no observed
    OpenAI-compatible endpoint uses) parses as zero events. That fails to the
    safe side -- no terminator is seen, so
    :func:`_reassemble_streamed_completion` reports the stream incomplete and
    the call is classified ``_DISPATCH_UNMEASURED`` rather than serving a
    fragment as an answer. ``\r\n`` and ``\n`` are both handled.
    """
    buffer = b""
    pending: list[str] = []
    started = False

    def _data_value(raw_line: bytes) -> str | _UnrecognisedLine | None:
        """The ``data:`` value on one line, or a marker for anything else.

        Three outcomes, and the third is the one that matters:

        * a ``data:`` value -- the frame;
        * ``None`` for a line we KNOW carries no completion data: a comment
          (a line beginning ``:``, which is what OpenRouter sends as a
          keep-alive -- 1, 16, 16 and 21 of them across four measured streamed
          calls, with no fixed cadence) or one of
          :data:`_SSE_IGNORED_FIELDS`. These are discarded at READ time, so a
          well-formed keep-alive flood does not accumulate;
        * :data:`_UNRECOGNISED_LINE` for anything else.

        **The specification says to ignore an unknown field. This does not**,
        and the difference is a measured defect rather than pedantry. A leading
        byte-order mark, one stray leading space, or ``Data:`` with a capital D
        all make a real frame fail the ``data:`` test; ignoring it dropped that
        frame in silence, and the shortened answer was then served as complete,
        priced, and reported ``is_truncated=False``. The non-streaming reader
        this replaced failed LOUDLY on the same bodies, so ignoring would have
        been a regression in failure posture. We cannot tell a field we do not
        need from a frame we failed to parse, so on a paid path we refuse to
        guess.
        """
        # ``strict`` decoding, matching the whole-body ``.decode()`` this
        # replaced: a body that is not UTF-8 raises here exactly as it did
        # before, rather than being silently mangled. ``errors="replace"``
        # would be worse than the raise -- it corrupts a paid answer's text
        # while every gate stays green.
        line = raw_line.rstrip(b"\r").decode()
        if line.startswith(":") or line.startswith(_SSE_IGNORED_FIELDS):
            return None
        if not line.startswith(_SSE_DATA_FIELD):
            return _UNRECOGNISED_LINE
        value = line[len(_SSE_DATA_FIELD) :]
        # The specification strips ONE optional leading space, not all
        # whitespace -- JSON tolerates the difference, but a sentinel compared
        # with ``==`` does not.
        return value[1:] if value.startswith(" ") else value

    for chunk in chunks:
        buffer += chunk
        if not started:
            # Strip ONE byte-order mark, at the very start of the stream only.
            # Measured: without this, a BOM'd body loses its first frame
            # entirely -- the mark rides on the first ``data:`` line and makes
            # it unrecognisable.
            #
            # **No line is parsed until this decision is made**, and that is
            # what makes the result independent of how the wire split the
            # bytes. Two weaker versions were measured failing that:
            # deciding on the first chunk alone left a BOM delivered in a
            # 1- or 2-byte chunk unstripped, and merely waiting for three
            # bytes still lost when the first chunk was a lone newline --
            # the loop drained the buffer while this flag was still unset, so
            # a LATER chunk's BOM was stripped as though it began the stream.
            # Both made the same bytes classify two different ways, which is
            # the property ``test_the_result_does_not_depend_on_how_the_bytes_
            # were_split`` exists to forbid.
            if len(buffer) < len(_SSE_BOM):
                # Not enough yet to tell. Wait for more rather than guess; the
                # end-of-stream path below handles a body shorter than a mark.
                continue
            started = True
            if buffer.startswith(_SSE_BOM):
                buffer = buffer[len(_SSE_BOM) :]
        while True:
            break_at = buffer.find(b"\n")
            if break_at < 0:
                break
            raw_line, buffer = buffer[:break_at], buffer[break_at + 1 :]
            if not raw_line.rstrip(b"\r"):
                if pending:
                    yield "\n".join(pending)
                    pending = []
                continue
            value = _data_value(raw_line)
            if isinstance(value, _UnrecognisedLine):
                yield value
            elif value is not None:
                pending.append(value)
    if buffer.strip():
        # A final line with NO trailing newline at all. ``strip()`` and not
        # merely truthiness: a trailing bare CR or a single space at end of
        # stream is not a line we failed to read, and treating it as one
        # refused a complete, terminated, usage-bearing answer -- measured. A server may close
        # immediately after writing its last frame, and that frame was still
        # DELIVERED -- dropping it loses whichever frame came last, which is
        # most often the usage frame and therefore the run's ``measured``
        # label. If the residue is instead a TORN line, ``json.loads`` fails on
        # it and the call is classified dispatched-but-unmeasured, which is the
        # honest reading either way.
        value = _data_value(buffer)
        if isinstance(value, _UnrecognisedLine):
            yield value
        elif value is not None:
            pending.append(value)
    if pending:
        yield "\n".join(pending)


@dataclass(frozen=True)
class _StreamedCompletion:
    """One streamed response, folded into the shape the extractors already read.

    ``payload`` is deliberately a completion-shaped mapping rather than a new
    type: ``_extract_message_content``, ``_extract_usage``,
    ``_finish_reason_indicates_truncation`` and ``_extract_citations`` are
    reused UNCHANGED, so streaming cannot make them disagree with the
    non-streamed shape they were written against.

    ``body_error`` carries a frame-level parse failure OUT of the transport
    stage instead of raising it there. That is not tidiness: the transport
    handler and the body handler differ in LOG LEVEL --
    ``_log_post_dispatch_failure`` logs an *expected* class at WARNING and
    anything else at ERROR -- and ``json.JSONDecodeError`` is expected of a
    BODY (``_EXPECTED_BODY_ERRORS``) and not of a transport. Raising it inside
    the ``urlopen`` block would page an operator at ERROR for an ordinary
    upstream hiccup, and would file it in the #105 dataset under the wrong
    event.
    """

    payload: dict[str, object]
    terminator: str
    frame_count: int
    #: Lines that were neither a comment nor a field we know. Any at all means
    #: the stream carried something we could not read, so an answer assembled
    #: from the rest is missing content we cannot account for.
    unrecognised_lines: int
    # ``BaseException`` rather than ``Exception``, matching the declared type of
    # ``_EXPECTED_BODY_ERRORS`` that fills it and of the
    # ``_log_post_dispatch_failure`` that consumes it. Narrowing it here would
    # be a claim about the catch that the catch does not make.
    body_error: BaseException | None


def _reassemble_streamed_completion(
    frames: Iterator[str | _UnrecognisedLine],
) -> _StreamedCompletion:
    """Fold SSE frames into the payload an equivalent non-streamed call returns.

    Each rule below exists because getting it wrong is a defect somebody can
    name, not because it is the obvious way to write a loop.

    * **Only choice index 0 contributes.** Every frame carries an ``index`` and
      everything downstream reads ``choices[0]``, so a stream carrying a second
      choice would otherwise splice its text into the first one undetectably.
      An absent index is treated as 0, which is what a single-choice stream
      sends.
    * **Only ``delta.content`` is text**, whitelisted by name. A reassembler
      that concatenated whatever string a delta carried would prepend
      ``delta.reasoning`` -- chain-of-thought -- onto the answer, and the judge
      asks for ``reasoning`` explicitly while parsing its reply as STRICT JSON
      with no repair. One leaked token there costs a paid call its verdict.
      ``refusal`` and ``tool_calls`` are excluded by the same whitelist.
    * **Usage is taken, never summed and never invented.** The last frame
      carrying a ``usage`` mapping wins, which is correct whether the upstream
      sends one final total (the documented shape) or a running total per
      frame; summing is wrong for both. Fabricating a zero-filled record would
      be far worse than losing it: ``_extract_usage`` accepts
      ``{0, 0, 0}`` as REAL usage, so the run would read ``measured`` at
      $0.00, and a measured receipt is the one thing that overwrites the booked
      charge on both spend rails. Absent usage costs the run its ``measured``
      label, which is the honest direction.
    * **An unclean ``finish_reason`` LATCHES.** A frame reporting ``length``
      followed by a usage frame repeating ``stop`` must stay truncated, or the
      user-visible "(shortened)" marker vanishes from an answer they paid for.
      Otherwise the last non-null value wins, and an absent one stays absent --
      :func:`_finish_reason_indicates_truncation` must never be handed an
      invented reason.
    * **Annotations accumulate in arrival order and are NOT de-duplicated**,
      and ``citations`` is a fallback for ``annotations`` rather than a merge.
      Both rules exist to match ``_extract_citations`` exactly: it dedupes
      nothing, and it reads ``annotations or citations`` -- a short-circuit, so
      a response carrying both yields only the first. An earlier version of
      this function deduplicated and merged, which sounds tidier and silently
      renumbered a user's bibliography relative to the same response delivered
      non-streamed. Dropping the de-duplication also removes a quadratic scan:
      it compared each annotation against a growing list, measured at 10.12s of
      CPU for 20,000 annotations inside a paid call's budget.

    **The terminator is the framing check, and streaming is why it has to
    exist.** ``_iter_body_within_budget`` restores an ``IncompleteRead`` guard
    that ``read1`` had silently dropped -- but that guard reads
    ``HTTPResponse.length``, which is ``None`` under chunked framing, and a
    streamed response is always chunked. So a stream that delivers three of
    forty frames and then closes CLEANLY raises nothing at all: measured on
    loopback, such a response returns its prefix with no exception and
    ``resp.length is None``. Without an application-level terminator that
    prefix is valid JSON, is served as a whole answer, is priced, and reports
    ``is_truncated=False`` -- the exact defect the ``IncompleteRead`` restore
    was written to prevent, reached by a different route.

    Three terminators are accepted, and accepting more than one is deliberate.
    ``data: [DONE]`` is the OpenAI-compatible sentinel but is **not measured
    against this upstream anywhere in this repository** -- requiring it alone
    would risk classifying every healthy call ``_DISPATCH_UNMEASURED``, which
    is rule 8c's failure mirrored. A non-null ``finish_reason`` is the
    upstream's own statement that generation stopped, and a top-level ``error``
    is its documented mid-stream failure marker. Absent all three the stream is
    reported incomplete and the caller classifies it dispatched-but-unmeasured:
    tokens were generated and may well have been billed, and we cannot say what
    arrived.
    """
    text_parts: list[str] = []
    annotations: list[object] = []
    citations: list[object] = []
    finish_reason: object = None
    latched = False
    usage: object = None
    error: object = None
    frame_count = 0
    unrecognised = 0
    terminator = _STREAM_TERMINATOR_NONE
    body_error: BaseException | None = None

    for data in frames:
        if isinstance(data, _UnrecognisedLine):
            unrecognised += 1
            continue
        if data == _SSE_DONE_SENTINEL:
            terminator = _STREAM_TERMINATOR_DONE
            # DRAIN rather than ``break``, and the difference is a real defect
            # caught by a pre-existing test. Breaking here leaves
            # ``_iter_body_within_budget`` suspended mid-generator, so the EOF
            # arm that re-raises ``IncompleteRead`` on a body short of its
            # declared ``Content-Length`` never runs -- and a truncated body
            # whose prefix happened to contain a complete stream was served as
            # a whole answer and priced. That is the guarantee ``read1`` had
            # already dropped once; losing it again by exiting a loop early
            # would be the same defect a third time.
            #
            # Draining ends at the END OF BODY, not the end of the socket: the
            # chunked terminator (or the declared length) is what makes the
            # read return empty, and a well-formed stream sends it immediately
            # after the sentinel. The call budget still bounds the wait, so a
            # server that sends ``[DONE]`` and then falls silent costs the
            # budget rather than hanging for ever.
            #
            # Frames after the sentinel are deliberately consumed WITHOUT being
            # processed: the stream said it was finished, so nothing after it
            # may change the answer, the usage or the finish reason.
            for _ in frames:
                pass
            break
        try:
            frame = json.loads(data)
        except _EXPECTED_BODY_ERRORS as exc:
            body_error = exc
            break
        frame_count += 1
        if not isinstance(frame, dict):
            # A frame that is not a mapping says nothing; it is not an end
            # condition either. Skipping it rather than raising keeps one
            # malformed keep-alive from discarding an otherwise good answer.
            continue
        if isinstance(frame.get("error"), dict):
            error = frame["error"]
            if terminator == _STREAM_TERMINATOR_NONE:
                terminator = _STREAM_TERMINATOR_ERROR
        if isinstance(frame.get("usage"), dict):
            usage = frame["usage"]
        choices = frame.get("choices")
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            index = choice.get("index", 0)
            if index != 0:
                continue
            delta = choice.get("delta")
            if isinstance(delta, dict):
                piece = delta.get("content")
                if isinstance(piece, str):
                    text_parts.append(piece)
                for key, sink in (("annotations", annotations), ("citations", citations)):
                    extra = delta.get(key)
                    if isinstance(extra, list):
                        sink.extend(extra)
            reason = choice.get("finish_reason")
            if isinstance(reason, str) and reason in _UNCLEAN_FINISH_REASONS:
                finish_reason = reason
                latched = True
            elif reason is not None and not latched:
                finish_reason = reason
            if reason is not None and terminator in (
                _STREAM_TERMINATOR_NONE,
                _STREAM_TERMINATOR_ERROR,
            ):
                terminator = _STREAM_TERMINATOR_FINISH_REASON

    message: dict[str, object] = {"content": "".join(text_parts)}
    # ``annotations or citations``, mirroring ``_extract_citations``' own
    # short-circuit rather than merging the two.
    if annotations or citations:
        message["annotations"] = annotations or citations
    choice_zero: dict[str, object] = {"message": message}
    if finish_reason is not None:
        choice_zero["finish_reason"] = finish_reason
    elif error is not None:
        # The documented mid-stream failure frame carries BOTH a top-level
        # ``error`` and ``finish_reason: "error"``. When only the first
        # arrives, say so here rather than letting a broken generation report
        # a clean stop: ``"error"`` is already a member of
        # ``_UNCLEAN_FINISH_REASONS``, so the answer is marked shortened and
        # any usage the provider stated still reaches the receipt.
        choice_zero["finish_reason"] = "error"
    payload: dict[str, object] = {"choices": [choice_zero]}
    if isinstance(usage, dict):
        payload["usage"] = usage
    if error is not None:
        payload["error"] = error
    return _StreamedCompletion(
        payload=payload,
        terminator=terminator,
        frame_count=frame_count,
        unrecognised_lines=unrecognised,
        body_error=body_error,
    )


def _read_within_budget(exc: HTTPError, limit: int, budget: float) -> tuple[bytes, bool]:
    """Read at most ``limit + 1`` bytes in at most ``budget`` seconds TOTAL.

    Returns ``(body, time_bounded)``. Raises only what ``read`` raises.

    **A socket timeout is per-``recv``, not cumulative, and that distinction is
    the whole reason this function exists.** The previous version simply
    lowered the socket timeout once and called ``exc.read(limit + 1)``, which
    loops internally until it has the bytes or hits EOF. Measured against a
    loopback server dribbling 512 bytes every 1.0s — every gap comfortably
    under the 2s cap, so the cap never fired — that took **16.051 seconds**,
    twice the 8.009s of the unbounded version it was introduced to fix, while
    cheerfully reporting ``sniff_time_bounded=True``.

    So the budget is enforced as a DEADLINE across the whole read: before each
    chunk the socket timeout is set to whatever remains, and the loop stops
    when the deadline passes. Worst case is the budget plus at most one
    already-started ``recv`` — and if the socket cannot be reached at all
    (the hop is CPython-implementation-specific), the deadline check between
    chunks still bounds the total.
    """
    deadline = time.monotonic() + budget
    want = limit + 1
    chunks: list[bytes] = []
    got = 0
    bounded = True
    while got < want:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            exc.fp.fp.raw._sock.settimeout(remaining)  # type: ignore[attr-defined]
        except Exception:
            # Cannot reach the socket: the per-chunk read keeps the
            # connection's own timeout, and only the deadline check above
            # bounds us. Say so rather than claim a bound we do not have.
            bounded = False
        size = min(_ERROR_BODY_SNIFF_CHUNK_BYTES, want - got)
        # ``read1`` returns after ONE ``recv`` instead of looping until it has
        # ``size`` bytes, which is what keeps a slow dribble from overrunning
        # the deadline inside a single call. Not every file object has it.
        reader = getattr(exc, "read1", None)
        try:
            chunk = reader(size) if callable(reader) else exc.read(size)
        except Exception:
            # A read that fails after we already have bytes must not throw the
            # evidence away: a partial body still says whether it is JSON and
            # whether it names a provider. With nothing in hand there is
            # nothing to salvage, so the caller's handler reports "unreadable".
            if not chunks:
                raise
            break
        if not isinstance(chunk, bytes):
            # A transport that hands back something other than bytes is
            # BROKEN, not finished. Treating it as EOF would report "empty",
            # which claims the upstream sent an empty body — a different and
            # wrong finding. With nothing in hand, let the caller report
            # "unreadable"; with a partial body, keep it.
            if not chunks:
                raise TypeError(f"read returned {type(chunk).__name__}, not bytes")
            break
        if not chunk:
            break
        chunks.append(chunk)
        got += len(chunk)
    return b"".join(chunks), bounded


def _provider_name_header_present(exc: HTTPError) -> bool | None:
    """Did the response carry OpenRouter's ``X-Provider-Name`` header?

    A second, INDEPENDENT signal for the same question the body answers, found
    by probing the live API: OpenRouter lists ``X-Provider-Name`` in its
    ``Access-Control-Expose-Headers``. A header survives a body that is
    truncated, unreadable or not JSON, so the two together fail independently.
    ``None`` means there were no headers to read at all.
    """
    try:
        headers = exc.headers
        if headers is None:
            return None
        return bool(headers.get("X-Provider-Name"))
    except Exception:
        return None


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
    # ``billing_class`` is a CONSTANT here, and that is the point rather than an
    # oversight. Both callers return ``_DISPATCH_UNMEASURED`` unconditionally,
    # so the record and the return agree by construction; the field exists so
    # the durable billing file can be read without also reading this function.
    # Without it, the two most common dispatched failures were the only ones in
    # the file with no billing verdict on them — and the most expensive live
    # failure mode (a healthy chunked response abandoned by the per-``recv``
    # socket timeout) arrives here, as ``upstream_provider_transport_error``.
    _LOGGER.log(
        logging.WARNING if isinstance(exc, expected) else logging.ERROR,
        event,
        extra={
            "error_type": type(exc).__name__,
            "model_id": model_id,
            "billing_class": "possibly_billed",
        },
    )


#: The character-to-token divisor the telemetry estimate uses. Deliberately a
#: local integer rather than an import of ``costs.CHARS_PER_TOKEN``: providers
#: sits on the paid path and does not import ``costs`` today, and adding that
#: edge for one constant is a poor trade. The two are pinned equal by
#: ``test_the_telemetry_divisor_matches_the_cost_estimators_divisor`` — and
#: they MUST stay equal, because ``injected_tokens_est`` is only meaningful as
#: a comparison against the estimate that constant feeds.
_CHARS_PER_TOKEN_ESTIMATE: int = 4

#: File-only stream for issue #268 (see ``telemetry_sink``). Not ``_LOGGER``:
#: one of these per provider call on the root logger would evict Fly's
#: ~100-line ring. Staying off the root logger does NOT keep them out of
#: Sentry — ``telemetry_sink._configure_token_logger`` calls ``ignore_logger``
#: for that, and its docstring records the measurement.
_TOKEN_LOGGER = logging.getLogger(TOKEN_TELEMETRY_LOGGER)


def _log_call_token_shape(
    *,
    model_id: str,
    messages: list[dict[str, str]],
    max_tokens: int | None,
    usage: TokenUsage | None,
    stream_terminator: str,
) -> None:
    """Record how many INPUT tokens this call carried (issue #268).

    ``config.py`` prices every billed call with two constants —
    ``cost_system_prompt_tokens = 350`` and
    ``cost_web_search_context_tokens = 2000`` — and the comment above them
    grounds BOTH on a single live run (``d7785cd8``). One sample. Issue #268
    already measured that our system prompts are comfortably under 350, so that
    is not the exposure. The exposure is the web-search context: OpenRouter's
    ``:online`` suffix injects retrieved passages upstream, bills them to us as
    input tokens, and nothing of ours bounds or measures them. The cost
    guardrail keys off the estimate, so an under-estimate there is a fail-safe
    hole.

    ``injected_tokens_est`` is the number that settles it: what the provider
    charged as input, minus what we actually sent.

    COUNTS ONLY, NEVER CONTENT. ``messages`` carries the user's question and
    the models' prior answers; only its length ever leaves this frame. Nothing
    here is read by any decision — no classification, default or constant moves
    on account of it. The reading that would justify moving one, and the
    condition for deleting this stream, are in
    ``docs/adr/0031-three-blocked-issues-get-durable-telemetry-not-a-guessed-fix.md``.

    ``usage_absent`` is reported rather than a fabricated ``prompt_tokens: 0``.
    A zero would sit in the distribution and drag every percentile taken from
    it, which is the same reason :func:`_extract_usage` refuses to invent one.

    ``stream_terminator`` does two jobs, both needing production data rather
    than another reading of a vendor page.

    It SEPARATES pre- and post-streaming rows. Every row this stream has
    written so far came from a non-streamed call, and ``injected_tokens_est``
    is ``usage.prompt_tokens`` minus what we sent -- meaningful only if a
    streamed ``prompt_tokens`` counts the same thing. Mixing the two regimes
    into one percentile would quietly corrupt the dataset #268 exists to
    build; this field is what lets a reader split them.

    It also ANSWERS the premise this transport rests on that nobody here has
    measured. ``docs/adr/0078`` and the B3 probe both record "``usage`` arrives
    in the final chunk with no opt-in" under what they settled, but both
    attribute it to OpenRouter's DOCUMENTATION rather than to a probe row, and
    the probe script was not retained -- so it is ASSUMED, not measured.
    Reading ``usage_absent`` against this field over real traffic settles that,
    and settles whether ``[DONE]`` is sent at all, at no cost and with no extra
    instrumentation. Being wrong costs receipts their ``measured`` label, which
    is the safe direction, never a silent overcharge.
    """
    sent_chars = sum(len(str(message.get("content", ""))) for message in messages)
    system_chars = sum(
        len(str(message.get("content", "")))
        for message in messages
        if message.get("role") == "system"
    )
    sent_tokens_est = sent_chars // _CHARS_PER_TOKEN_ESTIMATE
    fields: dict[str, object] = {
        "model_id": model_id,
        # The suffix IS the search flag, as it goes on the wire.
        "search_enabled": model_id.endswith(":online"),
        "max_tokens": max_tokens,
        "system_prompt_chars": system_chars,
        "sent_chars": sent_chars,
        "sent_tokens_est": sent_tokens_est,
        "usage_absent": usage is None,
        "stream_terminator": stream_terminator,
    }
    if usage is not None:
        fields["prompt_tokens"] = usage.prompt_tokens
        fields["completion_tokens"] = usage.completion_tokens
        fields["injected_tokens_est"] = usage.prompt_tokens - sent_tokens_est
    _TOKEN_LOGGER.info("provider_call_tokens", extra=fields)


#: The ``finish_reason`` values that mean the text in hand is NOT the model's
#: complete view of the question. Deliberately a closed set of two, not "any
#: reason other than stop":
#:
#: * ``"length"`` — the token ceiling cut it off. This is what the field was
#:   built for (F-07).
#: * ``"error"`` — the provider broke part-way through. OpenRouter's error
#:   documentation gives this as the marker on a MID-STREAM failure frame,
#:   alongside a top-level ``error`` object. Read 2026-08-26; the STREAMING
#:   half is the vendor's own written contract. Whether a NON-streaming
#:   response ever carries it is a separate question and is **UNVERIFIED** —
#:   settling it needs a paid call to a provider forced to fail mid-generation.
#:   That gap does not weaken the entry: reporting an unclean stop as unclean
#:   is correct whether or not this particular upstream emits it here, and the
#:   opposite error (rule 8c) would be GATING behaviour on an unmeasured
#:   upstream, which this does not do.
#:   What IS measured, 2026-08-26: a body carrying it was previously served
#:   with ``is_truncated=False``, byte-identical in that respect to a healthy
#:   completion.
#:
#: ``"content_filter"`` is deliberately ABSENT. It means the provider refused,
#: which is a different event from running out or breaking, and
#: ``tests/unit/test_providers.py`` pins it as non-truncation on purpose.
#: Widening this set again is a decision, not a tidy-up.
_UNCLEAN_FINISH_REASONS: frozenset[str] = frozenset({"length", "error"})


def _finish_reason_indicates_truncation(payload: object) -> bool:
    """Did the provider stop before it had finished answering?

    Reads ``choices[0].finish_reason`` and reports ``True`` only for the
    values in :data:`_UNCLEAN_FINISH_REASONS`. Every other shape — a payload
    that is not a mapping, a missing/empty/non-list ``choices``, a non-mapping
    element, an absent ``finish_reason``, or any other reason (``"stop"``,
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
    reason = first.get("finish_reason")
    # The ``isinstance`` is not defensive noise, and it is not free: the
    # previous form was ``== "length"``, which is total over every type. A set
    # membership is NOT — ``["length"] in frozenset(...)`` raises
    # ``TypeError: unhashable type: 'list'``. That call sits inside the parsing
    # ``try``, so an upstream sending a LIST finish_reason would have taken a
    # perfectly good, billed, measurable response and downgraded it to
    # ``estimated``. Caught by
    # ``test_malformed_payloads_never_assert_truncation[payload7]``, which is
    # why that test's "finish_reason is a list" row exists.
    if not isinstance(reason, str):
        return False
    return reason in _UNCLEAN_FINISH_REASONS


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

    The two reasons this docstring gave until #285 were both wrong, and
    are recorded here so nobody re-derives them: this app has no hash
    router (``grep -c "location.hash\\|hashchange\\|pushState"
    static/app.js`` -> 0) and mounts no iframe in the workspace it authors
    (``grep -rn iframe static/app.js templates/`` -> no hits; hedged
    deliberately, because ``grep -rl iframe src/`` DOES hit the two vendored
    bundles under ``static/vendor/``); and a fragment cannot smuggle a
    scheme past the check below, because the ``startswith(("http://",
    "https://"))`` gate runs BEFORE the cut. The two reasons that hold:

    1. The sanitized URL is inlined verbatim into PROMPTS — the judge's
       evidence source lines (``evaluation.build_judge_evidence``) and the
       synthesis prompt (``synthesis._flatten_for_prompt``, applied to the
       title and the URL alike). A fragment is provider-chosen text that
       tells the prompt nothing and costs tokens.
    2. ``_extract_citations`` dedups on the sanitized string, so keeping
       fragments would split one page into several bibliography rows and
       inflate the citation-coverage denominator.

    Whichever reason you prefer, the SHAPE is a contract. Issue #285 was
    the evaluation engine comparing citation markers WITHOUT this cut, so a
    marker citing its own source with an anchor matched nothing and was
    scored as an off-run URL. The comparison side folds the same way now —
    ``evaluation._canonical_marker_key`` — and
    ``tests/integration/test_source_url_sanitization.py`` pins the two
    together over the URLs a source row can hold.

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
    # into a prompt it forges its own line, and TWO downstream consumers
    # inline sources this way: the synthesis prompt (``synthesis.py:763-764``)
    # and the judge's evidence block (``evaluation.py:1714-1715``).
    # This said "every downstream consumer (debate, synthesis, the evaluation
    # judge)" until 2026-08-10; ``grep -c "\.url" src/product_app/debate.py``
    # prints 0 — debate only counts ``answer.sources``, it never inlines one.
    # ``urlparse`` strips these for its own host check and then hands the
    # ORIGINAL string back, so the host check passing says nothing about what
    # the rest of the string will do. Reject here, at the producer, rather
    # than flattening at each consumer — two consumers means the next one
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
    if not is_visible(text):
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
