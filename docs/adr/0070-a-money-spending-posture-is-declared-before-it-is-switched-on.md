# ADR-0070: A money-spending posture is declared before it is switched on

## Status

Accepted — 2026-08-25. Answers the gap #357 records; ADR-0060 is its history.

## Context

`OPENROUTER_LIVE_EXECUTION_ENABLED` is the one switch that lets any `/ui` visitor
spend real money. `providers.py:669-670` is
`bool(settings.openrouter_live_execution_enabled and openrouter_key)`, and the
key is a deployed secret, so the flag alone decides.

ADR-0060 turned it on to collect a sample and recorded a posture "expected to be
reverted in the same session it was adopted". It ran for three days. Every
automated check was green throughout, and every one of them was **right** to be:

| Existing check | The question it asks | Why it was silent |
|---|---|---|
| `deploy-drift-watchdog.yml` | does production serve `main`'s tip? | it reported the drift RESOLVED at the moment the flag deployed — that is what it is for |
| `availability-check.yml` | is `/ready` 200 and `live`? | `live` IS the money-spending posture, and this check treats it as the good state |
| `error-rate-check.yml` | is the 5xx share inside the SLO? | a money-spending posture is neither unavailable nor erroring |

Measured 2026-08-25, scoped to `main` at `b5d6224` — i.e. BEFORE this ADR's
workflow existed: `git grep -n 'live_execution' b5d6224 -- .github/` matched
**nothing** (exit 1). The scoping is deliberate and was a review finding: an
earlier draft wrote this as `grep -rn ... .github/` over the working tree, where
it now matches the very workflow this ADR adds. A claim that refutes itself the
moment it ships is worse than no claim. Positive partner, so the grep is known
to work and the directory is known not to be empty: `git grep -c build_sha
b5d6224 -- .github/workflows/deploy-drift-watchdog.yml` returns **5**.

ADR-0060's own "revert condition, stated so it is not a judgement call" is prose
in a document. Nothing executed it. Spend over the window was $0.1768 — which is
not the point. The exposure was bounded only by `GLOBAL_DAILY_CEILING_USD`
($5.00/day, `costs.py:168`), **and that ceiling resets daily**, so unnoticed the
standing exposure renews indefinitely.

## The failure modes, enumerated before the code (rule 16e)

Rule 16e exists because the spend-cap work went five review rounds discovering
its failure modes one at a time from defects. This list was written first, from
ADR-0004, ADR-0013, ADR-0016, ADR-0031 and ADR-0060, and the design below is
answerable to it row by row.

