# ultracode — #175: a whitespace answer is not an answer. Autonomous through merge.

> **HOW TO USE THIS FILE.** Do not paste it into a chat. Paste the block in **§12**.
> One short message from you; one long document for the session.
>
> **Anchor: `main` at `e6c84ea`, merged, deployed and prod-verified** (Deploy job
> `success`, `/status.build_sha == e6c84ea` on both `quorum.stackclimb.com` and
> `quorum-ai.fly.dev`, `/ready.live_readiness.state: live`). That commit is in the
> past and cannot change, so this line is never wrong. See everything since with
> `git log --oneline e6c84ea..origin/main`. **Every other number, path and line
> reference below is a claim you must re-measure.**

---

## 1. The operator grant — read this before anything else

`AGENTS.md` rule 17b normally requires explicit human approval to push, open a
pull request, merge, or deploy. **For this task only, that approval is granted in
advance.** You may run the whole loop to merge and deploy without checking in,
**provided every condition in §8 holds.** If any one fails, you stop and report
instead — the grant is conditional, not blanket.

The grant does **not** extend to:

- **Any paid API call.** Hermetic and $0 throughout. No funding a key, no live
  provider run, no secret rotation.
- **Inventing a threshold, a minimum answer length, or a "usable answer" heuristic
  beyond emptiness.** See §4. Trimming whitespace is not a judgement call;
  deciding that a 3-character answer is "too short" is, and it stays the
  operator's.
- **Widening scope beyond #175.** File what you find; do not fix it here.
- **Closing any issue other than the ones your change actually closes**, and only
  with the evidence that it does.
- **Writing a close-keyword next to an issue you are NOT closing.** See §10.6 —
  this exact mistake closed #175 by accident on 2026-07-30.

---

## 2. What #175 is

**Read the issue itself — `gh issue view 175` — it is the source of truth and it
carries an executed reproduction.** This section is orientation only.

`_live_openrouter_response` gates usable text on plain truthiness, not on
`.strip()`. A completion of `"   \n\t "` is truthy, so the slot returns
**COMPLETED** on the `openrouter_search` path. #171's guard never runs — it only
fires on the exactly-empty string.

Measured consequence, all four slots returning whitespace, live execution on:

```
 slot 1..4 completed openrouter_search  text='   \n  '
 live_count 4 local_count 0 demo_mode False
 status completed  cost_source measured
 failed_steps []  missing_steps []
 coverage {'answer_count': 4, 'sourced_answer_count': 0, 'ratio': '0.00'}
 agreement {'aligned': 0, 'total': 4}
```

The panel produced nothing and the product reports **"4 of 4 answered live",
status `completed`, no failed steps, and a `measured` (billed) receipt.** No
degraded banner fires. **This is the only run shape that reaches a `measured`
receipt with no text anywhere.**

The sharper variant — the whitespace slot also returns a citation annotation —
reports **`coverage 4 of 4 = 100%` on a run where one slot produced no text**:
the same figure #171 was filed about, through the door #171 does not close.

**The payload already contradicts itself.** `synthesis_consensus` applies
`.strip()` when deciding alignment, so `agreement` reads 3 of 4 while `live_count`
and the coverage denominator read 4. The product knows the slot is empty in one
place and not in the other. **That disagreement is your cheapest oracle** — find
every place that strips and every place that does not, and make them agree.

---

## 3. Phase 0 — re-measure the ground, then reproduce

Nothing below is trusted until you have run it.

```bash
git fetch origin && git status --porcelain     # expect a clean tracked tree
git log --oneline e6c84ea..origin/main
gh issue view 175 --json state -q .state       # must be OPEN (it was reopened 2026-07-30)
gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'
uv sync --all-extras
make quality && make validate                  # green BEFORE you touch anything
```

**Capture the pass count and the commit you measured it at.** "Pre-existing" must
mean measured against a named commit and you must say which.

**Beware a masked exit code.** `make quality | tail -6` returns *tail's* status,
not make's — that hid a real `format-check` failure on PR #174 until CI caught
it. Use `set -o pipefail`, or run the target bare and echo `$?`.

Then **reproduce the defect**: patch `product_app.providers.urlopen` so every
slot returns a 200 whose message content is `"   \n  "` **with a `usage` object**,
drive the real create-to-terminal pipeline, and print `status`, `live_count`,
`local_count`, `demo_mode`, `cost_source`, `failed_steps`, the coverage block and
`agreement`. Then the second variant with a citation annotation on one slot only.
**Capture both verbatim. That is your RED.** If it does not reproduce, stop and
say so — a false premise is a mandatory stop.

