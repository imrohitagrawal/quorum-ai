#!/usr/bin/env python3
"""Alert when production is in a money-spending posture nobody declared.

WHAT THIS IS FOR (#357)
    ``OPENROUTER_LIVE_EXECUTION_ENABLED`` is the one switch that lets any ``/ui``
    visitor spend real money (``providers.py:670`` is
    ``openrouter_live_execution_enabled and openrouter_key``, and the key is a
    deployed secret). ADR-0060 turned it on for "one attended session". It ran
    for three days. Every automated check was green throughout, and each of them
    was RIGHT to be — none of them asks this question:

      * ``deploy-drift-watchdog.yml`` asks whether production serves ``main``'s
        tip. It reported the drift RESOLVED the moment the flag deployed.
      * ``availability-check.yml`` asks whether ``/ready`` is 200 and ``live``.
        ``live`` is the money-spending posture, and that check treats it as the
        GOOD state. Its definition of healthy and this one's are deliberately
        opposed.
      * ``error-rate-check.yml`` watches 5xx. A money-spending posture is neither
        unavailable nor erroring.

    Verified 2026-08-25 in this worktree: ``grep -rn 'live_execution' .github/``
    matched NOTHING. (Positive partner, so the grep is known to work and the
    directory is known not to be empty: ``build_sha`` matches 5 lines of
    ``deploy-drift-watchdog.yml``.)

WHY IT READS PRODUCTION AND NOT ``fly.toml``
    ``DEPLOY.md:61``, ``:175`` and ``:230`` instruct the operator to turn live
    execution on with ``fly secrets set OPENROUTER_LIVE_EXECUTION_ENABLED=true``
    — a path that touches no tracked file at all. Fly's configuration reference
    states that secrets take precedence over ``[env]`` entries of the same name,
    which ADR-0060 recorded as UNVERIFIED and which is UNVERIFIED here too
    (``fly secrets list -a quorum-ai`` needs an access token this box does not
    have). Either way the documented operator path is invisible to any check
    that reads the repository, so this one asks the running process instead.

WHY IT READS ``/ready`` AND NOT ``/status.live_execution``
    ``/status.live_execution`` is NOT the flag. ``main.py:984`` is
    ``report.state in ("live",)``, and ``readiness.py:429-446`` makes ``"live"``
    require the flag AND a key AND a probe verdict that is not ``unauthorized``.
    So flag-on-with-a-refused-key serves ``live_execution: false`` while
    ``providers.py:670`` — which has no probe term — still returns True.

    ``/ready.live_readiness.state`` carries the clean equivalence: the ``else``
    branch at ``readiness.py:445`` means ``offline_by_config`` if and only if the
    flag is off. Every other state in the vocabulary implies the flag is ON.
    That is the question this script asks.

THE SIGNAL IS "ON WITHOUT A DECLARATION", NOT "ON AT ALL"
    Live execution is legitimately switched on sometimes; ADR-0060 is the
    worked example. A check that alerts on every sanctioned window is a check
    somebody mutes, and a muted alert is worse than none. So the sanctioned
    window is DECLARED, in ``configs/live-execution-windows.json``, in the same
    pull request that flips the flag — and this script is quiet inside it while
    still printing what it observed and when the window expires.

    The declaration expires on its own. A forgotten entry becomes inert rather
    than leaving the watchdog permanently disarmed, so the only way to silence
    this check indefinitely is to commit a far-future ``expires_at``, which is
    visible in a diff and reviewable.

WHAT THIS CANNOT SEE — stated per AGENTS.md's "before adding a gate" rule
    * The gap between scheduled runs. Measured 2026-08-25 over the existing
      ``*/30`` lane's last 100 scheduled runs (2026-08-21T07:25Z ->
      2026-08-24T22:33Z, 87.1h): gaps min 21.7 / median 53.4 / max 129.4 minutes.
      A window that opens and closes inside one gap is never observed at all.
      Against a three-day exposure that is ample; against a ten-minute one it is
      nothing.
    * A flag set to ``"true"`` in ``main`` but not yet deployed — the exact
      shape of #351, which stranded ADR-0060's merge. Production has not begun
      spending, so this script is correctly silent. That case is covered by the
      SECOND layer, ``tests/unit/test_live_execution_posture_declaration.py``,
      which runs pre-merge in a blocking lane.
    * Whether a declaration is HONEST. It checks that a window was declared,
      not that the reason is true or the length is reasonable.
    * Spend. Deliberately: the whole three-day exposure cost $0.1768 against a
      $5.00/day ceiling, so any spend threshold would have stayed quiet through
      the entire incident. The hazard is standing exposure, not realised loss.
    * ``judge_enabled``, a second paid subsystem that ``/status`` reports as
      ``true`` today and that has no declared posture at all. Watching it needs a
      policy decision nobody has made; ADR-0070 records that as an open question.
    * Itself. GitHub disables scheduled workflows after a period of repository
      inactivity, and this check dies silently when that happens.

Exit codes: 0 when the posture is off, or on inside a declared window; 1 when it
is on without one, or when anything needed to decide could not be read. An
unreadable input is LOUD on purpose — reporting health from a value that was
never read is the failure this script exists to prevent.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

#: The two hosts production is served on, matching ``availability-check.yml:60``.
#: Both are read; a posture is live if EITHER reports one, which fails closed if
#: the two ever diverge.
DEFAULT_READY_URLS = (
    "https://quorum-ai.fly.dev/ready",
    "https://quorum.stackclimb.com/ready",
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WINDOWS_PATH = _REPO_ROOT / "configs" / "live-execution-windows.json"

#: ``readiness.py:54-58``'s complete vocabulary. A state outside it is a version
#: of the app this script has never heard of, which is not the same as healthy.
KNOWN_READINESS_STATES = frozenset(
    {"live", "offline_by_config", "offline_by_no_key", "offline_by_bad_key"}
)

#: The ONE state that means the flag is off. ``readiness.py:445`` is the ``else``
#: branch of a four-way, so this equivalence is exact rather than approximate.
FLAG_OFF_STATE = "offline_by_config"

#: Bound the probes. Lifted verbatim from ``deploy_drift_check.py:71,77,78``,
#: whose comment records why: ``fly.toml`` sets ``min_machines_running = 0``, so
#: the machine can be COLD and one sample would turn an ordinary cold start into
#: a red job and a GitHub issue — the red-you-learn-to-ignore failure.
_READY_TIMEOUT_SECONDS = 10.0
_READY_ATTEMPTS = 3
_READY_RETRY_SLEEP_SECONDS = 5.0


class PostureDecision(Enum):
    """Every terminal state. Pinned exhaustively by the test suite."""

    OFF_AS_DECLARED = "off_as_declared"
    LIVE_WITHIN_DECLARED_WINDOW = "live_within_declared_window"
    LIVE_UNDECLARED = "live_undeclared"
    LIVE_PAST_DECLARED_WINDOW = "live_past_declared_window"
    UNKNOWN = "unknown"


#: The decisions that must alert. ``UNKNOWN`` is here deliberately: "I could not
#: tell" is a failure of the check, and a check that cannot tell must not read as
#: healthy. This is the same choice ``deploy_drift_check.py:93`` makes.
_ALERTING = frozenset(
    {
        PostureDecision.LIVE_UNDECLARED,
        PostureDecision.LIVE_PAST_DECLARED_WINDOW,
        PostureDecision.UNKNOWN,
    }
)


@dataclass(frozen=True)
class DeclaredWindow:
    owner: str
    reason: str
    opened_at: dt.datetime
    expires_at: dt.datetime

    def covers(self, now: dt.datetime) -> bool:
        return self.opened_at <= now < self.expires_at


@dataclass(frozen=True)
class PostureResult:
    decision: PostureDecision
    detail: str

    @property
    def should_alert(self) -> bool:
        return self.decision in _ALERTING


def parse_windows(payload: object) -> list[DeclaredWindow] | None:
    """Parse the declaration file's contents, or None if it cannot be trusted.

    None means "this file did not tell me anything I may rely on", and every
    caller turns that into UNKNOWN rather than into "nothing is declared". The
    difference matters: "nothing is declared" plus a live posture is an alert
    anyway, but "nothing is declared" plus an OFF posture is silence — so a
    malformed file must not be able to route through the quiet branch.
    """
    if not isinstance(payload, dict):
        return None
    raw = payload.get("windows")
    if not isinstance(raw, list):
        return None

    windows: list[DeclaredWindow] = []
    for entry in raw:
        if not isinstance(entry, dict):
            return None
        owner = entry.get("owner")
        reason = entry.get("reason")
        opened = _parse_instant(entry.get("opened_at"))
        expires = _parse_instant(entry.get("expires_at"))
        if not isinstance(owner, str) or not owner.strip():
            return None
        if not isinstance(reason, str) or not reason.strip():
            return None
        if opened is None or expires is None:
            return None
        if expires <= opened:
            # A window that ends before it starts covers no instant at all, so
            # accepting it would silently produce a declaration that can never
            # sanction anything while looking to a reader like one that does.
            return None
        windows.append(
            DeclaredWindow(owner=owner, reason=reason, opened_at=opened, expires_at=expires)
        )
    return windows


def _parse_instant(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # A naive timestamp would compare against an aware ``now`` by raising,
        # and it is genuinely ambiguous: "17:00" in whose day? Refuse it rather
        # than guess a zone that could widen a window by hours.
        return None
    return parsed


def evaluate_posture(
    *,
    readiness_states: Mapping[str, str | None],
    windows: Sequence[DeclaredWindow] | None,
    now: dt.datetime,
) -> PostureResult:
    """Decide whether production's money posture is one somebody declared.

    ``readiness_states`` maps each probed URL to the ``live_readiness.state`` it
    reported, or None where it could not be read. It is deliberately a mapping
    rather than a single value so the detail can name HOW MANY hosts were read —
    a check that reports "nothing found" without saying what it looked at is the
    trivially-true shape this repository keeps paying for.
    """
    readable = {url: state for url, state in readiness_states.items() if state is not None}
    probed = len(readiness_states)

    if not readable:
        return PostureResult(
            PostureDecision.UNKNOWN,
            f"read live_readiness.state from 0 of {probed} host(s) — refusing to "
            "report a money posture from a value that was never read",
        )

    unknown_states = sorted(
        {state for state in readable.values() if state not in KNOWN_READINESS_STATES}
    )
    if unknown_states:
        return PostureResult(
            PostureDecision.UNKNOWN,
            f"read {len(readable)} of {probed} host(s); state(s) "
            f"{unknown_states} are outside the known vocabulary "
            f"{sorted(KNOWN_READINESS_STATES)} — a state this check has never "
            "heard of is not evidence that live execution is off",
        )

    if windows is None:
        return PostureResult(
            PostureDecision.UNKNOWN,
            f"read {len(readable)} of {probed} host(s) reporting "
            f"{sorted(set(readable.values()))}, but the declared-window file could "
            "not be read or did not parse — a declaration that cannot be parsed "
            "must never be mistaken for one that permits something",
        )

    live_hosts = sorted(url for url, state in readable.items() if state != FLAG_OFF_STATE)
    counted = (
        f"read {len(readable)} of {probed} host(s); {len(live_hosts)} report a "
        f"live-execution posture; {len(windows)} window(s) declared"
    )

    if not live_hosts:
        return PostureResult(
            PostureDecision.OFF_AS_DECLARED,
            f"{counted}. Every host reports {FLAG_OFF_STATE!r}: the money switch "
            "is off and no visitor can spend.",
        )

    active = [window for window in windows if window.covers(now)]
    if active:
        window = active[0]
        remaining = (window.expires_at - now).total_seconds() / 3600.0
        return PostureResult(
            PostureDecision.LIVE_WITHIN_DECLARED_WINDOW,
            f"{counted}. {live_hosts} report a live posture, inside a window "
            f"declared by {window.owner!r} for {window.reason!r}, opened "
            f"{window.opened_at.isoformat()} and expiring "
            f"{window.expires_at.isoformat()} — {remaining:.1f}h remaining. "
            "Sanctioned; no alert.",
        )

    expired = [window for window in windows if window.expires_at <= now]
    if expired:
        latest = max(expired, key=lambda window: window.expires_at)
        overrun = (now - latest.expires_at).total_seconds() / 3600.0
        return PostureResult(
            PostureDecision.LIVE_PAST_DECLARED_WINDOW,
            f"{counted}. {live_hosts} report a live posture, and the most recent "
            f"declared window — {latest.owner!r}, {latest.reason!r} — expired "
            f"{latest.expires_at.isoformat()}, {overrun:.1f}h ago. Every visitor "
            "to /ui is spending real money past the instant somebody wrote down "
            "as the end of it.",
        )

    return PostureResult(
        PostureDecision.LIVE_UNDECLARED,
        f"{counted}. {live_hosts} report a live posture and NO declared window "
        f"covers {now.isoformat()}. Every visitor to /ui can spend real money "
        "and nobody wrote down that this was intended.",
    )


#: Values of ``OPENROUTER_LIVE_EXECUTION_ENABLED`` that mean "off". ANY other
#: value — including a typo — counts as ON, because a gate that reads an
#: unrecognised value as "off" is the silently-green shape this whole package
#: exists to abolish.
_FLAG_OFF_VALUES = frozenset({"", "false", "0", "no", "off"})


def refuse_undeclared_flag(
    *,
    flag_value: str | None,
    windows: Sequence[DeclaredWindow] | None,
    now: dt.datetime,
) -> str | None:
    """Why a COMMITTED flag value must not merge, or None if it may.

    This is the pre-merge half of #357, used by
    ``tests/unit/test_live_execution_posture_declaration.py`` in the blocking
    ``pytest (Python 3.12)`` lane. It answers a different question from
    ``evaluate_posture``: that one asks what production is DOING, this one asks
    what ``main`` is about to ASK production to do. It is the only half that can
    see a flag flipped in a merge that has not deployed yet — the exact shape of
    #351, which stranded ADR-0060's merge and stretched its window to three days.

    It is also the half a Fly secret bypasses completely, which is why it is a
    complement to the runtime watchdog and never a substitute for it.
    """
    if windows is None:
        return (
            "configs/live-execution-windows.json could not be read or did not "
            "parse. A declaration that cannot be parsed must never be mistaken "
            "for one that permits something."
        )

    normalised = (flag_value or "").strip().lower()
    if normalised in _FLAG_OFF_VALUES:
        return None

    if any(window.covers(now) for window in windows):
        return None

    return (
        f"fly.toml sets OPENROUTER_LIVE_EXECUTION_ENABLED = {flag_value!r}, which "
        "lets every /ui visitor spend real money, and no window in "
        f"configs/live-execution-windows.json covers {now.isoformat()} "
        f"({len(windows)} window(s) declared). Declare the window — owner, "
        "reason, opened_at, expires_at — in THIS pull request, or set the flag "
        'back to "false". ADR-0060 turned this on for one session and it ran '
        "three days because nothing executed its revert condition."
    )


# --------------------------------------------------------------------------
# I/O. Every read returns None on failure so the decision above stays pure and
# an unreadable input becomes UNKNOWN rather than an exception or a silent pass.
# NOTHING below may raise: a crash would skip the workflow's alert step and
# leave the job green, which is the failure this whole script is about.
# --------------------------------------------------------------------------


def fetch_readiness_state(url: str, *, attempts: int = _READY_ATTEMPTS) -> str | None:
    """Read ``live_readiness.state`` from ``/ready``. None if it cannot be read."""
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=_READY_TIMEOUT_SECONDS) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
            # INSIDE the try, exactly as deploy_drift_check.py:200 is: a body
            # that is valid JSON but not an object would otherwise raise
            # AttributeError here, kill the process before $GITHUB_OUTPUT is
            # written, and leave the watchdog green.
            if not isinstance(payload, dict):
                print(f"{url} returned JSON that is not an object: {type(payload).__name__}")
                return None
            readiness = payload.get("live_readiness")
            if not isinstance(readiness, dict):
                print(f"{url} has no live_readiness object (got {readiness!r})")
                return None
            state = readiness.get("state")
            if isinstance(state, str) and state.strip():
                return state.strip()
            # NOT a default of "offline_by_config". A missing key means "I could
            # not read it", and letting that fall through as the off-state would
            # make this check permanently, silently green.
            print(f"{url} has no usable live_readiness.state (got {state!r})")
            return None
        except Exception as exc:  # noqa: BLE001 — any failure means "unknown"
            print(f"attempt {attempt}/{attempts}: could not read {url}: {exc!r}")
            if attempt < attempts:
                time.sleep(_READY_RETRY_SLEEP_SECONDS)
    return None


def load_windows(path: Path) -> list[DeclaredWindow] | None:
    """Read and parse the declaration file. None if it cannot be trusted."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"could not read {path}: {exc!r}")
        return None
    return parse_windows(payload)


