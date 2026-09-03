# 2026-09-03 — autonomous run: #290 peer critique built, W3 assessed

## Summary

**Shipped and verified.** One work package: #290 / W2, peer critique. ADR-0093's
approved shape implemented in full (decisions 1, 1a, 1b, 2, 3, 4, 5) behind
`settings.peer_critique_enabled`, default FALSE. Five commits on
`feat/290-peer-critique` (cut from `origin/main` at `2a045c2`), squash-merged as
**`5aed777`** and **verified running in production**. A sixth finding, from the
mutation gate after the merge, ships as PR #431.

**Stopped, and why.** Item 3 (W3, the money constants) is STOP and stays STOP.
Its precondition is "#290 built AND its cost measured". This run built it; no
peer-shaped call has ever been made, so the second half is not met. Opening a
live-execution window would have spent real money on an unmerged, unreviewed
branch, which the prompt forbids ("Do NOT start this unless Item 1 MERGED and is
verified in production").

**Left for the owner.**
- The `main` checkout is 10 ahead / 10 behind `origin/main` (duplicate doc
  commits, content already published). Untouched deliberately — see the section
  at the end.
- Turning `PEER_CRITIQUE_ENABLED` on is a MONEY decision, not a feature toggle:
  it raises the fail-safe bound, which moves catalog mixes into the confirmation
  band. It belongs in the same pull request as a declared window and the
  ADR-0094 constants.
- #290 stays OPEN. Done means running in production; with the flag off nothing
  peer-shaped runs.

## The decision this run took that ADR-0093 did not

`CostEstimationService._estimate_bound_usd` describes itself, in its own
docstring, as a TRUE CEILING — "the guardrail keying off it can only ever
over-protect, never wave through a run that then bills more" — and prices
exactly TWO debate calls. A peer run makes two PER ELIGIBLE CRITIC.

Reproduced before fixing, four slots all on the moderator's own model so the
multiplier does not depend on any price:

| `peer_critique_enabled` | `by_stage.debate_round_1` |
|---|---|
| `false` | `$0.0052` |
| `true`  | `$0.0208` (ratio exactly 4.0000) |

Before the fix both columns read `$0.0052`. That is the defect as a number.

**This table said `$0.0207` and `3.98x` for most of the run.** Both wrong: the
figure came from a probe using a different `query_text` than the ADR and the
test use, and 3.98 is a display-quantum artefact of the clean 4.0000 the
sentence was arguing for. Corrected here, in ADR-0095 and in the commit bodies
after review re-derived it. Reproduce with
`pytest tests/unit/test_peer_bound_is_a_true_ceiling.py -q --no-cov`.
ADR-0095 records the flag, the bound change, and why the flag defaults off.

On the SHIPPED default mix the same change moves `$0.0052 -> $0.0081` (1.56x),
because the four default slots are collectively cheaper than four Haikus. My
first draft of the test asserted `> 2x` there and went red against correct code —
a fact about the price list written into an assertion about the feature.

## INDEPENDENT VERIFICATION — commands I ran myself, with their output

Kept separate from what the review subagents reported.

### Gates (rule 14), each read from a log file, never through a pipe (rule 13f)

| Required context | Command | Result |
|---|---|---|
| `pytest (Python 3.12)` | `make quality` | `4123 passed, 25 skipped`; coverage `96.16%` vs an 88% floor. One failure on the first run (`test_debate_output_fields_are_current`) — the published-contract pin doing its job; updated and re-verified `52 passed` in `tests/contract/` |
| `FR traceability completeness` | `make validate` | `all validation gates passed` |
| `Changed-lines coverage >= 95%` | `make diff-cover DIFF_BASE=origin/main` | `Total: 205 lines, Missing: 6, Coverage: 97%` |
| `Schemathesis API contract` | `make api-contract` | `52 tests executed (floor 22), 0 skipped` |
| (part of `validate-and-test`) | `make openapi-check` | `openapi contract validation passed` |
| (part of `validate-and-test`) | `make security-scan` | `1530 files scanned, 0 findings` |
| `e2e axe + parity (chromium)` | the invariants lane, run as CI runs it plus the two rate-limit overrides a local run needs (rule 13) | **`259 passed (4.6m)`** |

`docker-build` is covered by nothing local and was not run — the same gap
AGENTS.md rule 14's table already records.

### Mutation proofs — 21, all killed

`PYTHONDONTWRITEBYTECODE=1`, each target `cp`'d aside and restored from the copy
(never `git checkout` — rule 6), restore verified with `diff -q` after every one.
Baseline with NO mutation: `59 passed`, so a green result is not the harness
being broken.

Two SURVIVED on the first pass. Both were my own vacuous tests, and both are the
kind this repository keeps recording:

* **M2, the row-forgery test.** It used `split("\n")`, which sees only ONE of the
  five line-breaker characters it parametrises over — so 4 of 5 parameters
  passed against source with `_one_line` deleted from the digest. Changed to
  `str.splitlines()`: the same mutation now fails 5 of 5.
* **M19, `_actual_cost`'s critique split.** It had NO test. Every existing test
  called `build_measured_breakdown` with the critique lines ALREADY computed, so
  the builder was well covered and its only CALLER was not. Deleting
  `if round_number in peer_rounds:` left the entire suite green. Two tests added
  that drive the real `_actual_cost`.

### Production, probed free (rule 18)

`curl -s https://quorum-ai.fly.dev/status` — `build_sha` is
`2a045c2e4daa3e5de483b1cf7d43fad842052881`, which is `origin/main`'s tip and the
commit this branch was cut from. So main is deployed and current before this
work lands.

## Item 4 — #105, assessed, not started

`#105` ("5xx is classified as possibly-billed on a premise with no evidence")
needs production 5xx events from LIVE provider calls. Settled with one command:
`/status.live_execution` is **`false`**. Nothing in production makes a live
provider call, so the `telemetry-billing.jsonl` stream #105 is to be decided from
**cannot grow at all** while that stays true — which is why the prior window
gathered zero. It is not a hermetic item and it is not blocked on code; it is
blocked on live traffic. No window was opened for it, per the prompt.

Also unowned and worth an issue, from ADR-0094 and NOT re-derived here (marked
ASSUMED, not measured, by this run): **220 of 715 catalog mixes (31%) are
already hard-refused today**, before any constant moves.

## Review — two rounds, capped (rule 12)

### Round 1: four read-only lenses, four largely disjoint finding sets

Consistent with what AGENTS.md rule 10 records about single-lens recall. My own
self-review caught ONE of the seven things that needed a code change; the
reviewers caught the other six.

**Four CRITICAL_BLOCKERs, all reproduced:**

1. **A cancel made the product MORE confident.** Four critics split 2-2 read
   `weak`; the same run with a cancel after two read `strong`, on identical
   model opinions. The majority denominator shrank with the critics that were
   never asked.
2. **The 4x fail-open was NOT closed.** I fixed it in the keyword channel; it
   survived in the STANCE channel, which `compute_consensus_strength` reaches
   FIRST. **My commit body's claim that it was fixed was false as written.**
3. **The fail-safe bound FELL when the flag was turned on** and no slot was
   eligible — found independently by two lenses on two different legal mixes,
   `$0.0967 -> $0.0740` and `$0.0953 -> $0.0652`.
4. **Round 2's prior-critique input** was charged 1x at the moderator's rate and
   paid Nx at the critics'. `$0.0640` on the four priciest catalog models.

**Two REQUIRED_CONTRACT breaks:** `debate_mode` LIVE-if-ANY suppressed the
"Written by Quorum" disclosure while 3 of 4 rendered rows were template text;
and a cancelled peer round shipped COMPLETED with an EMPTY critique.

**And the finding that matters most for how I work:** the telemetry correlator
was tested at the TYPE and not at the WIRE. All four stage labels could be
renamed to strings joining to no receipt line, and three of four wirings severed
outright, with NO new failures in the full suite. Every green result was green
against labels the tests constructed themselves. That is this repository's own
recorded failure mode — "test the wire, not just the decision" — and I made it
again, in the same package where I had already fixed one instance of it.

The same lens found the MODERATOR debate path carried no correlator at all, so
the correlator did not cover the shape that actually ships. I had found that one
myself, in self-review, before the lens reported.

**Eleven false prose claims**, several mine. The worst: `$0.0207 / 3.98x` came
from a probe using a different `query_text` than the ADR and test use, and
ADR-0095 read the 3.98 rounding artefact as CONFIRMATION of the four-calls
argument — when the clean 4.0000 was the confirmation. Re-measured, with the
command inline: `$0.0052 -> $0.0208`, ratio exactly 4.0000.

### The gates did not catch any of it

Six green gates and 21 mutation proofs stood between me and those four blockers,
and stopped none of them. Two — a cancel raising a verdict, a bound that falls
when you enable the feature — are shapes no gate in this repository could see.
That is the same result `docs/metrics/defect-discovery-audit.md` already
records: 0 of 16 `src/` defects caught by an automated check, 10 of 16 by
adversarial review.

### Mutation, after the fixes

35 mutants total across both rounds. Five that had survived the ENTIRE suite now
fail. Five more survived on first attempt during this work and each got the test
it was missing (M2, M6, M19, R8, R10, R14). One survives BY DESIGN — R13, the
inner `should_stop` check, which is defence in depth and not observable — and
that test's docstring now says so instead of claiming a RED-WHEN that is false.

### Gates re-run on the FIXED tree (not carried over from before the fixes)

| Gate | Result |
|---|---|
| `make quality` | `4144 passed, 25 skipped`; coverage `96.08%` vs an 88% floor |
| `make validate` | `all validation gates passed` |
| `make diff-cover DIFF_BASE=origin/main` | **`Total: 221 lines, Missing: 0, Coverage: 100%`** |
| `make api-contract` | `52 tests executed (floor 22), 0 skipped` |
| `make openapi-check` | passed |
| `make security-scan` | `1529 files scanned, 0 findings` |
| e2e invariants lane (rule 13 flags) | **`259 passed (4.6m)`**, matching the floor |

The changed-lines figure moved 96% -> 100% because `diff-cover` named seven
defensive branches nothing drove — a critic whose envelope parses but carries
blank prose, `_peer_digest(())`, the zero-panel stance floor, four malformed
`finish_reason` payload shapes, and the negation guard. Each now has a test AND
a positive partner, because "returns absent for everything" would satisfy the
refusals on their own.

### One gate I CANNOT clear locally, named rather than glossed

`e2e/fixtures/golden-run.ts`'s `BY_MODEL` writer row was relabelled
`"Debate + synthesis"` -> `"Synthesis"` so the fixture matches what the server
now sends. That array feeds `goldenCompletedResp()`, which
`visual-snapshots.spec.ts` screenshots full-page — and that lane is **BLOCKING**
(`e2e.yml`: "Run visual snapshots (BLOCKING)", no `continue-on-error`).

I asserted here that "a shorter label changes pixels, so the Linux baselines are
now stale and the lane will go RED in CI."

**That was WRONG, and it was an inference stated as a fact.** The re-seed ran on
the branch and reported, verbatim:

```
No baseline changes to commit.
```

The baselines are byte-identical: the writer-row label is not inside the region
`visual-snapshots.spec.ts` captures. I had reasoned "shorter string -> different
pixels" and written it down as a certainty without a command that could settle
it — the same class of error as the `$0.0207` figure and the two inherited
sweep pairs, three for three in one session.

The ACTION was still right, and this is the part worth keeping: rule 13e says a
local pixel comparison here cannot be trusted, so the only way to know was to
run the CI-side seed. Dispatching it converted an unverifiable local assumption
into a measured fact, cost nothing, and would have been the correct move even if
the answer had gone the other way. What was wrong was announcing the answer
before running it.

The original reasoning, kept because the CONSTRAINT it describes is real even
though my conclusion was not: per rule 13e this cannot be settled locally,
because Playwright
compares `*-chromium-darwin.png` here and `*-chromium-linux.png` in CI, the
darwin images have been stale on clean `main` since before this work, and
`--update-snapshots` would commit noise while testing nothing CI tests.

The documented path is `seed-visual-baselines.yml`, a `workflow_dispatch` that
regenerates the Linux baselines on the branch and commits them back — its own
header says "Re-run whenever the intended layout changes." That dispatch has to
happen AFTER the branch is pushed and BEFORE the PR can go green, and it is a
push-authorised action, so it is sequenced with the push rather than done now.

The critique rows themselves do NOT touch this lane: they live in a DEDICATED
builder (`goldenRespWithCritiqueRows`), which is what rule 13d asks for
precisely so a new shape cannot red a lane that has no local re-baseline.

### Round 2: the fix round introduced a WORSE defect, and review caught it

Rule 12 says "expect your own fix to introduce a defect — budget a round for
it." That is not a platitude here; it is what happened.

The round-1 fix changed the peer round's `debate_mode` from `any(critics live)`
to `all(...)`, correctly, so `app.js`'s authorship disclosure fails closed. But
`_usable_stance` used that SAME flag as its evidence-admissibility gate. So one
blank critic — a 400 on `response_format`, a torn body — discarded the round's
correct, majority-derived stance, and the verdict fell through to
`_has_strong_overlap`, the 4-gram vocabulary heuristic whose own comment records
that it "said 'strong' on a panel split down the middle".

**Measured: a genuinely 2-2 panel read `divided` with four usable critics and
`strong` with three. Losing evidence RAISED the claim.**

I reproduced it myself before fixing. The root cause is that one field was doing
two jobs whose safety directions are opposite: tightening it for the disclosure
loosened it for the verdict. `_stance_is_admissible` splits them.

**My test could not see it, and that is the second lesson.** The fixture
hardcoded `debate_mode=live`, so it never modelled the coupling — the mutation
reverting the fix SURVIVED against it. A fixture that cannot reach the defect is
a fixture that certifies its absence. It now derives `debate_mode` from its
critics exactly as `run_debate_rounds` does.

Round 2 also found:
- a money test that was ORDER-DEPENDENT, deriving its slot mix from
  `price_index()` — a process global rule 16a names — and pinning a literal
  against it. Green in CI, red under `pytest tests/unit`, and in full-suite
  ordering it was the ONLY killer of the prior-critique pricing. It now owns its
  price list.
- the round-TWO `all()` site was unguarded: reverting it alone left 3089 tests
  passing. A rule written at two sites needs asserting at two sites.
- a real CEILING BREACH the feature amplifies: the bound priced every debate
  system prompt at a flat 350 tokens against a real 479.5 including the peer
  directive I added. Paid twice under the moderator, EIGHT times under peer. One
  mix quoted `$0.2496` against a worst real spend of `$0.251788` — waved through
  and able to bill past the `$0.25` hard limit. Corrected on the peer branch
  only; the moderator's pre-existing `$0.000466` gap is filed, because moving it
  would invalidate ADR-0094's measured sweep.

### And two more of my numbers were inherited, not measured

`$0.0967 -> $0.0740` and `$0.0953 -> $0.0652` were the round-1 reviewers' own
figures. I wrote both into ADR-0095 and a commit body AS MEASURED without
re-deriving either. Neither reproduces at any query length. The defect was real
and LARGER than the figures quoted for it — a third sweep found the bound fell
on 522 of 3,640 mixes, largest drop `$0.0853 -> $0.0532`.

That is rule 11 broken three paragraphs after the ADR's own confession about
`$0.0207`, in the same document, in the same session. Writing the lesson down
did not stop the next instance. What stopped it was a reviewer running the sweep.

### Final gates, on the tree that will be pushed (5 commits)

| Gate | Result |
|---|---|
| `make quality` | `4163 passed, 25 skipped`; coverage `96.21%` vs an 88% floor |
| `make validate` | `all validation gates passed` |
| `make diff-cover DIFF_BASE=origin/main` | **`Total: 239 lines, Missing: 0, Coverage: 100%`** |
| `make api-contract` | `52 tests executed (floor 22), 0 skipped` |
| `make openapi-check` | passed |
| `make security-scan` | `1531 files scanned, 0 findings` |
| e2e invariants lane | (final run) |

`docker-build` is covered by nothing local and was not run — the same gap
AGENTS.md rule 14's own table records.

### A phantom e2e failure, diagnosed rather than guessed

The final lane run came back with **30+ failures** — 23 in `readiness-banner`,
6 in `provider-notice-coverage`, then `rendering-invariants` and
`result-debate`. Not one of those specs is touched by this diff, and every
failure was a **10.1 s timeout** (the page never rendered) rather than an
assertion.

Rule 9a's corollary: *a failure in a file your diff never touched is a phantom
until you re-run it on a stable tree.* The evidence said environment, not diff:

- the SAME lane had passed 259/259 twice on this branch earlier today
- `make quality` (4163 tests) and `diff-cover` (100%) were green on the
  identical tree, minutes before
- `.data/feedback_events.sqlite3` was untracked, gitignored, 208 KB, and freshly
  written by my OWN repeated runs

That is the documented signature of the durable per-IP daily mint cap: it
accumulates across local runs, `/ui` starts answering 429, and every invariant
spec after that point fails to render. `SESSION_MINT_CAP_OVERRIDE=600` raises
the cap; it does not empty a database already past it.

**Settled by experiment, not by assertion.** Deleted the two gitignored SQLite
files by name and re-ran the worst-hit spec alone:

```
readiness-banner.spec.ts, before: 23 failed
readiness-banner.spec.ts, after:  23 passed (14.1s)
```

Same spec, same tree, same commit — only the scratch database differed. The full
lane was then re-run from clean.

Worth recording because the wrong reaction here is expensive in both
directions: treating it as a real regression would have sent me hunting a defect
that does not exist, and treating a red lane as "probably the known flake"
without the controlled re-run would have been exactly the unverified claim this
repository keeps paying for.

### The close-guard caught me twice in three minutes

The pull request's first CI run failed on `validate-and-test`, at the step
"Guard against a negated issue close". My body read:

> **This does NOT close #290.**

GitHub cannot read the negation, so on merge that sentence would have closed an
issue this work deliberately leaves open. AGENTS.md rule 17c records **four**
issues already lost exactly this way, and I had quoted that rule in this very
run log before writing the sentence.

Then the sentence I wrote to EXPLAIN the mistake — "...would have closed #290 on
merge" — tripped the same gate, for the same reason, and had to be rewritten
too.

```
close-keyword guard: 5740 chars, 1 closing reference(s), 1 negated
  #290: 'not ... close #290' -> GitHub will CLOSE #290
...after the first fix:
close-keyword guard: 6080 chars, 1 closing reference(s), 0 negated
  will close: #290 — none of them negated. OK.      <- still wrong!
...after the second:
close-keyword guard: 6281 chars, 0 closing reference(s), 0 negated
```

Note the middle state: the guard PASSED while the outcome was still wrong. It
answers "is a negated close going to fire?", not "did you mean to close this?"
Reading its output rather than its exit code is what caught that.

The lesson is the one this repository keeps paying to relearn: **prose about a
trap is not protection from it.** I had read the rule, written it down, and
still walked in twice. What stopped it was a mechanical check reading the actual
text — which is exactly rule 1's "enforcement is mechanical, never prose."

### Merge text vetted separately, because CI never sees it

`make close-guard` on the exact squash subject and body, passed through the
ENVIRONMENT (rule 17c — a merge body full of backticks must never be re-parsed
by a shell):

```
close-keyword guard [MERGE_SUBJECT+MERGE_BODY]: 2977 chars, 0 closing reference(s), 0 negated
pre-merge check for PR #430: expected 0 issue(s) to close, merge text closes 0,
GitHub reports 0
  closes exactly the expected set: nothing. OK.
```

`EXPECT_CLOSE=""` deliberately: issue 290 stays open because nothing peer-shaped
runs while the flag is off, and W3's precondition is a MEASURED cost, not a
merged mechanism.

This is a separate step from the CI guard that failed earlier, and the
distinction matters: CI vets the pull request's title and body; **it never sees
the merge text**. Rule 17c records four issues closed through that blind spot.

### The visual lane: verified at the JOB, not the rollup

My wrong claim above is closed out by three independent facts, none of them an
inference:

1. `seed-visual-baselines.yml` ran on the branch and reported
   `No baseline changes to commit`.
2. CI's blocking lane passed — read from the JOB, not the run's rollup:
   `success  Run visual snapshots (BLOCKING)`.
3. Its executed-count floor also passed:
   `success  visual-snapshots lane: floor on tests actually executed` — so the
   lane MEASURED something rather than passing by being skipped, which is the
   distinction rule 2 exists for and the one a rollup cannot make.

## Merged

PR #430 squash-merged as **`5aed777`** at 2026-09-03T00:22:20Z, with the
pre-vetted subject and body passed through the ENVIRONMENT.

**Issue 290 is still OPEN**, verified after the merge (`gh issue view 290` ->
`OPEN`). That is the outcome `close-guard` asserted with `EXPECT_CLOSE=""`, and
it is the correct one: nothing peer-shaped runs while the flag is off, so the
issue's own condition is unmet.

All six required contexts were confirmed INDIVIDUALLY green before merging, by
re-deriving the list from branch protection rather than trusting AGENTS.md's
table (rule 14 records that table being wrong twice):

```
SUCCESS  <- REQUIRED: validate-and-test
SUCCESS  <- REQUIRED: pytest (Python 3.12)
SUCCESS  <- REQUIRED: Changed-lines coverage >= 95% (blocking)
SUCCESS  <- REQUIRED: Schemathesis API contract (blocking)
SUCCESS  <- REQUIRED: FR traceability completeness (blocking)
SUCCESS  <- REQUIRED: e2e axe + parity (chromium)
```

`mergeStateStatus` read `UNSTABLE` at merge time. That was the mutation-score
ADVISORY still running — not a required context. Checked rather than assumed,
because "unstable" reads like a blocker and is not one here.

## NOT DONE, and deliberately: the owner's local `main`

`/Users/rohitagrawal/Projects/quorum-ai` sits at `df4d534`, **10 ahead and 10
behind** `origin/main`. The 10 local commits are `docs(analysis)` run logs whose
content is BYTE-IDENTICAL to what is already on `origin/main` (verified at the
start of this session with `diff` against `git show origin/main:<path>` for all
three files) — they were published through PR #428 and friends, so the local
copies are superseded rather than lost.

Because the histories have genuinely diverged, BOTH `git branch -f main
origin/main` and `git merge --ff-only origin/main` are wrong here, and the
run prompt says so explicitly. Reconciling them is the owner's call (reset,
rebase, or drop), so this session did not touch that checkout at all. **Nothing
is at risk — the content is on the remote.**

