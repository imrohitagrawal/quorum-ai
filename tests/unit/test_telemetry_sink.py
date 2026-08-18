"""Durable, bounded sinks for the telemetry that unblocks #105 and #268.

(#203 was a third stream until ADR-0054 removed it; the history below still
mentions it because the two-file design was argued when it existed.)

WHY A FILE AT ALL
-----------------
All three issues are blocked on production data that does not exist yet, and
stdout is not a place data exists. Measured on this deployment: ``fly logs
--app quorum-ai --no-tail | wc -l`` returns **100** — Fly keeps a ring of about
that many lines, and no log drain is configured (``docs/adr/0018-*.md`` records
that; ``grep -in drain DEPLOY.md`` → 0 hits). A record written to stdout is
therefore gone in minutes and dies on restart, while #105 needs a week of 5xx
bodies. So the records are ALSO written to JSONL files on the Fly volume
already mounted at ``/data``.

WHY TWO FILES AND NOT ONE
-------------------------
The two streams have different volumes and different value. #105 records
(and, until ADR-0054, #203's)
are rare and precious. #268's record fires on every successful provider call,
roughly a dozen per run. On one shared file the high-volume stream would rotate
the rare one out of existence — the defect
``test_a_token_burst_cannot_evict_a_billing_record`` exists to prevent.

WHAT TURNS EACH TEST RED
------------------------
Named in each test's own docstring. The file-level answer: delete
``install_telemetry_sinks`` and every test here fails.

NO CLASSIFICATION IS CHANGED BY ANY OF THIS. ``_UNBILLED_HTTP_STATUSES`` is
byte-identical; this package ships measurement, not a fix. (#203's
credential-refusal stream was removed on 2026-08-18 — ADR-0054 — and the
readiness verdict was byte-identical across that removal too.)
"""

from __future__ import annotations

import io
import json
import logging
import os
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from email.message import Message
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError

import pytest
import sentry_sdk

from product_app import config, telemetry_sink
from product_app.logging_config import JsonFormatter
from product_app.providers import provider_execution_service

_MODEL_ID = "anthropic/claude-haiku-4.5"

#: A REAL router-refusal envelope. Every error-body test in this file ships a
#: real body on purpose (AGENTS.md rule 8a): the repo's pre-existing
#: ``_http_error`` doubles pass ``fp=None``, and CPython 3.12.13 then returns
#: ``b''`` from ``.read()`` rather than raising — so "the body does not contain
#: X" passes vacuously against an implementation that never reads the body.
_ROUTER_REFUSAL_BODY = json.dumps(
    {"error": {"message": "No allowed providers are available", "code": 503}}
).encode()

#: The leak canary. A provider or proxy error body really can echo the request
#: headers back, and ``Authorization`` is key material.
_LEAKY_BODY = json.dumps(
    {
        "error": {
            "message": "denied",
            "code": 503,
            "metadata": {"raw": "Authorization: Bearer sk-or-v1-DEADBEEFCAFE"},
        }
    }
).encode()


def _headers(**fields: str) -> Message:
    message = Message()
    for key, value in fields.items():
        message[key.replace("_", "-")] = value
    return message


def _http_error(code: int, body: bytes, **headers: str) -> HTTPError:
    """An ``HTTPError`` carrying a REAL, readable body.

    ``body`` is REQUIRED on purpose. The repo already has two helpers of this
    name that default to an unreadable ``fp=None``, and every test that reused
    them measured nothing. This one cannot be called without stating the bytes
    the upstream sent.

    The default headers carry NO ``Content-Length``: the live OpenRouter API is
    behind Cloudflare and answers errors with ``Transfer-Encoding: chunked``
    (AGENTS.md rule 8c).
    """
    return HTTPError(
        url="https://openrouter.ai/api/v1/chat/completions",
        code=code,
        msg="upstream said no",
        hdrs=_headers(Transfer_Encoding="chunked", **headers),
        fp=io.BytesIO(body),
    )


