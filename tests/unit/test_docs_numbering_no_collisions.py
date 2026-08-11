"""ADR-0034 exists because nothing checked a new doc's number against the
tree before it was committed — 14 numbers collided (28 files) before
housekeeping PR 4 resolved them. This test is the check that was missing.

What turns it red: `git mv docs/24-adr-index.md docs/17-adr-index.md`
(or any other rename that makes two tracked `docs/NN-*.md` files share a
leading number) and run this suite. Restore with `cp`-aside/restore, never
`git checkout`, per this repo's own mutation-proof convention.
"""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_NUMBER_PREFIX = re.compile(r"^docs/(\d+)-")


def _tracked_docs_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "docs/*.md"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def test_the_scan_sees_a_nonzero_number_of_numbered_docs() -> None:
    """Floor: a scan over zero files would let the collision check pass vacuously."""
    numbered = [p for p in _tracked_docs_files() if _NUMBER_PREFIX.match(p)]
    assert len(numbered) > 100


def test_no_two_docs_share_a_leading_number() -> None:
    by_number: dict[str, list[str]] = defaultdict(list)
    for path in _tracked_docs_files():
        match = _NUMBER_PREFIX.match(path)
        if match is None:
            continue
        by_number[match.group(1)].append(path)

    collisions = {number: paths for number, paths in by_number.items() if len(paths) > 1}
    assert not collisions, (
        "two or more docs/NN-*.md files share a leading number -- pick a free "
        "slot in the matching theme range instead (see ADR-0034, "
        "docs/adr/0034-docs-numbering-scheme-and-ranges.md, for the range table "
        "and how to find a free number):\n"
        + "\n".join(f"  {number}: {paths}" for number, paths in sorted(collisions.items()))
    )
