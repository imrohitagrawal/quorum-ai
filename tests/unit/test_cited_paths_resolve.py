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

GATE CHARTER
------------
WHY THIS EXISTS: prose in this repo cites files constantly, and a citation that
does not resolve reads as evidence while being unfollowable. Measured
2026-08-03: 1,352 repo-path citations, 38 unresolved (2.8%), including a
phantom ADR filename that never existed. The same session cited an agent report
that exists nowhere in the repo as if it were a repo fact.

WHAT IT CANNOT SEE: whether the CLAIM around the path is true. "0.267
(`scripts/probe.py`)" passes even when 0.267 is wrong. Nothing mechanical can
tell Jaccard from containment by reading a sentence; adversarial review remains
the primary defence, and this repo measured 0 of 16 src/ defects caught by any
gate versus 10 of 16 by review.

FALSE-POSITIVE COST: near zero after THREE narrowings, all found by running it:
paths relative to `working-directory: e2e`; this file's own regex fixtures; and
a diff with no added lines in a scanned file type. The third was a design error,
not a narrowing. The anti-vacuity floor asserted `checked > 0` against the live
diff, which is empty on `main` by definition — so the gate failed on every push
to main, reddening it at the merge of the batch that introduced it and blocking
the deploy. Review then showed it would equally have red'd every UI-only pull
request, since `_SCANNED_SUFFIXES` excludes `.css`, `.html` and `.js`.

An empty DIFF is not a broken EXTRACTOR. The floor now compares our hand-rolled
diff parsing against `git diff --numstat`, an independent count of the same
quantity, and fires only when git says there are added lines and the parser
found none. Two claims made while fixing this were themselves false and are
recorded so nobody re-derives them: the regex fixture test is NOT a partner for
the diff plumbing (it never calls `_added_lines`), and printing the count did
NOT report anything, because pytest captures stdout and CI does not pass `-s`.

WHEN TO REMOVE: when prose stops carrying repo paths, or when a docs toolchain
resolves links at build time and fails on a broken one. Its scope is
diff-only; the 38 pre-existing breaks are backlog, not this gate's job.
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

#: This file is exempt from its own check. It necessarily contains example
#: paths that do NOT resolve -- regex fixtures, and the phantom ADR that
#: motivated the gate. A linter's test data is not a claim about the repo.
#: Scoped to exactly one file so the exemption cannot quietly widen.
_EXEMPT = (
    "tests/unit/test_cited_paths_resolve.py",
    # Pure vendored template content (see `.agents/skills/project-faq/CHANGELOG.md`):
    # these 3 files cite generic EXAMPLE paths for a hypothetical consumer project
    # (`docs/confluence/page-map.yaml`, `docs/runbook.md`, ...) -- illustrative
    # placeholders in an upstream template, not a claim about THIS repository, and
    # not bundle-relative self-references either (the `_SKILL_BUNDLE_RE` root above
    # doesn't help here). Exact-file-scoped, same convention as this file's own
    # exemption above, so it cannot quietly widen to cover real prose.
    ".agents/skills/project-faq/assets/project-profile.md",
    ".agents/skills/project-faq/assets/publish-targets.yaml",
    ".agents/skills/project-faq/ci/README.md",
)

#: A vendored skill bundle's own files (see `configs/external-skill-registry.json`) cite
#: paths relative to the bundle itself (`scripts/verify.py` meaning ITS OWN script), not
#: only relative to the repo root. A blanket `.agents/skills/` exemption was tried first
#: and rejected on review: it would silently stop checking genuine repo-root citations
#: that already exist inside other bundles' SKILL.md files (e.g.
#: `architecture-and-decisions/SKILL.md` cites real `docs/...` paths that SHOULD stay
#: checked). Instead, a citation found in a file under `.agents/skills/<name>/...` is
#: resolved against BOTH the normal roots below AND `.agents/skills/<name>` -- so a
#: bundle-relative self-reference resolves, while a genuinely broken citation (bundle-
#: relative or repo-root) still fails, and a real repo-root citation is still checked.
_SKILL_BUNDLE_RE = re.compile(r"^\.agents/skills/([^/]+)/")


