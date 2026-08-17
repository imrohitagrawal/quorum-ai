"""ADR-0034 exists because nothing checked a new doc's number against the
tree before it was committed — 14 numbers collided (28 files) before
housekeeping PR 4 resolved them. This test is the check that was missing.

What turns it red: renaming `docs/24-adr-index.md` to share a leading
number with `docs/17-requirement-registry.md` (or any other rename that
makes two tracked `docs/NN-*.md` files collide) and running this suite.
Restore with `cp`-aside/restore, never `git checkout`, per this repo's own
mutation-proof convention.

TWO POPULATIONS, ONE CONCERN (#332)
-----------------------------------
`docs/NN-*.md` and `docs/adr/NNNN-*.md` are numbered independently, and both
break the same way when two files claim one number. The `docs/adr/` half was
NOT covered until 2026-08-17: `_NUMBER_PREFIX` is anchored `^docs/(\\d+)-`, and
`git ls-files "docs/*.md"` DOES list the ADRs (the glob crosses the slash), so
all 48 of them were fed to this gate and silently dropped by the pattern.
Measured on 2026-08-17:

    $ git ls-files "docs/*.md" | grep -c "^docs/adr/"
    48
    $ ... | python3 -c "...count matches of ^docs/(\\d+)-..."
    matched by existing regex: 0

Three branches each created a `docs/adr/0047-*.md`; `make validate` exited 0
and the index carried two ADR-0047 rows. `_ADR_NUMBER_PREFIX` below closes it.

NOTE FOR ANYONE ADDING AN ADR: discovery here is `git ls-files`, so a NEW,
UNCOMMITTED `docs/adr/*.md` is invisible to this gate until it is `git add`ed.
`scripts/generate_adr_index.py` globs the FILESYSTEM instead and sees it at
once — which is why the duplicate refusal lives in BOTH places, not one.
"""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_NUMBER_PREFIX = re.compile(r"^docs/(\d+)-")
_ADR_NUMBER_PREFIX = re.compile(r"^docs/adr/(\d+)-")


def _tracked_docs_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "docs/*.md"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _collisions(paths: list[str], pattern: re.Pattern[str]) -> dict[str, list[str]]:
    """Numbers claimed by more than one path, as {number: [paths]}.

    Takes the path list as an ARGUMENT so the duplicate and gap cases can be
    driven from synthetic input without writing anything into the real tree.
    A gap in the sequence is not a collision and is not reported.
    """
    by_number: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        match = pattern.match(path)
        if match is None:
            continue
        by_number[match.group(1)].append(path)
    return {number: paths for number, paths in by_number.items() if len(paths) > 1}


def test_the_scan_sees_a_nonzero_number_of_numbered_docs() -> None:
    """Floor: a scan over zero files would let the collision check pass vacuously."""
    numbered = [p for p in _tracked_docs_files() if _NUMBER_PREFIX.match(p)]
    assert len(numbered) > 100


def test_no_two_docs_share_a_leading_number() -> None:
    """Turns red if: two tracked `docs/NN-*.md` files are given the same NN."""
    collisions = _collisions(_tracked_docs_files(), _NUMBER_PREFIX)
    assert not collisions, (
        "two or more docs/NN-*.md files share a leading number -- pick a free "
        "slot in the matching theme range instead (see ADR-0034, "
        "docs/adr/0034-docs-numbering-scheme-and-ranges.md, for the range table "
        "and how to find a free number):\n"
        + "\n".join(f"  {number}: {paths}" for number, paths in sorted(collisions.items()))
    )


