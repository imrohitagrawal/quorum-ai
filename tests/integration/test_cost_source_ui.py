"""Item 1 of the PR #7 coordinated backend follow-ups — UI coordination.

The backend tags ``actual_cost_usd`` provenance with ``cost_source``
(``"estimated"`` today, ``"measured"`` when per-call usage capture lands).
The run-receipt reconciliation footer MUST read that flag and, while the
source is ``"estimated"``, present the figure as an estimate rather than a
measured est→actual reconciliation (which would imply the value was checked
against provider billing).

``buildReconciliationRow`` builds DOM nodes, so — like the other DOM helpers
in this suite — we pin the invariant at the source level rather than executing
it under a DOM shim.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_JS = REPO_ROOT / "src" / "product_app" / "static" / "app.js"


def _reconciliation_body() -> str:
    text = APP_JS.read_text(encoding="utf-8")
    match = re.search(r"function buildReconciliationRow\(result\) \{", text)
    assert match is not None, "buildReconciliationRow not found in app.js"
    start = match.start()
    depth = 0
    for idx in range(text.index("{", start), len(text)):
        if text[idx] == "{":
            depth += 1
        elif text[idx] == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    raise AssertionError("buildReconciliationRow body not brace-balanced")


def test_reconciliation_reads_cost_source() -> None:
    body = _reconciliation_body()
    assert "cost_source" in body, (
        "buildReconciliationRow must read result.cost_source to avoid presenting "
        "an estimate as a measured actual"
    )
    assert re.search(r'cost_source\s*===\s*"measured"', body), (
        "the delta reconciliation must be gated on a 'measured' source"
    )


def test_estimated_source_is_labelled_not_reconciled() -> None:
    body = _reconciliation_body()
    # The estimated branch must render an honest 'estimated' state/label ...
    assert 'row.dataset.state = "estimated"' in body, (
        "an estimated cost_source must set the 'estimated' receipt state"
    )
    assert "Actual cost (estimated)" in body, (
        "an estimated cost_source must be labelled as estimated in the receipt"
    )
    # ... and it must be reached BEFORE the est→actual delta branches, so an
    # estimate is never rendered as a real under/over reconciliation.
    estimated_idx = body.index('row.dataset.state = "estimated"')
    under_idx = body.index('"under"')
    assert estimated_idx < under_idx, (
        "the estimated branch must short-circuit before the delta (under/over) branches"
    )
