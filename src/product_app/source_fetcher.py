"""Read a cited page so the judge can grade what it has read (#447, ADR-0124).

WHAT THIS IS FOR
    The judge is asked whether an answer asserts only what its evidence
    supports, and until now it saw titles and URLs only. This module fetches
    the pages a run cited, as plain text with per-page provenance, under a
    closed egress policy. It is SHIPPED OFF (``quorum_source_fetch_enabled``
    defaults to ``False``) and nothing in the run path calls it yet: wiring its
    output into the judge is the second pull request of #447.

WHY IT DOES NOT REUSE ``credentialed_url.is_credential_safe``
    That module exists to send the OPERATOR'S KEY to OpenRouter safely, so it
    accepts ``http://localhost`` and link-local hosts by design. A cited URL
    comes from model output, which an attacker can influence; the policy here
    is the inverse. What IS shared is the rule that a redirect is never
    followed — here by construction, because ``http.client`` never follows
    one, so every 3xx is reported as ``refused_redirect``.

THE EGRESS POLICY (docs/analysis/2026-09-24-447-source-fetch-failure-modes.md)
    * Scheme ``http`` or ``https`` only, read with ``urlsplit``; no userinfo,
      no control characters or whitespace.
    * The host is resolved ONCE, and the fetch is refused unless EVERY address
      is public (``_address_is_allowed``): global, not multicast, not reserved,
      after unwrapping IPv4-mapped IPv6, and outside NAT64. That refuses
      loopback, RFC 1918, link-local and the cloud metadata address, CGNAT,
      ``0.0.0.0``, ULA, and spellings such as ``127.1`` and ``2130706433``
      (the resolver normalises them before they are classified).
    * The connection dials the CLASSIFIED address, never the name again, so a
      DNS answer that changes between the check and the connect (rebinding)
      is never used. The hostname is kept for ``Host`` and for TLS SNI and
      certificate verification. ``http.client`` consults no proxy variables.
    * No credential of any kind is sent: the request carries ``User-Agent``,
      ``Accept`` and ``Accept-Encoding: identity`` only.
    * Bytes are bounded on the READ ARGUMENT and the loop, never by slicing
      after an unbounded read (AGENTS 8b). ``Content-Length`` is a cheap
      pre-check, not the bound. The content type is checked BEFORE the body is
      read; only ``text/html`` and ``text/plain`` are read.
    * Time is bounded by ONE total deadline shared by every page of one call,
      enforced two ways: the name lookup runs in a worker thread joined with
      the remaining time, and a watchdog timer armed before the request
      SHUTS THE SOCKET when the deadline passes. That bounds everything a
      per-recv socket timeout cannot: a dribbled status line or headers,
      endless ``100 Continue`` responses, chunk-size lines and trailers. Over
      HTTPS the TLS socket is assigned BEFORE its handshake runs, so the
      watchdog can shut it mid-handshake too, and the watchdog is checked
      again once the request is sent. Each recv is also bounded by the
      per-read timeout.
    * Pages per call and per host are capped; the rest are ``skipped_cap``.

WHAT IT CANNOT SEE, stated
    Whether a page changed since the model cited it (the provenance carries
    the fetch time and the server's ``Date``/``Last-Modified`` so the reader
    can say so); robots.txt (not consulted in this pull request; the wiring
    record decides); JavaScript-rendered content (the raw HTML only).
"""

from __future__ import annotations

import contextlib
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import quote, urlsplit

Outcome = Literal[
    "fetched",
    "unusable",
    "refused_scheme",
    "refused_host",
    "refused_address",
    "refused_redirect",
    "refused_content_type",
    "too_large",
    "timeout",
    "http_error",
    "network_error",
    "skipped_cap",
]

#: The identifying agent every fetch sends, with a contact URL.
USER_AGENT = "quorum-ai-source-check/0.1 (+https://quorum.stackclimb.com)"
#: The only content types whose body is read at all.
READABLE_CONTENT_TYPES = frozenset({"text/html", "text/plain"})
#: A page whose extracted text is shorter than this is a login shell, a
#: consent wall or a bot challenge far more often than evidence, so it is
#: reported as ``unusable`` and the reader treats it as not fetched.
MIN_USABLE_TEXT_CHARS = 200
#: At most this many pages from any one host per call, so one server is not
#: hit for every citation a run makes.
MAX_PAGES_PER_HOST = 2
#: Chunk size of each bounded read.
READ_CHUNK_BYTES = 8192