`tests/resilience/test_fault_injection_lane.py` already has the harness
(`_FakeResponse`, `_enable_live`, `_drive_full_run`, `_urlopen_faulting_only_the_participant`).
Reuse it; do not build a second one.

---

## 4. The three things you must NOT invent

1. **A minimum answer length.** Emptiness after `.strip()` is a fact. "Too short
   to be useful" is a product call. Do not add one.
2. **A content-quality heuristic** — no refusal detection, no "looks like an
   error" matching. #171 exists because invented content reached a trust number.
3. **A new threshold, band, or cap of any kind.** If a fix seems to need one, that
   is the signal to stop and report, not to pick a number.

---

## 5. Phase 1 — plan, and decide the money question FIRST

The naive fix is one character: `if not result.answer_text.strip():`. Proven by
mutation, it turns the all-whitespace run into an honest one (`partial`, no
synthesis, `failed_steps` populated). **But shipping only that is wrong, and here
is the trap that makes this issue bigger than it looks.**

### The money trap — settle this before writing code

A whitespace completion **was billed**: the provider returned a `usage` object.
Today that usage is captured on a COMPLETED answer and flows into a `measured`
receipt. `providers._failed_answer` constructs its `InitialModelAnswer` **without
`token_usage`**, so it defaults to `None`.

So the naive fix silently **discards the measured tokens of a call that really was
charged.** The receipt drops to `estimated` — the safe direction, no false
`measured` — but the dollars actually spent stop being recorded anywhere.

**Verify all of that by execution before designing around it**, then decide
deliberately between:

- **(a)** a missing slot that still carries its `token_usage`, so the spend stays
  measurable while the answer is correctly absent; or
- **(b)** a missing slot with no usage, accepting `estimated` and recording the
  loss where the cost layer can see it.

Whichever you choose, **say why in the pull request**, and pin it with a test that
asserts **how many** cost records the run produced and what they summed to — not
that a run "completed". Read `docs/analysis/` and the F-06 material on
`_DISPATCH_UNMEASURED` first: this repo has already reasoned about
"dispatched, maybe billed, no usage" and you must not re-litigate it blind.

### The pinning test must be INVERTED, not deleted

`tests/unit/test_provider_billing_classification.py::test_initial_answer_path_still_serves_a_whitespace_only_completion`
deliberately pins today's behaviour, and its docstring says tightening the guard
"would be a silent behaviour change smuggled in under a billing fix."

**That docstring is right about the risk and wrong about the conclusion, and your
pull request must say so in those terms.** The test also carries the F-06 billing
contract — the number of POSTs each upstream outcome provokes — which must not
move. Invert the honesty half; keep the cardinality half **byte-for-byte**.

### Decide the slice by measuring, not by preference

Measure the changed-line count. If the guard + the cost decision + the tests fit
one reviewable diff, ship one pull request. If the cost decision turns out to need
its own reasoning and its own review, that is two, and the second starts only
after the first merges. **Say which you chose and the number that decided it.**

Fan out **read-only** planners only if the design space is genuinely open. Tell
every subagent, IN CAPITALS: **DO NOT WRITE, EDIT, CREATE OR DELETE ANY FILE. DO
NOT RUN `git checkout`, `git stash`, `git commit`, `git add` OR `sed -i`. REPORT
FINDINGS AS TEXT.**

---

## 6. Phase 2 — build serially, test so it bites

**ONE writer: you.** Subagents share one working tree and parallel writers corrupt
each other. Fan the review, never the construction. Branch in a dedicated
`git worktree` (rule 17a), never the main checkout.

Test discipline, all of it non-negotiable:

- **RED first, verbatim.** "It failed" is not evidence; the message is.
- **Prove every test bites by mutation.** `cp` the file aside, re-introduce the
  defect, watch it red, restore **from the copy**, confirm with `diff -q`.
  **Never `git checkout <file>`.** Purge `__pycache__` before and after.
- **Assert CARDINALITY.** How many slots counted toward `live_count`; what the
  coverage denominator was; how many cost records the run wrote and their sum;
  how many answers reached the debate prompt. Ask of every assertion: **could this
  fail for ANY implementation?**
- **Every negative needs a positive partner.** A guard that returns "missing" for
  everything satisfies every zero. Drive the paired case that must still succeed.
- **The one-character answer is the case that decides whether you over-corrected.**
  A model that legitimately answers `"7"` must still count. Assert it.
- **Do NOT grep source text for the defect.** Assert the observable consequence.
- **Sweep for the disagreement.** `git grep` every place that tests answer text
  for emptiness. `synthesis_consensus.py` strips; `providers.py` does not; find
  the rest. A fix that leaves two more disagreeing is a partial fix — enumerate
  them and say which you unified.
