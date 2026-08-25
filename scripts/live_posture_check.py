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

    Measured 2026-08-25, BEFORE this file existed:
    ``git grep -n 'live_execution' b5d6224 -- .github/`` matched NOTHING (exit 1).
    Scoped to that commit deliberately — run against the working tree it now
    matches this very workflow, and a claim that refutes itself the moment it
    ships is worse than no claim. Positive partner, so the grep is known to work
    and the directory is known not to be empty: ``build_sha`` matches 5 lines of
    ``deploy-drift-watchdog.yml``.

WHAT ADR-0071 CHANGED, AND WHY — this file's second revision
    ADR-0070 built this mechanism on an assumption that is wrong: that a live
    posture is EXCEPTIONAL. It is the intended steady state — the operator's
    decision of 2026-08-25, recorded in ADR-0071. A mechanism whose only quiet
    state is a time-boxed exception is the wrong shape for a steady state, and
    the pressure to silence it would have grown every week.

    Three things follow, and they are the whole of this revision:

    1. THE JUDGE IS PART OF THE DECLARATION — see THE SECOND PAID SUBSYSTEM.
    2. RE-AFFIRMATION REPLACES A MAXIMUM WINDOW LENGTH — see RE-AFFIRMATION.
    3. A WINDOW HAS A MODE: ``time_boxed`` as before, or ``standing`` for the
       steady state — an abuse surface, and built as one.

THE SECOND PAID SUBSYSTEM: the judge
    ``/status.judge_enabled`` is ``true`` in production today (``curl``,
    2026-08-25, build ``57be5a8``). It is a SECOND paid subsystem, and it is not
    an independent exposure — it is a MULTIPLIER on this one:

      * The judge CANNOT spend while live execution is off. The run-path gate
        (``query_run_orchestration.py:2256-2278``) needs a COMPLETED answer whose
        ``provider_path`` is outside
        ``NOT_INVOKED_PATHS = {LOCAL_SIMULATION, FALLBACK_SEARCH}``
        (``providers.py:122``), and the only site producing one is inside
        ``produce_initial_answer``'s ``_live_execution_enabled`` branch
        (``providers.py:512,571``). Live off, every answer is LOCAL_SIMULATION.
      * So the dangerous cell is live ON with the judge ON — and there the
        judge's GET-path spend reaches NO ledger at all (ADR-0013), so
        ``/status.global_daily_spend_usd`` UNDER-REPORTS by exactly that
        subsystem's cost, precisely while that cell is active.

    That conjunction is why a window now carries ``judge``. This is a
    DECLARATION requirement, not a policy: it does not say the judge must be
    off, it says the window must SAY whether the judge is in it. ADR-0070's open
    decision 2 asked for a judge policy and refused to guess one; ADR-0071
    CORRECTS that decision rather than answering it, because its premise — that
    the judge was a second UNWATCHED money exposure — is refuted by the gate
    above.

    Judge state is load-bearing ONLY when the live posture is on. With live
    execution off the judge is inert, so its state is REPORTED and never
    alerted. That is deliberate, and it is what keeps this revision honest: it
    adds ZERO new alerting paths to today's production posture, so every new
    alert below is driven by a fixture rather than by a hoped-for future.

RE-AFFIRMATION: what separates a sanctioned week from a forgotten one
    A window is sanctioned only while somebody is still attending it. The clock
    starts at ``opened_at`` and is reset by a human RE-AFFIRMATION. Past
    ``REAFFIRMATION_CADENCE_HOURS`` with no reset, the window stops sanctioning
    anything and this check alerts — at ANY window length. That is what lets
    issue #105's log collection proceed — its own remediation step 2 is "Read a
    week of production logs" — while still catching #357's three unattended days
    on their first day. No MAXIMUM LENGTH can do both: 3 days is the failure and
    7 days is a legitimate need, so no number separates them.
    "Is anybody still watching?" separates them at every length.

    THE RE-AFFIRMATION IS A COMMENT ON A GITHUB ISSUE, NOT A FIELD IN THIS
    REPOSITORY, and that is forced by measurement rather than taste. A committed
    ``reaffirmed_at:`` would be satisfiable by automation HERE:

      * 366 of 366 commits carry NO signature (``git log --all --format='%G?'``
        -> ``366 N``) and ``required_signatures`` is disabled on ``main``.
      * 234 of 366 commits already have committer ``noreply@github.com`` — the
        ordinary squash-merge path — so "the committer must not be a bot"
        rejects this repository's normal workflow.
      * ``seed-visual-baselines.yml`` already holds ``contents: write``, already
        sets ``git config user.name "github-actions[bot]"`` by hand, and has
        already pushed a commit. The machinery to forge a file-based
        re-affirmation is installed and has fired.
      * ``required_approving_review_count`` on ``main`` is 0 and
        ``.github/CODEOWNERS`` is an unedited template, so "it appears in a diff
        and is reviewed" — ADR-0070's stated safeguard — has no mechanical
        backing at all.

    A comment does not have those problems, because GitHub sets the two fields
    that matter and the commenter cannot:

      * ``user.type`` is ``"Bot"`` for anything posted with a workflow token.
        Measured on this repository's own alert issue: all 11 machine comments
        on #351 are ``{"login": "github-actions[bot]", "type": "Bot"}``. THIS
        WATCHDOG CANNOT RE-AFFIRM ITSELF — everything it posts is typed ``Bot``,
        by GitHub, and ``parse_reaffirmations`` refuses ``Bot`` comments.
      * ``created_at`` is server-set, so a re-affirmation cannot be
        FORWARD-DATED to never lapse. With a committed field both the actor and
        the instant are self-declared; with a comment neither is.

    What this does NOT prove, stated plainly: that the human THOUGHT about it. A
    person can paste the token every morning without reading a thing. The
    mechanism establishes that a human acted inside the cadence, never that
    judgement was exercised. That residual is accepted, not solved.

