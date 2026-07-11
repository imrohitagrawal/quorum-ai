"""Regression tests for two unauthenticated info-leaks on the operations surface.

Both fixes live in ``product_app.main``:

1. ``/status`` used to embed the feedback SQLite file path in the public,
   unauthenticated ``feedback_db`` field (``"connected (/path/to.sqlite3)"``).
   The path is an internal detail and must never surface. ``/status`` stays
   public — only the path is redacted; the connected/disconnected health
   signal is preserved.
2. ``/feedback/audit`` served audit report content to anyone. It is now gated
   behind ``require_session`` (the same dependency ``/v1/models/defaults``
   uses): anonymous callers get 401, a valid session gets 200.

Each test is written so it fails against the pre-fix code (path present /
route open) and passes only with the redaction + auth gate in place.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from product_app import main
from product_app.feedback_store import FeedbackStore, configure, get_store
from product_app.main import app


@pytest.fixture
def restore_store() -> Iterator[None]:
    """Restore the process-wide feedback store after a test mutates it."""
    original = get_store()
    try:
        yield
    finally:
        configure(original)


# ---------------------------------------------------------------------------
# Finding 1: /status must not leak the feedback DB filesystem path.
# ---------------------------------------------------------------------------


def test_status_reports_db_health_without_leaking_path(tmp_path: Path, restore_store: None) -> None:
    """A connected store reports ``feedback_db == "connected"`` and the
    on-disk path never appears anywhere in the ``/status`` payload.

    Pre-fix, ``feedback_db`` was ``f"connected ({db_path})"``; this test
    fails there because the distinctive path substring is present and the
    field is not the bare ``"connected"`` health string.
    """
    db_file = tmp_path / "leak_probe_feedback_events.sqlite3"
    store = FeedbackStore(str(db_file))
    configure(store)
    try:
        client = TestClient(app)
        response = client.get("/status")

        assert response.status_code == 200
        body = response.json()

        # Health signal preserved, but path redacted.
        assert body["feedback_db"] == "connected"
        # No parenthetical path smuggled into the health string.
        assert "(" not in body["feedback_db"]
        # The distinctive path must not leak anywhere in the response.
        assert "leak_probe_feedback_events.sqlite3" not in response.text
        assert str(db_file) not in response.text
    finally:
        store.close()


def test_status_reports_disconnected_when_store_absent(restore_store: None) -> None:
    """With no store configured, ``feedback_db`` is the bare health string."""
    configure(None)
    client = TestClient(app)
    response = client.get("/status")

    assert response.status_code == 200
    body = response.json()
    assert body["feedback_db"] == "disconnected"


def test_status_stays_public_and_unauthenticated(restore_store: None) -> None:
    """Redaction must not regress the public-health contract: /status is
    still reachable without any session."""
    configure(None)
    client = TestClient(app)
    response = client.get("/status")
    assert response.status_code == 200
    assert set(response.json()) >= {
        "app",
        "environment",
        "feedback_db",
        "uptime_seconds",
    }


# ---------------------------------------------------------------------------
# Finding 2: /feedback/audit must require a valid session.
# ---------------------------------------------------------------------------


@pytest.fixture
def audit_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the feedback-audit surface at a temp dir holding one report."""
    report = tmp_path / "audit-2026-07-11.md"
    report.write_text("# Feedback audit\n\nAll clear.\n", encoding="utf-8")
    monkeypatch.setattr(main, "_FEEDBACK_DIR", tmp_path)
    return report


def test_feedback_audit_rejects_anonymous_request(audit_report: Path) -> None:
    """Anonymous callers get 401 even though a report exists on disk.

    Pre-fix the route was unauthenticated and returned the report body
    (200) to anyone; this test fails there.
    """
    client = TestClient(app)
    response = client.get("/feedback/audit")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"
    # The report body must not have leaked.
    assert "All clear." not in response.text


def test_feedback_audit_rejects_anonymous_even_with_no_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 401 comes from the dependency, before the 404 report lookup —
    an anonymous caller can't even probe whether a report exists."""
    monkeypatch.setattr(main, "_FEEDBACK_DIR", tmp_path)  # empty dir
    client = TestClient(app)
    response = client.get("/feedback/audit")
    assert response.status_code == 401


def test_feedback_audit_served_to_valid_legacy_session(audit_report: Path) -> None:
    """A valid session (legacy header path, enabled in tests) gets 200 and
    the report body."""
    client = TestClient(app)
    response = client.get(
        "/feedback/audit",
        headers={"X-Account-Id": str(uuid4())},
    )

    assert response.status_code == 200
    assert "All clear." in response.text
    assert response.headers["X-Audit-Date"] == "2026-07-11"


def test_feedback_audit_served_to_valid_cookie_session(audit_report: Path) -> None:
    """A valid browser cookie session (the production path) gets 200."""
    client = TestClient(app)
    # Establish the session cookie the same way a browser would.
    client.get("/v1/session").raise_for_status()
    response = client.get("/feedback/audit")

    assert response.status_code == 200
    assert "All clear." in response.text


def test_feedback_audit_authenticated_but_no_report_returns_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid session against an empty report dir still gets the 404
    branch (auth passes, then the report lookup misses) — the gate must
    not swallow the pre-existing not-found contract."""
    monkeypatch.setattr(main, "_FEEDBACK_DIR", tmp_path)  # empty dir
    client = TestClient(app)
    response = client.get(
        "/feedback/audit",
        headers={"X-Account-Id": str(uuid4())},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "AUDIT_NOT_FOUND"
