# ADR-0071: Live execution is the steady state, so the declaration is re-affirmed rather than time-boxed

## Status

Accepted — 2026-08-25. Follows [ADR-0070](0070-a-money-spending-posture-is-declared-before-it-is-switched-on.md),
which is not superseded: its two layers, its failure-mode table and its
"on without a declaration, not on at all" choice all stand. This record answers
ADR-0070's three open decisions — two resolved, one **corrected** — and fixes
the one assumption underneath the whole mechanism that its own evidence
contradicts.

## Context

### The assumption that was wrong

ADR-0070 is built for a live posture that is EXCEPTIONAL: an event, with an
owner, a reason and an end somebody writes down. Every property follows from
that — the expiry is a deadline, the pre-merge gate is a revert condition, the
quiet state is "off".

The project's own plan says the opposite.
`docs/analysis/2026-08-06-go-live-triage-and-plan.md:34-35`:

> The phrase "go-live" appears exactly once in the entire tree — `DEPLOY.md:219`,
> where "Go live" means *set the OpenRouter key and turn live execution on*.
> **That is already done.**

A mechanism whose only quiet state is a time-boxed exception is the wrong shape
for a steady state. Left alone it would have produced a red required context and
an open alert issue every day of normal operation, and the pressure to silence
it would have grown every week. That is failure mode 9 — the red you learn to
ignore — arriving by design rather than by accident.

### Why no MAXIMUM WINDOW LENGTH can be chosen (ADR-0070 open decision 1)

ADR-0070 left "is there a maximum permitted declared-window length" open and
refused to guess. It cannot be answered, and that is a finding rather than a
deferral:

| Case | Duration | Verdict |
|---|---|---|
| The #357 failure | ~3 days | the thing the mechanism exists to catch |
| Issue #105's need | ~7 days | legitimate, and blocked by anything shorter |

`docs/analysis/2026-08-06-go-live-triage-and-plan.md:208` on #105: *"Remaining
work is a week of production logs, not code."* So the failure is SHORTER than
the legitimate need. **No single number separates them**, and any number chosen
would either permit #357 or forbid #105.

What does separate them is whether anybody was still watching. Nobody attended
#357's three days; #105's week would be attended daily by the person collecting
the logs. So the mechanism measures ATTENTION, at any length.

### Why the judge is not a separate question (ADR-0070 open decision 2)

**ADR-0070's open decision 2 rests on a premise that is false, and this record
says so plainly rather than tidying it away.** It reads: *"`judge_enabled` … is a
second paid subsystem, ON in production today, governed by Fly secrets with no
commit and no time-box"*, and failure-mode row 19 calls it *"the sibling posture
unwatched"*. The implication is a second, independent money exposure running
unwatched right now.

It is not independent, and while live execution is off it is not an exposure at
all. Measured, by reading the gate and by driving the real producer:

* `query_run_orchestration.py:2256-2278` refuses a judge call unless some answer
  is `COMPLETED` **and** its `provider_path` is outside
  `NOT_INVOKED_PATHS = {LOCAL_SIMULATION, FALLBACK_SEARCH}` (`providers.py:122`).
* The only site that produces such an answer is inside `produce_initial_answer`'s
  `_live_execution_enabled` branch (`providers.py:512`, `:571`). The three other
  sites that set `OPENROUTER_SEARCH` (`providers.py:783`, `:853`, `:910`) all set
  status `FAILED`.
* `tests/integration/test_judge_never_spends_on_a_run_that_must_not_spend.py`
  pins the gate: 9 passed.

So the judge cannot spend while live execution is off. The exposure is not a
second switch to watch — it is a **multiplier on this one**, and the dangerous
state is the conjunction. Two of ADR-0070's own rows each state half of it and
neither states the conjunction:

* row 18 — while the judge is on, `global_daily_spend_usd` and the per-account
  cap UNDER-REPORT by the judge's GET-path spend (ADR-0013: no GET or DELETE
  route reaches any ledger writer);
