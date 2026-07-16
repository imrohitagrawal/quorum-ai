"""Issues #19 and #20 — JS cost-gate range + per-slot estimate.

Both functions live in ``static/app.js`` (the single source of truth); we
exercise them via ``node`` exactly like ``test_cost_gate_js.py`` /
``test_cost_formatter_js.py`` — no parallel JS copy, no new test framework.

* #19 ``gateRangeText`` — collapses a "$0.15–$0.15" band (both endpoints round
  to the same cents) to a single "$0.15", instead of a degenerate range.
* #20 ``computePerSlotEstimatesUsd`` — keys the web-search context tokens AND
  the flat per-request search fee (#18) off a PER-SLOT search flag, so a future
  per-slot search toggle cannot silently drift the estimate.
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

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


def _extract_function(name: str) -> str:
    text = APP_JS.read_text(encoding="utf-8")
    match = re.search(r"function " + re.escape(name) + r"\(", text)
    assert match is not None, f"{name} not found in app.js — was it renamed?"
    start = match.start()
    depth = 0
    started = False
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
            started = True
        elif ch == "}":
            depth -= 1
            if started and depth == 0:
                return text[start : i + 1]
    raise RuntimeError(f"{name} braces did not balance in app.js")


def _node(script: str) -> str:
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------- #19 range ---
def _range_text(lo: float, hi: float) -> str:
    script = (
        _extract_function("gateUsd2dp")
        + "\n"
        + _extract_function("gateRangeText")
        + "\n"
        + f"process.stdout.write(gateRangeText({lo}, {hi}));\n"
    )
    return _node(script)


def test_range_collapses_when_endpoints_render_equal() -> None:
    # Both endpoints round to $0.15 → a single figure, not "$0.15–$0.15".
    assert _range_text(0.15, 0.15) == "$0.15"
    # A tiny band that still rounds to the same cents also collapses (#19 repro:
    # a small total whose ±band stays inside one cent).
    assert _range_text(0.02, 0.023) == "$0.02"


def test_range_kept_when_endpoints_differ() -> None:
    assert _range_text(0.10, 0.22) == "$0.10–$0.22"
    assert _range_text(0.15, 0.20) == "$0.15–$0.20"


# ----------------------------------------------------------- #20 per-slot -----
_COST_MODEL = {
    "chars_per_token": 4,
    "system_prompt_tokens": 350,
    "web_search_context_tokens": 2000,
    "web_search_request_fee_usd": 0.02,
    "initial_output_tokens": 700,
    "output_tokens_per_query_token": 0.5,
    "default_input_price_per_1k": 0.001,
    "default_output_price_per_1k": 0.002,
}


def _per_slot(model_ids: list[str], query: str, search_flags: list[bool] | None) -> list[float]:
    # Both slots use the SAME (default-catalog) price, so any difference between
    # them isolates the search term. catalogPriceIndex is an empty Map → the
    # function falls back to default_input/output for every model.
    flags_js = "null" if search_flags is None else json.dumps(search_flags)
    script = (
        f"const window = {{ COST_MODEL: {json.dumps(_COST_MODEL)} }};\n"
        + "const catalogPriceIndex = new Map();\n"
        + _extract_function("computePerSlotEstimatesUsd")
        + "\n"
        + f"const ids = {json.dumps(model_ids)}, q = {json.dumps(query)}, flags = {flags_js};\n"
        + "const out = computePerSlotEstimatesUsd(ids, q, flags);\n"
        + "process.stdout.write(JSON.stringify(out));\n"
    )
    return [float(x) for x in json.loads(_node(script))]


def test_search_disabled_slot_excludes_context_tokens_and_fee() -> None:
    ids = ["m/a", "m/a"]  # identical price → isolates the search term
    query = "How do we measure retention well across cohorts?"
    est = _per_slot(ids, query, [True, False])
    searching, not_searching = est[0], est[1]
    assert searching > not_searching, "a searching slot must cost more than a non-searching one"
    # The delta is exactly the search-context prompt tokens priced at the input
    # rate PLUS the flat fee: 2000/1000 * 0.001 + 0.02 = 0.002 + 0.02 = 0.022.
    assert searching - not_searching == pytest.approx(0.022, abs=1e-9)


def test_default_flags_search_every_slot() -> None:
    ids = ["m/a", "m/b"]
    query = "Some question about retention."
    default = _per_slot(ids, query, None)
    all_on = _per_slot(ids, query, [True, True])
    assert default == pytest.approx(all_on), (
        "omitting searchFlags must default to search ON for every slot"
    )
