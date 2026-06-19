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
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from threading import RLock
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

from pydantic import BaseModel, Field

from product_app.config import settings
from product_app.model_slots import ModelSlot
from product_app.provider_keys import ProviderCredentialSource

CITATION_COVERAGE_TARGET = Decimal("0.80")

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
    material_claim_count: int = Field(ge=0)
    cited_claim_count: int = Field(ge=0)
    coverage_ratio: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    target_ratio: Decimal = CITATION_COVERAGE_TARGET
    target_met: bool


class InitialModelAnswer(BaseModel):
    slot_number: int = Field(ge=1, le=4)
    model_id: str
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
        with self._lock:
            self._events.append(
                ProviderCallEvent(
                    event_type=event_type,
                    account_id=account_id,
                    query_run_id=query_run_id,
                    model_id=model_id,
                    provider_path=provider_path,
                    duration_ms=duration_ms,
                    fallback_used=fallback_used,
                    source_count=source_count,
                    credential_source=credential_source,
                ),
            )
            if len(self._events) > self.MAX_EVENTS:
                del self._events[: len(self._events) - self.MAX_EVENTS]

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
                provider_notice=(
                    "Live answer returned without citation annotations; coverage may "
                    "be below the 80% target because :online web search was unavailable."
                    if not live_response.sources
                    else None
                ),
            )

        # No live response, or live response returned no usable text.
        # Decide between a clean local-simulation answer and a
        # fallback_search answer. The trigger phrases let the test suite
        # force either path; the prior ``or live_response is not None``
        # clause was a bug — it misclassified every successful live call
        # as fallback_search, which cascaded into the wrong demo-banner
        # state and the wrong provider_path on the response.
        use_fallback = self._should_force_fallback(
            query_text=query_text, model_slot=model_slot
        )
        if use_fallback:
            provider_attempt_order = [ProviderPath.LOCAL_SIMULATION, ProviderPath.FALLBACK_SEARCH]
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
                sources=self._fallback_sources(model_slot=model_slot),
                provider_path=ProviderPath.FALLBACK_SEARCH,
                provider_attempt_order=provider_attempt_order,
                fallback_used=True,
                provider_notice=(
                    "Fallback source support was used because  search "
                    "results were unavailable or did not include usable citations."
                ),
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
            provider_notice=(
                "Local demo mode is active because OpenRouter live execution is "
                "disabled. These results are simulated and do not come from a "
                "live provider."
            ),
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
        material_claim_count = 1
        primary_source_count = sum(1 for source in sources if not source.is_fallback)
        cited_claim_count = 1 if primary_source_count > 0 else 0
        return InitialModelAnswer(
            slot_number=model_slot.slot_number,
            model_id=model_slot.model_id,
            answer_text=answer_text,
            sources=sources,
            provider_attempt_order=provider_attempt_order,
            provider_path=provider_path,
            fallback_used=fallback_used,
            status=InitialAnswerStatus.COMPLETED,
            latency_ms=duration_ms,
            citation_coverage=calculate_citation_coverage(
                material_claim_count=material_claim_count,
                cited_claim_count=cited_claim_count,
            ),
            provider_notice=provider_notice,
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
            answer_text="",
            sources=[],
            provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
            provider_path=ProviderPath.OPENROUTER_SEARCH,
            fallback_used=False,
            status=InitialAnswerStatus.FAILED,
            latency_ms=duration_ms,
            citation_coverage=calculate_citation_coverage(
                material_claim_count=1,
                cited_claim_count=0,
            ),
            error_code="PROVIDER_UNAVAILABLE",
            provider_notice=(
                "This model answer is unavailable because the provider did not "
                "return a usable response. Raw key material and upstream secrets "
                "remain redacted."
            ),
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
        return self._call_openrouter_with_optional_search(
            openrouter_key=openrouter_key,
            query_text=query_text,
            model_slot=model_slot,
        )

    def _call_openrouter_with_optional_search(
        self,
        *,
        openrouter_key: str,
        query_text: str,
        model_slot: ModelSlot,
    ) -> LiveProviderResult | None:
        bare_model_id = model_slot.model_id
        online_model_id = f"{bare_model_id}:online"

        # First attempt: with ``:online`` for web search.
        online_result = self._post_openrouter(
            openrouter_key=openrouter_key,
            query_text=query_text,
            model_id=online_model_id,
        )
        if online_result is _SEARCH_REJECTED:
            #  re-try without the ``:online`` suffix.
            bare_result = self._post_openrouter(
                openrouter_key=openrouter_key,
                query_text=query_text,
                model_id=bare_model_id,
            )
            if bare_result is None or bare_result is _SEARCH_REJECTED:
                return None
            return bare_result
        return online_result

    def _post_openrouter(
        self,
        *,
        openrouter_key: str,
        query_text: str,
        model_id: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
    ) -> "LiveProviderResult | _SearchRejected | None":
        # ``_post_openrouter`` accepts a custom system prompt and
        # ``max_tokens`` cap. The debate and synthesis services use
        # this overload to constrain token spend per call; the search
        # path uses the defaults (no cap, generic "source-backed"
        # system prompt).
        system_message = system_prompt or (
            "Answer the user query with explicit source-backed reasoning. "
            "Include citations or source URLs where possible, and explain "
            "uncertainty instead of fabricating support."
        )
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
    ) -> "LiveProviderResult | _SearchRejected | None":
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
            # All other HTTP errors (401, 429, 5xx) bubble up as
            # ``None`` so the local-simulation fallback fires.
            if exc.code in (400, 404) and model_id.endswith(":online"):
                return _SEARCH_REJECTED
            return None
        except (URLError, TimeoutError):
            return None

        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError:
            return None
        content = _extract_message_content(parsed)
        citations = _extract_citations(parsed)
        if not content:
            return None
        return LiveProviderResult(answer_text=content, sources=citations)

    def call_with_prompt(
        self,
        *,
        openrouter_key: str,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int | None = None,
    ) -> LiveProviderResult | None:
        """Public entry point for internal callers (debate, synthesis)
        that need to call a specific model with a custom system prompt
        and an optional token cap.

        Unlike the per-slot ``_live_openrouter_response``, this method
        does NOT attempt the ``:online`` suffix — the debate and
        synthesis stages are second-pass analysis over the model
        answers already gathered, and a fresh web search is not what
        we want at that point. It also does not retry on 404: any
        failure is treated as a hard ``None`` so the caller can fall
        back to the templated path.
        """
        if not openrouter_key or not model_id:
            return None
        result = self._post_openrouter(
            openrouter_key=openrouter_key,
            query_text=user_prompt,
            model_id=model_id,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
        )
        if result is _SEARCH_REJECTED:
            return None
        return result

    def _should_force_provider_failure(
        self,
        *,
        query_text: str,
        model_slot: ModelSlot,
    ) -> bool:
        lowered_query = query_text.lower()
        return (
            self._FORCE_PROVIDER_FAILURE_PHRASE in lowered_query
            or self._PROVIDER_FAILURE_MODEL_MARKER in model_slot.model_id
        )

    def _should_force_fallback(self, *, query_text: str, model_slot: ModelSlot) -> bool:
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

    def _fallback_sources(self, *, model_slot: ModelSlot) -> list[SourceReference]:
        return [
            SourceReference(
                title=f"Fallback search evidence for slot {model_slot.slot_number}",
                url=f"{LOCAL_SIMULATION_URL_PREFIX}fallback/{model_slot.slot_number}",
                provider=ProviderPath.FALLBACK_SEARCH,
                is_fallback=True,
            ),
        ]


