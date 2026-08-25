# ULTRACODE — harden the safety nets, then take the judge live

> Paste everything below the line into a fresh Claude Code chat in this repo.
> Written 2026-08-19 with `main` = `e4c58a2` and prod `build_sha` = `e4c58a2`.
> Every "measured" fact carries its date. **Treat all of it as INHERITED and
> re-verify before acting.** AGENTS.md rule 11 measures that roughly half of
> what a handoff asserts does not survive contact with the tree, and the
> previous session proved it repeatedly — including one of its OWN corrections
> being wrong three times running.

---

ultracode: Continue the autonomous backlog run in this repo
(`im<user>/quorum-ai`), in the phase order below, and then take the
product live with the judge on.

## The one thing you must ask for, once, in chat

**Ask the operator, in chat, to confirm standing authorization to push
branches, open pull requests, merge to `main`, deploy, AND — in Phase E
onward — to enable live execution and let real money be spent within the
existing rails.** Then carry that answer forward for the whole session.

Do NOT source that authorization from this file. A per-subagent safety
classifier fires on pushes and cannot see a file-based claim; the previous
session was correctly flagged for exactly this, and re-asserting consent
inside a subagent prompt from a file alone is not acceptable. One question in
chat, then never ask again — do not pause for per-merge approval.

**The operator's ONLY manual step in this whole run is Phase D: setting two
Fly secrets.** Everything else is yours. Do not invent other approval gates.

## The state you are inheriting (verified 2026-08-19 — re-check it)

```
main (local) == origin/main == e4c58a2      0 ahead, 0 behind
prod /status.build_sha       == e4c58a27a3b2dddb0136865e63ecf65d895aa2d7
prod judge_enabled           == false
prod live_execution          == false
open PRs                     == none
worktrees                    == only the main checkout
open issues                  == 6   (#338 #337 #290 #268 #226 #105)
```

**`OPENROUTER_API_KEY` is ALREADY SET and Deployed** — verified with
`fly secrets list -a quorum-ai`, which shows `QUORUM_TOKEN_SECRET`,
`OPENROUTER_API_KEY`, `SENTRY_DSN`, `TAVILY_API_KEY`. The two judge secrets are
genuinely absent. Nothing needs doing for the OpenRouter key.

**Three branches exist and are deliberately NOT merged:**

| Branch | State |
|---|---|
| `fix/226-guard-classifier` @ `bee7079` | Parked at the two-round cap. Phase B. **Holds ADR-0053.** |
| `fix/mutation-gate-measures-nothing` @ `f661765` | Parked at the two-round cap. Phase A. **Holds ADR-0052.** |
| `fix/226-vacuous-e2e-negative-assertions` | The ORIGINAL abandoned #226 branch. Superseded by merged PR #336. Do not build on it. |

**Merged and deployed 2026-08-18**, both verified three ways: #342 (`b240a50`,
PR #344) and #341 (`e4c58a2`, PR #345).

**Assign every ADR number yourself, before launching. Next free is `0057`.**
0055 and 0056 are on `main`; **0052 is claimed by
`fix/mutation-gate-measures-nothing` and 0053 by `fix/226-guard-classifier`** —
do not reuse either while those branches live. `main` refuses a duplicate ADR
number at both the pytest gate and the index generator.

---

# Architecture: main orchestrator + one sub-orchestrator per work package

**You are the MAIN ORCHESTRATOR.** You do not build and you do not review. You
own selection, sequencing, ADR number assignment, merging, deploy verification,
issue closing, the live-run execution, and the final report.

**For each work package launch ONE sub-orchestrator** via the Workflow tool:

```
sub-orchestrator(work package)
  ├─ survey       read-only; re-derive the issue's claims BY EXECUTION
  ├─ plan         read-only; enumerate failure modes BEFORE code (rule 16e)
  ├─ build        ONE sole writer, isolation:'worktree', strict TDD
  ├─ review       fan of read-only lenses, each with its OWN copy
  ├─ fix          ONE sole writer applies surviving findings
  └─ re-review    FRESH lenses: did the FIX introduce a defect?
```