* row 19 — the judge is on in production and unwatched.

Put together: **the moment a live window opens with the judge left on, a second
paid subsystem starts spending and the one number an operator would look at is
under-reporting by exactly its cost.** Nobody re-decides the judge at that
moment, because `judge_enabled` was left true from testing.

The question is therefore not "does the judge have a policy?" — which nobody has
decided and which this record still refuses to invent. It is "does the window
SAY whether the judge is in it?" That is declaration, not policy, and it is the
same move the live flag's window already makes.

### Why the escalation channel is WITHDRAWN, not deferred (ADR-0070 open decision 3)

ADR-0070 asked whether a second, louder channel should exist above the issue if
an alert stays open past some duration. **Nothing prompted the question.** There
is no incident where an issue was opened and ignored; there is no measured basis
for the duration it would need; and the channel it would escalate FROM has never
fired — no `live-posture` issue has ever been opened, because the mechanism
shipped on 2026-08-25 and production has been `offline_by_config` since.

Recorded as **withdrawn** rather than deferred, and the difference matters. A
deferred decision is a gap somebody rediscovers, re-opens and eventually builds.
A withdrawn one carries its reason, so the next reader can see it was considered
and dropped for cause. If a posture alert is ever ignored long enough to matter,
that incident will supply the duration this question needs and it can be asked
again with evidence.

## The failure modes, enumerated before the code (rule 16e)

`mode: standing` is a mechanism whose honest purpose is also a way to silence
the alarm permanently. That is the exact shape ADR-0069 REJECTED for the
mutation-gate exclusion ledger, and its rejection ground 4 names the hazards
this design inherits: *entries outliving their code*, *growth with nothing
reporting size or age* — "this repo has **no** precedent for a size- or
age-reporting allowlist to copy" — and a re-blessing that *"turns into a rubber
stamp"*. The list below was written first and the design answers it row by row.

