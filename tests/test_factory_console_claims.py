"""Truthfulness gate for `docs/00-factory-console.md` (ledger FS-4).

The console is the dashboard an operator reads before deciding what to do next,
and it is *fully overwritten* by `make next`. Two failure modes have already
happened on this repo and are gated here:

1. A **stale "measured" claim** — the console asserted `make validate` "exits
   non-zero for everyone" and advertised a `make -o <target> validate` bypass
   long after the prerequisite had landed. A claim in a block labelled
   *measured* must still be true when the suite runs, so this test re-measures.
2. An **unresolvable durable-evidence pointer** — the console said the durable
   copy of a hand-written section lived in another document that did not
   contain it, so the record was one `make next` away from vanishing.

Neither the console nor `scripts/factory_next.py` is under `src/`, so
`--cov=src` never sees them: this file is the only mechanical check.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

CONSOLE = REPO_ROOT / "docs" / "00-factory-console.md"

# Hand-written (non router-generated) record headings, e.g. "## ROUTER OVERRIDE — ...".
RECORD_HEADING_RE = re.compile(r"^## ([A-Z][A-Z ]{3,}?)\s*—", re.MULTILINE)

# A claim that some other document holds the durable copy of those records.
DURABLE_POINTER_RE = re.compile(r"durable copy[^.]*?lives in `([^`]+)`", re.IGNORECASE | re.DOTALL)

# Claims that the top-level validation gate is currently broken.
BROKEN_VALIDATE_RE = re.compile(
    r"`make validate`[^\n]*(?:\n[^\n#]*)*?(?:exits non-zero|currently fails|is broken)",
    re.IGNORECASE,
)

# A copy-pasteable prerequisite bypass, e.g. `make -o fr-completeness validate`.
VALIDATE_BYPASS_RE = re.compile(r"make\s+-o\s+\S+\s+validate")


@pytest.fixture(scope="module")
def console_text() -> str:
    return CONSOLE.read_text(encoding="utf-8")


def test_console_does_not_advertise_a_validate_prerequisite_bypass(console_text: str) -> None:
    """`make -o ... validate` disables a gate; it must not be copy-pasteable from the console."""
    assert VALIDATE_BYPASS_RE.search(console_text) is None, (
        "docs/00-factory-console.md advertises a `make -o <target> validate` bypass, "
        "which skips a validation prerequisite. Remove it."
    )


def test_console_claim_about_make_validate_is_re_measured(console_text: str) -> None:
    """If the console claims `make validate` is broken, prove it — otherwise the claim is stale."""
    claim = BROKEN_VALIDATE_RE.search(console_text)
    if claim is None:
        return
    result = subprocess.run(
        ["make", "validate"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode != 0, (
        "docs/00-factory-console.md claims `make validate` is broken "
        f"({claim.group(0).strip()!r}), but it exits 0. Re-measure and update the "
        "'Validation status (measured)' block."
    )


def test_durable_evidence_pointers_resolve(console_text: str) -> None:
    """Every hand-written record the console says is durably copied must exist at the target."""
    records = RECORD_HEADING_RE.findall(console_text)
    for rel_path in DURABLE_POINTER_RE.findall(console_text):
        target = REPO_ROOT / rel_path
        assert target.is_file(), (
            f"docs/00-factory-console.md points at `{rel_path}` for durable evidence, "
            "but that file does not exist."
        )
        target_text = target.read_text(encoding="utf-8")
        for record in records:
            assert record in target_text, (
                f"docs/00-factory-console.md says the durable copy lives in `{rel_path}`, "
                f"but that file contains no '{record}' record. The console is overwritten by "
                "`make next`, so the record would be lost."
            )


def test_ephemeral_records_are_marked_as_not_durable(console_text: str) -> None:
    """A hand-written record with no durable home must say so, not imply one exists."""
    records = RECORD_HEADING_RE.findall(console_text)
    if not records:
        return
    if DURABLE_POINTER_RE.search(console_text):
        return
    assert "NOT durable" in console_text, (
        "docs/00-factory-console.md carries hand-written records "
        f"({', '.join(records)}) with no durable copy pointer and no 'NOT durable' "
        "warning; `make next` will silently delete them."
    )