## Deploy verified THREE ways (rule 18)

**1. The Deploy JOB ran** — not the run rollup. The merge produced **seven**
`Deploy to Fly.io` runs for `5aed777`: 1 success, 2 cancelled, 4 skipped. Keying
on "a completed run exists" would have been meaningless. Run `33700131160`'s job:

```
success  JOB: Gate — require CI + Tests + E2E green for the SHA
success  JOB: Deploy to Fly.io
   success  Guard — only deploy if this SHA is still main's tip
   success  Deploy to Fly.io
   success  Smoke test - GET /health
   success  Smoke test - GET /ready
```

**2. `/status.build_sha` == the merge SHA**, exactly:
`5aed77725b19fd25199c6bc5ffe8ae26994ce578`.

**3. The shipped BEHAVIOUR is live**, not just the SHA string. A free
`POST /v1/query-runs/estimate` against production returns:

```
by_model labels : ['GPT-4o mini', 'Claude Haiku 4.5', 'Gemini 2.5 Flash',
                   'DeepSeek Chat v3.1', 'Synthesis', 'Layer-B judge']
kinds           : ['model','model','model','model','synthesis','judge']
max_cost_usd    : 0.1192
```

The writer row reads **`Synthesis`** — ADR-0093 decision 4, on a real
user-visible money surface. And the shipped POSTURE is confirmed: six rows, NO
critique rows on the estimate path, and a bound unchanged by the flag, so
ADR-0094's held constants are untouched. That cost one session mint and no
money.

