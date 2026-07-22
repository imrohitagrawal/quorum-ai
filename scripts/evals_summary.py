"""OD-4: `make evals` — run the eval suites and print an honest summary.

Runs each suite under ``tests/evals/`` with the real pytest and prints a
per-suite table (suite, executed, passed, failed, pass rate). Every count
comes from the run that just happened — nothing is invented, and a failing
suite fails this script.

The two PINNED pilot measurements printed under the table are NOT re-run
here (they were operator-labelled, one-off measurements); they are cited
with their pinning documents so they are never mistaken for fresh numbers.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: (display name, pytest target) — one row per eval suite file.
SUITES: tuple[tuple[str, str], ...] = (
    ("synthesis checks", "tests/evals/test_synthesis_eval_checks.py"),
    ("output correctness (OC-1)", "tests/evals/test_output_correctness_gate.py"),
    ("trust calibration (OC-2)", "tests/evals/test_trust_calibration.py"),
    ("golden set gate", "tests/evals/test_golden_set_gate.py"),
    ("accuracy pilot harness", "tests/evals/test_accuracy_pilot.py"),
    ("refusal/fabrication residual", "tests/evals/test_refusal_fabrication_residual.py"),
)

#: One-off operator-labelled measurements, cited — never restated as new.
#: The accuracy pilot began as 7/7 (P2, PR #74) and was extended to n=10 by
#: the D5 operator-label queue (PR #76); the pinning doc now records the
#: merged 10/10 result, so that is what is cited here.
PINNED_LINES: tuple[str, ...] = (
    "Accuracy pilot: 10/10 engine-vs-operator agreement, n=10 "
    "(7 labels PR #74 + 3 D5-queue labels PR #76; pinned in "
    "docs/metrics/accuracy-pilot.md — not re-run here)",
    "D5 operator-label queue: all 4 entries complete "
    "(pinned in docs/metrics/operator-label-queue.md, PR #76; scored as part "
    "of the 10/10 pilot in docs/metrics/accuracy-pilot.md — not re-run here)",
)

_SUMMARY_RE = re.compile(
    r"(?:(?P<failed>\d+) failed)?(?:, )?"
    r"(?:(?P<passed>\d+) passed)?(?:, )?"
    r"(?:(?P<skipped>\d+) skipped)?"
)


@dataclass
class SuiteResult:
    name: str
    passed: int
    failed: int
    skipped: int

    @property
    def executed(self) -> int:
        return self.passed + self.failed

    @property
    def pass_rate(self) -> str:
        if self.executed == 0:
            return "n/a"
        return f"{100.0 * self.passed / self.executed:.0f}%"


def parse_pytest_summary(output: str) -> tuple[int, int, int]:
    """Extract (passed, failed, skipped) from pytest terminal output.

    Reads the LAST summary-shaped line (e.g. ``3 failed, 5 passed, 1 skipped
    in 0.42s``) so intermediate progress lines never confuse it. Raises when
    no summary line is found — an honest crash beats a silent zero row.
    """
    passed = failed = skipped = None
    for line in output.splitlines():
        if " in " not in line or not re.search(r"\d+ (passed|failed|skipped)", line):
            continue
        match = _SUMMARY_RE.search(line.strip())
        if match is None:
            continue
        passed = int(match.group("passed") or 0)
        failed = int(match.group("failed") or 0)
        skipped = int(match.group("skipped") or 0)
    if passed is None:
        raise ValueError(f"no pytest summary line found in output:\n{output[-2000:]}")
    return passed, failed or 0, skipped or 0


def run_suite(name: str, target: str) -> SuiteResult:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", target, "-q", "--no-cov", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    passed, failed, skipped = parse_pytest_summary(proc.stdout)
    return SuiteResult(name=name, passed=passed, failed=failed, skipped=skipped)


def main() -> int:
    results = [run_suite(name, target) for name, target in SUITES]

    name_w = max(len(r.name) for r in results)
    print()
    print(f"{'suite':<{name_w}}  executed  passed  failed  pass rate")
    print(f"{'-' * name_w}  --------  ------  ------  ---------")
    for r in results:
        print(
            f"{r.name:<{name_w}}  {r.executed:>8}  {r.passed:>6}  {r.failed:>6}  {r.pass_rate:>9}"
        )
    total_exec = sum(r.executed for r in results)
    total_pass = sum(r.passed for r in results)
    total_fail = sum(r.failed for r in results)
    rate = f"{100.0 * total_pass / total_exec:.0f}%" if total_exec else "n/a"
    print(f"{'-' * name_w}  --------  ------  ------  ---------")
    print(f"{'TOTAL':<{name_w}}  {total_exec:>8}  {total_pass:>6}  {total_fail:>6}  {rate:>9}")
    print()
    print("Pinned pilot measurements (cited, not re-run):")
    for line in PINNED_LINES:
        print(f"  - {line}")
    print()
    if total_fail:
        print(f"EVALS RED: {total_fail} failing test(s) — see the suites above.")
        return 1
    print("All eval suites green (hermetic run, $0, judge OFF).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
