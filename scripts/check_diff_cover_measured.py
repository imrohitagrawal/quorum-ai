"""Fail-closed floor for the changed-lines coverage gate.

WHY THIS EXISTS — measured, not hypothetical
    `diff-cover --fail-under=95` computes a percentage over the changed lines it
    could map to the coverage report. When it maps NOTHING, the denominator is
    empty, the percentage is reported as 100, and the gate exits 0.

    Reproduced on 2026-07-29: two genuinely uncovered new lines were added to
    `fence()`, `build/coverage/coverage.xml` was replaced with a report
    containing no packages, and:

        $ uv run diff-cover build/coverage/coverage.xml \
              --compare-branch=origin/main --fail-under=95
        No lines with coverage information in this diff.
        rc=0

    That is a BLOCKING gate reporting success having measured nothing, and it is
    indistinguishable at the tick from a clean pass. It is the same shape as the
    two incidents this repository has already paid for: #130 (a green advisory
    job that had never scored a mutant) and #158 (a red one that had not either).

WHAT THIS CHECKS — and it is narrower than it sounds
    Every changed Python file under `src/` must be PRESENT in the coverage
    report. That catches the report COLLAPSING — a broken `<source>` mapping, a
    coverage run that imported nothing, an excluded path — which is the case
    where the percentage is computed over the wrong denominator entirely.

WHAT IT DOES **NOT** CLOSE — read this before citing it
    It does not make diff-cover see a change that has no executable lines. A
    module-level constant or config table is exactly that shape, and it is this
    repository's most expensive defect class.

    Reproduced 2026-07-29 against real coverage.py and real diff-cover: adding
    two rows to a module-level `PRICES` dict produced

        No lines with coverage information in this diff.   diff-cover rc=0
        {"total_num_lines": 0, "num_changed_lines": 2}

    and this floor **passed**, because the file was present in the report. The
    changed lines are not statements, so there is nothing for line coverage to
    measure. That is arithmetically correct and completely blind.

    So: the mutation gate cannot see module-level constants (its charter says
    so), and neither can this one. Two gates, one shared blind spot, and it is
    where the money configuration lives. Tracked as an open issue with the
    measurement that would decide a stricter rule.

    A zero-measured-line file is therefore REPORTED LOUDLY here rather than
    failed. Failing it would also fire on a comment-only or import-only edit,
    which is legitimate and frequent — and a floor that fires on legitimate work
    is a floor somebody switches off.

    It also cannot see whether the coverage numbers are CORRECT, only that the
    report covers the files the diff touched.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def changed_source_files(base: str) -> list[str]:
    """Changed (not deleted) Python files under src/, as repo-relative paths.

    BOTH the merge-base diff and the working tree, because diff-cover scores
    "staged and unstaged changes" too. Measured while building this: with only
    the three-dot range, an uncommitted `src/` edit was invisible here while
    diff-cover was scoring it — the floor would have passed over exactly the
    case it exists to catch.
    """
    found: list[str] = []
    for args in (
        ["diff", "--name-only", "--diff-filter=d", f"{base}...HEAD"],
        ["diff", "--name-only", "--diff-filter=d", "HEAD"],
    ):
        proc = subprocess.run(["git", *args], capture_output=True, text=True)
        if proc.returncode != 0:
            print(
                f"check_diff_cover_measured: `git {' '.join(args)}` failed: {proc.stderr.strip()}",
                file=sys.stderr,
            )
            raise SystemExit(2)
        found.extend(
            line
            for line in proc.stdout.splitlines()
            if line.startswith("src/") and line.endswith(".py")
        )
    return sorted(set(found))


def reported_files(coverage_xml: Path) -> set[str]:
    """Files the coverage report contains, as repo-relative paths.

    `<class filename=...>` is relative to `<source>`, which for `--cov=src` is
    the absolute `src/` directory. Both are joined back to a repo-relative path
    so the comparison with git's output is like-for-like.
    """
    root = ET.parse(coverage_xml).getroot()
    sources = [s.text or "" for s in root.findall(".//source")]
    repo = Path.cwd().resolve()
    prefixes = []
    for source in sources:
        try:
            prefixes.append(Path(source).resolve().relative_to(repo).as_posix())
        except ValueError:
            prefixes.append("")
    files: set[str] = set()
    for klass in root.findall(".//class"):
        name = klass.attrib.get("filename", "")
        for prefix in prefixes or [""]:
            files.add(f"{prefix}/{name}" if prefix else name)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--coverage-xml", default="build/coverage/coverage.xml")
    parser.add_argument("--json-report", default="build/coverage/diff-cover.json")
    args = parser.parse_args(argv)

    coverage_xml = Path(args.coverage_xml)
    if not coverage_xml.is_file():
        print(
            f"diff-cover floor: {coverage_xml} is missing — the gate cannot have "
            "measured anything. A gate measures or it fails."
        )
        return 1

    changed = changed_source_files(args.base)
    if not changed:
        print(
            "diff-cover floor: no Python under src/ changed — nothing to measure, "
            "and that is honest."
        )
        return 0

    reported = reported_files(coverage_xml)
    missing = sorted(set(changed) - reported)
    if missing:
        listed = "\n".join(f"    {path}" for path in missing)
        print(
            "diff-cover floor: these changed files are ABSENT from the coverage "
            f"report, so the changed-lines percentage was computed without them:\n{listed}\n"
            f"  report: {coverage_xml} ({len(reported)} files)\n"
            "  This is the empty-denominator failure: diff-cover prints 'No lines with "
            "coverage information in this diff' and exits 0, which looks identical to a "
            "clean pass. Check that the coverage run actually imported these modules and "
            "that <source> in the report still matches the repository layout."
        )
        return 1

    # Positive partner: say what was actually measured, so a pass is falsifiable.
    total = None
    report = Path(args.json_report)
    if report.is_file():
        total = json.loads(report.read_text()).get("total_num_lines")

    if total == 0:
        # Not a failure — see the module docstring. But it must not hide inside a
        # success message, which is how "0 changed lines measured" read before.
        listed = "\n".join(f"    {path}" for path in changed)
        print(
            "diff-cover floor: NOTICE — the changed src/ file(s) are in the coverage "
            "report, but NONE of their changed lines are executable statements, so "
            "diff-cover measured ZERO of them:\n"
            f"{listed}\n"
            "  The 95% you are about to see is over an empty denominator. This is the "
            "module-level-constant blind spot: a pricing table, a spend cap or a model "
            "id changes here and NO coverage gate can see it — the mutation gate cannot "
            "either. If this change touches money or configuration, it needs a pinned "
            "literal assertion, and a reviewer should read it rather than trust a tick."
        )
        return 0

    print(
        f"diff-cover floor: all {len(changed)} changed src/ file(s) are present in the "
        f"coverage report ({len(reported)} files reported"
        + (f", {total} changed lines measured" if total is not None else "")
        + ")."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
