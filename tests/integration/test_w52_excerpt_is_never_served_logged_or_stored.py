"""W52 (ADR-0146 decisions 3-5): the excerpt is kept in memory and nowhere else.

Failure modes covered (``docs/analysis/2026-10-05-w52-search-excerpts-
failure-modes.md``):

* 1 -- served to the page or an API client: the real create and poll routes,
  and the OpenAPI schema, carry no ``excerpt`` and none of its text.
* 2 -- written to a log, telemetry, the run-history store or the account
  history: every log record of a live run, and every row of every SQLite store
  touched, is scanned for the text. Telemetry still records the LENGTH.
* 9 -- a request, a prompt or a price changes: every provider request body of
  a live run is byte-identical whether or not the annotations carry content,
  and a fixed panel's estimate and bound are pinned.

THE PARTNER THAT MAKES THE NEGATIVES MEAN SOMETHING (AGENTS.md rule 7): every
run-driven test first asserts that the in-memory run's sources DO carry the
excerpt. Without that, "the text is nowhere" is trivially true of today's code,
which keeps no excerpt at all -- and that partner is what turns each test red
before W52 is built.

The live path is driven exactly as ``test_f05_terminal_status_not_overwritten``
drives it: live execution on, a fake ``product_app.providers.urlopen`` that
records every request, the cookie session, the real routes. $0, no network.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import yaml
from fastapi.testclient import TestClient
from tests.helpers import isolated_run_semaphore, wait_for_free_permits
from tests.integration.test_google_sign_in import SignIn, _signed_in
from tests.provider_wire import sse_from_completion

from product_app import (
    account_history,
    config,
    feedback_store,
    run_history_store,
    session_store,
    telemetry_sink,
)
from product_app import query_run_orchestration as qro
from product_app.costs import CostEstimate, CostThresholdAction, cost_estimation_service
from product_app.main import app
from product_app.model_slots import (
    DEFAULT_MODEL_IDS,
    validate_model_slots,
    validate_model_slots_with_search,
)
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    SourceReference,
)
from product_app.query_run_orchestration import QueryRunStatus, query_run_repository
from product_app.run_history_store import RunHistoryRow
from product_app.safety import WARNING_VERSION, WarningType
from product_app.session_store import HistoryEntry

ROOT = Path(__file__).resolve().parents[2]

#: The marker searched for everywhere. It survives cleaning unchanged.
_TOKEN = "W52LEAKSENTINEL"
#: What the provider sends: whitespace that the cleaning collapses...
_RAW_CONTENT = f"{_TOKEN}  passage\n about   the cited page " + "q" * 40
#: ...and what the source must hold after cleaning (ADR-0146 decision 2).
_CLEAN_EXCERPT = f"{_TOKEN} passage about the cited page " + "q" * 40
_SOURCE_URL = "https://cited.example/w52-page"
_SOURCE_TITLE = "W52 cited page"

_QUESTION = "compare managed database options for a small team"
WAIT_S = 30.0


# ---------------------------------------------------------------------------
# The live-run harness.
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _completion_body(*, with_content: bool) -> bytes:
    citation: dict[str, Any] = {"url": _SOURCE_URL, "title": _SOURCE_TITLE}
    if with_content:
        citation["content"] = _RAW_CONTENT
    return sse_from_completion(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "A live answer that cites the page [1].",
                        "annotations": [{"type": "url_citation", "url_citation": citation}],
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }
    )


class _Collector(logging.Handler):
    """Every record from the root logger AND the file-only token logger (which
    does not propagate, so ``caplog`` alone would miss it)."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            self.records.append(record)


@pytest.fixture
def collector() -> Iterator[_Collector]:
    handler = _Collector()
    loggers = [logging.getLogger(), logging.getLogger(telemetry_sink.TOKEN_TELEMETRY_LOGGER)]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        for logger, level in zip(loggers, levels, strict=True):
            logger.removeHandler(handler)
            logger.setLevel(level)


@dataclass
class _LiveRun:
    query_run_id: UUID
    created_json: dict[str, Any]
    result_json: dict[str, Any]
    requests: list[tuple[str, bytes]] = field(default_factory=list)


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True)
    monkeypatch.setattr(config.settings, "openrouter_api_key", "sk-or-test-w52")
    monkeypatch.setattr(config.settings, "stage_delay_ms", 0)
    monkeypatch.setattr(config.settings, "tavily_api_key", "")
    monkeypatch.setattr(config.settings, "quorum_source_fetch_max_text_chars", 4000)