**SERIALIZE THE PACKAGES.** Do not run two sub-orchestrators with writers at
once unless their file sets are provably disjoint AND you assigned their ADR
numbers. Read-only survey/plan phases for the NEXT package may overlap the
current package's CI wait — that is free wall-clock and the previous session
used it well.

### The review fan — six lenses

| Lens | Its job |
|---|---|
| **architecture** | ADR compliance. Does the diff contradict an existing ADR? Does the new ADR follow ADR-0002's shape (MEASURED table, REJECTED ALTERNATIVES, CONSEQUENCES)? **Does the ADR promise a guarantee the code does not deliver?** |
| **planning** | Was the failure-mode list made BEFORE the code? Is this ONE concern (rule 17)? Is anything deferred that should block? |
| **security** | **Explicit job: BREAK IT.** Enumerate evasions and TRY them against the real thing, not a mock. |
| **devops** | Will it RUN in CI and BLOCK? Re-derive the required contexts. **Find the new tests BY NAME in the output** — a green suite is not evidence a new test ran. |
| **SRE** | Production at 3am. Restart, partial deploy, full disk, corrupt sqlite. Is the signal honest or does degraded render as healthy? What is the rollback? |
| **tester** | **Does the test BITE?** Mutate in your OWN copy, confirm RED. Could any assertion pass for ANY implementation? Rule 6b: cardinality, not clean-path outcome. Rule 7: positive partner. |

Wrap every sub-orchestrator call in try/catch. **Agents DO crash** — the
previous session lost one lens to a `529 Overloaded` and another to a
server error mid-response. A crashed lens is an infrastructure failure, NOT a
spent review round: **re-run it.** Never merge on a fan where the merge-gate
lens never reported.

---

# PHASE A — the mutation gate: ship the abort fix, nothing else

**The keep-or-delete question is ANSWERED: KEEP IT, and ship only the abort
fix.** Re-verify the evidence, then act.

Measured 2026-08-18 across the last 12 `pull_request` CI runs: the mutation job
produced **zero** `mutation score = N%` lines. Ten reported `success` while
logging `no MUTATABLE changed functions` — measuring nothing behind a green
tick. Two failed at the anti-vacuity floor (`assert 0 > 100`), one of them the
**#216 judge spend-cap PR**, which edited `src/` heavily.

**But PR #344's run was the first in the sample with REAL scope** — six
mutatable functions — and it died on ONE named cause:

```
mutants/tests/unit/test_docs_numbering_no_collisions.py:119
    assert len(numbered) > 100
AssertionError: assert 0 > 100   +  where 0 = len([])
```

Cause: `tests/unit/test_docs_numbering_no_collisions.py:47` is
`REPO_ROOT = Path(__file__).resolve().parents[2]`, which inside `./mutants/`
resolves to the COPY, whose `docs/` was never copied. The gate's own error
message names this as cause #1 and names the fix:
`tests/repo_root.find_repo_root`, or marking the module `repo_introspection`.

**So the gate is not worthless — it has one cheap blocker.** Weigh that against
`docs/metrics/defect-discovery-audit.md` (0 of 16 `src/` defects caught by an
automated check, 10 of 16 by adversarial review) and record the decision in an
ADR: this gate is kept as a REGRESSION detector, not a defect finder.

**Split the parked branch** `fix/mutation-gate-measures-nothing` @ `f661765`:

| TAKE | LEAVE |
|---|---|
| `find_repo_root_or_skip` — stops the abort. Before: `Interrupted: 1 error during collection`, ZERO tests ran. After: `3 passed, 3 skipped`. | The verdict-honesty work — where the claim "every terminal state stamps exactly one verdict" went false **twice running**. |