- **If you touch a UI surface, add its shape to `e2e/fixtures/golden-run.ts` in the
  same change**, or the gate cannot see it. Run any timing-sensitive spec N≥10×.

---

## 7. Phase 3 — review: two lenses, two rounds, no third

Fan out **read-only** reviewers on the staged diff. Two lenses, not five.

- **One lens must EXECUTE rather than read.** Give it its own copy
  (`git archive HEAD | tar -x -C <dir>`, then `uv sync --all-extras` there). Its
  prompt must require pasted command output for every verdict — **a verdict with
  no output is void.** On this repository the executing lens finds the real
  defects while reading lenses produce refuted noise.
- **One lens is the breaker**, whose explicit job is to get non-answer content
  counted as an answer, or a billed call to vanish from the receipt. This is
  trust-and-money code; that lens is mandatory.
- Give both the CAPITALS constraints from §5, plus: **they own exactly one
  directory and must not touch any other.**
- **Verify every reviewer claim by execution before acting on it.** Check the fix,
  not just the finding.
- **Round 2 re-reviews the FIX DIFF ONLY. Expect your own fix to introduce a
  defect — that happened in both rounds on PR #174. Then stop.**

---

## 8. Gates and the merge conditions

Re-derive the required list; do not trust any table:

```bash
gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'
```

Run these, stopping on the first red, **`pytest` and `diff-cover` serially** (they
race on a shared path), and **capture real exit codes**:

```bash
set -o pipefail
make quality && make validate
make diff-cover DIFF_BASE=origin/main
make api-contract
make openapi-check
make security-scan
# e2e exactly as CI does, or ~95 phantom failures appear:
lsof -ti tcp:18085 | xargs -r kill -9
cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 CI=true npx playwright test <specs> \
  --project=chromium --workers=1 --retries=0
```

The two blocking e2e lanes and their executed-count floors are listed in
`.github/workflows/e2e.yml` — read them there, run both, and expect the exact
floor. Visual snapshots are Linux-baselined; leave them to CI.

**Never lower a threshold, add `# pragma: no cover`, or delete a test to go green.**

### Merge only if ALL of these hold

1. The defect **reproduces before** and **does not after**, both captured verbatim,
   for **both** variants (all-whitespace, and whitespace-with-citation).
2. Every new test **proven to bite** by mutation, with the mutation named.
3. **The money decision is explicit, tested by cardinality, and stated.**
4. All required contexts green on the real runner; re-verify the rollup
   independently. **Open the advisory mutation gate's log and find its number** —
   a green tick is not evidence it measured.
5. Two review rounds completed; every surviving finding fixed or explicitly listed
   as shipped-open in the pull request body.
6. No fabricated number, threshold or length anywhere in the change.
7. The pull request body says what changed, what it closes, what it leaves open,
   and **one line on why this item outranks the top of the backlog.**

Then:

```bash
gh pr merge <n> --squash --delete-branch --subject "<explicit>" --body "<explicit>"
```

**Never a bare `--squash`.** And see §10.6 about issue references in that body.

**If any condition fails, do not merge. Stop and report with the open findings
listed.** That is a successful outcome, not a failure.

### Deploy — verify, then prove it fires

- **A merge produces two deploy runs; one is `cancelled` by concurrency dedupe.**
  On PR #174 the cancelled one completed **64 seconds earlier** than the real one.
  Resolve the **newest run by `createdAt`**, then read its **Deploy job**
  conclusion — not the run's rollup.
- `/status.build_sha` equals the merged SHA, on **both** `quorum.stackclimb.com`
  and `quorum-ai.fly.dev`.
- `/ready.live_readiness.state: live`.
- **Confirm the local branch is actually gone on BOTH sides afterwards** —
  `--delete-branch` left it on the remote on PR #174:
  `git ls-remote --heads origin '<branch>'` must print nothing.
- **The thing you built actually fires.** Probe only where it costs nothing —
  `/ready`, `/status`, `/metrics`, `/ui/ops`, `/estimate`. **If you cannot
  demonstrate it firing without a paid run, say so plainly and name the check that
  would** — do not dress up "the build is deployed" as "the fix works". There is
  no provider-failure counter in `/metrics` today; that is #177.

---

## 9. Phase 4 — report, and name the next action

Write `ISSUE-175-RESULT.md` at the repo root:

1. **What shipped** — PR number, squash SHA, deploy run id, the Deploy **job**
   conclusion, and the prod `build_sha` you observed on both hostnames.
2. **RED → GREEN**, both variants, verbatim.
3. **The bite proofs** — per test, the mutation and the failure it produced.
   **Name any assertion that does NOT move and label it a pin.**
4. **The money decision** — what you chose, why, and the cardinality test pinning
   it.
