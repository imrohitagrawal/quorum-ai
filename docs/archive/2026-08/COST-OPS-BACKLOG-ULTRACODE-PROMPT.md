# Cost & ops backlog — close the remaining money holes

ultracode

Eight open issues in the cost/ops stream. They are ordered by MEASURED money risk, not by
issue number. Work them in tiers, ship one PR per issue, and **stop at the tier boundary** if
you are running low on budget rather than half-finishing the next tier.

**Run autonomously.** Investigate → build → review ×2 → remediate → gate without checking in.
Batch every human decision into ONE checkpoint (§5). Do not ask three separate times.

---

## 0. Ground truth — verify before trusting anything below

Measured **2026-07-28**. The repo moves and a parallel session is active. Verify → implement → document.

```bash
git fetch origin
git branch -f main origin/main        # DO THIS FIRST — a stale local main has burned this repo
git log --oneline -4 origin/main
curl -s https://quorum.stackclimb.com/status | python3 -m json.tool
gh issue list --state open --limit 30
```

| Fact | Value at time of writing |
|---|---|
| `origin/main` | `526758a` — #109 (PR #121) |
| then | `43f5d65` (#108), `3b9bb9d` (#107), `1792655` (#99) |
| prod `build_sha` | `526758a`, deploy-verified |
| prod `/status` now serves | `feedback_writes`, `feedback_lost_billed_writes` (new in #109) |
| **CLOSED — do not reopen** | #94–#99, **#101, #102, #109** |
| **YOUR SCOPE** | **#100, #122, #106, #105, #123, #110, #103, #104** |
| **NOT YOURS — another session owns these** | **#111–#120** (UI stream) and the branch `feat/ui-pr1-quickfixes` |

`feat/ui-pr1-quickfixes` was live at 3 ahead / 41 behind `main`. **Never check it out, never run a
git write command in `/Users/rohitagrawal/Projects/quorum-ai`.** Work only in your own worktrees.
If an issue in your scope turns out to need a file that stream owns (`static/app.js`, `app.css`,
`templates/workspace.html`, `e2e/`), STOP and escalate rather than editing it.

**Line numbers below WILL have drifted. Locate by symbol.**

---

## 1. TIER 1 — live money holes. Do these first.

### ITEM 1 — #100: the per-account cap is bypassable by dropping a cookie *(own PR, highest value)*

`DAILY_CAP_USD = $0.20` is enforced **per account**. MEASURED during #109: `issue_session` mints
a fresh `uuid4()` account when no cookie is presented (`auth.py`, reached by `GET /v1/session`),
so two fresh cookie jars get two different `account_id`s. The 24 h "per-account" cap therefore
resets whenever a visitor drops their cookie — and there is **no deployment-wide ceiling at all**.

Also measured, and relevant: the in-memory cumulative `HARD_LIMIT_USD` guard that survives a
degraded store is a SINGLE 1024-entry FIFO shared across all accounts and event types, with **no
time bound**, and 1024 free refused requests flush it to zero. It bounds a burst, not a day, and
it is not per-account at all.

**Investigate first, then decide with the human (§5):** what identifies a payer? Options include
a deployment-wide 24 h ceiling summed across all accounts (simplest, and the thing the issue
title asks for), an IP-scoped cap, or requiring a real identity for priced routes. Each has a
different abuse profile and a different availability cost. **Present measured options; do not
pick one yourself.**

Build only the mechanism the human picks. Whatever it is: it reads from the durable store, so
respect #109's finding that the store can be silently unwritable — a deployment ceiling that
reads a frozen ledger is the same fail-open one layer up. Wire it to
`feedback_lost_billed_writes` so it cannot claim a total it cannot substantiate.

### ITEM 2 — #122: the spend-cap policy when the ledger is known stale *(own PR, small)*

#109 shipped DETECTION only, by an explicit operator decision. The app can now tell a stale
ledger from a healthy one (`feedback_lost_billed_writes > 0`, or `feedback_writes == "failing"`).
The policy question is now answerable and is **operator-gated** — read the issue, present the
measured consequences, do not decide.

MEASURED, so you do not re-derive it:
* **BLOCK** hits **100 %** of priced requests on both routes for the life of the process
  (`_threshold_for` does not return early, so the store block is reached on every one), and the
  UI renders "Over the hard cap", which blames the user's cost rather than a storage fault.
* **REQUIRE_CONFIRMATION caps nothing** — confirmation is user-supplied and unlimited.
* **Raising is NOT a policy**: `already_spent = store.daily_spend_for(...)` is unwrapped and the
  app has no matching handler, so a raise is a bare **HTTP 500 with no error envelope** on both
  routes while `/health` still returns 200.
* The prior #101 decision was "loud only". Its stated mitigation (the in-memory cumulative
  guard) is weaker than it assumed — see ITEM 1. Say so when you present the options.

### ITEM 3 — #106: F-05 Layer 2 — a cancel does not stop the spend *(own PR)*

A cancelled run still leaves billed calls in flight inside debate/synthesis (the issue records a
residual of ~2). Real money, bounded scope. #108 added a `BillableStage` marker
(`NOT_ENTERED/ENTERED/RECORDED`) that already tracks stage entry — check whether it gives you a
cheaper cancellation seam than threading a new flag.

**Re-verify the residual count yourself before building.** A full run is 10 provider calls
(4 initial + 2 debate + 4 synthesis), measured — not 11.

---

## 2. TIER 2 — correctness and robustness

### ITEM 4 — #105: E1, close an unevidenced classification with data *(own PR)*
5xx is classified as possibly-billed on a premise with no evidence in the repo. MEASURED **4.2×
OVERSTATEMENT** for a router-level 503. It was deliberately shipped as-is because the run is
labelled `estimated` (the honest direction). **Close it with DATA, not a guess**: log the status
code and whether the error body carries `error.metadata.provider_name`, ship that, and only then
re-classify. Do not re-classify on reasoning alone — that is exactly what the issue objects to.

### ITEM 5 — #123: no reconnect path *(own PR)*
`configure_feedback_store` runs once at import; no retry, no reconnect. A transient boot lock
disables the cap for the whole process lifetime, and a repaired read-only volume still needs a
restart. MEASURED constraints (do not re-derive, but do re-verify):
* A reopen keyed on `store is None` **never fires for #109's fault** — that store opens fine.
  Build it on #109's write-health signal instead.
* Recovery depends on ORDERING (4 shapes measured): a handle that PREDATES the fault resumes on
  `chmod` alone, so does one opened when only the DIRECTORY was unwritable; only a handle opened
  onto an already-read-only FILE needs a fresh one.
* A lock-blocked open costs **5.24 s** (sqlite3 default `timeout=5.0`, never overridden), so do
  NOT put it on the request path without a monotonic cooldown, and do NOT hook `/status`
  (unauthenticated — an anonymous caller could drive repeated 5 s opens).
* Retries leak nothing (5 failed opens + gc → zero `ResourceWarning`).
* `configure()` deliberately does not close the displaced store (pinned by
  `test_configure_does_not_close_the_displaced_store`); `test_store_lifecycle.py`'s autouse guard
  asserts singleton identity; several tests pin the degraded path with `FEEDBACK_DB_PATH=:memory:`
  where a reopen would silently SUCCEED and re-enable the cap — it needs an explicit off switch.
* `run_history_store` is the same shape and the lifecycle tests parametrize over both.

### ITEM 6 — #110: a BILLED judge call is in no cost line *(own PR)*
`GET /v1/query-runs/{id}` → `_result_response` → `_evaluation_projection` → `_evaluate_terminal_run`
dispatches a real OpenRouter call **on the same request that serves the cost receipt**, and
`grep -in "judge" src/product_app/costs.py` returns zero hits. MEASURED: 4300 judge tokens billed,
`$0.0155` served as `measured`, `vendor/judge-model` absent from `by_model`; the memo is a
512-entry LRU that dies with the process, so the same run **re-bills** after eviction or redeploy.

**Reachable only when `QUORUM_EVAL_JUDGE_API_KEY` + `QUORUM_EVAL_JUDGE_MODEL_ID` are both set.
VERIFY prod's config yourself — at time of writing neither is set, so nothing is dispatched. If
that has changed, this is LIVE and jumps to Tier 1; say so loudly.**

Reuse #108's `BillableStage` machinery rather than inventing a parallel mechanism.

---

## 3. TIER 3 — observability and hygiene

### ITEM 7 — #103: the nightly audit has never audited production *(own PR)*
`.github/workflows/feedback-audit.yml` runs on a GitHub runner and sets no `FEEDBACK_DB_PATH`, so
`FeedbackStore.from_env()` falls back to `.data/feedback_events.sqlite3` — a fresh, empty,
checkout-local file it creates itself. It has never seen the Fly volume. Verified: zero
`FEEDBACK_DB_PATH` hits across all files in `.github/`.
Decide deliberately whether the fix is to run the audit against prod (needs volume access and is
a security decision) or to make the job FAIL LOUDLY rather than emit a plausible all-zeros report.
The second is much cheaper and removes the false signal; recommend, then let the human choose.

### ITEM 8 — #104: two measured test flakes *(own PR)*
`provider_event_recorder` unfiltered, and a non-hermetic gate test. Fix both; prove each with a
repeat run (N ≥ 20) rather than a single green.

---

## 4. Non-negotiable practices

### 4.1 Evidence-first
No claim without a check. Never state a cause, cost, status or config value without running the
cheapest command that settles it. If you cannot verify, say **"UNVERIFIED hypothesis"** out loud
and name the exact check.

**When you CORRECT a false claim, verify the REPLACEMENT before writing it.** Three separate
review rounds on this repo have caught rewrites that were themselves false — one told an operator
a money-losing fault was benign; another told them to restart a process that did not need it.
Prefer narrow hedged wording ("no workflow sets it") over absolutes ("set nowhere else").

### 4.2 TDD with a bite proof
1. Test FIRST. Run it. **Capture the verbatim failure.** If it passes, it does not bite.
2. Minimal fix. Re-run.
3. **Bite proof:** `cp` the source aside, re-introduce the defect BY HAND, confirm RED, restore
   **from your copy**. **NEVER `git checkout <file>`** — it discards uncommitted work.
4. Accounting code asserts **CARDINALITY** (how many records, rows, calls), never a clean-path
   outcome. Ask of every assertion: *could this fail for ANY implementation?* Reviewers here have
   found `assert len(billed) == 5` comparing a test-local literal to itself, and a charge-walk
   that could not distinguish `>` from `>=`.

### 4.3 Run the gate CI actually runs
```bash
uv sync --all-extras                      # NOT --extra dev; schemathesis is in `quality`
make quality
make validate
make diff-cover DIFF_BASE=origin/main     # BLOCKING in CI, in NEITHER target above, >=95%
make openapi-check                        # blocking, and NOT in the above
make security-scan                        # blocking, and NOT in the above
```
Never lower a threshold, add `# pragma: no cover`, or delete a test to go green.

### 4.4 Adversarial review — hard two-round cap
Mandatory before "done", including a reviewer whose explicit job is to **break** it. All Tier 1–2
items are cost-honesty code, so that reviewer is required. **At most TWO rounds, then STOP and
escalate** with open findings listed.

Both rounds have earned their keep every single time on this repo. On #109 round 1 found that the
shipped signal was **maskable** — a write-failure timestamp that any concurrent writer overwrote,
measured as 8 runs / $0.2088 billed against a $0.20 cap with `/status` reading healthy throughout.
**Expect your own fix to introduce a defect. Budget a round for it.**

### 4.5 Parallelism
Fan out **wide** on read-only phases. **Serialize writes.** Parallel builds only across genuinely
disjoint files in separate worktrees. Give every reviewer that needs to mutate source its OWN copy
(`git archive HEAD | tar -x -C <dir>`) — a shared-worktree mutation once produced 4 phantom
failures for another reviewer, and once left uncommitted edits a later agent inherited.

### 4.6 Shipping
- Branch off `main` in a **dedicated `git worktree`**, never in the main checkout.
- Commit locally. **Push / PR / merge / deploy only with explicit human approval.**
- Squash-merge, ONE PR at a time, and **wait for each deploy** — a follow-up push to `main`
  cancels the in-flight run via the concurrency group.
- **This repo requires the head branch to be up to date with base.** A second stacked PR must
  merge `main` in first, then **re-gate the merged tree locally** (`diff-cover` included).
- **Supply an explicit squash message** (`gh pr merge --squash --subject --body`). A squash
  concatenates every commit body onto `main`, so superseded figures from intermediate commits
  land there unless you override.
- **Deploy verification = the Deploy JOB ran (`success`) AND prod `/status build_sha` == the
  merged SHA.** An unchanged `/health` 200 proves nothing.
- **After merging, `git branch -f main origin/main`.**
- **Hermetic / $0.** No paid API calls. Never fabricate a number.

---

## 5. Operator-gated — batch into ONE checkpoint

1. **#100's payer-identity question** (ITEM 1) — deployment-wide ceiling vs IP-scoped vs real
   identity. Present measured abuse profiles and availability costs.
2. **#122's fail-closed policy** (ITEM 2).
3. **#103's fix shape** (ITEM 7) — audit prod, or fail loudly.
4. **Pushing / PRs / merging / deploying.**
5. **Any paid live run.** Default to $0. Prod has run `live_count: 0` since ~2026-07-23
   (unfunded OpenRouter key), so live-path behaviour cannot be observed for free.

---

## 6. Traps this repository has already sprung

- **Stale local `main`.** `git branch -f main origin/main` before AND after merging.
- **`git checkout <file>` to undo a mutation** destroys uncommitted work. Restore from a `cp`.
- **`make quality` green ≠ CI green.** `diff-cover`, `openapi-check`, `security-scan` are all
  separate and blocking.
- **`uv sync --extra dev` is not enough** — use `--all-extras`.
- **`SESSION_RATE_LIMIT_PER_MINUTE=600` is for Playwright e2e ONLY.** Setting it for pytest makes
  `test_session_endpoint_rate_limited_after_burst` fail — a phantom red.
- **There is no `pytest-timeout`.** `--timeout=` is not a valid flag on this tree.
- **Deploy produces TWO runs per SHA** — one `cancelled` (concurrency dedupe) and one real. A
  wait-loop keyed on "any completed run" fires on the cancelled one. Resolve the NEWEST run by
  `createdAt` each poll. `gh run list --commit <SHA>` silently returns `[]`; use `--branch main`
  + `startswith(SHA)`.
- **A probe script that does `sys.path.insert(0, ROOT/src)`** can silently measure a STALE copy of
  the tree sitting next to it, making a working fix look broken. Repoint ROOT and sanity-check by
  grepping the imported file for a symbol only the intended version has.
- **Process-global test state.** The cost event ring, the run-capacity semaphore and the model
  catalog are process globals. Use `tests/helpers.isolated_run_semaphore`. A test that drains and
  "restores" a `BoundedSemaphore` restores it to its *bound*, minting a phantom permit.
- **`tests/conftest.py` does NOT pin `FEEDBACK_DB_PATH`** (it pins `RUN_HISTORY_DB_PATH`), so a
  test importing `product_app.main` opens the on-disk dev default.
- **A barrier-race probe may not bite** (measured 0/5000). Park the writer at the lock door with
  `Event` handshakes instead.
- **An EXCLUSIVE-lock test costs ~5.2 s** (sqlite3's default busy timeout, never overridden in
  source). Inject a short timeout in-test, capturing the real `sqlite3.connect` BEFORE patching so
  the lock holder stays real.
- **`/status` is unauthenticated, unthrottled and a sync `def`** in anyio's 40-token threadpool.
  Never add a write or a blocking probe to it — measured, `BEGIN IMMEDIATE` under a held lock
  blocks 5197 ms, so 40 anonymous requests stall every endpoint.
- **The money signal assumes ONE process** (`Dockerfile` runs `--workers 1`). Per-process counters
  become maskable with N>1.
- **Agent scratch files break `make quality`** (`ruff format --check`). Delete before gating.
- **`gh` may be blocked by the permission classifier.** If a merge is denied, stop and ask.

---

## 7. Definition of done

- [ ] Tier 1 (#100, #122, #106) shipped, each its own PR, each deploy-verified
- [ ] Tier 2 (#105, #123, #110) shipped or explicitly deferred with an evidenced argument
- [ ] Tier 3 (#103, #104) shipped or deferred
- [ ] Every PR: `make quality` + `make validate` + `make diff-cover` + `make openapi-check` +
      `make security-scan` green, verified independently — not just quoted from a build agent
- [ ] ≤2 adversarial review rounds per item, breaker included; leftovers escalated
- [ ] Nothing pushed/merged/deployed without approval; each merge deploy-verified by the Deploy
      JOB **and** prod `build_sha`
- [ ] Local `main` re-synced; worktrees and branches cleaned up, local and remote
- [ ] A close-out note: what was fixed, what was refuted, what stayed open **and why**

**Report honestly.** A refutation, a "could not reproduce", or a "could not verify — here is the
exact check that would" are all successful outcomes. A confident wrong answer is the only real
failure. **If this brief is wrong, say so and do not build what it asked for** — that has already
prevented one measured ~4.8× regression on this repo.

**And state your scope decisions UP FRONT.** If you defer an item, say so in the same message that
reports the work, with the reason — do not leave the reader to infer that "shipped" meant
"everything closed".