#: NAT64 prefixes: an address inside them reaches an IPv4 host of the
#: attacker's choosing, including private and metadata addresses.
_NAT64_NETWORKS = (
    ipaddress.IPv6Network("64:ff9b::/96"),
    ipaddress.IPv6Network("64:ff9b:1::/48"),
)
#: Whitespace or control characters anywhere in a URL are refused: they are
#: how header-splitting and parser-confusion payloads are smuggled.
_FORBIDDEN_IN_A_URL = re.compile(r"[\x00-\x20\x7f]")
_SKIPPED_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "head"})


@dataclass(frozen=True)
class FetchedSource:
    """One row per URL handed in, fetched or not, so a reader can always say
    what was and was not fetched."""

    url: str
    outcome: Outcome
    final_status: int | None
    bytes_read: int
    truncated: bool
    elapsed_seconds: float
    text: str
    fetched_at: str
    server_date: str | None
    last_modified: str | None


def _address_is_allowed(address: str) -> bool:
    """True only for a public unicast address (see the module docstring)."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif any(ip in network for network in _NAT64_NETWORKS) or ip.is_site_local:
            # fec0::/10 (deprecated, RFC 3879) still routes on some legacy
            # internal networks, and ``is_global`` reports it True.
            return False
    return bool(ip.is_global and not ip.is_multicast and not ip.is_reserved)


def _resolve(host: str, port: int) -> list[str]:
    """Every address the resolver returns for ``host`` (the test seam)."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _resolve_within(host: str, port: int, timeout: float) -> list[str]:
    """``_resolve`` bounded by ``timeout``: ``getaddrinfo`` takes no timeout,
    and a slow authoritative nameserver is attacker-controlled for any name it
    can get cited. The lookup runs in a daemon thread; if it outlives the
    budget the thread is abandoned and ``TimeoutError`` is raised."""
    result: list[list[str]] = []
    failure: list[BaseException] = []

    def run() -> None:
        try:
            result.append(_resolve(host, port))
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller
            failure.append(exc)

    worker = threading.Thread(target=run, daemon=True, name="source-fetch-resolve")
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise TimeoutError(f"resolving {host!r} outlived the budget")
    if failure:
        raise failure[0]
    return result[0]


def classify_host(host: str, port: int, *, timeout: float = 10.0) -> str | None:
    """The one address to dial for ``host``, or ``None`` to refuse.

    Refused unless EVERY resolved address is allowed: a name that resolves to
    one public and one private address is refused, because the dial could be
    steered to either. Raises ``TimeoutError`` only when the lookup outlives
    ``timeout``; every other failure is a refusal.
    """
    try:
        addresses = _resolve_within(host, port, timeout)
    except TimeoutError:
        raise
    except (OSError, UnicodeError, ValueError):
        return None
    if not addresses or not all(_address_is_allowed(address) for address in addresses):
        return None
    return addresses[0]


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Dials the classified address; keeps the hostname for ``Host``."""

    def __init__(self, host: str, port: int, *, pinned_address: str, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout)
        self._pinned_address = pinned_address

    raw_sock: socket.socket | None = None

    def connect(self) -> None:
        self.sock = self.raw_sock = socket.create_connection(
            (self._pinned_address, self.port), self.timeout
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Dials the classified address; keeps the hostname for SNI and for
    certificate verification, which ``create_default_context`` enforces."""

    def __init__(self, host: str, port: int, *, pinned_address: str, timeout: float) -> None:
        self._tls = ssl.create_default_context()
        super().__init__(host, port, timeout=timeout, context=self._tls)
        self._pinned_address = pinned_address

    raw_sock: socket.socket | None = None

    def connect(self) -> None:
        self.raw_sock = socket.create_connection((self._pinned_address, self.port), self.timeout)
        # Wrap WITHOUT handshaking, assign, THEN handshake: wrapping detaches
        # the raw socket, so a handshake run inside wrap_socket() leaves the
        # watchdog with no live socket to shut until it returns (review
        # round 2). Assigned first, the handshake itself can be cut.
        self.sock = self._tls.wrap_socket(
            self.raw_sock, server_hostname=self.host, do_handshake_on_connect=False
        )
        self.sock.do_handshake()


