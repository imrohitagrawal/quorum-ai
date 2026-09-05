"""ADR-0100: the estimate-attribution note appears exactly when it is true.

The note explains why a peer run's receipt shows the Synthesis row shrinking
while four per-model ``(critique)`` charges appear: ``costs.py`` computes
``writer_cost = debate_total - critique_total + synthesis_cost``, so the money
moves rather than growing. It must NOT appear on a run that was billed no
critique charges, where it would explain charges the reader never had.

WHAT TURNS THIS RED: replacing ``hasItemisedCritiqueRows``'s body with anything
that does not read ``kind === "critique"``. Review defeated the e2e specs alone
with ``return rows.length > 6;`` — the two fixtures (10 rows and 6 rows) cannot
tell that apart from the real predicate, so the browser gate could not either.

Follows ``tests/unit/test_agreement_clause_honesty.py``: the function is lifted
out of ``app.js`` by brace count and executed under Node, so this measures the
SERVED source rather than a Python re-implementation of it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_JS = REPO_ROOT / "src" / "product_app" / "static" / "app.js"


@pytest.fixture(autouse=True)
def _needs_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")


def _extract_function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.index(marker)
    i = source.index("(", start)
    depth = 0
    while True:
        if source[i] == "(":
            depth += 1
        elif source[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    brace = source.index("{", i)
    depth = 0
    i = brace
    while True:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1


@pytest.fixture(scope="module")
def harness() -> str:
    source = APP_JS.read_text(encoding="utf-8")
    assert "function hasItemisedCritiqueRows(" in source
    return _extract_function(source, "hasItemisedCritiqueRows")


def _run(harness: str, cases: list[Any]) -> list[Any]:
    script = (
        harness
        + "\n\nconst cases = "
        + json.dumps(cases)
        + ";\nconsole.log(JSON.stringify(cases.map((c) => hasItemisedCritiqueRows(c))));\n"
    )
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    decoded: list[Any] = json.loads(out.stdout)
    return decoded


def _row(kind: str) -> dict[str, str]:
    return {"model_id": "v/m", "display_name": "M", "usd": "0.003", "kind": kind}


def test_the_note_is_keyed_on_the_critique_KIND_not_on_a_row_count(harness: str) -> None:
    """RED WHEN: the predicate stops reading ``kind === "critique"``.

    The row COUNTS are deliberately equal across the two halves below, so a
    ``rows.length > N`` implementation — the one review used to defeat the e2e
    specs — cannot satisfy both.
    """
    seven_with_critique = {"by_model": [_row("model")] * 6 + [_row("critique")]}
    seven_without = {"by_model": [_row("model")] * 6 + [_row("synthesis")]}
    two_with_critique = {"by_model": [_row("critique"), _row("synthesis")]}
    two_without = {"by_model": [_row("model"), _row("synthesis")]}

    got = _run(harness, [seven_with_critique, seven_without, two_with_critique, two_without])

    # Same length, opposite answers — in both directions.
    assert got[0] is True
    assert got[1] is False
    assert got[2] is True
    assert got[3] is False


def test_the_predicate_never_throws_on_a_shape_the_server_can_emit(harness: str) -> None:
    """RED WHEN: the null/array guards are dropped.

    A thrown exception here takes out `renderResultReceipt` entirely, so the
    reader loses the whole receipt rather than one sentence.
    """
    cases: list[Any] = [
        None,
        {},
        {"by_model": None},
        {"by_model": []},
        {"by_model": [None]},
        {"by_model": [{}]},
        {"by_model": [{"kind": None}]},
        {"by_model": [{"kind": "Critique"}]},
        {"by_model": [{"kind": " critique"}]},
    ]
    got = _run(harness, cases)

    assert all(v is False for v in got), got
    # POSITIVE PARTNER: the harness DOES return True for the real shape, so the
    # all-False assertion above is not passing because the function is inert.
    assert _run(harness, [{"by_model": [_row("critique")]}]) == [True]