def _write_outputs(result: PostureResult) -> None:
    """Publish the verdict to ``$GITHUB_OUTPUT`` so the workflow can branch on it."""
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
    parser = argparse.ArgumentParser(
        description="Alert when production's money-spending posture is undeclared."
    )
    parser.add_argument("--ready-url", action="append", dest="ready_urls", default=None)
    parser.add_argument("--windows-file", default=str(DEFAULT_WINDOWS_PATH))
    args = parser.parse_args(argv)

    urls = tuple(args.ready_urls or DEFAULT_READY_URLS)
    states = {url: fetch_readiness_state(url) for url in urls}
    for url, state in states.items():
        print(f"probed {url} -> live_readiness.state={state!r}")

    windows_path = Path(args.windows_file)
    print(f"declared windows read from {windows_path}")
    windows = load_windows(windows_path)

    result = evaluate_posture(
        readiness_states=states,
        windows=windows,
        now=dt.datetime.now(dt.UTC),
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
        # Last-resort net, copied from deploy_drift_check.py:313-324 for the
        # reason recorded there: an uncaught traceback exits non-zero WITHOUT
        # writing $GITHUB_OUTPUT, so the workflow's alert and fail steps are
        # skipped and — the step being continue-on-error — the job reports
        # SUCCESS. Never crash quietly.
        print(f"live_posture_check crashed: {exc!r}")
        _write_outputs(PostureResult(PostureDecision.UNKNOWN, f"crashed: {exc!r}"))
        sys.exit(1)
