# Stream B close-out — F-05, F-06, and the three unclosed items

**Paste this whole file into a fresh session. Add the word `ultracode` to your message.**

You are closing out Stream B of the quorum-ai remediation. Two of its four P0s (F-01, F-02)
are already merged and live in production. This prompt covers everything that is left.

---

## 0. Ground truth — verify these before trusting anything below

Everything in this document was measured on **2026-07-27**. The repository moves. The house
rule is *verify → implement → document*, so **re-verify before you build**, and say so out
loud when a claim here turns out to be stale.

```bash
git fetch origin
git branch -f main origin/main        # DO THIS FIRST — see the trap in §6
git log --oneline -3 origin/main
curl -s https://quorum.stackclimb.com/status | python3 -m json.tool | grep build_sha
```

Expected at the time of writing:

| Fact | Value |
|---|---|
| `origin/main` | `025bd83` — F-01 double billing (#95) |
| previous | `b95a5ee` — F-02 session fixation (#94) |
| prod `build_sha` | `025bd83` (deploy-verified) |
| Unrelated live branch | `feat/ui-pr1-quickfixes` — **DO NOT TOUCH.** It carries a parallel session's work |

### Already done — do NOT redo

- **F-01** double billing → PR #95, `025bd83`, deployed. `/estimate` now records
  `cost_estimate_previewed`; a one-shot `schema_migrations`-marked relabel migration repairs
  pre-fix durable rows; the capacity permit is reserved before anything bills.
- **F-02** session fixation → PR #94, `b95a5ee`, deployed. `auth.py` reads exactly one cookie
  name per environment.

---

## 1. The five items

Severity is **user impact**. Line numbers are from `origin/main` @ `025bd83` and **will drift**.

### ITEM 1 — F-05: a cancel may be silently reverted  *(P0, own PR)*

**The claim (from the original ledger):** a cancel landing mid-stage is overwritten by the
pipeline; billed calls continue and the run ends `completed` after the user was told
`cancelled`.

**⚠️ THE LEDGER IS PARTLY STALE — this is your first job.** The cancel *endpoint* has since
been hardened: `cancel_query_run` (`query_runs.py:1242`) routes through
`query_run_repository.transition(...)` (`:1274`) so the `ALLOWED_TRANSITIONS` guard rejects a
race that would promote a terminal status back to `CANCELLED`, and it catches
`InvalidQueryRunTransitionError` to return the winning terminal state.

**What is NOT yet established** — and what you must actually reproduce or refute:

1. The *pipeline* writes status at many points (`query_runs.py:1423, 1434, 1513, 1524, 1531,
   1561, 1572` — all `query_run_repository.update_status`, plus `transition` at `:1371`).
   Does any of them clobber a `CANCELLED` set concurrently by the endpoint? `update_status`
   is the call that historically bypassed the guard.
2. After a successful cancel, does the pipeline **stop making billed provider calls**, or
   does it run to completion? A cancel that does not stop spend is the expensive half of this
   defect, independent of the final status label.
3. Does `_persist_terminal_run` / the safety wrapper (`_execute_query_run_safely`) re-write a
   terminal state over `CANCELLED`?

**Deliverable:** either a fix with a RED test, **or** a written, evidence-backed refutation
that the defect no longer exists — with the exact commands and output that show it. A
refutation is a perfectly good outcome. **Do not invent a fix for a bug that is already
fixed.** If only part of it is real, fix that part and say precisely which part was stale.

### ITEM 2 — F-06: `measured` cost may be a lie  *(P0, own PR)*

**The claim:** `_actual_cost` labels a run `measured` while dropping billed calls whose usage
was not captured; the capture gate is vacuously true.

**Current code** — `_actual_cost` at `query_runs.py:2139`. The STRICT honesty gate landed in
`3580658` (#11) and is genuinely strict for the initial answers:

```python
initial_fully_captured = (
    bool(model_slots)                                  # <- NOT vacuous
    and len(initial_answers) == len(model_slots)
    and all(... provider_path is OPENROUTER_SEARCH
            and status is COMPLETED
            and token_usage is not None ...)
)
debate_captured    = all(usage is not None for _, usage in query_run.debate_call_usages)   # :2176
synthesis_captured = all(usage is not None for usage in query_run.synthesis_call_usages)   # :2177
```

**The specific unverified suspicion:** `all()` over an **empty** list is `True`. So
`debate_captured` and `synthesis_captured` are vacuously true when those lists are empty —
and the question that decides whether this is a real defect is:

> **Can a live run make a billed debate or synthesis call whose usage is never appended to
> `debate_call_usages` / `synthesis_call_usages` at all?**

If a failed / timed-out / empty-content call is simply *never recorded* rather than recorded
as `None`, the gate cannot see it, the run is labelled `measured`, and the receipt understates
real billing. **Trace where those lists are populated** (`query_runs.py`, `debate.py`,
`synthesis.py`) and establish this by reproduction, not by reading alone.

Contrast with `initial_fully_captured`, which defends against exactly this by comparing
`len(initial_answers) == len(model_slots)` — a *cardinality* check. That is the shape of the
fix if the defect is real.

**Deliverable:** a fix with a RED test that fails on the vacuous gate, or an evidence-backed
refutation. The regression test must assert **cardinality** (expected call count vs recorded
usage count), not merely "the flag is right on a clean run" — a clean-path test is exactly
what let this survive.

### ITEM 3 — document the `schema_migrations` mechanism  *(docs; can ride with Item 1 or 2)*

F-01 introduced a **new durable table on the production Fly volume**
(`FEEDBACK_DB_PATH=/data/feedback_events.sqlite3`). Nothing in `docs/` describes it.

- `feedback_store.py` — `_MIGRATIONS_DDL`, `_F01_MIGRATION`, `_F01_PREVIEW_SELECT`,
  `_migration_applied`, and the migration runner invoked from `__init__`.
- Behaviour worth documenting: it is one-shot (marker row), atomic (`BEGIN IMMEDIATE`,
  rewriting the `event_type` column and the `payload` JSON together, `ROLLBACK` on error),
  and **best-effort** — a read-only or locked volume logs a warning and degrades to the
  pre-migration state rather than failing to boot.
- Write it where operators will look. `make validate` gates `docs/`; check
  `docs/80-observability.md` and the operations runbook family before creating a new file, and
  **run `make validate` after** — the doc validators are strict about structure.

### ITEM 4 — verify the F-01 backfill actually ran in production  *(operational, $0, no code)*

The migration logs its repaired row count at INFO on first boot after the `025bd83` deploy.
**That number was never read** — `flyctl logs -a quorum-ai --no-tail` returned empty for me.

```bash
flyctl logs -a quorum-ai --no-tail | grep -i "relabelled\|feedback_store\|migration"
# if the log buffer has rolled, try:
flyctl logs -a quorum-ai -i <instance-id>
flyctl ssh console -a quorum-ai   # then inspect /data/feedback_events.sqlite3 read-only
```

What you are establishing:

1. Did the migration run at all, and how many rows did it repair?
2. Are there **zero** remaining `cost_guardrail_accepted` rows with `query_run_id IS NULL`?
3. Is the `schema_migrations` marker row present?

**This is read-only. Do not run a paid query.** If the log window has rolled and SSH is not
available, say so plainly and record it as unverified — do not guess a number, and do not
trigger a deploy just to re-observe the boot line.

### ITEM 5 — the unreproduced `/estimate` failure cluster  *(investigation; may close as "not a defect")*

During F-01 review, one agent reported a **first-run** cluster of ~5 `/estimate` test failures
("preview branch never executed"). It **never reproduced**: 6 clean full-suite base-tree runs,
and the default-mix estimate is `allow` at both catalog prices measured (0.0261 cold / 0.0244
with the static catalog pinned). No mechanism was found. It was deliberately **left open**.

Known real order-dependencies already fixed (do not re-fix — confirm they hold):

- `cost_event_recorder` is a process-global ring; assertions filter by the test's own account id.
- The catalog price depends on **import order** — `tests/contract/test_api_contract_schemathesis.py`
  pins the static catalog at import time. The cost-guardrail module now pins it explicitly.
- The run-capacity semaphore is a process global; `tests/helpers.isolated_run_semaphore`
  installs a private one per test.

**Task:** run the full suite enough times, cold and under CPU contention, to either reproduce
it or bound it. Suggested: `N ≥ 20` runs, including cold-cache first runs, plus randomized
collection order if the repo has `pytest-randomly` available.

**Acceptable outcomes, in order of preference:** (a) reproduced and fixed with a bite-proof
test; (b) reproduced and root-caused but deliberately deferred, with a filed issue;
(c) **cannot reproduce in N runs — closed with the measured evidence.** (c) is a real result.
State N and the conditions. Do not claim it is fixed if you only failed to see it.

---

## 2. Non-negotiable practices

These are not style preferences. Every one of them exists because skipping it cost real time
on this repository.

### 2.1 Evidence-first — no claim without a check

Never state a cause, cost, status, capability, config value, or "likely X" without first
running the single cheapest command that confirms or refutes it. Protocol: hypothesis → the
one command that settles it → run it → report the verified result with its evidence. If you
cannot verify, say **"UNVERIFIED hypothesis"** out loud, name the check that would settle it,
and offer to run it.

### 2.2 TDD with a bite proof

1. Write the test FIRST. Run it. **Capture the verbatim failure output.** If it passes, it does
   not bite — rewrite it.
2. Implement the minimal fix. Re-run: it passes.
3. **Bite proof:** `cp` the fixed source aside, re-introduce the defect **by hand**, confirm
   the test FAILS, then restore **from your copy**.
   **NEVER `git checkout <file>` to revert a mutation** — it discards your other uncommitted
   edits too. This has bitten this repo before.
4. For any *accounting* code (cost, quota, rate limits, usage), assert **cardinality**, not
   just outcome. F-01 survived every existing test because they all asserted *that* a run was
   billed, never *how many times*. F-06 is the same shape.

### 2.3 Run the gate CI actually runs

```bash
make quality                              # format-check, lint, type-check, test
make validate                             # factory doc/architecture/security gates
make diff-cover DIFF_BASE=origin/main     # ⚠️ BLOCKING IN CI, AND IN NEITHER TARGET ABOVE
```

**`make diff-cover` is not part of `make quality` or `make validate`.** CI runs it as a
separate blocking job at **≥95% changed-line coverage** (`.github/workflows/ci.yml`). Green
locally on the first two and red in CI is *guaranteed* for any diff whose new lines are
under-covered — this exact thing happened on PR #95.

Never lower the threshold, add `# pragma: no cover`, or delete a test to go green. If a line
is genuinely untestable, say so explicitly with evidence.

If you touch e2e specs: `SESSION_RATE_LIMIT_PER_MINUTE=600 ... --workers=1`. Without those,
~95 failures are phantom.

**Worth proposing (not required):** add `pre-push: quality validate diff-cover openapi-check`
to the Makefile and point AGENTS.md at it, so local verification cannot drift from CI again.

### 2.4 Adversarial review — and a hard two-round circuit breaker

`AGENTS.md` requires independent adversarial review before "done", including a reviewer whose
explicit job is to **break** the change for anything touching security, auth, secrets, cost or
validation logic. Both remaining items are cost/billing-honesty code, so that reviewer is
mandatory.

**Run at most TWO review rounds. After round 2, stop and escalate to the human** with the open
findings listed. Do not start a round 3. Round 2 on PR #95 earned its keep — it caught a
4-in-21 test flake and a fail-open spend guard — but the loop must terminate.

Reviewers must **refute by default** and report only findings backed by a concrete,
demonstrated failure scenario. Reviews are **read-only**; a separate single writer applies fixes.

### 2.5 Parallelism

Fan out **wide** on read-only phases (investigation, review, verification) with diverse
independent lenses. **Serialize writes** — subagents share one working tree, so parallel
writers corrupt each other. Parallel builds only across genuinely disjoint files, in separate
worktrees. Keep a tightly-coupled unit as ONE builder; fan its *review*, not its construction.

### 2.6 One concern per PR

A reviewer cannot audit a billing fix and a docs restructure in the same diff. F-05 and F-06
are **separate PRs**. Item 3 (docs) may ride along with whichever lands first, or be its own
small PR. Items 4 and 5 produce **findings**, not necessarily code.

### 2.7 Shipping

- Branch off `main`, in a **dedicated `git worktree`**, so `feat/ui-pr1-quickfixes`'s
  uncommitted work is never at risk.
- Commit locally. **Push and open a PR only when the human approves.**
- Squash-merge (the repo's dominant convention).
- Merge one PR at a time and **wait for its deploy** — a follow-up push to `main` cancels the
  in-flight run via the concurrency group.
- **Deploy verification = the Deploy JOB ran (`success`, not `skipped`/`cancelled`) AND prod
  `/status` `build_sha` == the merged SHA.** An unchanged `/health` 200 proves nothing.
  Duplicate Deploy runs where one is `cancelled` are concurrency dedupe, not failure.
- **Hermetic / $0.** No paid API calls, no secret rotation, no paid runs for routine checks.
  Never fabricate a number, label, or baseline — flag the gap instead.

---

## 3. Suggested ULTRACODE shape

Scale to the task; this is a sketch, not a straitjacket.

```
PHASE 1  Investigate (read-only, WIDE fan-out, parallel)
         ├─ F-05: reproduce or refute — trace every pipeline status write vs a
         │        concurrent cancel; and separately, does spend actually stop?
         ├─ F-06: reproduce or refute — can a billed debate/synthesis call be
         │        absent from the usage list entirely? Trace the populate sites.
         ├─ Item 4: read prod logs / DB read-only. Findings only.
         └─ Item 5: N≥20 full-suite runs, cold + contended. Findings only.
         → each returns a structured verdict: REAL / PARTLY-STALE / REFUTED, with evidence

PHASE 2  Build (parallel across the two, SEPARATE worktrees, one writer each)
         └─ only for items that came back REAL. RED test → fix → bite proof →
            quality + validate + diff-cover.

PHASE 3  Review round 1 (read-only, parallel lenses per PR)
         └─ security-breaker (mandatory) · correctness · concurrency · test-bite
            (test-bite must independently mutate and re-verify, restoring from a cp copy)

PHASE 4  Remediate (single writer per worktree, reproduce each finding first)

PHASE 5  Review round 2 — then STOP. Escalate whatever is left.
```

### Skills to use — do not reinvent

| When | Skill | Why |
|---|---|---|
| Before touching either defect | **systematic-debugging** | Both items are "reproduce before changing". The ledger has already been wrong once about F-05/F-06's current state |
| Any behavioural change | **verification / TDD discipline** (§2.2) | The bite proof is the deliverable, not the passing test |
| Item 3 | **operations-runbook** | `schema_migrations` is operator-facing: what it does on boot, and what a read-only volume means |
| Item 3 review | **doc-critic** | Catches code-vs-doc mismatch — the exact risk when documenting freshly-written code |
| Before merge | **security-review** | Mandatory for Stream B per `AGENTS.md`; both items are cost-honesty code |
| Quality pass | **taste-check** | Only after correctness; never let it drive a billing fix |
| Routing | `make skill-route` / `make next` | The repo's own deterministic router |

---

## 4. Boundaries — do NOT do these

- **Do not touch `feat/ui-pr1-quickfixes`** or its worktree. Another session owns it.
- **Do not re-fix F-01 or F-02.** They are merged and deployed.
- **Do not re-open the money-envelope decision here.** It was operator-ratified on PR #95
  (~$0.078 → ~$0.183 per account per 24h; `DAILY_CAP_USD` stays 0.20). **But see §5.**
- **Do not delete** the five `.claude/worktrees/wf_86c1a1b8-b4b-*` worktrees — they hold
  another session's uncommitted work.
- **Do not widen scope** into the P3 deferred list (`/ui` session minting, `/feedback/audit`
  gate, CSP `unsafe-inline`, simulated sources flagged `is_fallback=False`, feedback retention,
  the auth GC lock). File issues instead.

---

## 5. Operator-gated — needs a human decision, not your judgement

1. **The money envelope will move again when `feat/ui-pr1-quickfixes` merges.** Measured: that
   branch's WP-D token caps (2000/3000) plus the WP-G1 NVIDIA-nano slot swap push the
   default-mix unit price from **$0.0244 → ~$0.031**, so the ratified ~$0.183 / 7-runs figure
   becomes wrong (~6 runs). F-01's tripwire —
   `test_daily_cap_admits_the_number_of_runs_its_dollar_value_pays_for` — fires with
   *"the pinned static catalog's default-mix price moved to 0.0310; re-measure the envelope
   before updating this constant"* and **blocks that merge until re-measured and re-ratified.**
   That re-measurement belongs to whoever merges that branch. **It is not yours to silently
   update.** Flag it; do not touch the constant.
2. **Pushing branches / opening PRs / merging / deploying** — all need explicit approval.
3. **Any paid live run.** Default to $0.

---

## 6. Traps this repository has already sprung

- **Stale local `main`.** An agent ran `git rebase main` against a local `main` two commits
  behind `origin/main` and silently rebased off a merged PR, putting ~220 lines of unrelated
  work in the diff. **`git branch -f main origin/main` before handing worktrees to agents**,
  and always diff against `origin/main`.
- **`git checkout <file>` to undo a mutation** destroys uncommitted work. Restore from a `cp`.
- **`make quality` green ≠ CI green.** See §2.3.
- **Process-global test state.** The cost event ring, the run-capacity semaphore, and the
  model catalog are all process globals. A test that drains and "restores" a `BoundedSemaphore`
  restores it to its *bound*, not to what it drained — minting a phantom permit that kills
  in-flight workers. Use `tests/helpers.isolated_run_semaphore`.
- **A clean auto-merge is not a correct merge.** Verify the merged result semantically (run
  the suite on it), not just the absence of conflict markers.
- **Compound shell one-liners lie.** A `tar --wildcards` flag macOS does not support silently
  produced "0 hits" and nearly caused a wrong conclusion. When a number looks impossible,
  re-derive it a second, simpler way before reporting it.

---

## 7. Definition of done

- [ ] F-05 fixed with a bite-proof RED→GREEN test, **or** refuted with evidence
- [ ] F-06 fixed with a **cardinality-asserting** RED test, **or** refuted with evidence
- [ ] `schema_migrations` documented where operators look; `make validate` green
- [ ] Backfill's production effect verified read-only, **or** explicitly recorded as unverified
- [ ] `/estimate` cluster reproduced+fixed, or closed with measured evidence and stated N
- [ ] Every PR: `make quality` + `make validate` + `make diff-cover DIFF_BASE=origin/main` green
- [ ] ≤2 adversarial review rounds, security-breaker lens included; leftovers escalated
- [ ] Nothing pushed, merged or deployed without explicit human approval
- [ ] Each merged PR deploy-verified: Deploy job `success` AND `/status build_sha` == merged SHA
- [ ] Worktrees and branches cleaned up after merge
- [ ] A close-out note recording what was fixed, what was refuted, and what stayed open

**Report honestly.** A refutation, a "could not reproduce in N runs", or a "could not verify —
here is the exact check that would" are all successful outcomes. A confident wrong answer is
the only real failure.