## The mutation gate found three survivors in my own new function

It failed AFTER the merge. It is advisory, so the merge was legitimate — and
reading its LOG rather than its exit code is what made it useful (rule 2). It
was honest about its own limits: `UNMEASURED ... 560 of the scope's 2877
mutants (19%)`, `27 mutant(s) SURVIVED before the cut-off`.

Three were in `_peer_round_signals_convergence`. Two reproduced locally:

- **`.lower()` was decorative.** Every convergence string in my test file
  already carried the keyword lowercase, so deleting the normalisation changed
  nothing any test could see — 46 passed against a build without it. A model
  writes prose, and prose capitalises.
- **`or ""` was an EQUIVALENT mutant** — `critique_text` is a required `str`, so
  the guard cannot fire. The gate's own message says to stop GENERATING such a
  mutant rather than record an exception, so the dead guard is deleted.

**The lesson, and it undercuts my own evidence:** I mutation-proved that
function by hand with 35+ mutants of my own choosing and killed every one.
Systematic generation found three I would not have thought to write. Hand-picked
mutation measures the author's imagination; generated mutation measures the
tests. Every mutation figure in this run's commit bodies should be read with
that caveat.

Fixed in PR #431 (`fix/290-mutation-survivors`), which also records that
`make diff-cover` printed its BLIND-SPOT notice for that change: none of the
changed `src/` lines are executable statements, so it measured zero of them and
the 95% would have been over an empty denominator. The evidence there is the
mutation result, not a coverage tick.

