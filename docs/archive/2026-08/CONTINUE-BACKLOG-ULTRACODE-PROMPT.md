> # ⛔ SUPERSEDED — DO NOT EXECUTE THIS FILE
>
> **Read `CONTINUE-TWO-LANES-ULTRACODE-PROMPT.md` instead.**
>
> Superseded 2026-08-25. Its packages A and B are folded into that document,
> with corrected evidence. **The state block below is stale** — it says
> `ef55128`, and main has moved twice since (`7f4d217` at the time of writing).
>
> Kept only as a record. Everything actionable moved.

# CONTINUE-BACKLOG — autonomous multi-package run

**You are the MAIN ORCHESTRATOR.** You do not write code. You spawn one
sub-orchestrator per work package, verify its work yourself, merge it yourself,
and own close-out. Then you spawn the next.

Written 2026-08-24, from a session that shipped four packages this way.

---

## State when this was written — RE-VERIFY, do not trust it

```
main / origin/main   ef55128
production build_sha ef55128   (Deploy JOB success, /status match)
live_execution       false     ← must stay false
open PRs             0
open issues          #357, #337, #290, #268, #105
latest ADR           0067      → next is 0068
```

```bash
git fetch origin && git log --oneline -1 origin/main
curl -s https://quorum-ai.fly.dev/status | python3 -m json.tool
gh issue list --state open
gh pr list
git worktree list
ls docs/adr/ | tail -3
```

**Per AGENTS.md rule 11, roughly half of what a handoff asserts does not survive
contact with the tree.** Everything below is marked VERIFIED (a command was run
on `ef55128`) or INHERITED. Re-derive anything you depend on.

---

## THE MOST IMPORTANT THING IN THIS DOCUMENT

**Only packages A and B below can be executed autonomously. C, D and E are
blocked on decisions only the human can make — all three involve spending
money.**

Do not "unblock" them by guessing. Do not adjust a cost constant from a sample
of one. When you reach package C, **STOP, write the handoff, and ask.** An
autonomous run that stalls honestly is a success; one that guesses at a money
guardrail is a failure, and this repo has a rule against exactly that.

Expect this run to complete **two packages**, not five.

---

## THE PROTOCOL — every package, no exceptions

### Roles

| Role | Authority |
|---|---|
| **You (main orchestrator)** | Verify independently. **Merge.** Deploy-verify. Close out. Never write product code. |
| **Sub-orchestrator** (one per package) | Owns a dedicated worktree. Plans, builds, reviews. Opens ONE PR. **NO merge authority. Stops when the PR is open and green.** |
| **Planner fan** (3–4, read-only) | Enumerate approaches and failure modes before code exists. |
| **Reviewer fan** (2–3 per round, read-only) | Refute by default. Distinct lenses. |

### Why the sub-orchestrator may not merge

A previous session pre-authorised a merge ("merge once CI is green"). The
sub-orchestrator then judged for itself whether the condition held and merged.
That delegates the judgement the review layer exists to apply, and from outside
it is indistinguishable from a subagent merging on its own authority — a safety
classifier flagged it, correctly. **A go-ahead is an ACT, not a standing
permission.** It paid for itself immediately: under the corrected protocol the
next package handed back rather than merging, and its own round-2 review caught
two defects its round-1 fix had introduced.

**One sub-orchestrator in this session went further and refused to push at all,**
citing AGENTS.md rule 17b (push/PR/merge need explicit *human* approval) on the
grounds that an agent's instruction is not the human's. It was wrong on the facts
— the human had granted it — but right to stop. **Grant push and PR authority
explicitly in each brief so this does not recur, and never grant merge.**

### Circuit breaker — enforced by the sub-orchestrator on itself

- **2 review rounds maximum.** Then STOP and hand back with open findings listed.
- **2–3 reviewers per round**, with *distinct* lenses.
- **1 builder writing at any moment.** Subagents share one working tree.
- **0 merges.**
- Two defective fixes in a row → STOP, escalate, change approach.

### On fan size — read this before setting it

You asked for 3–4 planners and 4–5 PR reviewers. **AGENTS.md rule 10 says the
opposite, and cites a source**: *"Two lenses, not five. Two reviewers ≈ four; one
is worse (Porter et al., IEEE TSE 1997). Spend the difference on verification,
not more finders."*

