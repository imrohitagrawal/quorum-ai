"""W88 (CHG-063 (b), CHG-067): refuse another site's loads of ``/ui`` and ``/v1/session``.

Both routes open or renew a browser session, and each new session counts
against the network's small daily allowance. A page on another site could
load either route without the visitor ever seeing it, using up that
allowance or replacing the token an open tab holds. The browser says where a
request came from in ``Sec-Fetch-Site`` (and how it was made in
``Sec-Fetch-Mode`` and ``Sec-Fetch-Dest``), and a script cannot set those
headers, so the decision is made from them alone:

* A prefetch (``Sec-Purpose`` or the older ``Purpose`` naming ``prefetch``,
  a prerender included) is refused on both routes, whatever else the request
  says. Round 1 of W88's review MEASURED Chromium fetching both routes from
  another site's ``<script type="speculationrules">`` with
  ``Sec-Fetch-Site: none``, the value of a typed address, so the rule below
  alone let it open a counted session. This site's own pages never prefetch.
* ``same-origin`` and ``none`` (this site's own pages, a typed address or a
  bookmark) are allowed on both routes.
* From another site, including a neighbour on the same registrable domain
  (``same-site``), ``/ui`` may only be opened as a page: a navigation that
  loads a document. An image, a script, a fetch or a frame of it is refused.
  ``/v1/session`` is refused in every form, a link included, because only
  this site's own page script ever needs it.
* An unknown ``Sec-Fetch-Site`` value is refused.
* Without ``Sec-Fetch-Site`` (an older browser) the ``Origin`` header decides:
  another origin, or ``null``, is refused; this site's own origin, or no
  ``Origin`` at all, is allowed, as before W88.

The check is a plain function called first in each handler, before any
counter, limiter or session is touched, so a refusal opens and counts nothing.
The refusal is returned from the handler, so the security headers, the
request id and the request metrics still apply to it. No decorators here: the
decorated-function cap is full (``tests/unit/test_mutation_test_set_integrity.py``).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from urllib.parse import urlsplit

from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
from starlette.datastructures import Headers
from starlette.requests import Request

from product_app.google_signin import _origin

_log = logging.getLogger(__name__)

#: ``Sec-Fetch-Site`` values that mean this site, or no site (a typed address).
_OURS = frozenset({"same-origin", "none"})
#: ``Sec-Fetch-Site`` values that name another site. ``same-site`` counts as
#: another site: neighbours on the same domain are hosted elsewhere, and
#: their images carry this site's cookie.
_ANOTHER_SITE = frozenset({"cross-site", "same-site"})
#: ``Sec-Fetch-Dest`` values of a frame or an embedded object. These are
#: navigations too, which is why ``Sec-Fetch-Mode`` alone cannot decide.
_FRAME_DESTS = frozenset({"iframe", "frame", "object", "embed", "fencedframe"})

#: The headers in which a browser marks a load it makes ahead of time, before
#: anyone opens the page: ``Sec-Purpose``, and ``Purpose``, its older name.
_PURPOSE_HEADERS = ("sec-purpose", "purpose")

#: The refusal classes, the only words ``/status`` and the log ever carry.
CLASSES = ("subresource", "frame", "navigation", "unknown", "origin-fallback", "prefetch")
#: The two routes this module guards, keyed by ``page``.
_ROUTES = {True: "/ui", False: "/v1/session"}

_lock = threading.Lock()
_refusals: dict[tuple[str, str], int] = {}

SESSION_REFUSAL_CODE = "CROSS_SITE_REFUSED"
SESSION_REFUSAL_MESSAGE = (
    "This request came from another site, so it cannot open or renew a session."
)

#: The ``/ui`` refusal. Short and plain, with no script (the page's
#: Content-Security-Policy applies to it). A person sees it only when a
#: browser that does not say how a page was opened lands here (a hidden load
#: or a prefetch is never shown), so it does not guess why; the link back is
#: same-origin, so it is always allowed.
_PAGE_REFUSAL_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Quorum-AI: this page cannot be opened this way</title>
  </head>
  <body>
    <main>
      <h1>This page cannot be opened this way</h1>
      <p>This page was opened in a way this site does not allow.
        Nothing was started or counted.</p>
      <p><a id="cross-site-back" href="/ui">Open Quorum-AI</a></p>
    </main>
  </body>
</html>
"""


class CrossSiteRefusalDetail(BaseModel):
    code: str
    message: str


class CrossSiteRefusalResponse(BaseModel):
    detail: CrossSiteRefusalDetail


