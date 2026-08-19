"""Every apt-dependent CI step is bounded in time and uses the hardened mirror.

WHY THIS FILE EXISTS, measured 2026-08-19.

Three consecutive ``E2E (axe + parity)`` runs on main SHA ``15d822c`` were
reported ``cancelled`` after 20m19s, 20m22s and ~21m against a job
``timeout-minutes: 20``. **No test ever ran.** The job was stuck in
``npx playwright install --with-deps``, which shells out to apt-get, and apt
was looping on a black-holed Azure mirror::

    Ign:2 http://azure.archive.ubuntu.com/ubuntu noble InRelease
    Hit:2 https://archive.ubuntu.com/ubuntu noble InRelease

The canonical mirror answered; only the Azure one GitHub runners default to
did not. At kill time the orphan process was
``npm exec playwright install --with-deps chromium``.

Two separate defects, and this file pins the fix for both:

1. **Unbounded network wait.** apt retried until the JOB budget was gone.
2. **An illegible failure.** A job killed by its own timeout is reported
   ``cancelled`` — byte-identical to a concurrency cancellation — so the
   deploy gate called it a STRANDED merge without naming the mirror or the
   timeout. It took three runs and a log dive to find. A step-level
   ``timeout-minutes`` makes the failure name the step that hung.

This is a REGRESSION detector. It cannot see a mirror that starts failing; it
only ensures a new apt-dependent step cannot be added without a time bound.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from tests.repo_root import find_repo_root

REPO_ROOT = find_repo_root(Path(__file__))
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
HARDEN_ACTION = "./.github/actions/harden-apt"

#: Anything whose ``run:`` contains this shells out to apt-get, which is the
#: operation that hung. ``playwright install`` WITHOUT ``--with-deps`` does
#: not, and is deliberately not covered.
APT_MARKER = "--with-deps"

#: One parsed workflow step. ``yaml.safe_load`` gives plain dicts.
_Step = dict[str, object]


def _apt_steps() -> list[tuple[str, str, int, _Step, _Step | None]]:
    """(workflow, job, index, step, preceding step) for every apt-shelling step."""
    found: list[tuple[str, str, int, _Step, _Step | None]] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_name, job in (doc.get("jobs") or {}).items():
            steps = job.get("steps") or []
            for i, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                if APT_MARKER in str(step.get("run", "")):
                    found.append((path.name, job_name, i, step, steps[i - 1] if i else None))
    return found


def test_the_scan_sees_apt_dependent_steps() -> None:
    """Positive partner for the two negative checks below (AGENTS.md rule 7).

    Both assertions below are of the form "no step lacks X", which is
    trivially true over an empty list. This proves the list is not empty and
    that the parser actually reaches the workflows.

    Turns red if: the glob, the parser, or ``APT_MARKER`` stops matching —
    e.g. someone renames the workflows directory, or every ``--with-deps``
    is dropped (in which case delete this file and the composite action
    together, rather than leaving a gate that measures nothing).
    """
    steps = _apt_steps()
    assert steps, (
        f"no step under {WORKFLOWS} has a run: containing {APT_MARKER!r} — "
        "this gate is measuring NOTHING. Either the parser broke or apt is no "
        "longer shelled out; do not leave this file passing vacuously."
    )
    # Deliberately no literal count (AGENTS.md rule 1a): a corpus count goes
    # stale the moment a workflow is added, and nothing compares it to the tree.


@pytest.mark.parametrize("marker", [APT_MARKER])
def test_every_apt_dependent_step_is_time_bounded(marker: str) -> None:
    """Each apt-shelling step declares its own ``timeout-minutes``.

    Turns red if: ``timeout-minutes`` is removed from any
    ``playwright install --with-deps`` step. Without it a hung mirror consumes
    the whole job budget and the job is reported ``cancelled``, which reads as
    a concurrency cancellation rather than a hang.

    NOTE this asserts the bound EXISTS, not its value, and deliberately does
    not compare against the constant that would define it (rule 7a).
    """
    unbounded = [
        f"{wf}:{job} step[{i}] {step.get('name', '<unnamed>')!r}"
        for wf, job, i, step, _prev in _apt_steps()
        if step.get("timeout-minutes") is None
    ]
    assert not unbounded, (
        "these steps shell out to apt with no time bound, so a black-holed "
        "mirror hangs them until the JOB timeout and the failure is reported "
        "as an unexplained 'cancelled':\n  " + "\n  ".join(unbounded)
    )


def test_every_apt_dependent_step_is_preceded_by_the_mirror_hardening() -> None:
    """The hardening action runs immediately before each apt-shelling step.

    Turns red if: the ``uses: ./.github/actions/harden-apt`` step is deleted or
    reordered away from directly before an install step. Order matters — apt
    reads its sources at invocation, so hardening after the install is a no-op.
    """
    missing = [
        f"{wf}:{job} step[{i}] {step.get('name', '<unnamed>')!r} "
        f"(preceded by {(prev or {}).get('name') or (prev or {}).get('uses') or '<nothing>'!r})"
        for wf, job, i, step, prev in _apt_steps()
        if (prev or {}).get("uses") != HARDEN_ACTION
    ]
    assert not missing, (
        f"these steps shell out to apt without {HARDEN_ACTION} immediately "
        "before them, so they use the Azure mirror that hung three runs on "
        f"2026-08-19:\n  " + "\n  ".join(missing)
    )


def test_the_hardening_action_bounds_the_time_not_only_the_retries() -> None:
    """The composite action sets an apt *timeout*, not just a retry count.

    Turns red if: the ``Acquire::*::Timeout`` lines are dropped from the
    action, leaving only ``Acquire::Retries``. This is the rule-8b distinction
    that mattered here — N retries against a black hole with no per-request
    timeout still hangs forever, so a retry count alone does not bound
    anything.
    """
    action = (REPO_ROOT / ".github" / "actions" / "harden-apt" / "action.yml").read_text(
        encoding="utf-8"
    )
    assert "Acquire::http::Timeout" in action and "Acquire::https::Timeout" in action, (
        "the hardening action must bound apt's per-request TIME; a retry count "
        "alone does not stop a hang against an unresponsive mirror"
    )