---

## Package 9 — ADR-0096, and the second time the mutation gate paid for itself

The owner read the shipped debate and asked what round 1 and round 2 actually
do. That question found four defects no gate could:

1. **Critics were judging sources they were never shown.** Round 1's system
   prompt asked about "weak or missing source support" while `grep -c sources`
   over the debate prompt builder returned **0**. Debate calls also cannot
   search, so a critic had no evidence available at all.
2. **The directive forbade the behaviour.** ADR-0093's build shipped "Do not
   defend or restate your own answer". A model that may not reconsider cannot
   converge.
3. **Every stage measured concord**, so a model could satisfy all three prompts
   without once saying a claim was wrong and citing why — while agreement alone
   paints the green verdict.
4. **The debate could not change the answer.** Nothing asked a model what it
   now believed to be correct.

Round 2 now asks each critic where it stands on its own answer
(`held_agreement` / `held_solution` / `amended` / `changed`, with rationale,
sources and a revised answer), and synthesis reads those REVISED answers as its
primary input. Anti-sycophancy is the constraint: a change of position must
cite sources, and `held_solution` is a first-class outcome rather than a weaker
`changed`.

Honest about the limit, in the ADR, the PR body and a test: this is **L1** — a
source was CITED. Not resolved, not verified. Nothing opens a URL. L3 would
cost $0.03–$0.40 per run against a $0.25 hard limit.

