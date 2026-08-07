#!/usr/bin/env python3
"""Assert that production actually runs `main`'s tip, and go red when it does not.

This is the POSITIVE check #245's third failure mode needs. On 2026-08-07 a
merge to `main` produced **zero `push`-event runs**, so `deploy.yml` — which is
`on.workflow_run` off CI/Tests/E2E — was never fired by that merge at all.
Production served the previous build for 34m31s while `/ready`, `/status`, the
Availability check and the Error-rate check all reported healthy, because each
answers from whatever build is running rather than the build that *should* be.

(Two `Deploy to Fly.io` runs DO exist for that SHA, both `skipped` — fired by
`pull_request` runs on another branch. An earlier draft of this file said
"nothing at all", which was false; what was zero is `push`-event runs.)

Everything already in place asks a weaker question:

* `deploy-drift-watchdog.yml` asked "does `main` HEAD have a successful Deploy
  RUN?". That is a proxy — it reads only `.workflow_runs[].conclusion`, so it
  cannot see a run that reported success while production did not actually roll.
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
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from enum import Enum

#: How long production may lag `main` before that counts as drift.
#:
#: MEASURED, not chosen by taste. Merge (`.commit.committer.date`) to the deploy
#: job's `completed_at`, over the last nine successful deploys on 2026-08-07:
#:
#:     795s 758s 734s 753s 792s 803s 734s 737s 744s   -> max 803s, median 753s
#:
#: The structural ceiling is `GATE_TIMEOUT_SECONDS = 1500` in deploy.yml plus a
#: ~60s deploy job, i.e. ~1560s even when the gate waits its entire budget.
#: 1800s clears that with headroom.
#:
#: An earlier draft used 2700s, sized against the 2071s of the 2026-08-07
#: INCIDENT. That was the wrong calibration: sizing the grace to tolerate the
#: failure means a repeat reads DEPLOY_IN_FLIGHT for its whole duration. Size it
#: against the legitimate path instead.
DEFAULT_GRACE_SECONDS = 1800.0

DEFAULT_STATUS_URL = "https://quorum-ai.fly.dev/status"

#: Bound the status probe. `/status` is free (rule 18) but it is a network call.
_STATUS_TIMEOUT_SECONDS = 10.0

#: `fly.toml` sets `min_machines_running = 0` and `auto_stop_machines = "stop"`,
#: so the machine can be COLD when this runs and a cold start can blow a 10s
#: budget. One sample would turn an ordinary cold start into a red job and a
#: GitHub issue — the red-you-learn-to-ignore failure. Retry before despairing.
_STATUS_ATTEMPTS = 3
_STATUS_RETRY_SLEEP_SECONDS = 5.0


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
    drift_age_seconds: float | None,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
) -> DriftResult:
    """Decide whether production has drifted from `main`'s tip.

    ``drift_age_seconds`` is how long production has been BEHIND — the age of
    the oldest commit on `main` that production does not have. Deliberately not
    the age of the tip commit: a fresh merge would reset a tip clock and launder
    an outage that had already run for hours. Measured merge gaps on `main` for
    2026-08-07 were 21, 148, 119, 20 and 256 minutes, so two of five were inside
    the grace period — a run of close merges could keep a tip-clocked check
    quiet indefinitely.
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
        return DriftResult(DriftDecision.IN_SYNC, f"production serves main's tip {tip}")

    if drift_age_seconds is None:
        return DriftResult(
            DriftDecision.UNKNOWN,
            f"production serves {served} but main's tip is {tip}, and how long it "
            "has been behind could not be determined, so this cannot be told "
            "apart from an in-flight deploy",
        )

    if drift_age_seconds < 0:
        # A commit dated in the future (clock skew) would otherwise compare as
        # "younger than the grace period" forever, silencing the check for as
        # long as the date stayed ahead. Silently-healthy is the one outcome
        # this script must never produce.
        return DriftResult(
            DriftDecision.UNKNOWN,
            f"production serves {served} but main's tip is {tip}, and the commit "
            f"clock reads {drift_age_seconds:.0f}s — a negative age means a "
            "skewed clock, which cannot be distinguished from a fresh deploy",
        )

    if drift_age_seconds < grace_seconds:
        return DriftResult(
            DriftDecision.DEPLOY_IN_FLIGHT,
            f"production serves {served}, main's tip is {tip}; production has been "
            f"behind for {drift_age_seconds:.0f}s — inside the "
            f"{grace_seconds:.0f}s grace period, so a deploy is presumed in flight",
        )

    return DriftResult(
        DriftDecision.DRIFTED,
        f"production serves {served} but main's tip is {tip}; production has been "
        f"behind for {drift_age_seconds:.0f}s, past the {grace_seconds:.0f}s grace "
        "period. Nothing is going to deploy it on its own.",
    )