class _Watchdog:
    """Shuts a connection's sockets when the shared deadline passes.

    A per-recv socket timeout cannot bound a server that keeps sending
    slowly, or that sends endless ``100 Continue`` responses or trailers; this
    can. After it fires every blocked or later read fails, and the caller
    reports ``timeout``."""

    def __init__(self, connection: http.client.HTTPConnection, seconds: float) -> None:
        self._connection = connection
        self.fired = False
        self._timer = threading.Timer(max(0.0, seconds), self._fire)
        self._timer.daemon = True

    def _fire(self) -> None:
        self.fired = True
        for sock in (getattr(self._connection, "raw_sock", None), self._connection.sock):
            if sock is not None:
                with contextlib.suppress(OSError):
                    sock.shutdown(socket.SHUT_RDWR)

    def __enter__(self) -> _Watchdog:
        self._timer.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._timer.cancel()


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def extract_text(body: str, content_type: str, *, max_chars: int) -> str:
    """Visible text of an HTML or plain-text body, whitespace collapsed and
    capped at ``max_chars``."""
    if content_type == "text/html":
        parser = _TextExtractor()
        parser.feed(body)
        parser.close()
        body = " ".join(parser.parts)
    return " ".join(body.split())[:max_chars]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _row(
    url: str,
    outcome: Outcome,
    *,
    started: float,
    clock: Callable[[], float],
    status: int | None = None,
    bytes_read: int = 0,
    truncated: bool = False,
    text: str = "",
    server_date: str | None = None,
    last_modified: str | None = None,
) -> FetchedSource:
    return FetchedSource(
        url=url,
        outcome=outcome,
        final_status=status,
        bytes_read=bytes_read,
        truncated=truncated,
        elapsed_seconds=round(max(0.0, clock() - started), 3),
        text=text,
        fetched_at=_now_iso(),
        server_date=server_date,
        last_modified=last_modified,
    )


