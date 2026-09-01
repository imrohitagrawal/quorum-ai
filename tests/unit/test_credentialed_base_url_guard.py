"""The operator's API key must not leave the machine in clear.

``OPENROUTER_API_BASE_URL`` is operator-settable, and two calls put
``Authorization: Bearer <the operator's key>`` on a URL built from it:
``providers._post_messages`` (the paid answer/debate/synthesis call) and
``feedback_audit._call_audit_model`` (the paid audit call). Before this file
neither checked the scheme, so a base of ``http://…`` -- a typo, a copied
proxy address, an internal gateway someone never fronted with TLS -- sent the
key across the network in clear, and a base of ``file://`` or ``data:`` handed
it to a scheme that is not a chat endpoint at all.

RED when: the scheme guard is deleted from either call site, or weakened to
accept cleartext to a non-loopback host, or weakened to accept a scheme other
than http/https. Every refusal test below has a positive partner in the same
file proving the ordinary case still dials (rule 7) -- a guard that refused
everything would pass the refusals and fail the partners.

Assertions are on the ``Request`` object the code really built and on the
CARDINALITY of dispatch attempts, never on log prose (rule 8). The count is
the load-bearing part: an ``AssertionError`` raised inside a ``urlopen``
double is swallowed by ``_post_messages``' catch-all (its own NOTE for test
authors says so), so "assert nothing was sent" has to be counted from
outside.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request

import pytest
from tests.code_text import code_without_comments
from tests.repo_root import find_repo_root

from product_app import config
from product_app import feedback_audit as feedback_audit_module
from product_app import providers as providers_module
from product_app.credentialed_url import base_url_provenance, chat_completions_url
from product_app.providers import provider_execution_service

_MODEL_ID = "openai/gpt-4o-mini"

#: A base whose scheme and host are both fine. Nothing in this file dials it;
#: ``urlopen`` is always doubled.
_SAFE_BASE = "https://openrouter.ai/api/v1"


class _Recorder:
    """A ``urlopen`` double that records every dispatch attempt.

    It raises ``OSError`` rather than returning a body: these tests care only
    about whether a request was built and handed to the transport, and
    ``URLError`` is the class both call sites already handle, so a refusal
    test and its positive partner differ only in whether a request was built.
    """

    def __init__(self) -> None:
        self.requests: list[Request] = []

    def __call__(self, request: Request, *args: Any, **kwargs: Any) -> Any:
        self.requests.append(request)
        raise URLError("the double never answers")


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    double = _Recorder()
    monkeypatch.setattr(providers_module, "urlopen", double)
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    return double


def _post() -> Any:
    """Drive the paid call. The base comes from ``_point_at``, not from here."""
    return provider_execution_service._post_messages(
        openrouter_key="sk-or-SECRET",
        model_id=_MODEL_ID,
        messages=[{"role": "user", "content": "q"}],
        max_tokens=100,
    )


def _point_at(monkeypatch: pytest.MonkeyPatch, base: str) -> None:
    monkeypatch.setattr(config.settings, "openrouter_api_base_url", base, raising=False)


# --------------------------------------------------------------------------
# The helper's own decision table.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "base",
    [
        "https://openrouter.ai/api/v1",
        "HTTPS://openrouter.ai/api/v1",
        "https://gateway.internal/v1",
        "http://127.0.0.1:9999/v1",
        "http://localhost:9999/v1",
        "HTTP://LOCALHOST:9999/v1",
        "http://[::1]:9999/v1",
    ],
)
def test_a_credential_safe_base_yields_the_endpoint(base: str) -> None:
    """Positive partner for the whole refusal table below.

    RED when: the guard hardens into https-only (which would refuse the three
    loopback rows), or when the scheme/host comparison stops normalising
    case.

    Measured by mutation on 2026-09-01: replacing the loopback carve-out with
    ``return False`` -- i.e. hardening to https-only -- turns **22 of the 31**
    tests in ``tests/unit/test_provider_streaming_transport.py`` plus
    ``tests/unit/test_provider_call_time_budget.py`` red, because those are the
    repo's only real-socket coverage of this seam and they drive it against
    ``http://127.0.0.1:PORT``.
    """
    assert chat_completions_url(base) == f"{base}/chat/completions"


@pytest.mark.parametrize(
    "base",
    [
        # Cleartext to something that is not this machine: the key crosses a
        # network in clear. This is the defect W18 names.
        "http://openrouter.ai/api/v1",
        "http://gateway.internal/v1",
        # A host that only LOOKS like loopback. Refused by exact match, not by
        # a substring or prefix test -- both of these contain "127.0.0.1" and
        # "localhost" respectively.
        "http://127.0.0.1.evil.com/v1",
        "http://localhost.evil.com/v1",
        "http://notlocalhost/v1",
        # urlopen speaks more than http.
        "file:///etc/passwd",
        "ftp://openrouter.ai/api/v1",
        "data:text/plain,x",
        # Fail closed: these do reach loopback once a resolver is involved,
        # and the guard refuses them anyway rather than reimplementing a
        # resolver.
        "http://127.1/v1",
        "http://2130706433/v1",
        "http://0.0.0.0/v1",
        # No scheme at all -- what an unset OPENROUTER_API_BASE_URL produces.
        "",
        "/v1",
        "openrouter.ai/api/v1",
        # An http URL with no authority section at all: ``urlsplit`` reports
        # scheme "http" and hostname ``None``, so the loopback check is asked
        # about nothing. Refusing is the only safe answer, and this row is the
        # only thing that executes that branch.
        "http:/openrouter.ai/api/v1",
        # Whitespace and control characters. Every one of these reaches
        # ``http.client`` as ``InvalidURL`` -- an ``HTTPException``, which is
        # none of the classes either call site catches -- so refusing here is
        # what makes the guard's "return None to refuse" contract true. The
        # trailing space is the likeliest operator typo of the lot; the
        # ``\r\n`` row is a request-smuggling shape.
        "https://openrouter.ai/api/v1 ",
        " https://openrouter.ai/api/v1",
        "https://openrouter.ai/api/v1\n",
        "https://openrouter.ai/v1\r\nX-Injected: 1",
        "https://openrouter.ai/api/v1\x00",
        # Userinfo. Never a legitimate way to reach a Bearer-auth API, and
        # ``http.client`` raises ``InvalidURL("nonnumeric port: 'pass@host'")``
        # -- a message carrying the password verbatim.
        "https://user:pass@openrouter.ai/api/v1",
        "https://user@openrouter.ai/api/v1",
    ],
)
def test_a_base_that_must_not_carry_a_credential_yields_nothing(base: str) -> None:
    """RED when: the guard is deleted, or its scheme set is widened.

    Returning ``None`` rather than raising is what lets both call sites keep
    the failure shape they already document.
    """
    assert chat_completions_url(base) is None


def test_the_guard_refuses_rather_than_raising_on_an_unparseable_base() -> None:
    """RED when: the ``ValueError`` guard around ``urlsplit`` is removed.

    ``urlsplit`` raises on a netloc whose characters NFKC-normalise into a URL
    delimiter. A refusal that escapes as an exception is not a refusal: it
    propagates out of ``_call_audit_model``, whose contract is that it returns
    ``None`` on any failure, and out of ``_post_messages`` ahead of the ``try``
    that would have classified it.

    Both the builder AND the log helper are covered, because the refusal path
    calls the helper -- an exception there would blow up while reporting the
    refusal.

    Verbatim, on CPython 3.12.13 before this guard:
    ``ValueError: netloc 'localhost\uff0fevil.com' contains invalid characters
    under NFKC normalization``.
    """
    hostile = "http://localhost\uff0fevil.com/v1"
    assert chat_completions_url(hostile) is None
    assert base_url_provenance(hostile) == ("", "")


def test_the_log_helper_still_reports_a_parseable_base() -> None:
    """The positive partner for the test above (rule 7).

    RED when: ``base_url_provenance`` starts returning ``("", "")`` for
    everything, which would make the assertion above pass over a helper that
    reports nothing at all.
    """
    assert base_url_provenance("http://someone:hunter2@gateway.internal/v1") == (
        "http",
        "gateway.internal",
    )


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        # scheme present, host absent -- the ``hostname or ""`` fallback.
        ("file:///etc/passwd", ("file", "")),
        ("http:/openrouter.ai/api/v1", ("http", "")),
        # host present, scheme absent -- the ``scheme or ""`` fallback.
        ("//gateway.internal/v1", ("", "gateway.internal")),
        # both absent.
        ("", ("", "")),
        # both present, and userinfo excluded from the host.
        ("https://u:p@openrouter.ai/api/v1", ("https", "openrouter.ai")),
    ],
)
def test_the_log_helper_never_reports_none(base: str, expected: tuple[str, str]) -> None:
    """RED when: the ``hostname or ""`` fallback in ``base_url_provenance`` is dropped.

    Two mutants of this function survived CI's gate on the first push
    (``x_base_url_provenance__mutmut_4`` and ``__mutmut_6``) — the only two
    survivors in this package's own new code, against 80 in a pre-existing
    function. One was a missing test and is killed here: ``urlsplit`` returns
    ``None``, not ``""``, for an absent host, and a log record whose field type
    changes with how malformed the setting was is a record nobody can query.

    The other was EQUIVALENT — ``urlsplit`` never returns ``None`` for
    ``scheme``, so an ``or ""`` there could not change behaviour for any input
    and no test could kill it. Per the gate's own instruction it was removed
    from the code rather than excepted, so the mutant is no longer generated.
    The ``("", ...)`` rows below still pin that an absent scheme reports ``""``.

    Parametrized over INPUTS, not over the fallbacks themselves (rule 7a), and
    every expectation is a literal.
    """
    assert base_url_provenance(base) == expected


def test_the_endpoint_is_built_byte_identically_to_the_unguarded_form() -> None:
    """RED when: the helper normalises the base (e.g. adds ``rstrip('/')``).

    The point of the guard is the scheme check. Silently changing the URL for
    a base with a trailing slash would be a second, unreviewed behaviour
    change on the paid seam.
    """
    base = "https://gateway.internal/v1/"
    assert chat_completions_url(base) == "https://gateway.internal/v1//chat/completions"


# --------------------------------------------------------------------------
# providers._post_messages -- the paid call.
# --------------------------------------------------------------------------


def test_an_https_base_is_dialled_with_the_credential(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    """The positive partner for every providers refusal below.

    RED when: the guard refuses a base it should accept, or the call site
    stops dispatching at all. Without it, the refusal tests would still pass
    against a ``_post_messages`` that never dials anything.
    """
    _point_at(monkeypatch, _SAFE_BASE)
    _post()
    assert len(recorder.requests) == 1
    request = recorder.requests[0]
    assert request.full_url == "https://openrouter.ai/api/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer sk-or-SECRET"


def test_a_loopback_cleartext_base_is_still_dialled(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    """RED when: the guard hardens into https-only.

    This is not a convenience: it is the carve-out that keeps the repo's only
    real-socket coverage of this seam alive, and it is the reason an operator
    can still front the paid call with a local double.
    """
    _point_at(monkeypatch, "http://127.0.0.1:9999/v1")
    _post()
    assert len(recorder.requests) == 1
    assert recorder.requests[0].full_url == "http://127.0.0.1:9999/v1/chat/completions"


@pytest.mark.parametrize(
    "base",
    [
        "http://openrouter.ai/api/v1",
        "http://127.0.0.1.evil.com/v1",
        "file:///etc/passwd",
        "",
    ],
)
def test_the_paid_call_dispatches_nothing_when_the_base_is_unsafe(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder, base: str
) -> None:
    """RED when: ``_post_messages`` builds its URL without the guard.

    Counted, not asserted inside the double: ``_post_messages`` swallows every
    exception raised past ``urlopen``.
    """
    _point_at(monkeypatch, base)
    _post()
    assert recorder.requests == []


def test_a_refused_base_is_reported_as_unbilled(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    """RED when: the refusal returns ``_DISPATCH_UNMEASURED`` instead of ``None``.

    ``_DISPATCH_UNMEASURED`` means "dispatched and possibly billed". Nothing
    left the process here, so ``None`` -- the shape ``_post_messages`` already
    documents for an unbilled failure -- is the honest answer.

    Stated as a CONTRACT, not as an observed difference, and the correction
    matters: an earlier version of this docstring said the wrong return
    "forces the run's receipt to ``estimated``". Review measured that by
    mutating the refusal and diffing every run-level field -- ``status``,
    ``live_count``, ``local_count``, ``cost_source``, ``actual_cost_usd``,
    ``failed_steps``, the daily meter -- and **none of them moved**, because a
    refused base refuses every call in the run so no measured slot survives
    for the distinction to protect. The return is still right; the consequence
    that was claimed for it was not reproducible. See ADR-0085.
    """
    _point_at(monkeypatch, "http://openrouter.ai/api/v1")
    assert _post() is None


def test_the_refusal_names_the_host_and_never_the_url(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: the refusal is silent, or logs the configured URL verbatim.

    A base URL can carry userinfo (``https://user:pass@host``), which is
    credential material. ``urlsplit(...).hostname`` excludes it, so the record
    carries scheme and host and never the URL it was cut from.
    """
    _point_at(monkeypatch, "http://someone:hunter2@gateway.internal/v1")
    with caplog.at_level(logging.WARNING, logger="product_app.providers"):
        _post()
    records = [r for r in caplog.records if r.name == "product_app.providers"]
    assert len(records) == 1
    assert getattr(records[0], "base_url_scheme", None) == "http"
    assert getattr(records[0], "base_url_host", None) == "gateway.internal"
    # Over the record's OWN ATTRIBUTES, not ``caplog.text``. Review
    # demonstrated that ``caplog.text`` renders only the formatted message,
    # and this record puts everything in ``extra`` -- so adding
    # ``"base_url": settings.openrouter_api_base_url`` to that dict left the
    # whole file at ``36 passed`` while production's ``JsonFormatter``, which
    # emits unknown extras, wrote the password out. The assertion that was
    # supposed to guard the credential could not see it.
    leaked = sorted(
        f"{name}={value!r}"
        for name, value in vars(records[0]).items()
        if isinstance(value, str) and "hunter2" in value
    )
    assert leaked == [], f"the log record carries the base URL's userinfo: {leaked}"
    assert "hunter2" not in caplog.text