# --------------------------------------------------------------------------
# I/O. Every fetch returns None on failure so the decision above stays pure and
# an unreadable input becomes UNKNOWN rather than an exception or a silent pass.
# NOTHING below may raise: a crash would skip the workflow's alert step and
# leave the job green, which is the failure this whole script is about.
# --------------------------------------------------------------------------


def fetch_build_sha(url: str, *, attempts: int = _STATUS_ATTEMPTS) -> str | None:
    """Read ``build_sha`` from ``/status``. Returns None if it cannot be read."""
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=_STATUS_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
            # INSIDE the try: a body that is valid JSON but not an object (a
            # list, a bare string, null) would otherwise raise AttributeError
            # here, kill the process before $GITHUB_OUTPUT is written, and leave
            # the watchdog green.
            if not isinstance(payload, dict):
                print(f"{url} returned JSON that is not an object: {type(payload).__name__}")
                return None
            value = payload.get("build_sha")
            if isinstance(value, str) and value.strip():
                return value
            print(f"{url} has no usable build_sha (got {value!r})")
            return None
        except Exception as exc:  # noqa: BLE001 — any failure means "unknown"
            print(f"attempt {attempt}/{attempts}: could not read {url}: {exc!r}")
            if attempt < attempts:
                time.sleep(_STATUS_RETRY_SLEEP_SECONDS)
    return None


def _gh(args: list[str]) -> str | None:
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60, check=False)
    except Exception as exc:  # noqa: BLE001
        print(f"gh {' '.join(args)} failed: {exc!r}")
        return None
    if out.returncode != 0:
        print(f"gh {' '.join(args)} exited {out.returncode}: {out.stderr.strip()[:200]}")
        return None
    return out.stdout.strip() or None


def _age_seconds(iso: str) -> float | None:
    """Seconds since an ISO-8601 instant, or None if it cannot be parsed."""
    try:
        landed = dt.datetime.fromisoformat(iso.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None
    if landed.tzinfo is None:
        # A naive datetime would raise on subtraction from an aware one, which
        # would crash the process before the verdict is written.
        landed = landed.replace(tzinfo=dt.UTC)
    try:
        return (dt.datetime.now(dt.UTC) - landed).total_seconds()
    except (TypeError, OverflowError):
        return None


def fetch_main_tip(repo: str) -> str | None:
    return _gh(["api", f"repos/{repo}/commits/main", "--jq", ".sha"])


def fetch_drift_age(repo: str, served_sha: str) -> float | None:
    """Seconds since the OLDEST commit on `main` that production does not have.

    This is the duration of the drift, not the age of the tip. ``compare`` lists
    the commits `main` is ahead by, oldest first, so the first entry is the
    change production has been missing longest.
    """
    raw = _gh(
        [
            "api",
            f"repos/{repo}/compare/{served_sha}...main",
            "--jq",
            ".commits[0].commit.committer.date // empty",
        ]
    )
    if not raw:
        return None
    return _age_seconds(raw)


def _write_outputs(result: DriftResult) -> None:
    """Publish the verdict to `$GITHUB_OUTPUT` so the workflow can branch on it."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"decision={result.decision.value}\n")
            handle.write(f"should_alert={'true' if result.should_alert else 'false'}\n")
    except OSError as exc:
        print(f"could not write $GITHUB_OUTPUT: {exc!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assert production serves main's tip.")
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
    tip = fetch_main_tip(args.repo) if args.repo else None
    served = fetch_build_sha(args.status_url)

    age: float | None = None
    if tip and served and _clean(tip) != _clean(served):
        age = fetch_drift_age(args.repo, served)

    result = evaluate_drift(
        main_tip=tip,
        build_sha=served,
        drift_age_seconds=age,
        grace_seconds=args.grace_seconds,
    )
    print(f"decision={result.decision.value}")
    print(result.detail)

    _write_outputs(result)
    return 1 if result.should_alert else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        # Last-resort net. An uncaught traceback exits non-zero WITHOUT writing
        # $GITHUB_OUTPUT, so the workflow's alert and fail steps are skipped and
        # (being continue-on-error) the job reports SUCCESS. Never crash quietly.
        print(f"deploy_drift_check crashed: {exc!r}")
        _write_outputs(DriftResult(DriftDecision.UNKNOWN, f"crashed: {exc!r}"))
        sys.exit(1)
