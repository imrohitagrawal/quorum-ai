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

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

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


def _load_generator() -> Any:
    """Import the generator as a module so ``ADR_DIR`` can be pointed at a
    temporary directory, leaving the real tree untouched."""
    spec = importlib.util.spec_from_file_location("gen", GENERATOR)
    assert spec and spec.loader
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_adr(directory: Path, filename: str, title: str) -> None:
    """Write the minimum an ADR needs for ``_row`` to parse it."""
    number = filename.split("-", 1)[0]
    directory.joinpath(filename).write_text(
        f"# ADR-{number}: {title}\n\n## Status\n\nAccepted.\n",
        encoding="utf-8",
    )


def test_the_generator_refuses_to_write_an_empty_index(tmp_path: Path) -> None:
    """A generator that emits an empty table on a bad path would silently
    erase the record. Asserted rather than assumed.

    Turns red if: ``build_table``'s ``if not records`` guard is deleted.
    """
    module = _load_generator()
    module.ADR_DIR = tmp_path  # empty directory
    try:
        module.build_table()
    except SystemExit as exc:
        assert "refusing to write an empty index" in str(exc)
    else:  # pragma: no cover - the assertion above is the contract
        raise AssertionError("an empty ADR directory must not produce an index")


def test_the_generator_refuses_to_write_an_index_with_duplicate_numbers(
    tmp_path: Path,
) -> None:
    """#332: three branches each created a ``docs/adr/0047-*.md`` and the index
    carried two ADR-0047 rows while ``make validate`` exited 0.

    Reproduced 2026-08-17 on a ``git archive HEAD`` copy: adding a second
    ``0047-*.md`` printed ``wrote docs/24-adr-index.md (49 records)`` at exit 0,
    ``grep -c "ADR-0047"`` returned 2, and ``--check`` printed
    ``adr-index: up to date (49 records)`` at exit 0.

    Turns red if: the duplicate-number guard in ``build_table`` is deleted.
    """
    module = _load_generator()
    module.ADR_DIR = tmp_path
    _write_adr(tmp_path, "0047-first-claimant.md", "First claimant")
    _write_adr(tmp_path, "0047-second-claimant.md", "Second claimant")
    _write_adr(tmp_path, "0049-unique-one.md", "Unique one")

    try:
        module.build_table()
    except SystemExit as exc:
        message = str(exc)
        # Structure, not substring of the prose: the message must name the
        # duplicated number AND both files that claim it.
        assert "0047" in message
        assert "0047-first-claimant.md" in message
        assert "0047-second-claimant.md" in message
        # The unique record is not accused.
        assert "0049-unique-one.md" not in message
    else:  # pragma: no cover - the assertion above is the contract
        raise AssertionError("two ADRs sharing a number must not produce an index")


def test_the_generator_still_writes_an_index_when_numbers_are_unique_but_gappy(
    tmp_path: Path,
) -> None:
    """The positive partner for the duplicate refusal, and the guard against
    over-reach: the real tree has an unused gap (0048 is held by the unmerged
    branch ``origin/fix/226-vacuous-e2e-negative-assertions``), so a gate that
    demanded a contiguous run would go red on clean ``main``.

    The synthetic sequence below is deliberately NOT the real gap value, so
    this test survives 0048 later being filled.

    Turns red if: the duplicate guard is widened into a contiguity check.
    """
    module = _load_generator()
    module.ADR_DIR = tmp_path
    _write_adr(tmp_path, "0001-first.md", "First")
    _write_adr(tmp_path, "0002-second.md", "Second")
    _write_adr(tmp_path, "0004-fourth.md", "Fourth")  # 0003 deliberately absent

    table = module.build_table()

    assert "ADR-0001" in table
    assert "ADR-0002" in table
    assert "ADR-0004" in table
