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

WHAT THIS CHECKS
    Every changed Python file under `src/` must be PRESENT in the coverage
    report. If a changed file is absent, the report cannot have measured it and
    the percentage is over the wrong denominator.

WHAT THIS DELIBERATELY DOES NOT CHECK
    It does not require `total_num_lines > 0`. A comment-only or blank-line
    change to a `src/` module legitimately contributes no executable lines, and
    failing that would be a false alarm that gets the floor switched off. The
    signal used instead — a changed file the report has never heard of — cannot
    be produced by a comment-only edit.

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
    print(
        f"diff-cover floor: all {len(changed)} changed src/ file(s) are present in the "
        f"coverage report ({len(reported)} files reported"
        + (f", {total} changed lines measured" if total is not None else "")
        + ")."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