``standing`` IS AN ABUSE SURFACE AND IS BUILT AS ONE
    A mode with no expiry is the same shape as the proven-equivalent exclusion
    ledger ADR-0069 REJECTED, whose stated grounds name these hazards exactly:
    entries outliving their code, "growth with nothing reporting size or age",
    and a re-blessing that "turns into a rubber stamp". So:

      * ``standing`` REMOVES THE DEADLINE. IT DOES NOT REMOVE THE ATTENTION.
        A standing window still lapses without re-affirmation, so reaching for
        ``standing`` to quiet a noisy alert buys 24 hours, never silence. That
        single property is what stops the self-defeating gradient in which the
        cheapest way to stop an alarm at 03:00 is to make it permanent.
      * ``standing`` MUST CITE AN ADR THAT AUTHORISES IT, and the citation is
        RESOLVED rather than trusted: the ADR must exist, its ``## Status`` must
        begin ``Accepted``, it must carry ``ADR_AUTHORISATION_MARKER`` on a line
        of its own, and it may NOT be one of this mechanism's own records
        (``MECHANISM_OWN_ADRS``) — a mechanism cannot authorise its own use.
        Measured 2026-08-25 and SCOPED TO ``origin/main`` — the tree BEFORE this
        revision, because run against the working tree the same grep now counts
        ADR-0071 itself, and a claim that refutes itself the moment it ships is
        worse than no claim:
        ``git grep -l 'OPENROUTER_LIVE_EXECUTION_ENABLED' origin/main -- docs/adr/``
        returns **6** of that commit's **68** records, and 2 of the 6
        (ADR-0022's credential removal, ADR-0054's 403 capture) authorise nothing
        at all. Matching ADR PROSE is therefore not a discriminator, which is why
        an explicit marker is required instead.
      * A ``standing`` DECLARATION DOES NOT MAKE THIS CHECK GO QUIET. It gets its
        own decision, ``LIVE_WITHIN_STANDING_DECLARATION``, so every cycle names
        it and prints the ADR, the owner, how long it has stood and how long
        since it was last re-affirmed. A standing posture that produced silence
        would be indistinguishable from a dead watchdog.
      * A ``standing`` window closes the far-future-expiry hole rather than
        widening it. ADR-0070 named ``expires_at: 9999-...`` as the one way to
        silence this indefinitely and defended it only by diff review, which is
        unenforced here. Re-affirmation closes it for every window length at
        once: an unattended window lapses in a day whether its expiry is
        tomorrow or the year 9999.

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

    ``judge_enabled`` is read from ``/status`` because it appears NOWHERE on
    ``/ready``. Measured 2026-08-25: ``curl -s https://quorum-ai.fly.dev/ready``
    returns exactly THREE top-level keys — ``status``, ``environment`` and
    ``live_readiness`` — and none is judge-bearing. It does NOT carry ``live_execution``'s defect:
    ``main.py:1032`` is a direct ``judge_configured()`` call
    (``evaluation.py:1814-1827`` — a key AND a model id, no probe term), and it
    is the SAME predicate the run-path gate uses, so the reported state cannot
    drift from the spending behaviour.

WHAT THIS CANNOT SEE — stated per AGENTS.md's "before adding a gate" rule
    * The gap between scheduled runs. Measured 2026-08-25 over the existing
      ``*/30`` lane's last 100 scheduled runs (2026-08-21T07:25Z ->
      2026-08-24T22:33Z, 87.1h): gaps min 21.7 / median 53.4 / max 129.4 minutes.
      A window that opens and closes inside one gap is never observed at all.
      Against the 24-hour re-affirmation cadence the worst measured gap is 9% of
      the interval, so lapse detection is comfortable — but the INSTANT an alert
      lands is unpredictable within about 2.2h.
    * A flag set to ``"true"`` in ``main`` but not yet deployed — the exact shape
      of #351, which stranded ADR-0060's merge. Production has not begun
      spending, so this script is correctly silent. That case is covered by the
      SECOND layer, ``tests/unit/test_live_execution_posture_declaration.py``,
      which runs pre-merge in a blocking lane.
    * THE JUDGE, PRE-MERGE. There is no judge configuration in ``fly.toml`` at
      all (measured: ``grep -i judge fly.toml`` exits 1). The judge is governed
      purely by Fly secrets, so NO pre-merge gate can ever see it, and this
      runtime check is the only place the judge dimension can bite. That
      asymmetry with the live flag is recorded rather than discovered later.
    * RE-AFFIRMATION FRESHNESS, PRE-MERGE, for the same reason: attention is a
      runtime fact read from GitHub, and the pre-merge gate is offline.
    * Whether a declaration is HONEST, or whether a re-affirmation was THOUGHT
      about. It checks that a window was declared and that a human acted inside
      the cadence, not that the reason is true or the judgement sound.
    * Spend. Deliberately: the whole three-day exposure cost $0.1768 against a
      $5.00/day ceiling, so any spend threshold would have stayed quiet through
      the entire incident. The hazard is standing exposure, not realised loss.
      See THE SUCCESSOR.
    * Itself. GitHub disables scheduled workflows after a period of repository
      inactivity, and this check dies silently when that happens. INHERITED from
      ``availability-check.yml:22-23`` and still UNVERIFIED.

THE SUCCESSOR — so this is REPLACED rather than deleted for being noisy
    At GA the question this asks stops being the right one. "Is the posture
    declared?" is a PRE-GA question: it is worth asking while live execution is
    exceptional and each window is an event somebody should be able to name.
    Once live execution is the permanent steady state, every cycle answers "yes,
    standing, as declared", the signal's information content falls towards zero,
    and the daily re-affirmation becomes friction.

    Its successor asks "is SPEND ANOMALOUS?" — a different mechanism needing a
    baseline of normal production spend that DOES NOT EXIST TODAY. None is built
    here and no threshold is chosen here, deliberately: ADR-0070 rejected a spend
    threshold on the measurement that the entire #357 exposure was $0.1768, and
    picking a number now would repeat exactly the move ADR-0060's Decision (1)
    refused. When the daily re-affirmation starts to feel like theatre, that is
    the signal to BUILD THE SUCCESSOR, not to delete this.

Exit codes: 0 when the posture is off, or on inside a declared window somebody
is still attending; 1 when it is on without one, when the attention lapsed, when
the judge is running outside the declaration, or when anything needed to decide
could not be read. An unreadable input is LOUD on purpose — reporting health
from a value that was never read is the failure this script exists to prevent.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