| # | Failure mode | Evidence | How this design is immune |
|---|---|---|---|
| 1 | **Watching a derived field instead of the posture.** `/status.live_execution` is `report.state in ("live",)` (`main.py:984`), and `"live"` needs the flag AND a key AND a probe verdict (`readiness.py:429-446`). Flag-on-with-a-refused-key serves `live_execution: false` while `providers.py:670` — which has no probe term — returns True. | `main.py:984` vs `readiness.py:437-445` | reads `/ready.live_readiness.state`. `readiness.py:445` is the `else` of a four-way, so `offline_by_config` ⟺ the flag is off, exactly. A test walks all four states. |
| 2 | **A Fly secret overriding `fly.toml`, invisible to any repo-reading check.** | `DEPLOY.md:61`, `:175`, `:230` instruct the operator to use `fly secrets set OPENROUTER_LIVE_EXECUTION_ENABLED="true"` — a path touching no tracked file. Precedence itself is UNVERIFIED (below). | the primary check reads what the running process serves, never the repository. |
| 3 | **A gate green having measured nothing.** Its normal verdict is "found nothing", the trivially-true shape; 13 of 21 CI jobs here could once reach a terminal status having measured nothing. | AGENTS.md, `docs/analysis/03-enforcement-machinery.md` | every decision names how many hosts were read of how many probed and how many windows are declared, asserted by `test_the_detail_names_how_many_hosts_and_windows_it_read`; no readable host is `UNKNOWN`, which alerts. |
| 4 | **An unreadable input read as fine.** A missing key defaulting to the off-state is permanently, silently green. | `deploy_drift_check.py`'s docstring: "printing a blank and exiting 0 is the silent wrong-number failure this script exists to prevent" | every fetch returns `None`, never a default; `None` routes to `UNKNOWN`, which alerts. **10** malformed-body rows and **12** malformed-declaration rows pin it (`pytest --collect-only \| grep -c`). |
| 5 | **A cold machine read as "off".** `fly.toml` sets `min_machines_running = 0`. | `deploy_drift_check.py:72-78` | the same measured retry shape: 10s timeout, 3 attempts, 5s sleep — then alert, never silently pass. |
| 6 | **Declared cadence is not detection latency.** | re-measured for this ADR, below | the workflow header and this ADR both state the measured latency, not the cron. |
| 7 | **The scheduled check auto-disabled after repository inactivity** — it dies exactly during the unattended stretch it covers. | `availability-check.yml:22-23`; ~60 days is INHERITED, not verified here | not solved. Stated as a blind spot. The pre-merge layer keeps working regardless of schedules. |
| 8 | **An alert routed to an ephemeral channel nobody reads.** | `availability-check.yml:24-28` — the failure email goes to whoever last touched the schedule, and honours their notification settings | a labelled GitHub issue, the mechanism proven end-to-end on issue #351 (machine-opened, 11 machine comments, machine-closed). |
| 9 | **Alert fatigue — the red you learn to ignore.** Three measured instances here, including a permanently-red deploy job and ~96 emails/day. | `deploy_drift_check.py:74-76`, `deploy.yml:275-281`, `availability-check.yml:26-28` | quiet in the normal posture AND quiet inside a declared window; ONE issue, opened once, no repeat comments (the sibling watchdog produced 11 comments in 10h14m, which over three days is ~70). |
| 10 | **The mirror image: excluding the deliberate state excludes the subject.** `availability-check.yml:77-96` deliberately treats `offline_by_config` as not an event. | that file | this check's alarm predicate is the deliberate complement of that one's. Both files now say so. |
| 11 | **Auto-resolving on the wrong event.** The drift watchdog closes its issue when a deploy succeeds — which is exactly what happened as the flag deployed. | `deploy-drift-watchdog.yml:80-81`; #351 closed 2026-08-19T19:01Z while the posture then ran unwatched until 08-22 | the posture alert closes ONLY on an observed non-alerting reading (`outcome == 'success' && should_alert == 'false'`), never on a deploy or a merge. |
| 12 | **Merging the revert is not turning it off.** The enable was stranded by CI; the revert can be stranded identically. | ADR-0060 Status, #351 | the runtime watchdog watches what production serves, never what `main` says. This is also why #357's option 3 (a deploy-time assertion) is not the primary mechanism. |
| 13 | **Read-modify-write races and lost writes**, if the watchdog keeps its own state. | ADR-0016's barrier harness: 32 threads → $0.9376 against a serial control of $0.1758. ADR-0004's F-01: 12 requests allowed, $0.3180 spent, ledger $0.00, zero rows on disk. ADR-0002 pins single-writer SQLite. | **the watchdog is stateless.** Two reads, one pure function, no counter, no store, nothing to lose. |
| 14 | **Masking — a later benign reading re-stamps health over the money signal.** | ADR-0004 shape 3; `feedback_lost_billed_writes` exists because a concurrent success can mask a lost charge | the open issue persists until an observed safe reading closes it; the closing comment names the decision that closed it. |
| 15 | **Duplicate alarms from concurrent runs.** | `deploy-drift-watchdog.yml:47-49` | same two mechanisms: a `concurrency` group and a single-issue-by-label lookup. |
| 16 | **Clock skew / "how long has it been on".** | no local evidence for skew; `/status.uptime_seconds` is a lower bound only, since `min_machines_running = 0` makes restarts routine | the decision never subtracts two clocks to reach a verdict. It compares one runner clock against declared instants that must carry an explicit UTC offset; a naive timestamp is refused rather than assigned a zone. |
| 17 | **Alarming on spend instead of posture — it would have been silent.** | ADR-0060's close-out: $0.1768 over 3 runs and 1 `/ui` load across the whole three days | no spend threshold. The hazard is standing exposure, not realised loss. |
| 18 | **The money number you would threshold on under-reports anyway.** | ADR-0013: while `judge_enabled` is true, `global_daily_spend_usd` and the per-account cap under-report by GET-path judge spend | reinforces 17. |
| 19 | **Scoping to one flag leaves the sibling posture unwatched.** `/status` reports `judge_enabled: true` in production today. | my `curl` on 2026-08-25 | **not solved.** See the open decisions below; watching it needs a policy nobody has written. |
| 20 | **Gating on a platform behaviour never measured.** | rule 8c: a `Content-Length` gate, correct on loopback, would have collected nothing against Cloudflare's chunked errors | reading `/ready` makes Fly's secret-precedence question moot for the primary check. It is answered through the running process, not through config. |
| 21 | **The mechanism is prose that nothing executes.** | ADR-0060's revert condition; #357 | the declared window is a machine-readable file two checks parse, and a malformed one alerts. |
| 22 | **A test that passes with the mechanism absent.** | rules 6b, 8, 8a | eleven mutations, each proven red and restored — table below. |

