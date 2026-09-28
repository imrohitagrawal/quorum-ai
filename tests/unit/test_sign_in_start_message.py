"""W7 part 3 (ADR-0137): the page's message when starting a sign-in fails.

``signInStartMessage`` is lifted out of ``app.js`` and run under Node, as
``tests/unit/test_account_delete_message.py`` does.

WHAT TURNS THIS RED: a 429 (the per-network limit) told to "try again" at
once, or any other failure losing the "try again" message.
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
LIMITED = "Too many sign-in attempts. Try again in a few minutes."
RETRY = "Sign-in could not start. Please try again."


@pytest.fixture(autouse=True)
def _needs_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")


def _messages(errors: list[Any]) -> list[str]:
    harness = _extract_function(APP_JS.read_text(encoding="utf-8"), "signInStartMessage")
    script = (
        harness
        + "\nconst errors = "
        + json.dumps(errors)
        + ";\nconsole.log(JSON.stringify(errors.map((e) => signInStartMessage(e))));\n"
    )
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    decoded: list[str] = json.loads(out.stdout)
    return decoded


def test_only_the_rate_limit_says_to_wait() -> None:
    got = _messages(
        [
            {"status": 429, "code": "SIGN_IN_RATE_LIMITED"},
            {"status": 409, "code": "SIGN_IN_WRONG_HOST"},
            {"status": 503},
            {"status": 0, "code": "NETWORK_UNREACHABLE"},
            None,
        ]
    )
    assert got == [LIMITED, RETRY, RETRY, RETRY, RETRY]
