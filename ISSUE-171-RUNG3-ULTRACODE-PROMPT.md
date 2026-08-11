# ultracode — #171, the remaining rungs. Autonomous through merge and deploy.

> **HOW TO USE THIS FILE.** Do not paste it into a chat. Paste the block in **§14**.
> One short message from you; one long document for the session.
>
> **Anchor: `main` at `9c60bc3486e738c07b85356fe3cf1532c3bc370a`, merged, deployed
> and prod-verified** — Deploy **job** `success` on run `30542484850` (the newest
> by `createdAt`; a 53s-older run is `cancelled` by concurrency dedupe),
> `/status.build_sha == 9c60bc3` on **both** `quorum.stackclimb.com` and
> `quorum-ai.fly.dev`, `/ready.live_readiness.state: live`. That commit is in the
> past and cannot change, so this line is never wrong. See everything since with
> `git log --oneline 9c60bc3..origin/main`.
>
> **Every other number, path, line reference and claim below is something you must
> re-measure.** This document was written by the session that shipped #175; roughly
> half of what a handoff asserts does not survive contact with the tree
> (`AGENTS.md` rule 11). Treat it as a map, not as evidence.

---

## 1. The operator grant

`AGENTS.md` rule 17b normally requires explicit human approval to push, open a
pull request, merge, or deploy. **For this task that approval is granted in
advance**, and you may run the loop to merge and deploy without checking in —
**provided every condition in §10 holds.** If any one fails, stop and report.
The grant is conditional, not blanket.

It does **not** extend to:

- **Any paid API call.** Hermetic and $0 throughout. No funding a key, no live
  provider run, no secret rotation.
- **Inventing a number.** No minimum-answer floor, no participant threshold, no
  quality heuristic, no cost band. See §5 — this is the single most important
  constraint in this document, because the issue is *about* fabricated numbers.
- **Widening scope beyond #171's remaining rungs.** File what you find.
- **Closing any issue other than the ones your change actually closes**, with the
  evidence that it does.
- **Writing a close-keyword next to an issue you are NOT closing.** See §12.7.

---

## 2. Where #171 actually stands — verified 2026-07-30, re-verify anyway

**Read the issue: `gh issue view 171`.** Then know these two things.

**#171 is OPEN and has never been closed.** Its timeline has zero `closed` and
zero `reopened` events. PR #174 shipped a real fix and its subject said `(#171)`
— a *reference*, not a close keyword, so nothing auto-closed. Do not assume the
issue state reflects the code state in either direction.

**What PR #174 (`e6c84ea`) DID ship:** `produce_initial_answer` no longer
substitutes locally-simulated text for a failed live slot. A missing slot is
reported missing.

**What PR #179 (`9c60bc3`, #175) then shipped:** `_live_openrouter_response`
gates usable text on `.strip()`, so a whitespace-only completion is no longer
served as a COMPLETED live answer with a `measured` receipt.

**What REMAINS in #171** — four claims, each verified against `9c60bc3` on
2026-07-30 by the command shown. **Re-run every one before planning.**

| Remaining item | Verification command | Result then |
|---|---|---|
| `synthesis_consensus` never consults `synthesis_mode`, so the verdict ring can be decided by Quorum's own template while `failed_steps` is empty and `live_count` is 4 | `grep -c synthesis_mode src/product_app/synthesis_consensus.py` | **0** |
| `DebateOutput` has no `debate_mode` field | `grep -rn "debate_mode" src/` | no hits (only `debate_model_id`, unrelated) |
| `DebateResult` builds `fallback_messages` and discards them | built `debate.py:245,261,327`; absent from `class DebateResult`; no read after 327 | confirmed |
| No provenance field on `InitialModelAnswer` | `grep -n provenance src/product_app/providers.py` | only an unrelated F-06 comment |

The scope, as `ISSUE-171-RESULT.md` §6 records it:

- **Rung 3** — a required provenance field on the answer; consumers switching
  **exhaustively** (`assert_never`); coverage and agreement accepting only
  real-provenance answers; the provenance set pinned **derived from the enum,
  never retyped**.
- **The debate's own provenance** (issue finding 5) — `debate_mode` on
  `DebateOutput`, `fallback_messages` surfaced rather than discarded, and
  `classify_model_alignment` consulting `synthesis_mode` so a templated synthesis
  cannot silently decide the verdict ring.