5. **Review** — raised, verified, refuted, fixed. Report the refuted ones too.
6. **Issues closed**, each with the evidence. **Re-check their state after the
   merge** (`gh issue view <n> --json state,stateReason`).
7. **Shipped open**, and why.
8. **The operator queue** — anything needing a measured number or a paid run.
9. **The next action item**, derived from the live backlog, with one line on why it
   outranks the alternatives.

Then **stop.** Do not start the next item.

---

## 10. Standing rules — every one was learned by breaking something here

1. **Verify by executing, never by reading.** State the command and what it
   printed, or say UNVERIFIED out loud.
2. **A pipeline hides the exit code.** `make x | tail` returns tail's status.
   Use `set -o pipefail` or echo `$?` on a bare run.
3. **A green advisory job is not evidence it ran; a RED one is not evidence it
   measured.** Open the log and find the number.
4. **When you CORRECT a false claim, verify the REPLACEMENT before writing it.**
   On PR #174 the round-1 repair of a wrong count introduced a different wrong
   count, in the same docstring.
5. **A count in prose is a claim.** If you write "N assertions move", measure N —
   or mark each one inline and quote no total.
6. **Never put a close-keyword next to an issue you are not closing.**
   `Filed, not fixed: #175` in PR #174's merge body **closed #175** — GitHub
   matches `fixed: #175` and ignores the negation. Write `filed as #N (not
   addressed here)`. Re-check issue states after every merge.
7. **Line numbers are locators, not addresses.** Confirm the quoted text.
8. **A content audit cannot see an inbound reference.** `git grep` before
   concluding anything is unused — and after any rename, sweep for citations to
   the old name. Two dangling citations shipped that way on PR #174.
9. **Before deleting any file, `git ls-files` it.**
10. **`make format` reformats test assertions.** Grep for the real text before any
    programmatic edit, and re-run the tests after formatting.
11. **Fan out for review, never for building. One tree-writer: you.**
12. **Reviewers get their own copy** if they must mutate source.
13. **Never fabricate a number, label or baseline.** Absent means `—`.
14. **Plain English. No jargon, no invented shorthand.**
15. **Close more than you open.** If the item is bigger than it looked, say so and
    stop — do not file and continue.

---

## 11. Stop and ask instead of proceeding if

- The defect does not reproduce, or reproduces differently — **a false premise is
  a mandatory stop.**
- A fix would require inventing a length, a threshold or a quality heuristic.
- The money decision cannot be made without a measurement you cannot take for $0.
- Review has not converged after two rounds.
- CI is red for a reason you cannot root-cause from the logs.
- You discover a higher-ranked item mid-work — **park the branch, record it,
  re-run selection.**
- The work cannot honestly fit one reviewable pull request and cannot be split.

---

## 12. Paste this into a fresh chat

```
ultracode

Work issue #175 end to end, autonomously, through merge and deploy verification.

Read ISSUE-175-ULTRACODE-PROMPT.md at the repo root and follow it. Read AGENTS.md
first — its operating rules bind, and rule 14's gate list must be re-derived with
gh api rather than trusted. Then read the issue itself: gh issue view 175.

You have my approval in advance to branch, commit, push, open a pull request,
merge and verify the deploy WITHOUT checking in — but only if every condition in
section 8 holds. If any one fails, stop and report instead.

FIRST: re-measure section 3 yourself and REPRODUCE both variants of the defect
before building anything. If it does not reproduce, or any premise does not hold,
STOP and tell me — do not repair it silently.

Settle the money question in section 5 BEFORE writing code: a whitespace
completion was billed, and the obvious fix drops its measured tokens. Decide it
deliberately, test it by cardinality, and state it. Do not invent a minimum answer
length or any other threshold.

Build serially — one tree-writer, you, in a dedicated git worktree. Fan out
read-only subagents for planning and review, and tell every one IN CAPITALS not to
write, edit, git checkout, git stash or sed -i anything, and that it owns exactly
one directory. Two review lenses, not five: one must EXECUTE rather than read, and
one is a breaker trying to get non-answer content counted as an answer or a billed
call dropped from the receipt. Two rounds maximum, the second on the fix diff
only, then stop.

Assert cardinality, not clean-path outcomes. Prove every test bites by mutation
using cp-aside and restore-from-copy, never git checkout. Do not enforce this by
grepping source text — assert the observable consequence. Invert the test that
pins the current behaviour; do not delete it, and keep its billing-cardinality
half byte-for-byte.

Hermetic and $0 throughout: no paid API calls, no funded key, no live provider run.

When done, write ISSUE-175-RESULT.md and tell me the next action item with one
line on why it outranks the alternatives. Then stop.
```