def _completion_body(*, prompt_tokens: int = 900, completion_tokens: int = 120) -> bytes:
    return json.dumps(
        {
            "choices": [{"message": {"role": "assistant", "content": "An answer."}}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
    ).encode()


@pytest.fixture
def sink_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Install both sinks into a temp directory and tear them down after."""
    monkeypatch.setenv(telemetry_sink.TELEMETRY_DIR_ENV_VAR, str(tmp_path))
    assert telemetry_sink.install_telemetry_sinks() is True
    yield tmp_path
    monkeypatch.delenv(telemetry_sink.TELEMETRY_DIR_ENV_VAR, raising=False)
    telemetry_sink.install_telemetry_sinks()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _billing_lines(directory: Path) -> list[dict[str, Any]]:
    return _read_jsonl(directory / telemetry_sink.BILLING_FILE_NAME)


def _token_lines(directory: Path) -> list[dict[str, Any]]:
    return _read_jsonl(directory / telemetry_sink.TOKENS_FILE_NAME)


def _live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)


def _drive_provider_error(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> Any:
    """Drive the REAL provider path into ``exc`` and return what it returned."""
    _live(monkeypatch)

    def fake_urlopen(request: Any, timeout: float = 0) -> Any:
        raise exc

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)
    return provider_execution_service.call_with_prompt(
        openrouter_key="sk-or-test",
        model_id=_MODEL_ID,
        system_prompt="s",
        user_prompt="u",
    )


def _drive_successful_call(monkeypatch: pytest.MonkeyPatch, *, model_id: str = _MODEL_ID) -> Any:
    """Drive the REAL provider success path and return the result."""
    _live(monkeypatch)
    response = MagicMock()
    response.read.return_value = _completion_body()
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("product_app.providers.urlopen", MagicMock(return_value=response))
    return provider_execution_service.call_with_prompt(
        openrouter_key="sk-or-test",
        model_id=model_id,
        system_prompt="s",
        user_prompt="u",
    )


def _custom_fields(record: logging.LogRecord) -> set[str]:
    """The ``extra=`` keys on a record, BEFORE the formatter gets a chance to
    swallow any of them.

    Read from ``record.__dict__`` rather than from the formatted JSON on
    purpose: a field named ``line`` never appears in the output, so a
    formatted-JSON reading would report it as absent and the registry check
    below would not notice it.
    """
    reserved: set[str] = set(JsonFormatter._RESERVED)
    # ``request_id`` is stamped by the record factory; ``message`` and
    # ``asctime`` are stamped by whatever formatter has already run (caplog's
    # handler formats on emit). None of the three can be an ``extra=`` key:
    # ``Logger.makeRecord`` raises ``KeyError`` for ``message``/``asctime``,
    # and the factory refuses to overwrite an existing ``request_id``.
    return {k for k in record.__dict__ if k not in reserved and not k.startswith("_")} - {
        "request_id",
        "message",
        "asctime",
    }


# --- the formatter silently drops some field names ---------------------------


def test_no_telemetry_field_name_is_silently_dropped_by_the_formatter() -> None:
    """RED WHEN: a declared telemetry field is renamed to one the formatter owns.

    ``JsonFormatter.format`` builds ``payload`` first and then folds ``extra``
    in with ``if key in self._RESERVED or key in payload: continue``. So
    ``extra={"line": 7}``, ``{"message": …}``, ``{"module": …}``,
    ``{"function": …}``, ``{"timestamp": …}``, ``{"level": …}`` and
    ``{"logger": …}`` are dropped with no error and no warning — the record
    would look healthy in production and carry nothing.
    """
    assert telemetry_sink.TELEMETRY_FIELD_NAMES, (
        "no telemetry field names were declared — this check refuses to pass "
        "over an empty input (AGENTS.md rule 7)"
    )
    formatter = JsonFormatter()
    sentinel = "SURVIVED-4c1a"

    def _blank() -> logging.LogRecord:
        return logging.LogRecord(
            name="product_app.test",
            level=logging.WARNING,
            pathname=__file__,
            lineno=1,
            msg="probe",
            args=(),
            exc_info=None,
        )

    record = _blank()
    for name in telemetry_sink.TELEMETRY_FIELD_NAMES:
        setattr(record, name, sentinel)
    emitted = json.loads(formatter.format(record))
    dropped = sorted(n for n in telemetry_sink.TELEMETRY_FIELD_NAMES if emitted.get(n) != sentinel)
    assert not dropped, (
        f"{len(dropped)} declared telemetry field(s) never reach the JSON the "
        f"aggregator reads: {', '.join(dropped)}. JsonFormatter owns those keys."
    )

    # POSITIVE PARTNER: prove this check can actually SEE a drop. Without it, a
    # formatter that echoed every attribute would make the assertion above
    # trivially true and the gate would be measuring nothing.
    control = _blank()
    control.line = sentinel
    control.message = sentinel
    swallowed = json.loads(formatter.format(control))
    assert swallowed["line"] == 1, "extra={'line': …} is no longer swallowed"
    assert swallowed["message"] == "probe", "extra={'message': …} is no longer swallowed"


def test_every_field_the_two_streams_actually_emit_is_declared(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED WHEN: a field is added to a record without declaring it.

    The registry the test above reads is only worth something if it matches
    what the code emits. This is the other direction, and it collects the names
    by DRIVING every record type rather than by reading a second list —
    a hand-written list would agree with itself forever.
    """
    billing_seen: set[str] = set()
    with caplog.at_level(logging.DEBUG):
        _drive_provider_error(monkeypatch, _http_error(503, _ROUTER_REFUSAL_BODY))
        _drive_provider_error(monkeypatch, URLError(reason=TimeoutError()))
        _drive_successful_call(monkeypatch, model_id=f"{_MODEL_ID}:online")
        for record in caplog.records:
            if record.msg in telemetry_sink.BILLING_EVENTS:
                billing_seen |= _custom_fields(record)

    # The token drive gets its own LEVEL, not just its own handler, and that is
    # load-bearing. It used to sit outside the ``caplog.at_level`` block above,
    # so the token logger was back at its ambient level and the record was
    # DROPPED before reaching ``_Collector``. Measured 2026-08-10 running this
    # file alone: ``PROBE token effective=30 enabled=False`` — zero #268 fields
    # collected, and the single ``>= 15`` floor was satisfied by the billing
    # names on their own, so the gap was invisible. Both mutations it exists to
    # catch (dropping ``search_enabled`` from the registry; adding an undeclared
    # field to the token record) survived when the file ran alone and went red
    # only on ambient state left by earlier tests.
    token_logger = logging.getLogger(telemetry_sink.TOKEN_TELEMETRY_LOGGER)
    captured: list[logging.LogRecord] = []
    previous_level = token_logger.level
    token_logger.setLevel(logging.DEBUG)
    token_logger.addHandler(_Collector(captured))
    try:
        _drive_successful_call(monkeypatch, model_id=f"{_MODEL_ID}:online")
    finally:
        token_logger.handlers = [h for h in token_logger.handlers if not isinstance(h, _Collector)]
        token_logger.setLevel(previous_level)
    token_seen: set[str] = set()
    for record in captured:
        token_seen |= _custom_fields(record)

    # TWO floors, not one. A single total let the billing stream cover for a
    # token stream that emitted nothing at all.
    # 11 is the exact number the three billing drivers above emit today,
    # measured 2026-08-18 by running this test after #203's credential-refusal
    # driver was removed (ADR-0054): the failure message printed
    # ``only 11 billing field names were collected``. It was 15 while that
    # fourth driver existed. Pinned at the measured value, not below it, so
    # any driver going quiet still trips it.
    assert len(billing_seen) >= 11, (
        f"only {len(billing_seen)} billing field names were collected; the drivers went quiet"
    )
    assert len(token_seen) >= 9, (
        f"only {len(token_seen)} token field names were collected; the #268 "
        f"driver emitted nothing, so this check is measuring the billing stream twice"
    )
    undeclared = sorted((billing_seen | token_seen) - telemetry_sink.TELEMETRY_FIELD_NAMES)
    assert not undeclared, (
        f"field(s) emitted by a telemetry record but not declared in "
        f"TELEMETRY_FIELD_NAMES: {', '.join(undeclared)}"
    )


class _Collector(logging.Handler):
    def __init__(self, into: list[logging.LogRecord]) -> None:
        super().__init__(level=logging.DEBUG)
        self._into = into

    def emit(self, record: logging.LogRecord) -> None:
        self._into.append(record)


# --- routing and bounds ------------------------------------------------------


def test_the_5xx_evidence_record_reaches_the_durable_billing_file(
    monkeypatch: pytest.MonkeyPatch, sink_dir: Path
) -> None:
    """RED WHEN: ``upstream_provider_http_error`` leaves the sink's allowlist.

    Drives the real provider path into a real 503 with a real body, then reads
    the FILE back — not a caplog handler. A record that only exists in memory
    is exactly the thing this package exists to stop shipping.
    """
    # ``call_with_prompt`` maps ``_DISPATCH_UNMEASURED`` to a blank-text marker
    # with ``usage=None`` — "billed, but we cannot measure it". Pinned here so
    # the sink cannot be shown working against a path that stopped behaving.
    result = _drive_provider_error(monkeypatch, _http_error(503, _ROUTER_REFUSAL_BODY))
    assert result is not None and result.answer_text == "" and result.usage is None
    lines = _billing_lines(sink_dir)
    # CARDINALITY, not presence (AGENTS.md rule 6b): one failed call must
    # produce exactly one billing record, never zero and never a duplicate.
    assert len(lines) == 1, f"expected exactly 1 billing record, got {len(lines)}"
    assert lines[0]["message"] == "upstream_provider_http_error"
    assert lines[0]["status_code"] == 503
    assert lines[0]["provider_name_present"] is False
    assert lines[0]["error_metadata_present"] is False


def test_an_unrelated_warning_does_not_reach_the_billing_file(sink_dir: Path) -> None:
    """RED WHEN: the sink's filter is removed and it takes the whole root logger.

    The positive partner is ``test_the_5xx_evidence_record_reaches_the_durable_billing_file``:
    the allowlisted event DOES land.
    Without this one, "the billing file is small" would be satisfied by a sink
    that swallowed everything into a 5 MiB ring nobody could read.
    """
    noisy = logging.getLogger("product_app.somewhere")
    noisy.setLevel(logging.WARNING)
    noisy.warning("an_unrelated_event")
    assert _billing_lines(sink_dir) == []


def test_the_connect_timeout_evidence_record_reaches_the_durable_billing_file(
    monkeypatch: pytest.MonkeyPatch, sink_dir: Path
) -> None:
    """RED WHEN: ``upstream_provider_opener_error`` leaves the sink's allowlist.

    The third event in ``BILLING_EVENTS`` and the only one nothing covered:
    measured 2026-08-10, deleting it from the allowlist left the whole suite
    green at ``2801 passed``. It is the ``URLError(reason=TimeoutError())``
    branch, which #105 cannot be decided without — a connect timeout
    demonstrably never reached the model, yet ``providers`` classifies it
    ``possibly_billed`` on purpose (the opener does not say which phase timed
    out, and misreading a post-generation timeout as unbilled would understate
    a charge). That conservative call is EXACTLY the premise #105 exists to
    test against production data, so the record has to be durable.

    NO CLASSIFICATION IS ASSERTED AS CORRECT HERE, only recorded as it stands.
    The first draft of this test asserted ``not_billed`` from my own reading of
    the branch and went red against the code — kept as a reminder that the
    conservative call is deliberate, not accidental.

    Both arms are driven so the field cannot be a constant: a connect timeout
    reads ``possibly_billed`` and a refused connection reads ``not_billed``.
    """
    _drive_provider_error(monkeypatch, URLError(reason=TimeoutError()))
    _drive_provider_error(monkeypatch, URLError(reason=ConnectionRefusedError()))
    lines = _billing_lines(sink_dir)
    assert len(lines) == 2, f"expected exactly 2 billing records, got {len(lines)}"
    assert [line["message"] for line in lines] == ["upstream_provider_opener_error"] * 2
    assert [line["error_type"] for line in lines] == ["TimeoutError", "ConnectionRefusedError"]
    assert [line["billing_class"] for line in lines] == ["possibly_billed", "not_billed"]


def test_the_token_stream_survives_an_operator_setting_log_level_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RED WHEN: ``token_logger.setLevel(logging.INFO)`` is deleted from
    ``install_telemetry_sinks``.

    The token record is emitted at INFO on a logger whose own level is NOTSET,
    so without that line ``getEffectiveLevel`` walks to the root and an
    operator setting ``LOG_LEVEL=WARNING`` silently ends #268's collection —
    with a healthy-looking empty file as the only symptom. Latent today
    (``fly.toml`` sets INFO) and untested until now: measured 2026-08-10,
    deleting the line left the whole suite green at ``2801 passed``.

    The token logger's level is reset to NOTSET first ON PURPOSE. A previous
    ``install_telemetry_sinks`` anywhere in the session leaves it at INFO and
    nothing ever puts it back, so without this reset the test would pass under
    the mutation whenever it ran second (AGENTS.md rule 16a).
    """
    token_logger = logging.getLogger(telemetry_sink.TOKEN_TELEMETRY_LOGGER)
    root = logging.getLogger()
    previous_token_level, previous_root_level = token_logger.level, root.level
    token_logger.setLevel(logging.NOTSET)
    root.setLevel(logging.WARNING)
    monkeypatch.setenv(telemetry_sink.TELEMETRY_DIR_ENV_VAR, str(tmp_path))
    try:
        assert telemetry_sink.install_telemetry_sinks() is True
        _drive_successful_call(monkeypatch)
        lines = _token_lines(tmp_path)
    finally:
        token_logger.setLevel(previous_token_level)
        root.setLevel(previous_root_level)
        monkeypatch.delenv(telemetry_sink.TELEMETRY_DIR_ENV_VAR, raising=False)
        telemetry_sink.install_telemetry_sinks()
    assert len(lines) == 1, (
        "the #268 stream went quiet because the root logger was set to WARNING; "
        "the token logger must carry its own level"
    )
    assert lines[0]["message"] == "provider_call_tokens"


def test_an_unhashable_log_message_cannot_break_somebody_elses_logging_call(
    sink_dir: Path,
) -> None:
    """RED WHEN: the allowlist filter stops guarding against ``TypeError``.

    ``_EventAllowlist.filter`` does ``record.msg in frozenset``, and
    ``record.msg`` is whatever the caller passed. A ``dict`` or ``list``
    message is unhashable, so that raises. Handler FILTERS run inside
    ``Handler.handle`` BEFORE ``emit``, so ``handleError`` never sees it and
    the exception comes straight back out of the caller's ``logger.warning``.
    This handler sits on the ROOT logger, which makes "the caller" every
    logging call in the process — and ``install_telemetry_sinks``'s contract
    is that telemetry NEVER reaches a request path.

    No such call site exists in ``src/``, ``scripts/`` or site-packages today
    (AST-scanned), so this is a latent hole, not a live bug. It is still a hole
    in a stated contract.
    """
    caller = logging.getLogger("product_app.somewhere_else")
    caller.setLevel(logging.WARNING)
    for message in ({"a": 1}, ["b"], ("c",), 7):
        caller.warning(message)
    assert _billing_lines(sink_dir) == [], "an unallowlisted message reached the billing file"

    # POSITIVE PARTNER: the filter still ADMITS the real event, so the empty
    # file above is the allowlist working rather than the handler being dead.
    caller.warning("upstream_provider_http_error", extra={"status_code": 503})
    assert [line["message"] for line in _billing_lines(sink_dir)] == [
        "upstream_provider_http_error"
    ]


def test_installing_the_sink_twice_leaves_one_handler_per_stream(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RED WHEN: ``_remove_installed()`` stops removing anything.

    The module docstring advertises the function as idempotent, and nothing
    installed it twice against the same directory. Two handlers on one stream
    would write every record twice — and #268's whole deliverable is a
    distribution, so a silently doubled sample would be read as fact
    (AGENTS.md rule 6b: cardinality, not presence).
    """
    monkeypatch.setenv(telemetry_sink.TELEMETRY_DIR_ENV_VAR, str(tmp_path))
    try:
        assert telemetry_sink.install_telemetry_sinks() is True
        assert telemetry_sink.install_telemetry_sinks() is True
        root_sinks = [
            h
            for h in logging.getLogger().handlers
            if isinstance(h, telemetry_sink._TelemetryFileHandler)
        ]
        token_sinks = [
            h
            for h in logging.getLogger(telemetry_sink.TOKEN_TELEMETRY_LOGGER).handlers
            if isinstance(h, telemetry_sink._TelemetryFileHandler)
        ]
        assert (len(root_sinks), len(token_sinks)) == (1, 1)
        _drive_successful_call(monkeypatch, model_id=_MODEL_ID)
        logging.getLogger("product_app.providers").warning(
            "upstream_provider_http_error", extra={"status_code": 503}
        )
        assert len(_token_lines(tmp_path)) == 1, "the token record was written twice"
        assert len(_billing_lines(tmp_path)) == 1, "the billing record was written twice"
    finally:
        monkeypatch.delenv(telemetry_sink.TELEMETRY_DIR_ENV_VAR, raising=False)
        telemetry_sink.install_telemetry_sinks()


def test_the_token_record_never_becomes_a_sentry_breadcrumb(
    monkeypatch: pytest.MonkeyPatch, sink_dir: Path
) -> None:
    """RED WHEN: ``ignore_logger(TOKEN_TELEMETRY_LOGGER)`` is removed.

    ``propagate=False`` does NOT keep these records out of Sentry, and three
    comments in this package claimed it did until this test was written.
    Sentry's ``LoggingIntegration`` is on by default (``main.py`` passes no
    ``integrations=``) and patches ``Logger.callHandlers``, which runs on the
    ORIGINATING logger — propagation never enters into it. Measured 2026-08-10
    on sentry-sdk 2.63.0 with ``propagate=False`` already set: one breadcrumb
    per record, carrying ``sent_chars`` — the character count of the user's
    question plus the models' prior answers — off to a third party. The
    redaction hooks cannot help: ``before_send`` never sees a breadcrumb, and
    ``grep -n breadcrumb src/product_app/main.py`` returns no hits.
    """
    crumbs: list[dict[str, Any]] = []

    def _record_crumb(crumb: dict[str, Any], _hint: object) -> dict[str, Any]:
        crumbs.append(crumb)
        return crumb

    previous_client = sentry_sdk.get_client()
    try:
        sentry_sdk.init(
            dsn="https://public@example.invalid/1",
            before_breadcrumb=_record_crumb,
            traces_sample_rate=0.0,
        )
        _drive_successful_call(monkeypatch, model_id=f"{_MODEL_ID}:online")
        assert len(_token_lines(sink_dir)) == 1, "the record never reached the sink at all"
        token_crumbs = [
            c for c in crumbs if c.get("category") == telemetry_sink.TOKEN_TELEMETRY_LOGGER
        ]
        assert token_crumbs == [], "a #268 token record became a Sentry breadcrumb"

        # POSITIVE PARTNER: an ordinary logger on this very client DOES produce
        # a breadcrumb, so "zero" above is the ignore-list working and not a
        # capture that was switched off.
        logging.getLogger("product_app.somewhere").warning("an_unrelated_event")
        assert [c["category"] for c in crumbs] == ["product_app.somewhere"]
    finally:
        sentry_sdk.get_global_scope().set_client(previous_client)


def test_the_token_record_reaches_the_tokens_file_and_not_the_root_logger(
    monkeypatch: pytest.MonkeyPatch, sink_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """RED WHEN: ``propagate=False`` is dropped, or the record is re-routed.

    One token record per provider call on the root logger would evict Fly's
    ~100-line ring in seconds. Keeping them off the root logger does NOT keep
    them out of Sentry — that needs ``ignore_logger``, and
    ``test_the_token_record_never_becomes_a_sentry_breadcrumb`` is what pins
    it. This docstring claimed otherwise until that test was written.
    """
    with caplog.at_level(logging.DEBUG):
        _drive_successful_call(monkeypatch, model_id=f"{_MODEL_ID}:online")
        # POSITIVE PARTNER on the same capture: the billing stream still
        # reaches the root logger, so "absent from caplog" below is a property
        # of the routing and not of the capture being switched off.
        _drive_provider_error(monkeypatch, _http_error(503, _ROUTER_REFUSAL_BODY))

    root_events = [r.msg for r in caplog.records]
    assert "provider_call_tokens" not in root_events, (
        "the token record reached the root logger; it would evict Fly's log "
        "ring and become a Sentry breadcrumb"
    )
    assert "upstream_provider_http_error" in root_events

    token_lines = _token_lines(sink_dir)
    assert len(token_lines) == 1, f"expected exactly 1 token record, got {len(token_lines)}"
    assert token_lines[0]["message"] == "provider_call_tokens"
    assert [line["message"] for line in _billing_lines(sink_dir)] == [
        "upstream_provider_http_error"
    ]


def test_both_sinks_are_bounded_by_the_size_they_were_constructed_with(
    sink_dir: Path,
) -> None:
    """RED WHEN: ``maxBytes`` or ``backupCount`` is raised, or rotation dropped.

    Asserts on the ARGUMENTS the handlers were built with, with literals on
    both sides (AGENTS.md rules 7a/8b). Asserting ``handler.maxBytes ==
    telemetry_sink._BILLING_MAX_BYTES`` would survive that constant being
    raised to a gigabyte.
    """
    handlers = telemetry_sink.installed_handlers()
    assert handlers is not None
    billing, tokens = handlers
    assert (billing.maxBytes, billing.backupCount) == (1_048_576, 4)
    assert (tokens.maxBytes, tokens.backupCount) == (4_194_304, 4)
    # ``maxBytes=0`` disables rotation entirely in RotatingFileHandler — the
    # unbounded case wearing the same shape.
    assert billing.maxBytes > 0 and billing.backupCount > 0
    assert tokens.maxBytes > 0 and tokens.backupCount > 0


def test_the_sink_rotates_and_evicts_the_oldest_line_first(sink_dir: Path) -> None:
    """RED WHEN: rotation is dropped (the file grows without bound).

    A size-only assertion would pass over an empty directory, so this asserts
    BOTH that the total stays under the ceiling AND that the newest line is
    still readable while the oldest is gone.
    """
    logger = logging.getLogger(telemetry_sink.TOKEN_TELEMETRY_LOGGER)
    padding = "x" * 8000
    ceiling = 4_194_304 * (4 + 1)
    logger.warning("provider_call_tokens", extra={"model_id": "FIRST-8a20", "sent_chars": 0})
    for _ in range(int(ceiling / 8000) + 600):
        logger.warning("provider_call_tokens", extra={"model_id": padding, "sent_chars": 0})
    logger.warning("provider_call_tokens", extra={"model_id": "LAST-8a20", "sent_chars": 0})

    on_disk = sorted(sink_dir.glob(f"{telemetry_sink.TOKENS_FILE_NAME}*"))
    total = sum(path.stat().st_size for path in on_disk)
    assert total <= ceiling, f"tokens stream grew to {total} bytes, past its {ceiling} ceiling"
    blob = "".join(path.read_text(encoding="utf-8") for path in on_disk)
    assert "LAST-8a20" in blob, "the NEWEST record was evicted — rotation drops the wrong end"
    assert "FIRST-8a20" not in blob, "nothing was evicted, so the ceiling was never reached"


def test_a_token_burst_cannot_evict_a_billing_record(sink_dir: Path) -> None:
    """RED WHEN: both streams are pointed at one file.

    This is the defect the two-file split exists to prevent. #105 needs a week
    of rare 5xx records; #268 writes about a dozen per run. Shared, the second
    erases the first.
    """
    billing_logger = logging.getLogger("product_app.providers")
    billing_logger.setLevel(logging.WARNING)
    billing_logger.warning(
        "upstream_provider_http_error",
        extra={"status_code": 503, "model_id": "PRECIOUS-1f70", "billing_class": "possibly_billed"},
    )
    token_logger = logging.getLogger(telemetry_sink.TOKEN_TELEMETRY_LOGGER)
    padding = "x" * 8000
    for _ in range(int(4_194_304 * 5 / 8000) + 600):
        token_logger.warning("provider_call_tokens", extra={"model_id": padding, "sent_chars": 0})

    survivors = [line for line in _billing_lines(sink_dir) if line["model_id"] == "PRECIOUS-1f70"]
    assert len(survivors) == 1, (
        "the rare billing record did not survive a token burst that rotated "
        "the tokens stream several times over"
    )
    # POSITIVE PARTNER: the burst really did rotate something, so the survival
    # above is not just "nothing was written at all".
    assert (sink_dir / f"{telemetry_sink.TOKENS_FILE_NAME}.1").exists(), (
        "the tokens stream never rotated, so this test proved nothing"
    )


# --- the sink must never be able to break the request path -------------------


def test_an_unusable_telemetry_directory_does_not_break_the_request_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED WHEN: the try/except around sink installation is removed.

    The failure is driven by pointing the sink at a path whose parent is a
    regular FILE, so ``mkdir`` raises whatever the process's privileges are —
    a ``chmod``-based version silently SKIPS when the suite runs as root, which
    is a gate measuring nothing.
    """
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("i am a file", encoding="utf-8")
    monkeypatch.setenv(telemetry_sink.TELEMETRY_DIR_ENV_VAR, str(blocker / "telemetry"))
    with caplog.at_level(logging.DEBUG):
        installed = telemetry_sink.install_telemetry_sinks()
    assert installed is False
    assert [r.msg for r in caplog.records].count("telemetry_sink_unavailable") == 1
    assert telemetry_sink.installed_handlers() is None

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        returned = _drive_provider_error(monkeypatch, _http_error(503, _ROUTER_REFUSAL_BODY))
    assert returned is not None and returned.answer_text == "" and returned.usage is None
    assert [r.msg for r in caplog.records].count("upstream_provider_http_error") == 1


def test_re_running_the_json_logging_setup_does_not_tear_the_sink_down(
    monkeypatch: pytest.MonkeyPatch, sink_dir: Path
) -> None:
    """RED WHEN: ``setup_json_logging`` goes back to an ``isinstance`` test.

    That function removes root handlers whose formatter is a ``JsonFormatter``,
    and the billing sink deliberately WEARS that formatter so the on-disk shape
    equals the stdout shape. A ``RotatingFileHandler`` is a ``StreamHandler``,
    so an ``isinstance`` test there silently removes the durable #105 sink on
    any later call — and the only symptom in production would be an empty file.
    """
    from product_app.logging_config import setup_json_logging

    setup_json_logging("INFO")
    _drive_provider_error(monkeypatch, _http_error(503, _ROUTER_REFUSAL_BODY))
    assert len(_billing_lines(sink_dir)) == 1, (
        "the billing sink stopped receiving after setup_json_logging re-ran"
    )
    # POSITIVE PARTNER: the stdout handler it is supposed to manage really was
    # replaced rather than duplicated, so this is not passing because the
    # function stopped removing anything at all.
    root = logging.getLogger()
    stream_handlers = [h for h in root.handlers if type(h) is logging.StreamHandler]
    assert len(stream_handlers) == 1


def test_no_sink_is_installed_when_the_directory_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED WHEN: the sink starts writing to a default path nobody chose.

    Hermetic by default: an unconfigured deployment (and the whole test suite)
    must write no telemetry files at all. ``fly.toml`` is what turns it on in
    production, and the test below is what keeps that true.
    """
    monkeypatch.delenv(telemetry_sink.TELEMETRY_DIR_ENV_VAR, raising=False)
    assert telemetry_sink.install_telemetry_sinks() is False
    assert telemetry_sink.installed_handlers() is None


def test_fly_toml_points_the_telemetry_sink_at_the_persistent_volume() -> None:
    """RED WHEN: the env var is renamed, aimed off the mounted volume, OR
    commented out.

    Without this the sink is wired, tested and switched OFF in the one
    deployment whose data the three issues are waiting for. ``/data`` is the
    Fly volume ``fly.toml``'s ``[[mounts]]`` block mounts; the ephemeral rootfs
    is wiped on every deploy (issue #27 learned that the expensive way).

    PARSED, not grepped, and that is the whole point of this revision. This
    test asserted ``f'{VAR} = "/data"' in text`` until a reviewer prefixed the
    line with ``#``: the substring survives a comment intact, so the check
    stayed green over EXACTLY the state its own docstring says it exists to
    prevent (measured: ``tomllib`` then parses the value as ``None`` while the
    substring assertion still passes). Same defect on ``destination``.
    ``tomllib`` is stdlib on 3.12.
    """
    fly_toml = Path(__file__).resolve().parents[2] / "fly.toml"
    parsed = tomllib.loads(fly_toml.read_text(encoding="utf-8"))
    mounts = parsed.get("mounts", [])
    assert [m.get("destination") for m in mounts] == ["/data"], (
        "the mount this sink depends on moved, or there is no longer exactly one"
    )
    assert parsed.get("env", {}).get(telemetry_sink.TELEMETRY_DIR_ENV_VAR) == "/data", (
        f"fly.toml does not set {telemetry_sink.TELEMETRY_DIR_ENV_VAR} to the "
        f"mounted volume, so production collects nothing"
    )


def test_importing_the_app_installs_the_sink_at_boot(tmp_path: Path) -> None:
    """RED WHEN: the ``install_telemetry_sinks()`` call is deleted from main.py.

    That single line is what turns this whole package on in production, and it
    was covered by NOTHING. Measured 2026-08-10: commenting it out left the
    entire suite byte-identical at ``2801 passed, 55 skipped``. The fly.toml
    test above proves the variable is SET; nothing proved anything READS it at
    boot, so every gate could stay green while production collected zero bytes
    for all three issues.

    A SUBPROCESS, because ``product_app.main`` is already imported by the time
    this test runs and a plain import would be a silent no-op. Hermetic: the
    child makes no network call, and its only side effect is the
    live-execution-probe warning it prints on stderr.
    """
    repo_root = Path(__file__).resolve().parents[2]
    probe = (
        "import product_app.main\n"
        "from product_app import telemetry_sink\n"
        "print('INSTALLED', telemetry_sink.installed_handlers() is not None)\n"
    )

    def _boot(directory: str | None) -> str:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(repo_root / "src")
        if directory is None:
            env.pop(telemetry_sink.TELEMETRY_DIR_ENV_VAR, None)
        else:
            env[telemetry_sink.TELEMETRY_DIR_ENV_VAR] = directory
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(repo_root),
            timeout=180,
        )
        assert completed.returncode == 0, f"the app failed to import:\n{completed.stderr}"
        return completed.stdout

    configured = tmp_path / "boot"
    assert "INSTALLED True" in _boot(str(configured))
    # Not just the handler object: the files the sink probes for writability
    # exist on disk, so importing the app really did reach the filesystem.
    assert sorted(p.name for p in configured.iterdir()) == [
        telemetry_sink.BILLING_FILE_NAME,
        telemetry_sink.TOKENS_FILE_NAME,
    ]

    # NEGATIVE PARTNER: with the variable unset the same boot installs nothing,
    # so "INSTALLED True" above is a property of the wiring reading the
    # environment and not of a sink that installs itself unconditionally.
    assert "INSTALLED False" in _boot(None)


# --- no credential may reach any record --------------------------------------


def test_no_credential_reaches_any_log_record_or_sink_file(
    monkeypatch: pytest.MonkeyPatch, sink_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """RED WHEN: any call site switches to ``repr(exc)`` or logs body content.

    Two real leak sources, both re-measured on CPython 3.12.13 in this
    worktree:

    * an error body that echoes the request headers back — the ``metadata.raw``
      field of ``_LEAKY_BODY`` carries a whole ``Authorization`` header;
    * ``repr(UnicodeEncodeError)`` out of ``http.client.putheader``, which
      contains the header value in full. ``str(exc)`` does NOT — so ``repr`` is
      banned outright, and ``providers.py``'s own comment that "the payload is
      in the message" is true of ``repr``/``args``/``.object`` and false of
      ``str``.

    What is new here is the SINK FILES, not the log records. An earlier version
    of this docstring claimed no test anywhere else in the repo asserted a
    credential is absent from a log record. That was FALSE — measured with
    ``git show origin/main:tests/unit/test_provider_billing_evidence.py``, line
    503's ``test_opener_failure_never_logs_the_exception_message`` already walks
    ``record.__dict__.values()`` for exactly this, and
    ``test_provider_billing_classification.py:379`` is a second instance. It is
    still true that ``tests/security/test_release_security_redaction.py`` covers
    HTTP responses and in-memory recorders only, and that nothing swept a
    durable telemetry file, which is what the last assertion below adds.
    """
    assert b"sk-or-v1-" in _LEAKY_BODY, "the canary is not in the body; this would prove nothing"
    rendered = ""
    formatter = JsonFormatter()

    with caplog.at_level(logging.DEBUG):
        _drive_provider_error(monkeypatch, _http_error(503, _LEAKY_BODY))
    body_record = next(r for r in caplog.records if r.msg == "upstream_provider_http_error")
    # POSITIVE PARTNER: the body really WAS read and parsed, so the absence
    # below is a property of what we log — not of a code path that never ran.
    assert body_record.__dict__["error_metadata_present"] is True
    assert body_record.__dict__["provider_name_present"] is False
    assert body_record.__dict__["body_shape"] == "json"
    rendered += "".join(formatter.format(r) for r in caplog.records)

    caplog.clear()
    try:
        "Authorization: Bearer sk-or-v1-DEADBEEFCAFE ".encode("latin-1")
    except UnicodeEncodeError as exc:
        header_error = exc
    assert "sk-or-v1-" in repr(header_error), "the canary is not in repr(); this proves nothing"
    with caplog.at_level(logging.DEBUG):
        _drive_provider_error(monkeypatch, header_error)
    transport = next(r for r in caplog.records if r.msg == "upstream_provider_transport_error")
    # POSITIVE PARTNER: the exception really did reach the logging call site.
    assert transport.__dict__["error_type"] == "UnicodeEncodeError"
    rendered += "".join(formatter.format(r) for r in caplog.records)

    rendered += "".join(
        path.read_text(encoding="utf-8") for path in sink_dir.iterdir() if path.is_file()
    )
    assert "sk-or-v1-" not in rendered, "a credential reached a log record or a sink file"
    assert "DEADBEEFCAFE" not in rendered
