# Major-issues batch — one integration branch, one final merge

> **HOW TO USE THIS FILE.** Paste this into a fresh chat to start:
> "Read `MAJOR-ISSUES-BATCH-ULTRACODE-PROMPT.md` in the repo root and execute
> it end to end, autonomously, overnight. I have pre-authorized push / PR /
> merge into the integration branch, per §1. Do not wait for me — I will not
> be available. Follow §5's stuck-issue rule instead of stalling. The one
> exception is §8.4a: stop there and wait for me — do not merge to `main`
> without it."
>
> **Expect this run to end in one of two states by morning, not always a
> finished merge:** either it completed §8 in full (rare, requires you
> having been reachable to run `/code-review ultra`), or — far more likely —
> it stops at §8.4a with the integration branch green, reviewed, and waiting
> for you to run one command and say go.
>
> **Written:** 2026-08-03, immediately after a full open-issue verification
> pass (28 issues, each confirmed by execution — grep, tests, `gh run view`,
> not by trusting the issue text). That verification is why the queue below
> is ordered the way it is and why some issues carry a pre-decided policy
> instead of an open question.
>
> **Anchor — written at `3032282`.** That commit is in the past and cannot
> change. To see everything since:
> ```bash
> git log --oneline 3032282..origin/main
> ```
> Do not expect any file/line reference below to be exactly where this
> document says. **Re-verify by execution before acting on any of it** — that
> is rule 1 in `AGENTS.md`, not a suggestion.

---

## 1. What is pre-authorized, exactly

The operator has explicitly pre-authorized, for this run only:
- pushing commits to remote `fix/*` branches and the integration branch,
- opening a PR for each issue,
- merging each reviewed, green PR into the integration branch.

**The final merge of the integration branch into `main` — and the deploy it
triggers — is explicitly carved OUT of that pre-authorization.** It is
gated on a separate, manual step: §8.4a. This is a deliberate change from
"pre-authorize everything" — `/code-review ultra` (the multi-agent cloud
review, aka the deprecated `/ultrareview`) is user-triggered and billed, so
it cannot be invoked from inside this autonomous run no matter what is
pre-authorized. Do not attempt to launch it via Bash, the API, or any other
mechanism. Do not merge to `main` without it having run and been addressed.

Nothing else in this document extends beyond what's listed above (per this
repo's own rule: authorization stands for the scope specified, not beyond).
In particular this still does **not** cover: adding new secrets to CI,
running the operator-only visual-baseline reseed workflow, or force-pushing /
rewriting `main` history. Those stay gated — see §5 and §7.9.

---

## 2. Branch topology

```
main
 └─ feature/major-issues-batch                 (integration branch)
     ├─ fix/103-feedback-audit-empty-db        → PR into integration → 2 reviewers → squash-merge
     ├─ fix/124-provider-notice-coverage        → same
     ├─ fix/127-e2e-ci-wiring                   → same
     ├─ fix/162-166-gate-liveness               → same
     ├─ fix/182-mutation-gate-partial-score     → same
     ├─ fix/123-feedback-store-reconnect        → same
     ├─ fix/122-spend-cap-policy                → same  (branches from a tip that already has #123)
     ├─ fix/155-high-stakes-context-bypass      → same
     ├─ fix/193-source-support-denominator      → PR reviewed + approved, HELD (see §5.1)
     ├─ fix/117-readiness-banner-flash          → same, HELD only if it trips the visual gate
     ├─ fix/222-landing-mobile-density          → same, HELD only if it trips the visual gate
     └─ fix/180-consensus-boilerplate           → attempt once, drop if 2 review rounds don't clear it
                     │
                     ▼ (only fixes that actually landed)
        merge `main` into the integration branch, re-run the FULL gate
        suite fresh (§7.9), then one holistic adversarial review of the
        whole accumulated diff
                     │
                     ▼
        merge integration branch → main as a MERGE COMMIT (not squash —
        each issue's own squashed commit stays distinct in main's history,
        matching this repo's rule against a bare `--squash` concatenating
        every commit body into one)
                     │
                     ▼
              ONE deploy, verified per §7.9
```

Create the integration branch from `main` in a dedicated worktree (never the
main checkout): `git worktree add ../quorum-ai-major-batch -b
feature/major-issues-batch origin/main`. Every `fix/*` branch below is cut
from the **current tip of the integration branch**, not from `main` directly,
so each issue sees the previous ones' fixes.

