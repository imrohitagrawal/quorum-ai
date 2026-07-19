"""The perf gate's collection floor must equal the perf suite it guards.

`PERF_MIN_TESTS` is the only thing standing between "perf-gate is green" and
"perf-gate collects a single sequential-latency case and measures nothing".
Unlike the contract floor — which is deliberately slack because schemathesis
parametrises off the live OpenAPI schema — the perf specs are hand-authored, so
the floor can and must sit at the exact collected count. A floor below the count
is dead slack: the hermeticity and concurrency specs can be deleted to make a
red build green and the guard still prints a pass.

This asserts against the *live* collection rather than a copied constant, so
adding perf specs without raising the floor fails here instead of silently
widening the hole.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"


def _make_variable(name: str) -> str:
    """Read a `NAME ?= value` assignment out of the Makefile."""
    text = MAKEFILE.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\s*\?=\s*(.+)$", text, flags=re.MULTILINE)
    assert match, f"{name} is not defined in the Makefile"
    return match.group(1).strip()


def _collected_count(paths: str) -> int:
    result = subprocess.run(
        ["uv", "run", "pytest", *paths.split(), "-q", "--no-cov", "--collect-only"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={
            **__import__("os").environ,
            "SENTRY_DSN": "",
            "OPENROUTER_LIVE_EXECUTION_ENABLED": "false",
            "QUORUM_RUNTIME_ENVIRONMENT": "ci",
        },
    )
    assert result.returncode == 0, f"perf collection failed:\n{result.stdout}"
    return sum(1 for line in result.stdout.splitlines() if "::" in line)


@pytest.fixture(scope="module")
def perf_collected() -> int:
    return _collected_count(_make_variable("PERF_TEST_PATHS"))


def test_perf_floor_equals_the_collected_perf_suite(perf_collected: int) -> None:
    floor = int(_make_variable("PERF_MIN_TESTS"))
    assert floor == perf_collected, (
        f"PERF_MIN_TESTS is {floor} but PERF_TEST_PATHS collects {perf_collected}. "
        "A floor below the count lets perf specs (hermeticity, concurrency) be "
        "deleted with `make perf-gate` still green; a floor above it fails the "
        "gate for everyone. Re-measure and update both the value and its comment."
    )


def test_perf_floor_comment_records_a_real_measurement(perf_collected: int) -> None:
    """The recorded 'perf collects N' must be the count, on a tree that has it.

    The prose above the floors is what a future agent reads before touching the
    number, so it has to be checkable too: the count it quotes must match the
    live collection, and if it cites a revision, that revision must actually
    contain the perf suite it claims to have measured.
    """
    text = MAKEFILE.read_text(encoding="utf-8")
    quoted = re.search(r"perf collects (\d+)", text)
    assert quoted, "the collection floors record no measured perf count"
    assert int(quoted.group(1)) == perf_collected, (
        f"the Makefile records 'perf collects {quoted.group(1)}' but "
        f"PERF_TEST_PATHS collects {perf_collected}"
    )

    cited = re.search(r"MEASURED at ([0-9a-f]{7,40})", text)
    if cited is None:
        return
    revision = cited.group(1)
    tracked = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", revision],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert tracked.returncode == 0, tracked.stderr
    perf_files = [
        line
        for line in tracked.stdout.splitlines()
        if line.startswith("tests/perf/") and line.endswith(".py")
    ]
    assert perf_files, (
        f"the floors claim to be measured at {revision}, but that tree has no "
        "tests/perf specs — the recorded number cannot be a measurement of it"
    )
