> **SUPERSEDED 2026-08-28 — do not execute.** This document was archived by the
> pull request that created `docs/65-open-work.md`. Its live items (W2, W3 and W4) were carried
> onto that board before it was moved here, and the board is checked against the
> tree by `scripts/check_open_work.py`. `docs/archive/` is excluded from this
> repository's doc gates, so nothing here is held to a live claim any more.
> Read it as history.

# CONTINUE — demo readiness, autonomous overnight run

Written 2026-08-26. **You are the MAIN ORCHESTRATOR. The human is asleep and will
not answer.** Drive this to completion within the scope below, then hand off.

The approved plan is `/Users/rohitagrawal/.claude/plans/i-think-you-did-quiet-stearns.md`.
**Read it first, in full.** It carries the settled decisions, their evidence, the
critical files, and the verification for each item. This file is the operating
procedure; that file is the content.

---

## FIRST — derive the state. Trust nothing written here.

```bash
git fetch origin --prune && git log --oneline -1 origin/main
git status -sb && git worktree list && git branch -a
gh issue list --state open
gh pr list
curl -s https://quorum-ai.fly.dev/status | python3 -m json.tool
ls docs/adr/ | tail -3
```

At the time of writing: `main` and production both **`34bbc64`**; working tree
clean; open issues **376, 290, 268, 105**; `live_execution: false`.

**Roughly half of what a handoff asserts does not survive contact with the tree.
Re-verify anything you depend on.**

### Check for other live sessions BEFORE dispatching anything

```bash
ps -eo pid,etime,command | grep -i claude | grep -v grep
lsof -a -p <pid> -d cwd -Fn 2>/dev/null | grep '^n'
```

On 2026-08-25 two sessions ran against this repo at once and **both created
ADR-0072**. If another session is live in this working directory, **do not start** —
write a note saying so and stop. Never kill another session.

---

## SCOPE — do these, in this order, and nothing else

