"""Deploy gate: decide whether a Fly deploy may proceed for a commit.

Background — the race this fixes
--------------------------------
The Fly deploy (``.github/workflows/deploy.yml``) is gated on THREE required
workflows all being green for the *same* commit on ``main``: ``CI``, ``Tests``,
and ``E2E (axe + parity)``. Each of the three completing fires the deploy via
``workflow_run``.

The previous gate *skipped* whenever a required workflow was still in progress
and relied on the LAST-finishing workflow's trigger to be the one that deploys.
When that last trigger did not produce a landing deploy (a dropped
``workflow_run`` event, a concurrency-cancel interaction), the commit was
*merged but silently never deployed* under a green "Deploy success" — exactly
what happened to PR #44 (the Fly-volume mount): the fast checks (~40s) ran the
gate before the ~3-minute E2E finished, so every trigger that fired skipped, and
no trigger deployed.

The fix here
------------
The gate no longer skips-and-hopes. It **waits** (bounded poll) for every
required workflow to reach a terminal conclusion for the SHA, then proceeds iff
ALL succeeded. This removes the dependency on *which* trigger fires last: the
earliest-arriving trigger simply waits for the rest.

Decision rules (fail-safe — never deploy what we cannot positively verify):

* Any required workflow concluded non-``success`` (failure/cancelled/…): STOP
  immediately, do not deploy.
* All required workflows concluded ``success``: PROCEED.
* One or more still pending (queued / in progress / not yet visible via the REST
  API, or a transient ``gh api`` error): keep polling until they resolve or the
  overall ``timeout`` elapses. On timeout: do NOT deploy (unverified).
* ``workflow_dispatch``: the manual escape hatch — proceed immediately, ungated.

The core :func:`evaluate_gate` takes injectable ``fetch_conclusion`` / ``sleep``
/ ``monotonic`` collaborators so it is unit-tested with zero network and zero
real waiting (``tests/unit/test_deploy_gate.py``).
"""

from __future__ import annotations

import json
import os
import subprocess  # noqa: S404 - used only to shell out to the trusted `gh` CLI
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

#: The workflows that must ALL be green on the SHA before a deploy may proceed.
#: Order is irrelevant (the gate waits for every one); it must stay in sync with
#: ``deploy.yml``'s ``on.workflow_run.workflows`` list.
REQUIRED_WORKFLOWS: tuple[str, ...] = ("CI", "Tests", "E2E (axe + parity)")

#: The one conclusion that lets a deploy proceed. Everything else that is not
#: ``None`` (pending) blocks — this is an ALLOW-LIST on purpose. An earlier
#: block-LIST (failure/cancelled/…) failed open: a completed run whose conclusion
#: was outside the list — GitHub's ``skipped`` / ``neutral`` (materialised when a
#: required workflow is path-filtered or its jobs are ``if:``-skipped), or any
#: future conclusion string — slipped through as "not-failed" and was treated as
#: a pass. Fail-safe means: deploy ONLY on an explicit ``success``.
_SUCCESS = "success"

#: Default bounded-wait knobs. ``timeout`` comfortably exceeds the slowest
#: required workflow (E2E ≈ 3 min) with headroom for a loaded runner; ``poll``
#: is frequent enough to deploy promptly once the last check turns green.
DEFAULT_TIMEOUT_SECONDS = 900.0
DEFAULT_POLL_SECONDS = 15.0


class GateDecision(StrEnum):
    PROCEED = "proceed"
    #: A required workflow concluded non-success — a red build must never ship.
    BLOCKED_FAILURE = "blocked_failure"
    #: Still-pending workflows never resolved within ``timeout`` — unverified,
    #: so we refuse to deploy (fail-safe) rather than ship something unproven.
    BLOCKED_TIMEOUT = "blocked_timeout"


@dataclass(frozen=True)
class GateResult:
    decision: GateDecision
    #: Per-workflow last-seen conclusion (``None`` == still pending at exit).
    conclusions: dict[str, str | None]
    reason: str

    @property
    def proceed(self) -> bool:
        return self.decision is GateDecision.PROCEED