- **The denominator-reporting rule** — every trust number states its denominator
  and what it excluded ("coverage 100% (4 of 4 answers, 0 excluded)").

---

## 3. Phase 0 — re-measure the ground, then REPRODUCE before building

Nothing above is trusted until you have run it.

```bash
git fetch origin && git status --porcelain        # expect a clean TRACKED tree
git log --oneline 9c60bc3..origin/main
gh issue view 171 --json state -q .state          # expect OPEN
gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'
uv sync --all-extras                              # NOT --extra dev
```

Then capture a baseline and **say which commit you measured it at**:

```bash
set -o pipefail
make quality && make validate
```

At `9c60bc3` with `e2e/node_modules` absent this was **1878 passed / 37 skipped**;
with it installed, **1894 / 25** (the 12 tests in
`tests/unit/test_negative_assertion_guard.py` skip without it). Total 1919 either
way. **If your number differs, explain it before proceeding** — an unexplained
count is an unexplained change.

**Beware a masked exit code.** `make quality | tail -6` returns *tail's* status.
Use `set -o pipefail`, or run bare and echo `$?`.

### Now REPRODUCE the defect — all of it

Build a hermetic probe at the `product_app.providers.urlopen` seam (no socket,
$0) that drives the **real create-to-terminal pipeline** and prints `status`,
`live_count`, `local_count`, `demo_mode`, `cost_source`, `failed_steps`, the
coverage block, `agreement`, and — new for this work — `synthesis_mode`,
whether the synthesis was templated, and what the verdict ring decided.

The scenario that matters most: **every live participant answers, but the
SYNTHESIS falls back to its template.** Show that the verdict ring is then
decided by Quorum's own words with `failed_steps` empty and `live_count` at 4.
That is finding 5, and it is the sharpest thing left in #171.

`tests/resilience/test_fault_injection_lane.py` already has the harness
(`_FakeResponse`, `_enable_live`, `_drive_full_run`,
`_urlopen_faulting_only_the_participant`). **Reuse it. Do not build a second
one.** Note `_faulted_model_collides_with_no_moderator` — the moderator models
are `settings.debate_model_id` and `settings.synthesis_model_id`, and faulting a
participant that is also a moderator changes what you are measuring.

**If it does not reproduce, or reproduces differently, STOP and say so.** A false
premise is a mandatory stop. Do not repair it silently and carry on.

---

## 4. Phase 1 — the scope decision, which you must make FIRST

**This is bigger than one pull request, and pretending otherwise is the main way
this work goes wrong.** `AGENTS.md` rule 17: one CONCERN per pull request. A
reviewer cannot audit a provenance-model change, a debate-provenance change and a
number-formatting rule in one diff.

Measure, then decide and **state the number that decided it**:

```bash
# after prototyping each rung far enough to size it — NOT by guessing
git diff --stat
```

The likely split, which you should confirm or refute by measurement:

1. **PR-A — the debate/synthesis provenance leak (finding 5).** `synthesis_mode`
   consulted by `classify_model_alignment`; `debate_mode` on `DebateOutput`;
   `fallback_messages` surfaced. **This is the one that serves a wrong number
   today**, so it ranks first.
2. **PR-B — Rung 3, the provenance field and exhaustive consumers.** Larger, and
   a type-model change that touches many call sites.
3. **PR-C — the denominator-reporting rule.** Mostly presentation, and it depends
   on B's vocabulary.

**Each merges before the next starts** (rule 17). A second stacked PR merges
`main` in first and **re-gates the merged tree locally**, diff-cover included — a
clean auto-merge is not a correct merge (17d).

**If the whole thing cannot honestly fit even a sensible split, say so and stop.**
Rule 19: close more than you open; if an item is bigger than it looked, say so —
do not file and continue.

### Fan out for PLANNING — read-only

Spawn read-only planners **only if the design space is genuinely open**, which
for the provenance model it is. Tell every subagent, IN CAPITALS:

> **DO NOT WRITE, EDIT, CREATE OR DELETE ANY FILE. DO NOT RUN `git checkout`,
> `git stash`, `git commit`, `git add`, `git restore` OR `sed -i`. YOU OWN
> EXACTLY ONE DIRECTORY: `<path>`. REPORT FINDINGS AS TEXT ONLY. MAKE NO PAID
> API CALLS.**

Useful planner questions, one agent each:

- **The consumer census.** Every place that reads `InitialModelAnswer.status`,
  `provider_path`, `answer_text` or `fallback_used` to decide whether an answer
  is real. Which become redundant under a provenance field? Which would need
  `assert_never`? Give `file:line` and quoted code.
- **The enum-derivation question.** How do existing exhaustive pins in this repo
  derive their member set from the enum rather than retyping it? (#160 says 11 of
  14 production enums have no exhaustive pin — read it.) What is the idiom here?
- **The trust-number census** for the denominator rule: every served number, its
  denominator, and what it silently excludes.

**A planner is not evidence.** Verify each claim yourself before building on it —
see §7, where a reviewer claim was checked and turned out to be wrong.

---

## 5. The things you must NOT invent — read twice

#171 exists because invented content reached a trust number. The failure mode of
*fixing* it is inventing a different number.

1. **No minimum-answer floor.** "Should there be a minimum number of answers
   before a debate runs at all?" is an explicit open question in #171. It was
   deliberately **not** answered, and **you must not answer it either.** What
   already holds: a live run where **zero** answers arrive is refused. The floor
   between 1 and 4 is undecided, and settling it needs the accuracy pilot run at
   n = 1, 2, 3 surviving answers — a **measurement**, costing paid runs, and
   therefore operator-gated. Put it in the operator queue; do not pick a number.
2. **No quality heuristic** — no refusal detection, no "looks like an error".
3. **No new threshold, band or cap.** If a fix seems to need one, that is the
   signal to stop and report, not to pick a value.
4. **Do not decide the demo-coverage question.** With live execution off,
   simulated sources carry `is_fallback=False` and read as 100% primary coverage.
   The one-line change (`is_fallback=True`) would make demo coverage read 0%.
   That is a **product decision about what a demo should show** — operator's.
5. **Do not move `agreement.total`.** It counts slots asked, not answers
   received, and feeds a persisted `agreement_ratio` behind a measured accuracy
   baseline. Moving the denominator moves a measured number. The honest fix is
   the denominator-reporting rule, not a redefinition.

---

## 6. Phase 2 — build serially, test so it bites

**ONE writer: you.** Subagents share one working tree and parallel writers
corrupt each other. Fan the review, never the construction. Branch in a dedicated
`git worktree` (rule 17a), never the main checkout.

**Do NOT mutate the tree while anything is measuring it.** A `make diff-cover`
run overlapping a source edit produced a "measured ZERO lines" reading that
looked exactly like a gate failure and was self-inflicted. Same for subagents: a
read-only reviewer once observed a transient experiment mid-flight and had to
re-derive everything from `git show HEAD`.

Test discipline, all of it non-negotiable:

- **RED first, verbatim.** "It failed" is not evidence; the message is.
- **Prove every test bites by mutation.** `cp` the file aside, re-introduce the
  defect, watch it red, restore **from the copy**, confirm with `diff -q`.
  **Never `git checkout <file>`** — it discards uncommitted work. Purge
  `__pycache__` before and after.
- **PERFORM every "what turns it red" instruction you write, literally, exactly
  as written.** This is not optional and it is where the last two pull requests
  both failed. On #175 the documented mutation was
  `result.answer_text = ...strip()` — impossible, `LiveProviderResult` is a
  frozen dataclass, so it raised `FrozenInstanceError` and reddened the test for
  the wrong reason. The *repair* said `dataclasses.replace(...)` — also
  impossible, because that module binds only `asdict` and `dataclass`, so it
  raised `NameError`. **A mutation that raises instead of running proves nothing.**
  Both were found only by someone performing the instruction rather than reading
  it. Perform yours, and confirm it reds on the ASSERTION.
- **Assert CARDINALITY, not clean-path outcomes.** How many answers carried real
  provenance; what the coverage denominator was; how many reached the debate
  prompt; how many cost records the run wrote and what they summed to. Ask of
  every assertion: **could this fail for ANY implementation?** If not, delete it —
  on #175 an assertion `live_count == aligned` was entailed by the two `== 3`
  assertions above it and could not fail.
