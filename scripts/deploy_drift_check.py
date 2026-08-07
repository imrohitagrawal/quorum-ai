#!/usr/bin/env python3
"""Assert that production actually runs `main`'s tip, and go red when it does not.

This is the POSITIVE check #245's third failure mode needs. On 2026-08-07 a
merge to `main` produced **zero** workflow runs, so `deploy.yml` — which is
`on.workflow_run` — was never even considered: no Deploy run, no skipped job, no
red. Production served the previous build for 34m31s while `/ready`, `/status`,
the Availability check and the Error-rate check all reported healthy, because
each of them answers from whatever build is running, not from the build that
*should* be running.

Everything already in place asks a weaker question:

* `deploy-drift-watchdog.yml` asked "does `main` HEAD have a successful Deploy
  RUN?". That is a proxy — it cannot see a Deploy run that reported success
  while production did not actually roll.
* `availability-check.yml` asserts `/ready` is 200 and `live`. True of a stale
  build.

`/status.build_sha` is the truth: `deploy.yml` passes
`--build-arg GIT_SHA=<sha>`, the Dockerfile bakes it into `BUILD_SHA`, and
`/status` serves it. Comparing it to `main`'s tip is the check AGENTS.md rule 18
makes a human perform.

Per ADR-0024 the decision lives here, in tested Python, rather than in an inline
shell block: a decision that cannot be tested drifts from its own documentation,
which is exactly how #62's fail-loud contract stayed false for weeks.

Exit codes: 0 when production is in sync or a deploy is legitimately in flight;
1 when it has drifted, or when either side could not be read. An unreadable
input is LOUD on purpose — printing a blank and exiting 0 is the silent
wrong-number failure this script exists to prevent.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from enum import Enum

#: How long after a commit lands on `main` production is still allowed to be
#: serving the previous build before that counts as drift.
#:
#: MEASURED, not chosen by taste. On 2026-08-07:
#:   * typical (`2931c8c`): merged 08:37:36Z, deploy job finished 08:50:47Z
#:     -> 13m11s (791s). Most of that is the gate WAITING for E2E.
#:   * worst (`bd7c46b`): merged 08:16:16Z, and the first production build
#:     containing it finished deploying at 08:50:47Z -> 34m31s (2071s),
#:     because its own merge triggered nothing and it had to ride the next
#:     merge's deploy.
#:
#: 45 minutes clears the measured worst case by ~13 minutes. Larger would hide a
#: real drift for longer than the incident it is meant to catch; smaller would
#: alert on an ordinary slow deploy.
DEFAULT_GRACE_SECONDS = 2700.0

DEFAULT_STATUS_URL = "https://quorum-ai.fly.dev/status"

#: Bound the status probe. `/status` is free (rule 18) but it is still a network
#: call, and a hung socket must not hang the workflow.
_STATUS_TIMEOUT_SECONDS = 10.0


class DriftDecision(Enum):
    """Every terminal state. Pinned exhaustively by the test suite."""

    IN_SYNC = "in_sync"
    DEPLOY_IN_FLIGHT = "deploy_in_flight"
    DRIFTED = "drifted"
    UNKNOWN = "unknown"


#: The decisions that must alert. UNKNOWN is here deliberately: "I could not
#: tell" is a failure of the check, and a check that cannot tell must not read
#: as healthy.
_ALERTING = frozenset({DriftDecision.DRIFTED, DriftDecision.UNKNOWN})


@dataclass(frozen=True)
class DriftResult:
    decision: DriftDecision
    detail: str

    @property
    def should_alert(self) -> bool:
        return self.decision in _ALERTING


def _clean(value: str | None) -> str:
    return (value or "").strip().lower()


def evaluate_drift(
    *,
    main_tip: str | None,
    build_sha: str | None,
    tip_age_seconds: float | None,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
) -> DriftResult:
    """Decide whether production has drifted from `main`'s tip.

    ``tip_age_seconds`` is how long ago the current tip commit landed. A
    mismatch younger than ``grace_seconds`` is an ordinary in-flight deploy.
    """
    tip = _clean(main_tip)
    served = _clean(build_sha)

    if not tip:
        return DriftResult(
            DriftDecision.UNKNOWN,
            "could not resolve main's tip SHA — refusing to report health from a "
            "value that was never read",
        )
    if not served:
        return DriftResult(
            DriftDecision.UNKNOWN,
            f"could not read build_sha from production — main's tip is {tip}, "
            "but what production serves is unknown",
        )

    if tip == served:
        return DriftResult(
            DriftDecision.IN_SYNC,
            f"production serves main's tip {tip}",
        )

    if tip_age_seconds is None:
        return DriftResult(
            DriftDecision.UNKNOWN,
            f"production serves {served} but main's tip is {tip}, and the age of "
            "the tip commit could not be determined, so this cannot be told "
            "apart from an in-flight deploy",
        )

    if tip_age_seconds < grace_seconds:
        return DriftResult(
            DriftDecision.DEPLOY_IN_FLIGHT,
            f"production serves {served}, main's tip is {tip}, landed "
            f"{tip_age_seconds:.0f}s ago — inside the {grace_seconds:.0f}s grace "
            "period, so a deploy is presumed in flight",
        )

    return DriftResult(
        DriftDecision.DRIFTED,
        f"production serves {served} but main's tip is {tip}, which landed "
        f"{tip_age_seconds:.0f}s ago — past the {grace_seconds:.0f}s grace "
        "period. Nothing is going to deploy it on its own.",
    )


# --------------------------------------------------------------------------
# I/O. Every fetch returns None on failure so the decision above stays pure and
# an unreadable input becomes UNKNOWN rather than an exception or a silent pass.
# --------------------------------------------------------------------------


def fetch_build_sha(url: str) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=_STATUS_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — any failure means "unknown"
        print(f"could not read {url}: {exc.__class__.__name__}: {exc}")
        return None
    value = payload.get("build_sha")
    return value if isinstance(value, str) and value.strip() else None


def _gh(args: list[str]) -> str | None:
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60, check=False)
    except Exception as exc:  # noqa: BLE001
        print(f"gh {' '.join(args)} failed: {exc.__class__.__name__}: {exc}")
        return None
    if out.returncode != 0:
        print(f"gh {' '.join(args)} exited {out.returncode}: {out.stderr.strip()[:200]}")
        return None
    return out.stdout.strip() or None


def fetch_main_tip(repo: str) -> tuple[str | None, float | None]:
    """Return (tip SHA, seconds since the tip commit was committed)."""
    raw = _gh(
        [
            "api",
            f"repos/{repo}/commits/main",
            "--jq",
            "[.sha, .commit.committer.date] | @tsv",
        ]
    )
    if not raw:
        return None, None
    parts = raw.split("\t")
    if len(parts) != 2:
        return None, None
    sha, when = parts[0].strip(), parts[1].strip()

    import datetime as _dt

    try:
        landed = _dt.datetime.fromisoformat(when.replace("Z", "+00:00"))
        age = (_dt.datetime.now(_dt.UTC) - landed).total_seconds()
    except ValueError:
        return sha or None, None
    return sha or None, age


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("REPO", ""))
    parser.add_argument("--status-url", default=os.environ.get("STATUS_URL", DEFAULT_STATUS_URL))
    parser.add_argument(
        "--grace-seconds",
        type=float,
        default=float(os.environ.get("DRIFT_GRACE_SECONDS", DEFAULT_GRACE_SECONDS)),
    )
    args = parser.parse_args(argv)

    if not args.repo:
        print("no --repo/REPO given — cannot resolve main's tip")
        tip, age = None, None
    else:
        tip, age = fetch_main_tip(args.repo)

    served = fetch_build_sha(args.status_url)

    result = evaluate_drift(
        main_tip=tip,
        build_sha=served,
        tip_age_seconds=age,
        grace_seconds=args.grace_seconds,
    )
    print(f"decision={result.decision.value}")
    print(result.detail)

    step_summary = os.environ.get("GITHUB_OUTPUT")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(f"decision={result.decision.value}\n")
            handle.write(f"should_alert={'true' if result.should_alert else 'false'}\n")

    return 1 if result.should_alert else 0


if __name__ == "__main__":
    sys.exit(main())