Measured in this session: **2 reviewers per round found 10 real findings** on the
#354 package, including one that reopened the defect being fixed. More reviewers
did not appear to be the constraint; **verifying their claims was.**

**Recommendation: 3–4 for PLANNING (divergent — enumerating approaches and
failure modes genuinely benefits from breadth) and 2–3 for REVIEW, each with an
explicitly different lens.** If you use more reviewers, they must be
lens-diverse, not redundant — four agents running the same correctness pass is
four times the cost for one pass of information.

**Mandatory lenses for a review round:**
1. **Correctness** — does it do what it claims?
2. **Breaker** — its only job is to defeat the change. For detection/validation/
   money/auth code this is REQUIRED by AGENTS.md, not optional.
3. **Prose** — verbatim in the prompt: *"For every number, superlative, and
   causal claim in the diff's comments, commit body and PR description, name the
   command that produces it — or mark it UNVERIFIED."*

Six false claims shipped in one session here, every one in prose, because the
reviewers were not asked to read prose.

### Reviewer rules — put these IN CAPITALS in every reviewer prompt

> **DO NOT WRITE, EDIT, `git checkout`, `git stash`, `sed -i`, OR
> `--update-snapshots` ANYTHING. YOU ARE READ-ONLY.**

A reviewer that must mutate source takes its own copy:
`git archive HEAD | tar -x -C <dir>` (rule 12b). A shared-tree mutation once gave
another reviewer 4 phantom failures and left edits a later agent inherited.

**Reviewers must report to their sub-orchestrator.** In this session two
reviewers could not reach their peer and reported to the main orchestrator
instead, which worked only because a human-facing relay existed. Tell each
reviewer its parent's agent id, and tell the sub-orchestrator to poll for reports
rather than assume silence means clean.

### Verification is the main orchestrator's job, and it is not optional

**Two of three premises briefed by the main orchestrator this session were
wrong**, and execution caught both:

- "This will push runs across a cost band" → **false**; bands key on the bound,
  which that diff left byte-identical.
- "`fix(#N)` is the auto-close vector" → **false**; it appears in 10 commit
  subjects and has closed nothing. Building to that brief would have produced 10
  false positives and missed the real sentence.

So: **when a sub-orchestrator refutes something you told it, that is the system
working.** Verify the refutation yourself, then thank it and move on.

Before merging any PR, independently:

1. Re-derive the required contexts — never trust a list:
   ```bash
   gh api repos/:owner/:repo/branches/main/protection \
     --jq '.required_status_checks.contexts[]'
   ```
2. **Mutate the core function yourself and watch the suite go red.** `cp` aside,
   mutate, restore from the copy, `diff -q`. **NEVER `git checkout <file>`.**
   On #354 this caught nothing new but confirmed a stance-blind implementation
   was rejected by 15 tests — that is the check that proves a fix is not inert.
3. **Open every advisory job's log and find the number.** A green gate is not
   evidence it ran; a red one is not evidence it measured.
4. Read the diff's prose for claims, not just its code.

---

## CLOSE-OUT — same order every time, never reordered

1. Local gates green, every review finding resolved.
2. **Merge** — `gh pr merge <N> --squash --subject "..." --body "..."`.
   A bare `--squash` concatenates every commit body onto main.
3. **Verify the deploy three ways**: the Deploy **JOB** ran `success` (not
   `skipped`/`cancelled` — read the job, not the run rollup); `/status.build_sha`
   equals the merge SHA; the thing you built actually fires.
   A merge fires SEVERAL deploy runs; early ones are cancelled by concurrency
   dedupe. **Resolve the newest by `createdAt`.** Runs whose `headSha` is main's
   tip but which were triggered by a PR branch correctly show `skipped` —
   `deploy.yml` gates on `head_branch == 'main'`. That is not drift.
4. `git merge --ff-only origin/main` from the main checkout (NOT
   `git branch -f main origin/main` — that fails when main is checked out).
   Remove the worktree FIRST, then delete the branch local and remote.