- **Every negative needs a positive partner.** A guard that returns "not real"
  for everything satisfies every zero. Drive the paired case that must succeed.
- **`assert_never` needs a test that a NEW member breaks the build**, not just
  that today's members pass. Derive the member set from the enum; never retype it
  (rule 7a: never parametrize a test over the constant it tests).
- **Do NOT grep source text for the defect.** Assert the observable consequence.
- **Quote verbatim or elide honestly.** If a docstring says "verbatim", it must
  be byte-exact. On #175 an elided `...` was "helpfully" expanded and silently
  dropped a dict key, turning a truthful abbreviation into a false claim.
- **A count in prose is a claim.** If you write "N sites", measure N and state the
  command — or name the SET and quote no number. Two successive drafts on #175
  quoted counts ("ten", then "eleven") that no reader could re-derive.
- **UI surfaces:** if you touch one, add its shape to `e2e/fixtures/golden-run.ts`
  in the same change, or the gate cannot see it. Run any timing-sensitive spec
  N ≥ 10× to establish a real flake rate.

### Performance — measure it, do not assume it

A provenance field on every answer plus exhaustive switching touches the hot path
of every run. **Do not assume it is free.**

- Run the perf gate locally before and after:
  `QUORUM_RUN_PERF_BUDGET=1 uv run pytest tests/perf tests/performance -q`
- Know before you interpret it: this job is **advisory**
  (`continue-on-error: true`, named "CI budgets pending", tracked as DEBT-009)
  and it is **load-sensitive**. Measured on #175: two runs of the *identical*
  commit gave concurrent p95 **2928.0ms** then **1514.4ms** against a 1500ms
  budget — a 1.9× swing. **A real regression reproduces; noise does not.** If it
  reds, re-run it, and check whether it also reds on `main`.
- If your change genuinely moves p50/p95, say so with both numbers and decide
  deliberately. Do not silently accept a regression, and **do not raise a budget
  to go green.**

---

## 7. Phase 3 — review: two lenses, two rounds, no third

Fan out **read-only** reviewers on the staged diff. **Two lenses, not five**
(rule 10: two reviewers ≈ four; spend the difference on verification).

- **Give each lens its OWN COPY** — `git archive HEAD | tar -x -C <dir>`, then
  `uv sync --all-extras` there (rule 12b). A shared-worktree mutation has already
  cost this repo four phantom failures once and stray uncommitted edits once.
- **One lens must EXECUTE rather than read.** Its prompt must require pasted
  command output for every verdict — **a verdict with no output is void.** On
  this repository the executing lens finds the real defects while reading lenses
  produce refuted noise. Tell it explicitly to *perform* every documented
  mutation and report whether the test reds on the assertion or on an exception.
- **One lens is the BREAKER**, whose job is to get fabricated or templated
  content counted as real — a templated synthesis deciding the verdict ring, a
  templated debate round counted as a live one, an answer with no real provenance
  entering the coverage numerator. This is trust code; that lens is mandatory.
- Give both the CAPITALS constraints from §4, plus **they own exactly one
  directory and must not touch any other**, plus **no paid API calls**.
- **VERIFY EVERY REVIEWER CLAIM BY EXECUTION BEFORE ACTING ON IT.** Reviewers are
  wrong often enough to matter. On #175 the executing lens asserted "the strip is
  not in `query_runs`" — there are two, one of them a direct filter; acting on it
  would have *weakened* a correct comment. Check the fix, not just the finding.
- **Round 2 re-reviews the FIX DIFF ONLY. Expect your own fix to introduce a
  defect — budget a round for it.** On #175 round 2 found that **two of round 1's
  four repairs replaced one wrong claim with another.** On #174 the same thing
  happened. Assume it will happen to you. **Then stop** — two rounds, then ship
  with leftovers written down.

---

## 8. Cleanup and bookkeeping — part of the work, not an afterthought

- **Before deleting any file, `git ls-files <path>`.** Tracked files are
  recoverable; an untracked file that was ever `git add`ed survives as a dangling
  blob recoverable via `git fsck --lost-found` + `git cat-file -p`. **Check the
  object store before declaring loss** (rule 16c).