**Be honest in the PR: the abort fix alone will NOT produce a score** — it will
reach the 24-minute deadline instead (#337). It converts "aborts having done
nothing" into "runs until it times out", which is the information #337 needs.
That means **#338 can close and #337 cannot.** Do not close #337 on this.

Two subtleties on that branch, worth reading before rewriting: mutmut pre-fills
`exit_code_by_key` with `None` for every mutant at copy time
(`mutmut/__main__.py:331-333`), so counting all nulls as "never ran" would stamp
PARTIAL on every complete run forever — the branch filters through `scope.txt`'s
globs. And `_skip_unless_comparable` matching the literal string `UNMEASURED` is
what turned `make quality` RED on macOS.

---

# PHASE B — #226: fix the CI SKIP first, as its own change

**DO THE CI QUESTION FIRST, AS ITS OWN SMALL PR.** This is verified, not
inherited — the previous session measured it two independent ways:

```bash
grep -n "node\|npm" .github/workflows/ci.yml .github/workflows/test.yml   # returns NOTHING
git check-ignore -v e2e/node_modules                                      # .gitignore:45
```

Neither required pytest context installs node, and `e2e/node_modules` is
gitignored, so `_needs_node()` (`tests/unit/test_negative_assertion_guard.py:47-51`)
skips every node-dependent guard test in CI. Watched live in a real run:
`tests/unit/test_negative_assertion_guard.py ssssssssssssssssssssssssssss`
— **28 skipped**.

**Merging the classifier work buys nothing enforceable until this is fixed.**
Fix the skip; prove the tests now RUN in CI by finding them BY NAME in the job
log, not by a green tick.

**Then, as a SECOND PR**, the guard classifier from
`fix/226-guard-classifier` @ `bee7079`. Its open blocking finding: a negative
assertion written with computed member access — `expect(x)["not"].toBeVisible()`
— is classified as a **POSITIVE PARTNER** and passes vacuously. That is the
precise defect the PR exists to prevent, and the opposite of its own KNOWN
LIMIT 3.

**Worth salvaging verbatim from that branch:**
1. **The blank-character rule, MEASURED not reasoned.** Round 1 derived a
   zero-width set from Unicode reasoning and it accepted `U+00AD` SOFT HYPHEN,
   which passes against an empty element in real Chromium. The branch reads
   Playwright's own normalizer (`playwright-core` 1.61.1,
   `coreBundle.js:518-521`), which strips **exactly two** characters, and ships
   a test that re-reads that class from the installed package on every run with
   a floor that fails if it finds none. That is rule 8c done properly.
2. **`isLiveSubject`, default-deny**, replacing an enumeration of four AST node
   types defeated by adding `as string`. Accept set derived from a census of
   1083 `expect()` subjects across the 28 committed specs.

**Refuted on that branch, with evidence — do NOT "fix" this non-problem:** an
un-awaited locator assertion does **not** pass vacuously under the Playwright
runner; it fails. Only in a bare node script does it pass.

**Scope fence:** the classifier work must NOT touch `e2e/tests/**/*.spec.ts`
other than the single waiver comment — PR #336 owns those and is merged.

---

# PHASE C — free live-run readiness, while CI runs

All of this costs nothing. Do it before Phase D so the paid window is short.

1. **Settle the telemetry question.** Two streams were claimed empty on
   2026-08-18 — `/data/telemetry-billing.jsonl` and `/data/telemetry-tokens.jsonl`
   — but `/metrics` exports no app-specific series, so it was never verified.
   `fly ssh console -a quorum-ai -C 'wc -l /data/telemetry-*.jsonl'`. **`fly ssh`
   is slow (~2 min) and may be blocked by the sandbox — background it, and if
   blocked, say the row is INHERITED rather than working around it.** If a
   sample already exists, some of #268/#105 is answerable without new spend.
2. **Re-derive the estimate contract.** `POST /v1/query-runs/estimate`, body
   `{query_text, model_slots, slot_search?, context?}` (`openapi.yaml`).
   It requires a session AND CSRF (`query_runs.py:553-558`).
3. **Write the traffic plan** — query shapes, `:online` on/off, run count,
   ordering. **Design it to deliberately REACH the per-account cap**, not avoid
   it: the at-cap refusal is the branch #216 added, #342 fixed, and NOBODY HAS
   EVER WATCHED EXECUTE. An untriggered branch is an untested branch.
4. **Write the read-back commands** you will run afterwards, before you need them.