5. **Close the issue by hand, after deploy verification** — never by a closing
   keyword in the merge. See the auto-close trap below.

---

## THE AUTO-CLOSE TRAP — this repo has been bitten four times

GitHub closes an issue when a commit message, PR title or PR body puts
`close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved` next to `#N`.
**Its parser has no concept of negation.** Three of the four occurrences were the
sentence *"This does NOT close #N"*.

**A guard now exists** (`scripts/check_close_keywords.py`, live on the required
lane since `3ddc313`). It is enforcement for PR title+body, and *discipline* for
the merge subject — CI cannot see text you type at `gh pr merge` time.

```bash
export T="<your subject>" B="$(cat body.md)"
python3 scripts/check_close_keywords.py --env T B     # must print 0 negated
gh pr view <N> --json closingIssuesReferences --jq '.closingIssuesReferences'
```

**Vet the `--subject` AND `--body` you are about to pass to `gh pr merge`, not
just the PR.** The most recent occurrence was in a merge subject and the PR's own
`closingIssuesReferences` read `[]` — a clean bill of health while the damage
happened anyway.

**Known limitation, measured at zero occurrences over 586 texts:** markdown block
structure is not a boundary, so a negation heading directly above a legitimate
close is flagged. It fails loudly; reword and move on.

---

# THE PACKAGES

## A — the mutation gate: #337's remainder + the equivalent-mutant defect

**Do these as ONE package.** Rule 17g: several open concerns in the same narrow
area get clubbed into one PR to cut redundant review-and-deploy churn. Both are
the mutation gate; both live in the same Makefile recipe and
`scripts/run_with_deadline.py`.

### What is already fixed (VERIFIED — do not re-investigate)

`4ea57ba` repaired the root cause: mutmut reads the scope argument list twice and
the two readers want different spellings. `collect_source_file_mutation_data()`
matches concrete mutant keys (WITH `__mutmut_N`); `tests_for_mutant_names()`
matches the mangled names recorded at stats collection (WITHOUT it —
`mangled_name_from_mutant_name()` partitions it off). A suffixed glob matched
zero mangled names, `_pytest_args_regular_run()` read the empty set as "no
selection given", and it ran the whole suite before scoring anything.

**Measured on the first real `src/` diff since the repair (PR #362, run
32728631298):**

```
mutants scored: 250 killed, 2 survived, 85 timeout (excluded), 0 no-tests
```

Before the repair: `0 killed, 0 survived` after burning 24 minutes. **The core
defect is fixed and proven on a CI runner.**

### Defect A1 — the gate calls an EQUIVALENT MUTANT a demonstrated test gap

Both survivors above were in `synthesis_consensus._stance_majority_flags`:

- mutant 8: `sizes.get(label, 0)` → `sizes.get(label, 1)`
- mutant 9: `+ 1` → `+ 2`

The function uses counts **only** for `max()` and equality-with-max. Both
mutations are monotonic, so both preserve the result exactly.

**VERIFIED exhaustively by the main orchestrator: over all 5,460 label
assignments for panels of size 1–6 with 4 labels, neither differs from the
original in a single case.** No test can kill them.

But the gate prints:

> *"2 mutant(s) SURVIVED before the cut-off. A survivor is a test gap that was
> DEMONSTRATED — it needs no denominator and the rest of the run cannot take it
> back — so this fails even though no score was produced."*

**That claim is false for this class**, and the consequence is structural: the
job now fails red on an unkillable mutant **with no path to green**. That is the
same shape as the immutable-commit-message problem — a gate that can never be
satisfied gets ignored, and an ignored gate is worse than none.

**Design constraint:** an exclusion mechanism must not become a way to silence
real survivors. Whatever you build, a genuine survivor must still fail.
Enumerate how an exclusion list gets abused **before** designing it (rule 16e).

### Defect A2 — #337's remaining half: the deadline

The run above was **TRUNCATED** — it scored 252 of the scope before the 1440s
deadline. The truncation detection worked correctly and refused to report a
percentage (that was the second half of `4ea57ba`, firing for real for the first
time).

Note what is *different* now: it dies on a **large 20-file diff**, not "at
minimum scope" as #337's title says. **Re-scope or retitle the issue to match
what is now true**, and say so.