| # | Failure mode | Evidence | How this design answers it |
|---|---|---|---|
| 1 | `standing` set to quiet a noisy alert, with no intent to go live | ADR-0069 measured the same reflex on the adjacent hatch (`# pragma: no mutate`, 2 of 11 mutants deleted per comment); ADR-0070 makes an expired window turn the **required** `pytest (Python 3.12)` context red on `main` and on every open pull request, which is the strongest possible incentive to reach for a silencer | `standing` removes the DEADLINE and nothing else. It still lapses without re-affirmation, so it buys 24 hours, never silence |
| 2 | `standing` added during an incident and never removed | ADR-0070's escape valve is designed for retrospective declaration; under `time_boxed` it self-closes, under `standing` it would not | same as 1, plus the decision value names it in the job log every cycle |
| 3 | The ADR citation points at an ADR that authorises nothing | measured: `grep -rl 'OPENROUTER_LIVE_EXECUTION_ENABLED' docs/adr/` returns **6 of 68**, and 2 of the 6 (ADR-0022's credential removal, ADR-0054's 403 capture) authorise nothing at all. **A prose grep is measurably not a discriminator** | the cited ADR must carry an explicit authorisation marker on a line of its own — a deliberate act that cannot be satisfied by accident |
| 4 | The citation points at a non-existent ADR | nothing in the repo resolves an ADR citation made anywhere else | resolved against `docs/adr/` on disk; a miss makes the whole file untrusted |
| 5 | The citation points at a **Proposed** or **Superseded** ADR | ADR-0014 is Proposed and ADR-0001 Superseded — both exist on disk and would pass a file-exists check | `## Status` must begin `Accepted`, parsed structurally |
| 6 | Circular citation — `standing` cites the ADR that invented `standing` | ADR-0070 is one of the 6 that name the flag, so any flag-name grep accepts it | `MECHANISM_OWN_ADRS` refuses ADR-0070 and ADR-0071 even when they are in the authorised set. Going permanently live costs a NEW record that says so |
| 7 | "It appears in a diff and is reviewed" — ADR-0070's stated safeguard | measured: `required_approving_review_count` on `main` is **0**, `require_code_owner_reviews` false, `.github/CODEOWNERS` is the unedited template `* @<github-org-or-username>`, `required_signatures` disabled | **that safeguard does not exist here.** Every property in this design is mechanical or it is not claimed. This ADR does not write "reviewed in a diff" anywhere as a control |
| 8 | `standing` silently covers the judge | prose reading "the GA steady state" would be read as covering both | `judge` is REQUIRED on every window, in both modes, with no default |
| 9 | A `mode` typo silently degrades | measured on the pre-change parser: `{"mode": "standing"}` parsed fine and was **silently ignored** — unknown keys were tolerated at both levels | `mode` is enumerated; any unrecognised value makes the file unparseable, the same posture `_FLAG_OFF_VALUES` already takes on `"trve"` |
| 10 | A re-affirmation supplied by a scheduled workflow | not hypothetical: `seed-visual-baselines.yml` holds `contents: write`, sets `git config user.name "github-actions[bot]"` by hand, pushes, and has already produced a commit | the re-affirmation is not a repository file. See the Decision |
| 11 | A human-authored commit whose COMMITTER is a bot | measured: **234 of 366** commits already have committer `noreply@github.com` — the ordinary squash-merge path | committer-based detection is unusable here, measured rather than assumed |
| 12 | Git author fields forged | measured: **366 of 366** commits carry no signature (`git log --all --format='%G?'` → `366 N`), and `seed-visual-baselines.yml` literally sets the author strings | `%an`/`%ae` carry zero evidence of humanity. Any design reading them is theatre by construction |
| 13 | A bot comments the affirmation on the alert issue | the watchdog holds `issues: write` and a workflow token, and already comments elsewhere | `user.type` is refused when it is `"Bot"`. Measured on this repo's own alert issue: `gh api repos/:owner/:repo/issues/351/comments` → **11 of 11 are `"type": "Bot"`**. GitHub sets that field; the commenter cannot |
| 14 | A re-affirmation FORWARD-DATED so it never lapses | measured on the pre-change code: `expires_at: 9999-12-31T23:59:59Z` parses and `refuse_undeclared_flag` returns `None` — **the far-future silencer works today** | `created_at` is GitHub's, not the commenter's. A future-dated comment is refused, and there is no field anybody types |
| 15 | A far-future `expires_at` used instead of `standing` | same measurement; ADR-0070 named it as the one indefinite silencer and defended it only by row 7's non-existent review | **re-affirmation closes it for every length at once**: an unattended window lapses in a day whether its expiry is tomorrow or the year 9999 |
| 16 | One affirmation covering every open window | the batch rubber-stamp ADR-0069 rejected | the token quotes the window's own `opened_at`, so one comment attends exactly one window |
| 17 | Genuine human rubber-stamping | unfalsifiable mechanically; ADR-0069 says so of its own ledger | **not solved, and not claimed.** See Consequences |
| 18 | The self-defeating gradient: the lapse fires at 03:00 and the cheap fix is to make it permanent | a 24h cadence lands the deadline at every hour of the day in rotation | `standing` does not exempt re-affirmation, so the gradient does not exist: making it permanent does not make it quiet |
| 19 | Clock skew, non-UTC offsets on a new timestamp | ADR-0070 row 16 refuses to subtract two clocks | every new instant goes through the existing `_parse_instant`: explicit offset required, normalised to UTC |
| 20 | Cron throttling against a 24h cadence | INHERITED from ADR-0070: gaps min 21.7 / median 53.4 / max 129.4 minutes | the worst measured gap is **9%** of the cadence, so lapse detection is comfortable. The alert INSTANT is unpredictable within ~2.2h, which is row 18's mechanism, not a defect |
| 21 | `standing` produces silence indistinguishable from a dead watchdog | the brief's own requirement | `standing` has its own decision value and reports mode, ADR, owner, age and last re-affirmation EVERY cycle |
| 22 | Reading a second endpoint adds a new UNKNOWN alert path in today's steady state | ADR-0070 row 3; every new check is trivially green against `offline_by_config` | judge state is load-bearing ONLY when the posture is live. With the flag off an unreadable `/status` is reported, never alerted — **zero new alerting paths on today's production**, pinned by a test |
| 23 | A new gate that passes with the mechanism absent | rules 6b, 7, 8 | every new behaviour ships a fixture-driven POSITIVE partner; 14 demonstrations, and the mutation table below |