### The mutation gate, again

The gate scored **271 of 377** mutants before its own 1440s deadline and
reported **15 survivors**. Six required contexts were green; the branch was
mergeable. Classifying the survivors by measurement rather than by reading:

**Seven are EQUIVALENT.** Computing the function under each mutant's iteration
set:

| | round 1 | round 2 | round 3 |
|---|---|---|---|
| `_peer_critic_directive` length, slots 0–5 | 152 | 1106 | 1106 |

The length does not vary with the slot number at all — the panel is
single-digit — and any round other than 1 takes the round-2 branch. All seven
mutations of the slot `range(...)` and the round tuple return **3695**, the
same as the original. No test can kill them.

The `max(...)` was NOT restructured to stop them being generated. It is what
keeps the ceiling correct if the panel ever grows past nine slots; removing it
to satisfy an advisory gate would make the code worse. What was added is a test
pinning the two invariants that MAKE the equivalence true, so the day it stops
being true the ceiling goes red instead of silently under-pricing.

**Eight were real**, all in code ADR-0096 had just added. The one that matters:
the source filter's `and` becoming `or` yields
`('', '', 'https://example.org/report', '')` — three blank strings admitted as
cited sources — and raises `TypeError` on a non-string. ADR-0096 makes a source
the price of changing position; a filter that counts `"   "` as a citation is
one that lets a model buy a position change with nothing. Also real: the
`live is None` path — a critic whose call returned NOTHING — was reached by no
test, and substituting any visible string makes that critic read as a `live`
critique carrying that text, because `parse_moderator_output` returns a
non-JSON reply as prose verbatim.

