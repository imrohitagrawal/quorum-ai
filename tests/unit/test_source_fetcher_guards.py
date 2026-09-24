"""The source fetcher's egress policy (#447, ADR-0124): what may be dialled,
and what must never leave.

Every test that needs a socket uses a LOOPBACK server and opts in by
monkeypatching the fetcher's resolver or address predicate; the suite's own
no-egress guard (``tests/conftest.py``) stays in force throughout.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.source_fetch_server import respond, serve

from product_app import source_fetcher
from product_app.config import settings

_HTML = (
    "<html><head><title>t</title><script>var secret=1</script></head><body>"
    + "<p>"
    + "Evidence sentence about the cited claim. " * 12
    + "</p></body></html>"
).encode()
_OK = respond("200 OK", {"Content-Type": "text/html; charset=utf-8"}, _HTML)


def _fetch(urls: list[str], **overrides: Any) -> tuple[source_fetcher.FetchedSource, ...]:
    kwargs: dict[str, Any] = {
        "budget_seconds": 5.0,
        "per_recv_seconds": 2.0,
        "max_bytes": 262_144,
        "max_pages": 8,
        "max_text_chars": 4_000,
    }
    kwargs.update(overrides)
    return source_fetcher.fetch_cited_pages(urls, **kwargs)


def _allow_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let the classifier accept 127.0.0.1 for one test, and nothing else."""
    monkeypatch.setattr(
        source_fetcher, "_address_is_allowed", lambda address: address == "127.0.0.1"
    )


# --- The address predicate ---------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # loopback
        "10.0.0.1",  # RFC 1918
        "172.19.4.130",  # Fly's private range
        "192.168.1.1",
        "169.254.169.254",  # cloud metadata
        "100.64.0.1",  # CGNAT
        "0.0.0.0",
        "224.0.0.1",  # multicast
        "240.0.0.1",  # reserved
        "::1",
        "fe80::1",
        "fdaa::1",  # Fly 6PN (ULA)
        "fd00:ec2::254",  # AWS metadata over IPv6
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "::ffff:169.254.169.254",
        "64:ff9b::a9fe:a9fe",  # NAT64 to the metadata address
        "64:ff9b:1::1",
        "fec0::1",  # deprecated site-local, still routed on some networks
        "not-an-address",
    ],
)
def test_a_non_public_address_is_refused(address: str) -> None:
    """RED IF: any of these reaches the dial — each is a way into the
    deployment's own network or its metadata service."""
    assert source_fetcher._address_is_allowed(address) is False


@pytest.mark.parametrize(
    "address",
    [
        "93.184.216.34",
        "2606:2800:220:1:248:1893:25c8:1946",
        # An IPv4-mapped PUBLIC address is judged by the IPv4 address it
        # carries. RED IF the mapped form is not unwrapped: the whole
        # ::ffff:0:0/96 block then reads as non-global, and the private cases
        # above would pass only by that accident rather than by the check.
        "::ffff:93.184.216.34",
    ],
)
def test_a_public_address_is_allowed(address: str) -> None:
    """POSITIVE PARTNER. RED IF: the predicate refuses everything."""
    assert source_fetcher._address_is_allowed(address) is True


def test_a_name_is_refused_when_any_resolved_address_is_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED IF: the classifier checks only the first answer — the dial could
    then be steered to the private one."""
    monkeypatch.setattr(
        source_fetcher, "_resolve", lambda host, port: ["93.184.216.34", "10.0.0.1"]
    )
    assert source_fetcher.classify_host("mixed.example", 443) is None
    monkeypatch.setattr(source_fetcher, "_resolve", lambda host, port: ["93.184.216.34"])
    assert source_fetcher.classify_host("public.example", 443) == "93.184.216.34"


def test_a_resolver_failure_is_a_refusal_not_an_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED IF: a DNS failure escapes and fails the caller."""

    def boom(host: str, port: int) -> list[str]:
        raise OSError("no such host")

    monkeypatch.setattr(source_fetcher, "_resolve", boom)
    assert source_fetcher.classify_host("nowhere.example", 80) is None
    (row,) = _fetch(["http://nowhere.example/x"])
    assert row.outcome == "refused_address"


# --- Scheme and URL shape -------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "outcome"),
    [
        ("file:///etc/passwd", "refused_scheme"),
        ("ftp://example.com/x", "refused_scheme"),
        ("gopher://example.com/x", "refused_scheme"),
        ("data:text/html,<p>x</p>", "refused_scheme"),
        ("javascript:alert(1)", "refused_scheme"),
        ("http://example.com/a b", "refused_scheme"),
        ("http://example.com/\r\nX-Injected: 1", "refused_scheme"),
        ("http://user:pass@example.com/", "refused_host"),
        ("http:///nohost", "refused_host"),
        ("http://example.com:99999/", "refused_scheme"),  # port out of range
        ("http://[::1/", "refused_scheme"),  # malformed IPv6 literal
    ],
)
def test_a_url_outside_the_policy_is_refused_before_any_lookup(
    monkeypatch: pytest.MonkeyPatch, url: str, outcome: str
) -> None:
    """RED IF: a non-http scheme, a control character or userinfo reaches the
    resolver. The resolver is replaced with one that fails the test."""

    def must_not_resolve(host: str, port: int) -> list[str]:
        raise AssertionError(f"resolved {host!r} for a URL that should have been refused")

    monkeypatch.setattr(source_fetcher, "_resolve", must_not_resolve)
    (row,) = _fetch([url])
    assert row.outcome == outcome
    assert row.text == ""