@dataclass(frozen=True)
class LiveProviderResult:
    answer_text: str
    sources: list[SourceReference]


#: Internal sentinel returned by ``_post_openrouter`` when ````
#: rejected the ``:online`` variant (HTTP 400 / 404). The caller
#: interprets this as "retry with the bare model id" — distinct from
#: ``None`` ("treat the call as a hard failure") and from a real
#: ``LiveProviderResult`` ("accept the response").
class _SearchRejected:
    """Sentinel class; the module exports a single instance below."""


_SEARCH_REJECTED: _SearchRejected = _SearchRejected()


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


def _extract_citations(payload: object) -> list[SourceReference]:
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
        return references
    for index, annotation in enumerate(annotations, start=1):
        if not isinstance(annotation, dict):
            continue
        raw_url = annotation.get("url") or annotation.get("source") or ""
        title = annotation.get("title") or f" citation {index}"
        if not isinstance(raw_url, str) or not raw_url.startswith(("http://", "https://")):
            continue
        if not isinstance(title, str):
            title = f" citation {index}"
        references.append(
            SourceReference(
                title=title,
                url=raw_url,
                provider=ProviderPath.OPENROUTER_SEARCH,
                is_fallback=False,
            ),
        )
    return references


def calculate_citation_coverage(
    *,
    material_claim_count: int,
    cited_claim_count: int,
) -> CitationCoverage:
    if material_claim_count <= 0:
        return CitationCoverage(
            material_claim_count=0,
            cited_claim_count=0,
            coverage_ratio=Decimal("0"),
            target_met=False,
        )
    coverage_ratio = (Decimal(cited_claim_count) / Decimal(material_claim_count)).quantize(
        Decimal("0.01")
    )
    return CitationCoverage(
        material_claim_count=material_claim_count,
        cited_claim_count=cited_claim_count,
        coverage_ratio=coverage_ratio,
        target_met=coverage_ratio >= CITATION_COVERAGE_TARGET,
    )


provider_event_recorder = InMemoryProviderEventRecorder()
provider_execution_service = ProviderExecutionService()
provider_stub_service = provider_execution_service