def test_the_scan_sees_the_real_population_of_adrs() -> None:
    """The anti-vacuity floor for the ADR half: `_ADR_NUMBER_PREFIX` matching
    nothing is EXACTLY the defect #332 reports, and it would leave the
    collision check below trivially true.

    The floor is deliberately loose. Measured 2026-08-17,
    `git ls-files "docs/adr/*.md" | wc -l` printed 48, and the population only
    grows, so 40 cannot be tripped by adding an ADR — while a regex that
    matched nothing (0) or only a handful still trips it.

    A COUNT ALONE IS NOT ENOUGH, measured: reverting `_ADR_NUMBER_PREFIX` to the
    original buggy `^docs/(\\d+)-` left this test GREEN, because that pattern
    matches the 100+ `docs/NN-*.md` files instead and 100 clears a floor of 40.
    So the floor also asserts every matched path is really under `docs/adr/` —
    otherwise it certifies a healthy population it never looked at.

    Turns red if: `_ADR_NUMBER_PREFIX` is re-anchored so it stops matching
    `docs/adr/NNNN-*.md` paths — the original bug.
    """
    numbered = [p for p in _tracked_docs_files() if _ADR_NUMBER_PREFIX.match(p)]
    assert len(numbered) >= 40
    not_adrs = [p for p in numbered if not p.startswith("docs/adr/")]
    assert not not_adrs, (
        "the ADR floor is counting files that are not ADRs, so it is measuring "
        f"the wrong population: {not_adrs[:5]}"
    )


def test_no_two_adrs_share_a_leading_number() -> None:
    """#332: three branches each created a `docs/adr/0047-*.md`, `make validate`
    exited 0, and the index carried two ADR-0047 rows.

    Turns red if: a second `docs/adr/0047-*.md` (or any repeated ADR number) is
    committed.
    """
    collisions = _collisions(_tracked_docs_files(), _ADR_NUMBER_PREFIX)
    assert not collisions, (
        "two or more docs/adr/NNNN-*.md files claim the same ADR number -- "
        "renumber the newer record to a free slot. Find the highest in use "
        'with `git ls-files "docs/adr/*.md" | tail -1`, and check unmerged '
        "branches too, since a number can be claimed by a branch that has not "
        "landed yet (see ADR-0050):\n"
        + "\n".join(f"  {number}: {paths}" for number, paths in sorted(collisions.items()))
    )


def test_a_repeated_adr_number_is_actually_detected() -> None:
    """The negative check above ("no collisions") is trivially true over input
    the pattern cannot match. This is its positive partner: fed a duplicate,
    the same helper and the same pattern must REPORT it.

    Turns red if: `_collisions` stops grouping by number, or
    `_ADR_NUMBER_PREFIX` stops matching ADR paths.
    """
    collisions = _collisions(
        [
            "docs/adr/0047-first-claimant.md",
            "docs/adr/0047-second-claimant.md",
            "docs/adr/0049-unique-one.md",
        ],
        _ADR_NUMBER_PREFIX,
    )

    assert collisions == {
        "0047": [
            "docs/adr/0047-first-claimant.md",
            "docs/adr/0047-second-claimant.md",
        ]
    }


def test_a_gap_in_the_adr_sequence_is_not_a_collision() -> None:
    """A missing number is normal, not a defect: on 2026-08-17 the tree ran
    0001..0047 then 0049, because 0048 is claimed by the unmerged branch
    `origin/fix/226-vacuous-e2e-negative-assertions`. A gate that demanded a
    contiguous run would be red on clean `main` today.

    The sequence below is synthetic and deliberately does NOT use 0048, so this
    test keeps its meaning once that gap is filled.

    Turns red if: the collision check is widened into a contiguity check.
    """
    collisions = _collisions(
        [
            "docs/adr/0001-first.md",
            "docs/adr/0002-second.md",
            "docs/adr/0004-fourth.md",  # 0003 deliberately absent
        ],
        _ADR_NUMBER_PREFIX,
    )

    assert collisions == {}


def test_the_adr_pattern_does_not_swallow_the_top_level_docs_population() -> None:
    """The two populations must stay separate: if `_ADR_NUMBER_PREFIX` also
    matched `docs/NN-*.md`, the ADR floor and collision check would be
    measuring the wrong tree and `docs/24-adr-index.md` would look like ADR-24.

    Turns red if: `_ADR_NUMBER_PREFIX` loses its `adr/` segment.
    """
    assert _ADR_NUMBER_PREFIX.match("docs/adr/0049-a-record.md") is not None
    assert _ADR_NUMBER_PREFIX.match("docs/24-adr-index.md") is None
    assert _NUMBER_PREFIX.match("docs/adr/0049-a-record.md") is None