## Decision

### 1. The judge is part of the declaration

Every window carries a REQUIRED `judge` boolean — no default, and a real boolean
(`isinstance(True, int)` is True in Python, so `"true"` and `1` are refused).
The watchdog reads `/status.judge_enabled` on both hosts alongside
`/ready.live_readiness.state`, and compares the two **only when the posture is
live**.

`/status.judge_enabled` does NOT carry the defect that made ADR-0070 reject
`/status.live_execution`. That one is derived (`main.py:984` is
`report.state in ("live",)`, so a flag ON with a refused key reads `false`).
`main.py:1032` is a direct `judge_configured()` call
(`evaluation.py:1814-1827` — a key AND a model id, no probe term), and it is the
SAME predicate the run-path gate uses, so the reported state cannot drift from
the spending behaviour.

The four-way matrix, and what each cell does:

| Live posture | Judge | Verdict | Why |
|---|---|---|---|
| off | off | silent | nothing can spend |
| off | on | **reported, not alerted** | proven inert, but `judge_enabled: true` READS like activity and an operator should be told. This is today's production |
| on, declared, window says `judge: true` | on | silent | sanctioned, and written down |
| on, declared, window says `judge: false` | on | **ALERT** | the cell ADR-0070 got wrong. A second paid subsystem is running and the ledger is under-reporting by its cost |
| on, undeclared | either | alert | ADR-0070's existing behaviour, unchanged |
| on | unreadable | **UNKNOWN → alert** | while live, the judge CAN spend; refusing to guess is the same posture every other unreadable input gets |

**This does not fabricate the policy ADR-0070 deferred.** It does not say the
judge must be off. It says the window must state whether the judge is in it. If
the answer at GA turns out to be "permanently on", every window carries
`"judge": true` and the mechanism costs nothing.

**Stated because it will otherwise be discovered later: no pre-merge gate can
ever see the judge.** `fly.toml` carries no judge configuration at all
(measured: `grep -i judge fly.toml` exits 1) — the judge is governed purely by
Fly secrets. The runtime watchdog is the only place this dimension can bite,
which is an asymmetry with the live flag, not an oversight.

### 2. The escalation channel is withdrawn

See Context. Recorded with its reason so it is not rediscovered as a gap.

### 3. Re-affirmation replaces a maximum window length, and a window has a mode

**No maximum length.** Instead, an ATTENTION CLOCK. It starts at `opened_at` —
opening a window is itself the first act of attention, so a window shorter than
the cadence costs nothing extra — and is reset by a human re-affirmation. Past
`REAFFIRMATION_CADENCE_HOURS` = **24** with no reset, the window stops
sanctioning anything and the watchdog alerts.

The cadence is a REMINDER interval, not a money guardrail: nothing here prices or
bounds spend, and a wrong value self-corrects. Approved by the operator,
2026-08-25.

**The re-affirmation is a comment on a GitHub issue, not a field in this
repository**, and that is forced by measurement. The hard requirement is that
neither the watchdog, nor CI, nor a bot can supply it. A committed
`reaffirmed_at:` fails that requirement HERE — rows 10 to 12 above: no commit is
signed, most commits already carry a bot-shaped committer, and a workflow that
can push already exists and has pushed. Both fields a file-based affirmation
would rest on are self-declared.

A comment rests on two fields GitHub sets and the commenter cannot:

* `user.type` is `"Bot"` for anything posted with a workflow token — **this
  watchdog cannot re-affirm itself**, and 11 of 11 machine comments on issue
  #351 measure it;
