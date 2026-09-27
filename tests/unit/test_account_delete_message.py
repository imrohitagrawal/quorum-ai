"""W7 2b (ADR-0136): the delete page says "try again" only when trying again
can work.

``accountDeleteMessage`` is lifted out of ``app.js`` by brace count and run
under Node, as ``tests/unit/test_receipt_attribution_note.py`` does, so this
measures the served source.

WHAT TURNS THIS RED: any error other than a store failure or a dropped
connection being told to "try again" (retrying a stale token, an expired
session or a missing cookie sends the same thing and fails the same way), or
either of those two losing the "try again" message.
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
MISMATCH = "That is not the email address you signed in with."
RETRY = "Your account could not be deleted just now. Please try again."
RELOAD = "Your session changed. Reload the page, then try again."


@pytest.fixture(autouse=True)
def _needs_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")


def _messages(errors: list[Any]) -> list[str]:
    harness = _extract_function(APP_JS.read_text(encoding="utf-8"), "accountDeleteMessage")
    script = (
        harness
        + "\nconst errors = "
        + json.dumps(errors)
        + ";\nconsole.log(JSON.stringify(errors.map((e) => accountDeleteMessage(e))));\n"
    )
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    decoded: list[str] = json.loads(out.stdout)
    return decoded


def test_only_a_store_failure_or_a_dropped_connection_says_try_again() -> None:
    got = _messages(
        [
            {"code": "CONFIRMATION_MISMATCH", "status": 400},
            {"code": "DELETION_FAILED", "status": 503},
            {"code": "NETWORK_UNREACHABLE", "status": 0},
            {"status": 0},
            {"code": "CSRF_INVALID", "status": 403},
            {"code": "SESSION_EXPIRED", "status": 401},
            {"code": "AUTH_REQUIRED", "status": 401},
            {"code": "NOT_SIGNED_IN", "status": 403},
            None,
        ]
    )
    assert got == [MISMATCH, RETRY, RETRY, RETRY, RELOAD, RELOAD, RELOAD, RELOAD, RELOAD]
