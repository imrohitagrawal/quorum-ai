"""W87-1 (ADR-0174; CHG-066 a): the warning shown 5 minutes before a signed-in
session's 12 hours end.

``maxAgeReminderText`` is lifted out of ``app.js`` and run under Node, as
``tests/unit/test_idle_reminder_page.py`` does for the idle reminder. It must
be self-contained (the harness extracts that one function). Minutes are
rounded as ``idleReminderText`` rounds them: up, with "about a minute" at 60 s
or less.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.unit.test_receipt_attribution_note import _extract_function

APP_JS = Path(__file__).resolve().parents[2] / "src" / "product_app" / "static" / "app.js"

#: CHG-066 (a), verbatim, at 300 s.
AT_FIVE_MINUTES = (
    "You will be signed out in about 5 minutes because 12 hours have passed since you signed in."
)


@pytest.fixture
def _node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")


def _run(names: list[str], calls: str) -> Any:
    source = APP_JS.read_text(encoding="utf-8")
    harness = "\n".join(_extract_function(source, name) for name in names)
    out = subprocess.run(
        ["node", "-e", harness + "\nconsole.log(JSON.stringify(" + calls + "));\n"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(out.stdout)


@pytest.mark.usefixtures("_node")
def test_the_warning_is_the_owners_sentence_at_five_minutes() -> None:
    """Red when: the sentence differs by a character from CHG-066 (a)."""
    assert _run(["maxAgeReminderText"], "maxAgeReminderText(300)") == AT_FIVE_MINUTES


@pytest.mark.usefixtures("_node")
def test_the_warning_rounds_minutes_as_the_idle_reminder_does() -> None:
    """Red when: the rounding differs from ``idleReminderText`` (up; "about a
    minute" at 60 s or less), e.g. under 5 minutes it must read "about 3
    minutes", not a fixed "5 minutes"."""
    got = _run(
        ["maxAgeReminderText"],
        "[300, 241, 180, 61, 60, 5].map((s) => maxAgeReminderText(s))",
    )
    tail = " because 12 hours have passed since you signed in."
    assert got == [
        "You will be signed out in about 5 minutes" + tail,
        "You will be signed out in about 5 minutes" + tail,
        "You will be signed out in about 3 minutes" + tail,
        "You will be signed out in about 2 minutes" + tail,
        "You will be signed out in about a minute" + tail,
        "You will be signed out in about a minute" + tail,
    ]


@pytest.mark.usefixtures("_node")
def test_the_warning_never_blames_inactivity_or_offers_to_stay() -> None:
    """FM-22: pressing "Stay signed in" cannot extend the 12 hours, and nothing
    about inactivity is true. Red when: either phrase appears. Partner: the
    idle reminder's own text has both, so the check can see them."""
    got = _run(
        ["maxAgeReminderText", "idleReminderText"],
        "[[300, 180, 60].map((s) => maxAgeReminderText(s)), idleReminderText(300)]",
    )
    warnings, idle = got
    assert "nothing has happened" in idle
    assert "Stay signed in" in idle
    assert len(warnings) == 3
    for text in warnings:
        assert "nothing has happened" not in text
        assert "Stay signed in" not in text