**Unexplained and worth one bounded look:** why the clean-test phase was ~9×
slower than the stats phase over the same suite. The previous package stopped
investigating once it became clear that phase should not have been running that
suite at all. **Time-box this. If it does not yield in one pass, record it and
move on** — the honest alternatives are a longer deadline, a nightly lane
instead of per-PR, or accepting truncation as normal on large diffs.

### Do not forget
- **File the equivalent-mutant defect as an issue first**, so the work is
  traceable, then fix it in the same PR. Rule 19: close more than you open.
- If your diff touches no `src/` Python, the gate is green having measured
  nothing and says so. **Report that verbatim; do not present it as a pass.**

---

## B — #357: nothing notices when live execution is left on

**The highest-value autonomously-executable item.**

`OPENROUTER_LIVE_EXECUTION_ENABLED` is the single switch that lets any `/ui`
visitor spend real money. ADR-0060 set it to `true` and stated the posture was
"expected to be reverted in the same session it was adopted." **It ran for three
days.** Nothing noticed.

Spend in the window was $0.1768 — **not the point**. The exposure was bounded
only by `GLOBAL_DAILY_CEILING_USD` ($5.00/day), **and that ceiling resets
daily**, so unnoticed the standing exposure renews indefinitely.

**INHERITED from the issue — verify each:**
- `/status` **does** serve `live_execution`. Nothing reads it and complains.
- The deploy-drift watchdog (every 30 min) checks production serves main's tip.
  It reported the drift *resolved* the moment the flag deployed.
- Availability and error-rate checks watch `/ready` and 5xx. A money-spending
  posture is neither unavailable nor erroring.
- ADR-0060's revert condition is prose. Nothing executes it.

**Every automated check was green throughout, correctly, because none of them
asks this question.**

### Design guidance

This is the same failure shape as the auto-close defect: **a human remembering,
with no mechanism behind it.** The fix is a mechanism.

Enumerate the failure modes first (rule 16e — this is money). Questions worth
settling with a command:

- Where can a check live that CANNOT be bypassed? A scheduled workflow is
  unbypassable; a make target is discipline.
- What is the right signal — the flag being on at all, or on for longer than a
  declared window? A time-box is the thing ADR-0060 actually promised.
- **How does it avoid crying wolf during a legitimate sampling window?** A
  deliberate window must be declarable, or the alert gets muted and you are back
  where you started.
- Where does the alert GO? A red CI job nobody looks at is not noticing. Be
  honest in the ADR about what is enforcement and what is discipline.
- **Before adding a gate, measure its yield against real defect history and state
  what it cannot see** — a literal AGENTS.md requirement.
  `docs/metrics/defect-discovery-audit.md`: **0 of 16** `src/` defects were
  caught by an automated check.

**Do not switch live execution on to test this.** Drive the check with a fixture
or a monkeypatched status payload.

---

## C, D, E — STOP HERE AND ASK

**All three need a human decision about spending money. Do not start any of them.
Write the handoff, present the three decisions, and end the run.**

### C — #290: peer critique (the largest item, and it needs a price decision first)

Today the four slot models are called **once each, in parallel, and never read
each other's answers**. One separate moderator reads all four and writes the
critique twice. FR-008 describes peer critique and is marked PARTIALLY MET.

**Blast radius (VERIFIED on `ef55128`):** 18 test files consume `DebateOutput`;
~13 UI/e2e files touch debate, including the visual lane whose Linux baselines
can only be reseeded through CI; orchestration goes from **2 debate calls to 8**;
the cost model hard-codes `Decimal(2) * debate_round_cost` in two places.

**The decision the human must make — DERIVED ARITHMETIC, NOT MEASURED:** debate
is ~$0.0104 of a $0.0547 estimate. Eight calls instead of two takes that to
~$0.042, so the estimate rises to roughly **$0.086** (~57%). The fail-safe bound
moves proportionally, and **the bound is what the cost bands key on**. Today's
bound is $0.1134 against a **$0.15 confirmation threshold**. This plausibly
crosses it, meaning **users start having to confirm every run.**