def _merge_base() -> str:
    """The base this gate diffs against, or skip if origin/main is absent."""
    result = subprocess.run(
        ["git", "merge-base", "origin/main", "HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if result.returncode != 0:
        pytest.skip("origin/main not available; cannot diff-scope")
    return result.stdout.strip()


def _added_lines(base: str) -> list[tuple[str, str]]:
    """(file, line) for every line this branch adds vs ``base``."""
    diff = subprocess.run(
        ["git", "diff", "--unified=0", f"{base}...HEAD"],
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


def _added_line_count_from_git(base: str) -> int:
    """Added lines in scanned file types, counted by git rather than by us.

    THE POINT IS THE INDEPENDENCE. ``_added_lines`` above parses ``git diff``
    text by hand — the ``+++ b/`` prefix, the leading ``+``. If that parsing
    breaks, it returns an empty list and every negative check downstream passes
    over nothing. ``--numstat`` is a different code path through git that yields
    the same quantity, so the two disagreeing is exactly the signal that our
    parser is broken.

    A review of the first version of this fix demonstrated the gap: mutating
    ``"+++ b/"`` to ``"+++ zz/"`` left the gate green on a branch that really
    did cite a missing path. The docstring at the time claimed the regex fixture
    test covered this. It does not — that test exercises ``_CITATION`` and never
    touches this function.
    """
    out = subprocess.run(
        ["git", "diff", "--numstat", f"{base}...HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert out.returncode == 0, out.stderr
    total = 0
    for row in out.stdout.splitlines():
        fields = row.split("\t")
        if len(fields) != 3:
            continue
        added, _deleted, path = fields
        if added == "-":  # binary file; numstat reports no line counts
            continue
        if Path(path).suffix in _SCANNED_SUFFIXES:
            total += int(added)
    return total


def test_every_repo_path_cited_on_an_added_line_exists() -> None:
    """Turns red if: a comment, docstring or doc names a file that is not there.

    The phantom `docs/adr/0003-chromium-only-e2e.md` in this repo's history is
    the exact shape.
    """
    base = _merge_base()
    added = _added_lines(base)
    expected = _added_line_count_from_git(base)

    if expected == 0:
        # NOTHING IN SCOPE — and on `main` this is the normal state, not a
        # fault. The scope is `merge-base(origin/main, HEAD)...HEAD`; on `main`
        # itself that range is empty by definition.
        #
        # This gate shipped asserting `checked > 0` unconditionally, which
        # turned every push to `main` RED — including the merge of the batch
        # that introduced it, blocking the deploy. Review then showed it would
        # equally have red'd every UI-only pull request, because
        # `_SCANNED_SUFFIXES` excludes `.css`, `.html` and `.js`: a diff
        # touching only those yields no added lines either.
        #
        # The condition is `expected == 0`, not `not added`, so this message is
        # TRUE in both cases. An earlier revision skipped on `not added` and
        # told a branch that had added lines to two files that there were none.
        pytest.skip(
            "the diff adds no lines to any file type this gate scans "
            f"({', '.join(sorted(_SCANNED_SUFFIXES))}) — nothing in scope"
        )

    # PLUMBING FLOOR — the anti-vacuity check that can actually hold.
    #
    # git says there are added lines in scannable files. If our own hand-rolled
    # diff parser found none, the parser is broken and every negative check
    # below would pass over an empty set. Keyed on git's own count rather than
    # on "were any files changed", because a pure DELETION changes a scanned
    # file while legitimately adding nothing.
    assert added, (
        f"git reports {expected} added line(s) in scanned file types, but "
        "`_added_lines` extracted none — the diff parser is broken, not the "
        "branch. Every citation check below would pass vacuously."
    )

    # No count is kept. A diff can add lines and cite no paths at all — any
    # ordinary code change without prose — so "zero citations examined" is a
    # legitimate outcome here and asserting against it is what broke `main`.
    # The quantity that must never be silently zero is the PARSER's output, and
    # the plumbing floor above is what holds that.
    #
    # An earlier revision printed the count "so the gate reports what it
    # measured". Review demonstrated that was decoration: `pytest -q` showed the
    # line 0 times, `-s` showed it 1 time, and CI runs `make test-report`
    # without `-s`. The numbers that matter now live in the failure messages,
    # where they are actually read.
    broken: list[str] = []
    for path, line in added:
        if path in _EXEMPT:
            continue
        bundle_match = _SKILL_BUNDLE_RE.match(path)
        roots = _CITATION_ROOTS + ((f".agents/skills/{bundle_match.group(1)}",) if bundle_match else ())
        for cited in _CITATION.findall(line):
            # Strip trailing punctuation prose leaves behind.
            cited = cited.rstrip(".,;:)")
            if not any((ROOT / prefix / cited).exists() for prefix in roots):
                broken.append(f"{path}: {cited}")

    assert not broken, (
        "these paths are cited on lines this branch adds, but do not exist:\n  "
        + "\n  ".join(sorted(set(broken)))
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
