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
    """#332: two records were both written as ``docs/adr/0047-*.md`` — the one
    on ``origin/main`` and the one that became ADR-0049 — and the index carried
    two ADR-0047 rows while ``make validate`` exited 0. (ADR-0049's Consequences
    section is the source; it also records that three branches were editing this
    directory at the time, which is a different fact.)

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


def test_the_generator_refuses_a_padding_variant_duplicate(tmp_path: Path) -> None:
    """Padding is not identity: ``0047-x.md`` and ``47-y.md`` claim ONE number.

    Grouping by the raw digit string put them in two buckets, so the refusal
    above never fired. Verified against the unfixed generator on a
    ``git archive HEAD`` copy, 2026-08-17: ``_duplicate_numbers`` returned
    ``{}`` and ``build_table()`` returned a table carrying both an ``ADR-47``
    row and an ``ADR-0047`` row.

    Turns red if: ``_number_key`` stops collapsing the padding — e.g. it returns
    the raw prefix instead of ``f"{int(...):04d}"``.
    """
    module = _load_generator()
    module.ADR_DIR = tmp_path
    _write_adr(tmp_path, "0047-padded-claimant.md", "Padded claimant")
    _write_adr(tmp_path, "47-unpadded-claimant.md", "Unpadded claimant")

    try:
        module.build_table()
    except SystemExit as exc:
        message = str(exc)
        # The message must name the FILES a human has to go and rename, not
        # only a normalised number that appears in no filename.
        assert "0047-padded-claimant.md" in message
        assert "47-unpadded-claimant.md" in message
    else:  # pragma: no cover - the assertion above is the contract
        raise AssertionError("a padding-variant duplicate must not produce an index")


def test_padding_normalisation_does_not_merge_two_different_numbers(
    tmp_path: Path,
) -> None:
    """The over-reach partner for the test above: collapsing leading zeros must
    not collapse numbers that genuinely differ. ``0047`` and ``0470`` are two
    records and must both be indexed.

    Turns red if: ``_number_key`` normalises by stripping zeros anywhere rather
    than reading the digits as a number.
    """
    module = _load_generator()
    module.ADR_DIR = tmp_path
    _write_adr(tmp_path, "0047-forty-seven.md", "Forty seven")
    _write_adr(tmp_path, "0470-four-hundred-and-seventy.md", "Four hundred and seventy")

    table = module.build_table()

    assert "ADR-0047" in table
    assert "ADR-0470" in table


def test_the_generator_refuses_a_heading_that_contradicts_its_filename(
    tmp_path: Path,
) -> None:
    """The number a human CITES is the ``# ADR-NNNN:`` heading; both duplicate
    gates compare FILENAMES. Nothing compared the two, so two records could each
    self-identify as ADR-0050 while their filenames differed and every gate
    stayed green.

    Verified against the unfixed generator on a ``git archive HEAD`` copy,
    2026-08-17: two files named ``0060-alpha.md`` and ``0061-beta.md``, both
    headed ``# ADR-0050:``, produced rows ``ADR-0060`` and ``ADR-0061`` at exit
    0 with no complaint.

    A padding difference alone is NOT a contradiction — both sides go through
    ``_number_key`` — which is what the second case below pins.

    Turns red if: the ``heading_number != filename_number`` refusal in ``_row``
    is deleted.
    """
    module = _load_generator()
    module.ADR_DIR = tmp_path
    tmp_path.joinpath("0060-alpha.md").write_text(
        "# ADR-0050: Alpha\n\n## Status\n\nAccepted.\n", encoding="utf-8"
    )

    try:
        module.build_table()
    except SystemExit as exc:
        message = str(exc)
        assert "0060-alpha.md" in message
        assert "0050" in message
    else:  # pragma: no cover - the assertion above is the contract
        raise AssertionError("a heading contradicting the filename must be refused")

    # ...and a padding-only difference is accepted, so the check cannot be
    # satisfied by a naive string comparison that would reject `47-x.md` headed
    # `# ADR-0047:`.
    other = tmp_path / "other"
    other.mkdir()
    other.joinpath("47-unpadded.md").write_text(
        "# ADR-0047: Unpadded\n\n## Status\n\nAccepted.\n", encoding="utf-8"
    )
    module.ADR_DIR = other
    assert "ADR-0047" in module.build_table()


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
