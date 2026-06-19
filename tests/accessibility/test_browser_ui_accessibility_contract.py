from fastapi.testclient import TestClient

from product_app.main import app


def test_browser_ui_exposes_accessible_labels_focus_and_landmarks() -> None:
    client = TestClient(app)

    response = client.get("/ui")

    assert response.status_code == 200
    html = response.text
    assert '<a class="skip-link" href="#main-content">Skip to main content</a>' in html
    assert '<main id="main-content" class="shell" tabindex="-1">' in html
    assert 'aria-labelledby="composer-heading"' in html
    assert 'role="alert"' in html
    assert '<fieldset class="field-group">' in html
    assert "<legend>Model slots</legend>" in html
    assert 'id="model-inputs"' in html
    assert 'aria-live="polite" aria-atomic="true"' in html
    assert "Choose four different models" in html
    assert '<label for="query-text">Question</label>' in html
    assert 'id="time-meta"' in html
    assert ":focus-visible" in html
    assert "min-height: 44px" in html
    assert "decision support only" in html
    assert "Toggle dark mode" in html
