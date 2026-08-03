"""A repo path named in prose must exist.

THE FAILURE THIS CLOSES. Prose in this repo cites files constantly — comments
point at the test that proves them, commit bodies point at the script that
measured them. A citation that does not resolve is worse than no citation: it
reads as evidence and cannot be followed. Measured repo-wide during the
2026-08-03 review: **1,352 repo-path citations, 38 unresolved (2.8%)**,
including a phantom `docs/adr/0003-chromium-only-e2e.md` that never existed.

COMMIT BEFORE YOU TRUST IT. The scope is `git diff origin/main...HEAD`, so an
UNCOMMITTED citation is invisible to it — the same caveat `make diff-cover`
carries (AGENTS.md rule 15a). In CI everything is committed, so it is exact
there; locally, run it after committing.

DIFF-SCOPED ON PURPOSE. It checks paths cited on lines this branch ADDED, not
the whole repository. The 38 pre-existing breaks are a backlog, not this
change's problem, and a gate that opens red on unrelated history gets disabled.

WHAT IT CANNOT DO. It checks a path RESOLVES, never that the claim around it is
true. "MEASURED: 0.267 (`scripts/probe.py`)" passes here even if 0.267 is
wrong — the point is to turn a 20-minute re-derivation into a 5-second one.
Nothing mechanical can tell Jaccard from containment by reading a sentence;
adversarial review remains the primary defence, and this repo has measured that
(0 of 16 src/ defects caught by a gate, 10 of 16 by review).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: A repo-relative path with a known source extension. Anchored on the leading
#: directory so ordinary prose ("src/ layout", "the tests directory") is not a
#: candidate, and a trailing extension so bare directory names are skipped.
_CITATION = re.compile(
    r"\b((?:docs|src|tests|scripts|e2e|profiles)/[\w./-]+\.(?:md|py|ts|mjs|yml|yaml|json|css|html))"
)

#: Only prose-bearing files. A path inside real code is already checked by the
#: import system or the test that runs it.
_SCANNED_SUFFIXES = {".md", ".py", ".ts", ".yml", ".yaml"}

#: Roots a citation may legitimately be relative to. `.github/workflows/e2e.yml`
#: names `tests/invariants/foo.spec.ts` while running with
#: `working-directory: e2e`, so that path is correct in its own context and
#: resolving it only from the repo root produced six false positives the first
#: time this gate ran. A gate that cries wolf gets deleted.
_CITATION_ROOTS = ("", "e2e")


def _added_lines() -> list[tuple[str, str]]:
    """(file, line) for every line this branch adds vs origin/main."""
    merge_base = subprocess.run(
        ["git", "merge-base", "origin/main", "HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if merge_base.returncode != 0:
        pytest.skip("origin/main not available; cannot diff-scope")
    diff = subprocess.run(
        ["git", "diff", "--unified=0", f"{merge_base.stdout.strip()}...HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert diff.returncode == 0, diff.stderr

    out: list[tuple[str, str]] = []
    current = ""
    for line in diff.stdout.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        elif (
            line.startswith("+")
            and not line.startswith("+++")
            and Path(current).suffix in _SCANNED_SUFFIXES
        ):
            out.append((current, line[1:]))
    return out


def test_every_repo_path_cited_on_an_added_line_exists() -> None:
    """Turns red if: a comment, docstring or doc names a file that is not there.

    The phantom `docs/adr/0003-chromium-only-e2e.md` in this repo's history is
    the exact shape.
    """
    added = _added_lines()
    broken: list[str] = []
    checked = 0
    for path, line in added:
        for cited in _CITATION.findall(line):
            # Strip trailing punctuation prose leaves behind.
            cited = cited.rstrip(".,;:)")
            checked += 1
            if not any((ROOT / prefix / cited).exists() for prefix in _CITATION_ROOTS):
                broken.append(f"{path}: {cited}")

    assert not broken, (
        "these paths are cited on lines this branch adds, but do not exist:\n  "
        + "\n  ".join(sorted(set(broken)))
    )
    # Anti-vacuity: "no broken citations" is trivially true over nothing.
    # This branch cites plenty; if it suddenly cites none, the regex broke.
    assert checked > 0, (
        "no repo-path citations were examined at all — the extractor is broken, "
        "not the branch. A negative check over an empty set proves nothing."
    )


def test_the_extractor_finds_a_citation_and_ignores_ordinary_prose() -> None:
    """The positive partner for the regex itself, which the test above depends
    on entirely."""
    found = _CITATION.findall(
        "see tests/unit/test_cited_paths_resolve.py and docs/adr/0002-x.md for why"
    )
    assert found == ["tests/unit/test_cited_paths_resolve.py", "docs/adr/0002-x.md"]

    # Directory mentions and bare words must not be treated as citations.
    assert _CITATION.findall("the src/ layout and the tests directory") == []


def test_a_path_relative_to_a_known_working_directory_resolves() -> None:
    """The e2e workflow cites specs relative to `working-directory: e2e`.
    Those are correct and must not be reported."""
    cited = "tests/invariants/readiness-no-flash.spec.ts"
    assert not (ROOT / cited).exists(), "precondition: not resolvable from the repo root"
    assert any((ROOT / prefix / cited).exists() for prefix in _CITATION_ROOTS)