- **Do not commit root-level `*-ULTRACODE-PROMPT.md` / `*-RESULT.md` documents.**
  Current practice is that they stay untracked: `27227d5` staged 32 handoff
  documents for deletion and `8536627` deleted 29, extracting the operating
  manual into `AGENTS.md`. `ISSUE-171-RESULT.md` and `ISSUE-175-RESULT.md` are
  both untracked today. **If you believe a document belongs in the repo, put its
  content in `docs/` and say why** — do not quietly commit a root handoff file.
- **Update `AGENTS.md` if you learn a rule** that would have saved you time —
  that is where the operating manual lives now. Add it as a rule, not a story.
- **Sweep for stale references after any rename** (rule 8). A content audit
  cannot see an inbound reference; `git grep` before concluding anything is
  unused. Two dangling citations shipped on #174 that way.
- **Leave the branch list clean.** After merge, delete your branch on **both**
  sides and verify (see §11).
- **Do not delete branches you did not create.** `feat/ui-pr5b-cost-guard-diff`
  and `worktree-wf_8fbedc6c-041-3` exist locally and are not yours.

---

## 9. Gates — re-derive the list, never trust a table

```bash
gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'
```

At `9c60bc3` this returned six, matching `AGENTS.md` rule 14's table:
`validate-and-test`, `pytest (Python 3.12)`,
`Changed-lines coverage >= 95% (blocking)`, `Schemathesis API contract (blocking)`,
`FR traceability completeness (blocking)`, `e2e axe + parity (chromium)`.
**That table has been wrong twice. Re-derive it anyway.**

