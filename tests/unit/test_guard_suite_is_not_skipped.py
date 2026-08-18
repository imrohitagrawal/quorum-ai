"""The #131 guard's own test suite must never go wholly skipped again.

`tests/unit/test_negative_assertion_guard.py` spent months reporting green in
the required `pytest (Python 3.12)` context while every one of its tests
skipped: its autouse fixture needs `e2e/node_modules`, and no pytest lane ran
`npm ci`. ADR-0058 fixed the lane. This file is the watchdog that stops the
skip coming back.

**It lives in a separate file on purpose.** The first version of this check sat
inside the module it watches, and a review round proved that worthless by
mutation: a module-level `pytest.mark.skip`, or an unguarded `pytest.skip` at
the top of that module's autouse fixture — the exact original defect — silenced
the watchdog along with everything it was watching, and pytest still exited 0.
A watchdog inside the kennel it guards is not a watchdog.

Nothing here needs node: the first test runs the guard module as it stands, and
the second deliberately runs it with an EMPTY PATH so `node` cannot be found,
which is how the fail-versus-skip decision gets exercised on the wire rather
than only on the pure helper that computes it.

Honest limit: a `pytest.mark.skip` applied to THIS file is not caught by this
file. Nothing can self-guard against that. What is caught is every route that
silences the guard module, which is where the defect actually happened.
"""

from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from tests.unit.test_negative_assertion_guard import (
    NODE_TOOLING_REQUIRED_ENV,
    _missing_tooling,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD_MODULE = REPO_ROOT / "tests" / "unit" / "test_negative_assertion_guard.py"

pytestmark = pytest.mark.repo_introspection


def _run_the_guard_suite(env_overrides: dict[str, str | None]) -> dict[str, int]:
    """Run the guard module in a child pytest and return its JUnit counts.

    ``env_overrides`` values of ``None`` REMOVE the variable, so a lane that
    already exports the require flag cannot leak it into the "elsewhere" case.
    """
    relative = GUARD_MODULE.relative_to(REPO_ROOT).as_posix()
    # Per-pid name: two concurrent pytest processes must not share this file
    # (AGENTS.md rule 15 records the guard-xml race that taught this).
    junit = REPO_ROOT / "build" / "gates" / f"guard-no-skips-{os.getpid()}.xml"
    junit.parent.mkdir(parents=True, exist_ok=True)
    junit.unlink(missing_ok=True)

    environment = dict(os.environ)
    for key, value in env_overrides.items():
        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = value

    inner = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            relative,
            "-q",
            "--no-cov",
            "-p",
            "no:cacheprovider",
            f"--junitxml={junit}",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=environment,
        timeout=600,
    )
    assert junit.is_file(), (
        f"the inner pytest wrote no JUnit report — it died before collecting:\n"
        f"{inner.stdout}{inner.stderr}"
    )
    suite = ET.parse(junit).getroot().find("testsuite")
    junit.unlink(missing_ok=True)
    assert suite is not None, f"no testsuite in the inner report:\n{inner.stdout}{inner.stderr}"
    counts = {key: int(suite.get(key, "0")) for key in ("tests", "skipped", "failures", "errors")}
    counts["passed"] = counts["tests"] - counts["skipped"] - counts["failures"] - counts["errors"]
    counts["_stdout_len"] = len(inner.stdout)
    return counts


@pytest.mark.no_node_required
def test_the_guard_suite_never_goes_wholly_skipped() -> None:
    """No test in the guard module may skip once the node tooling is installed.

    Deliberately counts nothing: a floor like "at least N tests ran" goes stale
    the moment a test is added, and the count in the handoff that opened this
    work was already wrong (it said 28; `--collect-only` said 30). ``tests > 0``
    is the mandatory positive partner — ``skipped == 0`` alone is trivially true
    over an empty run (AGENTS.md rule 7).

    Fails rather than skips where the required lane set the flag: the one check
    whose whole job is "this file must not go all-skipped" must not itself be
    the quiet one when the tooling is missing.

    Turns red if: an unconditional skip returns to the guard module by any
    route — a module-level `pytest.mark.skip`, an unguarded `pytest.skip` in
    its autouse fixture, or a `skipif` on any test in it.
    """
    missing = _missing_tooling()
    if missing:
        reason = "; ".join(missing)
        if os.environ.get(NODE_TOOLING_REQUIRED_ENV) == "1":
            pytest.fail(
                f"{NODE_TOOLING_REQUIRED_ENV}=1 — this lane installs the node tooling "
                f"and this watchdog must run, but {reason}"
            )
        pytest.skip(reason)

    counts = _run_the_guard_suite({NODE_TOOLING_REQUIRED_ENV: "1"})
    assert counts["tests"] > 0, f"the inner run collected nothing: {counts}"
    assert counts["skipped"] == 0, (
        f"{counts['skipped']} of {counts['tests']} tests in {GUARD_MODULE.name} skipped "
        f"with the node tooling installed; in CI that is a required lane reporting "
        f"green over a gate it never ran"
    )
    assert counts["failures"] == 0 and counts["errors"] == 0, (
        f"the inner run was not clean: {counts}"
    )


@pytest.mark.no_node_required
def test_absent_tooling_errors_in_the_required_lane_and_skips_elsewhere(
    tmp_path: Path,
) -> None:
    """The fail-versus-skip decision, driven on the wire rather than in a helper.

    The pure `_tooling_verdict` table was already covered, and that proved
    nothing: mutating the fixture's `pytest.fail(` to `pytest.skip(` — reverting
    the whole point of ADR-0058 — left the entire suite green. This test hides
    `node` by emptying PATH and reads the child run's JUnit counts, so the
    fixture's actual branch is what is measured.

    The second half is the mandatory partner (AGENTS.md rule 7): without it,
    "absent tooling errors" is equally satisfied by a fixture that fails on
    every machine, which would make a fresh clone red.

    ``passed > 0`` in both halves pins the `no_node_required` opt-out: delete
    that early return from the fixture and every test skips, including the
    text-only ones that need nothing.

    Turns red if: the required branch goes back to `pytest.skip`, the
    unrequired branch starts failing, or the marker opt-out is removed.
    """
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()

    required = _run_the_guard_suite({"PATH": str(empty_bin), NODE_TOOLING_REQUIRED_ENV: "1"})
    assert required["errors"] > 0, (
        f"with the flag set and node unreachable the fixture must FAIL, not skip: {required}"
    )
    assert required["skipped"] == 0, (
        f"a skip survived in the lane that demanded these tests run: {required}"
    )
    assert required["passed"] > 0, (
        f"the node-free tests must still run when node is absent: {required}"
    )

    elsewhere = _run_the_guard_suite({"PATH": str(empty_bin), NODE_TOOLING_REQUIRED_ENV: None})
    assert elsewhere["skipped"] > 0, (
        f"a laptop without node must SKIP the node-driven tests, not run them: {elsewhere}"
    )
    assert elsewhere["errors"] == 0 and elsewhere["failures"] == 0, (
        f"a machine that never asked for these tests must not go red: {elsewhere}"
    )
    assert elsewhere["passed"] > 0, (
        f"the node-free tests must still run when node is absent: {elsewhere}"
    )