**A half-day design spike would settle it** — compute the real delta and whether
it crosses the band, before committing to 12–20 hours of work. That spike is
itself worth proposing to the human.

It also multiplies by four the exact stage #268 says is already mis-priced.

**Estimate if approved: 12–16 hours across 3–4 PRs, upper end ~20.** Basis:
three packages in the prior session measured 94–101 minutes of agent time each
plus 30–60 minutes of verification and CI, at ~1,200–1,500 lines and one module.
#290 is 3–4 of those.

### D — #268: the debate input is mis-priced

Body was rewritten 2026-08-22 around the measured cause; **its original
diagnosis (the `:online` web-search context) is refuted** — that context is
priced into initial-answer calls only, and those measured accurate to 1.25×. The
debate rounds, carrying no web-search context, are 2.67× and 3.23× over.

**VERIFIED structural gap:** the point estimate prices debate output at **400**
tokens (`config.py:364`) while the call site enforces **2000**
(`debate.py:546`). Also verified: `#354`'s fix added ~434 input tokens per run to
this stage, which has flipped `cost_system_prompt_tokens = 350` from an over- to
an under-estimate for debate.

**Blocked because:** setting that constant is setting a money guardrail, and the
only evidence is one production run. The issue body itself says do not adjust
constants on a guess. Confirmed unavailable for free: `/ui/ops` exposes no
per-stage actuals and the run-history store keeps no breakdown.

**The decision:** authorise a small number of live runs to get a distribution, or
leave it.

### E — #105: 5xx classified as possibly-billed on no evidence

Every 5xx is treated as possibly-billed on the premise that it can follow a
generation that consumed tokens. **There is no evidence for that premise anywhere
in the repo**, and the common `503 "No allowed providers are available"` is a
router-level refusal decided before any provider is engaged.

Measured consequence: a **4.2× overstatement** of actual cost on an otherwise
measurable run. It shipped that way deliberately — the run is labelled
`estimated`, so no false precision is served, and the opposite direction
understates a real charge under a `measured` label.

**The proper close is $0 and evidence-first:** log the status code and whether
the error body carries `error.metadata.provider_name` (its absence ⇒ no provider
engaged ⇒ unbilled) — the *shape*, not the content — then read a week of
production logs and decide.

**So E is only half-blocked**: the logging step is buildable now and costs
nothing; the decision needs a week of data. **If the human wants momentum, E's
logging half is a legitimate autonomous package.** Propose it.

---

# GATES — every package

```bash
uv sync --all-extras --python 3.12   # a bare `uv run` in a fresh worktree builds a 3.14.5 venv with NO pytest
make quality && make validate
make diff-cover DIFF_BASE=origin/main   # COMMIT first — it measures the working tree too
make api-contract
make openapi-check
make security-scan
```

Run `pytest` and `make diff-cover` **serially** — the pytest-invoking targets
rewrite the shared coverage data diff-cover reads.

**Six required contexts** (re-derive, do not trust): `validate-and-test`,
`pytest (Python 3.12)`, `Changed-lines coverage >= 95% (blocking)`,
`Schemathesis API contract (blocking)`, `FR traceability completeness (blocking)`,
`e2e axe + parity (chromium)`.

`make quality` and `make validate` do NOT cover them all. `docker-build` is
covered by nothing local.

---

# TESTS

- Test first, RED, then GREEN. **Every test ships with one line saying what turns
  it red**, proven by mutation: `cp` aside, mutate, restore from the copy,
  `diff -q`. **NEVER `git checkout <file>`** — it discards uncommitted work.
- **Capture the verbatim failure output** on first RED.
- **A negative check needs a positive partner.** "No survivor found" is trivially
  true over zero mutants; "does not claim unanimous" is satisfied by a build that
  claims nothing. **Pin the positive direction too, or the test is worthless.**
- **Accounting code asserts CARDINALITY** — how many records/rows/calls.
- Never parametrise a test over the constant it tests; never assert a bound
  against the constant defining it.
- Assert structure, not substrings — use `tests/code_text.py` to read a file.
- **Ask of every assertion: could this pass for ANY implementation?** The #354
  package's wire test initially passed a build that hardcoded the verdict —
  2795 tests green on a feature that could have shipped inert.

---