## Decision

**Two checks, asking different questions, blind in opposite directions.**

**1. Runtime, unbypassable — `scripts/live_posture_check.py` +
`.github/workflows/live-posture-watchdog.yml`.** Every 30 minutes it reads
`live_readiness.state` from both production hosts, reads the declared windows
from `configs/live-execution-windows.json`, and alerts when a live posture is not
covered by a window. Decision in tested Python per ADR-0024, thin shell,
`$GITHUB_OUTPUT`, an alert step, a resolve step and an explicit fail step — the
five-part shape `deploy_drift_check.py` established.

**2. Pre-merge, in a blocking lane —
`tests/unit/test_live_execution_posture_declaration.py`.** It refuses a `fly.toml`
that commits the flag as `"true"` with no window covering the merge. It runs in
`pytest (Python 3.12)`, a required context.

Layer 1 cannot see a flag flipped in `main` and not yet deployed — the exact
shape of #351, which stranded ADR-0060's merge and stretched a one-session window
to three days. Production is not spending yet, so layer 1 is correctly silent.
Layer 2 sees exactly that, and is in turn blind to a Fly secret. Neither is
sufficient; together they cover both edges of the same concern.

### The signal is "on without a declaration", not "on at all"

This is the load-bearing choice, and it is the answer to crying wolf.

Live execution is legitimately switched on sometimes — ADR-0060 is the worked
example, and a future sample is explicitly anticipated. A check that fires
through every sanctioned window is a check somebody mutes, and **a muted alert is
worse than none**. So the sanctioned window is *declared*: an entry with an
owner, a reason and an expiry, committed in the same pull request that flips the
flag. Inside it the check is quiet — while still printing the owner, the reason
and the hours remaining, so a reader of a green job can see what it counted.

Two properties fall out, and both are deliberate:

* **A forgotten declaration cannot disarm the watchdog.** It expires on its own
  and becomes inert. There is no state in which an unclosed file leaves the check
  permanently silent.
* **The only way to silence this indefinitely is to commit a far-future
  `expires_at`**, which appears in a diff and is reviewed like any other change.
  That is a deliberate, attributable act — the opposite of the failure #357
  records, which was nobody noticing anything.

The escape valve is real and intended: an already-firing alert can be resolved by
declaring the window retrospectively. That is a commit saying "yes, this was
meant", which is precisely the record ADR-0060 lacked.

**That valve did not work in the first draft, and review is what found it.** A
test asserted the shipped declaration file was EMPTY (`parsed == []`). Doing the
sanctioned thing — one covering window plus `fly.toml` `"true"` — turned the
blocking `pytest (Python 3.12)` lane red, so the sanctioned window could never
merge; and because the file's own README asks that expired entries stay as the
record, there was no state after the first declaration in which it was empty
again. A guard that goes red on the path it exists to permit is a guard somebody
deletes, which is failure mode 9 arriving through the front door. The assertion
is now that the file PARSES, plus a separate one that no window covers the
present *while the flag is off* — which an expired historical entry satisfies.
Both directions are proven: with a covering window and the flag `"true"` the
suite is green (95 passed), and with that window expired and the flag still
`"true"` it is red on
`test_the_committed_flag_is_off_or_covered_by_a_declared_window`.

### A partial read may be acted on, but it may not retire an alert

Review found the first draft returning `OFF_AS_DECLARED` when one host answered
`offline_by_config` and the other could not be read at all — with a detail line
that said "**Every** host reports `offline_by_config`" over a host it never
read, directly above its own printed "read 1 of 2". Worse, that reading
satisfied the resolve step, so a half-blind cycle could close a standing money
alert.

The verdict itself is still taken from the hosts that answered — both URLs are
the same Fly app, so one answer settles the posture, and demanding both would
turn an ordinary DNS blip into a money alert. What changed is that the result
now carries `complete`, published on the wire alongside `decision` and
`should_alert`, and the resolve step requires `complete == 'true'`. Retiring an
alert on a partial view is the one thing a half-blind cycle must not do.