Before the final merge to `main`, merge `main` into the integration branch
first and re-gate the merged tree locally (this repo's rule for any stacked
branch) — `main` may have moved during the session.

---

## 3. The standing rules this run must not violate

Read `AGENTS.md` in full before starting; do not skip it because this
document exists. The ones most likely to matter tonight, by number:

- **Rule 1–4 (truth):** verify every claim in an issue by executing, not by
  reading. If a premise turns out false, stop and say so — do not repair it
  silently.
- **Rule 6/6a/6b/7 (tests):** TDD — RED, then GREEN, then prove it bites by
  mutating a **copy** of the file (never `git checkout <file>` to revert — it
  discards uncommitted work). Capture the verbatim failure output. Every
  negative check needs a positive partner.
- **Rule 9/10/12/12a (review):** exactly **two** independent reviewer
  subagents per issue, fanned out from a **read-only** working copy of that
  issue's diff, each told **IN CAPITALS** not to write, edit, `git checkout`,
  `git stash`, or `sed -i` anything. Cap review at two rounds total per
  issue. If a second fix round adds a new defect, stop and change the
  approach for that issue rather than attempting a third round.
- **Rule 12b:** if a reviewer must mutate source to prove a test bites, give
  it its **own copy** (`git archive HEAD | tar -x -C <dir>`), never the
  shared worktree.
