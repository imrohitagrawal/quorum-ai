"""Housekeeping PR 2 — closes the gap that let generated artifacts get tracked.

Deleting ``e2e/undefined/`` (two screenshots from an unset path template
variable — the directory name is literally the JS string ``"undefined"``)
without a gate just waits for the next one. This test fails the moment a
generated-artifact pattern is committed again, rather than relying on someone
noticing during review.

What turns it red: `git add -f` any of —
* a path with a directory component named ``undefined`` or ``null`` (the
  classic unset-template-variable marker, exactly how ``e2e/undefined/``
  happened),
* a `.coverage` file, or a macOS duplicate-name copy of one (`.coverage 2`,
  `.coverage 3`, ...),
* a `.DS_Store` file,
* anything under a top-level `.hypothesis/` directory,

then commit it (even `git commit --no-verify` — this is a pytest gate, not a
pre-commit hook) and run this suite.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_BAD_PATH_COMPONENTS = {"undefined", "null"}


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def test_the_scan_sees_a_nonzero_number_of_tracked_files() -> None:
    """Floor: a scan over zero files would let every check below pass vacuously."""
    assert len(_tracked_files()) > 1000


def test_no_tracked_path_has_an_unset_template_variable_component() -> None:
    problems = [path for path in _tracked_files() if set(Path(path).parts) & _BAD_PATH_COMPONENTS]
    assert not problems, (
        "tracked path(s) contain a literal 'undefined'/'null' directory "
        f"component — an unset template variable almost certainly generated "
        f"these, exactly how e2e/undefined/ happened: {problems}"
    )


def test_no_tracked_coverage_data_file() -> None:
    problems = [
        path
        for path in _tracked_files()
        if Path(path).name == ".coverage" or Path(path).name.startswith(".coverage ")
    ]
    assert not problems, f"tracked .coverage data file(s): {problems}"


def test_no_tracked_ds_store() -> None:
    problems = [path for path in _tracked_files() if Path(path).name == ".DS_Store"]
    assert not problems, f"tracked .DS_Store file(s): {problems}"


def test_no_tracked_hypothesis_cache() -> None:
    problems = [path for path in _tracked_files() if ".hypothesis" in Path(path).parts]
    assert not problems, f"tracked .hypothesis/ cache file(s): {problems}"