#: The two hosts production is served on, matching ``availability-check.yml:61``.
#: Both are read; a posture is live if EITHER reports one, which fails closed if
#: two READABLE hosts diverge. A host that could not be read is a different
#: matter: the verdict is still taken from the hosts that answered (they are the
#: same app, so one answer settles the posture), but ``PostureResult.complete``
#: goes False and the workflow refuses to CLOSE a standing alert on that reading.
#: Retiring an alert on a partial view is the one thing a half-blind cycle must
#: not be allowed to do.
DEFAULT_READY_URLS = (
    "https://quorum-ai.fly.dev/ready",
    "https://quorum.stackclimb.com/ready",
)

#: ``judge_enabled`` lives on ``/status`` and nowhere else — measured, ``/ready``
#: returns three top-level keys and none is judge-bearing. Same two hosts;
#: measured 2026-08-25 they return byte-identical JSON apart from
#: ``uptime_seconds``, so this is one app read twice, exactly as ``/ready`` is.
DEFAULT_STATUS_URLS = (
    "https://quorum-ai.fly.dev/status",
    "https://quorum.stackclimb.com/status",
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WINDOWS_PATH = _REPO_ROOT / "configs" / "live-execution-windows.json"
DEFAULT_ADR_DIR = _REPO_ROOT / "docs" / "adr"

#: ``readiness.py:54-58``'s complete vocabulary. A state outside it is a version
#: of the app this script has never heard of, which is not the same as healthy.
KNOWN_READINESS_STATES = frozenset(
    {"live", "offline_by_config", "offline_by_no_key", "offline_by_bad_key"}
)

#: The ONE state that means the flag is off. ``readiness.py:445`` is the ``else``
#: branch of a four-way, so this equivalence is exact rather than approximate.
FLAG_OFF_STATE = "offline_by_config"

#: How long a declared window may run before a human has to say, positively,
#: that it is still wanted. A REMINDER cadence, not a money guardrail: nothing
#: here prices or bounds spend, and a wrong value self-corrects — too short and
#: somebody says so on the first weekend, too long and the next incident does.
#: Approved by the operator, 2026-08-25, alongside ADR-0071.
#:
#: Deliberately NOT a maximum window length. ADR-0070 left that as an open
#: decision and it cannot be answered honestly: the #357 failure ran ~3 days and
#: issue #105 legitimately needs ~7, so no single number separates them.
REAFFIRMATION_CADENCE_HOURS = 24.0

#: The two modes a declared window may have. ``time_boxed`` carries
#: ``expires_at`` and is the ADR-0060 shape: an event with an end somebody wrote
#: down. ``standing`` has no expiry and is the steady-state shape — and because
#: a mode with no expiry is a way to silence an alarm forever, it costs an ADR
#: citation that RESOLVES, and it does not exempt the window from re-affirmation.
MODE_TIME_BOXED = "time_boxed"
MODE_STANDING = "standing"
WINDOW_MODES = frozenset({MODE_TIME_BOXED, MODE_STANDING})

#: The exact line a ``standing`` window's cited ADR must carry to authorise it.
#: An explicit marker rather than a grep of the ADR's prose, because prose is
#: measurably not a discriminator: on ``origin/main`` 6 of 68 ADRs name the flag
#: and 2 of those authorise nothing at all — the module docstring carries the
#: scoped command. A deliberate marker cannot be satisfied by accident.
ADR_AUTHORISATION_MARKER = "**Authorises:** OPENROUTER_LIVE_EXECUTION_ENABLED"

#: A mechanism may not authorise its own use. ADR-0070 and ADR-0071 BUILD the
#: standing mode; the ADR that says "we are going live permanently, and here is
#: why" is a different, future document, and requiring it is the point. Without
#: this the first ``standing`` window would cite the ADR that invented
#: ``standing`` and the citation would carry no information whatsoever.
MECHANISM_OWN_ADRS = frozenset({"ADR-0070", "ADR-0071"})

#: The text a human writes to re-affirm. It names the window by its ``opened_at``
#: instant, so one comment attends exactly one window and a person running two
#: windows must say so twice.
REAFFIRM_TOKEN = "REAFFIRM live-execution"

#: Where re-affirmations are read from. ``{repo}`` and ``{issue}`` are filled in.
#: Overridable so every test drives a ``file:`` fixture and no test touches
#: GitHub — the discipline the ``/ready`` tests already follow.
DEFAULT_REAFFIRMATION_URL_TEMPLATE = (
    "https://api.github.com/repos/{repo}/issues/{issue}/comments?per_page=100"
)

#: Bound the probes. Lifted verbatim from ``deploy_drift_check.py:71,77,78``,
#: whose comment records why: ``fly.toml`` sets ``min_machines_running = 0``, so
#: the machine can be COLD and one sample would turn an ordinary cold start into
#: a red job and a GitHub issue — the red-you-learn-to-ignore failure.
_READY_TIMEOUT_SECONDS = 10.0
_READY_ATTEMPTS = 3
_READY_RETRY_SLEEP_SECONDS = 5.0

_ADR_NAME = re.compile(r"^ADR-\d{4}$")


class PostureDecision(Enum):
    """Every terminal state. Pinned exhaustively by the test suite."""

    OFF_AS_DECLARED = "off_as_declared"
    LIVE_WITHIN_DECLARED_WINDOW = "live_within_declared_window"
    LIVE_WITHIN_STANDING_DECLARATION = "live_within_standing_declaration"
    LIVE_UNDECLARED = "live_undeclared"
    LIVE_PAST_DECLARED_WINDOW = "live_past_declared_window"
    LIVE_REAFFIRMATION_LAPSED = "live_reaffirmation_lapsed"
    LIVE_JUDGE_UNDECLARED = "live_judge_undeclared"
    UNKNOWN = "unknown"


#: The decisions that must alert. ``UNKNOWN`` is here deliberately: "I could not
#: tell" is a failure of the check, and a check that cannot tell must not read as
#: healthy. This is the same choice ``deploy_drift_check.py:93`` makes.
_ALERTING = frozenset(
    {
        PostureDecision.LIVE_UNDECLARED,
        PostureDecision.LIVE_PAST_DECLARED_WINDOW,
        PostureDecision.LIVE_REAFFIRMATION_LAPSED,
        PostureDecision.LIVE_JUDGE_UNDECLARED,
        PostureDecision.UNKNOWN,
    }
)


@dataclass(frozen=True)
class Reaffirmation:
    """One human saying, positively, that a window is still wanted.

    ``at`` is GitHub's ``created_at``, not a value anybody typed — which is what
    makes forward-dating impossible rather than merely discouraged. ``by`` is the
    login, carried so the job log can name who last attended the window.
    """

    at: dt.datetime
    by: str
    window_opened_at: dt.datetime


@dataclass(frozen=True)
class DeclaredWindow:
    owner: str
    reason: str
    opened_at: dt.datetime
    #: None if and only if the mode is ``standing``.
    expires_at: dt.datetime | None
    #: These carry defaults so a construction site in a test can say only what it
    #: is testing. They are NOT defaults of the FILE FORMAT: ``parse_windows``
    #: requires ``mode`` and ``judge`` explicitly and refuses a file missing
    #: either, because a defaulted money field is a decision nobody made.
    mode: str = MODE_TIME_BOXED
    judge: bool = False
    adr: str | None = None
    reaffirm_issue: int | None = None

    @property
    def is_standing(self) -> bool:
        return self.mode == MODE_STANDING

    def covers(self, now: dt.datetime) -> bool:
        """Whether this window's DECLARED span contains ``now``.

        Half-open, as before: it covers its opening instant and not its expiry.
        A standing window has no expiry and so covers everything from its opening
        instant onward — which is exactly why covering is not, on its own, enough
        to sanction anything. See ``is_attended``.
        """
        if self.opened_at > now:
            return False
        return self.expires_at is None or now < self.expires_at

    def attended_since(self, reaffirmations: Sequence[Reaffirmation]) -> dt.datetime:
        """The instant this window was last positively attended.

        Opening a window IS the first act of attention, so the clock starts at
        ``opened_at`` and a window shorter than the cadence needs no separate
        re-affirmation at all. Deliberate: the cheap, common, short window costs
        nothing extra, and only a window that outlives a day earns the rest of
        its life.
        """
        latest = self.opened_at
        for entry in reaffirmations:
            if entry.window_opened_at == self.opened_at and entry.at > latest:
                latest = entry.at
        return latest

    def hours_unattended(self, now: dt.datetime, reaffirmations: Sequence[Reaffirmation]) -> float:
        return (now - self.attended_since(reaffirmations)).total_seconds() / 3600.0

    def is_attended(self, now: dt.datetime, reaffirmations: Sequence[Reaffirmation]) -> bool:
        return self.hours_unattended(now, reaffirmations) < REAFFIRMATION_CADENCE_HOURS

    def describe(self) -> str:
        if self.is_standing:
            return (
                f"a STANDING declaration by {self.owner!r} for {self.reason!r}, citing {self.adr}"
            )
        expiry = self.expires_at.isoformat() if self.expires_at else "?"
        return (
            f"a time-boxed window declared by {self.owner!r} for {self.reason!r}, expiring {expiry}"
        )


@dataclass(frozen=True)
class PostureResult:
    decision: PostureDecision
    detail: str
    #: True when every host probed actually answered. A verdict taken over a
    #: partial view may be acted on, but it may not RETIRE a standing alert —
    #: see the workflow's resolve step, which requires this.
    complete: bool = True

    @property
    def should_alert(self) -> bool:
        return self.decision in _ALERTING


# --------------------------------------------------------------------------
# Parsing. Everything here is PURE, so every branch is reachable from a fixture
# and none of it needs a network, or a clock it was not handed.
# --------------------------------------------------------------------------


def authorising_adrs(adr_dir: Path) -> frozenset[str]:
    """Which ADRs on disk positively authorise a standing live-execution posture.

    An ADR qualifies only if it is ACCEPTED and carries
    ``ADR_AUTHORISATION_MARKER`` on a line of its own. Returning a SET rather
    than answering a yes/no keeps the decision below pure: the caller resolves
    the citations once, and ``parse_windows`` compares against what it was
    handed.
    """
    found: set[str] = set()
    try:
        candidates = sorted(adr_dir.glob("[0-9]*.md"))
    except OSError as exc:  # noqa: BLE001 — an unreadable directory authorises nothing
        print(f"could not list {adr_dir}: {exc!r}")
        return frozenset()
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:  # noqa: BLE001
            print(f"could not read {path}: {exc!r}")
            continue
        if not any(line.strip() == ADR_AUTHORISATION_MARKER for line in text.splitlines()):
            continue
        heading = re.search(r"^# (ADR-\d{4}):", text, re.M)
        status = re.search(r"^## Status\s*\n+([^\n]+)", text, re.M)
        if heading is None or status is None:
            continue
        if not status.group(1).strip().startswith("Accepted"):
            continue
        found.add(heading.group(1))
    return frozenset(found)


def parse_windows(
    payload: object, *, authorised_adrs: frozenset[str] | None = None
) -> list[DeclaredWindow] | None:
    """Parse the declaration file's contents, or None if it cannot be trusted.

    None means "this file did not tell me anything I may rely on", and every
    caller turns that into UNKNOWN rather than into "nothing is declared". The
    difference matters: "nothing is declared" plus a live posture is an alert
    anyway, but "nothing is declared" plus an OFF posture is silence — so a
    malformed file must not be able to route through the quiet branch.

    ``authorised_adrs`` defaults to the EMPTY set, not to "do not check". A
    caller that forgets to resolve the citations therefore refuses every standing
    window rather than accepting every one of them; the default is the
    fail-closed direction.
    """
    authorised = frozenset() if authorised_adrs is None else authorised_adrs
    if not isinstance(payload, dict):
        return None
    raw = payload.get("windows")
    if not isinstance(raw, list):
        return None

    windows: list[DeclaredWindow] = []
    for entry in raw:
        window = _parse_window(entry, authorised)
        if window is None:
            return None
        windows.append(window)
    return windows


def _parse_window(entry: object, authorised: frozenset[str]) -> DeclaredWindow | None:
    if not isinstance(entry, dict):
        return None
    owner = entry.get("owner")
    reason = entry.get("reason")
    if not isinstance(owner, str) or not owner.strip():
        return None
    if not isinstance(reason, str) or not reason.strip():
        return None

    opened = _parse_instant(entry.get("opened_at"))
    if opened is None:
        return None

    # A mode this script does not recognise is REFUSED, never defaulted. Before
    # ADR-0071 an unknown key was silently ignored, so `{"mode": "standng"}`
    # parsed and meant nothing — the silently-green shape this whole package
    # exists to abolish, and the same reason `_FLAG_OFF_VALUES` fails closed on
    # `"trve"`.
    mode = entry.get("mode")
    if mode not in WINDOW_MODES:
        return None

    # `judge` must be a real boolean. `isinstance(True, int)` is True in Python,
    # so the check is on `bool`, and the STRING "true" is refused: a money field
    # that quietly accepts a near-miss is a money field nobody decided.
    judge = entry.get("judge")
    if not isinstance(judge, bool):
        return None

    reaffirm_issue = entry.get("reaffirm_issue")
    if reaffirm_issue is not None:
        if isinstance(reaffirm_issue, bool) or not isinstance(reaffirm_issue, int):
            return None
        if reaffirm_issue <= 0:
            return None

    adr = entry.get("adr")
    expires = entry.get("expires_at")

    if mode == MODE_STANDING:
        # No expiry: that is what `standing` MEANS, and an expiry alongside it
        # would leave a reader unable to say which one governs.
        if expires is not None:
            return None
        if not isinstance(adr, str) or not _ADR_NAME.match(adr.strip()):
            return None
        adr = adr.strip()
        if adr in MECHANISM_OWN_ADRS:
            return None
        if adr not in authorised:
            return None
        return DeclaredWindow(
            owner=owner,
            reason=reason,
            opened_at=opened,
            expires_at=None,
            mode=MODE_STANDING,
            judge=judge,
            adr=adr,
            reaffirm_issue=reaffirm_issue,
        )

    if adr is not None:
        # An ADR citation on a time-boxed window would read as an authorisation
        # it does not carry. Refuse it rather than ignore it.
        return None
    expires_at = _parse_instant(expires)
    if expires_at is None:
        return None
    if expires_at <= opened:
        # A window that ends before it starts covers no instant at all, so
        # accepting it would silently produce a declaration that can never
        # sanction anything while looking to a reader like one that does.
        return None
    return DeclaredWindow(
        owner=owner,
        reason=reason,
        opened_at=opened,
        expires_at=expires_at,
        mode=MODE_TIME_BOXED,
        judge=judge,
        adr=None,
        reaffirm_issue=reaffirm_issue,
    )


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
    # Normalise to UTC. Any offset is ACCEPTED — the comparison is correct either
    # way — but everything this script prints, including the alert body, is then
    # in one zone. Review's point: the whole "a far-future expiry is visible in a
    # diff" argument rests on a reader computing the instant correctly, and
    # `2026-08-26T00:00:00-12:00` ends twelve hours later than it looks.
    return parsed.astimezone(dt.UTC)


def parse_reaffirmations(payload: object, *, now: dt.datetime) -> list[Reaffirmation] | None:
    """Read human re-affirmations out of a GitHub issue-comments payload.

    Two filters, and BOTH rest on fields GitHub sets rather than on anything the
    commenter supplies:

      * ``user.type == "Bot"`` is dropped. This is what makes the mechanism
        satisfiable only by a person: a comment posted with a workflow token —
        including this watchdog's own — is typed ``Bot`` by GitHub. Measured on
        issue #351: 11 of 11 machine comments carry ``"type": "Bot"``.
      * ``created_at`` in the FUTURE is dropped. GitHub cannot produce one, so
        its only source is a hand-built payload, and honouring it would restore
        exactly the forward-dating cheat a committed timestamp would have had.

    A comment counts only if it carries ``REAFFIRM_TOKEN`` followed by the
    ``opened_at`` instant of the window it re-affirms, so one comment attends
    exactly one window.

    Returns None if the payload is not a comment list at all — which the caller
    turns into UNKNOWN, never into "nobody has re-affirmed".
    """
    if not isinstance(payload, list):
        return None
    found: list[Reaffirmation] = []
    for comment in payload:
        if not isinstance(comment, dict):
            return None
        user = comment.get("user")
        if not isinstance(user, dict):
            return None
        login = user.get("login")
        kind = user.get("type")
        body = comment.get("body")
        created = _parse_instant(comment.get("created_at"))
        if not isinstance(login, str) or not isinstance(kind, str):
            return None
        if not isinstance(body, str) or created is None:
            return None
        if kind == "Bot":
            continue
        if created > now:
            continue
        target = _reaffirmed_instant(body)
        if target is None:
            continue
        found.append(Reaffirmation(at=created, by=login, window_opened_at=target))
    return found


def _reaffirmed_instant(body: str) -> dt.datetime | None:
    """The window instant a comment body re-affirms, or None if it is not one."""
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith(REAFFIRM_TOKEN):
            continue
        remainder = stripped[len(REAFFIRM_TOKEN) :].strip()
        if not remainder:
            continue
        return _parse_instant(remainder.split()[0])
    return None


# --------------------------------------------------------------------------
# The decision.
# --------------------------------------------------------------------------


def _judge_verdict(judge_states: Mapping[str, bool | None]) -> tuple[bool, bool]:
    """(the judge is on somewhere, the judge state was readable somewhere).

    Fails closed across hosts exactly as the live posture does: if either
    readable host reports the judge on, the judge is on.
    """
    readable = [state for state in judge_states.values() if state is not None]
    return (any(readable), bool(readable))


def _judge_note(judge_states: Mapping[str, bool | None], *, live: bool) -> str:
    """One sentence naming what was read about the judge — never a value not read."""
    probed = len(judge_states)
    if not probed:
        return "judge_enabled was not probed."
    judge_on, judge_known = _judge_verdict(judge_states)
    readable = len([state for state in judge_states.values() if state is not None])
    if not judge_known:
        return f"judge_enabled was unreadable on all {probed} /status host(s)."
    state = "true" if judge_on else "false"
    note = f"judge_enabled={state} (read {readable} of {probed} /status host(s))."
    if judge_on and not live:
        note += (
            " The judge cannot spend while live execution is off — the run-path "
            "gate needs a COMPLETED answer on an invoked provider path and "
            "live-off produces none — so this is REPORTED and not alerted, "
            "because it reads like activity and an operator should know."
        )
    return note


def evaluate_posture(
    *,
    readiness_states: Mapping[str, str | None],
    windows: Sequence[DeclaredWindow] | None,
    now: dt.datetime,
    judge_states: Mapping[str, bool | None] | None = None,
    reaffirmations: Mapping[int, list[Reaffirmation] | None] | None = None,
) -> PostureResult:
    """Decide whether production's money posture is one somebody declared.

    ``readiness_states`` maps each probed URL to the ``live_readiness.state`` it
    reported, or None where it could not be read. It is deliberately a mapping
    rather than a single value so the detail can name HOW MANY hosts were read —
    a check that reports "nothing found" without saying what it looked at is the
    trivially-true shape this repository keeps paying for.

    ``judge_states`` maps each probed ``/status`` URL to ``judge_enabled``, or
    None where it could not be read. ``reaffirmations`` maps an issue number to
    the human re-affirmations read from it, or None where the issue could not be
    read.

    ORDER OF PRECEDENCE once the posture is live, and each step's reason:
      1. the declaration file did not parse       -> UNKNOWN (cannot rely on it)
      2. judge state unreadable                   -> UNKNOWN (it can spend now)
      3. no window covers now                     -> PAST_WINDOW / UNDECLARED
      4. a covering window's issue unreadable     -> UNKNOWN (attention unknown)
      5. every covering window's attention lapsed -> REAFFIRMATION_LAPSED
      6. judge on, no attended window declares it -> JUDGE_UNDECLARED
      7. otherwise                                -> WITHIN (standing or not)

    Attention outranks the judge because a lapsed window means nobody is watching
    AT ALL, which is the larger fact; the judge question presumes somebody is.
    """
    judge_states = {} if judge_states is None else judge_states
    reaffirmations = {} if reaffirmations is None else reaffirmations

    readable = {url: state for url, state in readiness_states.items() if state is not None}
    probed = len(readiness_states)
    judge_probed = len(judge_states)
    judge_readable = len([state for state in judge_states.values() if state is not None])
    #: Did every endpoint probed actually answer? A verdict taken over a partial
    #: view may be acted on, but it may not RETIRE a standing alert.
    complete = len(readable) == probed and judge_readable == judge_probed

    if not readable:
        return PostureResult(
            PostureDecision.UNKNOWN,
            f"read live_readiness.state from 0 of {probed} host(s) — refusing to "
            "report a money posture from a value that was never read",
            complete=False,
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
            complete=complete,
        )

    if windows is None:
        return PostureResult(
            PostureDecision.UNKNOWN,
            f"read {len(readable)} of {probed} host(s) reporting "
            f"{sorted(set(readable.values()))}, but the declared-window file could "
            "not be read or did not parse — a declaration that cannot be parsed "
            "must never be mistaken for one that permits something",
            complete=complete,
        )

    judge_on, judge_known = _judge_verdict(judge_states)
    live_hosts = sorted(url for url, state in readable.items() if state != FLAG_OFF_STATE)
    unread = probed - len(readable)
    counted = (
        f"read {len(readable)} of {probed} host(s); {len(live_hosts)} report a "
        f"live-execution posture; {len(windows)} window(s) declared"
    )
    judge_note = _judge_note(judge_states, live=bool(live_hosts))
    partial = (
        ""
        if complete
        else (
            f" {unread} host(s) did not answer, so this verdict is taken over a "
            "partial view and may not close a standing alert."
        )
    )

    if not live_hosts:
        return PostureResult(
            PostureDecision.OFF_AS_DECLARED,
            f"{counted}. Every host that ANSWERED reports {FLAG_OFF_STATE!r}: the "
            f"money switch is off and no visitor can spend. {judge_note}{partial}",
            complete=complete,
        )

    # From here the posture IS live, so the judge dimension becomes load-bearing
    # and an unreadable one is a refusal to guess rather than an assumption.
    if judge_probed and not judge_known:
        return PostureResult(
            PostureDecision.UNKNOWN,
            f"{counted}. {live_hosts} report a live posture, but judge_enabled "
            f"could not be read from any of {judge_probed} /status host(s). While "
            "live execution is ON the judge CAN spend, and its GET-path spend "
            "reaches no ledger (ADR-0013) — so this check refuses to call a live "
            f"posture sanctioned without knowing it.{partial}",
            complete=False,
        )

    active = [window for window in windows if window.covers(now)]
    if not active:
        expired = [
            window
            for window in windows
            if window.expires_at is not None and window.expires_at <= now
        ]
        if expired:
            latest = max(expired, key=_cover_ends)
            expiry = latest.expires_at.isoformat() if latest.expires_at else "?"
            overrun = (
                (now - latest.expires_at).total_seconds() / 3600.0 if latest.expires_at else 0.0
            )
            return PostureResult(
                PostureDecision.LIVE_PAST_DECLARED_WINDOW,
                f"{counted}. {live_hosts} report a live posture, and the most "
                f"recent declared window — {latest.owner!r}, {latest.reason!r} — "
                f"expired {expiry}, {overrun:.1f}h ago. Every visitor to /ui is "
                "spending real money past the instant somebody wrote down as the "
                f"end of it. {judge_note}{partial}",
                complete=complete,
            )
        return PostureResult(
            PostureDecision.LIVE_UNDECLARED,
            f"{counted}. {live_hosts} report a live posture and NO declared window "
            f"covers {now.isoformat()}. Every visitor to /ui can spend real money "
            f"and nobody wrote down that this was intended. {judge_note}{partial}",
            complete=complete,
        )

    # A window whose re-affirmation issue could not be read is a window whose
    # attention this check cannot establish. Refusing to guess is the posture
    # every other unreadable input gets.
    unreadable_issues = sorted(
        {
            window.reaffirm_issue
            for window in active
            if window.reaffirm_issue is not None
            and window.reaffirm_issue in reaffirmations
            and reaffirmations.get(window.reaffirm_issue) is None
        }
    )
    if unreadable_issues:
        return PostureResult(
            PostureDecision.UNKNOWN,
            f"{counted}. {live_hosts} report a live posture inside a declared "
            f"window, but re-affirmation issue(s) {unreadable_issues} could not be "
            "read, so this check cannot establish whether anybody is still "
            f"attending it.{partial}",
            complete=False,
        )

    def _entries(window: DeclaredWindow) -> list[Reaffirmation]:
        if window.reaffirm_issue is None:
            return []
        return reaffirmations.get(window.reaffirm_issue) or []

    attended = [window for window in active if window.is_attended(now, _entries(window))]
    if not attended:
        stalest = max(active, key=lambda w: w.hours_unattended(now, _entries(w)))
        unattended = stalest.hours_unattended(now, _entries(stalest))
        issue = stalest.reaffirm_issue if stalest.reaffirm_issue else "<none declared>"
        return PostureResult(
            PostureDecision.LIVE_REAFFIRMATION_LAPSED,
            f"{counted}. {live_hosts} report a live posture inside "
            f"{stalest.describe()}, but nobody has re-affirmed it for "
            f"{unattended:.1f}h against a {REAFFIRMATION_CADENCE_HOURS:.0f}h "
            "cadence. A declaration nobody is still attending is a declaration in "
            "name only — this is what three unattended days looked like in #357. "
            f"To re-affirm, comment '{REAFFIRM_TOKEN} "
            f"{stalest.opened_at.isoformat()}' on issue {issue}; or switch live "
            f"execution off. {judge_note}{partial}",
            complete=complete,
        )

    if judge_on and not any(window.judge for window in attended):
        return PostureResult(
            PostureDecision.LIVE_JUDGE_UNDECLARED,
            f"{counted}. {live_hosts} report a live posture inside "
            f"{attended[0].describe()} — but /status reports judge_enabled=true "
            "and NO attended window declares the judge. The judge is a second "
            "paid subsystem whose GET-path spend reaches no ledger (ADR-0013), so "
            "global_daily_spend_usd under-reports by exactly its cost while this "
            'stands. Set "judge": true in the window if it was meant, or turn the '
            f"judge off.{partial}",
            complete=complete,
        )

    # The governing window is the one whose cover ends LAST — a standing
    # declaration never ends, so it governs whenever one is attended. Review
    # measured a 24-hour window reported as "0.1h remaining" because a shorter
    # sibling happened to be listed first; the number an operator plans around
    # must be when cover actually ends.
    window = max(attended, key=_cover_ends)
    attended_ago = window.hours_unattended(now, _entries(window))
    if window.is_standing:
        standing_for = (now - window.opened_at).total_seconds() / 3600.0
        return PostureResult(
            PostureDecision.LIVE_WITHIN_STANDING_DECLARATION,
            f"{counted}. {live_hosts} report a live posture under "
            f"{window.describe()}, standing for {standing_for:.1f}h, last "
            f"re-affirmed {attended_ago:.1f}h ago against a "
            f"{REAFFIRMATION_CADENCE_HOURS:.0f}h cadence, judge declared="
            f"{str(window.judge).lower()}. Sanctioned; no alert — and REPORTED "
            "every cycle on purpose, because a standing posture that produced "
            f"silence would look exactly like a dead watchdog. {judge_note}{partial}",
            complete=complete,
        )
    remaining = (window.expires_at - now).total_seconds() / 3600.0 if window.expires_at else 0.0
    expiry = window.expires_at.isoformat() if window.expires_at else "?"
    return PostureResult(
        PostureDecision.LIVE_WITHIN_DECLARED_WINDOW,
        f"{counted}. {live_hosts} report a live posture, inside a window declared "
        f"by {window.owner!r} for {window.reason!r}, opened "
        f"{window.opened_at.isoformat()} and expiring {expiry} — "
        f"{remaining:.1f}h remaining, last re-affirmed {attended_ago:.1f}h ago, "
        f"judge declared={str(window.judge).lower()}. Sanctioned; no alert. "
        f"{judge_note}{partial}",
        complete=complete,
    )


#: A standing window never stops covering, so it sorts above every dated one.
_FOREVER = dt.datetime.max.replace(tzinfo=dt.UTC)


def _cover_ends(window: DeclaredWindow) -> dt.datetime:
    return window.expires_at if window.expires_at is not None else _FOREVER


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

    WHAT IT DELIBERATELY CANNOT CHECK, per ADR-0071:
      * RE-AFFIRMATION FRESHNESS. Attention is a runtime fact read from GitHub;
        this gate is offline and hermetic, and reaching the network to decide a
        merge would be a worse trade than the blind spot. A window that goes
        stale in production is caught by the watchdog within the hour.
      * THE JUDGE, at all. ``fly.toml`` carries no judge configuration
        (measured: ``grep -i judge fly.toml`` exits 1) — the judge is governed
        purely by Fly secrets, so no pre-merge gate can ever see it.

    A ``standing`` window therefore makes this gate permanently quiet, and that
    is the intended trade rather than an oversight: ADR-0070's expiry deadline
    was the mechanical form of a revert condition, and at GA there is nothing to
    revert to. The pressure moves to the runtime attention check, which is the
    only layer that can see whether anybody is still watching.
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
        "reason, mode, judge, opened_at and (for time_boxed) expires_at — in "
        'THIS pull request, or set the flag back to "false". ADR-0060 turned this '
        "on for one session and it ran three days because nothing executed its "
        "revert condition."
    )