# --- What leaves on the wire ------------------------------------------------------


def test_a_cited_page_is_fetched_with_no_credential_on_the_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED IF: any key the deployment holds (OpenRouter, the judge's, Tavily's)
    or any auth-shaped header reaches a cited host. The request arriving is the
    positive partner: a fetcher that sent nothing would pass the absence
    checks and fail this one."""
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-secret-app")
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", "sk-or-secret-judge")
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-secret")
    _allow_loopback(monkeypatch)
    with serve(_OK) as (port, received):
        (row,) = _fetch([f"http://127.0.0.1:{port}/page"])
    assert row.outcome == "fetched"
    assert len(received) == 1
    headers = received[0]
    assert headers["user-agent"] == source_fetcher.USER_AGENT
    for name in ("authorization", "x-api-key", "x-title", "http-referer", "cookie"):
        assert name not in headers
    for value in headers.values():
        for secret in ("sk-or-secret-app", "sk-or-secret-judge", "tvly-secret"):
            assert secret not in value


def test_a_redirect_is_refused_and_its_target_never_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED IF: a 3xx is followed. The target server counting ZERO requests is
    the proof; the direct fetch of that same server counting ONE is the
    positive partner."""
    _allow_loopback(monkeypatch)
    with serve(_OK) as (target_port, target_received):
        redirect = respond("302 Found", {"Location": f"http://127.0.0.1:{target_port}/landed"}, b"")
        with serve(redirect) as (port, _):
            (row,) = _fetch([f"http://127.0.0.1:{port}/start"])
        assert row.outcome == "refused_redirect"
        assert row.final_status == 302
        assert target_received == []
        (direct,) = _fetch([f"http://127.0.0.1:{target_port}/direct"])
        assert direct.outcome == "fetched"
        assert len(target_received) == 1


def test_the_dial_uses_the_classified_address_and_keeps_the_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DNS rebinding: the name is resolved ONCE and the connection dials that
    address, never the name again; the hostname still reaches the server as
    ``Host``. RED IF: the connection re-resolves the name, or ``Host`` carries
    the address."""
    lookups: list[str] = []

    def resolve_once(host: str, port: int) -> list[str]:
        lookups.append(host)
        return ["127.0.0.1"]

    monkeypatch.setattr(source_fetcher, "_resolve", resolve_once)
    _allow_loopback(monkeypatch)
    with serve(_OK) as (port, received):
        (row,) = _fetch([f"http://cited.example:{port}/a?b=1"])
    assert row.outcome == "fetched"
    assert lookups == ["cited.example"]
    assert received[0]["host"] == f"cited.example:{port}"
    assert received[0][":path"] == "/a?b=1"


def test_a_refused_address_is_never_dialled(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED IF: the fetcher connects before (or despite) the refusal. The
    server counting zero requests is the proof; the same URL counting one
    once the address is allowed is the positive partner."""
    monkeypatch.setattr(source_fetcher, "_resolve", lambda host, port: ["127.0.0.1"])
    with serve(_OK) as (port, received):
        (row,) = _fetch([f"http://cited.example:{port}/"])
        assert row.outcome == "refused_address"
        assert received == []
        _allow_loopback(monkeypatch)
        (row,) = _fetch([f"http://cited.example:{port}/"])
        assert row.outcome == "fetched"
        assert len(received) == 1


def test_https_to_a_server_that_does_not_speak_tls_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TLS is real: an ``https`` URL whose server answers in plaintext is a
    network error, never read as a page. RED IF: the HTTPS connection skips
    the TLS handshake. The positive partner is that the server was reached
    (the handshake bytes arrived), so the refusal is TLS, not the policy."""
    _allow_loopback(monkeypatch)
    with serve(_OK) as (port, received):
        (row,) = _fetch([f"https://127.0.0.1:{port}/"], per_recv_seconds=0.5)
    # A plaintext server never answers the TLS hello, so the handshake either
    # errors or times out; both fail closed with nothing read.
    assert row.outcome in {"network_error", "timeout"}
    assert row.text == ""
    assert row.bytes_read == 0
    assert len(received) == 1
    assert "user-agent" not in received[0]


def test_a_refused_connection_is_a_network_error_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED IF: a connection error escapes instead of becoming a row."""
    import socket

    _allow_loopback(monkeypatch)
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    closed_port = probe.getsockname()[1]
    probe.close()
    (row,) = _fetch([f"http://127.0.0.1:{closed_port}/"])
    assert row.outcome == "network_error"
    assert row.text == ""