The cost, stated: if a host is permanently retired without being removed from
`DEFAULT_READY_URLS`, no cycle is ever complete and an open alert can never
auto-close. The job log names the count on every run ("read 1 of 2 host(s)"), so
that is visible rather than silent — but it is a real consequence, not a
hypothetical.

### Where the alert goes

A GitHub issue labelled `live-posture`, opened once and closed only by an
observed non-alerting reading, plus a red job every cycle. This reuses the
mechanism proven on issue #351 — machine-opened, machine-commented 11 times,
machine-closed 10h14m later.

It deliberately does **not** re-comment each cycle. The sibling watchdog's 11
comments in 10h14m would be roughly seventy over a three-day posture, and that is
how an alert gets muted (failure mode 9). The recurring signal is the red job.

## Measured

Every row run by me in this worktree on 2026-08-25 unless marked.

| Question | Command | Result |
|---|---|---|
| Does anything in CI read the flag? | `grep -rn 'live_execution' .github/` | **nothing** (exit 1) |
| ...and is that grep working? | `grep -c 'build_sha' .github/workflows/deploy-drift-watchdog.yml` | 5 lines — the positive partner |
| What does production serve? | `curl -s https://quorum-ai.fly.dev/status` | `live_execution: false`, `judge_enabled: **true**`, `global_daily_spend_usd: "0"`, ceiling `"5.00"` |
| ...and `/ready`? | `curl -s https://quorum-ai.fly.dev/ready` | `live_readiness.state: offline_by_config` |
| Does the state vocabulary have exactly one off-state? | `readiness.py:54-58`, `:429-446` | four states; `offline_by_config` is the `else`, so the equivalence with "flag off" is exact |
| Real detection latency of a `*/30` lane | `gh api .../deploy-drift-watchdog.yml/runs?per_page=100`, gaps between the 100 most recent scheduled runs (2026-08-21T07:25Z → 08-24T22:33Z, 87.1h) | min **21.7** / median **53.4** / max **129.4** minutes against a declared 30 |
| Does the shipped watchdog alert on today's production? | `uv run python scripts/live_posture_check.py` | `decision=off_as_declared`, exit **0**, "read 2 of 2 host(s); 0 report a live-execution posture" |
| Does it FIRE when the flag is on? | the script against a `file:` fixture serving `state: "live"` | `decision=live_undeclared`, `should_alert=true`, exit **1** |
| Does it reproduce #357's shape? | same, with a window that expired 72h ago | `decision=live_past_declared_window`, exit **1**, "expired ..., 72.0h ago" |
| Does it stay quiet inside a declared window? | same, with a covering window | `decision=live_within_declared_window`, exit **0**, "3.0h remaining. Sanctioned; no alert." |
| Baseline suite before this change | `make quality` | `3292 passed, 67 skipped`, coverage 95.28% |

**The flag was never switched on to test any of this.** Every firing path is
driven by a `file:` fixture. No paid provider call was made.

**The `*/30` cadence is not a money guardrail** — it is a detection-latency
choice, matched to the existing sibling lane. Against a three-day exposure any of
21.7–129.4 minutes closes it, so buying a faster cadence at the cost of a weaker
question would be the wrong trade.

## The bite table

Twenty-one mutations, each `cp` aside, applied, run, restored from the copy and
confirmed with `diff -q` (never `git checkout`). **All were re-run against the
final tree**, so every count below shares one baseline: **97 passed**.
An earlier draft quoted 78, which was the baseline when the first eleven were
run and was stale by the time the file shipped — review caught it, and re-running
was cheaper than explaining the discrepancy. The harness refuses a mutation that
changes nothing (`MUTATION-NOOP`), because a `perl` expression that silently
matches nothing proves nothing.

A trap worth recording: the first attempt at this re-run passed the two test
paths as an unquoted `$T` shell variable. **zsh does not word-split**, so pytest
received one bogus path and printed `no tests ran in 0.00s` — for the baseline
AND for every mutation. Every row would have "passed" having measured nothing.
The baseline row is what caught it. Quote the baseline, always.

