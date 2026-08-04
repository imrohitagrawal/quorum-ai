"""Issue #105 step 1: capture the EVIDENCE that decides a 5xx's billing class.

``_UNBILLED_HTTP_STATUSES`` treats every 5xx as possibly-billed, on the premise
that a 5xx can follow a generation that already consumed tokens. Issue #105's
finding is that **there is no evidence for that premise anywhere in the repo**,
and its instruction is explicit: do NOT change the classification on a guess
about an external API's semantics. Log the evidence, read a week of production
logs, then decide.

So this file pins the INSTRUMENTATION, and nothing else. The classification is
deliberately untouched, and one test below exists purely to prove that.

WHAT DECIDES THE QUESTION
-------------------------
OpenRouter's error envelope carries ``error.metadata.provider_name`` when a
provider was actually engaged. Its ABSENCE from a well-formed JSON envelope is
positive evidence that the router refused before any provider ran, so nothing
could have been billed. The three-valued reporting is the whole point:

* ``True``  — a provider was named. A charge is possible.
* ``False`` — a JSON envelope arrived and definitively did not name one.
* ``None``  — we do not know (no body, unreadable, not JSON, truncated).

Collapsing ``False`` and ``None`` into one falsy value would make a week of
production logs unreadable, because "the router refused" and "we failed to
parse the body" would be the same record. That collapse is the specific defect
these tests exist to prevent.

WHY EVERY TEST HERE SHIPS A REAL BODY
-------------------------------------
The repo's existing double is ``HTTPError(..., hdrs=None, fp=None)``. Measured
on CPython 3.12.13, that object does not raise on ``.read()`` — it returns
``b''`` (CPython substitutes an empty ``BytesIO``), and its ``.headers`` is
``None``. So a test that asserted "no provider was named" against that double
would pass VACUOUSLY, against any implementation, including one that never
reads the body at all. Every assertion below that expects ``False`` is
therefore paired with a ``True`` partner built from a real body, per AGENTS.md
rule 7.

WHAT TURNS EACH TEST RED
------------------------
Named per test in its own docstring. The file-level answer: delete the
``extra=`` keys that ``_billing_evidence_shape`` contributes at
``providers.py`` and the 8 shape tests here fail (measured: ``8 failed,
14 passed``). The classification, leak, search-rejection and opener tests
are untouched by that deletion by design — they guard different things.
"""

from __future__ import annotations

import io
import json
import logging
from email.message import Message
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from product_app import config, providers
from product_app.providers import provider_execution_service

_MODEL_ID = "anthropic/claude-haiku-4.5"

#: The real body OpenRouter returns for the router-level refusal issue #105
#: names. Captured shape: an ``error`` envelope with a message and a code, and
#: NO ``metadata.provider_name`` — nothing was engaged, so nothing was billed.
_ROUTER_REFUSAL_BODY = json.dumps(
    {"error": {"message": "No allowed providers are available for the selected model", "code": 503}}
).encode()

#: The opposite case: a 5xx that arrived AFTER a provider was engaged. This is
#: the shape the premise behind ``_UNBILLED_HTTP_STATUSES`` assumes is common.
_PROVIDER_ENGAGED_BODY = json.dumps(
    {
        "error": {
            "message": "Provider returned error",
            "code": 502,
            "metadata": {"provider_name": "Anthropic", "raw": "overloaded_error"},
        }
    }
).encode()

#: What a corporate proxy or WAF returns: not JSON at all.
_PROXY_HTML_BODY = (
    b"<html><head><title>ERROR: Access Denied</title></head>"
    b"<body><h1>ERROR</h1><p>Access denied by policy.</p></body></html>"
)


def _headers(**fields: str) -> Message:
    """Build real response headers."""
    message = Message()
    for key, value in fields.items():
        message[key.replace("_", "-")] = value
    return message


