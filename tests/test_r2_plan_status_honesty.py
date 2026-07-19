"""Status-honesty gate for `docs/R2-comprehensive-plan.md` (ledger EN-1/EN-4).

`docs/DAY-ONE-PROMPT.md` §3 designates **Part B of the R2 plan** as the ONE
existence table: every row is either ✅ (the artifact exists AND was proven
RED-then-GREEN) or **TODO** (it does not exist yet). EN-1 fixed the
aspiration-marked-done direction; these tests close the inverted direction —
*delivered-marked-absent* — by keying the table against the machinery that
actually exists in the tree (Makefile targets, CI job names, proof artifacts).

The tests deliberately read the real `Makefile` / `.github/workflows/ci.yml`
rather than a fixture: a row may only be ✅ while its gate is really wired, and
must not be **TODO** once it is. Both directions fail the build.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAN = REPO_ROOT / "docs" / "R2-comprehensive-plan.md"
MAKEFILE = REPO_ROOT / "Makefile"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# Part B row id -> (make targets, CI job-name fragments, proof artifacts).
# A row is "delivered" only when every listed piece of machinery is present.
# This map is TOTAL over the ✅ direction: a Part B row may only claim ✅ while
# it has an entry here (see `test_every_checked_row_is_keyed`), so flipping a
# row to ✅ forces whoever flips it to name the machinery that backs it.
DELIVERED_ROWS: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "1": (
        ("fr-completeness",),
        ("FR traceability completeness",),
        ("scripts/validate_fr_completeness.py", "tests/test_fr_completeness_gate.py"),
    ),
    "3": (
        ("test",),
        ("Unit tests",),
        (".github/workflows/test.yml",),
    ),
    "3b": (
        ("diff-cover",),
        ("Changed-lines coverage",),
        ("docs/metrics/diff-cover.md",),
    ),
    "4": (
        ("mutation-baseline",),
        ("Mutation score",),
        ("docs/metrics/mutation-baseline.md",),
    ),
    "7": (
        ("api-contract",),
        ("Schemathesis API contract",),
        ("tests/contract/test_api_contract_schemathesis.py",),
    ),
    "7b": (
        ("openapi-check",),
        ("openapi.yaml is in sync",),
        ("openapi.yaml",),
    ),
    "9": (
        (),
        ("axe + parity",),
        ("e2e/tests/ui-parity", ".github/workflows/e2e.yml"),
    ),
    # Row 10 is a hybrid: ✅ for the screenshot baseline, TODO for the depth work.
    "10": (
        (),
        ("Run visual snapshots (BLOCKING)",),
        ("e2e/tests/invariants/visual-snapshots.spec.ts",),
    ),
    "11": (
        (),
        ("axe",),
        ("e2e/tests/accessibility/axe-all-views.spec.ts",),
    ),
    # Row 12 is a hybrid too: ✅ for the base scan, TODO for the honesty/PII gate.
    "12": (
        ("security-scan",),
        ("Security scan",),
        ("scripts/security_scan.py",),
    ),
    "13": (
        ("perf-gate",),
        ("Hermetic perf",),
        ("tests/perf/test_workflow_latency_percentiles.py",),
    ),
}


def _part_b_rows() -> dict[str, str]:
    """Return {row id: full Part B table row} for the practice→gate matrix."""
    text = PLAN.read_text(encoding="utf-8")
    start = text.index("## Part B — Practice")
    end = text.index("## Part C", start)
    rows: dict[str, str] = {}
    for line in text[start:end].splitlines():
        match = re.match(r"\|\s*([0-9]+[a-z]?)\s*\|", line)
        if match:
            rows[match.group(1)] = line
    return rows


def _status_cell(row: str) -> str:
    return row.rstrip().rstrip("|").rsplit("|", 1)[-1].strip()


def _workflow_text() -> str:
    """Every workflow, concatenated: E2E jobs live outside `ci.yml`."""
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(WORKFLOWS.glob("*.yml")))


def _machinery_present(row_id: str) -> bool:
    targets, ci_names, artifacts = DELIVERED_ROWS[row_id]
    makefile = MAKEFILE.read_text(encoding="utf-8")
    ci = _workflow_text()
    return (
        all(re.search(rf"^{re.escape(t)}:", makefile, re.M) for t in targets)
        and all(name in ci for name in ci_names)
        and all((REPO_ROOT / a).exists() for a in artifacts)
    )


@pytest.mark.parametrize("row_id", sorted(DELIVERED_ROWS))
def test_delivered_gate_is_not_marked_todo(row_id: str) -> None:
    """A gate that exists and is wired to CI may not still say TODO."""
    if not _machinery_present(row_id):
        pytest.skip(f"Part B row {row_id}: machinery not present yet, TODO is honest")
    status = _status_cell(_part_b_rows()[row_id])
    if "✅" in status and "TODO" in status:
        # Hybrid rows (✅ base / TODO depth) already admit what is delivered.
        pytest.skip(f"Part B row {row_id}: hybrid status, delivery acknowledged")
    assert "TODO" not in status, (
        f"Part B row {row_id} is marked TODO but its gate exists and is wired "
        f"into CI: {_part_b_rows()[row_id].strip()}"
    )


@pytest.mark.parametrize("row_id", sorted(_part_b_rows()))
def test_status_claim_is_backed_by_machinery(row_id: str) -> None:
    """The inverse (EN-1): ✅ may not be claimed without the machinery.

    Parametrized over *every* Part B row, not just the keyed ones — an
    allow-list would let an unkeyed row be flipped to ✅ unchallenged.
    """
    row = _part_b_rows()[row_id]
    if "✅" not in _status_cell(row):
        return
    assert row_id in DELIVERED_ROWS, (
        f"Part B row {row_id} claims ✅ but names no machinery in DELIVERED_ROWS; "
        f"add its make target / CI job / proof artifact there first: {row.strip()}"
    )
    assert _machinery_present(row_id), (
        f"Part B row {row_id} claims ✅ but its make target / CI job / proof "
        f"artifact is missing: {row.strip()}"
    )


def test_every_checked_row_is_keyed() -> None:
    """Belt-and-braces on totality: no ✅ row may be absent from the key map.

    The parametrized test above cannot fire for a row that vanishes from the
    table entirely; this one states the invariant over the table as a whole.
    """
    unkeyed = sorted(
        row_id
        for row_id, row in _part_b_rows().items()
        if "✅" in _status_cell(row) and row_id not in DELIVERED_ROWS
    )
    assert not unkeyed, (
        f"Part B rows {unkeyed} claim ✅ with no DELIVERED_ROWS entry — every ✅ "
        "must name the machinery that backs it"
    )


def test_mutation_threshold_is_the_measured_number() -> None:
    """Row 4 and Part K row 5 must cite the measured floor, not 'absent'."""
    text = PLAN.read_text(encoding="utf-8")
    makefile = MAKEFILE.read_text(encoding="utf-8")
    measured = re.search(r"^MUTATION_MIN_SCORE \?= (\d+)", makefile, re.M)
    assert measured, "MUTATION_MIN_SCORE not defined in Makefile"
    assert "deliberately absent here until measured" not in text, (
        "Part K row 5 still says the mutation threshold is unmeasured, but "
        f"MUTATION_MIN_SCORE = {measured.group(1)} is enforced in the Makefile"
    )
    assert f"{measured.group(1)}%" in text, (
        f"the measured mutation floor ({measured.group(1)}%) is not cited in the plan"
    )


def test_evidence_artifact_gate_is_consistently_layer_three() -> None:
    """Part B0 numbers evidence-artifact gates 3rd; prose must not say layer 2."""
    text = PLAN.read_text(encoding="utf-8")
    start = text.index("### The three enforcement layers")
    end = text.index("## Part B — Practice", start)
    section = text[start:end]
    assert "3. **Evidence-artifact CI gates**" in section, (
        "Part B0's numbered ladder no longer puts evidence-artifact gates third"
    )
    offenders = [
        line.strip()
        for line in section.splitlines()
        if re.search(r"evidence-artifact CI gate \(layer 2", line)
    ]
    assert not offenders, f"evidence-artifact gate mis-numbered as layer 2: {offenders}"
