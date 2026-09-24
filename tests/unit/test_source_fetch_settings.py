"""The source-fetch settings (#447, ADR-0124): shipped off, bounded, visible.

RED IF: the fetch is on by default, a bound accepts 0/negative/NaN, the
total budget may sit at or below the per-read timeout, or /status stops
reporting the flag.
"""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from product_app.config import Settings, settings
from product_app.main import app


def test_the_fetch_ships_off_with_the_documented_bounds() -> None:
    fresh = Settings(_env_file=None)  # type: ignore[call-arg]
    assert fresh.quorum_source_fetch_enabled is False
    assert fresh.quorum_source_fetch_timeout_seconds == 3.0
    assert fresh.quorum_source_fetch_budget_seconds == 8.0
    assert fresh.quorum_source_fetch_max_bytes == 262_144
    assert fresh.quorum_source_fetch_max_pages == 8
    assert fresh.quorum_source_fetch_max_text_chars == 4_000


@pytest.mark.parametrize(
    "field",
    [
        "quorum_source_fetch_timeout_seconds",
        "quorum_source_fetch_max_bytes",
        "quorum_source_fetch_max_pages",
        "quorum_source_fetch_max_text_chars",
    ],
)
@pytest.mark.parametrize("bad", [0, -1, math.nan])
def test_a_bound_that_is_not_positive_is_refused(field: str, bad: float) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: bad})  # type: ignore[call-arg,arg-type]


def test_the_budget_must_exceed_the_per_read_timeout() -> None:
    with pytest.raises(ValidationError, match="strictly greater"):
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            quorum_source_fetch_timeout_seconds=3.0,
            quorum_source_fetch_budget_seconds=3.0,
        )
    # Positive partner: a budget above the timeout is accepted.
    assert (
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            quorum_source_fetch_timeout_seconds=3.0,
            quorum_source_fetch_budget_seconds=3.5,
        ).quorum_source_fetch_budget_seconds
        == 3.5
    )


@pytest.mark.parametrize("value", [False, True])
def test_status_reports_the_flag_as_configured(
    monkeypatch: pytest.MonkeyPatch, value: bool
) -> None:
    """ADR-0013: an egress-capable subsystem is never enabled invisibly."""
    monkeypatch.setattr(settings, "quorum_source_fetch_enabled", value)
    payload = TestClient(app).get("/status").json()
    assert payload["source_fetch_enabled"] is value