# --------------------------------------------------------------------------
# I/O. Every read returns None on failure so the decision above stays pure and
# an unreadable input becomes UNKNOWN rather than an exception or a silent pass.
# NOTHING below may raise: a crash would skip the workflow's alert step and
# leave the job green, which is the failure this whole script is about.
# --------------------------------------------------------------------------


def _request_headers(url: str) -> dict[str, str]:
    """Authenticate only to api.github.com, and only if a token is present.

    A ``file:`` fixture URL gets no headers at all, so every test drives the same
    code path a real read takes without a token ever mattering.
    """
    if not url.startswith("https://api.github.com/"):
        return {}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _fetch_json(url: str, *, attempts: int) -> object | None:
    """Read a JSON body, or None. Never raises — see the module note above."""
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, headers=_request_headers(url))  # noqa: S310
            with urllib.request.urlopen(request, timeout=_READY_TIMEOUT_SECONDS) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 — any failure means "unknown"
            print(f"attempt {attempt}/{attempts}: could not read {url}: {exc!r}")
            if attempt < attempts:
                time.sleep(_READY_RETRY_SLEEP_SECONDS)
    return None


def fetch_readiness_state(url: str, *, attempts: int = _READY_ATTEMPTS) -> str | None:
    """Read ``live_readiness.state`` from ``/ready``. None if it cannot be read."""
    payload = _fetch_json(url, attempts=attempts)
    if payload is None:
        return None
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
    # NOT a default of "offline_by_config". A missing key means "I could not read
    # it", and letting that fall through as the off-state would make this check
    # permanently, silently green.
    print(f"{url} has no usable live_readiness.state (got {state!r})")
    return None


