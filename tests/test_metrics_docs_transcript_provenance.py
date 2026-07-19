"""Provenance gate for pasted transcripts under `docs/metrics/`.

The metrics docs justify shipped guardrail values (the 95% changed-lines floor, the
mutation baseline) with fenced, verbatim-looking command output. A pasted transcript
is the strongest evidence a doc can offer, so its *label* has to be as true as its
numbers: `docs/metrics/diff-cover.md` shipped a block headed
"Run on ... @ `5ccd6f9`" that quoted `544 passed, 1 skipped` and
`Total coverage: 88.42%`, while the whole suite at `5ccd6f9` is only 502 collected
tests. The numbers came from some mid-flight working tree; the commit named cannot
produce them.

Whole-suite totals (`N passed`, `Total coverage: X%`) are a property of a *working
tree*, not of a commit: they move with every uncommitted test a peer adds. So they
must never be attributed to a bare commit SHA, because that attribution invites a
reader to re-run at that SHA and promises a match the toolchain cannot deliver.
Per-diff sections (which diff-cover computes against a named base ref) are unaffected.

The same doc carries a second, quieter version of the defect: the pasted diff-cover
section and the prose that reasons about it ("on a branch with N changed lines, K or
more uncovered lines breach the threshold") are three copies of the same numbers.
They drift the moment the branch grows — the block said `Total: 165 lines` while the
tree measured 173 — so their agreement is asserted here rather than trusted.

`docs/` is not under `src/`, so `--cov=src` never sees this; the check is mechanical
here or nowhere.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
METRICS_DIR = REPO_ROOT / "docs" / "metrics"
DIFF_COVER_DOC = METRICS_DIR / "diff-cover.md"
MAKEFILE = REPO_ROOT / "Makefile"

FENCE_RE = re.compile(r"^[ \t]*```[^\n]*\n(.*?)^[ \t]*```", re.MULTILINE | re.DOTALL)

# A whole-suite total: pytest's summary line, or coverage.py's repo-wide footer.
SUITE_TOTAL_RE = re.compile(
    r"^\s*(?:=*\s*)?(?:\d+ failed,\s*)?\d+ passed[ ,]|^\s*(?:Required test coverage"
    r" of \d+% reached\.\s*)?Total coverage:",
    re.MULTILINE,
)

# "Run on `branch` @ `5ccd6f9`" / "Measured at commit `5ccd6f9`" — an explicit claim
# that the block below is reproducible at that revision.
SHA_ATTRIBUTION_RE = re.compile(
    r"@\s*`?[0-9a-f]{7,40}`?"
    r"|(?:run|measured|captured|recorded)\s+(?:on|at)\b[^\n]*`[0-9a-f]{7,40}`",
    re.IGNORECASE,
)


# The pasted `make diff-cover` footer, and the two prose restatements of it.
DIFF_TOTALS_RE = re.compile(
    r"^Total:\s+(\d+) lines\s*\n^Missing:\s+(\d+) lines\s*\n^Coverage:\s+(\d+)%",
    re.MULTILINE,
)
PROSE_TOTALS_RE = re.compile(
    r"changed-lines coverage:\s*(\d+)%\s*\((\d+) changed lines,\s*(\d+) missing\)",
    re.IGNORECASE,
)
PROSE_BREACH_RE = re.compile(
    r"on a branch with (\d+) changed lines,\s*\*\*(\d+) or more\*\*", re.IGNORECASE
)
DIFF_COVER_MIN_RE = re.compile(r"^DIFF_COVER_MIN\s*\?=\s*(\d+)", re.MULTILINE)


def _blocks_with_intro(text: str) -> list[tuple[str, str]]:
    """(intro paragraph, fenced body) for every code fence in a markdown doc."""
    blocks = []
    for match in FENCE_RE.finditer(text):
        before = text[: match.start()].rstrip()
        # The nearest preceding non-empty paragraph is what labels the block.
        intro = before.split("\n\n")[-1] if before else ""
        blocks.append((intro, match.group(1)))
    return blocks


@pytest.fixture(scope="module")
def metrics_blocks() -> list[tuple[Path, str, str]]:
    return [
        (doc, intro, body)
        for doc in sorted(METRICS_DIR.glob("*.md"))
        for intro, body in _blocks_with_intro(doc.read_text(encoding="utf-8"))
    ]


def test_the_gate_still_recognises_the_original_defect(
    metrics_blocks: list[tuple[Path, str, str]],
) -> None:
    """Guard the gate: prove extraction and both regexes on the pre-fix doc verbatim.

    Asserting against the *current* docs would make this vacuous the moment they stop
    quoting suite totals — which is the outcome the gate is pushing them toward. So the
    self-check runs on a frozen copy of the block that triggered the finding instead.
    """
    defective = (
        "## Measured baseline (evidence)\n\n"
        "Run on `feat/r2-s1-run-history-persistence` @ `5ccd6f9`, base "
        "`origin/main` (`5f7b1a6`), full suite, hermetic, $0.\n\n"
        "```\n$ make diff-cover\n544 passed, 1 skipped in 30.11s\n"
        "Required test coverage of 88% reached. Total coverage: 88.42%\n```\n"
    )
    blocks = _blocks_with_intro(defective)
    assert len(blocks) == 1, f"fence extraction is broken; it found {len(blocks)} blocks"
    intro, body = blocks[0]
    assert SUITE_TOTAL_RE.search(body), "suite-total detection no longer fires"
    assert SHA_ATTRIBUTION_RE.search(intro), "SHA-attribution detection no longer fires"
    assert metrics_blocks, "no fenced blocks found under docs/metrics/ at all"


def test_suite_totals_are_not_attributed_to_a_commit_sha(
    metrics_blocks: list[tuple[Path, str, str]],
) -> None:
    """A fence pinned to a SHA must not quote totals that SHA cannot reproduce."""
    for doc, intro, body in metrics_blocks:
        if not SUITE_TOTAL_RE.search(body):
            continue
        attribution = SHA_ATTRIBUTION_RE.search(intro)
        assert attribution is None, (
            f"{doc.relative_to(REPO_ROOT)} labels a pasted transcript with the commit "
            f"attribution {attribution.group(0)!r} and quotes a whole-suite total "
            "inside it. Suite totals belong to a working tree, not a commit — a "
            "reader re-running at that SHA will get different numbers. Label the "
            "block with the tree and date it was measured on, or trim the quote to "
            "the part that does reproduce."
        )


@pytest.fixture(scope="module")
def diff_cover_doc() -> str:
    return DIFF_COVER_DOC.read_text(encoding="utf-8")


def _baseline_section(text: str) -> str:
    """The `## Measured baseline (evidence)` section, up to the next H2.

    The doc also pastes synthetic RED/GREEN transcripts with their own totals; the
    prose claims are about the baseline one only.
    """
    start = text.index("## Measured baseline")
    rest = text[start:]
    end = rest.find("\n## ", 1)
    return rest if end == -1 else rest[:end]


def test_pasted_diff_cover_totals_are_self_consistent(diff_cover_doc: str) -> None:
    """Every pasted diff-cover footer must satisfy floor(100*(total-missing)/total)."""
    footers = DIFF_TOTALS_RE.findall(diff_cover_doc)
    assert footers, "no diff-cover Total/Missing/Coverage footer found — gate vacuous"
    for total, missing, coverage in footers:
        total, missing, coverage = int(total), int(missing), int(coverage)
        expected = (total - missing) * 100 // total
        assert expected == coverage, (
            f"{DIFF_COVER_DOC.name}: pasted footer says Coverage: {coverage}% but "
            f"{total} lines / {missing} missing floors to {expected}%. diff-cover "
            "cannot emit that combination — the block was edited by hand or pasted "
            "from a different run."
        )


def test_prose_matches_the_pasted_baseline_numbers(diff_cover_doc: str) -> None:
    """The headline restatement must not drift from the transcript it summarises."""
    section = _baseline_section(diff_cover_doc)
    footer = DIFF_TOTALS_RE.search(section)
    prose = PROSE_TOTALS_RE.search(section)
    assert footer is not None and prose is not None, (
        "the measured-baseline section must contain both a pasted diff-cover footer "
        "and its prose restatement; one of them is missing"
    )
    assert (prose.group(2), prose.group(3), prose.group(1)) == footer.groups(), (
        f"{DIFF_COVER_DOC.name}: prose claims {prose.group(1)}% "
        f"({prose.group(2)} changed lines, {prose.group(3)} missing) but the pasted "
        f"transcript says Total: {footer.group(1)} / Missing: {footer.group(2)} / "
        f"Coverage: {footer.group(3)}%. Re-measure and update both together."
    )


def test_breach_arithmetic_matches_the_shipped_threshold(diff_cover_doc: str) -> None:
    """ "N changed lines -> K uncovered breaches" must follow from DIFF_COVER_MIN."""
    breach = PROSE_BREACH_RE.search(diff_cover_doc)
    assert breach is not None, (
        "the 'why not 100' rationale must state the breach arithmetic "
        "('on a branch with N changed lines, **K or more** ...'); it is the only "
        "thing showing the 5% allowance is small in practice"
    )
    minimum = DIFF_COVER_MIN_RE.search(MAKEFILE.read_text(encoding="utf-8"))
    assert minimum is not None, "DIFF_COVER_MIN not found in Makefile"
    threshold, total, claimed = int(minimum.group(1)), *map(int, breach.groups())
    smallest = next(k for k in range(1, total + 1) if (total - k) * 100 // total < threshold)
    assert claimed == smallest, (
        f"{DIFF_COVER_DOC.name}: says {claimed} uncovered lines breach {threshold}% on "
        f"a {total}-line diff, but the smallest breaching count is {smallest}. Either "
        "the changed-line total is stale or the threshold moved."
    )