#: The 403 for ``/v1/session``'s ``responses=``.
SESSION_RESPONSES: dict[int | str, dict[str, object]] = {
    403: {
        "model": CrossSiteRefusalResponse,
        "description": "The request came from another site (CROSS_SITE_REFUSED).",
    },
}
#: The 403 for ``/ui``'s ``responses=``.
PAGE_RESPONSES: dict[int | str, dict[str, object]] = {
    403: {
        "description": (
            "The page was opened in a way this site does not allow (for example, loaded hidden"
            " by another site, or prefetched)."
        ),
        "content": {"text/html": {"schema": {"type": "string"}}},
    },
}


def _values(headers: Headers, name: str) -> set[str]:
    """Every value of ``name``, stripped and lower-cased, a repeated header or
    a comma-joined one included. Empty values are dropped: empty is missing."""
    found: set[str] = set()
    for raw in headers.getlist(name):
        for part in raw.split(","):
            value = part.strip().lower()
            if value:
                found.add(value)
    return found


def _normalised(origin: str) -> tuple[str, str, int | None] | None:
    """Scheme, host and port as a browser compares origins (the host
    lower-cased, a default port dropped), or ``None`` when ``origin`` is not
    a plain http(s) origin (``null`` included)."""
    try:
        parts = urlsplit(origin)
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        return None
    if parts.username is not None or parts.path not in ("", "/") or parts.query:
        return None
    host, effective = _origin(scheme, parts.hostname, port)
    return scheme, host, effective


def _is_prefetch(headers: Headers) -> bool:
    """Whether ``Sec-Purpose`` or ``Purpose`` names ``prefetch`` as a token:
    ``prefetch``, ``prefetch;prerender``, ``prefetch;anonymous-client-ip``,
    in any case and spacing. A word that only contains it does not count."""
    return any(
        token.strip() == "prefetch"
        for name in _PURPOSE_HEADERS
        for value in _values(headers, name)
        for token in value.split(";")
    )


def _all_ours(origins: Iterable[str], own_origin: str) -> bool:
    own = _normalised(own_origin)
    return own is not None and all(_normalised(o) == own for o in origins)


def classify(headers: Headers, own_origin: str, *, page: bool) -> str | None:
    """``None`` to allow the request, else its refusal class (one of
    :data:`CLASSES`). ``page=True`` is ``/ui``; ``page=False`` is
    ``/v1/session``. ``own_origin`` is this request's own origin, for
    example ``https://quorum.stackclimb.com``."""
    # First: a prefetch arrives as ``none`` (a typed address) when another
    # site's page asks for it, so the allow below must not see it.
    if _is_prefetch(headers):
        return "prefetch"
    sites = _values(headers, "sec-fetch-site")
    if not sites:
        origins = _values(headers, "origin")
        if not origins or _all_ours(origins, own_origin):
            return None
        return "origin-fallback"
    if not sites <= _OURS | _ANOTHER_SITE:
        return "unknown"
    if sites <= _OURS:
        return None
    modes = _values(headers, "sec-fetch-mode")
    dests = _values(headers, "sec-fetch-dest")
    if dests & _FRAME_DESTS:
        return "frame"
    if page and modes == {"navigate"} and dests == {"document"}:
        return None
    if "navigate" in modes:
        return "navigation"
    return "subresource"


def _record(route: str, kind: str) -> None:
    with _lock:
        _refusals[(route, kind)] = _refusals.get((route, kind), 0) + 1
    # The route and the class only, never a header value: those come from
    # the request and would let anyone write into the log.
    _log.info("refused another site's request: route=%s class=%s", route, kind)


def status_snapshot() -> dict[str, dict[str, int]]:
    """``/status``: refusals since the process started, per route and class."""
    with _lock:
        return {
            route: {kind: _refusals.get((route, kind), 0) for kind in CLASSES}
            for route in _ROUTES.values()
        }


def _own_origin(request: Request) -> str:
    """The request's own origin: its scheme (set from a trusted proxy's
    ``X-Forwarded-Proto`` by ``auth.VisitorAddressMiddleware``) and the host
    and port it was addressed to. Never a fixed list: two hosts serve the app."""
    return f"{request.url.scheme}://{request.url.netloc}"


def cross_site_refusal(request: Request, *, page: bool) -> Response | None:
    """The 403 for a request another site made, or ``None`` to go on.

    ``page=True`` answers for ``/ui`` with a short HTML page; ``page=False``
    for ``/v1/session`` with the JSON error envelope. Neither sets a cookie,
    and neither may be cached."""
    kind = classify(request.headers, _own_origin(request), page=page)
    if kind is None:
        return None
    _record(_ROUTES[page], kind)
    no_store = {"Cache-Control": "no-store"}
    if page:
        return HTMLResponse(_PAGE_REFUSAL_HTML, status_code=403, headers=no_store)
    return JSONResponse(
        status_code=403,
        content={"detail": {"code": SESSION_REFUSAL_CODE, "message": SESSION_REFUSAL_MESSAGE}},
        headers=no_store,
    )