* `created_at` is server-set, so there is no timestamp for anybody to
  forward-date.

The window names its `reaffirm_issue`. A comment counts only if it carries
`REAFFIRM live-execution` followed by that window's own `opened_at`.

**`mode` is `time_boxed` or `standing`, required, enumerated.** `time_boxed`
carries `expires_at` — the ADR-0060 shape, unchanged. `standing` has no expiry,
for the steady state, and:

* **removes the deadline and nothing else.** It still needs re-affirming every
  24 hours. This is the single property that keeps it from being a silencer;
* **must cite an ADR that RESOLVES** — one that exists in `docs/adr/`, whose
  `## Status` begins `Accepted`, which carries the marker line (the literal
  `**Authorises:** OPENROUTER_LIVE_EXECUTION_ENABLED`, on a line of its own), and
  which is NOT ADR-0070 or ADR-0071. **No ADR in the tree carries that marker
  today**, and a test keeps it that way, so `standing` cannot be used until
  somebody writes the record that says "we are going live permanently, and here
  is why";
* **does not make the watchdog quiet.** It gets its own decision value,
  `live_within_standing_declaration`, and every cycle prints the ADR, the owner,
  how long it has stood and how long since it was last re-affirmed. A standing
  posture that produced silence would be indistinguishable from a dead watchdog.

What `standing` deliberately DOES change, stated so it is a decision and not a
discovery: **the pre-merge gate goes quiet for it.** ADR-0070 made the expiry a
deadline that turned the required `pytest (Python 3.12)` context red until
somebody acted — "the mechanical form of ADR-0060's revert condition". At GA
there is nothing to revert TO, so that pressure is deliberately removed and
replaced by the runtime attention check, which is the only layer that can see
whether anybody is still watching.

### 4. This is a PRE-GA instrument, and its successor is named — PROSE ONLY

At GA the question this asks stops being the right one. "Is the posture
declared?" is worth asking while live execution is exceptional and each window
is an event somebody can name. Once it is permanent, every cycle answers "yes,
standing, as declared", the signal's information content falls towards zero, and
the daily re-affirmation becomes friction.

Its successor asks **"is spend ANOMALOUS?"** That needs a baseline of normal
production spend, and **no such baseline exists**. None is built here and no
threshold is chosen here. ADR-0070 rejected a spend threshold on the measurement
that the entire #357 exposure was $0.1768 against a $5.00/day ceiling, so any
threshold would have been silent throughout; choosing one now from zero
production data is exactly the move ADR-0060's Decision (1) refused.

Recorded so the next person REPLACES this rather than deleting it for being
noisy. **When the daily re-affirmation starts to feel like theatre, that is the
signal to build the successor.** The friction is not a bug in this design; it is
the thing that should motivate the next one.

## Measured

Every row run by me in this worktree on 2026-08-25 unless marked INHERITED.