def _http_error(code: int, body: bytes | None = None, **headers: str) -> HTTPError:
    """Build an ``HTTPError`` carrying a REAL readable body and REAL headers.

    The default headers deliberately carry NO ``Content-Length``, because that
    is what the real OpenRouter API does: it sits behind Cloudflare and answers
    errors with ``Transfer-Encoding: chunked``. Measured against the live API
    on 2026-08-05 — see ``test_a_chunked_body_with_no_content_length_is_read``,
    which exists because an earlier version of this change gated the read on
    ``Content-Length`` and would therefore have collected NOTHING in
    production.

    ``body=None`` reproduces the repo's pre-existing double (empty body), which
    is the vacuity case the module docstring describes.
    """
    return HTTPError(
        url="https://openrouter.ai/api/v1/chat/completions",
        code=code,
        msg="upstream said no",
        hdrs=_headers(Transfer_Encoding="chunked", **headers),
        fp=io.BytesIO(body if body is not None else b""),
    )


def _install(monkeypatch: pytest.MonkeyPatch, outcome: Any) -> list[int]:
    """Point ``providers.urlopen`` at ``outcome`` and count POSTs issued."""
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    posts = [0]

    def fake_urlopen(request: Any, timeout: float = 0) -> Any:
        posts[0] += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)
    return posts


def _call(model_id: str = _MODEL_ID) -> Any:
    return provider_execution_service.call_with_prompt(
        openrouter_key="sk-or-test",
        model_id=model_id,
        system_prompt="s",
        user_prompt="u",
    )


def _record(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    outcome: Any,
    event: str = "upstream_provider_http_error",
) -> dict[str, Any]:
    """Drive the real provider path and return the single ``event`` record's fields.

    Returns ``record.__dict__`` rather than the ``LogRecord`` itself: the fields
    under test arrive via ``extra={...}``, so they exist at runtime but not on
    ``LogRecord``'s declared type, and ``mypy`` rejects attribute access on
    them. Indexing a dict also fails loudly on a MISSING key, which is what
    these tests want — an absent field is the defect, not an attribute error.
    """
    _install(monkeypatch, outcome)
    with caplog.at_level(logging.DEBUG, logger="product_app.providers"):
        _call()
    records = [r for r in caplog.records if r.msg == event]
    assert len(records) == 1, f"expected exactly one {event!r} record, got {len(records)}"
    return records[0].__dict__


# --- the three-valued provider_name evidence ---------------------------------


def test_router_refusal_body_reports_provider_name_absent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: the body is not read, or absence is reported as ``None``.

    This is the exact case issue #105 measured as a 5.27x cost overstatement.
    """
    record = _record(monkeypatch, caplog, _http_error(503, _ROUTER_REFUSAL_BODY))
    assert record["provider_name_present"] is False
    assert record["error_metadata_present"] is False
    assert record["body_shape"] == "json"
    assert record["body_bytes"] == len(_ROUTER_REFUSAL_BODY)


def test_provider_engaged_body_reports_provider_name_present(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The POSITIVE PARTNER for the test above (AGENTS.md rule 7).

    RED when: the extractor always reports ``False``. Without this test, an
    implementation that hardcoded ``provider_name_present = False`` would pass
    every other assertion in this file.
    """
    record = _record(monkeypatch, caplog, _http_error(502, _PROVIDER_ENGAGED_BODY))
    assert record["provider_name_present"] is True
    assert record["body_shape"] == "json"


def test_empty_body_reports_unknown_not_absent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: ``False`` and ``None`` are collapsed into one falsy value.

    An empty body is the repo's pre-existing double shape. Reporting it as
    "no provider was named" would manufacture evidence of an unbilled call out
    of a failure to read anything at all — and would poison the very log
    sample issue #105 step 2 is meant to read.
    """
    record = _record(monkeypatch, caplog, _http_error(503, None))
    assert record["provider_name_present"] is None
    assert record["error_metadata_present"] is None
    assert record["body_shape"] == "empty"
    assert record["body_bytes"] == 0


def test_non_json_body_reports_unknown(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: a proxy's HTML denial is parsed as an absent provider name."""
    record = _record(monkeypatch, caplog, _http_error(503, _PROXY_HTML_BODY))
    assert record["provider_name_present"] is None
    assert record["body_shape"] == "not_json"


