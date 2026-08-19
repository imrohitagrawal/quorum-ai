"""Every apt-dependent CI step bounds its own time, and apt bounds each request.

WHY THIS FILE EXISTS, measured 2026-08-19 on run 32228043232 (main SHA 15d822c).

Three ATTEMPTS of that ``E2E (axe + parity)`` run were reported ``cancelled``
after ~20 minutes against a job ``timeout-minutes: 20``. **No test ever ran.**
The hung step was ``npx playwright install --with-deps``, which shells out to
apt. From the attempt-1 log::

    07:30:16-07:30:23  Ign:2..5 http://azure.archive.ubuntu.com/...  (x12)
    07:30:23.826       Hit:2 https://archive.ubuntu.com/ubuntu noble InRelease
    07:30:24.490       Get:5 https://archive.ubuntu.com/.../noble-security [126 kB]
    07:49:28.482       ##[error]The operation was canceled

The Azure mirror was unresponsive, the runner's own mirrorlist failover
engaged and reached the canonical mirror in ~7s, and then apt went silent for
**19m04s** talking to ``archive.ubuntu.com``. A healthy run (32222230691) shows
``Hit:2`` on azure, zero ``Ign:`` lines, ``Fetched 11.4 MB in 1s``, step 21s.

Two defects, and this file pins the fix for both:

1. **apt had no per-request timeout**, so a stalled transfer consumed the JOB
   budget. ``Acquire::Retries`` alone would not help — N retries with no
   per-request timeout still hang (AGENTS.md rule 8b: bound the TIME).
2. **The failure was illegible.** A job killed by its own ``timeout-minutes``
   reports ``cancelled``, byte-identical to a concurrency cancellation, so the
   deploy gate's STRANDED-merge message named neither apt nor the timeout. That
   cost two wrong causal claims before the log was read properly.

This is a REGRESSION detector. It cannot see a mirror that starts stalling; it
ensures a new apt-dependent step cannot be added without a time bound.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from tests.repo_root import find_repo_root

REPO_ROOT = find_repo_root(Path(__file__))
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
BOUND_ACTION = "./.github/actions/bound-apt-waits"
ACTION_FILE = REPO_ROOT / ".github" / "actions" / "bound-apt-waits" / "action.yml"

#: Anything whose ``run:`` contains this shells out to apt-get, which is what
#: stalled. ``playwright install`` WITHOUT ``--with-deps`` does not.
APT_MARKER = "--with-deps"

#: One parsed workflow step. ``yaml.safe_load`` gives plain dicts.
_Step = dict[str, object]


def _apt_steps() -> list[tuple[str, str, int, _Step, _Step | None, object]]:
    """(workflow, job, index, step, preceding step, job timeout) per apt step."""
    found: list[tuple[str, str, int, _Step, _Step | None, object]] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_name, job in (doc.get("jobs") or {}).items():
            steps = job.get("steps") or []
            for i, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                if APT_MARKER in str(step.get("run", "")):
                    found.append(
                        (
                            path.name,
                            job_name,
                            i,
                            step,
                            steps[i - 1] if i else None,
                            job.get("timeout-minutes"),
                        )
                    )
    return found


def _action_script() -> str:
    """The composite action's shell body, PARSED out of the YAML.

    Deliberately not a read of the whole file: an earlier version of this
    module asserted the ``Acquire::*::Timeout`` strings appeared anywhere in
    the file, which a COMMENT naming them satisfies (AGENTS.md rule 8 —
    assert structure, not substrings; rule 6b — could this pass for any
    implementation?). Review demonstrated exactly that hole.
    """
    doc = yaml.safe_load(ACTION_FILE.read_text(encoding="utf-8")) or {}
    steps = (doc.get("runs") or {}).get("steps") or []
    return "\n".join(str(s.get("run", "")) for s in steps)


def test_the_scan_sees_apt_dependent_steps() -> None:
    """Positive partner for the negative checks below (AGENTS.md rule 7).

    The checks below are "no step lacks X", trivially true over an empty list.
    This proves the list is not empty and the parser reaches the workflows.

    Turns red if: the glob, the parser or ``APT_MARKER`` stops matching — e.g.
    the workflows directory is renamed, or every ``--with-deps`` is dropped
    (in which case delete this file and the action together rather than leave
    a gate that measures nothing).
    """
    assert _apt_steps(), (
        f"no step under {WORKFLOWS} has a run: containing {APT_MARKER!r} — "
        "this gate is measuring NOTHING."
    )
    # No literal count on purpose (rule 1a): a corpus count goes stale silently.


@pytest.mark.parametrize("marker", [APT_MARKER])
def test_every_apt_dependent_step_is_time_bounded(marker: str) -> None:
    """Each apt-shelling step declares its own ``timeout-minutes``.

    Turns red if: ``timeout-minutes`` is removed from any
    ``playwright install --with-deps`` step. Without it a stalled mirror
    consumes the whole job budget and the job reports ``cancelled``, which
    reads as a concurrency cancellation rather than a hang.
    """
    unbounded = [
        f"{wf}:{job} step[{i}] {step.get('name', '<unnamed>')!r}"
        for wf, job, i, step, _prev, _jt in _apt_steps()
        if step.get("timeout-minutes") is None
    ]
    assert not unbounded, (
        "these steps shell out to apt with no time bound, so a stalled mirror "
        "hangs them until the JOB timeout and the failure surfaces as an "
        "unexplained 'cancelled':\n  " + "\n  ".join(unbounded)
    )


def test_each_step_bound_can_actually_fire_before_the_job_bound() -> None:
    """A step bound >= its job's bound is not a bound at all.

    Review demonstrated this: setting the step to any value >= the job's
    ``timeout-minutes`` restores the ORIGINAL symptom — the job dies first,
    reports ``cancelled``, and names no step. The step bound only buys
    legibility if it fires first.

    This compares two INDEPENDENT declared values, not a constant against
    itself, so it is not the rule-7a trap.

    Turns red if: any step's ``timeout-minutes`` is raised to or above its
    job's, or the job's is lowered to or below a step's.
    """
    offenders = []
    for wf, job, i, step, _prev, job_timeout in _apt_steps():
        step_timeout = step.get("timeout-minutes")
        if step_timeout is None or job_timeout is None:
            continue
        if int(str(step_timeout)) >= int(str(job_timeout)):
            offenders.append(f"{wf}:{job} step[{i}] step={step_timeout}min >= job={job_timeout}min")
    assert not offenders, (
        "these step bounds cannot fire before their job bound, so a hang still "
        "surfaces as an unexplained job-level 'cancelled':\n  " + "\n  ".join(offenders)
    )


def test_every_apt_dependent_step_is_preceded_by_the_wait_bounding() -> None:
    """The bounding action runs immediately before each apt-shelling step.

    Order matters: apt reads its config at invocation, so bounding afterwards
    is a no-op.

    Turns red if: the ``uses: ./.github/actions/bound-apt-waits`` step is
    deleted or reordered away from directly before an install step.
    """
    missing = [
        f"{wf}:{job} step[{i}] {step.get('name', '<unnamed>')!r} "
        f"(preceded by {(prev or {}).get('name') or (prev or {}).get('uses') or '<nothing>'!r})"
        for wf, job, i, step, prev, _jt in _apt_steps()
        if (prev or {}).get("uses") != BOUND_ACTION
    ]
    assert not missing, (
        f"these steps shell out to apt without {BOUND_ACTION} immediately "
        "before them, so apt has no per-request timeout:\n  " + "\n  ".join(missing)
    )


def test_the_action_writes_a_per_request_timeout_not_only_retries() -> None:
    """The action's SCRIPT writes apt timeout directives.

    Asserted against the parsed ``run:`` body, not the file text, so a comment
    mentioning the directives cannot satisfy it — review proved the previous
    whole-file substring version had exactly that hole.

    Turns red if: the ``Acquire::*::Timeout`` lines are dropped from the
    script, leaving only ``Acquire::Retries``. That is the rule-8b distinction
    that mattered here: N retries against a stalled transfer with no
    per-request timeout still hangs forever.
    """
    script = _action_script()
    for directive in ("Acquire::http::Timeout", "Acquire::https::Timeout"):
        assert directive in script, (
            f"{directive} is not written by the action's script; a retry count "
            "alone does not bound a stalled transfer"
        )
    assert "apt-config dump" in script, (
        "the action must read its write back through apt itself — a config file "
        "apt silently fails to parse is the same as no bound at all"
    )


def test_the_action_does_not_claim_to_rewrite_mirrors() -> None:
    """Guards a retracted, twice-wrong causal theory from coming back.

    The first version of this change rewrote ``azure.archive.ubuntu.com`` in
    ``/etc/apt/sources.list.d/ubuntu.sources``. It was wrong twice over:
    a NO-OP on ubuntu-24.04 (the runner puts azure in
    ``/etc/apt/apt-mirrors.txt`` and leaves ``mirror+file:`` in the sources),
    and aimed at the wrong hop anyway — the measured 19m04s stall was on the
    CANONICAL mirror, after failover had already succeeded.

    Turns red if: a mirror rewrite is reintroduced into the action's script.
    If a future change genuinely needs one, it must target
    ``/etc/apt/apt-mirrors.txt`` and ship evidence that the mirror, not the
    transfer, is what stalled — delete this test in that same commit.
    """
    script = _action_script()
    assert "sources.list" not in script, (
        "the action is editing apt sources again. That approach was measured "
        "to be a no-op on ubuntu-24.04 and aimed at the wrong hop; see the "
        "docstring and ADR-0061 before reinstating it."
    )
