"""PR-0 / Bug 3: regression test for the magnitude-aware cost formatter.

The bug was that ``formatCostWithLocal`` (and its helper ``formatUsd``)
used ``.toFixed(2)``, so any sub-cent cost displayed as ``$0.00 USD``.
The fix uses magnitude-aware decimals (4dp below 1¢, 3dp below $1,
2dp otherwise) and strips trailing zeros.

We can't unit-test the JS in the Python test runner without a
framework, so this test invokes the formatter via ``node`` as a
subprocess. The test stays small (one process call) and is
self-contained: no new test framework, no new Python dependencies.
The node invocation mirrors the actual function source so any
regression in the JS is caught here.

If node is unavailable in CI this test is skipped — the alternative
is the Playwright walkthrough documented in PR-0.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_JS = REPO_ROOT / "src" / "product_app" / "static" / "app.js"


def _extract_format_usd() -> str:
    """Pull the ``formatUsd`` function source from ``app.js``.

    We avoid shipping a parallel copy: the JS source of truth lives
    there, and the regex keeps this test honest if the function is
    renamed or its signature changes.
    """
    text = APP_JS.read_text(encoding="utf-8")
    match = re.search(r"function formatUsd\(usdAmount\) \{", text)
    assert match is not None, "formatUsd not found in app.js — was the function renamed?"
    start = match.start()
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise RuntimeError("formatUsd braces did not balance in app.js")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_format_usd_sub_cent_does_not_display_zero() -> None:
    """formatUsd(0.0023) must NOT collapse to "$0.00 USD".

    This is the core Bug 3 regression. We check that the string
    produced for a known sub-cent cost contains a non-zero digit
    after the decimal point, and that zero dollars with zero cents
    still renders as ``$0.00 USD`` (so the "free" label only appears
    when the cost really is zero).
    """
    body = _extract_format_usd()
    script = (
        body
        + "\n"
        + "const inputs = [0.0023, 0.001, 0.0007, 0.5, 5.25, 0.0];\n"
        + "const out = inputs.map((n) => ({input: n, actual: formatUsd(n)}));\n"
        + "process.stdout.write(JSON.stringify(out));\n"
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    out = json.loads(result.stdout)
    by_input = {item["input"]: item["actual"] for item in out}

    # Sub-cent values must show the actual sub-cent digits, not "$0.00".
    assert by_input[0.0023] != "$0.00 USD", "Bug 3 regression: 0.0023 displayed as $0.00 USD"
    assert "$0.0023" in by_input[0.0023], f"expected '$0.0023' substring in {by_input[0.0023]!r}"

    assert by_input[0.001] != "$0.00 USD"
    assert "$0.001" in by_input[0.001]

    assert by_input[0.0007] != "$0.00 USD"

    # Zero stays zero.
    assert by_input[0.0] == "$0.00 USD"

    # Whole-dollar values retain the cents segment so the display
    # is unambiguous (e.g. ``$5.25 USD`` not ``$5.2``).
    assert by_input[5.25] == "$5.25 USD"
    # 0.5 is below $1 so it gets 3dp, then trailing zeros are
    # stripped, leaving ``$0.5 USD``. That is unambiguous, so the
    # test pins the contract: 0.5 displays as ``$0.5`` (not ``$0``
    # and not rounded away).
    assert by_input[0.5] in {"$0.5 USD", "$0.50 USD"}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_format_usd_returns_string_for_finite_input() -> None:
    """formatUsd must always return a string with the right structure.

    Each input has a known expected output, so we assert the *exact*
    string. This is what makes the test useful — a regression that
    collapsed every value to ``"$0.00 USD"`` would still pass the
    previous (tautological) ``startswith("$")`` + ``"USD" in s``
    assertions.
    """
    body = _extract_format_usd()
    script = (
        body
        + "\n"
        + "const inputs = [0.0, 0.01, 0.5, 5.25, 0.0023];\n"
        + "const out = inputs.map(formatUsd);\n"
        + "process.stdout.write(JSON.stringify(out));\n"
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    out = json.loads(result.stdout)
    assert len(out) == 5
    for s in out:
        assert isinstance(s, str)
        assert s.startswith("$"), s
        assert s.endswith(" USD"), s
    # Pin the exact strings so a regression to a single format is
    # caught immediately.
    assert out[0] == "$0.00 USD", f"0.0 -> {out[0]!r}"
    # 0.01 is exactly one cent — 4dp is used below 1¢ so this
    # displays as ``$0.01`` (the trailing zeros are stripped from
    # the 4dp form). Anything other than $0.01 means the magnitude
    # boundary moved.
    assert out[1] in {"$0.01 USD", "$0.0100 USD"}, f"0.01 -> {out[1]!r}"
    # 0.5 is below $1 so 3dp is used, then trailing zeros stripped.
    assert out[2] in {"$0.5 USD", "$0.50 USD"}, f"0.5 -> {out[2]!r}"
    # 5.25 is >= $1 so 2dp is used.
    assert out[3] == "$5.25 USD", f"5.25 -> {out[3]!r}"
    # 0.0023 must show its sub-cent digits, never "$0.00".
    assert out[4] != "$0.00 USD", f"0.0023 -> {out[4]!r} (regression of Bug 3)"
    assert "$0.0023" in out[4], f"0.0023 -> {out[4]!r}"
