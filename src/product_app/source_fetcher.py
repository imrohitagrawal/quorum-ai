"""Read a cited page so the judge can grade what it has read (#447, ADR-0124).

WHAT THIS IS FOR
    The judge is asked whether an answer asserts only what its evidence
    supports, and until now it saw titles and URLs only. This module fetches
    the pages a run cited, as plain text with per-page provenance, under a
    closed egress policy. It is SHIPPED OFF (``quorum_source_fetch_enabled``
    defaults to ``False``). Its one caller is ``evaluation.judge_source_pages``
    (W29, ADR-0148), reached only when that setting is on and a judge is
    configured, for a panel run's verdict.

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
    can say so); JavaScript-rendered content (the raw HTML only).

ROBOTS.TXT (W29, ADR-0148 decision 3)
    With ``respect_robots=True`` each origin's (scheme, host and port)
    ``/robots.txt`` is read ONCE per call, through the same pinned path,
    limits and deadline as the pages
    (``_fetch_one`` with ``raw=True``), and judged by :func:`robots_allows`,
    the app's own RFC 9309 matcher. ``urllib.robotparser`` is not used:
    ``.read`` opens the URL with its own client, outside the pinned address and
    the no-redirect rule, and its matching allowed five kinds of path a file
    forbids (ADR-0148 decision 3, review round 1). A page robots.txt does not
    allow is reported as ``refused_robots`` and never requested. A page whose
    robots.txt could not be read or checked is never requested either, but is
    reported as ``robots_unchecked`` (W54, ADR-0150 decision 1): that site
    asked nothing, so the trust note must not say it did.
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
    "refused_robots",
    "robots_unchecked",
]
#: What robots.txt says about one page: a rule allows it, a rule does not, or
#: the file could not be read or checked (W54, ADR-0150 decision 1).
RobotsVerdict = Literal["allowed", "refused", "unchecked"]

#: The identifying agent every fetch sends, with a contact URL.
USER_AGENT = "quorum-ai-source-check/0.1 (+https://quorum.stackclimb.com)"
#: The only content types whose body is read at all.
READABLE_CONTENT_TYPES = frozenset({"text/html", "text/plain"})
#: A page whose extracted text is shorter than this is a login shell, a
#: consent wall or a bot challenge far more often than evidence, so it is
#: reported as ``unusable`` and the reader treats it as not fetched.
MIN_USABLE_TEXT_CHARS = 200
#: At most this many pages from any one host per call, so one server is not
#: hit for every citation a run makes. 4 since ADR-0152 decision 6 (CHG-033
#: (a)); it was 2. The call still attempts at most ``max_pages`` pages within
#: the same budget, so the judge's reserve and the run-slot bound do not move.
MAX_PAGES_PER_HOST = 4
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


#: W54 (ADR-0150 decision 5): the most block text :func:`reading_text` returns
#: for a long page; the same number as the fetcher's default byte cap.
READING_TEXT_MAX_CHARS = 262_144
#: The area a long page is read from must hold at least this many characters
#: of block text (ADR-0150 decision 3), or the next, wider area is used.
_MAIN_AREA_MIN_CHARS = 1_000
#: Elements that start and end a block of text. Every container the area rules
#: below look at is one too, so the text between two boundaries always has one
#: context.
_BLOCK_TAGS = frozenset(
    {
        "address", "article", "aside", "blockquote", "body", "caption", "dd", "details",
        "dialog", "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form",
        "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "html", "legend", "li", "main",
        "nav", "ol", "p", "pre", "section", "summary", "table", "tbody", "td", "tfoot", "th",
        "thead", "tr", "ul",
    }
)  # fmt: skip
#: Page furniture, dropped from a long page only while what is left still
#: holds enough text (failure mode 5: some sites wrap the whole page in one).
_FURNITURE_TAGS = frozenset({"nav", "header", "footer", "aside", "form"})


class _BlockExtractor(_TextExtractor):
    """:class:`_TextExtractor` that also keeps the text in blocks, with what
    the area rules need about each. ``parts`` is collected exactly as the
    parent collects it, so the visible text read from it is ``extract_text``'s.

    Each ``<article>`` is recorded ONCE, as the range of block positions
    between its opening and its closing tag (nested articles included), so the
    work and memory grow with the number of tags plus blocks, never with
    their product (failure mode 18; review round 1's measurement of the
    first version is in ADR-0150 decision 3)."""

    def __init__(self) -> None:
        super().__init__()
        self.texts: list[str] = []
        self.in_main: list[bool] = []
        self.in_furniture: list[bool] = []
        #: ``[start, end)`` block positions per article, in opening order.
        self.articles: list[list[int]] = []
        self._open_articles: list[int] = []
        self._pending: list[str] = []
        self._main = 0
        self._furniture = 0

    def _flush(self) -> None:
        text = " ".join(" ".join(self._pending).split())
        self._pending = []
        if text:
            self.texts.append(text)
            self.in_main.append(self._main > 0)
            self.in_furniture.append(self._furniture > 0)

    def handle_starttag(self, tag: str, attrs: object) -> None:
        super().handle_starttag(tag, attrs)
        if tag not in _BLOCK_TAGS:
            return
        self._flush()
        if tag == "main":
            self._main += 1
        elif tag == "article":
            self._open_articles.append(len(self.articles))
            self.articles.append([len(self.texts), -1])
        elif tag in _FURNITURE_TAGS:
            self._furniture += 1

    def handle_endtag(self, tag: str) -> None:
        super().handle_endtag(tag)
        if tag not in _BLOCK_TAGS:
            return
        self._flush()
        if tag == "main" and self._main:
            self._main -= 1
        elif tag == "article" and self._open_articles:
            self.articles[self._open_articles.pop()][1] = len(self.texts)
        elif tag in _FURNITURE_TAGS and self._furniture:
            self._furniture -= 1

    def handle_data(self, data: str) -> None:
        before = len(self.parts)
        super().handle_data(data)
        if len(self.parts) > before:
            self._pending.append(data)

    def close(self) -> None:
        super().close()
        self._flush()
        # An article never closed runs to the end of the page.
        for index in self._open_articles:
            self.articles[index][1] = len(self.texts)
        self._open_articles = []


def _joined_length(blocks: Sequence[str]) -> int:
    return sum(len(block) for block in blocks) + max(0, len(blocks) - 1)


def _main_area(parser: _BlockExtractor, visible_chars: int) -> list[str]:
    """ADR-0150 decision 3: ``<main>``, else the longest ``<article>`` (its own
    text, nested articles included), each when it holds at least
    ``_MAIN_AREA_MIN_CHARS``; else the page without its furniture when that
    keeps at least ``_MAIN_AREA_MIN_CHARS`` AND at least half of the visible
    text (a page wrapped in one ``<form>`` beside a notice would otherwise
    keep only the notice); else every block."""
    texts = parser.texts
    main = [text for text, inside in zip(texts, parser.in_main, strict=True) if inside]
    if _joined_length(main) >= _MAIN_AREA_MIN_CHARS:
        return main
    # Prefix sums give each article's joined length in O(1), whatever the nesting.
    prefix = [0]
    for text in texts:
        prefix.append(prefix[-1] + len(text))

    def article_length(span: list[int]) -> int:
        start, end = span
        return prefix[end] - prefix[start] + max(0, end - start - 1)

    # max() keeps the first of equal lengths, so a tie goes to the earlier one.
    longest = max(parser.articles, key=article_length, default=None)
    if longest is not None and article_length(longest) >= _MAIN_AREA_MIN_CHARS:
        return texts[longest[0] : longest[1]]
    unfurnished = [
        text for text, inside in zip(texts, parser.in_furniture, strict=True) if not inside
    ]
    kept = _joined_length(unfurnished)
    if kept >= _MAIN_AREA_MIN_CHARS and 2 * kept >= visible_chars:
        return unfurnished
    return texts


def reading_text(body: str, content_type: str, *, limit: int) -> str:
    """What the judge's passage picking reads of a page (W54, ADR-0150).

    When the visible text is at most ``limit`` characters it is exactly
    ``extract_text(body, content_type, max_chars=limit)`` (failure mode 14: a
    short page is read as before). Otherwise the main area's blocks, each with
    its whitespace collapsed, joined by "\\n" and cut at
    ``READING_TEXT_MAX_CHARS``. A plain-text page's blocks are its paragraphs
    (runs of lines between blank lines)."""
    if content_type == "text/html":
        parser = _BlockExtractor()
        parser.feed(body)
        parser.close()
        visible = " ".join(" ".join(parser.parts).split())
        if len(visible) <= limit:
            return visible
        blocks = _main_area(parser, len(visible))
    else:
        visible = " ".join(body.split())
        if len(visible) <= limit:
            return visible
        paragraphs = (" ".join(chunk.split()) for chunk in re.split(r"\n[ \t\r\f\v]*\n", body))
        blocks = [paragraph for paragraph in paragraphs if paragraph]
    return "\n".join(blocks)[:READING_TEXT_MAX_CHARS]


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
    raw: bool = False,
    robots_permit: Callable[[str, str], RobotsVerdict] | None = None,
    long_pages: bool = False,
) -> FetchedSource:
    """One bounded GET.

    ``raw`` (robots.txt only) keeps the decoded body as sent, lines intact,
    uncut and with no usable-length floor: a robots file is parsed, not read
    as page text, and is often far shorter than a page. ``robots_permit``,
    when given, is asked with the URL's ``scheme://host[:port]`` and the URL
    once the URL has passed the scheme and host checks, before anything is
    dialled. ``long_pages`` reads the page with :func:`reading_text` instead
    of :func:`extract_text`; the usable-length floor is the same."""
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
    origin = f"{parts.scheme}://{parts.netloc.lower()}"
    verdict = "allowed" if robots_permit is None else robots_permit(origin, url)
    if verdict == "refused":
        return _row(url, "refused_robots", started=started, clock=clock)
    if verdict == "unchecked":
        return _row(url, "robots_unchecked", started=started, clock=clock)
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
    outcome: Outcome
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
            if raw:
                text, outcome = decoded, "fetched"
            else:
                if long_pages:
                    text = reading_text(decoded, content_type, limit=max_text_chars)
                else:
                    text = extract_text(decoded, content_type, max_chars=max_text_chars)
                outcome = "fetched" if len(text) >= MIN_USABLE_TEXT_CHARS else "unusable"
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


#: Work bounds on one robots.txt (ADR-0148 decision 3). The file itself is
#: already capped at the fetcher's ``max_bytes`` (262,144 by default); these
#: bound the matching. A rule longer than 2,048 characters, or a file with
#: more than 4,096 Allow/Disallow lines, fails CLOSED: real files are far
#: smaller, and refusing costs only the page (the excerpt is used instead).
#: No regex is built from the file: matching uses literal
#: ``str.startswith``/``str.find`` between ``*`` wildcards, so one rule costs
#: at most about the address length times the rule length, and the limits
#: here and below bound the whole file's work.
_ROBOTS_MAX_RULE_CHARS = 2_048
_ROBOTS_MAX_RULES = 4_096
#: The longest address path plus query (after percent-encoding is put in one
#: form) that robots.txt is matched against. A longer one is not fetched
#: (ADR-0148 decision 3, the session's choice): matching cost grows with the
#: address length times the rule length. Exactly 2,048 characters is matched.
_ROBOTS_MAX_ADDRESS_CHARS = 2_048

#: RFC 3986 unreserved characters: a percent-encoding of one of these is
#: decoded before matching (RFC 9309 section 2.2.2); every other escape stays.
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
#: FIXED patterns (never built from a file) for the two normalising passes.
_NON_ASCII = re.compile(r"[^\x00-\x7f]")
_PERCENT_ESCAPE = re.compile(r"%([0-9A-Fa-f]{2})")


def _robots_normalise(text: str) -> str:
    """One form for a rule's path pattern and an address's path plus query
    (RFC 9309 section 2.2.2): characters outside ASCII are percent-encoded as
    UTF-8, an escape of an unreserved character is decoded, and every other
    escape's hex digits are upper-cased (so ``%2F`` stays ``%2F``). ``*`` and
    ``$`` are ASCII and untouched, so they stay operators in a pattern."""
    encoded = _NON_ASCII.sub(
        lambda m: "".join(f"%{b:02X}" for b in m.group(0).encode("utf-8", "surrogatepass")),
        text,
    )

    def escape(m: re.Match[str]) -> str:
        char = chr(int(m.group(1), 16))
        return char if char in _UNRESERVED else f"%{m.group(1).upper()}"

    return _PERCENT_ESCAPE.sub(escape, encoded)


def _lower_host(authority: re.Match[str]) -> str:
    userinfo, at, host_and_port = authority.group(2).rpartition("@")
    return f"{authority.group(1)}{userinfo}{at}{host_and_port.lower()}"


_ADDRESS_AUTHORITY = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*://)([^/?]*)")


def canonical_address(url: str) -> str:
    """The address a citation is compared and fetched by (ADR-0148 decision 4):
    stripped, without its fragment (search results often add one), and with
    the host lower-cased. Nothing else is rewritten."""
    return _ADDRESS_AUTHORITY.sub(_lower_host, url.strip().split("#", 1)[0], count=1)


class _RobotsTooLarge(ValueError):
    """The file is over a work bound; the caller fails closed."""


def _robots_rules(body: str, product_token: str) -> list[tuple[bool, str]]:
    """The ``(allow, pattern)`` rules RFC 9309 section 2.2 applies to
    ``product_token``: every group whose user-agent line equals it (ignoring
    case) combined, else every ``*`` group combined, else none (allow all).

    A group is one or more user-agent lines followed by its rules; a
    user-agent line after a rule starts the next group. Lines other than
    user-agent, allow and disallow are ignored. An empty rule matches nothing,
    so an empty ``Disallow:`` allows everything. Raises ``_RobotsTooLarge``
    over the work bounds above.
    """
    own: list[tuple[bool, str]] = []
    star: list[tuple[bool, str]] = []
    own_seen = False
    agents: set[str] = set()
    in_rules = False
    rule_count = 0
    for raw_line in body.removeprefix("\ufeff").splitlines():
        key, sep, value = raw_line.split("#", 1)[0].partition(":")
        key, value = key.strip().lower(), value.strip()
        if not sep:
            continue
        if key == "user-agent":
            if in_rules:
                agents, in_rules = set(), False
            agents.add(value.lower())
            own_seen = own_seen or product_token in agents
        elif key in ("allow", "disallow"):
            in_rules = True
            rule_count += 1
            if rule_count > _ROBOTS_MAX_RULES or len(value) > _ROBOTS_MAX_RULE_CHARS:
                raise _RobotsTooLarge(key)
            if value:
                rule = (key == "allow", _robots_normalise(value))
                if product_token in agents:
                    own.append(rule)
                if "*" in agents:
                    star.append(rule)
    return own if own_seen else star


def _robots_pattern_matches(pattern: str, target: str) -> bool:
    """RFC 9309 section 2.2.3: ``*`` matches any run of characters and a
    trailing ``$`` anchors the end; everything else is literal. The literal
    pieces between ``*`` are found left to right, each from where the last
    ended, which is exact for a pattern whose only wildcard is ``*``. Cost: at
    most about the address length times the rule length (each ``str.find``),
    bounded by ``_ROBOTS_MAX_ADDRESS_CHARS`` and ``_ROBOTS_MAX_RULE_CHARS``;
    no backtracking."""
    anchored = pattern.endswith("$")
    pieces = (pattern[:-1] if anchored else pattern).split("*")
    if not target.startswith(pieces[0]):
        return False
    position = len(pieces[0])
    for piece in pieces[1:-1]:
        found = target.find(piece, position)
        if found < 0:
            return False
        position = found + len(piece)
    if len(pieces) == 1:
        return not anchored or position == len(target)
    last = pieces[-1]
    if anchored:
        return target.endswith(last) and len(target) - len(last) >= position
    return target.find(last, position) >= 0


def robots_allows(
    robots_status: int | None, robots_body: str | None, url: str, user_agent: str
) -> bool:
    """Whether robots.txt lets ``user_agent`` fetch ``url`` (ADR-0148 decision 3):
    :func:`robots_verdict` is ``"allowed"``. Every case that cannot be checked
    fails closed."""
    return robots_verdict(robots_status, robots_body, url, user_agent) == "allowed"


def robots_verdict(
    robots_status: int | None, robots_body: str | None, url: str, user_agent: str
) -> RobotsVerdict:
    """What robots.txt says about ``user_agent`` fetching ``url`` (ADR-0148
    decision 3; the three-way answer is W54, ADR-0150 decision 1).

    ``robots_status`` is the status the pinned fetch read at ``/robots.txt``,
    or ``None`` when nothing could be read (a timeout, a refused address, an
    oversized or undecodable file). RFC 9309 section 2.3.1: a 4xx means no
    rules apply and a 5xx means the site is unreachable (fail closed). A 3xx
    fails closed by the session's choice: following it would need a second
    pinned fetch. A 2xx body is matched by the app's own RFC 9309 matcher
    against the URL's path plus query, both put in one percent-encoding form
    first: the longest matching rule wins and ``Allow`` wins a tie. The
    product token is ``user_agent`` up to its "/".

    ``"refused"`` only when a file was read and a rule does not allow the
    page. ``"unchecked"`` when nothing could be read, for a 3xx or 5xx, for a
    file over the work bounds, and for an address whose path plus query is
    longer than ``_ROBOTS_MAX_ADDRESS_CHARS``: the page is not fetched, but
    the site did not ask for that.
    """
    parts = urlsplit(url)
    target = _robots_normalise((parts.path or "/") + (f"?{parts.query}" if parts.query else ""))
    if robots_status is None or len(target) > _ROBOTS_MAX_ADDRESS_CHARS:
        return "unchecked"
    if 400 <= robots_status < 500:
        return "allowed"
    if not 200 <= robots_status < 300:
        return "unchecked"
    product_token = user_agent.split("/", 1)[0].strip().lower()
    try:
        rules = _robots_rules(robots_body or "", product_token)
    except _RobotsTooLarge:
        return "unchecked"
    best: tuple[int, bool] = (-1, True)
    for allow, pattern in rules:
        if _robots_pattern_matches(pattern, target):
            best = max(best, (len(pattern), allow))
    return "allowed" if best[1] else "refused"


def _robots_reading(row: FetchedSource) -> tuple[int | None, str | None]:
    """What a raw robots.txt fetch read, as ``robots_allows`` takes it."""
    if row.outcome == "fetched" and not row.truncated:
        return row.final_status, row.text
    # A 3xx or an error status is judged on the status alone; anything else
    # (a timeout, a refusal, an oversized or non-text file) read nothing.
    status = row.final_status if row.outcome in ("http_error", "refused_redirect") else None
    return status, None


def fetch_cited_pages(
    urls: Sequence[str],
    *,
    budget_seconds: float,
    per_recv_seconds: float,
    max_bytes: int,
    max_pages: int,
    max_text_chars: int,
    clock: Callable[[], float] = time.monotonic,
    respect_robots: bool = False,
    long_pages: bool = False,
) -> tuple[FetchedSource, ...]:
    """Fetch ``urls`` in order, one row per distinct URL.

    Each URL is first reduced to :func:`canonical_address` (no fragment, host
    in lower case), so two spellings of one page are one row and one fetch.
    Sequential, one GET per page, no retries. Stops dialling once ``max_pages``
    have been attempted or the shared ``budget_seconds`` deadline passes; later
    URLs, and any beyond ``MAX_PAGES_PER_HOST`` for one host, are
    ``skipped_cap``. Never raises.

    With ``respect_robots`` (W29, ADR-0148) each origin's (scheme, host and
    port) robots.txt is read once,
    inside the same deadline, before its first page; a page it does not allow
    is ``refused_robots`` (or ``robots_unchecked`` when robots.txt could not
    be read or checked) and counts toward ``max_pages`` like a fetch, so the
    caller's page-or-excerpt items stay within the page cap.

    With ``long_pages`` (W54, ADR-0150) a page's text is
    :func:`reading_text`: a page longer than ``max_text_chars`` keeps its main
    area's blocks, up to ``READING_TEXT_MAX_CHARS``, for the caller to pick
    passages from. Robots.txt is read the same way either way.
    """
    deadline = clock() + budget_seconds
    rows: list[FetchedSource] = []
    seen: set[str] = set()
    per_host: dict[str, int] = {}
    robots: dict[str, tuple[int | None, str | None]] = {}

    def permit(origin: str, url: str) -> RobotsVerdict:
        # One robots.txt read per origin per call, inside the same deadline.
        if origin not in robots:
            robots[origin] = _robots_reading(
                _fetch_one(
                    f"{origin}/robots.txt",
                    deadline=deadline,
                    per_recv_seconds=per_recv_seconds,
                    max_bytes=max_bytes,
                    max_text_chars=max_text_chars,
                    clock=clock,
                    raw=True,
                )
            )
        return robots_verdict(*robots[origin], url, USER_AGENT)

    attempted = 0
    for raw in urls:
        url = canonical_address(raw)
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
                robots_permit=permit if respect_robots else None,
                long_pages=long_pages,
            )
        )
    return tuple(rows)
