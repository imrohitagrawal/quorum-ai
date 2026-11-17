"""OD-1: Prometheus ``/metrics`` exposition — RED-first contract.

Asserts the observable behaviour the observability backbone depends on:

* ``GET /metrics`` returns 200 with the Prometheus text exposition format.
* Requests to a route move that route's counter by exactly the number sent,
  grouped by the route TEMPLATE (never the raw path/UUID — cardinality guard).
* A 5xx response increments the 5xx series.
* ``/metrics`` itself is excluded from instrumentation (self-scrape guard).
* ``/metrics`` does not appear in the OpenAPI schema, so the byte-faithful
  ``openapi.yaml`` drift guard and the Schemathesis conformance gate are
  unaffected by a non-OpenAPI plain-text route.
"""

from __future__ import annotations

import re
import uuid

from fastapi.testclient import TestClient

from product_app.main import STATIC_DIR, app


def _scrape(client: TestClient) -> str:
    response = client.get("/metrics")
    assert response.status_code == 200
    return response.text


def _requests_total(text: str, handler: str, status: str) -> float:
    """Sum http request-count samples for a handler + status class."""
    total = 0.0
    found = False
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        if "http" not in line or "_total" not in line.split("{")[0]:
            continue
        if f'handler="{handler}"' in line and f'status="{status}"' in line:
            total += float(line.rsplit(" ", 1)[1])
            found = True
    return total if found else 0.0


def test_metrics_returns_prometheus_text_format() -> None:
    client = TestClient(app)
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    # Prometheus exposition format: HELP/TYPE comment lines present.
    assert "# TYPE" in response.text


def test_request_counter_moves_by_exactly_the_requests_sent() -> None:
    client = TestClient(app)
    before = _requests_total(_scrape(client), "/health", "2xx")
    n = 3
    for _ in range(n):
        assert client.get("/health").status_code == 200
    after = _requests_total(_scrape(client), "/health", "2xx")
    assert after == before + n


def test_5xx_increments_error_series() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    handler = "/__od1_boom__"
    before = _requests_total(_scrape(client), handler, "5xx")

    # Force a real unhandled 5xx via a throwaway route; the instrumentator
    # records it under the route template with status class "5xx".
    @app.get(handler)
    def _boom() -> None:  # pragma: no cover - raises immediately
        raise RuntimeError("forced 5xx for metrics test")

    try:
        response = client.get(handler)
        assert response.status_code == 500
        after = _requests_total(_scrape(client), handler, "5xx")
        assert after == before + 1
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != handler]


def test_metrics_endpoint_excluded_from_self_instrumentation() -> None:
    client = TestClient(app)
    _scrape(client)  # first scrape — would be counted if not excluded
    text = _scrape(client)  # second scrape shows any /metrics samples
    assert 'handler="/metrics"' not in text


def test_route_templates_not_raw_paths_as_labels() -> None:
    client = TestClient(app)
    raw_id = "0d9c7a52-aaaa-bbbb-cccc-000000000000"
    # 404/422 either way — what matters is the label value, not the status.
    client.get(f"/v1/query-runs/{raw_id}")
    text = _scrape(client)
    assert raw_id not in text
    uuid_re = re.compile(
        r'handler="[^"]*[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}'
        r'-[0-9a-f]{4}-[0-9a-f]{12}[^"]*"'
    )
    assert not uuid_re.search(text)


def test_metrics_not_in_openapi_schema() -> None:
    assert "/metrics" not in app.openapi()["paths"]


def test_bogus_http_method_never_becomes_a_label_value() -> None:
    """Adversarial review finding (OD-1, major): attacker-chosen method tokens.

    Every unique bogus HTTP method a public client sends would otherwise mint
    a new persistent time series (unauthenticated slow memory growth + scrape
    blowup).  Non-standard methods must be normalised to the ``OTHER``
    sentinel before instrumentation sees them.
    """
    client = TestClient(app)
    client.request("FOOBAR42XYZ", "/health")
    text = _scrape(client)
    assert 'method="FOOBAR42XYZ"' not in text
    assert 'method="OTHER"' in text


