"""Durable, bounded sinks for the telemetry that unblocks #105, #268 and #203.

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
The two streams have different volumes and different value. #105/#203 records
are rare and precious. #268's record fires on every successful provider call,
roughly a dozen per run. On one shared file the high-volume stream would rotate
the rare one out of existence — the defect
``test_a_token_burst_cannot_evict_a_billing_record`` exists to prevent.

WHAT TURNS EACH TEST RED
------------------------
Named in each test's own docstring. The file-level answer: delete
``install_telemetry_sinks`` and every test here fails.

NO CLASSIFICATION IS CHANGED BY ANY OF THIS. ``_UNBILLED_HTTP_STATUSES``,
``_CREDENTIAL_REFUSED_STATUSES`` and the readiness verdict are byte-identical;
this package ships measurement, not a fix.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from email.message import Message
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError

import pytest

from product_app import config, readiness, telemetry_sink
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


def _drive_key_probe(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> str:
    """Drive the REAL readiness key probe into ``exc`` and return its verdict."""
    _live(monkeypatch)
    monkeypatch.setattr(config.settings, "openrouter_api_key", "sk-or-test", raising=False)

    def transport(*, url: str, api_key: str, timeout: float) -> int:
        raise exc

    return readiness.probe_key_auth(transport=transport)


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


def test_every_field_the_three_streams_actually_emit_is_declared(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED WHEN: a field is added to a record without declaring it.

    The registry the test above reads is only worth something if it matches
    what the code emits. This is the other direction, and it collects the names
    by DRIVING all four record types rather than by reading a second list —
    a hand-written list would agree with itself forever.
    """
    seen: set[str] = set()
    with caplog.at_level(logging.DEBUG):
        _drive_provider_error(monkeypatch, _http_error(503, _ROUTER_REFUSAL_BODY))
        _drive_provider_error(monkeypatch, URLError(reason=TimeoutError()))
        _drive_successful_call(monkeypatch, model_id=f"{_MODEL_ID}:online")
        _drive_key_probe(monkeypatch, _http_error(403, b"<html>denied</html>"))
        for record in caplog.records:
            if record.msg in telemetry_sink.BILLING_EVENTS:
                seen |= _custom_fields(record)
    token_logger = logging.getLogger(telemetry_sink.TOKEN_TELEMETRY_LOGGER)
    captured: list[logging.LogRecord] = []
    token_logger.addHandler(_Collector(captured))
    try:
        _drive_successful_call(monkeypatch, model_id=f"{_MODEL_ID}:online")
    finally:
        token_logger.handlers = [h for h in token_logger.handlers if not isinstance(h, _Collector)]
    for record in captured:
        seen |= _custom_fields(record)

    assert len(seen) >= 15, f"only {len(seen)} field names were collected; the drivers went quiet"
    undeclared = sorted(seen - telemetry_sink.TELEMETRY_FIELD_NAMES)
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


def test_the_403_probe_record_reaches_the_same_durable_billing_file(
    monkeypatch: pytest.MonkeyPatch, sink_dir: Path
) -> None:
    """RED WHEN: ``key_probe_credential_refused`` leaves the sink's allowlist."""
    _drive_key_probe(monkeypatch, _http_error(403, b"<html>denied</html>"))
    lines = _billing_lines(sink_dir)
    assert len(lines) == 1, f"expected exactly 1 billing record, got {len(lines)}"
    assert lines[0]["message"] == "key_probe_credential_refused"
    assert lines[0]["status_code"] == 403


def test_an_unrelated_warning_does_not_reach_the_billing_file(sink_dir: Path) -> None:
    """RED WHEN: the sink's filter is removed and it takes the whole root logger.

    The positive partner is the test above: the allowlisted event DOES land.
    Without this one, "the billing file is small" would be satisfied by a sink
    that swallowed everything into a 5 MiB ring nobody could read.
    """
    noisy = logging.getLogger("product_app.somewhere")
    noisy.setLevel(logging.WARNING)
    noisy.warning("an_unrelated_event")
    assert _billing_lines(sink_dir) == []


def test_the_token_record_reaches_the_tokens_file_and_not_the_root_logger(
    monkeypatch: pytest.MonkeyPatch, sink_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """RED WHEN: ``propagate=False`` is dropped, or the record is re-routed.

    ~12 token records per run on the root logger would evict Fly's ~100-line
    ring in seconds AND become Sentry breadcrumbs (``LoggingIntegration`` is
    default-on; ``main.py`` passes no ``integrations=``). The tokens stream is
    file-only for both reasons.
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
    """RED WHEN: the env var is renamed, or aimed off the mounted volume.

    Without this the sink is wired, tested and switched OFF in the one
    deployment whose data the three issues are waiting for. ``/data`` is the
    Fly volume ``fly.toml``'s ``[[mounts]]`` block mounts; the ephemeral rootfs
    is wiped on every deploy (issue #27 learned that the expensive way).
    """
    fly_toml = Path(__file__).resolve().parents[2] / "fly.toml"
    text = fly_toml.read_text(encoding="utf-8")
    assert 'destination = "/data"' in text, "the mount this sink depends on moved"
    assert f'{telemetry_sink.TELEMETRY_DIR_ENV_VAR} = "/data"' in text, (
        f"fly.toml does not set {telemetry_sink.TELEMETRY_DIR_ENV_VAR} to the "
        f"mounted volume, so production collects nothing"
    )


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

    No test anywhere else in this repo asserts that a credential is absent from
    a LOG RECORD: ``tests/security/test_release_security_redaction.py`` covers
    HTTP responses and in-memory recorders only.
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