def _fetch_one(
    url: str,
    *,
    deadline: float,
    per_recv_seconds: float,
    max_bytes: int,
    max_text_chars: int,
    clock: Callable[[], float],
) -> FetchedSource:
    started = clock()
    if _FORBIDDEN_IN_A_URL.search(url):
        return _row(url, "refused_scheme", started=started, clock=clock)
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return _row(url, "refused_scheme", started=started, clock=clock)
    if parts.scheme not in ("http", "https"):
        return _row(url, "refused_scheme", started=started, clock=clock)
    host = parts.hostname
    if not host or parts.username is not None or parts.password is not None:
        return _row(url, "refused_host", started=started, clock=clock)
    port = port or (443 if parts.scheme == "https" else 80)
    remaining = deadline - clock()
    if remaining <= 0:
        return _row(url, "skipped_cap", started=started, clock=clock)
    try:
        pinned = classify_host(host, port, timeout=remaining)
    except TimeoutError:
        return _row(url, "timeout", started=started, clock=clock)
    if pinned is None:
        return _row(url, "refused_address", started=started, clock=clock)

    remaining = deadline - clock()
    if remaining <= 0:
        return _row(url, "timeout", started=started, clock=clock)
    connection_type = _PinnedHTTPSConnection if parts.scheme == "https" else _PinnedHTTPConnection
    connection = connection_type(
        host, port, pinned_address=pinned, timeout=min(per_recv_seconds, remaining)
    )
    # A cited URL can carry non-ASCII (non-English Wikipedia paths); the
    # request line must be ASCII, so percent-encode what is not already.
    path = quote(parts.path or "/", safe="/%:@!$&'()*+,;=~-._")
    if parts.query:
        path = f"{path}?{quote(parts.query, safe='/%:@!$&()*+,;=~-._?')}"
    status: int | None = None
    server_date: str | None = None
    last_modified: str | None = None
    total = 0
    with _Watchdog(connection, remaining) as watchdog:
        try:
            connection.request(
                "GET",
                path,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html, text/plain;q=0.9, */*;q=0.1",
                    "Accept-Encoding": "identity",
                },
            )
            if watchdog.fired:
                return _row(url, "timeout", started=started, clock=clock)
            response = connection.getresponse()
            if watchdog.fired:
                # The shutdown can end a dribbled header block early, so
                # getresponse() returns a truncated head: the cause is the
                # deadline, whatever the head now looks like.
                return _row(url, "timeout", started=started, clock=clock)
            status = response.status
            server_date = response.getheader("Date")
            last_modified = response.getheader("Last-Modified")
            if 300 <= status < 400:
                return _row(
                    url,
                    "refused_redirect",
                    started=started,
                    clock=clock,
                    status=status,
                    server_date=server_date,
                    last_modified=last_modified,
                )
            if status >= 400:
                return _row(
                    url,
                    "http_error",
                    started=started,
                    clock=clock,
                    status=status,
                    server_date=server_date,
                    last_modified=last_modified,
                )
            content_type, _, params = (response.getheader("Content-Type") or "").partition(";")
            content_type = content_type.strip().lower()
            if content_type not in READABLE_CONTENT_TYPES:
                return _row(
                    url,
                    "refused_content_type",
                    started=started,
                    clock=clock,
                    status=status,
                    server_date=server_date,
                    last_modified=last_modified,
                )
            declared = response.getheader("Content-Length")
            if declared and declared.strip().isdigit() and int(declared) > max_bytes:
                return _row(
                    url,
                    "too_large",
                    started=started,
                    clock=clock,
                    status=status,
                    server_date=server_date,
                    last_modified=last_modified,
                )

            chunks: list[bytes] = []
            truncated = False
            # ``isclosed()`` first: once a Content-Length body has been read
            # in full on a closing connection, http.client closes the
            # response, and reading on would fail on a closed socket.
            while not response.isclosed():
                if watchdog.fired or deadline - clock() <= 0:
                    return _row(
                        url,
                        "timeout",
                        started=started,
                        clock=clock,
                        bytes_read=total,
                        status=status,
                        server_date=server_date,
                        last_modified=last_modified,
                    )
                # The bound is on the ARGUMENT: never more than one byte past
                # the cap is requested, so an oversize body is detected, not
                # buffered.
                chunk = response.read1(min(READ_CHUNK_BYTES, max_bytes + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    truncated = True
                    total = max_bytes
                    break
            if watchdog.fired:
                return _row(
                    url,
                    "timeout",
                    started=started,
                    clock=clock,
                    bytes_read=total,
                    status=status,
                    server_date=server_date,
                    last_modified=last_modified,
                )
            body = b"".join(chunks)[:max_bytes]
            encoding = (response.getheader("Content-Encoding") or "identity").strip().lower()
            if encoding not in ("", "identity"):
                return _row(
                    url,
                    "unusable",
                    started=started,
                    clock=clock,
                    bytes_read=total,
                    status=status,
                    server_date=server_date,
                    last_modified=last_modified,
                )
            charset_match = re.search(r"charset=([\w.:-]+)", params, re.IGNORECASE)
            charset = charset_match.group(1) if charset_match else "utf-8"
            try:
                decoded = body.decode(charset, errors="replace")
            except (LookupError, UnicodeError):
                decoded = body.decode("utf-8", errors="replace")
            text = extract_text(decoded, content_type, max_chars=max_text_chars)
            outcome: Outcome = "fetched" if len(text) >= MIN_USABLE_TEXT_CHARS else "unusable"
            return _row(
                url,
                outcome,
                started=started,
                clock=clock,
                bytes_read=total,
                truncated=truncated,
                text=text if outcome == "fetched" else "",
                status=status,
                server_date=server_date,
                last_modified=last_modified,
            )
        except TimeoutError:
            # A single recv outlived the per-read timeout.
            return _row(
                url,
                "timeout",
                started=started,
                clock=clock,
                status=status,
                bytes_read=total,
                server_date=server_date,
                last_modified=last_modified,
            )
        except (OSError, http.client.HTTPException, ValueError):
            # After the watchdog fires every read fails with one of these;
            # the cause is then the deadline, not the network.
            timed_out = watchdog.fired or deadline - clock() <= 0
            return _row(
                url,
                "timeout" if timed_out else "network_error",
                started=started,
                clock=clock,
                status=status,
                bytes_read=total,
                server_date=server_date,
                last_modified=last_modified,
            )
        finally:
            connection.close()


def fetch_cited_pages(
    urls: Sequence[str],
    *,
    budget_seconds: float,
    per_recv_seconds: float,
    max_bytes: int,
    max_pages: int,
    max_text_chars: int,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[FetchedSource, ...]:
    """Fetch ``urls`` in order, one row per distinct URL.

    Sequential, one GET per page, no retries. Stops dialling once ``max_pages``
    have been attempted or the shared ``budget_seconds`` deadline passes; later
    URLs, and any beyond ``MAX_PAGES_PER_HOST`` for one host, are
    ``skipped_cap``. Never raises.
    """
    deadline = clock() + budget_seconds
    rows: list[FetchedSource] = []
    seen: set[str] = set()
    per_host: dict[str, int] = {}
    attempted = 0
    for raw in urls:
        url = raw.strip()
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            host = (urlsplit(url).hostname or "").rstrip(".").lower()
        except ValueError:
            host = ""
        started = clock()
        if (
            attempted >= max_pages
            or clock() >= deadline
            or per_host.get(host, 0) >= MAX_PAGES_PER_HOST
        ):
            rows.append(_row(url, "skipped_cap", started=started, clock=clock))
            continue
        attempted += 1
        per_host[host] = per_host.get(host, 0) + 1
        rows.append(
            _fetch_one(
                url,
                deadline=deadline,
                per_recv_seconds=per_recv_seconds,
                max_bytes=max_bytes,
                max_text_chars=max_text_chars,
                clock=clock,
            )
        )
    return tuple(rows)