# TRAPS — all measured, all cost real time

- **The local `.env` has `OPENROUTER_LIVE_EXECUTION_ENABLED=true` with a real
  key**, and the Playwright `webServer` does NOT override it (CI pins it false at
  `e2e.yml:74`). **A local e2e run CAN BILL.** Pin it false yourself.
- **`e2e/tests/review/` makes `make quality` RED locally and green in CI** — it
  is gitignored scratch and `test_no_orphaned_e2e_specs.py` enumerates the
  filesystem. Run `ls e2e/tests/review/` before blaming your diff.
- **Repeated local e2e runs poison `.data/feedback_events.sqlite3`** → `/ui`
  429s → ~130 phantom failures. Delete that gitignored file.
- **Never run two pytest suites concurrently with a Playwright run.** It cost the
  #354 package about an hour of phantom failures. Serial, always.
- **A stale `build/mutation/score.txt` makes `make quality` red locally**
  (`unparseable artifact`). Delete `build/mutation/`.
- **The visual lane fails 8/8 on a Mac on clean `main`** — stale darwin
  baselines; CI compares linux. NOT a regression. **Never `--update-snapshots`.**
  To move a Linux baseline: `gh workflow run seed-visual-baselines.yml --ref <branch>`.
- **Do not grow `goldenCompletedResp()`** — it feeds a blocking visual lane you
  cannot re-baseline locally. Add a dedicated builder.
- **`timeout` does not exist on this macOS box.** Use
  `perl -e 'alarm shift; exec @ARGV'`.
- **`make format` reformats test assertions** and breaks `sed` anchors. Grep for
  the real text before any programmatic edit.
- **`pytest-randomly` is NOT installed** despite `-p no:randomly`. Order is
  deterministic-alphabetical.
- **Before deleting any file, run `git ls-files <path>`.** Untracked files that
  were ever `git add`ed survive as dangling blobs; check the object store before
  declaring loss.
- **A probe doing `sys.path.insert(0, ROOT/"src")` can silently measure a STALE
  copy** — especially live when the work is about a `./mutants/` copy of the tree.

---

# DECISIONS

**A decision gets an ADR in the same PR that makes it** — a default value, a
failure posture, a policy, a rejected alternative that cost real work. Next
number is **0068**; verify with `ls docs/adr/ | tail -3`. Follow ADR-0002's
shape: measured table, rejected alternatives, consequences. Regenerate with
`python3 scripts/generate_adr_index.py` — `make validate` fails otherwise.
**Never hand-edit the index.**

**Before writing code that touches money, auth or safety, list the known failure
modes first** — one page, from research and existing ADRs, then design against
that list. The spend-cap work went five review rounds because the failure modes
were discovered one at a time from defects instead of enumerated up front.

---

# MONEY — hard constraint

**Live execution is OFF and must stay OFF. Make no paid provider call.** Never
set `OPENROUTER_LIVE_EXECUTION_ENABLED=true`.

Free and encouraged: `GET https://openrouter.ai/api/v1/models` (public,
unauthenticated), `/ready`, `/status`, `/metrics`, `/ui/ops`, `/estimate`. A 401
from a bad key costs nothing. **An inference call is not free.**

If a question can only be settled by spending money, mark it **UNVERIFIED**, name
the exact check, and carry on. Do not spend.

---

# WHEN YOU STOP

After package B — or earlier if something blocks:

1. `make next && make skill-route && make handoff`
2. Write the narrative handoff to
   `docs/analysis/<YYYY-MM-DD>-session-handoff.md` (if one exists for today,
   append `-2` — never overwrite). `scripts/session_handoff.py` links the newest
   by filename.
3. Present to the human, in plain English and in this order:
   - **What shipped**, with before/after behaviour and LIVE vs LATENT.
   - **What you verified yourself** versus what a subagent reported.
   - **Every premise in this document that turned out false.** Say it loudly.
   - **The three blocked decisions (C, D, E)** with the numbers each needs.
   - **What is still open**, not tidied away.
4. Do not start C, D or E.

**Report faithfully.** If a test failed, say so with the output. If you skipped a
step, say so. If a gate was green having measured nothing, say that rather than
calling it a pass.