def fetch_judge_enabled(url: str, *, attempts: int = _READY_ATTEMPTS) -> bool | None:
    """Read ``judge_enabled`` from ``/status``. None if it cannot be read.

    A missing or non-boolean value is None, NEVER False. False would be a claim
    that a second paid subsystem is off, made from a value that was never read —
    the exact failure this file exists to prevent, one field over.
    """
    payload = _fetch_json(url, attempts=attempts)
    if payload is None:
        return None
    if not isinstance(payload, dict):
        print(f"{url} returned JSON that is not an object: {type(payload).__name__}")
        return None
    value = payload.get("judge_enabled")
    if isinstance(value, bool):
        return value
    print(f"{url} has no usable judge_enabled (got {value!r})")
    return None


def fetch_reaffirmations(
    url: str, *, now: dt.datetime, attempts: int = _READY_ATTEMPTS
) -> list[Reaffirmation] | None:
    """Read human re-affirmations from a GitHub issue-comments URL."""
    payload = _fetch_json(url, attempts=attempts)
    if payload is None:
        return None
    return parse_reaffirmations(payload, now=now)


def load_windows(path: Path, *, adr_dir: Path | None = None) -> list[DeclaredWindow] | None:
    """Read and parse the declaration file. None if it cannot be trusted.

    Resolves any ``standing`` window's ADR citation against the ADRs on disk, so
    a citation naming a missing, un-Accepted, unmarked or self-referential record
    makes the file untrusted rather than silently sanctioning a posture with no
    authority behind it.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"could not read {path}: {exc!r}")
        return None
    resolved = authorising_adrs(DEFAULT_ADR_DIR if adr_dir is None else adr_dir)
    return parse_windows(payload, authorised_adrs=resolved)


def _write_outputs(result: PostureResult) -> None:
    """Publish the verdict to ``$GITHUB_OUTPUT`` so the workflow can branch on it."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"decision={result.decision.value}\n")
            handle.write(f"should_alert={'true' if result.should_alert else 'false'}\n")
            handle.write(f"complete={'true' if result.complete else 'false'}\n")
    except OSError as exc:
        print(f"could not write $GITHUB_OUTPUT: {exc!r}")


