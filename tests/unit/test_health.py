from fastapi.testclient import TestClient

from product_app.main import app


def test_root_endpoint_points_to_available_api_routes() -> None:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    # The service name is operator-configurable via APP_NAME in .env,
    # so we don't pin its value here — only assert the contract: a
    # non-empty string and that the route map is present.
    assert isinstance(body["service"], str) and body["service"]
    assert body["docs"] == "/docs"
    assert body["health"] == "/health"
    assert body["ready"] == "/ready"
    assert body["ui"] == "/ui"
    assert body["session"] == "/v1/session"
    assert body["model_defaults"] == "/v1/models/defaults"
    assert body["query_run_estimate"] == "/v1/query-runs/estimate"
    assert body["query_runs"] == "/v1/query-runs"


def test_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
