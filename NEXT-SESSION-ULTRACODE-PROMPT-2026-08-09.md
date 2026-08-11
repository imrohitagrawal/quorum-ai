ultracode, autonomous

Paste this whole file as your first message. Then work autonomously.

---

## 0. The rule that governs this document

**Treat every sentence below as UNVERIFIED until you have executed it.**

AGENTS.md rule 11 records the measured decay of handoff claims here: roughly half
do not survive contact with the tree. The session that wrote this file proved it
on itself — **four confident claims collapsed when a command was finally run**,
listed in §5. Expect the same of your own.

Every factual claim ships with the command that proves it. Run it. If it
disagrees, **the sentence is wrong** — say so out loud and fix it. Never repair a
false premise silently (rule 3).

---

## 1. Read first

1. `AGENTS.md` — non-negotiable operating rules.
2. `docs/analysis/2026-08-08-pipeline-trace-and-bug-hunt.md` — **the evidence
   base for everything below.** Pipeline trace, 23 verified bugs, cost
   measurements. Untracked working doc; do not assume it is committed.
3. `docs/00-factory-console.md`

Then `make next` and `make skill-route`. Prefer installed skills.

---

## 2. Ground truth — re-derive it

True at 2026-08-09. Run the right-hand command before relying on any of it.

| Claim | Command |
|---|---|
| `main` tip `8ca6a98` | `git rev-parse --short main` |
| production runs main's tip | `uv run python scripts/deploy_drift_check.py --repo imrohitagrawal/quorum-ai` |
| **14** open issues | `gh issue list --state open --limit 60 --json number --jq 'length'` |
| 0 open PRs | `gh pr list --state open` |
| 1 stale branch + worktree (see §4.3) | `git branch; git worktree list` |
| six required contexts | `gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'` |

**Free production probes** (never cost money): `/status`, `/ready`, `/metrics`,
`/ui/ops`. A full run is **not** free — ask first.

**Paid API budget.** `OPENROUTER_API_KEY` in `.env` works and the per-key cap was
raised to $0.50 on 2026-08-08; ~$4.20 account credit remained. Check before
spending: `curl -s https://openrouter.ai/api/v1/credits -H "Authorization: Bearer $KEY"`.
**`QUORUM_EVAL_JUDGE_API_KEY` in `.env` is DEAD** — HTTP 401 "User not found".
Ask before ANY paid call. Never print a secret.

---

## 3. What the previous session shipped

**PR #282 → `8ca6a98`**, merged and verified running in production: the judge's
evidence `source_lines` are now bounded (32 lines x 300-char title x 300-char
url, spent round-robin across slots) and priced into `max_cost_usd`. ADR-0027.

Measured before the fix: 100 verbose citations produced a **1,003,263-character**
judge prompt — ~$0.25 of unpriced input on one call.

Two review rounds, 17 findings, 0 leftovers. **16 of 17 were false claims in the
diff's own prose, 1 was a code defect.** Budget for that ratio.

---

## 4. The work, ranked. Do them in this order.

**One CONCERN per PR (rule 17). Dedicated worktree (17a). Human approval before
any push / PR / merge / paid call (17b). Do NOT batch these.**

### 4.1 Grounding counts code blocks as citations — HIGH, LIVE

`evaluation.py:248` `extract_citation_markers` counts code blocks, JSON output
and array indices as citation markers. **An answer with ZERO real citations
scores grounding 1.0 and is presented as well-sourced.** This inverts the core
product claim. Reproduce it before designing the fix; then check what the trust
score and the `verified` badge do with it.

### 4.2 `/ready` can exceed Fly's health-check timeout — HIGH, LIVE

`catalog_fetcher.py:388-391`. The single-flight collapses on the fetch-FAILURE
path, so N concurrent callers each make an outbound fetch; measured ~8s against
`fly.toml`'s 5s health check. Restart-loop risk. Verify the timeout in
`fly.toml` yourself.

### 4.3 Finish the synthesis model upgrade — evidence in hand, work outstanding

Branch `fix/swap-debate-and-synthesis-models`, worktree
`/Users/rohitagrawal/Projects/quorum-wt-models`, **2 WIP commits, never pushed**.
Read `git log origin/main..HEAD` — the commit bodies carry the full measurement.