- **Rule 14:** `make quality && make validate` do **not** cover the real
  merge gates. Before calling any issue's PR green, also run
  `make diff-cover DIFF_BASE=<integration-branch-tip-before-this-issue>`,
  `make api-contract`, `make openapi-check`, `make security-scan`, and the
  e2e suite (rule 13's flags) if UI/specs/fixtures changed.
- **Rule 15/15a:** run `pytest` and `make diff-cover` serially (they share
  coverage state), and **commit before trusting diff-cover** — an uncommitted
  edit can attribute pre-existing lines to your diff.
- **Rule 17/17c:** one concern per PR. Squash-merge each issue's PR into the
  integration branch with an explicit subject and body naming only that
  issue (`gh pr merge --squash --subject --body`) — never a bare `--squash`.
- **Rule 18/18a:** done means merged **and running in production** — for
  every issue except the ones held per §5, that only becomes true at the
  very end of this run, after the single final deploy. Say so plainly in the
  final summary rather than calling any individual issue "done" before then.

---

## 4. The per-issue loop (repeat for every issue in §6 and §7)

1. **Verify the defect still exists, by executing** — grep the current file,
   run the named test, reproduce the exact snippet in the issue if one is
   given. If it's already fixed or the issue is stale, say so, close nothing
   yourself (leave that note for the final summary), and move to the next
   issue.
2. **Plan.** One paragraph: what changes, in which files, and what the test
   plan is. If the issue already has a "suggested fix" and it still holds up
   under your verification, use it — don't invent a different design for
   the sake of it.
3. **RED.** Write the test that fails against current behavior. Capture the
   verbatim failure.
4. **GREEN.** Make the minimal change that passes it.
5. **Bite-proof.** Copy the changed file aside, mutate the fix out, confirm
   the test goes red, restore from the copy (never `git checkout`).
6. **Local gates** per rule 14 above, scoped to this issue's diff.
7. **Commit and push** `fix/<n>-<slug>` to the remote.
8. **Open the PR** against the integration branch, in that direction
   (`gh pr create --base feature/major-issues-batch`).
9. **Fan out two reviewers**, read-only copies, one general-correctness lens
   and — for anything touching money, auth, safety, or CI gating (#122,
   #123, #155, #162/166, #182, #127) — one reviewer whose explicit job is to
   break the change.
10. **Verify every reviewer finding before acting on it**, same as any other
    claim (rule 11). Fix real findings; for anything genuinely out of scope,
    file it as a new issue rather than scope-creeping this PR.
11. **Squash-merge** into the integration branch with an explicit message.
    Delete the remote `fix/*` branch. Move to the next issue.

---

## 5. The stuck-issue rule (read this before you start — it's why this run
can proceed unattended)

The operator will be asleep. If you hit a point on any issue where you
genuinely need information or a decision that isn't already given in §6/§7 —
and it's not something you can resolve by executing a command yourself —
**do not stop the whole run.** Do this instead:

1. Leave that issue's branch pushed in whatever state it's in (even
   mid-fix), with a clear note at the top of its PR description (or a
   `PARKED.md` in its worktree if no PR was opened yet) saying exactly what
   is blocking it and what specific input or decision would unblock it.
2. Do **not** merge that issue into the integration branch.
3. Move on to the next issue in the queue.
4. Record it in the final summary (§8) under "parked — needs input," with
   the same one-line reason, so the operator can resolve it in five minutes
   tomorrow instead of having to reconstruct context.

This applies to every issue in §6 and §7. It is **especially** expected for:

### 5.1 The visual-baseline exception (applies to #193, and possibly #117/#222)

`e2e/tests/invariants/visual-snapshots.spec.ts` and
`trust-score-visual.spec.ts` are a **blocking** gate compared against PNG
baselines that only an operator can regenerate
(`.github/workflows/seed-visual-baselines.yml`, human-reviewed diff). If a
fix changes pixels in a region those specs cover:

- Finish the fix, get it through both reviewers, get the PR green on every
  gate **except** visual-snapshots.
- Do **not** merge it into the integration branch — that would leave the
  integration branch's own CI red for every issue merged after it.
- Leave the branch pushed, PR open against the integration branch, with a
  note: "Ready to merge. Needs: run `seed-visual-baselines.yml`, review the
  new PNGs, then merge this PR and re-run this issue's e2e lane before it
  joins the integration branch."
- Move to the next issue.

Check first, by reading the spec files, whether the DOM region each of #193 /
#117 / #222 actually touches is inside what those two specs assert on before
assuming this applies — #166's own audit describes the visual gate as
covering "the result + transcript views," which may not include the landing
page (#222) or the readiness banner's transient states (#117). Verify, don't
assume either way.

---

## 6. Active queue — attempt fully, in this order

### 6.1 — #103: nightly feedback-audit opens an empty DB

Verified 2026-08-03: `.github/workflows/feedback-audit.yml` sets no
`FEEDBACK_DB_PATH`; `FeedbackStore.from_env()` falls back to
`.data/feedback_events.sqlite3` in the fresh checkout, so the audit has never
read production data.

**Pre-decided default:** run the audit via a scheduled Fly machine (`fly
ssh`/`flyctl ssh console`) against the real volume, reusing whatever Fly
credential the existing deploy workflow already has in CI secrets — check
first (`grep -rn FLY_API_TOKEN .github/workflows/`) whether that credential
is actually available to a workflow shaped like this one. If it is not
available without adding a new secret, **do not add one** — fall back to
dropping the job entirely and removing the stale "or by the audit cron job"
line from `feedback_store.py`'s docstring. Either outcome closes the issue
honestly; inventing a new secret does not.

### 6.2 — #124: only 1 of 9 provider notices has browser-level coverage

Verified: only `NOTICE_NO_SOURCES_FOUND` appears anywhere under `e2e/`.
Follow the issue's own suggested acceptance: parameterise one spec over the
`PROVIDER_NOTICES` registry (run shape → expected notice) rather than
hand-writing eight specs, using `test_provider_notice_copy.py`'s registry
walk as the model. Budget: this is the single biggest scope item in the
active queue (8 fixture variants). If it runs long, it is still worth
finishing before moving to a smaller issue — do not abandon it partway
through just to hit a count; if truly not finishable tonight, park per §5
with the exact list of which notices still lack coverage.

### 6.3 — #127: 42 e2e tests run in no CI workflow

Verified: `workspace.spec.ts` (17), `accessibility.spec.ts` (16),
`api-mocking.spec.ts` (9) appear in zero `.github/workflows/*.yml` files.

**Order matters (the issue says so directly):** first run all three specs
locally and record the result as-is. `accessibility.spec.ts` is flagged as
suspected stale — do not register a red spec into a blocking lane. Fix
genuine failures that are real product defects; for failures that are stale
test assumptions (copy drift, an impossible focus state, a `display:none`
target), fix the test, not the product, and say which you did for each.
Only then wire all three into a CI workflow, and widen
`tests/test_e2e_workflow_covers_all_invariant_specs.py`'s `GATED_SPEC_DIRS`
to cover all of `e2e/tests/`, not just `invariants/` and `ops/`, so this
class of gap can't recur.

### 6.4 — #162 + #166: gate liveness (treat as one issue slot, close both)

Verified 2026-08-03, directly against the current workflow files:

| Gate | Verified current state | What to do |
|---|---|---|
| `codex-review` | `openai/codex-action` still commented out in `ci.yml`; job checks out and always passes | **Delete the job.** Wiring the paid secret is out of scope for an unattended run. |
| `perf-gate` missing-JSON branch | still prints "UNMEASURED... treat as UNMEASURED" then falls through to exit 0 | Make it fail. The rest of this gate is already floored — this is the one branch that isn't. |
| `csp-smoke` | no min-executed floor | Add one, mirroring `scripts/check_e2e_executed.py`'s pattern. |
| `flake-scan` | prints `UNMEASURED — every repetition was skipped`, no non-zero exit follows | Make the **step** fail on `executed <= 0`; keep the **job** advisory via `continue-on-error` at the job level, so the exit code stops lying without changing what actually blocks a merge. |
| `perf-sample` | same shape as flake-scan | Same treatment. |
| `check-error-rate` / `skip_low_traffic` | `exit_code_for()` returns 1 only for `alert`, so "not enough traffic" reads as a pass | Give `skip_low_traffic` its own distinct, non-zero-but-non-alert signal in the summary output — an explicit abstention, not a silent pass and not conflated with a real alert. |
| `visual-snapshots` step (`e2e.yml`, **blocking**) | no executed-count floor; never measured | **Measure it from a real run first** (trigger this PR's own e2e lane, read the actual count from the report) and floor it from that measured number. Do not invent a number — the issue is explicit that doing so is the exact fabrication this work package exists to remove. |

Update `docs/analysis/03-enforcement-machinery.md`'s table to match reality,
close #162 as superseded by #166 in the same PR body (careful: per this
repo's own recorded incident, writing "closes #162" in a commit/PR body
really does auto-close it on merge — that's the intended outcome here, not
an accident to avoid).

### 6.5 — #182: mutation gate scored nothing on a real PR (30m timeout)

Verified via `gh run view` on the real PR #181 run: cancelled at exactly
30m16s by its own `timeout-minutes: 30`, no score line printed, because
`make mutation-baseline` scopes by whole changed **function**, not changed
line — `produce_final_synthesis` alone generated 146+ mutants.

Implement step 1 from the issue's own 7-step plan only tonight: **always
print a partial score, even on timeout** (killed/survived/timeout/not-yet-run
as mutants complete). This is the cheapest fix and directly closes the
"a job that ends without measuring looks like a job that measured nothing
wrong" failure mode. Do not attempt steps 2–7 (changed-lines-first ranking,
per-mutant test selection, caching) in this run — each needs its own
measurement pass per the issue's own "before promoting or re-tuning
anything" section; scope creep here risks the exact timeout this issue is
about.

### 6.6 — #123: feedback_store has no reconnect path

Verified: `_configure_feedback_store()` / `configure_run_history_store(...)`
in `main.py` are bare import-time calls; no reconnect logic exists anywhere
in `src/`.

**Pre-decided shape:** build the reconnect on top of #109's existing
write-health signal, triggered off the request thread (a timer, or the next
`estimate` call behind a monotonic cooldown) so the 5.24s lock-open cost is
never paid synchronously by a user request. Give it an **explicit off
switch** — several existing tests
(`test_configure_does_not_close_the_displaced_store`,
`test_store_lifecycle.py`'s singleton guard, tests using
`FEEDBACK_DB_PATH=:memory:`) depend on the current no-reconnect behavior and
must keep passing or be deliberately updated, not broken. Apply the same
fix to `run_history_store`, which the issue notes is the identical shape —
fixing only one makes the paired lifecycle tests asymmetric.

**This issue is a prerequisite for #122 below — do not reorder.**

### 6.7 — #122: spend-cap policy when the ledger is known stale

Verified: `feedback_lost_billed_writes` is real and surfaced on `/status`
(from #109), but `CostEstimationService.estimate()` never consults it.

**Pre-decided policy (confirmed with the operator, not a code guess):**
`BLOCK`, but only **after** a reopen attempt (from #123, just built above)
has actually been tried and failed — not an immediate block on staleness
alone, not silent allow-and-log as today. This is the issue's own
"recommendation to consider," now confirmed rather than left as an open
question. Use an honest reason string that names the storage fault when
blocking — never a bare raise (measured today: an unwrapped raise produces
a bare 500 with no error envelope; that must not ship as the "fix").

### 6.8 — #155: high-stakes acknowledgement bypassable via context

Verified: `required_warnings_for_query(self, query_text)` takes no context
parameter; `context.prior_question` / `context.prior_synthesis` do reach
provider prompts unfiltered; the UI confirmed to never send `context` today
(`grep -c context app.js` → 0 matches for this field).

**Pre-decided:** not a breaking API change (zero live callers use `context`
today, confirmed by execution, so there is no real client to break). Ship
the discriminator fix: scan the context **with this product's own mandated
caveat sentence removed**, not the naive "scan everything" approach that was
already tried and reverted (it 422'd every legitimate follow-up, because
100% of this app's own synthesis output contains that sentence). Measure the
fix against a real synthesis output before shipping, per the issue's own
instruction. Also add `context` to `QueryRunWarningsRequest` and its handler,
so `/warnings` and the enforcement path agree — today a client following the
documented probe-then-create flow can enter an unbreakable 422 loop without
this.

---

## 7. Parked-for-end queue — attempt, but expect to hold or drop per §5

### 7.1 — #193: Source support trust card shows a bare percentage

Verified: `app.js` renders `value: coveragePct != null ? \`${coveragePct}%\`
: "—"` with no denominator statement, violating #171's own stated rule.
Fix: change the rendered value to state the denominator and exclusion count
(e.g. `NN% (X of Y answers)`), sourced only from already-served fields
(`citation_coverage.answer_count`, `citation_coverage.sourced_answer_count`)
— no new number needs to be computed. **This is the canonical case for
§5.1** — check whether `visual-snapshots.spec.ts` covers this DOM region
before assuming it does, but budget for it needing the held-branch
treatment.

### 7.2 — #117: readiness banner flashes and shifts layout

Verified: no `aria-busy`/skeleton suppression exists between the
server-rendered `window.LIVE_READINESS` seed paint and the later
`refreshReadiness()` update. Fix per the issue's own preference: suppress
the first paint until the `/ready` result is in, rather than reserving space
for a banner that might retract — "showing a warning that is then retracted
is its own small dishonesty," in the issue's own words. Check §5.1 before
merging.

### 7.3 — #222: landing page exceeds a 664px mobile viewport

Not independently re-measured by browser in the verification pass that
produced this document — the issue's own 2026-08-02 Playwright measurement
is the evidence in hand. **Re-measure it yourself, live, before touching
anything** (a throwaway Playwright script at 390x664, per the issue's own
reproduction recipe) — do not implement a fix against an unverified premise.
This is explicitly a design trade-off (which elements to compress, by how
much) rather than a mechanical bug fix; make a reasonable, reversible choice
(tighter spacing/type scale above the fold) and let review judge it. Check
§5.1 before merging — likely lower risk than #193/#117 since #166's audit
describes the visual gate as covering result/transcript views specifically,
but verify rather than assume.

### 7.4 — #180: consensus reads "strong, 4/4 aligned" on shared boilerplate

Verified directly against `synthesis_consensus.py`: `classify_model_alignment`
still short-circuits `elif opening_majority: final_aligned = True`, and the
clustering primitive `_overlap_partner_counts` (via `_four_grams`/`_excerpt`)
does zero boilerplate exclusion.

**This is last on purpose.** Three prior fix attempts (recorded in the
issue) were each broken in adversarial review. Do not repeat that pattern
with a fourth rushed guess.

1. **Measure first**, per the issue's own suggested first step: on the
   golden fixture and any captured real runs, quantify how much of the
   pairwise 4-gram overlap between answers is contributed by sentences the
   product itself dictates or appends (the mandated high-stakes caveat,
   the `_RECOMMENDATION_PROMPT` boilerplate) versus genuine shared content.
2. **Let that number decide the approach** — a targeted exclusion of the
   specific mandated text if it dominates the overlap, or a change to the
   clustering primitive itself (a minimum substantive-token count, IDF
   weighting) if the boilerplate is diffuse. Do not guess; the issue
   documents exactly why guessing here has failed three times already.
3. Build it, get it through both reviewers.
4. **If it does not clear two review rounds cleanly, stop.** Do not attempt
   a third. Push the branch with the measured findings recorded in the PR
   description (the actual overlap-contribution number, and which approach
   was tried and why it didn't hold up in review), leave it unmerged, and
   record it as dropped-from-this-batch in the final summary. Do not let
   this issue block the final integration → main merge.

---

## 8. End-of-batch integration (only after every issue in §6/§7 has either
landed, been held per §5.1, or been parked/dropped)

1. `git fetch origin && git merge origin/main` into the integration branch —
   catch anything that landed on `main` from elsewhere during the run.
2. **Commit everything** before measuring (rule 15a — an uncommitted state
   makes diff-cover attribute pre-existing lines to your diff).
3. Re-run the **full** gate suite fresh against the whole accumulated diff:
   `make quality && make validate`, `make diff-cover DIFF_BASE=origin/main`,
   `make api-contract`, `make openapi-check`, `make security-scan`, and the
   full e2e suite (both lanes, per rule 13's flags).
4. **One holistic adversarial review** of the entire accumulated diff — not
   per-issue this time, but looking specifically for interactions BETWEEN
   the landed fixes (e.g., does #122's new BLOCK path and #123's reconnect
   actually compose correctly under a real reopen-then-fail sequence? does
   #162/166's gate changes affect anything #127 wired in?). Two reviewers,
   same read-only/no-mutation discipline as §3. Fix anything real this
   surfaces, same two-round cap as any other review.

### 4a. STOP HERE. Do not proceed past this point on your own.

This is the one hard stop in the whole run, and it exists because
`/code-review ultra` cannot be launched by an autonomous session — it is
user-triggered and billed, by design, with no API or CLI escape hatch. Do
not attempt to invoke it, simulate it, or substitute another review round
for it. Instead:

1. Push the integration branch (already done by this point) and confirm it
   is fully green on the gates run in step 3.
2. Write a short status note (console output is enough, this is not the
   final result doc) stating: which issues landed, which are held per
   §5.1, which are parked/dropped per §5/§7.4, and that the integration
   branch is ready for review.
3. **Stop the run.** Literally end the session's turn here. Do not merge,
   do not deploy, do not keep working on parked issues past this point —
   there is nothing left in this document authorizing further action until
   the operator returns.
4. When the operator returns, they will run `/code-review ultra` against
   `feature/major-issues-batch` themselves, address whatever it finds (with
   your help, in a follow-up turn), and only then tell you to proceed to
   step 5 below.

If the operator is somehow already present and available to trigger
`/code-review ultra` interactively as part of this same session, that is
fine — but do not assume that; the default expectation for an overnight run
is that this is where it ends until morning.

5. Once the operator has run `/code-review ultra`, reviewed its findings,
   fixed whatever needed fixing (each fix still gets the same TDD +
   bite-proof + two-reviewer treatment as any other change here, on its own
   small commit on the integration branch), and explicitly says to proceed:
   merge the integration branch into `main` as a **merge commit** (not
   squash) — `main`'s history should show each issue's own squashed commit
   distinctly.
6. Verify the deploy per this repo's rule 18: the deploy **job** actually
   ran (not skipped/cancelled — check the job, not the run's rollup), on
   the **newest** run for the merge SHA if a concurrency-cancelled run
   appears first, `/status.build_sha` equals the merged SHA, and the
   product actually fires (`/ready`, `/status`, `/estimate` — free probes
   only, no paid live run).
7. Close-out: delete every merged `fix/*` branch (local + remote), delete
   the integration branch and its dedicated worktree once merged and
   verified, `git branch -f main origin/main`.

---

## 9. Final summary — write this as `MAJOR-ISSUES-BATCH-RESULT.md`

Write this at whichever point the run actually ends — either at §8.4a's stop
(the expected case) or after §8.7's close-out (if the operator was present
to run `/code-review ultra` in the same session). If stopping at §8.4a, title
the top of the doc **"AWAITING /code-review ultra — nothing below is merged
to main yet"** in plain words, so there is no ambiguity in the morning about
whether this run finished.

Required sections, matching this repo's own result-doc convention:

- **Shipped and deployed** (only issues that actually crossed the final
  merge+deploy in §8): issue number, one-line before/after behavior
  (plain English, not just the diff), commit SHA on `main`.
- **Held — needs an operator action** (§5.1 cases): issue number, exact
  action needed (e.g. "run seed-visual-baselines.yml, review N changed
  PNGs, then merge PR #___"), branch name, PR link.
- **Parked — needs input** (§5 general case): issue number, the exact
  question or decision that blocked it, what was already tried, branch
  name if one exists.
- **Dropped** (only possible for #180 per §7.4's rule): the measured
  overlap-contribution number, which approach was attempted, why it didn't
  survive review, branch name (left unmerged, not deleted).
- **Anything discovered but out of scope**: filed as a new issue, not
  fixed inline, per rule 17 (one concern per PR) — list the new issue
  numbers here.

Do not claim any issue "done" in this document unless it is merged into
`main` and the deploy is verified per §8.6 — "reviewed and merged into the
integration branch" is not done, per this repo's own rule 18.