def evaluate_gate(
    fetch_conclusion: Callable[[str], str | None],
    *,
    required_workflows: tuple[str, ...] = REQUIRED_WORKFLOWS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    poll: float = DEFAULT_POLL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] = print,
) -> GateResult:
    """Wait (bounded) for every required workflow to conclude, then decide.

    ``fetch_conclusion(workflow_name)`` returns the workflow's latest conclusion
    for the SHA — ``"success"``, a terminal non-success string, or ``None`` when
    the workflow is still pending / not yet visible / a transient API error
    occurred. It is called once per workflow per poll round.

    Returns a :class:`GateResult`; ``.proceed`` is ``True`` only when ALL
    required workflows concluded ``success`` within ``timeout``.
    """
    if not required_workflows:
        # Defensive: an empty required set would otherwise "pass" vacuously
        # (nothing pending, nothing blocked → PROCEED). Refuse — a deploy with
        # zero verified gates is a misconfiguration, not a green light.
        log("No required workflows configured — refusing to deploy (fail-safe).")
        return GateResult(GateDecision.BLOCKED_FAILURE, {}, "no required workflows configured")
    start = monotonic()
    conclusions: dict[str, str | None] = dict.fromkeys(required_workflows)
    while True:
        for workflow in required_workflows:
            if conclusions[workflow] == _SUCCESS:
                continue  # already resolved green — don't re-poll
            conclusions[workflow] = fetch_conclusion(workflow)

        pending = [wf for wf, c in conclusions.items() if c is None]
        # Fail-safe: anything that concluded but is NOT exactly ``success``
        # (failure, cancelled, skipped, neutral, timed_out, an unknown future
        # string, …) blocks the deploy. Only ``None`` means "keep waiting".
        blocked = {wf: c for wf, c in conclusions.items() if c is not None and c != _SUCCESS}

        if blocked:
            detail = ", ".join(f"{wf}={c}" for wf, c in blocked.items())
            log(f"Required workflow(s) did not pass for the SHA: {detail} — NOT deploying.")
            return GateResult(GateDecision.BLOCKED_FAILURE, conclusions, detail)

        if not pending:
            log("All required workflows are green for the SHA — proceeding to deploy.")
            return GateResult(GateDecision.PROCEED, conclusions, "all required workflows green")

        elapsed = monotonic() - start
        if elapsed >= timeout:
            detail = ", ".join(pending)
            log(
                f"Timed out after {elapsed:.0f}s waiting for: {detail}. "
                "Refusing to deploy an unverified SHA (fail-safe)."
            )
            return GateResult(GateDecision.BLOCKED_TIMEOUT, conclusions, f"pending: {detail}")

        log(
            f"Still waiting on: {', '.join(pending)} "
            f"(elapsed {elapsed:.0f}s); re-poll in {poll:.0f}s"
        )
        sleep(poll)


def _select_conclusion(runs: list[object], *, workflow: str, repo: str) -> str | None:
    """Pick the latest GENUINE main-push run for ``workflow`` and return its
    conclusion, or ``None`` when there is no such completed run yet.

    Security-critical filtering (issue: a spoofable identity check). A run is
    only counted when ALL hold:

    * ``name == workflow`` — the required workflow, not some other one;
    * ``head_branch == "main"`` — but this ALONE is not enough: a fork PR whose
      source branch is literally named ``main`` also reports ``head_branch ==
      "main"`` while carrying attacker-controlled code and an attacker commit;
    * ``event == "push"`` — a real branch push, not a ``pull_request`` run;
    * ``head_repository.full_name == repo`` — the run ran on OUR repo's commit,
      not a fork's. A fork PR's run lists the fork here.

    Requiring push + our-repo defeats the fork-branch-named-``main`` spoof: that
    run has ``event == "pull_request"`` and ``head_repository`` == the fork, so
    it is excluded and never counts toward a green gate.

    Among the survivors the latest by ``run_started_at`` (tie-broken by ``id``)
    wins, so a failed run followed by a green re-run resolves to the re-run.
    A survivor that is not yet ``completed`` (queued / in progress) yields
    ``None`` (pending, keep waiting).
    """
    candidates = [
        run
        for run in runs
        if isinstance(run, dict)
        and run.get("name") == workflow
        and run.get("head_branch") == "main"
        and run.get("event") == "push"
        and isinstance(run.get("head_repository"), dict)
        and run["head_repository"].get("full_name") == repo
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda run: (run.get("run_started_at") or "", run.get("id") or 0))
    if latest.get("status") != "completed":
        return None
    conclusion = latest.get("conclusion")
    return conclusion if isinstance(conclusion, str) and conclusion else None


def gh_fetch_conclusion(repo: str, sha: str, workflow: str) -> str | None:
    """Return the latest genuine-``main`` run conclusion for ``workflow`` at ``sha``.

    Shells out to the trusted ``gh`` CLI for the raw run list (selection is done
    in :func:`_select_conclusion`, which is unit-tested). Returns ``None`` (==
    pending, keep waiting) when no matching completed run exists yet, or when the
    API call / JSON parse fails transiently — never raising, so a blip becomes a
    re-poll rather than a hard gate crash.
    """
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, trusted `gh`
            [
                "gh",
                "api",
                f"repos/{repo}/actions/runs?head_sha={sha}&per_page=100",
                "--jq",
                ".workflow_runs",  # just the array; all selection happens in Python
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    try:
        runs = json.loads(proc.stdout or "null")
    except ValueError:
        return None
    if not isinstance(runs, list):
        return None
    return _select_conclusion(runs, workflow=workflow, repo=repo)


def _write_output(proceed: bool) -> None:
    """Emit ``proceed=<bool>`` to ``$GITHUB_OUTPUT`` (and stdout for logs)."""
    value = "true" if proceed else "false"
    print(f"proceed={value}")
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"proceed={value}\n")


def main() -> int:
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    if event_name == "workflow_dispatch":
        print("Manual dispatch — deploying default-branch HEAD (ungated escape hatch).")
        _write_output(True)
        return 0

    repo = os.environ.get("REPO", "")
    sha = os.environ.get("SHA", "")
    if not repo or not sha:
        print("Missing REPO or SHA — cannot verify; refusing to deploy (fail-safe).")
        _write_output(False)
        return 0

    timeout = float(os.environ.get("GATE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    poll = float(os.environ.get("GATE_POLL_SECONDS", DEFAULT_POLL_SECONDS))
    print(f"Evaluating required workflows {list(REQUIRED_WORKFLOWS)} for SHA {sha}")
    result = evaluate_gate(
        lambda workflow: gh_fetch_conclusion(repo, sha, workflow),
        timeout=timeout,
        poll=poll,
    )
    print("Conclusions: " + json.dumps(result.conclusions))
    _write_output(result.proceed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