def _reaffirmation_urls(
    windows: Iterable[DeclaredWindow], *, template: str, repo: str
) -> dict[int, str]:
    urls: dict[int, str] = {}
    for window in windows:
        if window.reaffirm_issue is not None:
            urls[window.reaffirm_issue] = template.format(repo=repo, issue=window.reaffirm_issue)
    return urls


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Alert when production's money-spending posture is undeclared."
    )
    parser.add_argument("--ready-url", action="append", dest="ready_urls", default=None)
    parser.add_argument("--status-url", action="append", dest="status_urls", default=None)
    parser.add_argument("--windows-file", default=str(DEFAULT_WINDOWS_PATH))
    parser.add_argument("--adr-dir", default=str(DEFAULT_ADR_DIR))
    parser.add_argument(
        "--reaffirmations-url",
        default=DEFAULT_REAFFIRMATION_URL_TEMPLATE,
        help="Template for the issue-comments URL; {repo} and {issue} are filled in.",
    )
    args = parser.parse_args(argv)

    now = dt.datetime.now(dt.UTC)
    urls = tuple(args.ready_urls or DEFAULT_READY_URLS)
    states = {url: fetch_readiness_state(url) for url in urls}
    for url, state in states.items():
        print(f"probed {url} -> live_readiness.state={state!r}")

    status_urls = tuple(args.status_urls or DEFAULT_STATUS_URLS)
    judge_states = {url: fetch_judge_enabled(url) for url in status_urls}
    for url, judge in judge_states.items():
        print(f"probed {url} -> judge_enabled={judge!r}")

    windows_path = Path(args.windows_file)
    adr_dir = Path(args.adr_dir)
    print(f"declared windows read from {windows_path}; ADR citations resolved in {adr_dir}")
    windows = load_windows(windows_path, adr_dir=adr_dir)

    # Re-affirmations are read ONLY when they can change the verdict: a live
    # posture, inside a covering window that names an issue. In today's steady
    # state (live execution off) that is ZERO network reads, which is why this
    # revision adds no new way for the quiet path to go wrong.
    reaffirmations: dict[int, list[Reaffirmation] | None] = {}
    live_now = any(state is not None and state != FLAG_OFF_STATE for state in states.values())
    if live_now and windows:
        repo = os.environ.get("GITHUB_REPOSITORY", "imrohitagrawal/quorum-ai")
        active = [window for window in windows if window.covers(now)]
        for issue, url in _reaffirmation_urls(
            active, template=args.reaffirmations_url, repo=repo
        ).items():
            entries = fetch_reaffirmations(url, now=now)
            reaffirmations[issue] = entries
            found = "unreadable" if entries is None else f"{len(entries)} human re-affirmation(s)"
            print(f"probed {url} -> {found}")

    result = evaluate_posture(
        readiness_states=states,
        windows=windows,
        now=now,
        judge_states=judge_states,
        reaffirmations=reaffirmations,
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
