from fastapi.testclient import TestClient

from product_app.main import app


def test_browser_ui_renders_core_workflow_sections_without_secrets() -> None:
    client = TestClient(app)

    response = client.get("/ui")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert '<html lang="en" data-theme="light">' in html
    assert "Quorum AI" in html
    assert 'id="model-inputs"' in html
    assert "renderModelInputs" in html
    assert "data-model-slot" in html
    assert '<script id="model-catalog-data" type="application/json">' in html
    assert 'id="query-text"' in html
    assert "Model outputs" in html
    assert "Debate and synthesis" in html
    assert "Estimate cost" in html
    assert "openai/gpt-4o-mini" in html
    assert "Browser session" in html
    assert 'id="time-meta"' in html
    assert "Current time" in html
    assert "secret_reference" not in html