| Question | Command | Result |
|---|---|---|
| Base | `git rev-parse origin/main` | `57be5a8`, and production serves the same `build_sha` |
| Baseline of the two posture test files | `uv run pytest tests/unit/test_live_posture_check.py tests/unit/test_live_execution_posture_declaration.py -q --no-cov` | **97 passed** |
| ...after this change | same | **198 passed** |
| ADR-0070's eight-row truth table, before | the real script over `file:` fixtures | all 8 rows as ADR-0070 records |
| ...and after | same harness | **all 8 unchanged**, and now pinned by `test_the_adr_0070_truth_table_still_holds` so nothing can silently move them again |
| Do the NEW behaviours fire? | 14 fixture-driven demonstrations of the real script | **14 of 14** — lapse alerts, fresh is silent, a Bot comment does not re-affirm, a forward-dated one does not, `standing` reports, `standing` still lapses, three bad ADR citations refused, judge-undeclared alerts, judge-declared is silent, judge-on-live-off reports, judge unreadable fails closed while live and stays quiet while off |
| Is any commit signed? | `git log --all --format='%G?' \| sort \| uniq -c` | **366 N** — none |
| Who commits? | `git log --all --format='%ce' \| sort \| uniq -c` | **234 of 366** are `noreply@github.com` |
| Are reviews or signatures required? | `gh api repos/:owner/:repo/branches/main/protection` | `required_approving_review_count: 0`, `required_signatures.enabled: false` |
| Is a comment's author type forgeable? | `gh api repos/:owner/:repo/issues/351/comments` | **11 of 11** `"type": "Bot"` — server-set |
| Workflows, and which can write | `ls .github/workflows/*.yml \| wc -l`; `grep -ln "contents: write"` | **14** total, **1** with `contents: write` (`seed-visual-baselines.yml`), **1** naming the declaration file (the watchdog, `contents: read`) — and they are not the same file |
| Can an ADR citation be text-checked? | `grep -rl 'OPENROUTER_LIVE_EXECUTION_ENABLED' docs/adr/` | **6 of 68**, two of which authorise nothing — so no |
| Does any ADR carry the authorisation marker? | `authorising_adrs(docs/adr)` over the real tree | **empty**, over 68 records — pinned, with a fixture partner proving the function does find a marked one |
| What does production report? | `curl -s https://quorum-ai.fly.dev/status` | `live_execution: false`, `judge_enabled: **true**` |
| Judge config in `fly.toml`? | `grep -i judge fly.toml` | **exit 1** — none, so no pre-merge gate can see it |
| Judge inertness pinned? | `uv run pytest tests/integration/test_judge_never_spends_on_a_run_that_must_not_spend.py` | **9 passed** |
| Are the tests hermetic? | the suite's wall clock | an early revision defaulted `main`'s `/status` probe to production and the suite took **103s**; with every URL a `file:` fixture it is **2.8s**. No test touches production |

**Live execution was never switched on to test any of this. Every firing path is
driven by a `file:` fixture. No paid provider call was made, and `fly.toml` still
reads `OPENROUTER_LIVE_EXECUTION_ENABLED = "false"`.**

## Rejected alternatives

1. **A maximum declared-window length** (ADR-0070 open decision 1). Rejected on
   the evidence, not the merits: the failure was ~3 days and the legitimate need
   is ~7, so no number separates them.
2. **A `reaffirmed_at` field in the declaration file.** The obvious design, and
   auditable in a diff. Rejected because in THIS repository it does not satisfy
   the requirement it exists for: rows 10 to 12 above. A workflow with
   `contents: write` already exists and has pushed; no commit is signed; most
   commits already have a bot committer. Both the actor and the instant would be
   self-declared.
3. **Reading git history to attribute the affirmation.** Rejected twice over:
   the identity fields carry no evidence (row 12), and the watchdog's checkout
   sets no `fetch-depth`, so it is shallow and cannot run `git log` on a path.
4. **`standing` exempt from re-affirmation.** Rejected: it is precisely the
   permanent-silence mechanism ADR-0069 refused, and it would create the
   gradient in row 18 where the cheapest way to stop a 03:00 alarm is to make it
   permanent.
5. **Capping `time_boxed` at the cadence, forcing anything longer through
   `standing`.** Rejected: it is a maximum window length wearing a different
   hat, and it would push #105's legitimate week through the ADR-citation path
   for no benefit. Re-affirmation already bounds an unattended window at 24h
   regardless of its declared length.
6. **Alerting when the judge is on while live execution is off.** Rejected: it
   is provably inert there, so the alert would be red on today's production from
   the day it shipped — failure mode 9 by construction. It REPORTS instead.
7. **A judge policy** ("the judge must be off outside a window"). Rejected as
   fabrication: nobody has made that decision, and ADR-0070 was right to refuse
   to invent it. The window states a fact; it does not impose a rule.
8. **Building the spend-anomaly successor now.** Rejected: no spend baseline
   exists, and picking a threshold from zero production data is the move
   ADR-0060's Decision (1) refused. Named in prose so it is built deliberately.