# --------------------------------------------------------------------------
# feedback_audit._call_audit_model -- the same credential, the same base.
# --------------------------------------------------------------------------


class _AuditRecorder:
    def __init__(self) -> None:
        self.requests: list[Request] = []

    def __call__(self, request: Request, *args: Any, **kwargs: Any) -> Any:
        self.requests.append(request)
        raise URLError("the double never answers")


class _AuditResponder:
    """A ``urlopen`` double that answers with a fixed body."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __call__(self, request: Request, *args: Any, **kwargs: Any) -> Any:
        return _AuditResponse(self._body)


class _AuditResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _AuditResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


@pytest.fixture
def audit_recorder(monkeypatch: pytest.MonkeyPatch) -> _AuditRecorder:
    import urllib.request as urllib_request

    double = _AuditRecorder()
    monkeypatch.setattr(urllib_request, "urlopen", double)
    return double


def _audit(monkeypatch: pytest.MonkeyPatch, base: str | None) -> str | None:
    if base is None:
        monkeypatch.delenv("OPENROUTER_API_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("OPENROUTER_API_BASE_URL", base)
    return feedback_audit_module._call_audit_model(
        openrouter_key="sk-or-SECRET",
        model_id=_MODEL_ID,
        user_prompt="p",
    )


def test_the_audit_call_dials_an_https_base(
    monkeypatch: pytest.MonkeyPatch, audit_recorder: _AuditRecorder
) -> None:
    """Positive partner for the audit refusals.

    RED when: the audit call stops dispatching, which would make the two
    refusal tests below pass vacuously.
    """
    assert _audit(monkeypatch, _SAFE_BASE) is None  # the double never answers
    assert len(audit_recorder.requests) == 1
    assert audit_recorder.requests[0].full_url == "https://openrouter.ai/api/v1/chat/completions"
    assert audit_recorder.requests[0].get_header("Authorization") == "Bearer sk-or-SECRET"


def test_the_audit_call_dispatches_nothing_over_cleartext(
    monkeypatch: pytest.MonkeyPatch, audit_recorder: _AuditRecorder
) -> None:
    """RED when: ``_call_audit_model`` builds its URL without the guard."""
    assert _audit(monkeypatch, "http://openrouter.ai/api/v1") is None
    assert audit_recorder.requests == []


def test_an_unset_base_returns_none_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch, audit_recorder: _AuditRecorder
) -> None:
    """RED when: the guard is absent from the audit call.

    Measured on CPython 3.12 before this change: with the variable unset the
    URL is ``/chat/completions`` and ``urllib.request.Request`` raises --
    before ``urlopen`` is reached at all --
    ``ValueError("unknown url type: '/chat/completions'")``, which
    ``_call_audit_model``'s ``except (HTTPError, URLError, TimeoutError)``
    does not catch -- so its own docstring, "Returns ``None`` on any
    failure", was false. ``pytest.raises`` is deliberately not used here: the
    assertion is that the function RETURNS.
    """
    assert _audit(monkeypatch, None) is None
    assert audit_recorder.requests == []


# --------------------------------------------------------------------------
# The population, pinned. A guard at a call site is only as good as the
# guarantee that no other call site exists.
# --------------------------------------------------------------------------


def test_exactly_one_module_builds_a_chat_completions_url() -> None:
    """RED when: any module under ``src/product_app`` builds that endpoint itself.

    W18 existed because ``providers.py`` and ``feedback_audit.py`` each wrote
    ``f"{base}/chat/completions"`` in their own hand, and the review that
    found the first one missed the second: it greps for the SETTINGS
    attribute, and ``feedback_audit`` reads the environment variable
    directly. A third such line, written the same way, would reintroduce the
    same defect and no existing gate would notice.

    So the URL is now built in exactly one place, and that place is the
    guard. Nothing here stops someone importing ``urlopen`` and dialling a
    URL of their own -- this pins the SHAPE the defect actually took, not
    every conceivable one.

    Read through ``code_without_comments``: this very file, and the comments
    in both call sites, quote the endpoint while explaining it (rule 8).
    """
    root = find_repo_root(Path(__file__)) / "src" / "product_app"
    modules = sorted(root.glob("*.py"))
    # ANTI-VACUITY (rule 7): a scan that read nothing would satisfy the set
    # comparison below trivially.
    assert len(modules) >= 20, f"only {len(modules)} modules scanned under {root}"
    builders = {p.name for p in modules if "/chat/completions" in code_without_comments(p)}
    assert builders == {"credentialed_url.py"}, (
        "a module other than the guard builds the chat-completions endpoint; "
        "route it through credentialed_url.chat_completions_url"
    )


def test_both_call_sites_import_the_guard() -> None:
    """The positive partner for the pin above.

    RED when: a call site drops the import -- which is what deleting the
    guard looks like. Without this, the pin above would still pass over a
    ``providers.py`` that had had the whole check removed, because removing
    it also removes the endpoint literal.
    """
    root = find_repo_root(Path(__file__)) / "src" / "product_app"
    for name in ("providers.py", "feedback_audit.py"):
        code = code_without_comments(root / name)
        assert "from product_app.credentialed_url import" in code, name
        assert "chat_completions_url(" in code, name


# --------------------------------------------------------------------------
# The audit request's own shape. Pinned because it carries the operator's key
# and had NO tests at all before this package: CI's mutation gate reported 80
# surviving mutants inside ``_call_audit_model`` on the first push. These do
# not chase all 80 -- they pin the parts that decide what goes on the wire.
# --------------------------------------------------------------------------


def test_the_audit_request_carries_exactly_four_headers_and_the_key(
    monkeypatch: pytest.MonkeyPatch, audit_recorder: _AuditRecorder
) -> None:
    """RED when: a header is added, removed, or given the wrong value.

    An EXACT SET, not a denylist of names, for the reason ADR-0080 records: a
    denylist can be spelled around by building the header dict somewhere the
    check does not look, and that exploit stayed green against the whole
    suite. ``urllib`` title-cases header names, so the expected set is written
    the way ``Request`` stores them.
    """
    _audit(monkeypatch, _SAFE_BASE)
    request = audit_recorder.requests[0]
    assert set(request.headers) == {
        "Authorization",
        "Content-type",
        "Http-referer",
        "X-title",
    }
    assert request.get_header("Authorization") == "Bearer sk-or-SECRET"
    assert request.get_header("Content-type") == "application/json"
    assert request.method == "POST"


def test_the_audit_request_sends_the_model_and_both_messages(
    monkeypatch: pytest.MonkeyPatch, audit_recorder: _AuditRecorder
) -> None:
    """RED when: the model id, the system prompt or the user prompt is dropped.

    Asserts the decoded payload STRUCTURE (rule 8), not a substring of the
    encoded bytes.
    """
    _audit(monkeypatch, _SAFE_BASE)
    data = audit_recorder.requests[0].data
    assert isinstance(data, bytes)
    payload = json.loads(data)
    assert payload["model"] == _MODEL_ID
    assert [message["role"] for message in payload["messages"]] == ["system", "user"]
    assert payload["messages"][0]["content"] == feedback_audit_module.AUDIT_SYSTEM_PROMPT
    assert payload["messages"][1]["content"] == "p"


def test_an_unparseable_audit_body_returns_none_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED when: the body-parsing ``except`` is narrowed or removed.

    The positive partner is below: the same path with a well-formed body
    returns the model's text, so this cannot pass over a function that always
    returns ``None``.
    """
    import urllib.request as urllib_request

    monkeypatch.setattr(urllib_request, "urlopen", _AuditResponder(b"not json at all"))
    assert _audit(monkeypatch, _SAFE_BASE) is None


def test_a_well_formed_audit_body_returns_the_models_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """The positive partner (rule 7).

    RED when: the response is not read, or the answer is taken from the wrong
    place in the completion.
    """
    import urllib.request as urllib_request

    body = json.dumps({"choices": [{"message": {"content": "the audit says"}}]}).encode()
    monkeypatch.setattr(urllib_request, "urlopen", _AuditResponder(body))
    assert _audit(monkeypatch, _SAFE_BASE) == "the audit says"