Decision taken: `synthesis_model_id` -> `openai/gpt-5-mini`, debate unchanged.

Evidence (10 golden fixtures, both models, real calls, $0.142): +70% verbatim
quotes, +167% source citations, disclaimer rule 10/10 both. Decisive case —
where all four answers agree and the prompt says *"Do not invent disagreement"*,
`gpt-4o-mini` invented two; `gpt-5-mini` said "None" and quoted why.

**What blocks it: 135 failing tests, and 77 are `assert 402 == 202`** — runs now
blocked or held for confirmation. On DEFAULT slots there is headroom (bound
0.1043 vs the 0.15 soft threshold, no crossing even at 20,000 chars); the
crossings are on expensive user-selectable mixes those tests happen to use.

That is arguably CORRECT — the runs really do cost more and the threshold exists
to make a user confirm an expensive run. **Do NOT move `SOFT_THRESHOLD_USD` to
go green.** Most failing tests are not about cost and use a query run as a
fixture; give them cheap slots so they keep testing what they were written to
test. Re-derive every literal by execution.

Then rewrite ADR-0028 for synthesis-only (it currently describes the abandoned
both-swap) and delete the stale figures.

### 4.4 The debate honesty fix — cheap, and it is a live false claim

The four models never critique each other. They are called once each, in
parallel, and never again. One moderator model reads a transcript of all four.
Verified by tracing the real pipeline.

These say otherwise — verify each with `grep` before editing:

| location | claim |
|---|---|
| `templates/workspace.html:923` | "run a query to see how the four models critique each other" — **user-visible** |
| `README.md:31` | "each model reads the others' answers and writes a critique" |
| `docs/10-functional-requirements.md:109` (FR-008) | "selected models evaluate ... the other model answers" |
| `docs/01-product-brief.md:5,33,47` | "two model critique/debate rounds" |

The precedent for honest wording already exists at `workspace.html:915` for
synthesis. Copy that treatment. FR-008 is a SPEC change — the behaviour is
fine, the specification describes something that was never built, so decide
deliberately whether to correct the spec or build to it, and record it.

### 4.5 #268's remaining half — measured, buildable

`cost_web_search_context_tokens = 2000` under-reserves. Measured n=12 on the
real API: injected context 951–2,965 tokens, mean 1,874, **over 2,000 in 6 of
12**. The design finding: ONE constant serves both the typical-case point
estimate and the worst-case bound. The bound needs a ceiling (>= 2,965 observed).
`costs.py` already does exactly this split for output tokens — follow it.

`cost_system_prompt_tokens = 350` **over**-reserves (worst real prompt 225.5
tokens). Strike it from the issue; no work needed.

### 4.6 Then work the remaining backlog, in order

The other 20 verified bugs are in the analysis doc §5 with reproductions.
Highest first: permanent account lockout (the cumulative-spend rail has no time
window); a malformed Tavily reply destroying an already-billed answer; 4 vacuous
security tests where deleting the control leaves 2,513 tests green.

**Re-run selection yourself (rule 20).** Do not recycle this list — AGENTS.md
records handoff chains narrowing the backlog while it grew. Re-triage the 14
open issues by execution, and state in one line why your pick outranks the top
of the backlog.

**Close more than you open (rule 19).** If an item is bigger than it looked, say
so and stop.

---

## 5. Traps measured 2026-08-08 — every one cost real time

Four of these are the previous session's own confidently-wrong claims.

- **Read the BLOCK a constant lives in, not the line.** "The $0.007 web-search
  fee is priced at zero — someone left it at 0.0" was FALSE. Twelve lines of
  docstring directly above (`config.py:332-353`) say it is an intentional,
  permanent exclusion (AC-037). The value was checked; the paragraph explaining
  it was not.

- **A sample that varies ONE dimension cannot support a claim spanning TWO.**
  400 random shapes were run to prove "output byte-identical below the cap" —
  the sample varied only source COUNT while the caps also truncate LENGTH. The
  measurement was structurally blind to what it was quoted as ruling out. A test
  230 lines below the claim already disproved it.

- **Cap arithmetic is not estimator arithmetic.** "The model swap is
  cost-neutral (~$0.0001/run)" was the ENFORCED-CAP maths. The app's own
  estimator says the point estimate rises **27.6%** and crosses the guardrail
  bands. Drive `cost_estimation_service.estimate`; never hand-compute.

