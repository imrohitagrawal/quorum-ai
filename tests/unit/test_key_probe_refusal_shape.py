"""Issue #203: capture the SHAPE of a credential refusal on this egress path.

WHAT #203 ASKS, AND WHAT THIS SHIPS
-----------------------------------
``DEPLOY.md`` and ``docs/architecture/50-failure-modes.md`` both already record
the same open question, in the same words: *a network proxy or WAF answering
403 on the app's behalf is indistinguishable from the provider doing so.*

This file ships the CAPTURE ONLY. **No classifier is shipped and none should
be**, because whether anything sits between the Fly runtime and the internet is
a question about infrastructure, not about code: ``fly.toml`` configures
inbound services, a volume and a VM, and nothing under ``docs/``, ``.github/``
or the ``Dockerfile`` describes an outbound path or a proxy variable. It is an
operator question, and the ADR records exactly which four questions to ask.

Two live facts already kill the obvious classifiers, so nobody re-derives them.
Measured against the real API with a bad bearer token (free, no tokens):

* ``server: cloudflare`` and ``cf-ray`` do NOT discriminate — OpenRouter is
  itself behind Cloudflare.
* the genuine OpenRouter 401 is ``application/json``, about 50 bytes, carries
  NO ``error.metadata`` and NO ``Content-Length``, and exposes
  ``X-Generation-Id,X-Provider-Name,cf-ray``.

Whether a genuine OpenRouter **403** looks the same is UNVERIFIED — the
available key answers 401. That is precisely what this capture is for.

WHAT TURNS EACH TEST RED
------------------------
Named per test. The file-level answer: delete the
``key_probe_credential_refused`` emission from ``readiness.probe_key_auth``.
"""

from __future__ import annotations

import io
import json
import logging
from email.message import Message
from typing import Any
from urllib.error import HTTPError

import pytest

from product_app import config, readiness

#: The real OpenRouter refusal envelope, captured from the live API.
_OPENROUTER_401_BODY = json.dumps({"error": {"message": "User not found.", "code": 401}}).encode()

#: What a proxy or WAF denial looks like instead: HTML, not JSON. The header
#: value below is the leak canary — header NAMES are recorded, values never.
_PROXY_HTML_BODY = (
    b"<html><head><title>403 Forbidden</title></head>"
    b"<body><h1>Access denied by policy</h1></body></html>"
)


def _headers(**fields: str) -> Message:
    message = Message()
    for key, value in fields.items():
        message[key.replace("_", "-")] = value
    return message


class _RecordingBody(io.BytesIO):
    """A real readable body that records the size each read ASKED for."""

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.read_sizes: list[int] = []

    def read1(self, size: int | None = -1, /) -> bytes:
        self.read_sizes.append(-1 if size is None else size)
        return super().read1(size)


def _http_error(code: int, body: bytes | _RecordingBody, **headers: str) -> HTTPError:
    """An ``HTTPError`` carrying a REAL, readable body and REAL headers.

    ``body`` is REQUIRED. ``tests/unit/test_readiness_key_auth.py:85`` has a
    helper of the same name that passes ``fp=None``; measured on CPython
    3.12.13, that returns ``b''`` from ``.read()`` instead of raising, so any
    body assertion made against it passes against an implementation that never
    reads the body at all (AGENTS.md rule 8a).
    """
    return HTTPError(
        url="https://openrouter.ai/api/v1/key",
        code=code,
        msg="refused",
        hdrs=_headers(**headers),
        fp=body if isinstance(body, _RecordingBody) else io.BytesIO(body),
    )


def _probe(monkeypatch: pytest.MonkeyPatch, outcome: BaseException | int) -> str:
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    monkeypatch.setattr(config.settings, "openrouter_api_key", "sk-or-test", raising=False)

    def transport(*, url: str, api_key: str, timeout: float) -> int:
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return readiness.probe_key_auth(transport=transport)


def _record(caplog: pytest.LogCaptureFixture) -> dict[str, Any]:
    records = [r for r in caplog.records if r.msg == "key_probe_credential_refused"]
    assert len(records) == 1, f"expected exactly 1 refusal record, got {len(records)}"
    return records[0].__dict__