def _drive(monkeypatch: pytest.MonkeyPatch, client: TestClient, *, with_content: bool) -> _LiveRun:
    body = _completion_body(with_content=with_content)
    requests: list[tuple[str, bytes]] = []
    lock = threading.Lock()

    def fake_urlopen(request: Any, timeout: float = 0) -> _FakeResponse:
        with lock:
            requests.append((request.full_url, bytes(request.data or b"")))
        return _FakeResponse(body)

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)
    with isolated_run_semaphore(1) as semaphore:
        csrf = client.get("/v1/session").json()["csrf_token"]
        created = client.post(
            "/v1/query-runs",
            json={
                "query_text": _QUESTION,
                "model_slots": DEFAULT_MODEL_IDS,
                "safety_acknowledgements": [
                    {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
                    {"warning_type": WarningType.HIGH_STAKES, "version": WARNING_VERSION},
                ],
            },
            headers={"x-csrf-token": csrf},
        )
        assert created.status_code == 202, created.text
        query_run_id = UUID(created.json()["query_run_id"])
        assert wait_for_free_permits(semaphore, 1, timeout_s=WAIT_S) == 1
    polled = client.get(f"/v1/query-runs/{query_run_id}")
    assert polled.status_code == 200, polled.text
    return _LiveRun(query_run_id, created.json(), polled.json(), requests)


def _assert_kept_in_memory(run: _LiveRun) -> None:
    """THE POSITIVE PARTNER. RED before W52: the in-memory run's sources keep
    no excerpt."""
    query_run = query_run_repository.get(run.query_run_id)
    assert query_run.status == QueryRunStatus.COMPLETED, query_run.status
    sources = [s for answer in query_run.initial_answers for s in answer.sources]
    assert [s.url for s in sources] == [_SOURCE_URL] * 4, [s.url for s in sources]
    assert [getattr(s, "excerpt", "<no excerpt attribute>") for s in sources] == [
        _CLEAN_EXCERPT
    ] * 4


def _dicts(value: object) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _dicts(child)


def _keys(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _keys(child)


# ---------------------------------------------------------------------------
# Failure mode 1: never served.
# ---------------------------------------------------------------------------


def test_the_excerpt_is_kept_for_the_run_and_never_served(
    monkeypatch: pytest.MonkeyPatch, live: None
) -> None:
    """RED IF: the in-memory run does not keep the excerpt (partner), or the
    create or poll response carries an ``excerpt`` key at ANY depth or any of
    the excerpt's text."""
    run = _drive(monkeypatch, TestClient(app), with_content=True)
    _assert_kept_in_memory(run)

    for name, served in (("create", run.created_json), ("poll", run.result_json)):
        assert "excerpt" not in set(_keys(served)), f"{name} response serves an excerpt key"
        assert _TOKEN not in json.dumps(served), f"{name} response serves the excerpt text"
    # Partner: the sources ARE served, so the absence above is about the
    # excerpt, not about an empty result.
    served_sources = [d for d in _dicts(run.result_json) if "url" in d and "is_fallback" in d]
    assert [s["url"] for s in served_sources].count(_SOURCE_URL) >= 4, served_sources
    for source in served_sources:
        assert set(source) == {"title", "url", "provider", "is_fallback"}, source


def _schemas(document: dict[str, Any]) -> dict[str, Any]:
    return dict(document.get("components", {}).get("schemas", {}))


def _properties_named_excerpt(value: object, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        props = value.get("properties")
        if isinstance(props, dict) and "excerpt" in props:
            found.append(path)
        for key, child in value.items():
            found += _properties_named_excerpt(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found += _properties_named_excerpt(child, f"{path}[{index}]")
    return found


def test_the_openapi_schema_has_no_excerpt() -> None:
    """ADR-0146 decision 3: excluded from the OpenAPI schema too.

    RED IF: SourceReference has no ``excerpt`` field (partner), or the
    fresh ``app.openapi()`` -- or the committed ``openapi.yaml``, which
    ``make openapi-check`` holds equal to it -- shows an ``excerpt`` property
    anywhere."""
    assert "excerpt" in SourceReference.model_fields, sorted(SourceReference.model_fields)

    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from export_openapi import load_openapi_schema

    fresh = load_openapi_schema()
    committed = yaml.safe_load((ROOT / "openapi.yaml").read_text(encoding="utf-8"))
    for name, document in (("app.openapi()", fresh), ("openapi.yaml", committed)):
        source_schemas = {
            key: schema
            for key, schema in _schemas(document).items()
            if key.startswith("SourceReference")
        }
        # Partner: the schema IS published, with its served fields.
        assert source_schemas, f"{name}: no SourceReference schema at all"
        for schema in source_schemas.values():
            assert {"title", "url", "provider", "is_fallback"} <= set(schema["properties"])
        assert _properties_named_excerpt(document) == [], name


# ---------------------------------------------------------------------------
# Failure mode 2: never logged, never stored.
# ---------------------------------------------------------------------------


def _serialise(record: logging.LogRecord) -> str:
    return record.getMessage() + json.dumps(record.__dict__, default=repr)


def test_the_excerpt_is_never_logged_and_its_length_still_is(
    monkeypatch: pytest.MonkeyPatch, live: None, collector: _Collector
) -> None:
    """RED IF: the run does not keep the excerpt (partner), any log record of
    the run -- root or token telemetry, message or any extra field, nested
    values included -- carries the excerpt text, or the token telemetry stops
    recording ``annotation_content_chars`` for the four answer calls."""
    run = _drive(monkeypatch, TestClient(app), with_content=True)
    _assert_kept_in_memory(run)

    records = list(collector.records)
    leaks = [r.name + ":" + r.getMessage() for r in records if _TOKEN in _serialise(r)]
    assert leaks == []

    # Positive partners: the capture saw this run, and the length IS logged.
    token_records = [
        r.__dict__
        for r in records
        if r.getMessage() == "provider_call_tokens"
        and r.__dict__.get("query_run_id") in (str(run.query_run_id), run.query_run_id)
    ]
    initial = [r for r in token_records if r.get("stage") == "initial_answers"]
    assert len(initial) == 4, [r.get("stage") for r in token_records]
    assert [r.get("annotation_content_chars") for r in initial] == [len(_RAW_CONTENT)] * 4


def _dump(store: object) -> str:
    connection = store._conn  # type: ignore[attr-defined]
    return "\n".join(connection.iterdump())


def test_the_excerpt_is_never_written_to_any_store(
    monkeypatch: pytest.MonkeyPatch, live: None
) -> None:
    """RED IF: the run does not keep the excerpt (partner), or any row of the
    run-history store, the feedback/event store or the session store holds the
    excerpt text after a live run reaches its terminal state."""
    with run_history_store.configure_for_tests() as history:
        run = _drive(monkeypatch, TestClient(app), with_content=True)
        _assert_kept_in_memory(run)

        stores: dict[str, object] = {
            "run_history": history,
            "feedback": feedback_store.get_store(),
        }
        if session_store.get_store() is not None:
            stores["session"] = session_store.get_store()
        dumps = {name: _dump(store) for name, store in stores.items() if store is not None}
        assert set(dumps) >= {"run_history", "feedback"}, set(dumps)
        # Partners: the terminal run really was written to both stores.
        assert str(run.query_run_id) in dumps["run_history"]
        assert str(run.query_run_id) in dumps["feedback"]
        for name, text in dumps.items():
            assert _TOKEN not in text, f"the excerpt text was stored in the {name} store"


@pytest.fixture
def _clean_history() -> Iterator[None]:
    query_run_repository.clear()
    account_history.clear_carried()
    yield
    query_run_repository.clear()
    account_history.clear_carried()


def _answer_with_excerpt() -> InitialModelAnswer:
    return InitialModelAnswer(
        slot_number=1,
        model_id="openai/gpt-4o-mini",
        display_name="GPT-4o mini",
        answer_text="A live answer that cites the page [1].",
        sources=[
            SourceReference(
                title=_SOURCE_TITLE,
                url=_SOURCE_URL,
                provider=ProviderPath.OPENROUTER_SEARCH,
                is_fallback=False,
                excerpt=_CLEAN_EXCERPT,
            )
        ],
        provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
        provider_path=ProviderPath.OPENROUTER_SEARCH,
        status=InitialAnswerStatus.COMPLETED,
        fallback_used=False,
        latency_ms=100,
        citation_coverage=CitationCoverage(
            answer_count=1,
            sourced_answer_count=1,
            sourced_answer_ratio=Decimal("1.00"),
            target_met=True,
        ),
    )


def test_a_signed_in_accounts_history_never_holds_the_excerpt(
    sign_in: SignIn, _clean_history: None
) -> None:
    """The account history (W7) through the one place a finished run is
    recorded, ``_persist_terminal_run``.

    RED IF: the finished run's source does not carry the excerpt (partner),
    the history entry is not written (partner), or the session store -- which
    holds the history -- or the run-history row holds the excerpt text."""
    client = sign_in.client()
    assert _signed_in(client).status_code == 303
    (row,) = sign_in.account_rows()
    account = UUID(row["account_id"])

    with run_history_store.configure_for_tests() as history:
        query_run = query_run_repository.create(
            account_id=account,
            query_text=_QUESTION,
            model_slots=validate_model_slots_with_search(list(DEFAULT_MODEL_IDS)[:2], mode="panel"),
            cost_estimate=CostEstimate(
                estimated_cost_usd=Decimal("0.0300"),
                threshold_action=CostThresholdAction.ALLOW,
                confirmation_token=None,
                reasons=[],
            ),
        )
        query_run_repository.record_initial_answer(query_run.query_run_id, _answer_with_excerpt())
        query_run_repository.update_status(
            query_run.query_run_id, status_value=QueryRunStatus.COMPLETED
        )
        qro._persist_terminal_run(query_run.query_run_id)

        kept = query_run_repository.get(query_run.query_run_id).initial_answers[0].sources[0]
        assert getattr(kept, "excerpt", "<no excerpt attribute>") == _CLEAN_EXCERPT
        entries = account_history.history_for(account) or []
        assert [entry.question for entry in entries] == [_QUESTION]
        # No store gains a field (ADR-0146 decision 4).
        assert "excerpt" not in {f.name for f in dataclasses.fields(HistoryEntry)}
        assert "excerpt" not in {f.name for f in dataclasses.fields(RunHistoryRow)}
        assert _TOKEN not in _dump(sign_in.store)
        history_dump = _dump(history)
        assert str(query_run.query_run_id) in history_dump
        assert _TOKEN not in history_dump


# ---------------------------------------------------------------------------
# Failure mode 9: no request, prompt or price change.
# ---------------------------------------------------------------------------


def test_every_provider_request_is_identical_with_or_without_excerpts(
    monkeypatch: pytest.MonkeyPatch, live: None
) -> None:
    """Two live runs of the same question: one whose annotations carry
    content, one whose do not. Every request body the provider double
    records -- answers, debate, synthesis -- must be byte-identical.

    RED IF: the run does not keep the excerpt (partner), or the excerpt text
    reaches ANY provider request (a prompt, the debate, the synthesis), or the
    two runs send different requests in any byte."""
    client = TestClient(app)
    with_content = _drive(monkeypatch, client, with_content=True)
    _assert_kept_in_memory(with_content)
    without_content = _drive(monkeypatch, client, with_content=False)

    assert not any(_TOKEN.encode() in body for _, body in with_content.requests)
    # Partners: a full run's requests were recorded, and the cited page's
    # address reaches later prompts, so the comparison covers prompts that
    # DO read the sources.
    assert len(with_content.requests) >= 10, len(with_content.requests)
    assert any(_SOURCE_URL.encode() in body for _, body in with_content.requests[4:])
    assert sorted(with_content.requests) == sorted(without_content.requests)


def test_a_fixed_panels_estimate_and_bound_are_unchanged() -> None:
    """The price of a fixed panel, recorded on the pre-W52 tree (24e3099 +
    the W52 docs commits) by this exact call. W52 changes no price.

    RED IF: the estimate or its "up to" bound for this panel moves."""
    estimate = cost_estimation_service.estimate(
        query_text=_QUESTION,
        model_slots=validate_model_slots(list(DEFAULT_MODEL_IDS)),
    )
    assert (estimate.estimated_cost_usd, estimate.max_cost_usd) == (
        Decimal("0.1053"),
        Decimal("0.1593"),
    )
