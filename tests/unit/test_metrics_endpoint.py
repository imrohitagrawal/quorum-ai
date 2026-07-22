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

from fastapi.testclient import TestClient

from product_app.main import app


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