def test_404_path_containing_metrics_is_still_counted() -> None:
    """Adversarial review finding (OD-1, minor): unanchored exclusion regex.

    ``excluded_handlers`` is applied with ``re.search`` against the raw path
    for untemplated requests, so a bare ``/metrics`` pattern silently drops
    any 404 whose path merely contains the substring — hiding scanner
    traffic.  The pattern must be anchored to the exact route.
    """
    client = TestClient(app)
    before = _requests_total(_scrape(client), "none", "4xx")
    assert client.get("/probe/metrics/x").status_code == 404
    after = _requests_total(_scrape(client), "none", "4xx")
    assert after == before + 1
    # And the real /metrics route stays excluded (self-scrape guard intact).
    assert 'handler="/metrics"' not in _scrape(client)


# --- Trailing-slash redirects and the static mount (cardinality guard) -------
#
# The promise in ``main.py`` is that raw paths never become ``handler`` label
# values. A request that FastAPI answers with a 307 trailing-slash redirect
# (``/v1/query-runs/<id>/``) matches no route in full, so an instrumentator
# that falls back to the raw path for it lets an anonymous visitor mint one
# new series per request. These tests probe every parametrised route, in
# every registered method, with and without the trailing slash, plus the
# ``/static`` mount, each with a unique marker that must never reach /metrics.

# Greedy: a template label value itself contains braces ("{query_run_id}").
_REQUESTS_TOTAL_RE = re.compile(r"^http_requests_total\{(?P<labels>.*)\} (?P<value>\S+)$")
_HANDLER_RE = re.compile(r'(?:^|,)handler="(?P<handler>[^"]*)"')
_PATH_PARAM_RE = re.compile(r"\{[^}]+\}")


def _walk_routes(routes: list[object]) -> list[tuple[str, frozenset[str]]]:
    """(path, methods) for every route, descending into included routers.

    FastAPI (0.137.2 and 0.162.0 alike) keeps an included router as one lazy ``_IncludedRouter``
    entry in ``app.routes`` rather than copying its routes up, so a flat walk
    of ``app.routes`` would miss ``/v1/query-runs/{query_run_id}`` entirely.
    ``test_route_enumeration_finds_every_templated_openapi_path`` proves this
    walk is not blind.
    """
    found: list[tuple[str, frozenset[str]]] = []
    for route in routes:
        candidates = getattr(route, "effective_candidates", None)
        if callable(candidates):
            found.extend(_walk_routes(candidates()))
            continue
        inner = getattr(route, "starlette_route", None) or route
        path = getattr(route, "path", "") or getattr(inner, "path", "")
        methods = getattr(inner, "methods", None) or getattr(
            getattr(route, "original_route", None), "methods", None
        )
        found.append((path, frozenset(methods or ())))
    return found


def _templated_endpoints() -> list[tuple[str, str]]:
    """(method, template) for every route whose path has a ``{...}`` parameter."""
    return sorted(
        (method, path)
        for path, methods in _walk_routes(list(app.routes))
        if _PATH_PARAM_RE.search(path)
        for method in methods
    )


def _request_series(text: str) -> dict[str, float]:
    """Every ``http_requests_total`` sample, keyed by its full label set."""
    series: dict[str, float] = {}
    for line in text.splitlines():
        match = _REQUESTS_TOTAL_RE.match(line)
        if match:
            series[match["labels"]] = float(match["value"])
    return series


def _probe(client: TestClient, method: str, path: str) -> tuple[int, dict[str, float]]:
    """Send one request (redirects NOT followed); return status and series deltas."""
    before = _request_series(_scrape(client))
    status = client.request(method, path, follow_redirects=False).status_code
    after = _request_series(_scrape(client))
    moved = {
        labels: value - before.get(labels, 0.0)
        for labels, value in after.items()
        if value != before.get(labels, 0.0)
    }
    return status, moved


def _handler_of(labels: str) -> str:
    match = _HANDLER_RE.search(labels)
    assert match, f"no handler label in {labels!r}"
    return match["handler"]


def _marker() -> str:
    return f"mk{uuid.uuid4().hex[:20]}"


def test_route_enumeration_finds_every_templated_openapi_path() -> None:
    # Red when: the route walk stops descending into included routers (it then
    # finds no parametrised route at all, and every probe below runs over nothing).
    endpoints = _templated_endpoints()
    assert endpoints, "no parametrised route found; the probes below would test nothing"
    walked = {(method, path) for method, path in endpoints}
    openapi_templated = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if _PATH_PARAM_RE.search(path)
        for method in operations
    }
    assert openapi_templated, "OpenAPI lists no parametrised path to cross-check against"
    assert openapi_templated <= walked, f"walk missed {sorted(openapi_templated - walked)}"