- **Verify the INSTRUMENT before planning around it.** "`tests/evals/golden/`
  can measure synthesis quality, ~$0.50" was FALSE. Its README says the cases
  are hand-authored fixtures and the gate does **"zero I/O, zero paid calls"**.
  It is a structural regression oracle. To A/B two models, drive the real
  synthesis service and intercept `provider_execution_service.call_with_prompt`.

- **`call_with_prompt` takes `user_prompt`, not `prompt`.** Getting it wrong
  sends an EMPTY message and both models answer plausibly about nothing.
  (Side finding worth keeping: on empty input `gpt-4o-mini` fabricated a whole
  consensus; `gpt-5-mini` refused.)

- **Trace on the LIVE path or you measure the wrong pipeline.** With
  `OPENROUTER_LIVE_EXECUTION_ENABLED=false`, debate and synthesis take the
  local-simulation path and make **no calls at all**.

- **Slow your stub before concluding "sequential".** An instant stub made five
  parallel synthesis calls look like one thread. A 0.25s sleep revealed
  `synthesis-section_0..4`.

- **A merge body auto-closes issues even when negated.** "This does NOT close
  #268" CLOSED #268. Never let `close`/`fix`/`resolve` precede `#N` in any form.
  Grep the body for `-iE '(clos|fix|resolv)[a-z]* *:? *#'` before merging.

- **`make format` reflows lines and breaks mutation anchors.** Assert the anchor
  exists before mutating, or a no-op mutation reports a false pass.

- **`e2e/tests/review/` makes `make quality` RED locally, green in CI.**
  Gitignored. Run `ls e2e/tests/review/` before blaming your diff.

---

## 6. How to work

- **Ask before**: any paid API call, push, PR, merge, destructive delete. Commit
  locally freely.
- **Fan out for review, never for building** (rule 9). Two lenses (rule 10).
  Read-only reviewers, **IN CAPITALS**. Cap at two rounds (rule 12) and budget
  one for the defect your own fix introduces.
- **Tell reviewers to audit the diff's PROSE** (rule 11a), verbatim: *"for every
  number, superlative, and causal claim in the diff's comments, commit body and
  PR description, name the command that produces it — or mark it UNVERIFIED."*
  This was again the highest-yield instruction: 16 of 17 findings were prose.
- **An ADR in the same PR as the decision** (rule 16d).
- **Workflow size:** keep a fan-out under ~15 agents unless told otherwise. The
  previous session ran a 31-agent hunt without flagging the size first — the
  results were good, the consent was not asked for.

### The six merge gates

`make quality` and `make validate` do **not** cover them. Re-derive the list.

```bash
uv sync --all-extras          # NOT --extra dev
make quality && make validate
make diff-cover DIFF_BASE=origin/main   # commit FIRST; run serially after quality
make api-contract
make openapi-check
make security-scan
```

`docker-build` is covered by nothing local. Run e2e per rule 13 if you touched
UI, specs or fixtures.

### Close-out, every time (rule 18a)

1. Local gates green, every review finding resolved
2. Merge with an **explicit** squash message (rule 17c)
3. **Verify the deploy**: the deploy **JOB** ran (read the job, not the rollup —
   a merge produces several runs and some are `cancelled` by concurrency),
   `/status.build_sha` equals the merged SHA, and the thing you built fires.
   `scripts/deploy_drift_check.py` is the reliable resolver.
4. `git merge --ff-only origin/main`, delete the branch local **and** remote,
   remove the worktree

### Your first four commands

```bash
cd /Users/rohitagrawal/Projects/quorum-ai
git fetch origin && git status && git log --oneline -8
gh issue list --state open --limit 60
uv run python scripts/deploy_drift_check.py --repo imrohitagrawal/quorum-ai
```

Then re-derive §2, re-run selection, and **state in one line why your pick
outranks the top of the backlog**. If that line cannot be written honestly,
re-rank.

---

## 7. Two things only a human can do

- **`docs/00-factory-console.md` is modified** in the working tree by `make next`
  (it regenerates on every run). Decide whether to commit or discard it.
- The stale branch and worktree in §4.3 hold **unpushed** work. Do not delete
  them without reading `git log origin/main..HEAD` first.