Run these, stopping on the first red, with **`pytest` and `diff-cover` SERIAL**
(they race on `build/gates/guard-good-xml.xml`, #113), capturing real exit codes:

```bash
set -o pipefail
make quality && make validate
make diff-cover DIFF_BASE=origin/main
make api-contract
make openapi-check
make security-scan
```

E2E exactly as CI does, or ~95 phantom failures appear (rule 13). **Read the two
blocking lanes and their executed-count floors out of `.github/workflows/e2e.yml`
— do not trust these numbers**; at `9c60bc3` they were **139** (invariants) and
**96** (axe + parity), and both must be hit exactly:

```bash
lsof -ti tcp:18085 | xargs -r kill -9
cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 CI=true npx playwright test <specs> \
  --project=chromium --workers=1 --retries=0
cd .. && python3 scripts/check_e2e_executed.py --report e2e/results.xml --min <floor> --lane "<lane>"
```

Visual snapshots are Linux-baselined; leave them to CI.

**Never lower a threshold, add `# pragma: no cover`, or delete a test to go green.**

---

## 10. Merge only if ALL of these hold

1. The defect **reproduces before** and **does not after**, captured verbatim,
   for every scenario in scope — including the templated-synthesis verdict ring.
2. Every new test **proven to bite** by mutation, with the mutation named **and
   performed**, reddening on the assertion rather than an exception.
3. **No invented number anywhere** — no answer floor, no threshold, no band.
4. All required contexts green on the real runner; **re-verify the rollup
   independently** (query `repos/:owner/:repo/commits/<sha>/check-runs`, not just
   the PR rollup). **Open the advisory mutation gate's log and find its number** —
   a green tick is not evidence it measured. On #175 it reported
   `57 killed, 0 survived, 22 timeout (excluded), 0 no-tests — 100.0%` with a
   scope of exactly the changed functions. If it scored nothing, say so.
5. Any advisory red **root-caused, not waved through**. The perf job is
   load-sensitive; re-run it and check `main` before attributing it to your diff.
6. Two review rounds completed; every surviving finding fixed or explicitly
   listed as shipped-open in the pull request body.
7. The pull request body says what changed, what it closes, what it leaves open,
   and **one line on why this item outranks the top of the backlog.**

Then, and note the exact form:

```bash
gh pr merge <n> --squash --delete-branch --subject "<explicit>" --body "<explicit>"
```

**Never a bare `--squash`** — it concatenates every commit body onto `main`.

Two mechanical traps, both hit on #175:

- **`gh pr merge` may fail with `'main' is already used by worktree at ...`.**
  That is the *local checkout* step failing **after the merge already landed**.
  Check `gh pr view <n> --json state,mergeCommit` before retrying, or you will
  merge twice.
- **`--delete-branch` does NOT reliably delete the remote branch.** It did not on
  #174 and did not on #175. Verify and clean up explicitly (§11).

---

## 11. Deploy — verify, then prove it fires

- **A merge produces two deploy runs; one is `cancelled` by concurrency dedupe.**
  Resolve the **newest run by `createdAt`**, then read its **Deploy job**
  conclusion — not the run's rollup.
- `/status.build_sha` equals the merged SHA on **both** `quorum.stackclimb.com`
  and `quorum-ai.fly.dev`.
- `/ready.live_readiness.state: live`.
- **Confirm the branch is gone on BOTH sides:**
  `git ls-remote --heads origin '<branch>'` must print nothing, and delete the
  local branch too. If `git branch -d` refuses because the commits were squashed,
  confirm content parity first — `git diff <branch> main --stat` must be empty —
  then `-D`.
- **After merging, `git branch -f main origin/main`** (17e). If `main` is checked
  out elsewhere, `git -C <main-checkout> merge --ff-only origin/main` instead.
- **Prove the thing fires, or say plainly that you cannot.** Probe only where it
  costs nothing — `/ready`, `/status`, `/metrics`, `/ui/ops`, `/estimate`.
  **Measured on #175: `/metrics` exposes only `http_*`, `process_*` and
  `python_*` series — there is no provider-failure or answer-slot counter**, so a
  provenance change is NOT observable in production today. If that is still true,
  **say so and name the check that would** (landing #177 would add the signal;
  otherwise one deliberate paid run). **Do not dress up "the build is deployed" as
  "the fix works."**

---

## 12. Standing rules — every one was learned by breaking something here

1. **Verify by executing, never by reading.** State the command and what it
   printed, or say UNVERIFIED out loud.
2. **A pipeline hides the exit code.** `make x | tail` returns tail's status.
3. **A green advisory job is not evidence it ran; a RED one is not evidence it
   measured.** Open the log and find the number.
4. **When you CORRECT a false claim, verify the REPLACEMENT before writing it.**
   Both recent pull requests introduced a new wrong claim while repairing an old
   one, in the same docstring.
5. **A count in prose is a claim.** Measure it or name the set instead.
6. **Never `git checkout <file>` to undo a mutation.** `cp` aside, restore from
   the copy, confirm with `diff -q`.
7. **Never put a close-keyword next to an issue you are not closing.**
   `Filed, not fixed: #175` in PR #174's body **closed #175** — GitHub matches
   `fixed: #175` and ignores the negation. Write `filed as #N (not addressed
   here)`. Conversely `(#171)` in a subject is only a REFERENCE and closes
   nothing — which is why #171 is still open. **Re-check every issue state after
   the merge** (`gh issue view <n> --json state,stateReason`).
8. **Line numbers are locators, not addresses.** Confirm the quoted text.
9. **`git grep` before concluding anything is unused**, and after any rename.
10. **Before deleting any file, `git ls-files` it**; check the object store before
    declaring loss.
11. **`make format` reformats test assertions.** Grep for the real text before any
    programmatic edit, and re-run the tests after formatting.
12. **Process-global test state** — the cost event ring, the run-capacity
    semaphore and the model catalog are process globals. Use
    `tests/helpers.isolated_run_semaphore`.
13. **A probe script doing `sys.path.insert(0, ROOT/"src")` can measure a STALE
    tree.** Print the resolved module `__file__` and check it is the one you think.
14. **Fan out for review, never for building. One tree-writer: you.**
15. **Never fabricate a number, label or baseline.** Absent means `—`.
16. **Plain English. No jargon, no invented shorthand.**
17. **Close more than you open.** If the item is bigger than it looked, say so and
    stop — do not file and continue.

---

## 13. Stop and ask instead of proceeding if

- The defect does not reproduce, or reproduces differently — **mandatory stop.**
- A fix would require inventing a floor, a threshold or a quality heuristic.
- The work cannot honestly fit a sensible split of pull requests.
- Review has not converged after two rounds.
- CI is red for a reason you cannot root-cause from the logs.
- A change would move a **measured** number (the accuracy baseline, the persisted
  `agreement_ratio`) — that needs the operator.
- You discover a higher-ranked item mid-work — **park the branch, record it,
  re-run selection.**

---

## 14. Paste this into a fresh chat

```
ultracode

Work issue #171's remaining rungs end to end, autonomously, through merge and
deploy verification.

Read ISSUE-171-RUNG3-ULTRACODE-PROMPT.md at the repo root and follow it. Read
AGENTS.md first — its operating rules bind, and rule 14's gate list must be
re-derived with gh api rather than trusted. Then read the issue itself:
gh issue view 171. Note it is OPEN and was never closed; PR #174 shipped a real
fix but its subject only REFERENCED the issue.

You have my approval in advance to branch, commit, push, open pull requests,
merge and verify the deploys WITHOUT checking in — but only if every condition in
section 10 holds. If any one fails, stop and report instead.

FIRST: re-measure section 3 yourself and REPRODUCE the remaining defect before
building anything — especially the case where every participant answers but the
SYNTHESIS is templated, and the verdict ring is then decided by Quorum's own
words with failed_steps empty and live_count at 4. If it does not reproduce, or
any premise in section 2 does not hold, STOP and tell me — do not repair it
silently.

Decide the scope split in section 4 BEFORE writing code, by measuring the diff
size, not by guessing. One concern per pull request, each merged before the next
starts. Say which split you chose and the number that decided it. If it cannot
honestly be split, say so and stop.

Do NOT invent a minimum-answer floor, a participant threshold, a quality
heuristic, or any other number — section 5. The open question about a minimum
number of answers before a debate runs is mine to answer, and it needs a measured
pilot, not a judgement.

Build serially — one tree-writer, you, in a dedicated git worktree. Never mutate
the tree while a gate or a subagent is measuring it. Fan out read-only subagents
for planning and review, each with its OWN copy via git archive, and tell every
one IN CAPITALS not to write, edit, git checkout, git stash or sed -i anything,
that it owns exactly one directory, and that it may make no paid API calls. Two
review lenses, not five: one must EXECUTE rather than read and paste command
output for every verdict, and one is a breaker trying to get templated or
fabricated content counted as real. Two rounds maximum, the second on the fix
diff only, then stop. Verify every reviewer claim yourself before acting on it —
they are wrong often enough to matter.

Assert cardinality, not clean-path outcomes. Prove every test bites by mutation
using cp-aside and restore-from-copy, never git checkout — and PERFORM every
"what turns it red" instruction literally, confirming it reds on the assertion
rather than on an exception. Measure performance before and after; the perf gate
is advisory and load-sensitive, so re-run it and check main before blaming your
diff.

Hermetic and $0 throughout: no paid API calls, no funded key, no live provider
run.

Do the cleanup and bookkeeping in section 8 as part of the work, not after it.

When done, write ISSUE-171-RUNG3-RESULT.md and tell me the next action item with
one line on why it outranks the alternatives. Then stop.
```

---

## 15. What the RESULT document must contain

Write `ISSUE-171-RUNG3-RESULT.md` at the repo root (untracked — see §8):

1. **What shipped** — PR number(s), squash SHA(s), deploy run id, the Deploy
   **job** conclusion, and the prod `build_sha` observed on both hostnames.
2. **The scope split** — what you chose and the measured number that decided it.
3. **RED → GREEN**, every scenario, verbatim.
4. **The bite proofs** — per test, the mutation, that you PERFORMED it, and the
   failure it produced. **Name any assertion that does NOT move and label it a
   pin.**
5. **Performance** — p50/p95 before and after, and whether any movement is real
   or load noise, with the evidence.
6. **Review** — raised, verified, refuted, fixed. **Report the refuted ones too**;
   a refutation is a result.
7. **Issues closed**, each with its evidence, and **re-checked after the merge**
   (`gh issue view <n> --json state,stateReason`). If #171 is now genuinely
   complete, close it explicitly and say why. If rungs remain, say which.
8. **Shipped open**, and why.
9. **The operator queue** — anything needing a measured number or a paid run.
   The minimum-answer floor belongs here, unanswered.
10. **The next action item**, derived from the live backlog, with one line on why
    it outranks the alternatives.

Then **stop.** Do not start the next item.