def test_json_that_is_not_an_error_envelope_reports_unknown(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A JSON body with no ``error`` key tells us nothing about a provider.

    RED when: the extractor treats "parsed as JSON" as "definitely no provider",
    which would report a bare ``{}`` as evidence of an unbilled call.
    """
    record = _record(monkeypatch, caplog, _http_error(503, b'{"detail": "gateway down"}'))
    assert record["provider_name_present"] is None
    assert record["body_shape"] == "json"


def test_oversized_body_is_reported_too_large_and_never_read(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: an over-large body is read or parsed anyway.

    Asserting the SHAPE is what makes this bite. An earlier version asserted
    only ``provider_name_present is None``, and deleting the guard survived it:
    a cut-off JSON body simply fails to parse, lands in ``not_json``, and
    reports ``None`` anyway. The distinction matters for issue #105 step 2 —
    "the upstream declared more than we sample" and "the upstream sent
    something that is not JSON" are different findings.

    ``body_bytes`` is the DECLARED length here, and both it and the fixture
    size are pinned to literals rather than to
    ``_ERROR_BODY_SNIFF_LIMIT_BYTES``: asserting a bound against the constant
    that defines it is what AGENTS.md rule 7a forbids, and an earlier version
    of this test did exactly that, so raising the limit to 40000 survived.
    """
    huge = (
        b'{"error": {"metadata": {"provider_name": "Anthropic"}, "pad": "' + b"x" * 40000 + b'"}}'
    )
    assert len(huge) == 40066, "the fixture size is pinned to a LITERAL, not to the bound"
    record = _record(monkeypatch, caplog, _http_error(503, huge))
    assert record["body_shape"] == "too_large"
    assert record["body_bytes"] == 8192
    assert record["provider_name_present"] is None
    assert record["error_metadata_present"] is None


def test_the_error_body_read_is_actually_bounded(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: ``exc.read()`` is called with no size argument.

    The test above does NOT catch that, and the gap is worth stating: the
    reported ``body_bytes`` is bounded by a SLICE taken after the read, so an
    unbounded read still produces a correct-looking record while having
    already allocated the whole body. A hostile or broken upstream must not be
    able to make an error path allocate without limit, so this asserts on the
    argument the read is actually given.
    """
    seen: list[Any] = []

    class _RecordingBody(io.BytesIO):
        def read(self, *args: Any, **kwargs: Any) -> bytes:
            seen.append(args[0] if args else None)
            return super().read(*args, **kwargs)

    exc = HTTPError(
        url="https://openrouter.ai/api/v1/chat/completions",
        code=503,
        msg="upstream said no",
        hdrs=_headers(Transfer_Encoding="chunked"),
        fp=_RecordingBody(_ROUTER_REFUSAL_BODY),
    )
    _record(monkeypatch, caplog, exc)
    assert seen, "the evidence read never happened"
    assert seen[0] is not None, "the body was read UNBOUNDED — read() got no size limit"
    assert seen[0] == 8193, "the read must ask for at most the bound plus one"


# --- the instrumentation must never leak, never raise, never reclassify ------


@pytest.mark.parametrize(
    "body",
    [
        json.dumps({"error": {"message": "SECRETQUERYTEXT-do-not-log", "code": 503}}).encode(),
        b"<html><body>SECRETQUERYTEXT denied by policy</body></html>",
        b"SECRETQUERYTEXT",
        json.dumps({"detail": "SECRETQUERYTEXT"}).encode(),
        b'{"error": {"metadata": {"raw": "SECRETQUERYTEXT"}}}',
    ],
    ids=["json-envelope", "proxy-html", "bare-text", "json-no-envelope", "metadata-raw"],
)
def test_the_body_content_is_never_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, body: bytes
) -> None:
    """RED when: the raw body is attached to the record, on ANY branch.

    An error body can carry the user's query text back verbatim, and this
    module already learned the same lesson about exception messages carrying
    key material (``_log_post_dispatch_failure``'s docstring). Only the SHAPE
    may be logged.

    Parametrized over every branch the extractor can take, because a single
    JSON fixture only ever reaches the ``json`` branch — review demonstrated
    that a leak planted in the ``not_json`` branch survived the whole suite.
    That branch is the highest-risk one: a corporate proxy's HTML denial page
    routinely echoes the request headers, ``Authorization`` included.
    """
    _install(monkeypatch, _http_error(503, body))
    with caplog.at_level(logging.DEBUG, logger="product_app.providers"):
        _call()
    assert "SECRETQUERYTEXT" not in caplog.text
    for record in caplog.records:
        for value in record.__dict__.values():
            assert "SECRETQUERYTEXT" not in str(value)


def test_a_body_that_raises_on_read_does_not_escape(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: the evidence read is not defensive.

    ``_post_messages`` documents an invariant at its catch-all: once
    ``urlopen`` has been called this method RETURNS, it never raises. An
    instrumentation read that raised would break that invariant on the error
    path — turning a priced-but-unmeasured call into a vanished one.
    """

    class _ExplodingBody(io.BytesIO):
        def read(self, *args: Any, **kwargs: Any) -> bytes:
            raise OSError("socket died mid-body")

    exc = HTTPError(
        url="https://openrouter.ai/api/v1/chat/completions",
        code=503,
        msg="upstream said no",
        hdrs=_headers(Transfer_Encoding="chunked"),
        fp=_ExplodingBody(b"never returned"),
    )
    record = _record(monkeypatch, caplog, exc)
    assert record["body_shape"] == "unreadable"
    assert record["provider_name_present"] is None


def test_a_body_returning_a_non_bytes_value_does_not_escape(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: ``len()`` or the slice sits OUTSIDE the defensive try.

    A ``read`` that returns ``None`` instead of bytes raises ``TypeError`` on
    ``len(raw)``, not inside ``read`` — so a guard wrapped around the read
    alone lets it escape and breaks ``_post_messages``' documented
    return-never-raise invariant. Found by review; the first version of this
    function had exactly that shape.
    """

    class _WrongTypeBody(io.BytesIO):
        def read(self, *args: Any, **kwargs: Any) -> Any:
            return None

    exc = HTTPError(
        url="https://openrouter.ai/api/v1/chat/completions",
        code=503,
        msg="upstream said no",
        hdrs=_headers(Transfer_Encoding="chunked"),
        fp=_WrongTypeBody(b"ignored"),
    )
    record = _record(monkeypatch, caplog, exc)
    assert record["body_shape"] == "unreadable"
    assert record["body_bytes"] == 0
    assert record["provider_name_present"] is None


@pytest.mark.parametrize(
    ("status", "body", "expect_billed"),
    [
        (503, _ROUTER_REFUSAL_BODY, True),
        (502, _PROVIDER_ENGAGED_BODY, True),
        (500, None, True),
        (400, _ROUTER_REFUSAL_BODY, False),
        (401, None, False),
        (402, _PROVIDER_ENGAGED_BODY, False),
        (403, _PROXY_HTML_BODY, False),
        (404, None, False),
        (429, _ROUTER_REFUSAL_BODY, False),
    ],
)
def test_capturing_the_evidence_does_not_change_the_classification(
    monkeypatch: pytest.MonkeyPatch, status: int, body: bytes | None, expect_billed: bool
) -> None:
    """The load-bearing guard: issue #105 forbids deciding on a guess.

    RED when: a status is added to or removed from ``_UNBILLED_HTTP_STATUSES``,
    or the evidence read consumes a branch. Every row is the classification as
    it stood BEFORE this change, including the ``503`` row that the evidence
    now argues is wrong — and that row stays until a week of production logs
    says otherwise. Asserting POST cardinality alongside the outcome, per
    AGENTS.md rule 6b.
    """
    posts = _install(monkeypatch, _http_error(status, body))
    result = _call()
    assert posts[0] == 1, "the POST was issued either way"
    if expect_billed:
        assert result is not None, f"HTTP {status} must still read as possibly-billed"
        assert result.answer_text == ""
        assert result.usage is None
    else:
        assert result is None, f"HTTP {status} must still read as not billed"


def test_search_rejected_variant_still_returns_before_any_evidence_read(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A 400/404 on an ``:online`` model returns before the log, and must stay so.

    RED when: the evidence read is hoisted above the ``_SEARCH_REJECTED``
    early return, which would start logging a benign, expected signal on every
    search-capable model probe.
    """
    _install(monkeypatch, _http_error(404, _ROUTER_REFUSAL_BODY))
    with caplog.at_level(logging.DEBUG, logger="product_app.providers"):
        assert _call(model_id=f"{_MODEL_ID}:online") is None
    assert [r for r in caplog.records if r.msg == "upstream_provider_http_error"] == []


# --- the URLError branch, which issue #105 asks to fold into the same review --


@pytest.mark.parametrize(
    ("reason", "expect_billed"),
    [
        (TimeoutError("timed out"), True),
        (ConnectionRefusedError(61, "Connection refused"), False),
    ],
    ids=["connect-timeout", "connection-refused"],
)
def test_opener_failure_is_logged_with_its_reason_class(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    reason: BaseException,
    expect_billed: bool,
) -> None:
    """RED when: the ``URLError`` branch logs nothing.

    Measured on 56edd1b: that branch had NO logger call at all, so the
    conservative possibly-billed classification of a connect timeout — which
    issue #105 explicitly folds into this review — produced no evidence
    whatsoever. The classification is unchanged; only the record is new.
    """
    record = _record(monkeypatch, caplog, URLError(reason), event="upstream_provider_opener_error")
    assert record["error_type"] == type(reason).__name__
    assert record["model_id"] == _MODEL_ID
    assert record["billing_class"] == ("possibly_billed" if expect_billed else "not_billed")


def test_opener_failure_never_logs_the_exception_message(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: ``str(exc)`` is logged anywhere — message OR an ``extra`` field.

    Same lesson as ``_log_post_dispatch_failure``: a ``URLError`` reason can
    carry a header value, and a header value can be key material.

    The ``record.__dict__`` walk is load-bearing and this test did not have it
    at first. ``caplog.text`` renders with pytest's ``DEFAULT_LOG_FORMAT``,
    which contains **no ``extra`` fields at all** — so checking only
    ``caplog.text`` left the whole file green against an implementation that
    put ``str(exc.reason)`` straight into ``extra=`` and shipped it to the
    production JSON, which ``JsonFormatter`` does fold in. Measured: all 22
    tests passed against exactly that leak. This is the vacuity class rule 8a
    describes, found inside the commit that added rule 8a.
    """
    _install(monkeypatch, URLError(OSError("REALKEYMATERIAL-in-the-reason")))
    with caplog.at_level(logging.DEBUG, logger="product_app.providers"):
        _call()
    assert "REALKEYMATERIAL" not in caplog.text
    for record in caplog.records:
        for value in record.__dict__.values():
            assert "REALKEYMATERIAL" not in str(value)


# --- the Content-Length gate: the read must not cost a socket timeout --------


def test_a_chunked_body_with_no_content_length_is_READ(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: the read is gated on ``Content-Length``.

    THIS TEST EXISTS BECAUSE THE FIRST FIX WAS WRONG IN PRODUCTION, and only a
    probe against the live API found it. OpenRouter is behind Cloudflare and
    answers errors with ``Transfer-Encoding: chunked`` and **no
    ``Content-Length``** — measured 2026-08-05 on a real 401:

        Content-Length : absent      Transfer-Encoding: chunked
        Server         : cloudflare  body: {"error":{"message":"User not found.","code":401}}

    An earlier version bounded the read's TIME by refusing to read a body whose
    length was not declared. Against a loopback server that looked correct;
    against the real API it would have reported ``no_length`` for **every
    single provider error** and collected nothing at all — defeating the entire
    purpose of issue #105 step 1 while every local gate stayed green.

    The lesson is in AGENTS.md 8c: a mitigation gated on an upstream behaviour
    must be measured against the real upstream.
    """
    record = _record(monkeypatch, caplog, _http_error(503, _ROUTER_REFUSAL_BODY))
    assert record["body_shape"] == "json", "the real OpenRouter error shape must be READ"
    assert record["body_bytes"] == len(_ROUTER_REFUSAL_BODY)
    assert record["provider_name_present"] is False


def test_the_evidence_read_is_time_bounded(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: the socket timeout is not lowered before the sniff read.

    Time, not bytes, is what a withheld body costs: 0.015s to 8.009s measured
    on a real loopback server. Reaching the socket is CPython-specific, so the
    helper is best-effort and the record says whether it worked — a field that
    would otherwise silently read as "no problem" on a platform where it
    cannot.
    """
    settimeouts: list[float] = []

    class _Sock:
        def settimeout(self, value: float) -> None:
            settimeouts.append(value)

    class _Raw:
        _sock = _Sock()

    class _Inner:
        raw = _Raw()

    class _TimedBody(io.BytesIO):
        fp = _Inner()

    exc = HTTPError(
        url="https://openrouter.ai/api/v1/chat/completions",
        code=503,
        msg="upstream said no",
        hdrs=_headers(Transfer_Encoding="chunked"),
        fp=_TimedBody(_ROUTER_REFUSAL_BODY),
    )
    record = _record(monkeypatch, caplog, exc)
    assert settimeouts == [providers._ERROR_BODY_SNIFF_TIMEOUT_SECONDS]
    assert settimeouts[0] < 8.0, "the sniff must be shorter than the connection timeout"
    assert record["sniff_time_bounded"] is True


def test_an_unreachable_socket_is_reported_not_silently_assumed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: a failure to bound the time is reported as success.

    The ordinary doubles here expose no socket, so this is also the control
    proving the field is not hardcoded ``True``.
    """
    record = _record(monkeypatch, caplog, _http_error(503, _ROUTER_REFUSAL_BODY))
    assert record["sniff_time_bounded"] is False


@pytest.mark.parametrize(
    ("header_value", "expected"),
    [("Anthropic", True), ("", False)],
    ids=["header-present", "header-empty"],
)
def test_the_provider_name_header_is_captured_independently_of_the_body(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    header_value: str,
    expected: bool,
) -> None:
    """RED when: ``X-Provider-Name`` is not read.

    A SECOND, independent signal for the same question, found by probing the
    live API — OpenRouter lists ``X-Provider-Name`` in its
    ``Access-Control-Expose-Headers``. A header survives a body that is
    unreadable, over-large or not JSON, so the two fail independently. Here the
    body deliberately says nothing about a provider, so only the header can
    supply the answer.
    """
    record = _record(
        monkeypatch,
        caplog,
        _http_error(502, _ROUTER_REFUSAL_BODY, X_Provider_Name=header_value),
    )
    assert record["provider_name_header"] is expected
    assert record["provider_name_present"] is False, "the BODY still names nobody"


# --- F2: the record must agree with the decision it describes ----------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (503, "possibly_billed"),
        (500, "possibly_billed"),
        (502, "possibly_billed"),
        (429, "not_billed"),
        (401, "not_billed"),
        (400, "not_billed"),
    ],
)
def test_the_http_record_states_the_same_billing_class_it_returns(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    status: int,
    expected: str,
) -> None:
    """RED when: ``billing_class`` is hardcoded, deleted, or disagrees.

    The commit's headline invariant is that ``billed`` is computed once and
    feeds BOTH the log and the return, so a record can never disagree with the
    decision it describes. Review found that invariant asserted only on the
    opener branch — on the HTTP branch, hardcoding ``billing_class`` to
    ``"not_billed"`` or deleting the field entirely passed the whole suite.

    That matters because step 2 of issue #105 is a human reading a week of
    production logs filtered on exactly this field. A ``billing_class`` that
    silently disagrees with the return value poisons the sample that decides a
    money question. So this asserts the record AND the returned classification
    together, in one test, for both directions.
    """
    record = _record(monkeypatch, caplog, _http_error(status, _ROUTER_REFUSAL_BODY))
    assert record["billing_class"] == expected
    assert record["status_code"] == status
    # ...and the RETURN agrees with what the record claims.
    posts = _install(monkeypatch, _http_error(status, _ROUTER_REFUSAL_BODY))
    result = _call()
    assert posts[0] == 1
    assert (result is not None) is (expected == "possibly_billed")


# --- F6: "no provider named" and "no provider block at all" are not the same -


def test_metadata_present_without_a_name_is_distinguishable_from_a_router_refusal(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: ``error_metadata_present`` is dropped or hardcoded.

    Both bodies below report ``provider_name_present is False``, but they are
    NOT the same evidence. The router refusal carries no ``metadata`` at all —
    nothing was engaged. The second carries a populated ``metadata`` block with
    a provider's own error text under ``raw`` and merely no ``provider_name``,
    which means a provider very likely DID respond. Counting the second as a
    router refusal in step 3 would license reclassifying a genuinely billed
    call as unbilled, understating a real charge — the exact dishonesty F-06
    exists to prevent.
    """
    refusal = _record(monkeypatch, caplog, _http_error(503, _ROUTER_REFUSAL_BODY))
    caplog.clear()
    engaged_but_unnamed = _record(
        monkeypatch,
        caplog,
        _http_error(502, b'{"error": {"code": 502, "metadata": {"raw": "overloaded"}}}'),
    )
    assert refusal["provider_name_present"] is False
    assert engaged_but_unnamed["provider_name_present"] is False
    assert refusal["error_metadata_present"] is False
    assert engaged_but_unnamed["error_metadata_present"] is True


# --- the three gaps a second mutation round found ---------------------------


def test_the_size_bound_is_pinned_at_its_exact_boundary(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: ``_ERROR_BODY_SNIFF_LIMIT_BYTES`` moves in either direction.

    Both sides are asserted against LITERALS (8192 / 8193), never against the
    constant itself — AGENTS.md rule 7a. An earlier version pinned only an
    over-large fixture of 40066 bytes, which left the limit free to be raised
    anywhere below that: mutating 8192 to 40000 survived the whole suite.
    """
    at_limit = b'{"error": {"pad": "' + b"x" * (8192 - 22) + b'"}}'
    assert len(at_limit) == 8192
    record = _record(monkeypatch, caplog, _http_error(503, at_limit))
    assert record["body_shape"] == "json", "a body of exactly the limit must be READ"
    assert record["body_bytes"] == 8192

    caplog.clear()
    over_limit = at_limit + b" "
    assert len(over_limit) == 8193
    record = _record(monkeypatch, caplog, _http_error(503, over_limit))
    assert record["body_shape"] == "too_large", "one byte over the limit must not be PARSED"
    assert record["body_bytes"] == 8192


@pytest.mark.parametrize(
    "provider_name", ['""', "null", "false", "0"], ids=["empty", "null", "false", "zero"]
)
def test_an_unusable_provider_name_reads_as_absent_not_present(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, provider_name: str
) -> None:
    """RED when: presence is tested with ``is not None`` instead of truthiness.

    A ``provider_name`` of ``""`` or ``null`` names nobody. Reporting it as
    "a provider was named" would suppress the very evidence issue #105 exists
    to gather, and the whole suite stayed green under that mutation until this
    test existed. ``error_metadata_present`` stays ``True`` throughout, which
    is what keeps the two findings separable.
    """
    body = b'{"error": {"code": 502, "metadata": {"provider_name": %s}}}' % provider_name.encode()
    record = _record(monkeypatch, caplog, _http_error(502, body))
    assert record["provider_name_present"] is False
    assert record["error_metadata_present"] is True


def test_response_headers_never_reach_the_record_on_the_unread_path(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: the ``too_large`` branch attaches headers or body content.

    The over-large branch never reads the body, so the earlier leak test —
    which only ever fed it small bodies — could not reach it at all, and a
    leak planted there survived. Response headers are the realistic leak on
    this path: a proxy echoes request headers back, ``Authorization``
    included.
    """
    over_limit = b'{"error": {"pad": "SECRETQUERYTEXT' + b"x" * 9000 + b'"}}'
    exc = HTTPError(
        url="https://openrouter.ai/api/v1/chat/completions",
        code=503,
        msg="upstream said no",
        hdrs=_headers(
            Transfer_Encoding="chunked",
            X_Echoed_Authorization="Bearer SECRETQUERYTEXT",
        ),
        fp=io.BytesIO(over_limit),
    )
    record = _record(monkeypatch, caplog, exc)
    assert record["body_shape"] == "too_large"
    for value in record.values():
        assert "SECRETQUERYTEXT" not in str(value)


def test_headers_that_raise_on_lookup_report_unknown_not_absent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: the header read is not defensive.

    ``_provider_name_header_present`` must never raise, for the same reason
    the body read must not: it runs inside the ``except HTTPError`` branch,
    where ``_post_messages`` guarantees it RETURNS rather than raises. And it
    must report ``None``, not ``False`` — "we could not look" is not the same
    finding as "no provider was named", which is the whole three-valued
    discipline this module exists to keep.
    """

    class _HostileHeaders(Message):
        def get(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("header table is corrupt")

    exc = HTTPError(
        url="https://openrouter.ai/api/v1/chat/completions",
        code=503,
        msg="upstream said no",
        hdrs=_HostileHeaders(),
        fp=io.BytesIO(_ROUTER_REFUSAL_BODY),
    )
    record = _record(monkeypatch, caplog, exc)
    assert record["provider_name_header"] is None, "unknown must not read as absent"
    assert record["body_shape"] == "json", "the BODY is still read and parsed"
