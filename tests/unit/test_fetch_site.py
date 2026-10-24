"""W88 (CHG-063 (b), CHG-067): which loads of ``/ui`` and ``/v1/session`` from
another site are refused, decided from the request's headers alone.

``fetch_site.classify(headers, own_origin, *, page)`` answers ``None`` to allow,
or the class of a refusal: ``"subresource"``, ``"frame"``, ``"navigation"``,
``"unknown"`` or ``"origin-fallback"``. ``page=True`` is ``/ui``, which may be
opened from another site only as a page (a navigation that loads a document);
``page=False`` is ``/v1/session``, which only this site, or a typed address,
may call. With no ``Sec-Fetch-Site`` the ``Origin`` header decides, and with
neither the request is allowed.

Every header value below is a literal: nothing is read back from the module
under test (AGENTS.md rule 7a). The module is imported inside each test, so a
missing module fails every test on its own rather than the whole file once.
"""

from __future__ import annotations

import ast
import importlib
import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from starlette.datastructures import Headers
from starlette.requests import Request

OWN = "https://quorum.stackclimb.com"
REFUSAL_CLASSES = {"subresource", "frame", "navigation", "unknown", "origin-fallback"}


def _fs() -> Any:
    return importlib.import_module("product_app.fetch_site")


def _headers(*pairs: tuple[str, str]) -> Headers:
    """Request headers in the order given; a name may repeat."""
    return Headers(raw=[(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in pairs])


def _site(site: str, mode: str | None = None, dest: str | None = None) -> Headers:
    pairs = [("Sec-Fetch-Site", site)]
    if mode is not None:
        pairs.append(("Sec-Fetch-Mode", mode))
    if dest is not None:
        pairs.append(("Sec-Fetch-Dest", dest))
    return _headers(*pairs)


def _ui(headers: Headers, own: str = OWN) -> str | None:
    result: str | None = _fs().classify(headers, own, page=True)
    return result


def _session(headers: Headers, own: str = OWN) -> str | None:
    result: str | None = _fs().classify(headers, own, page=False)
    return result


# --- this site and a typed address: allowed on both routes ---------------------


def test_same_origin_is_allowed_on_both_routes() -> None:
    # RED-IF: same-origin is refused on either route (the page's own fetch of /v1/session, F5).
    assert _session(_site("same-origin", "cors", "empty")) is None
    assert _session(_site("same-origin")) is None
    assert _ui(_site("same-origin", "navigate", "document")) is None
    assert _ui(_site("same-origin", "no-cors", "image")) is None


def test_none_is_allowed_on_both_routes() -> None:
    # RED-IF: a typed address, a bookmark or an extension (Sec-Fetch-Site: none) is refused (F4).
    assert _session(_site("none", "navigate", "document")) is None
    assert _ui(_site("none", "navigate", "document")) is None


# --- /ui from another site: only as a page ------------------------------------


def test_ui_opened_as_a_page_from_another_site_is_allowed() -> None:
    # RED-IF: /ui refuses a cross-site or same-site navigation to a document (a link, the Google
    #   return, a Chromium reload: F1, F2, F3).
    assert _ui(_site("cross-site", "navigate", "document")) is None
    assert _ui(_site("same-site", "navigate", "document")) is None


def test_ui_hidden_loads_from_another_site_are_subresources() -> None:
    # RED-IF: an image, script, or fetch of /ui from another site is allowed or classed as
    #   anything but "subresource".
    assert _ui(_site("cross-site", "no-cors", "image")) == "subresource"
    assert _ui(_site("cross-site", "no-cors", "script")) == "subresource"
    assert _ui(_site("cross-site", "no-cors", "empty")) == "subresource"
    assert _ui(_site("cross-site", "cors", "empty")) == "subresource"
    assert _ui(_site("same-site", "no-cors", "image")) == "subresource"


def test_ui_framed_from_another_site_is_a_frame() -> None:
    # RED-IF: the check reads Sec-Fetch-Mode alone (the textbook "allow every navigation"), so a
    #   frame, object or embed of /ui passes (F9).
    for dest in ("iframe", "frame", "object", "embed", "fencedframe"):
        assert _ui(_site("cross-site", "navigate", dest)) == "frame", dest
    assert _ui(_site("same-site", "navigate", "iframe")) == "frame"


def test_ui_navigation_without_a_dest_is_refused() -> None:
    # RED-IF: a missing Sec-Fetch-Dest is treated as "document" (F13).
    assert _ui(_site("cross-site", "navigate")) in REFUSAL_CLASSES
    assert _ui(_site("cross-site", "navigate", "")) in REFUSAL_CLASSES


def test_ui_document_without_navigate_mode_is_refused() -> None:
    # RED-IF: Dest: document alone is enough, without Mode: navigate.
    assert _ui(_site("cross-site", None, "document")) in REFUSAL_CLASSES
    assert _ui(_site("cross-site", "no-cors", "document")) in REFUSAL_CLASSES
    # Partner: the same request WITH Mode: navigate is a page and is allowed.
    assert _ui(_site("cross-site", "navigate", "document")) is None


# --- /v1/session from another site: refused in every form ---------------------


def test_session_link_from_another_site_is_a_navigation_refusal() -> None:
    # RED-IF: /ui's navigation exception is shared with /v1/session, so a cross-site link to
    #   /v1/session is allowed (A4, F11).
    assert _session(_site("cross-site", "navigate", "document")) == "navigation"
    assert _session(_site("same-site", "navigate", "document")) == "navigation"


def test_session_hidden_loads_from_another_site_are_refused() -> None:
    # RED-IF: same-site counts as this site (F10), or an image/fetch/frame of /v1/session from
    #   another site is allowed.
    assert _session(_site("cross-site", "no-cors", "image")) == "subresource"
    assert _session(_site("same-site", "no-cors", "image")) == "subresource"
    assert _session(_site("cross-site", "cors", "empty")) == "subresource"
    assert _session(_site("same-site", "cors", "empty")) == "subresource"
    assert _session(_site("cross-site", "navigate", "iframe")) == "frame"


def test_session_bare_cross_site_or_same_site_is_refused() -> None:
    # RED-IF: /v1/session reads Mode or Dest to allow anything that names another site.
    assert _session(_site("cross-site")) in REFUSAL_CLASSES
    assert _session(_site("same-site")) in REFUSAL_CLASSES


# --- values the table does not know -------------------------------------------


def test_an_unknown_site_value_is_refused_as_unknown_on_both_routes() -> None:
    # RED-IF: an unrecognised Sec-Fetch-Site value is allowed, or treated as missing (Origin would
    #   then decide).
    for value in ("cross-origin", "same_origin", "evil"):
        assert _session(_site(value)) == "unknown", value
        assert _ui(_site(value, "navigate", "document")) == "unknown", value


# --- header parsing: case, spaces, empty, repeated (F22) ----------------------


def test_values_are_compared_case_insensitively_and_stripped() -> None:
    # RED-IF: "Cross-Site" or " none " is compared as written, so an odd-cased refusal slips
    #   through or a real visit is refused.
    assert _session(_site("Cross-Site", "No-CORS", "Image")) == "subresource"
    assert _ui(_site("CROSS-SITE", "NO-CORS", "IMAGE")) == "subresource"
    assert _ui(_site("Cross-Site", "Navigate", "Document")) is None
    assert _ui(_site("Cross-Site", "Navigate", "IFrame")) == "frame"
    assert _session(_site("  same-origin  ", "cors", "empty")) is None
    assert _ui(_site(" none ", " navigate ", " document ")) is None


def test_an_empty_site_value_is_treated_as_missing() -> None:
    # RED-IF: an empty Sec-Fetch-Site is refused as unknown, or skips the Origin fallback.
    assert _session(_site("")) is None
    assert _ui(_site("   ")) is None
    with_foreign_origin = _headers(("Sec-Fetch-Site", ""), ("Origin", "https://evil.example"))
    assert _session(with_foreign_origin) == "origin-fallback"
    assert _ui(with_foreign_origin) == "origin-fallback"


def test_a_repeated_site_header_is_refused_if_any_value_is_not_allowed() -> None:
    # RED-IF: only the first (or last) of two Sec-Fetch-Site values is read.
    first_ours = _headers(("Sec-Fetch-Site", "same-origin"), ("Sec-Fetch-Site", "cross-site"))
    last_ours = _headers(("Sec-Fetch-Site", "cross-site"), ("Sec-Fetch-Site", "same-origin"))
    for headers in (first_ours, last_ours):
        assert _session(headers) in REFUSAL_CLASSES
        assert _ui(headers) in REFUSAL_CLASSES
    # Partner: two allowed values are still allowed.
    both_ours = _headers(("Sec-Fetch-Site", "same-origin"), ("Sec-Fetch-Site", "none"))
    assert _session(both_ours) is None
    assert _ui(both_ours) is None


def test_a_repeated_dest_or_mode_on_ui_is_refused_if_any_value_is_not_a_page() -> None:
    # RED-IF: /ui reads only one of two Sec-Fetch-Dest or Sec-Fetch-Mode values, so "document"
    #   beside "iframe" passes.
    two_dests = _headers(
        ("Sec-Fetch-Site", "cross-site"),
        ("Sec-Fetch-Mode", "navigate"),
        ("Sec-Fetch-Dest", "document"),
        ("Sec-Fetch-Dest", "iframe"),
    )
    two_modes = _headers(
        ("Sec-Fetch-Site", "cross-site"),
        ("Sec-Fetch-Mode", "no-cors"),
        ("Sec-Fetch-Mode", "navigate"),
        ("Sec-Fetch-Dest", "document"),
    )
    assert _ui(two_dests) in REFUSAL_CLASSES
    assert _ui(two_modes) in REFUSAL_CLASSES


# --- no Sec-Fetch-Site: Origin decides (CHG-063 (b)) --------------------------


def test_neither_header_is_allowed_on_both_routes() -> None:
    # RED-IF: a request with neither Sec-Fetch-Site nor Origin is refused (curl, scripts, old
    #   browsers: the owner chose "Allow").
    assert _session(_headers()) is None
    assert _ui(_headers()) is None
    assert _ui(_headers(("Accept", "text/html"))) is None


def test_our_own_origin_is_allowed_without_sec_fetch_site() -> None:
    # RED-IF: the fallback refuses this site's own Origin.
    assert _session(_headers(("Origin", "https://quorum.stackclimb.com"))) is None
    assert _ui(_headers(("Origin", "https://quorum.stackclimb.com"))) is None
    fly = "https://quorum-ai.fly.dev"
    assert _session(_headers(("Origin", fly)), own=fly) is None
    local = "http://127.0.0.1:18085"
    assert _session(_headers(("Origin", local)), own=local) is None


def test_our_own_origin_is_compared_as_a_browser_compares_it() -> None:
    # RED-IF: the comparison is a raw string match, so an upper-case host or an explicit default
    #   port (:443) makes our own origin look foreign (normalised like google_signin._origin).
    assert _session(_headers(("Origin", "https://Quorum.StackClimb.com"))) is None
    assert _session(_headers(("Origin", "https://quorum.stackclimb.com:443"))) is None
    assert _session(_headers(("Origin", "http://127.0.0.1:80")), own="http://127.0.0.1") is None


def test_a_foreign_origin_without_sec_fetch_site_is_refused() -> None:
    # RED-IF: the fallback compares only the host, a fixed list of hosts, or a prefix (F7).
    foreign = (
        "https://evil.example",
        "http://quorum.stackclimb.com",  # our host, the wrong scheme
        "https://quorum-ai.fly.dev",  # the app's other host is still another origin
        "https://quorum.stackclimb.com.evil.example",
        "https://www.stackclimb.com",
        "https://quorum.stackclimb.com:8443",
    )
    for origin in foreign:
        assert _session(_headers(("Origin", origin))) == "origin-fallback", origin
        assert _ui(_headers(("Origin", origin))) == "origin-fallback", origin
    assert (
        _session(_headers(("Origin", "http://127.0.0.1:18086")), own="http://127.0.0.1:18085")
        == "origin-fallback"
    )


def test_origin_null_without_sec_fetch_site_is_refused() -> None:
    # RED-IF: Origin: null (an opaque origin, e.g. a sandboxed frame) is treated as no Origin.
    assert _session(_headers(("Origin", "null"))) == "origin-fallback"
    assert _ui(_headers(("Origin", "null"))) == "origin-fallback"
    assert _ui(_headers(("Origin", "NULL"))) == "origin-fallback"


def test_a_repeated_origin_is_refused_if_any_value_is_foreign() -> None:
    # RED-IF: only the first of two Origin values is compared.
    headers = _headers(
        ("Origin", "https://quorum.stackclimb.com"), ("Origin", "https://evil.example")
    )
    assert _session(headers) == "origin-fallback"
    assert _ui(headers) == "origin-fallback"


def test_sec_fetch_site_decides_when_both_are_present() -> None:
    # RED-IF: a cross-site load with our own Origin is allowed because the Origin looked like ours.
    headers = _headers(
        ("Sec-Fetch-Site", "cross-site"),
        ("Sec-Fetch-Mode", "cors"),
        ("Sec-Fetch-Dest", "empty"),
        ("Origin", "https://quorum.stackclimb.com"),
    )
    assert _session(headers) == "subresource"


# --- cross_site_refusal(request, page=...): own origin from the request --------


def _request(
    *pairs: tuple[str, str], scheme: str = "https", host: str = "quorum.stackclimb.com"
) -> Request:
    raw = [(b"host", host.encode("latin-1"))]
    raw += [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in pairs]
    port = 443 if scheme == "https" else 80
    scope = {
        "type": "http",
        "method": "GET",
        "scheme": scheme,
        "server": (host, port),
        "path": "/v1/session",
        "raw_path": b"/v1/session",
        "query_string": b"",
        "headers": raw,
        "client": ("81.2.69.9", 50000),
        "root_path": "",
        "http_version": "1.1",
    }
    return Request(scope)


def test_the_request_s_own_scheme_and_host_are_its_origin_on_both_hosts() -> None:
    # RED-IF: own origin is a fixed host list or ignores the request's scheme (F7: two hosts serve
    #   the app; behind Fly the scheme comes from X-Forwarded-Proto into scope["scheme"]).
    refusal = _fs().cross_site_refusal
    for host in ("quorum.stackclimb.com", "quorum-ai.fly.dev"):
        assert refusal(_request(("Origin", f"https://{host}"), host=host), page=False) is None
        assert refusal(_request(("Origin", f"https://{host}"), host=host), page=True) is None
        refused = refusal(_request(("Origin", "https://evil.example"), host=host), page=False)
        assert refused is not None and refused.status_code == 403
    other = refusal(
        _request(("Origin", "https://quorum-ai.fly.dev"), host="quorum.stackclimb.com"), page=False
    )
    assert other is not None and other.status_code == 403
    # The same https Origin against a request the app sees as plain http is foreign.
    plain = refusal(
        _request(("Origin", "https://quorum.stackclimb.com"), scheme="http"), page=False
    )
    assert plain is not None and plain.status_code == 403


def _set_cookies(response: Any) -> list[str]:
    return [v for k, v in response.raw_headers if k.lower() == b"set-cookie"]


def test_the_session_refusal_is_a_403_with_the_fixed_body() -> None:
    # RED-IF: the /v1/session refusal is not 403, sets a cookie, may be cached, or its body
    #   differs from the planned envelope.
    response = _fs().cross_site_refusal(
        _request(("Sec-Fetch-Site", "cross-site"), ("Sec-Fetch-Mode", "no-cors")), page=False
    )
    assert response is not None
    assert response.status_code == 403
    assert json.loads(bytes(response.body)) == {
        "detail": {
            "code": "CROSS_SITE_REFUSED",
            "message": "This request came from another site, so it cannot open or renew a session.",
        }
    }
    assert response.headers["cache-control"] == "no-store"
    assert _set_cookies(response) == []


class _Anchors(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.anchors.append(dict(attrs))


def test_the_ui_refusal_is_a_short_html_403_with_a_link_back() -> None:
    # RED-IF: the /ui refusal is not a 403 HTML page, sets a cookie, may be cached, or lacks the
    #   same-origin link <a id="cross-site-back" href="/ui">.
    response = _fs().cross_site_refusal(
        _request(
            ("Sec-Fetch-Site", "cross-site"),
            ("Sec-Fetch-Mode", "navigate"),
            ("Sec-Fetch-Dest", "iframe"),
        ),
        page=True,
    )
    assert response is not None
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    assert _set_cookies(response) == []
    parser = _Anchors()
    parser.feed(bytes(response.body).decode("utf-8"))
    back = [a for a in parser.anchors if a.get("id") == "cross-site-back"]
    assert len(back) == 1, parser.anchors
    assert back[0].get("href") == "/ui"
    # Short: nobody but a person on a very old browser ever reads it in full.
    assert len(response.body) < 4096


def test_an_allowed_request_gets_no_response() -> None:
    # RED-IF: cross_site_refusal answers something other than None for the page's own same-origin
    #   call.
    request = _request(
        ("Sec-Fetch-Site", "same-origin"), ("Sec-Fetch-Mode", "cors"), ("Sec-Fetch-Dest", "empty")
    )
    assert _fs().cross_site_refusal(request, page=False) is None
    assert _fs().cross_site_refusal(_request(), page=True) is None


# --- the module shape the plan fixes -------------------------------------------


def test_the_module_defines_no_decorated_function() -> None:
    # RED-IF: fetch_site.py defines a decorated function (the decorated-function cap is 55 of 55,
    #   ADR-0142), lacks classify or cross_site_refusal, or does not exist.
    path = Path(_fs().__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    names = {f.name for f in functions}
    assert {"classify", "cross_site_refusal"} <= names, names
    assert [f.name for f in functions if f.decorator_list] == []
