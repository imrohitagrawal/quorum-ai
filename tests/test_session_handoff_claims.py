"""Truthfulness gate for `docs/session-handoff.md` (ledger DOC-FIX batch).

AGENTS.md "Session continuity" makes this file mandatory reading for every new
session *before editing*, so a stale claim here steers the next agent directly.
The failure that happened: the handoff's Risks/blockers section said
"`make validate` is red for everyone" until a peer agent landed
`scripts/validate_fr_completeness.py`, and offered `make -o fr-completeness
validate` as the workaround. The prerequisite landed; the claim did not get
updated — so the next session would have been told, in writing, to disable the
brand-new FR/NFR traceability-completeness gate.

This mirrors `tests/test_factory_console_claims.py`, which guards the same two
failure modes on `docs/00-factory-console.md`. Neither document is under
`src/`, so `--cov=src` never sees them: these tests are the only mechanical
check.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

HANDOFF = REPO_ROOT / "docs" / "session-handoff.md"

# Claims that the top-level validation gate is currently broken. Deliberately
# wider than the console's variant: handoffs are hand-written prose and have
# used "is red" / "blocked" phrasing rather than the console's "exits non-zero".
BROKEN_VALIDATE_RE = re.compile(
    r"`make validate`[^\n]*(?:\n[^\n#]*)*?"
    r"(?:exits non-zero|currently fails|is broken|is red|is blocked|blocked)",
    re.IGNORECASE,
)

# A copy-pasteable prerequisite bypass, e.g. `make -o fr-completeness validate`.
VALIDATE_BYPASS_RE = re.compile(r"make\s+-o\s+\S+\s+validate")


@pytest.fixture(scope="module")
def handoff_text() -> str:
    return HANDOFF.read_text(encoding="utf-8")


def test_handoff_does_not_advertise_a_validate_prerequisite_bypass(handoff_text: str) -> None:
    """`make -o ... validate` skips a prerequisite gate; it must not be copy-pasteable."""
    assert VALIDATE_BYPASS_RE.search(handoff_text) is None, (
        "docs/session-handoff.md advertises a `make -o <target> validate` bypass, "
        "which skips a validation prerequisite. Remove it."
    )


def test_handoff_claim_about_make_validate_is_re_measured(handoff_text: str) -> None:
    """If the handoff claims `make validate` is red/blocked, prove it — else it is stale."""
    claim = BROKEN_VALIDATE_RE.search(handoff_text)
    if claim is None:
        return
    result = subprocess.run(
        ["make", "validate"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode != 0, (
        "docs/session-handoff.md claims `make validate` is red/blocked "
        f"({claim.group(0).strip()!r}), but it exits 0. A new session is required to "
        "read this file before editing — re-measure and update the claim."
    )