| # | Mutation | Result |
|---|---|---|
| M1 | delete `_write_outputs(result)` from `main()` | **4 failed** |
| M2 | rename the `should_alert=` output key | **4 failed** |
| M3 | live-host filter ignores the state (`if False`) | **12 failed** |
| M4 | `covers()` drops its expiry bound | **4 failed** |
| M5 | a missing `live_readiness.state` defaults to `offline_by_config` | **2 failed** |
| M6 | an unreadable declaration treated as "nothing declared" | **1 failed** |
| M7 | `refuse_undeclared_flag` never refuses | **9 failed** |
| M8 | the alert step drops its crashed-step disjunct | **1 failed** |
| M9 | the workflow no longer `exit 1`s | **1 failed** |
| M10 | the resolve step drops its observed-reading terms | **2 failed** |
| M11 | `fly.toml` commits `"true"` with no declaration | **1 failed** |
| M12 | the alert step files a new issue every cycle | **1 failed** |
| M13 | the resolve step closes with an empty issue number | **1 failed** |
| M14 | the alert step no longer runs `gh issue create` | **1 failed** |
| M15 | the fail step's condition typo'd — `shouldAlert` / `faliure` | **1 failed** |
| M16 | the alert step gated on `github.event_name == 'workflow_dispatch'` | **1 failed** |
| M17 | `complete` hardcoded True | **1 failed** |
| M18 | declared offsets no longer normalised to UTC | **1 failed** |
| M19 | the readiness vocabulary drifts from `readiness.py` | **1 failed** |
| M20 | the active window is picked by file order again | **1 failed** |
| M21 | the alert title asserts "Live execution is on" again | **1 failed** |

M1, M2, M9, M15 and M16 are the ones no decision-only test could see: each
leaves the watchdog permanently GREEN while production spends.

**M15 and M16 are review's, not the author's**, and they are the reason sections
A-E of the test file are not enough on their own. The original condition tests
asserted that two substrings appeared *somewhere* in a step's `if:`, which is
blind to what else was ANDed to them — AGENTS.md rule 8 reappearing inside the
new gate. Both mutations left the whole suite green while making the watchdog
silent or permanently OK. Every step condition is now asserted by **equality**
against its full normalised text, and the fail step — which had no assertion at
all — has one.

M20 and M21 are review's second lens: with two overlapping windows the verdict
was right but the operator-facing "0.1h remaining" was taken from whichever was
listed first rather than from when cover actually ends; and the alert issue's
TITLE hard-coded "Live execution is on and no declared window covers it", which
is false for the `unknown` verdict — an unparseable declaration file would have
filed that title every thirty minutes while the flag was off. Both are the
repo's own "never report a value that was never read" rule pointed the wrong
way, and both are exactly how a real alert learns to be ignored.

M12-M14 come from a gap the author found separately: sections A-E assert the
workflow's *structure*, and structure cannot see whether a `set -euo pipefail`
block actually runs. The alert and resolve steps are therefore also EXECUTED
against a stubbed `gh`, asserting on the exit code and on the commands the stub
was asked to run.

## Rejected alternatives

1. **Read `/status.live_execution`, as #357 suggests.** Rejected: it is derived
   (`main.py:984`), so a flag that is ON with a refused key reads `false` while
   `providers.py:670` still returns True. `/ready.live_readiness.state` carries
   the exact equivalence instead.
2. **Read `fly.toml` as the primary check.** Rejected: `DEPLOY.md:61,175,230`
   tells operators to set this flag with `fly secrets set`, which touches no
   tracked file. Kept as the *secondary*, pre-merge layer only, with that limit
   written into the test file.