def test_the_403_probe_shape_is_captured_with_names_not_values(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED WHEN: the capture is deleted, or a header VALUE is recorded.

    A WAF denial page routinely echoes the request headers back, and a header
    value can be key material, so ``server`` is reduced to an enum and only
    header NAMES are kept. ``cf-ray: abc123`` is the canary: the name must be
    recorded and the value must not.
    """
    with caplog.at_level(logging.DEBUG, logger="product_app.readiness"):
        verdict = _probe(
            monkeypatch,
            _http_error(
                403,
                _PROXY_HTML_BODY,
                Server="nginx",
                cf_ray="abc123",
                Content_Type="text/html; charset=utf-8",
            ),
        )
    assert verdict == "unauthorized"
    record = _record(caplog)
    assert record["status_code"] == 403
    assert record["server_class"] == "other"
    assert record["content_type_main"] == "text/html"
    assert record["body_shape"] == "not_json"
    assert record["body_bytes"] == len(_PROXY_HTML_BODY)
    assert record["error_code_in_body"] is None
    assert "cf-ray" in record["header_names_present"]
    assert "server" not in record["header_names_present"], (
        "the allowlist is not an allowlist — it is echoing every header name"
    )
    assert "abc123" not in json.dumps(record, default=str), "a header VALUE was recorded"
    assert "Access denied by policy" not in json.dumps(record, default=str)


def test_the_genuine_openrouter_refusal_shape_is_captured_too(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED WHEN: the JSON envelope is not parsed, or the exposed-header probe
    stops looking for OpenRouter's own names.

    This is the POSITIVE PARTNER for the test above: without it, every field
    could report the same constant for every input and both tests would agree.
    The values here are the ones measured against the live API — including that
    ``server: cloudflare`` appears on the GENUINE provider refusal, which is
    why it cannot be used to detect a proxy.
    """
    with caplog.at_level(logging.DEBUG, logger="product_app.readiness"):
        verdict = _probe(
            monkeypatch,
            _http_error(
                401,
                _OPENROUTER_401_BODY,
                Server="cloudflare",
                cf_ray="9a1b2c3d4e5f",
                Content_Type="application/json",
                Access_Control_Expose_Headers="X-Generation-Id,X-Provider-Name,cf-ray",
            ),
        )
    assert verdict == "unauthorized"
    record = _record(caplog)
    assert record["status_code"] == 401
    assert record["server_class"] == "cloudflare"
    assert record["content_type_main"] == "application/json"
    assert record["body_shape"] == "json"
    assert record["error_code_in_body"] == 401
    assert record["expose_headers_names_openrouter"] is True
    assert sorted(record["header_names_present"]) == [
        "access-control-expose-headers",
        "cf-ray",
    ]
    assert "9a1b2c3d4e5f" not in json.dumps(record, default=str)


def test_a_refusal_with_no_headers_at_all_reports_absent_not_a_guess(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED WHEN: an absent header is collapsed into the same value as a present
    one that says something else.

    ``server_class`` must distinguish "no ``Server`` header" from "a ``Server``
    header naming something other than Cloudflare". Collapsing them would make
    the whole production sample unreadable, the same way collapsing
    ``provider_name_present``'s ``False`` and ``None`` would in #105.
    """
    with caplog.at_level(logging.DEBUG, logger="product_app.readiness"):
        _probe(monkeypatch, _http_error(403, b""))
    record = _record(caplog)
    assert record["server_class"] == "absent"
    assert record["content_type_main"] == "absent"
    assert record["body_shape"] == "empty"
    assert record["body_bytes"] == 0
    assert record["header_names_present"] == []
    assert record["expose_headers_names_openrouter"] is None


def test_an_unfamiliar_content_type_collapses_and_a_foreign_expose_list_reports_false(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED WHEN: the content-type enum is dropped, or the exposed-header probe
    reports a bare truthiness instead of a real answer.

    Two things are pinned here that the tests above cannot see.

    * A ``Content-Type`` is an upstream-controlled STRING. Recording it
      verbatim would let a hostile or broken server put a value of its choosing
      into our log, so anything outside the known pair collapses to ``other``.
      The header below is 300 characters for exactly that reason.
    * ``expose_headers_names_openrouter`` must be able to say ``False`` — a
      layer that exposes headers but not OpenRouter's is the interesting case,
      and the ``True``/``None`` tests above would both pass over an
      implementation that never returns ``False``.
    """
    with caplog.at_level(logging.DEBUG, logger="product_app.readiness"):
        _probe(
            monkeypatch,
            _http_error(
                403,
                b"blocked",
                Content_Type="application/x-" + "z" * 300,
                Access_Control_Expose_Headers="X-Corp-Trace, X-Corp-Rule",
            ),
        )
    record = _record(caplog)
    assert record["content_type_main"] == "other"
    assert record["expose_headers_names_openrouter"] is False
    assert "zzz" not in json.dumps(record, default=str), (
        "the raw Content-Type reached the record; an upstream can write our logs"
    )


def test_an_unreadable_body_still_produces_a_record_with_the_headers_it_had(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED WHEN: a failed body read swallows the whole record, or is reported as
    ``empty``.

    A dead socket is NOT an empty body, and recording it as one would claim the
    upstream sent nothing — a different and wrong finding in the very sample
    #203 is being collected for. The header evidence survives a body that does
    not, so it must still be written.
    """

    class _DeadSocket(io.BytesIO):
        def read1(self, size: int | None = -1, /) -> bytes:
            raise OSError("connection reset by peer")

    with caplog.at_level(logging.DEBUG, logger="product_app.readiness"):
        verdict = _probe(
            monkeypatch,
            HTTPError(
                url="https://openrouter.ai/api/v1/key",
                code=403,
                msg="refused",
                hdrs=_headers(Server="cloudflare", cf_ray="deadbeef"),
                fp=_DeadSocket(b"never read"),
            ),
        )
    assert verdict == "unauthorized"
    record = _record(caplog)
    assert record["body_shape"] == "unreadable"
    assert record["body_bytes"] == 0
    # POSITIVE PARTNER: the header half of the evidence still arrived, so this
    # is not passing because the record degraded to nothing at all.
    assert record["server_class"] == "cloudflare"
    assert record["header_names_present"] == ["cf-ray"]
    assert "deadbeef" not in json.dumps(record, default=str)


def test_capturing_the_403_shape_does_not_change_the_readiness_verdict(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED WHEN: the capture alters control flow in ``probe_key_auth``.

    #203 is NOT fixed here and ``_CREDENTIAL_REFUSED_STATUSES`` is untouched.
    This pins that: every verdict the probe could return before still comes
    back, from both the raised-error path and the returned-status path.
    """
    assert frozenset({401, 403}) == readiness._CREDENTIAL_REFUSED_STATUSES
    with caplog.at_level(logging.DEBUG, logger="product_app.readiness"):
        assert _probe(monkeypatch, _http_error(401, _OPENROUTER_401_BODY)) == "unauthorized"
        assert _probe(monkeypatch, _http_error(403, _PROXY_HTML_BODY)) == "unauthorized"
        assert _probe(monkeypatch, _http_error(429, b"slow down")) == "unknown"
        assert _probe(monkeypatch, _http_error(500, b"oops")) == "unknown"
        assert _probe(monkeypatch, 200) == "ok"
        assert _probe(monkeypatch, 403) == "unauthorized"
        assert _probe(monkeypatch, 418) == "unknown"

    # And the capture fires ONLY on the two refusal statuses, twice — not on
    # the inconclusive ones, and not on the returned-status path where there is
    # no response object to describe.
    refusals = [r for r in caplog.records if r.msg == "key_probe_credential_refused"]
    assert [r.__dict__["status_code"] for r in refusals] == [401, 403]


def test_the_probe_shape_read_is_bounded_by_the_argument_it_passes(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED WHEN: the read stops passing a size, or passes a bigger one.

    Asserts on the ARGUMENT, not on the length of the result (AGENTS.md rule
    8b): a slice taken after an unbounded read still reports a bounded number,
    so ``len(body) <= LIMIT`` survives deleting the bound entirely. A WAF
    denial page can be arbitrarily large and this runs on a failure path.
    """
    body = _RecordingBody(b"x" * 200_000)
    with caplog.at_level(logging.DEBUG, logger="product_app.readiness"):
        _probe(monkeypatch, _http_error(403, body))
    assert body.read_sizes, "no bounded read was issued at all"
    assert max(body.read_sizes) <= 2048, (
        f"the probe read asked for {max(body.read_sizes)} bytes in one call"
    )
    # And it stopped: an unbounded read would have consumed all 200_000 bytes.
    assert sum(body.read_sizes) <= 8193
    assert _record(caplog)["body_shape"] == "too_large"