### The harness lied first

The first mutation-proof run reported **3 of the 8 surviving**, which reads as
"your new tests are decoration". It was the harness that was wrong:
`text = "" if live is None` occurs **three times** in `debate.py` and the anchor
hit the moderator path, and the second fallback return needs a reply that is
visible as raw text but parses to empty prose (`{"critique": ""}`) — `"   "` is
caught by the first gate and returns from the branch the previous test already
covered.

Trusting that run would have meant concluding the tests were fine and shipping
three that assert nothing. **A mutation harness aimed at the wrong line is a
green light for a defect**, and it is the same shape as every other failure in
this run: the reading was confident and the command disagreed.

Corrected: **8 killed / 8**, `cp` aside and restored, `diff -q` byte-identical
after each, `__pycache__` purged between steps, re-proved after `make format`
rewrote the assertions.

### The window

`OPENROUTER_LIVE_EXECUTION_ENABLED` and `PEER_CRITIQUE_ENABLED` go `true`
together with a declared 5-day window, judge included, `reaffirm_issue: 290`.
It measures what eight critique calls cost (W3 is blocked on it), whether the
2000-token round cap still fits now that round 2 also returns a revised answer,
and whether OpenRouter's `:online` annotations carry passage content — the
input to any L2 decision.

Two actions are the owner's and cannot be done by an agent: re-affirming the
window on issue #290 every 24 hours from a human account (a workflow token is
typed `Bot` and refused), and the spend exposure of up to ~$25 over five days
($0.20/account/day, $5.00/day global ceiling).