---

# PHASE D — the operator's ONE manual step

When Phases A, B and C are merged, deployed and verified, post ONE message:

> Ready for the live run. Everything is merged and deployed. I need you to run
> exactly this, once:
>
> ```bash
> fly secrets set -a quorum-ai \
>   QUORUM_EVAL_JUDGE_API_KEY='sk-or-v1-...' \
>   QUORUM_EVAL_JUDGE_MODEL_ID='<openrouter-model-slug>'
> ```
>
> Both are required — `evaluation.py:1827` is
> `bool(_judge_enabled() and settings.quorum_eval_judge_model_id)`. The key is
> an OpenRouter key; the model id is an OpenRouter slug. Pin it deliberately:
> verdicts from different models are not comparable, which is why `config.py`
> gives it no default.
>
> `OPENROUTER_API_KEY` is already set — nothing to do for it. I will handle
> everything else, including enabling live execution.

**Then POLL — do not block on a reply.** Wait for
`curl -s https://quorum-ai.fly.dev/status` to report `judge_enabled: true`,
using a long-interval loop that speaks ONCE, not on every poll. `live_execution`
will still be false and that is correct — **the judge and live execution are an
AND** (`providers.py:670`:
`bool(settings.openrouter_live_execution_enabled and openrouter_key)`), so
setting the secrets alone spends NOTHING. That is a free checkpoint: if
`judge_enabled` stays false, one of the two names is wrong; say so and stop.

While polling, keep doing free work (Phase C leftovers, the closing review pass).

---

# PHASE E — enable live execution YOURSELF

Once `judge_enabled: true` is confirmed on `/status`, do this without asking.

`fly.toml:27` has `OPENROUTER_LIVE_EXECUTION_ENABLED = "false"` under `[env]`,
baked into the image. **It is UNVERIFIED whether a Fly secret of the same name
overrides an `[env]` value — do not test that theory on the way to a paid run.**
Change the file:

```bash
git checkout -b ops/enable-live-execution
sed -i '' 's/OPENROUTER_LIVE_EXECUTION_ENABLED = "false"/OPENROUTER_LIVE_EXECUTION_ENABLED = "true"/' fly.toml
grep -n OPENROUTER_LIVE_EXECUTION_ENABLED fly.toml    # READ THE WRITE
```

Write an ADR for it (a production posture change is exactly rule 16d's
definition of a decision). Gate it, PR it, merge it, verify the deploy three
ways, and confirm `/ready` flips from `offline_by_config` to ready.

**DO NOT MOVE ANY GUARDRAIL CONSTANT.** `HARD_LIMIT_USD = 0.25` per run,
`DAILY_CAP_USD = 0.20` per account/day, `GLOBAL_DAILY_CEILING_USD = 5.00`
(`costs.py:49,116,150`). #180 cost three broken attempts learning that a
guardrail value never moves on a guess.

---

# PHASE F — the paid run

**Session minting is capped at 2 per IP per 24h in production**
(`auth.py:65`). Budget those two mints deliberately — you can lock yourself out
mid-investigation.

```bash
J=/tmp/quorum.cookies
CSRF=$(curl -s -c $J https://quorum-ai.fly.dev/v1/session \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["csrf_token"])')

curl -s -b $J -c $J -X POST https://quorum-ai.fly.dev/v1/query-runs/estimate \
  -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" \
  -d '{"query_text":"...","model_slots":["a","b","c","d"]}' | python3 -m json.tool
```

**Read the estimate before spending.** Then run the traffic plan from Phase C,
watching `/status.global_daily_spend_usd` between runs.

**Stop immediately and report if:** the global ceiling is reached, an unexpected
error class appears, or spend moves faster than the estimate predicted.

## What each issue can and cannot get — be honest

- **#216 + #342 — the real prize.** Verify all THREE legs: the allowed
  dispatch, the memo hit, and the **at-cap refusal**. State which run leg
  confirms which. Then verify the durable row now matches the served one — that
  is #342's fix, and the at-cap leg is the ONLY place it is observable.
