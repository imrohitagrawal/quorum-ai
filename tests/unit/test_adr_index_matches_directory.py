"""The ADR index is DERIVED, so it is verified, not trusted.

It went stale twice by hand: ADR-0002 was unlisted for 11 days in July 2026,
and ADR-0004..0007 landed unlisted in August 2026. The index's own note said
"generate it from the directory rather than fixing it by hand a second time" —
which is exactly what did not happen, because a note is a suggestion.

This is the same note as a condition.

GATE CHARTER
------------
WHY THIS EXISTS: the index went stale by hand twice -- ADR-0002 unlisted for 11
days (2026-07-19..30), then ADR-0004..0007 landed unlisted (2026-08-03). Its own
note already said "generate it rather than fix it by hand a second time", which
is precisely what did not happen, because a note is a suggestion.

WHAT IT CANNOT SEE: whether an ADR *should* have been written. It checks the
index matches the directory, nothing about decisions that were never recorded.
Measured by review: it would have caught **zero** of the 6 ADRs this batch
failed to write.

FALSE-POSITIVE COST: zero. It fires only when the file disagrees with the
directory, which is always a real defect.

WHEN TO REMOVE: when the index stops being a hand-maintainable artifact --
e.g. it is generated at docs-build time, or the ADR list moves to a tool that
owns it. Not before: the failure it guards has recurred once already.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "scripts" / "generate_adr_index.py"
ADR_DIR = ROOT / "docs" / "adr"
INDEX = ROOT / "docs" / "24-adr-index.md"


def test_the_index_lists_exactly_the_adrs_on_disk() -> None:
    """Turns red if: an ADR is added without regenerating the index."""
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, (
        f"docs/24-adr-index.md is stale.\n{result.stdout}{result.stderr}"
        "\nFix: python3 scripts/generate_adr_index.py"
    )


def test_every_adr_on_disk_is_actually_referenced() -> None:
    """The positive partner.

    ``--check`` compares the generator's output to the file, so it would also
    pass if BOTH were empty. This asserts the population is real — the
    anti-vacuity rule this repo applies to every other negative check.
    """
    records = sorted(ADR_DIR.glob("[0-9]*.md"))
    assert len(records) >= 3, "expected the existing ADRs to be present"

    index_text = INDEX.read_text(encoding="utf-8")
    missing = [p.name for p in records if p.name not in index_text]
    assert not missing, f"ADRs on disk but absent from the index: {missing}"


def test_the_generator_refuses_to_write_an_empty_index(tmp_path: Path) -> None:
    """A generator that emits an empty table on a bad path would silently
    erase the record. Asserted rather than assumed."""
    import importlib.util
    from typing import Any

    spec = importlib.util.spec_from_file_location("gen", GENERATOR)
    assert spec and spec.loader
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    module.ADR_DIR = tmp_path  # empty directory
    try:
        module.build_table()
    except SystemExit as exc:
        assert "refusing to write an empty index" in str(exc)
    else:  # pragma: no cover - the assertion above is the contract
        raise AssertionError("an empty ADR directory must not produce an index")