9. **An escalation channel above the issue** (ADR-0070 open decision 3).
   Withdrawn — see Context.

## Consequences

- Opening a live window now costs two more fields (`mode`, `judge`) and, past 24
  hours, a daily comment from a person. The short attended session — the common
  case — costs nothing extra, because `opened_at` is the first act of attention.
- **Issue #105's seven-day log collection is now possible without either
  silencing the watchdog or picking a number that permits #357.** It costs six
  re-affirmations.
- **The far-future-expiry silencer is closed.** ADR-0070 named it as the only way
  to silence the mechanism indefinitely and defended it by diff review, which
  this record measures as non-existent here. An unattended window now lapses in a
  day at any declared length.
- **A `standing` window makes the pre-merge gate permanently quiet.** That is the
  intended trade (Decision 3) and it is the sharpest edge in this record. The
  runtime attention check replaces the pressure; if the watchdog's schedule is
  disabled (ADR-0070 failure mode 7, still UNVERIFIED) a standing posture has no
  layer watching it at all.
- **Rubber-stamping is not solved.** A person can paste the token every morning
  without reading anything. The mechanism establishes that a human acted inside
  the cadence, never that judgement was exercised. Accepted, not fixed.
- **Re-affirmation depends on the GitHub API.** While a live posture stands
  inside a window that names an issue, an unreadable API is UNKNOWN and alerts.
  That is a new dependency, and it is inert today: with live execution off the
  script makes zero re-affirmation reads.
- ADR-0070's Consequences line *"`judge_enabled` is `true` in production today
  and remains unwatched"* is now stale: it is watched, and the reason it was
  never urgent is recorded above.
- `make diff-cover` reports **green having measured nothing** on this diff, as it
  did on ADR-0070's: `--cov=src` sees no `scripts/`, `tests/`, `configs/`,
  `.github/` or `docs/` change. That is not evidence of anything, and it is
  written down rather than cited as a pass. This change's correctness rests on
  the `pytest (Python 3.12)` lane and on the mutation table below.

## The bite table

Each mutation `cp` aside, applied, run, restored from the copy and confirmed with
`diff -q` — never `git checkout`. Baseline for every row: **198 passed**.

| # | Mutation | Result |
|---|---|---|
| N1 | the `Bot` filter in `parse_reaffirmations` is removed | see the table produced by the run recorded in the pull request |
| N2 | a future `created_at` is honoured | as above |
| N3 | `standing` is exempted from the attention check | as above |
| N4 | the attention check is removed entirely | as above |
| N5 | an unrecognised `mode` is ignored rather than refused | as above |
| N6 | `judge` acquires a default of False | as above |
| N7 | the judge comparison is deleted | as above |
| N8 | judge-on-while-live-off starts alerting | as above |
| N9 | an unreadable judge state defaults to False | as above |
| N10 | `MECHANISM_OWN_ADRS` is emptied | as above |
| N11 | the `Accepted` requirement on a cited ADR is dropped | as above |
| N12 | the authorisation marker is matched anywhere rather than on its own line | as above |
| N13 | an unreadable re-affirmation issue is read as "no re-affirmations" | as above |
| N14 | the attention clock stops starting at `opened_at` | as above |
| N15 | the watchdog is granted `contents: write` | as above |

## Related

- [ADR-0070](0070-a-money-spending-posture-is-declared-before-it-is-switched-on.md) — the mechanism this revises. Not superseded.
- [ADR-0069](0069-an-equivalent-mutant-is-removed-not-recorded.md) — the rejected exclusion ledger whose abuse-path analysis `standing` is answerable to.
- [ADR-0060](0060-live-execution-is-switched-on-only-to-collect-a-sample.md) — the three-day window, and the refusal to pick a number from one sample.
- [ADR-0013](0013-a-paid-subsystem-may-not-be-enabled-invisibly.md) — the judge as a paid subsystem, and why its GET-path spend reaches no ledger.
- Issues #357 (the gap), #351 (the CI fault that stretched the window), #105 (the seven days this makes possible), #268.
