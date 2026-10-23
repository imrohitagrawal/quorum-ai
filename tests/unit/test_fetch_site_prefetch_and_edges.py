"""W88 round 1: a browser's prefetch of ``/ui`` or ``/v1/session`` is refused,
and the edges of ``fetch_site`` that round 1 found no test for.

Round 1's break-it review (B1) MEASURED that Chromium 149, on a page of another
site carrying ``<script type="speculationrules">``, fetches both routes in the
background with ``Sec-Fetch-Site: none`` (the value of a typed address),
``Sec-Purpose: prefetch``, no ``Origin`` and no cookie. ``none`` is allowed, so
each such fetch opened a counted session the visitor never saw. ``MEASURED``
below is the header set that browser actually sent (the orchestrator's
reproduction, ``hits.jsonl``), copied as literals.

Every value is a literal (AGENTS.md rule 7a); nothing is read back from the
module under test.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.responses import Response
from starlette.datastructures import Headers
from starlette.requests import Request

from product_app import fetch_site
from product_app.main import _add_vary

OWN = "https://quorum.stackclimb.com"

#: The headers Chromium 149 sent for a speculation-rules prefetch of /ui
#: from a page on another site (the same set came for /v1/session).
MEASURED = (
    ("host", "127.0.0.1:18231"),
    ("connection", "keep-alive"),
    ("upgrade-insecure-requests", "1"),
    ("sec-purpose", "prefetch"),
    (
        "accept",
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
        "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    ),
    ("sec-ch-ua", '"HeadlessChrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"'),
    ("sec-ch-ua-platform", '"macOS"'),
    ("sec-ch-ua-mobile", "?0"),
    ("sec-fetch-site", "none"),
    ("sec-fetch-mode", "navigate"),
    ("sec-fetch-dest", "document"),
    ("referer", "http://localhost:18232/"),
    (
        "user-agent",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) HeadlessChrome/149.0.0.0 Safari/537.36",
    ),
    ("accept-encoding", "gzip, deflate, br"),
)
MEASURED_OWN = "http://127.0.0.1:18231"


def _headers(*pairs: tuple[str, str]) -> Headers:
    return Headers(raw=[(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in pairs])


def _without(
    name: str, pairs: tuple[tuple[str, str], ...] = MEASURED
) -> tuple[tuple[str, str], ...]:
    return tuple(p for p in pairs if p[0] != name)


def _with_purpose(name: str, value: str) -> Headers:
    return _headers(*_without("sec-purpose"), (name, value))


def _both(headers: Headers, own: str = MEASURED_OWN) -> tuple[str | None, str | None]:
    return (
        fetch_site.classify(headers, own, page=True),
        fetch_site.classify(headers, own, page=False),
    )


# --- B1: a prefetch is refused on both routes ------------------------------------


def test_the_measured_prefetch_is_refused_on_both_routes() -> None:
    # RED-IF: classify allows Chromium's speculation-rules prefetch (Sec-Fetch-Site: none plus
    #   Sec-Purpose: prefetch), on either route, or classes it as anything but "prefetch" (B1).
    assert _both(_headers(*MEASURED)) == ("prefetch", "prefetch")
    # Partner: the same headers without Sec-Purpose are a typed address, allowed on both.
    assert _both(_headers(*_without("sec-purpose"))) == (None, None)


@pytest.mark.parametrize(
    "value",
    [
        "prefetch;prerender",
        "prefetch;anonymous-client-ip",
        "Prefetch",
        "  PREFETCH  ",
        "prefetch ; prerender",
    ],
)
def test_every_form_of_a_prefetch_purpose_is_refused(value: str) -> None:
    # RED-IF: only the exact lower-case word "prefetch" is read, so a prerender
    #   ("prefetch;prerender"), a private prefetch, or another case or spacing gets through.
    assert _both(_with_purpose("Sec-Purpose", value)) == ("prefetch", "prefetch")


def test_the_older_purpose_header_is_read_too() -> None:
    # RED-IF: only Sec-Purpose is read, so a browser that names a prefetch with the older
    #   Purpose header opens a session.
    assert _both(_with_purpose("Purpose", "prefetch")) == ("prefetch", "prefetch")
    # Partner: a Purpose that names something else changes nothing.
    assert _both(_with_purpose("Purpose", "preview")) == (None, None)


def test_a_prefetch_from_this_site_or_another_is_refused_too() -> None:
    # RED-IF: the prefetch check runs after the same-origin allow, or only on Sec-Fetch-Site: none.
    for site in ("same-origin", "cross-site", "same-site"):
        headers = _headers(
            ("Sec-Fetch-Site", site),
            ("Sec-Fetch-Mode", "navigate"),
            ("Sec-Fetch-Dest", "document"),
            ("Sec-Purpose", "prefetch"),
        )
        assert _both(headers, own=OWN) == ("prefetch", "prefetch"), site
    # And with no Sec-Fetch-Site at all (the Origin fallback is not reached).
    assert _both(_headers(("Sec-Purpose", "prefetch")), own=OWN) == ("prefetch", "prefetch")


def test_a_purpose_that_only_contains_the_letters_is_not_a_prefetch() -> None:
    # RED-IF: the check is a substring match, so a value such as "noprefetch" is refused.
    assert _both(_with_purpose("Sec-Purpose", "noprefetch")) == (None, None)
    assert _both(_with_purpose("Sec-Purpose", "prerender-only")) == (None, None)


def test_prefetch_is_a_counted_class() -> None:
    # RED-IF: "prefetch" is missing from fetch_site.CLASSES, so /status never shows it.
    snapshot = fetch_site.status_snapshot()
    assert set(snapshot) == {"/ui", "/v1/session"}
    for by_class in snapshot.values():
        assert set(by_class) == {
            "subresource",
            "frame",
            "navigation",
            "unknown",
            "origin-fallback",
            "prefetch",
        }


# --- edges round 1 found untested (B2, D1, F-c) ------------------------------------


@pytest.mark.parametrize(
    "origin",
    [
        "https://quorum.stackclimb.com:99999",  # a port out of range: urlsplit raises
        "https://quorum.stackclimb.com:abc",  # a port that is not a number
    ],
)
def test_an_origin_with_a_bad_port_is_foreign(origin: str) -> None:
    # RED-IF: a bad port in Origin raises (a 500) or is read as this site's own origin
    #   (fetch_site.py, the ValueError branch of _normalised).
    assert _both(_headers(("Origin", origin)), own=OWN) == ("origin-fallback", "origin-fallback")


@pytest.mark.parametrize(
    "origin",
    [
        "https://quorum.stackclimb.com/ui",
        "https://quorum.stackclimb.com/?a=1",
        "https://quorum.stackclimb.com?a=1",
        "https://user@quorum.stackclimb.com",
        "https://user:pw@quorum.stackclimb.com",
    ],
)
def test_an_origin_with_a_path_a_query_or_a_user_part_is_foreign(origin: str) -> None:
    # RED-IF: the user-part, path or query check of _normalised is removed, so a value no browser
    #   sends as an Origin is taken for this site's own.
    assert _both(_headers(("Origin", origin)), own=OWN) == ("origin-fallback", "origin-fallback")
    # Partner: this site's own origin, bare or with a trailing slash, is allowed.
    assert _both(_headers(("Origin", OWN)), own=OWN) == (None, None)
    assert _both(_headers(("Origin", OWN + "/")), own=OWN) == (None, None)


def test_an_upper_case_origin_matches_this_site_whichever_side_is_upper_case() -> None:
    # RED-IF: the scheme or host is compared as written, so this site's own origin in upper case
    #   (in the Origin, or in the Host the request was addressed to) looks foreign.
    upper = "HTTPS://QUORUM.STACKCLIMB.COM"
    assert _both(_headers(("Origin", upper)), own=OWN) == (None, None)
    assert _both(_headers(("Origin", OWN)), own=upper) == (None, None)
    request = _request(("Origin", upper), host="QUORUM.STACKCLIMB.COM")
    assert fetch_site.cross_site_refusal(request, page=False) is None
    # Partner: another host in upper case is still foreign.
    assert _both(_headers(("Origin", "HTTPS://EVIL.EXAMPLE")), own=OWN) == (
        "origin-fallback",
        "origin-fallback",
    )


def test_a_known_site_value_beside_an_unknown_one_is_unknown() -> None:
    # RED-IF: the unknown-value rule reads "refuse only if no value is known", so
    #   "cross-site, evil" on a page load of /ui is allowed.
    headers = _headers(
        ("Sec-Fetch-Site", "cross-site, evil"),
        ("Sec-Fetch-Mode", "navigate"),
        ("Sec-Fetch-Dest", "document"),
    )
    assert _both(headers, own=OWN) == ("unknown", "unknown")


def test_a_comma_joined_dest_naming_a_frame_is_refused() -> None:
    # RED-IF: the comma split is removed or Dest is checked with "document in dests", so
    #   "document, iframe" passes as a page.
    headers = _headers(
        ("Sec-Fetch-Site", "cross-site"),
        ("Sec-Fetch-Mode", "navigate"),
        ("Sec-Fetch-Dest", "document, iframe"),
    )
    assert _both(headers, own=OWN) == ("frame", "frame")
    image = _headers(
        ("Sec-Fetch-Site", "cross-site"),
        ("Sec-Fetch-Mode", "navigate"),
        ("Sec-Fetch-Dest", "document, image"),
    )
    assert fetch_site.classify(image, OWN, page=True) == "navigation"


def test_a_comma_joined_allowed_site_value_is_allowed() -> None:
    # RED-IF: the comma split is removed, so "same-origin, same-origin" becomes one unknown value
    #   and this site's own request is refused.
    for value in ("same-origin, same-origin", "same-origin,none"):
        headers = _headers(
            ("Sec-Fetch-Site", value), ("Sec-Fetch-Mode", "cors"), ("Sec-Fetch-Dest", "empty")
        )
        assert _both(headers, own=OWN) == (None, None), value


# --- main._add_vary keeps what a response already says (F-a) -----------------------


def _vary_lines(response: Response) -> list[str]:
    return [v.decode("latin-1") for k, v in response.raw_headers if k.lower() == b"vary"]


def test_add_vary_keeps_an_existing_vary_and_adds_each_name_once() -> None:
    # RED-IF: _add_vary replaces an existing Vary (a compression layer's Accept-Encoding would be
    #   lost) or adds a name the response already varies on a second time.
    response = Response("x", headers={"Vary": "Accept-Encoding, sec-fetch-site"})
    _add_vary(response, ("Sec-Fetch-Site", "Sec-Fetch-Mode", "Origin"))
    assert _vary_lines(response) == ["Accept-Encoding, sec-fetch-site, Sec-Fetch-Mode, Origin"]
    # Twice is the same as once.
    _add_vary(response, ("Sec-Fetch-Site", "Sec-Fetch-Mode", "Origin"))
    assert _vary_lines(response) == ["Accept-Encoding, sec-fetch-site, Sec-Fetch-Mode, Origin"]


def test_add_vary_folds_two_existing_vary_lines_into_one() -> None:
    # RED-IF: only the first of two Vary lines is kept, or a second line is left beside the merge.
    response = Response("x")
    response.raw_headers.append((b"vary", b"Accept-Encoding"))
    response.raw_headers.append((b"vary", b"Cookie"))
    _add_vary(response, ("Origin",))
    assert _vary_lines(response) == ["Accept-Encoding, Cookie, Origin"]


def test_add_vary_on_a_response_with_no_vary() -> None:
    # Partner of the two above: with nothing there, the names are the whole header.
    response = Response("x")
    _add_vary(response, ("Sec-Fetch-Site", "Origin"))
    assert _vary_lines(response) == ["Sec-Fetch-Site, Origin"]


def _request(*pairs: tuple[str, str], host: str = "quorum.stackclimb.com") -> Request:
    raw = [(b"host", host.encode("latin-1"))]
    raw += [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in pairs]
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "scheme": "https",
        "server": (host, 443),
        "path": "/v1/session",
        "raw_path": b"/v1/session",
        "query_string": b"",
        "headers": raw,
        "client": ("81.2.69.9", 50000),
        "root_path": "",
        "http_version": "1.1",
    }
    return Request(scope)
