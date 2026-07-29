"""Fail-closed executed-count floor for a Playwright lane.

WHY
    `npx playwright test <specs>` exits 0 when every test it found was skipped,
    and exits 0 when a spec path silently matches nothing. Both look identical to
    a clean pass at the tick. The e2e job is BLOCKING, so a lane that quietly
    stopped running is a merge gate that stopped gating.

    This is the same guard the Makefile already applies to the perf and contract
    gates (`gate-min-executed` in the Makefile) — a gate measures or it fails —
    applied to the lane that actually carries this project's UI invariants.

WHAT IT CHECKS
    From the lane's own JUnit XML: tests executed (total minus failures and
    errors) is at or above a floor, and nothing was skipped.

WHAT IT CANNOT SEE
    Whether the specs assert anything useful. A lane of 138 vacuous tests
    satisfies this completely. It closes the "the lane stopped running" hole,
    not the "the lane never bit" hole — that one belongs to the invariants
    themselves being proven RED against a real defect.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def counts(report: Path) -> tuple[int, int]:
    """(executed, skipped) summed across every testsuite in *report*."""
    root = ET.parse(report).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    total = sum(int(s.attrib.get("tests", 0)) for s in suites)
    failures = sum(int(s.attrib.get("failures", 0)) for s in suites)
    errors = sum(int(s.attrib.get("errors", 0)) for s in suites)
    skipped = sum(int(s.attrib.get("skipped", 0)) for s in suites)
    return total - failures - errors, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="e2e/results.xml")
    parser.add_argument("--min", type=int, required=True, help="executed-count floor")
    parser.add_argument("--lane", required=True, help="lane name, for the message")
    args = parser.parse_args(argv)

    report = Path(args.report)
    if not report.is_file():
        print(
            f"{args.lane}: {report} is missing — the lane never produced its JUnit "
            "report, so there is no evidence it ran. A gate measures or it fails.",
            file=sys.stderr,
        )
        return 1

    executed, skipped = counts(report)
    if skipped:
        print(
            f"{args.lane}: {skipped} test(s) were SKIPPED. A blocking lane must not be "
            "silenced — remove the skip, or delete the spec deliberately and re-measure "
            "the floor below.",
            file=sys.stderr,
        )
        return 1
    if executed < args.min:
        print(
            f"{args.lane}: only {executed} test(s) executed, below the floor of "
            f"{args.min}. Either specs stopped matching their paths, or tests were "
            "removed. Playwright exits 0 in both cases, which is why this floor exists.",
            file=sys.stderr,
        )
        return 1
    print(f"{args.lane}: {executed} tests executed (floor {args.min}), 0 skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