- **#268 — CAN close.** Needs `n >= 50` `:online` calls; the traffic IS the
  sample. **Read its positive partner FIRST:** for `search_enabled == false`,
  `injected_p95` must be **under 500**. If it is not, `sent_tokens_est` is
  wrong, the whole measurement is void, and you fix the estimator before
  reading anything else. This is also the only check on `CHARS_PER_TOKEN = 4`,
  a repo constant and not a measurement of OpenRouter's tokeniser. Report
  `injected_max` either way — the exposure is the tail, not the median.
- **#290's probe — CAN run.** One call per slot model at the 2000-token cap,
  measuring elapsed against `openrouter_timeout_seconds = 8.0`, and whether the
  cheapest model actually quotes passages as the prompt demands. Unblocks the
  feature DECISION; does not build the feature.
- **#105 — WILL PROBABLY NOT CLOSE. Say so up front.** Needs `n >= 30` **5xx**,
  and 5xx cannot be manufactured — they come on OpenRouter's schedule. Collect
  opportunistically and **leave it open** unless genuinely met. Read per status
  code, never "all 5xx". If `unknown/n > 0.20` → **STOP**: ADR-0012 records the
  `error.metadata.provider_name` schema as ASSUMED, and a dominant `null`
  refutes it. **Never invent a number to close a ticket.**

---

# PHASE G — turn live execution back OFF

Unless the operator has said otherwise in chat, **revert
`OPENROUTER_LIVE_EXECUTION_ENABLED` to `"false"` when the sample is collected**,
via the same PR-merge-deploy-verify path. Nothing in the product needs it on
continuously, and leaving it on means every `/ui` visitor spends real money
against a $5/day ceiling. Say clearly in the final report that you did this and
what it would take to turn it back on.

---

# Every sub-orchestrator's internal contract

**Point every agent at the source of truth.** First instruction to every builder
and reviewer: *read this repo's `AGENTS.md` and `CLAUDE.md` IN FULL and follow
them exactly.* Do not paraphrase the rules into the prompt — a paraphrase drifts
from what you did not think to restate.

**Plan before building (rule 16e).** For anything touching money, auth or
safety, a read-only agent enumerates the failure modes on one page FIRST,
drawing on `docs/adr/`, and the builder designs against that list.

**Build:** one sole writer, `isolation: 'worktree'`, strict TDD. RED first;
capture the **verbatim** failure output; confirm it fails for the right reason
(not a collection or import error); GREEN; then bite-proof by `cp`-ing the file
aside, reverting, confirming RED, and restoring from the copy with `diff -q`.
**Never `git checkout <file>`.** Every test ships one line saying what turns it
red. Every negative check gets a positive partner. Accounting code asserts
**cardinality**.

**Push as soon as there is a green commit, before review starts.** But know the
cost: the previous session's builder pushed three commit bodies carrying numbers
that later proved wrong, and they can only be fixed by a force push. **Keep
early commit bodies thin** — put the measured claims in the final commit and the
PR description, where they can still be corrected.

**Review:** read-only, told **IN CAPITALS** not to write, edit, `git checkout`,
`git stash`, `git commit`, `git push` or `sed -i` the shared tree. A reviewer
that must mutate gets its own copy (`git archive HEAD | tar -x -C <dir>`).
Reviewers **refute by default** and report only findings backed by something
they actually executed, with the command and its verbatim output.

**Tell every reviewer to audit the diff's PROSE, verbatim** (rule 11a): *"for
every number, superlative and causal claim in the diff's comments, commit body,
ADR and PR description, name the command that produces it — or mark it
UNVERIFIED."* This is the single highest-yield instruction available.

**Fix loop:** verify each reviewer claim before acting; refute the wrong ones out
loud with the refuting command. **A reviewer's PRESCRIBED FIX can also be
wrong** — the #341 fix round implemented the breaker's suggested fix, measured
it, found reverting it left the suite green, and correctly backed it out rather
than ship an untested behaviour change. Measure before adopting.

