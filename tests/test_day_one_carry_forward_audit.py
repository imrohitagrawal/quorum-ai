"""CF-1's carry-forward audit must be re-derivable, not asserted.

CF-1 claims the supersede of `docs/day-one-quality-standard.md` lost nothing:
every pointer in it also lives in the canonical `docs/DAY-ONE-PROMPT.md`. The
Phase-0 diff then gutted that very file from 154 lines to a 31-line redirect
stub, deleting the pointers the audit was run over — so the claim became
unfalsifiable at HEAD, and the number the ledger cited ("23/23") is not
re-derivable at any SHA (the pre-supersede blob has 15 backticked spans, 14
distinct). ``test_findings_ledger_consistency`` cannot catch this: it only
asserts the *cited path exists*, never that it still carries the evidence.

So the audit itself moves below the line. These tests read the pre-supersede
blob at :data:`PRE_SUPERSEDE_SHA` — which git keeps forever, unlike the working
tree — recompute the pointer set, and assert both the superset property and
that the ledger's cited count is the one the command actually produces.
Re-derive by hand with::

    git show 5ccd6f9:docs/day-one-quality-standard.md | grep -oE '`[^`]+`' | sort -u
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = REPO_ROOT / "docs" / "analysis" / "R2-plan-review-findings.md"
CANONICAL_PATH = REPO_ROOT / "docs" / "DAY-ONE-PROMPT.md"
SUPERSEDED_REL = "docs/day-one-quality-standard.md"

#: The S1 baseline — the last commit at which the superseded standard still had
#: its full content. The audit is anchored here so gutting the stub (or the
#: stub's eventual deletion) cannot erase the evidence.
PRE_SUPERSEDE_SHA = "5ccd6f9"

#: A backticked code span — the pointer unit the carry-forward audit counted.
#: Line-bounded on purpose, so it matches the documented ``grep -oE`` exactly;
#: an unbounded ``[^`]+`` pairs backticks across paragraphs and invents spans.
_SPAN_RE = re.compile(r"`([^`\n]+)`")


@pytest.fixture(scope="module")
def superseded_text() -> str:
    return subprocess.run(
        ["git", "show", f"{PRE_SUPERSEDE_SHA}:{SUPERSEDED_REL}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.fixture(scope="module")
def distinct_pointers(superseded_text: str) -> set[str]:
    return set(_SPAN_RE.findall(superseded_text))


@pytest.fixture(scope="module")
def cf1_row() -> str:
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("| CF-1 |"):
            return line
    pytest.fail(f"no CF-1 row in {LEDGER_PATH}")


def test_every_pointer_is_carried_into_the_canonical_file(
    distinct_pointers: set[str],
) -> None:
    """The superset property CF-1 asserts — checked, not claimed."""
    canonical = CANONICAL_PATH.read_text(encoding="utf-8")
    missing = sorted(p for p in distinct_pointers if f"`{p}`" not in canonical)
    assert not missing, (
        f"{len(missing)} pointer(s) from {SUPERSEDED_REL}@{PRE_SUPERSEDE_SHA} are "
        f"absent from {CANONICAL_PATH.name}, so the supersede lost content: {missing}"
    )


def test_cf1_cites_the_re_derivable_pointer_count(
    cf1_row: str, distinct_pointers: set[str]
) -> None:
    """The ledger must quote the number the documented command produces."""
    expected = len(distinct_pointers)
    assert f"{expected} distinct" in cf1_row, (
        f"CF-1 must cite the re-derivable count ({expected} distinct backticked "
        f"pointers at {PRE_SUPERSEDE_SHA}); row reads: {cf1_row}"
    )


def test_cf1_names_the_sha_the_audit_is_re_derivable_at(cf1_row: str) -> None:
    """A count with no SHA is unauditable once the stub is gutted."""
    assert PRE_SUPERSEDE_SHA in cf1_row, (
        f"CF-1 must name the SHA its audit is re-derivable at "
        f"({PRE_SUPERSEDE_SHA}); row reads: {cf1_row}"
    )