3. **A deploy-time assertion only** (#357's option 3). Rejected as a sole
   mechanism: a deploy-time check is an edge trigger and this is a level problem.
   It passes at the moment of deploy and says nothing for the next 72 hours. Its
   value — catching the transition — is kept in layer 2.
4. **Alert on "on at all", with no declaration file.** Rejected: it fires through
   every sanctioned window, which is how an alert gets muted (failure mode 9).
5. **Threshold on spend.** Rejected: the entire three-day exposure was $0.1768,
   so any threshold would have been silent throughout (failure mode 17), and the
   number under-reports anyway while the judge is on (18).
6. **Cap the maximum declared window length in code.** Rejected here, not on the
   merits but on the evidence: see the open decision below. Choosing that number
   from one production sample is exactly the move ADR-0060's Decision (1)
   refused.
7. **Comment on the open issue every cycle**, as the drift watchdog does.
   Rejected: ~70 comments over a three-day posture.
8. **Keep state (how many cycles the posture has been on).** Rejected: failure
   mode 13. A stateless check has nothing to lose or race.

## Consequences

- Turning live execution on now costs one extra file edit, in the same pull
  request. If the operator uses `fly secrets set` instead, layer 2 is bypassed
  and layer 1 alerts within ~1 hour — which is the intended shape.
- A red `Live-execution posture watchdog` job and an open `live-posture` issue
  mean production may be spending money nobody sanctioned. Neither closes itself
  on a deploy.
- **This check is a level detector, not a transition detector.** A window that
  opens and closes inside one throttled cron gap (up to 129.4 minutes, measured)
  is never observed at all.
- `judge_enabled` is `true` in production today and remains unwatched.
- `DEPLOY.md` step 4 — the one document that actually turns this flag on — now
  names the declaration file and the watchdog, and `docs/80-observability.md`
  lists the monitor. Review found both unchanged in the first draft, which would
  have left the quiet path undiscoverable from the runbook: an operator
  following it would trip the alert every sanctioned time, which is exactly the
  crying-wolf failure the declaration exists to prevent.
  `test_deploy_md_tells_the_operator_to_declare_the_window` keeps that true.
- **Once a declared window expires with `fly.toml` still `"true"`, the required
  `pytest (Python 3.12)` context goes red — on `main` and on every open pull
  request** — until someone sets the flag back or extends the declaration. That
  is the intended pressure, and it is the mechanical form of ADR-0060's revert
  condition; it is also the sharpest edge in this design, and it should be
  stated rather than discovered. The pre-merge gate is wall-clock dependent by
  construction: that is what makes it a deadline rather than a note.
- An alert opened by a transient `UNKNOWN` keeps that decision in its body even
  if a genuine live posture follows in the next cycle, because the alert step
  deliberately does not re-comment. The window is one cycle and the job log
  carries the current decision, but the design has no way to say "the reason
  changed". Accepted in exchange for not producing ~70 comments over three days.

## Open decisions for a human — numbers I refuse to guess

Rule: a money guardrail never moves on weak evidence. Three numbers here can only
be justified by a decision or a measurement I do not have, so the mechanism ships
without them rather than with a guess.

1. **Is there a maximum permitted declared-window length, and what is it?**
   Today a declaration may name any `expires_at`. The only comparators in this
   repo are the failure (~3 days) and ADR-0060's prose ("one attended session"),
   which names no hours. `GLOBAL_DAILY_CEILING_USD` is labelled in `costs.py` as
   "a business-policy figure, not derived from any ordering constraint" and was
   operator-decided; this is the same kind of number and deserves the same
   treatment.
2. **Does `judge_enabled` have a sanctioned posture, and should it be watched?**
   It is a second paid subsystem, ON in production today, governed by Fly secrets
   with no commit and no time-box. ADR-0013 recommends "a bounded, watched
   window"; the repository's working assumption has been that it is permanently
   on. Those are incompatible, and until one is chosen there is nothing for a
   watchdog to compare against. Extending this mechanism to it is a small change
   *after* that decision, and a fabricated policy before it.
3. **Should an escalation exist above the issue** — a second, louder channel if a
   posture alert stays open past some duration? That needs a duration, and no
   measured basis for one exists.

## UNVERIFIED

- **Whether a Fly secret overrides a `fly.toml` `[env]` value on this app.**
  ADR-0060 recorded it as UNVERIFIED and it still is. Fly's published
  configuration reference states that secrets take precedence, but that is vendor
  documentation, not a measurement here, and rule 8c is the price of trusting an
  upstream you have not looked at. The exact checks that would settle it:
  `fly secrets list -a quorum-ai` (read-only; `flyctl` on this box has no access
  token) and then `fly ssh console -a quorum-ai -C env | grep OPENROUTER_LIVE`.
  **The design does not depend on the answer**: layer 1 asks the running process,
  which is right either way, and layer 2 states the limit in its own docstring.
- **The ~60-day scheduled-workflow auto-disable** (failure mode 7) is inherited
  from `availability-check.yml:22-23` and `docs/80-observability.md`. Not
  re-verified against GitHub's documentation here.

## Related

- ADR-0060 — both halves: the adoption and the revert close-out.
- ADR-0024 — the decision lives in tested Python, not a YAML condition.
- ADR-0004, ADR-0013, ADR-0016, ADR-0031 — the spend rails whose recorded failure
  modes the table above is built from.
- Issues #357 (this gap), #351 (the CI fault that stretched the window),
  #105 and #268 (what the window existed to serve, and could not).