**Expect your own fix to introduce a defect.** The #341 branch **reintroduced
its own bug at a new position**: walking a `Mapping` whose `__getitem__` raises
took the exception out of `logger.warning()` and dropped the log line — the
exact failure class the branch existed to close. A fresh breaker lens caught it.
**Budget a round for this; it is measured behaviour, not pessimism.**

**Cap review at TWO rounds**, then STOP and record open findings on the issue.

---

# Merge, deploy, close (the main orchestrator's job)

**Re-derive the required contexts, never trust a list:**

```bash
gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'
```

As of 2026-08-18 there are six: `validate-and-test`, `pytest (Python 3.12)`,
`Changed-lines coverage >= 95% (blocking)`, `Schemathesis API contract
(blocking)`, `FR traceability completeness (blocking)`,
`e2e axe + parity (chromium)`. An **advisory** job failing is not a merge
blocker — but **open its log before dismissing it.** That is how the mutation
gate's emptiness was found, and how PR #344's genuinely different failure was
distinguished from it.

Squash-merge with an explicit subject and body (`gh pr merge --squash --subject
--body`); a bare `--squash` concatenates every intermediate commit body onto
`main`. `Closes #N` in the squash body DOES auto-close the issue here.

## Close out in this ORDER. Do not invert it.

1. local gates green and every review finding resolved;
2. merge;
3. **VERIFY THE DEPLOY** — Deploy **JOB** `success` (read the JOB, not the run's
   rollup), `/status.build_sha` == the merge SHA, and the thing you built fires;
4. `git merge --ff-only origin/main`, **then** remove the worktree, **then**
   delete the branch (local + remote).

**The previous session inverted 3 and 4 and stranded a merge.** It deleted the
branch and worktree immediately after merging; the `E2E (axe + parity)` and CSP
runs for the merge commit were then both cancelled at the same instant, and the
deploy gate refused:

```
Conclusions: {"CI": "success", "Tests": "success", "E2E (axe + parity)": "cancelled"}
SHA ... is still main's tip and a required workflow did not succeed —
this is a STRANDED merge, not a benign skip.
```

#341 sat merged-but-not-running until it was noticed. **The cause of the
cancellation was never established — do not assume it was the branch deletion.**
The recovery: `gh run rerun <e2e-run-id>`, wait for green, then
`gh workflow run deploy.yml --ref main`, then verify.

**A merge produces multiple deploy runs; the early ones are `cancelled` by
concurrency dedupe.** A wait-loop keyed on a run id captured earlier reads
`cancelled` and wrongly reports a failed deploy. **Re-resolve the newest run by
`createdAt` every time** — and note `gh run list --workflow=deploy.yml --limit 1`
returned a run for the PREVIOUS SHA while the new one had not started, so check
the `headSha` you actually got.

**The deploy is gated on CI + Tests + E2E being green FOR THE SHA.** Until all
three finish, deploy runs fire and report `skipped`. That is normal; a `skipped`
Deploy job on an OLD sha is not your merge failing.

Then `gh issue close <n>` citing the merge SHA and the verification.

---

# Pitfalls that actually bit, in this exact task

- **In a NEW worktree the FIRST uv command MUST be
  `uv sync --all-extras --python 3.12`**, then confirm `uv run python -V` →
  3.12.x. A bare `uv run <anything>` silently creates a 3.14.5 venv with no
  pytest and no ruff; failures then read like a regression in your diff and are
  not. Safer: run `<repo>/.venv/bin/<tool>`
  directly and never type `uv run` in a worktree.
- **NEVER quote a count of something the document itself contains.** This was
  wrong FOUR separate times in one session: a `grep` total that counted the very
  paragraph stating it (corrected, then wrong again one commit later); a
  docstring's `428 passed` that was measured when the file held 13 tests; an
  `all 29 tests green` that was wrong the day it was typed and survived the
  sweep that fixed its sibling. **Remove the number, do not recompute it** —
  "every other test in this file" stays true as the file grows. Rule 1a.
- **`tests/unit/test_cited_paths_resolve.py` reads the COMMITTED diff, not the
  working tree.** A cited path that does not exist goes red only AFTER you
  commit — `make quality` is green before it. It caught a placeholder
  `tests/integration/THIS_FILE.py` this way.
