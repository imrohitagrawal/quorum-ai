# #109 + #110 + the reconnect residual — cost fail-open close-out

ultracode

Three cost-honesty items, each its own PR. All three came out of closing #101/#102 (PRs
#107/#108, merged and deployed) and were deliberately left out to avoid widening scope.
None is speculative — #109 and #110 are each backed by a reproduction, and the third is a
one-line structural fact.

**Run autonomously.** Investigate → build → review → remediate → gate without checking in.
Batch every human decision into ONE checkpoint (§5) instead of blocking three times.

---

## 0. Ground truth — verify before trusting anything below

Measured **2026-07-28**. The repository moves and a parallel session may be active.
Verify → implement → document.

```bash
git fetch origin
git branch -f main origin/main        # DO THIS FIRST — a stale local main has burned this repo
git log --oneline -3 origin/main
curl -s https://quorum.stackclimb.com/status | python3 -m json.tool
gh issue list --state open --limit 20
```

| Fact | Value at time of writing |
|---|---|
| `origin/main` | `43f5d65` — E2 (#108) |
| then | `3b9bb9d` (#107), `1792655` (#99) |
| prod `build_sha` | `43f5d65`, deploy-verified |
| prod `feedback_db` | `connected`, `live_execution: true` |
| **CLOSED — do not reopen** | **#101, #102** (shipped in #107/#108), #94–#99 |
| Your scope | **#109**, **#110**, and the unfiled reconnect residual (§1 ITEM 2) |
| Untouchable | `feat/ui-pr1-quickfixes` and any `.claude/worktrees/wf_*` — another session owns them |

Check `git status` in `/Users/rohitagrawal/Projects/quorum-ai` before assuming anything about
that tree, and run **NO git write command there**. Work only in your own worktrees.

**Line numbers below WILL have drifted. Locate by symbol.**

---

## 1. The three items

### ITEM 1 — #109: the spend cap ALSO fails open when the DB is writable-but-not-writing *(own PR, highest priority)*

**The only LIVE money fail-open left.** #107 made the store-*absent* case loud. This is the
store-*present-but-not-writing* case, and it is the more likely production trigger.

`FeedbackStore.record` swallows every write failure with a `WARNING` (deliberately —
"best-effort"). So when the DB is present but unwritable: the store opens, every
`cost_guardrail_accepted` INSERT is dropped, `daily_spend_for` reads a **frozen ledger**, the
24h cap **silently stops firing**, `/status` reports **`"connected"`**, and there are **ZERO**
error records — #107's two ERRORs are both keyed on `store is None`.

Measured (RESERVED lock taken *after* boot; 4 charges at $0.05 against `DAILY_CAP_USD = $0.20`):

```
--- control, no lock ---   per-charge: [allow, allow, allow, BLOCK]   daily_spend_for: 0.20
--- RESERVED held ---      per-charge: [allow, allow, allow, allow]   daily_spend_for: 0
costs ERROR: 0 | main ERROR: 0 | store WARNING: 4 | status feedback_db: connected
AFTER release -> daily_spend_for: 0.05   (the 4 swallowed charges never replay)
```

Read-only volume is the same shape, with one extra fact: a read-only handle does **NOT**
recover on `chmod +w` (SQLite opened it `O_RDONLY`, confirmed via `lsof` access-mode `ar`) —
it needs a process restart. The RESERVED case **does** recover in-process on release.

**Re-verify both cheaply before building.** ENOSPC is the same shape but is UNVERIFIED.

**Deliverable:**
1. **`/status` must stop reporting `"connected"` when writes are failing.** This is the
   load-bearing half — today the one health signal an operator has reports green. #107 already
   introduced `disconnected` (never opened) vs `error` (open, health query raised); add the
   third state without collapsing the existing two, and update `openapi.yaml`.
2. Make the **cost stream's** swallowed write loud (ERROR, rate-limited, naming the cap), while
   leaving the other six event streams best-effort. Do not escalate all seven.
3. Tests for both fault shapes (RESERVED-after-boot and read-only), asserting **cardinality** of
   log records, and pinning the recover/no-recover asymmetry.

> **OPERATOR DECISION — do not decide this yourself.** Should `daily_spend_for` refuse to
> answer from a ledger known to be stale, rather than returning a confidently-wrong LOW number?
> This is the fail-closed question #101 item 3 asked, and **the answer may differ here**: #101
> was "no store, no data"; this is "a store returning a number that is wrong in the unsafe
> direction". Implement the loud-plus-`/status` part, present the options with trade-offs, let
> the human choose. The prior decision on #101 was **loud only** — see the comment on #101.

### ITEM 2 — the reconnect residual *(unfiled; small; own PR or fold into ITEM 1 — your call, justify it)*

`configure_feedback_store` runs **once**, at import. There is no retry and no reconnect path,
so a single transient lock at boot disables the daily cap for the **entire process lifetime**.
#107 documented this and tells the operator to restart; nothing fixes it.

Verify the claim yourself (`grep` for any retry/reopen around `FeedbackStore.from_env` — at
time of writing there is none), then decide whether a bounded lazy-reopen is worth it. This is
the smallest change that removes the sharpest edge of BOTH #101 and #109. If you conclude it
should not be built, say so with reasoning — that is a valid outcome.

File it as an issue if you do not fix it.

### ITEM 3 — #110: a BILLED judge call is absent from the cost model *(own PR, do LAST)*

`GET /v1/query-runs/{id}` → `_result_response` → `_evaluation_projection` →
`_evaluate_terminal_run` → `_request_path_judge` dispatches a real OpenRouter call **on the
same request that serves the run's cost receipt**. `grep -in "judge" src/product_app/costs.py`
→ **zero hits**. There is no judge cost line anywhere.

Measured (judge seam faked; a real POST would have billed): 4300 judge tokens billed,
`$0.0155` served as `measured`, `vendor/judge-model` absent from `by_model`. The verdict memo
is a bounded LRU (`_JUDGE_VERDICT_MEMO_MAX = 512`) that dies with the process, so **the same
run re-bills** after eviction or a redeploy — measured 2 calls for one run.

**Reachable only when the operator configures `QUORUM_EVAL_JUDGE_API_KEY` +
`QUORUM_EVAL_JUDGE_MODEL_ID`.** Current prod configures neither, so nothing is dispatched
today. **Verify that yourself before assigning severity** — if prod has them set, this is live
and you should say so loudly.

**Deliverable:** give the judge its own `BillableStage` + usage capture + a cost line, so a
judged run either prices the judge call or drops to `estimated`. #108 shipped the
`NOT_ENTERED/ENTERED/RECORDED` marker machinery — reuse it rather than inventing a parallel
mechanism. Then make the eviction/restart re-bill either impossible (persist the verdict) or
visible. It also sits outside the daily cap, since nothing records a cost event for it —
decide deliberately whether it should.

---

## 2. Non-negotiable practices

### 2.1 Evidence-first
No claim without a check. Never state a cause, cost, status or config value without running the
single cheapest command that settles it. If you cannot verify, say **"UNVERIFIED hypothesis"**
out loud and name the exact check.

**And when you CORRECT a false claim, verify the REPLACEMENT before writing it.** Both review
rounds on #107 caught rewrites that were themselves wrong — one told an operator a
money-losing fault was benign. Prefer narrow hedged wording ("no workflow sets it") over
sweeping absolutes ("set nowhere else").

### 2.2 TDD with a bite proof
1. Test FIRST. Run it. **Capture the verbatim failure.** If it passes, it does not bite.
2. Minimal fix. Re-run.
3. **Bite proof:** `cp` the source aside, re-introduce the defect BY HAND, confirm the test
   FAILS, restore **from your copy**. **NEVER `git checkout <file>`** — it discards other
   uncommitted edits. This has bitten this repo.
4. Accounting code asserts **cardinality** (how many log records, how many rows), never just a
   clean-path outcome. Ask of every assertion: *could this fail for ANY implementation?* A
   round-2 reviewer found `assert len(billed) == 5` comparing a test-local literal to itself.

### 2.3 Run the gate CI actually runs
```bash
uv sync --all-extras                      # NOT --extra dev; schemathesis is in `quality`,
                                          # without it mypy reports 6 phantom import errors
make quality
make validate
make diff-cover DIFF_BASE=origin/main     # BLOCKING IN CI, in NEITHER target above, >=95%
make openapi-check                        # blocking, and NOT in the above
make security-scan                        # blocking, and NOT in the above
```
Never lower a threshold, add `# pragma: no cover`, or delete a test to go green.

### 2.4 Adversarial review — hard two-round cap
`AGENTS.md` requires independent adversarial review before "done", including a reviewer whose
job is to **break** it. All three items are cost-honesty code, so that reviewer is **mandatory**.
**At most TWO rounds, then STOP and escalate** with open findings listed. Reviewers refute by
default and report only findings backed by a demonstrated failure. Reviews are read-only; a
separate single writer applies fixes.

Both rounds earned their keep on #107/#108: round 1 found documentation stating the
money-losing case backwards and a TOCTOU serving `measured` while dropping a billed call;
round 2 found that the TOCTOU *fix* had introduced a new under-statement regression. **Expect
your own fix to introduce a defect. Budget a round for it.**

### 2.5 Parallelism
Fan out **wide** on read-only phases. **Serialize writes** — subagents share one working tree.
Parallel builds only across genuinely disjoint files in separate worktrees. Keep a
tightly-coupled unit as ONE builder; fan its review, not its construction.

**Give every reviewer its OWN copy** (`git archive HEAD | tar -x -C <dir>`) if it needs to
mutate source. Concurrent mutation of a shared worktree gave a reviewer 4 phantom failures.

### 2.6 Shipping
- Branch off `main` in a **dedicated `git worktree`**, never in the main checkout.
- Commit locally. **Push / open a PR / merge / deploy only with explicit human approval.**
- Squash-merge. One PR at a time, and **wait for its deploy** — a follow-up push to `main`
  cancels the in-flight run via the concurrency group.
- **This repo requires a PR's head branch to be up to date with base.** The second of two
  stacked PRs must merge `main` in first — then **re-gate the merged tree locally**
  (`make diff-cover DIFF_BASE=origin/main` included) before pushing. A clean auto-merge is not
  a correct merge.
- **Deploy verification = the Deploy JOB ran (`success`, not `skipped`/`cancelled`) AND prod
  `/status build_sha` == the merged SHA.** An unchanged `/health` 200 proves nothing.
- **After merging, `git branch -f main origin/main`** — merges land on the remote and the local
  ref does NOT follow.
- **Hermetic / $0.** No paid API calls. Never fabricate a number — flag the gap instead.

---

## 3. Suggested shape

```
PHASE 1  Investigate (read-only, parallel)
         ├─ #109: reproduce BOTH fault shapes; enumerate every write path that can be
         │        swallowed; map what /status can actually observe (is a write-failure
         │        counter enough, or must a probe write happen?)
         ├─ ITEM 2: confirm there is no reconnect path; scope a bounded lazy-reopen
         └─ #110: VERIFY prod does not configure the judge key; map the judge call graph and
                  what a BillableStage for it would touch
PHASE 2  Build #109 (+ ITEM 2 if folded) — one writer, own worktree
PHASE 3  Review round 1 — security/money-breaker (mandatory) + correctness + test-bite
PHASE 4  Remediate (single writer, reproduce each finding first)
PHASE 5  Review round 2 — then STOP
PHASE 6  Repeat 2-5 for #110 in a separate worktree
PHASE 7  ONE human checkpoint (§5), then ship
```

Recommended: ONE session. Ship **#109 first and alone** — it is the live defect. If it grows
beyond its brief, stop and hand off rather than dragging #110 along.

---

## 4. Boundaries

- **Do not touch `feat/ui-pr1-quickfixes`** or any `.claude/worktrees/wf_*` worktree.
- **Do not re-fix #101, #102, F-01, F-02, F-05, F-06.** All merged and deployed.
- **Do not re-open the money-envelope decision.**
- **Do not widen into** #100 (no deployment-wide spend ceiling), #103 (audit job reads an empty
  DB), #105 (E1 5xx classification), #106 (F-05 Layer 2). File findings, do not fix them here.
- `run_history_store` has #101's identical failure mode and **no `/status` field at all**.
  In scope only if it falls out of #109's `/status` work for free — otherwise file it.

---

## 5. Operator-gated — batch into ONE checkpoint

1. **#109's fail-closed question** (§1 ITEM 1). Present options; do not decide.
2. **Whether ITEM 2 (reconnect) ships, and folded or standalone.** Recommend, do not assume.
3. **#110's memo-persistence choice** — persisting a verdict is a durability change.
4. **Pushing / PRs / merging / deploying.**
5. **Any paid live run.** Default to $0. Prod has run `live_count: 0` since ~2026-07-23
   (unfunded OpenRouter key), so live-path behaviour cannot be observed for free.

---

## 6. Traps this repository has already sprung

- **Stale local `main`.** `git branch -f main origin/main` before and after merging.
- **`git checkout <file>` to undo a mutation** destroys uncommitted work. Restore from a `cp`.
- **`make quality` green ≠ CI green.** `diff-cover`, `openapi-check` and `security-scan` are
  separate and blocking.
- **`uv sync --extra dev` is not enough** — use `--all-extras`.
- **`SESSION_RATE_LIMIT_PER_MINUTE=600` is for Playwright e2e ONLY.** Setting it for pytest
  makes `test_session_endpoint_rate_limited_after_burst` fail — ~1 phantom red.
- **There is no `pytest-timeout`.** `--timeout=` is not a valid flag on this tree.
- **Deploy produces TWO runs per SHA** — one `cancelled` (concurrency dedupe) and one real. A
  wait-loop keyed on "any completed run" fires on the cancelled one. Resolve the NEWEST run by
  `createdAt` each poll. And `gh run list --commit <SHA>` silently returns `[]` — use
  `--branch main` + `startswith(SHA)`.
- **Process-global test state.** The cost event ring, the run-capacity semaphore and the model
  catalog are all process globals. Use `tests/helpers.isolated_run_semaphore`. A test that
  drains and "restores" a `BoundedSemaphore` restores it to its *bound*, minting a phantom permit.
- **`tests/conftest.py` does NOT pin `FEEDBACK_DB_PATH`** (it pins `RUN_HISTORY_DB_PATH`), so a
  test importing `product_app.main` opens the on-disk dev default.
- **A barrier-race probe may not bite.** Measured 0 reverted / 5000 iterations, because the
  thread that trips the barrier keeps running. Park the writer *at the lock door* with `Event`
  handshakes instead.
- **An EXCLUSIVE-lock test costs ~5.2s** (sqlite3's default busy timeout, never overridden in
  source). Inject a short timeout in-test via `monkeypatch.setattr(sqlite3, "connect", ...)`,
  capturing the real `connect` before patching so the lock holder stays real.
- **Agent scratch files break `make quality`.** Reviewer `tests/scratch_*` dirs fail
  `ruff format --check`. Delete them before gating.
- **`gh` may be blocked by the permission classifier.** If a merge is denied, stop and ask.
- **A subagent may `git commit --amend`.** Verify with `git reflog` that nothing was orphaned.

---

## 7. Definition of done

- [ ] #109: `/status` no longer says `connected` while writes fail; the cost-stream swallowed
      write is loud; tests for BOTH fault shapes with cardinality assertions; fail-closed
      question put to the human
- [ ] ITEM 2: reconnect residual fixed, or filed with an evidenced argument for leaving it
- [ ] #110: judge call priced or the run drops to `estimated`, with a cardinality-asserting RED
      test; re-bill made impossible or visible
- [ ] Every PR: `make quality` + `make validate` + `make diff-cover DIFF_BASE=origin/main` +
      `make openapi-check` + `make security-scan` green
- [ ] ≤2 adversarial review rounds per item, money-breaker included; leftovers escalated
- [ ] Nothing pushed/merged/deployed without explicit approval; each merge deploy-verified by
      the Deploy JOB **and** prod `build_sha`
- [ ] Local `main` re-synced after merging; worktrees and branches cleaned up, local and remote
- [ ] A close-out note: what was fixed, what was refuted, what stayed open

**Report honestly.** A refutation, a "could not reproduce", or a "could not verify — here is the
exact check that would" are all successful outcomes. A confident wrong answer is the only real
failure. If the brief above turns out to be wrong, **say so and do not build what it asked for**
— that is exactly what happened to this brief's predecessor on #102, and it prevented shipping
a measured ~4.8x regression.