def test_no_raw_path_from_any_templated_route_reaches_metrics() -> None:
    # Red when: any parametrised route, with or without a trailing slash, puts
    # the raw request path into a /metrics label (prometheus-fastapi-instrumentator
    # 8.1.0 does this for the 307 trailing-slash redirect).
    client = TestClient(app)
    markers: list[tuple[str, str, str]] = []
    for method, template in _templated_endpoints():
        for suffix in ("", "/"):
            marker = _marker()
            path = _PATH_PARAM_RE.sub(marker, template) + suffix
            client.request(method, path, follow_redirects=False)
            markers.append((marker, method, path))
    assert markers, "no probe was sent"
    text = _scrape(client)
    leaked = [
        f"{method} {path}: {line}"
        for marker, method, path in markers
        for line in text.splitlines()
        if marker in line
    ]
    assert not leaked, f"{len(leaked)} /metrics lines carry a raw path:\n" + "\n".join(leaked[:10])


def test_direct_templated_request_adds_exactly_one_to_its_template_series() -> None:
    # Red when: a request WITHOUT a trailing slash is counted under anything
    # but its route template, more than once, or not at all.
    client = TestClient(app)
    endpoints = _templated_endpoints()
    assert endpoints
    for method, template in endpoints:
        path = _PATH_PARAM_RE.sub(_marker(), template)
        _status, moved = _probe(client, method, path)
        assert len(moved) == 1, f"{method} {path} moved {len(moved)} series: {moved}"
        ((labels, delta),) = moved.items()
        assert delta == 1.0, f"{method} {path} added {delta} to {labels}"
        assert _handler_of(labels) == template, f"{method} {path} counted under {labels}"
        assert f'method="{method}"' in labels.split(","), labels


def test_redirected_templated_request_adds_exactly_one_to_its_own_series() -> None:
    # Red when: a trailing-slash request that FastAPI answers 307 is counted
    # under its raw path (8.1.0), more than once, or not at all.
    client = TestClient(app)
    endpoints = _templated_endpoints()
    assert endpoints
    for method, template in endpoints:
        # Bounded, template-derived labels only. 8.0.2 uses template + "/";
        # "none" (the unmatched sentinel) would also be bounded.
        allowed_handlers = {template, template + "/", "none"}
        path = _PATH_PARAM_RE.sub(_marker(), template) + "/"
        status, moved = _probe(client, method, path)
        # Positive partner: the redirect branch was really exercised.
        assert status == 307, f"{method} {path} answered {status}, not the 307 redirect"
        assert len(moved) == 1, f"{method} {path} moved {len(moved)} series: {moved}"
        ((labels, delta),) = moved.items()
        assert delta == 1.0, f"{method} {path} added {delta} to {labels}"
        assert 'status="3xx"' in labels.split(","), labels
        assert _handler_of(labels) in allowed_handlers, f"{method} {path} counted under {labels}"


def test_static_mount_probes_count_once_under_the_mount_path() -> None:
    # Red when: a /static request (existing file, missing file, or a slash
    # variant) is counted under its raw path instead of the mount path "/static".
    client = TestClient(app)
    existing = sorted(p.name for p in STATIC_DIR.iterdir() if p.is_file())
    assert existing, "no static file to probe"
    shapes = (
        "/static/{file}?{m}=1",
        "/static/{file}/{m}",
        "/static/{m}.css",
        "/static/{m}",
        "/static/{m}/",
        "/static/{m}.css/",
        "/static//{m}",
    )
    probes: list[tuple[str, str]] = []
    for shape in shapes:
        marker = _marker()
        probes.append((marker, shape.format(file=existing[0], m=marker)))
    # The plain existing file: no marker in the path, but it must still count once.
    status, moved = _probe(client, "GET", f"/static/{existing[0]}")
    assert status == 200, f"/static/{existing[0]} answered {status}"
    assert list(moved.values()) == [1.0], moved
    assert _handler_of(next(iter(moved))) == "/static", moved
    for _marker_value, path in probes:
        _status, moved = _probe(client, "GET", path)
        assert list(moved.values()) == [1.0], f"{path} moved {moved}"
        assert _handler_of(next(iter(moved))) == "/static", f"{path} counted under {moved}"
    text = _scrape(client)
    leaked = [line for marker, _path in probes for line in text.splitlines() if marker in line]
    assert not leaked, "raw static path reached /metrics:\n" + "\n".join(leaked[:10])
