"""FS-5's ledger row must track what is actually on disk (Phase-0 self-check).

`tests/test_findings_ledger_consistency.py` catches the generic
"artifact exists but the row still says BUILD" drift, but only for the item IDs
listed in its `PHASE0_ARTIFACTS` map — FS-5 is not in it, so the ledger was free
to keep asserting that `R2-S2-S4-ULTRACODE-PROMPT.md` is *untouched* and *still
lacks the enforcement contract* while this branch had already added the
`## Precondition — Phase 0 …` section **and** the gate that asserts it
(`tests/test_ultracode_prompt_enforcement_contract.py`).

That direction — delivered but marked absent — is the dangerous one: the
reconciling session either redoes work that exists, or blocks S2 on a
precondition already satisfied, and a later deletion of the precondition section
flips no status because the ledger already claims it is missing.

These tests bind the FS-5 row (and the Post-Phase-0 action index that mirrors
it) to the two artifacts, in both directions.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = REPO_ROOT / "docs" / "analysis" / "R2-plan-review-findings.md"
PROMPT_PATH = REPO_ROOT / "R2-S2-S4-ULTRACODE-PROMPT.md"
CONTRACT_GATE = "tests/test_ultracode_prompt_enforcement_contract.py"

#: The section heading in the ULTRACODE prompt that *is* the enforcement
#: contract FS-5 asked for.
_PRECONDITION_RE = re.compile(r"^##\s+Precondition\b.*\bPhase 0\b", re.MULTILINE)

#: Claims the ledger may not make once the contract is on disk.
_STALE_CLAIMS = (
    "untouched",
    "still lacks the",
    "is still absent",
)


@pytest.fixture(scope="module")
def ledger_text() -> str:
    return LEDGER_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def fs5_row(ledger_text: str) -> str:
    for line in ledger_text.splitlines():
        if line.startswith("| FS-5 |"):
            return line
    pytest.fail(f"no FS-5 row in {LEDGER_PATH}")


@pytest.fixture(scope="module")
def contract_delivered() -> bool:
    """True when both FS-5 artifacts exist: the section AND its gate."""
    if not PROMPT_PATH.exists() or not (REPO_ROOT / CONTRACT_GATE).exists():
        return False
    return bool(_PRECONDITION_RE.search(PROMPT_PATH.read_text(encoding="utf-8")))


def test_fs5_reads_done_when_the_contract_exists(fs5_row: str, contract_delivered: bool) -> None:
    """Delivered-but-marked-absent is the drift that wastes the next session."""
    if not contract_delivered:
        pytest.skip("FS-5 enforcement contract not built yet")
    assert "DONE" in fs5_row, (
        f"{PROMPT_PATH.name} carries the Phase-0 precondition section and "
        f"{CONTRACT_GATE} asserts it, but the FS-5 row still reads: {fs5_row}"
    )


def test_fs5_cites_both_of_its_artifacts(fs5_row: str, contract_delivered: bool) -> None:
    """DONE must point at the prompt section *and* the gate that holds it."""
    if not contract_delivered:
        pytest.skip("FS-5 enforcement contract not built yet")
    for pointer in (PROMPT_PATH.name, CONTRACT_GATE):
        assert pointer in fs5_row, f"FS-5 row does not cite {pointer}: {fs5_row}"


def test_ledger_makes_no_stale_absence_claim_about_the_prompt(
    ledger_text: str, contract_delivered: bool
) -> None:
    """The action index mirrors the row; both must stop saying "absent"."""
    if not contract_delivered:
        pytest.skip("FS-5 enforcement contract not built yet")
    offenders = [
        line.strip()
        for line in ledger_text.splitlines()
        if "R2-S2-S4-ULTRACODE-PROMPT.md" in line and any(claim in line for claim in _STALE_CLAIMS)
    ]
    assert not offenders, (
        "ledger still claims the ULTRACODE prompt lacks the enforcement "
        f"contract it now carries: {offenders}"
    )


def test_fs5_is_not_listed_as_still_open(ledger_text: str, contract_delivered: bool) -> None:
    """A satisfied precondition must leave the "STILL OPEN" index."""
    if not contract_delivered:
        pytest.skip("FS-5 enforcement contract not built yet")
    still_open = ledger_text.split("STILL OPEN after Phase 0", 1)
    assert len(still_open) == 2, "Post-Phase-0 action index section not found"
    tail = still_open[1].split("\n4.", 1)[0]
    assert "FS-5" not in tail, (
        f"FS-5 is still listed under STILL OPEN after Phase 0: {tail.strip()}"
    )