| # | Work | Money? |
|---|---|---|
| A | **Item 0 — the spike.** The bound arithmetic, AND the paid timeout probe | **yes, capped** |
| B | **Item 1** — durable sessions + mint-cap fix + rendered 429 | no |
| C | **Item 2 (#376)** — the ledger distinguishes live spend from simulated | no |
| D | **Item 3** — variable panel size N ∈ {2,3,4} | no |
| E | **Item 5** — the money constants, ONLY if A's measured bound supports the approved shape | no |
| F | **Item 4 (#290)** — only if A–E are all merged AND verified in production | no |

**Stop after F.** Items 6–10 need product judgement the human owns.

**You will probably not reach F, and that is fine.** Finish whole packages; never
leave one half-merged. A half-done #290 is worse than no #290 — it is the demo
centrepiece and it retires four honesty claims that must go in the same change.
**Quality over coverage.**

### The spend authorization, verbatim

The human said, 2026-08-26:

> *"you may make up to 10 paid OpenRouter calls for the #290 timeout probe."*

That is the entire budget. **Ten calls, for the probe, and nothing else.**

---

## HARD CONSTRAINTS

- **Ten paid calls, for package A only.** Every other package spends **nothing**.
  Count them and report the actual total. If you need an eleventh, stop and write
  it down instead.
- **The probe does not touch production.** It is a standalone script calling
  OpenRouter directly — no app run, no `/ui` request, no deploy.
  **`OPENROUTER_LIVE_EXECUTION_ENABLED` stays `false` everywhere**: local `.env`,
  `fly.toml`, and production. Do not flip it, not even briefly.
- **Package E is conditional.** If A's measured bound is close to the plan's
  expectation, move the three constants to the approved shape (`SOFT ≈ $0.20`,
  `DAILY_CAP ≈ $0.60`, `HARD ≈ $0.75`, global unchanged at `$5.00`), preserving
  `SOFT < DAILY_CAP < HARD`. **If the measured bound is materially different from
  what the plan assumed, do NOT improvise a new shape — stop, record the number,
  and leave the constants alone.** A guardrail set from a surprise is a guess.
- **Package F is conditional** on A–E being merged and deploy-verified.
- **Never** `git clean -fdx` / `-fd` / `git stash -u`. Delete named paths only.
- **Never force-push.** Never delete a branch or file you did not create.
- **Do not touch** `AUTONOMOUS-WORK-LOOP-ULTRACODE-PROMPT.md` or the
  `quorum-ai-wt-ledger` worktree — another session's, left deliberately.

---

## THE PROTOCOL — one sub-orchestrator per package

You may push, open PRs, merge and deploy. **Sub-orchestrators may not merge.**

### Before dispatch, assign shared resources centrally

A worktree isolates *files*, not *namespaces*. You assign:
- **ADR numbers** — tell each sub-orchestrator its number explicitly. Regenerate the
  index with `python3 scripts/generate_adr_index.py`; never hand-edit it.
- **`openapi.yaml`** — only one package may hold it at a time.
- Issue numbers for anything newly filed.

### Each sub-orchestrator

1. Dedicated `git worktree` off `main`; merge `main` in first. Never the main checkout.
2. **Fan out 2–4 READ-ONLY planners** before any code exists. For money or auth
   work, enumerate the failure modes on one page first.
3. **Build as the sole writer.** Never fan out for building — subagents share one
   tree.
4. **Review with TWO lenses, not five.** One correctness lens, plus one adversarial
   lens chosen from what the diff touches:
   - money rails (C, D) → break the rail: find spend that escapes a meter
   - auth/session (B) → break the session: forge, replay, bypass identity
   - any user-visible change → the copy: find a claim the product cannot back

   Tell every reviewer **IN CAPITALS** that reviews are READ-ONLY: no writing,
   editing, `git checkout`, `git stash`, `sed -i`. A reviewer that must mutate gets
   its own copy (`git archive HEAD | tar -x -C <dir>`).

   Tell every reviewer verbatim: *"for every number, superlative, and causal claim
   in the diff's comments, commit body and PR description, name the command that
   produces it — or mark it UNVERIFIED."*

   Cap at **TWO rounds**, then stop and escalate with open findings listed. Budget a
   round for your own fix introducing a defect.
5. Run the gates; report each gate's **measured number**, not its colour.
6. Hand back a **green PR**. No merge.

### You verify independently before merging — non-optional

1. **Spot-check TWO claims by re-running them yourself.** Default to the highest
   consequence pair: the mutation/bite proof, and a gate's number read from its own
   log.
2. **Diff the implementation against the plan's own list and count.** Green measures
   what was built; it cannot measure what was omitted.

Then merge with vetted text:

```bash
PR=<n> EXPECT_CLOSE="<issues this closes, comma-separated, or empty>" \
  MERGE_SUBJECT="..." MERGE_BODY="$(cat body.md)" make close-guard
gh pr merge <n> --squash --subject "..." --body "$(cat body.md)"
```

`make close-guard` changed on 2026-08-25 (#375): it now **refuses** unless intended
and actual closes match in both directions. A close keyword next to `#N` closes that
issue and the parser cannot read negation.

### Close out, every time, in this order

1. Merge. 2. Verify the deploy **three ways** — the deploy **JOB** ran (not
`skipped`/`cancelled`; read the job, not the run rollup), `/status.build_sha` equals
the merged SHA, and the thing you built actually fires. 3. `git merge --ff-only
origin/main` from the main checkout. 4. Remove the worktree FIRST, then delete the
branch (local and remote).

---

## STOP CONDITIONS — write it down and move on, or halt

**Halt the whole run and write a handoff** if:
- Another live session is working in this repo.
- Two fixes in a row introduce defects — change approach or stop.
- A gate is red for a reason you cannot attribute, twice.
- Anything would require spending money or moving a guardrail value.
- Production `/status` stops matching `main` after a merge you made.

**A briefed premise turning out false is a SUCCESS, not a failure.** Say so loudly,
record it, and re-plan. Three sub-orchestrators did exactly that on 2026-08-25 —
twice improving a design, once correctly refusing to build at all. Brief yours to do
the same.

---

## GATES

```bash
uv sync --all-extras --python 3.12   # a bare `uv run` builds a 3.14.5 venv with NO pytest
make quality && make validate
make diff-cover DIFF_BASE=origin/main   # COMMIT first — it measures the working tree too
make api-contract && make openapi-check && make security-scan
```

Run test and coverage-diff targets **serially**. Re-derive the required contexts
from branch protection; never trust a list:

```bash
gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'
```

### Traps, all measured

- **`e2e/tests/review/` exists in the MAIN checkout** (3 specs) and makes
  `test_no_orphaned_e2e_specs` RED locally while green in CI. A fresh worktree lacks
  it. Check `ls e2e/tests/review/` before blaming your diff.
- **`tests/unit/test_mutation_copy_completeness.py::test_the_real_copy_runs_the_root_reading_specs`
  fails on clean `main` locally** and is green in CI. Verify against `main` before
  attributing it to your change.
- `timeout` does not exist on this box. Use `perl -e 'alarm shift; exec @ARGV'`.
- Never run two test suites concurrently.
- Python on this box fails SSL verification against the live hosts; use `file:`
  fixtures for local runs of any checker that probes production.
- Every test ships one line saying what turns it red, **proven by mutation**: `cp`
  the file aside, mutate, restore from the copy, `diff -q`. **Never
  `git checkout <file>`** — it discards uncommitted work.

---

## PACKAGE NOTES

**A — the spike. Two halves; do the free one first.**

*A1, free.* Compute `max_cost_usd` for the N=4 shape with **8** debate calls at
`cost_debate_output_tokens_cap = 2000`, against the pinned
`point 0.0547 / bound 0.1043`
(`tests/integration/test_query_run_cost_guardrails.py:55`). Record the number and
whether it crosses `SOFT_THRESHOLD_USD = 0.15`. **Change no constant here.**

*A2, the paid probe — max 10 calls.* A standalone script, not the app.

- Call **each of the four default slot models** — `openai/gpt-4o-mini`,
  `anthropic/claude-haiku-4.5`, `google/gemini-2.5-flash`,
  `nvidia/nemotron-3-nano-30b-a3b` (`model_slots.py:63-68`). **With #290 the critics
  are the ANSWER models, not `debate_model_id`** — probing only the moderator
  measures the wrong thing.
- `max_tokens=2000`, and a prompt that **genuinely produces ~2000 tokens**. Ask for
  a long, structured critique of a supplied passage.
- **Measure wall-clock to the LAST byte, not the first.** ADR-0037's earlier probe
  measured time-to-first-byte on a 7–10 token reply and settled nothing; its own
  text says so. Do not repeat that.
- Two repeats per model = 8 calls, leaving 2 spare. Report **completion tokens and
  actual cost per call**, and the total.
- The question: does a 2000-token critique finish inside
  **`openrouter_timeout_seconds = 8.0`**? Every timeout is classified
  possibly-billed and demotes a run's receipt from "measured" to "estimated".

**Record the result on #290 as a comment**, with the per-model table. If any model
exceeds 8s, say plainly that #290 needs streaming or a lower cap **before** the
feature is built, and do not start package F.

Use the local key from `.env` (present, `sk-or-v1…`). Never print it, never commit
it, and keep it out of any file you write.

**B — durable sessions.** Create the table in the **guarded** `schema_migrations`
block (`feedback_store.py:270-284`), **never** in the unguarded `_SCHEMA` — that
mistake makes the first open of an existing read-only DB raise and the app fail to
start. Fall back to in-memory when the path is not writable. A resumable identity
must not consume a mint.

**C — #376.** Read the issue's correction comment first: `/status.global_daily_spend_usd`
counts **simulated** runs at their estimate. Prefer a **new event type** over a
payload filter — it excludes the run from both meters at five call sites by
construction and matches the module's existing idiom.

**D — variable panel size.** Two cost edits: delete `costs.py:1551-1552`, and change
`Decimal(4)` → `Decimal(len(model_slots))` at `costs.py:1615`. Three literal
`Field(ge=1, le=4)` bounds move together: `debate.py:209`, `debate.py:1268`,
`providers.py:320`. **N=1 stays blocked** — it is item 6 and needs its own guard.
The `>= 3` bars (`synthesis_consensus.py:322`, `:420-425`) must become fractions of N.

---

## WHEN YOU STOP

1. Write `docs/analysis/2026-08-26-session-handoff.md` — what shipped, what is
   verified in production, what is open, what you could not verify and the exact
   command that would settle it. Then run `make handoff`.
2. Leave the tree clean and synced: nothing unpushed, no stray branches or
   worktrees, the same untracked files you started with.
3. Report in this shape, as the last thing you do:

```
## Done
## Verified myself      (the command, and what it printed)
## Cleanup              (each line confirmed by a command)
## Pending              (nothing tidied away)
## Next action          (or the decision now owed by the human)
```

Say explicitly whether work is **pushed**, **merged**, and **running in
production** — never leave it inferred. Keep what YOU ran separate from what a
subagent reported. If a gate was green having measured nothing, say that rather
than calling it a pass.

**The human's first question on waking will be "what is safe to look at, and what
needs me?" Answer that first.**
