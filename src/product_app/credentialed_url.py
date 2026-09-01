"""One scheme policy for the requests that carry the operator's OpenRouter key.

``OPENROUTER_API_BASE_URL`` is operator-settable, and two calls put
``Authorization: Bearer <the operator's key>`` on a URL built from it:
:meth:`product_app.providers.ProviderExecutionService._post_messages` (the paid
answer/debate/synthesis call) and
:func:`product_app.feedback_audit._call_audit_model` (the paid audit call).
Neither checked the scheme, so a base of ``http://…`` put the key on the wire
in clear and a base of ``file://`` handed it to something that is not a chat
endpoint at all. Board row W18; ADR-0085.

The module exports a BUILDER rather than a predicate on purpose: a call site
cannot obtain the endpoint without passing the check, so a future third
credential-bearing caller is guarded by construction rather than by
remembering. It depends on nothing but the standard library. That matters for
``feedback_audit``, whose every other ``product_app`` import is function-local
so the audit can run independently of the application's runtime state; this
module is the one exception, and it is safe to be one precisely because it
pulls in no configuration, no logging setup and no store.

Scope, stated because the sentence above invites a wider reading: this covers
the calls built from ``OPENROUTER_API_BASE_URL``. It is NOT every credentialed
request in the process — ``providers._tavily_search`` sends
``Authorization: Bearer <the operator's Tavily key>`` to
``f"{settings.tavily_api_base_url}/search"`` with no scheme guard at all, on a
setting that is operator-settable in exactly the same way. That is a different
credential and a different setting, so it is board row W21's neighbour W22
rather than a fifth thing bolted on here.

Two sibling guards already exist and this one is not a copy of either:

* :func:`product_app.readiness.probe_key_auth` demands ``https`` with no
  exception, because it is a probe that can decline to run at all.
* :func:`product_app.catalog_fetcher.catalog_url` allows ``http`` to anywhere,
  because it sends NO credential (ADR-0080 states that reasoning at length).

Neither is refactored onto this module. Widening readiness would loosen a
security guard for no reason; narrowing the catalog would break the local
mirror ADR-0080 exists to allow.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

#: Hostnames that name this machine literally. Compared by EXACT equality
#: after ``urlsplit`` has lower-cased the host, never by prefix or substring:
#: ``localhost.evil.com`` and ``127.0.0.1.evil.com`` both contain a loopback
#: spelling and neither is loopback.
_LOOPBACK_HOSTNAMES = frozenset({"localhost"})


#: Characters that never belong in a configured base URL and that
#: ``http.client`` rejects with ``InvalidURL`` -- an ``HTTPException``, which
#: is none of the classes either call site catches. A trailing space is the
#: likeliest operator typo there is, and a bare ``\r\n`` in a URL is a request
#: smuggling shape, so both are refused here rather than raised downstream.
_FORBIDDEN_IN_A_BASE_URL = re.compile(r"[\s\x00-\x1f\x7f]")


def is_credential_safe(url: str) -> bool:
    """Whether ``url`` may carry ``Authorization: Bearer``.

    ``https`` to anywhere, or ``http`` to a loopback host, and in neither case
    with whitespace, a control character or userinfo in it. Everything else is
    refused.

    **This function never raises.** ``urlsplit`` itself raises ``ValueError``
    on a netloc whose characters NFKC-normalise into a URL delimiter (measured
    2026-09-01: ``http://localhost\uff0fevil.com/v1`` gives *"netloc ...
    contains invalid characters under NFKC normalization"*), and a refusal that
    escapes as an exception is not a refusal -- it would leave
    ``_call_audit_model`` raising past its documented "returns ``None`` on any
    failure" exactly as the bug this module was written to close did.

    Userinfo is refused rather than tolerated for two reasons. It is never a
    legitimate way to reach a Bearer-auth API, and ``http.client`` rejects it
    anyway -- ``https://user:pass@host`` raises
    ``InvalidURL("nonnumeric port: 'pass@host'")``, whose message contains the
    password verbatim.

    The rule is about a credential crossing a NETWORK in clear. A loopback
    connection does not leave the machine, so there is no wire to observe --
    the same reasoning that makes ``http://localhost`` a potentially
    trustworthy origin on the web platform. That carve-out is also what lets
    an operator front the paid call with a local gateway, and what keeps the
    repo's only real-socket tests of this seam able to run: measured by
    mutation on 2026-09-01, replacing this line with ``return False`` turns
    **22 of the 31** tests in ``tests/unit/test_provider_streaming_transport.py``
    plus ``tests/unit/test_provider_call_time_budget.py`` red.

    Fail closed. ``http://127.1`` and ``http://2130706433`` both reach
    loopback once a resolver is involved and both are refused here, because
    reimplementing a resolver to widen the carve-out would trade a real risk
    for no gain. So is any hostname that merely RESOLVES to loopback.
    """
    if _FORBIDDEN_IN_A_BASE_URL.search(url):
        return False
    try:
        parts = urlsplit(url)
        if parts.username is not None or parts.password is not None:
            return False
        if parts.scheme == "https":
            return True
        if parts.scheme != "http":
            return False
        return _is_loopback_host(parts.hostname)
    except ValueError:
        return False


def _is_loopback_host(host: str | None) -> bool:
    if host is None:
        return False
    if host in _LOOPBACK_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def chat_completions_url(base_url: str) -> str | None:
    """The chat-completions endpoint for ``base_url``, or ``None`` to refuse.

    ``None`` means "do not dial this, and do not report a charge": both call
    sites already document ``None`` as their unbilled/best-effort failure, so
    the refusal reuses a shape the paid path has rather than inventing one.

    The URL is built exactly as both call sites built it before the guard --
    plain concatenation, no ``rstrip('/')`` -- so the only behaviour this
    module changes is the refusal. Normalising the base would be a second,
    unreviewed change on the paid seam.
    """
    url = f"{base_url}/chat/completions"
    return url if is_credential_safe(url) else None


def base_url_provenance(base_url: str) -> tuple[str, str]:
    """``(scheme, host)`` of ``base_url``, safe to put in a log record.

    A base URL can carry userinfo (``https://user:pass@host``) and that is
    credential material, so a refusal must never log the URL it was cut from.
    ``urlsplit(...).hostname`` excludes userinfo. It also returns ``None``, not
    ``""``, for an absent host, and the fallback is there so a log record's
    field type does not depend on how malformed the setting was -- a record
    nobody can query is not a record. ``scheme`` needs no such fallback:
    measured on CPython 3.12.13 across eight malformed inputs, ``urlsplit``
    returns ``str`` for it every time, empty when there is no scheme. An
    ``or ""`` there would be an EQUIVALENT mutant -- one CI's gate duly
    reported as a survivor -- so the code is written so it cannot be generated
    (ADR-0069), rather than an exception being recorded for it.

    The parse is guarded because ``urlsplit`` itself raises on some netlocs. A
    refusal must not blow up on the way to saying it refused.
    """
    try:
        parts = urlsplit(base_url)
        return parts.scheme, parts.hostname or ""
    except ValueError:
        return "", ""