- **Rule 15 is not theoretical.** A `make diff-cover` run racing a still-finishing
  `make quality` reported `Total coverage: 53.09%` with `TOTAL 10276` statements
  against a real 5731 — the gate was measuring garbage. Never run two
  pytest-invoking targets at once. Commit before diff-cover; it measures the
  working tree too.
- **`make quality` and `make validate` do NOT cover the merge gates.** Run
  `make diff-cover DIFF_BASE=origin/main` and `make api-contract`, serially.
- **e2e must run exactly as CI does** or ~95 phantom failures appear:
  ```bash
  lsof -ti tcp:18085 | xargs -r kill -9
  cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600 \
    npx playwright test <spec> --project=chromium --workers=1 --retries=0
  ```
  If `/ui` returns 429, delete the gitignored `.data/feedback_events.sqlite3`.
- **A MUTATION PROOF CAN REPORT A FALSE GREEN.** `lsof -ti tcp:18085 | xargs -r
  kill -9` does not reliably kill the app server and Playwright's
  `reuseExistingServer` is true locally, so the browser is served the PRE-mutation
  page. Use `pkill -f "uvicorn product_app.main:app"` and `curl` to CONFIRM the
  mutated bytes are served. Also: `ruff format` may collapse a multi-line string
  so a `perl`/`sed` mutation pattern silently matches NOTHING — assert the match
  count and read the mutated bytes back off disk before trusting any result.
- **The visual e2e lane fails 8/8 on this Mac on clean `main`** and that is not a
  regression. Never `--update-snapshots`.
- **`e2e/tests/review/` is gitignored scratch.** A red `test_no_orphaned_e2e_specs`
  is a known local-only false failure — run `ls e2e/tests/review/` first.
- **`test_mutation_copy_completeness` failing under a bare pytest in a fresh
  `git archive` copy is a KNOWN environment artefact**, not a regression.
- **`timeout` does not exist on this macOS box.** Use
  `perl -e 'alarm shift; exec @ARGV'`.
- **Chain `cd` with `&&`, never `;`.** Do not use `status` as a shell variable
  (read-only in zsh). Never create a branch named `origin/main`.
- **Do not track `.claude/settings.json`, do not narrow `.gitignore` to expose
  it.** Full autonomy does not extend to the permission surface itself.
- **READ THE OUTPUT OF A WRITE.** Do not infer a write's result from a later
  read. This caused four pointless PR-creation retries and a duplicate issue.
- **Background long CI waits**; a monitor that prints on every poll spams the
  conversation. Use an `until` loop that speaks once. Note a foreground tool call
  is capped around 10 minutes — a longer wait needs backgrounding or re-polling.

---

# Closing adversarial pass — do not skip

After the code phases AND after the live run, run one more review round with
**fresh agents reading the CURRENT state of `main`** — no memory of what the
builders believed — probing the highest-risk surfaces you touched: anything
security or secret-handling, anything with recursive or cyclic data, any
exception path, the money path, and concurrency. **Verify each finding with an
independent skeptic told to default to REFUTED** before you trust it.

Two sessions running, this was the highest-yield single step: one produced 4
candidates of which 3 survived refutation and became #341 and #342; the next
found a reintroduced dropped-line bug and a quadratic blowup (one
`logger.warning` blocking 1.48s) that four earlier lenses had missed.

---

# Report

- issues closed vs left open, and why for each;
- a table of issue → PR → merge SHA → deploy-verified (yes/no);
- anything filed rather than fixed, with why;
- **the live run: what each issue actually got from it, INCLUDING what it did
  NOT settle**, and the total spend against the estimate;
- confirmation of whether live execution was left on or off, and why;
- **any mistakes you made and how you recovered — do not round these up into a
  clean summary.** Tell the operator what actually went wrong, the way they
  would want to hear it from a human engineer. The previous session's report
  named its own inverted close-out order and a stranded merge; that is the
  standard.

Be concise and lead with the answer. Plain English, no invented shorthand.
