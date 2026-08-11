ultracode, autonomous

Paste this whole file as your first message. Then work autonomously.

---

## 0. The one rule that governs this document

**Treat every sentence below as UNVERIFIED until you have executed it.**

AGENTS.md rule 11 records the measured decay rate of claims inherited from
handoff documents in this repository: roughly half do not survive contact with
the tree. The session that wrote this file proved the rule on itself — it
shipped six false claims into its own commits and ADRs, and adversarial review
caught every one. They are listed in §5 so you expect the same of your own work.

Every factual claim here ships with the command that proves it. Run the command.
If it disagrees, **the sentence is wrong** — say so out loud and fix it. Never
repair a false premise silently (rule 3).

---

## 1. Read these first

1. `AGENTS.md` — the operating rules. Non-negotiable.
2. `docs/00-factory-console.md`
3. `docs/session-handoff.md`

Then `make next` and `make skill-route`. Prefer installed skills
(`.agents/skills/*`) over inventing an approach.

---

## 2. Ground truth — re-derive it

True at 2026-08-08T20:10Z. **Run the right-hand command before relying on any of it.**

| Claim | Command |
|---|---|
| `main` tip is `b904ce6` | `git rev-parse --short main` |
| local == origin | `git rev-parse main origin/main` |
| production runs `main`'s tip | `uv run python scripts/deploy_drift_check.py --repo imrohitagrawal/quorum-ai` |
| **1** branch, **1** worktree, **0** open PRs | `git branch; git worktree list; gh pr list --state open` |
| **14** open issues | `gh issue list --state open --limit 60 --json number --jq 'length'` |
| six required contexts | `gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'` |

Repository is clean: no stale branches, no orphan worktrees, no uncommitted
tracked changes. Leave it that way.

**Free production probes** (never cost money): `/ready`, `/status`, `/metrics`,
`/ui/ops`, `/estimate`. A full run is **not** free — ask first.

---

## 3. What the previous session shipped

**Three** PRs, all merged and verified running in production, all from issue
#245, which is now **closed**.

| PR | SHA | What |
|---|---|---|
| #279 | `f1eb7e4` | let the deploy gate run when a required workflow is red |
| #280 | `650a385` | escape the `+` so the E2E trigger actually matches |
| #281 | `b904ce6` | prove production runs `main`'s tip, and go red when it does not |

New ADRs **0024, 0025, 0026**. Read 0025 before touching any `workflow_run`
trigger and 0026 before touching `deploy-drift-watchdog.yml`.

**Three findings worth carrying forward, each measured:**

1. **`on.workflow_run.workflows` entries are FILTER PATTERNS, not literal
   strings.** `+ * ? [ ] !` are metacharacters. `"E2E (axe + parity)"` parsed as
   `E2E (axe` + one-or-more SPACES + ` parity)` and could never match its own
   workflow — E2E had fired **0 of 46** Deploy runs while CI and Tests fired
   47/47 each. Escape it, in **single quotes** (`\+` is a `ScannerError` inside a
   double-quoted YAML scalar, which would make the file unparseable and stop
   *every* trigger). Verified live twice since the fix.

2. **A `workflow_run` run is stamped with the DEFAULT BRANCH's `head_sha`.** So a
   Deploy run created by a *pull-request-branch* CI run appears under `main`'s
   SHA, and skips. This misled three separate analyses in one session. It also
   means **AGENTS.md rule 18a's "resolve the newest run by `createdAt`" is no
   longer sufficient** — the newest can be an unrelated PR-branch skip. Resolve
   by which run's gate job actually ran, or ask what production serves.

3. **The deploy gate's fail-loud contract had never once fired.** 238 Deploy
   runs since the check landed, zero failures, because the gate job's `if:`
   skipped it whenever a required workflow was red.

---

## 4. Pending work

### 4.1 The two things a human must do

- **Delete the historical Sentry events.** #277 stopped future sends; stored data
  stays until someone deletes it there. Two populations: a few hundred
  `environment: local` error events from 6-7 Aug (test noise), and — more
  importantly — **production transaction events that may contain raw user query
  text**, because `before_send` was never called for transactions before #277.
  Open a Performance/transaction event and check `request.data`.
- **Delete the throwaway probe repo `imrohitagrawal/wfrun-glob-probe`**, or grant
  the scope so an agent can: `gh auth refresh -h github.com -s delete_repo`.
  It exists only as evidence for #280's claim and is no longer needed.

### 4.2 Candidates from the 14 open issues

Re-run selection yourself (rule 20). These are the previous session's triage,
verified by execution, offered as a starting point and **not** a shortlist to
recycle — AGENTS.md records handoff chains narrowing the backlog while it grew.

- **#268 — `max_cost_usd` bounds every call's OUTPUT but nothing bounds its
  INPUT.** REAL, live, money. The catch: **the magnitude cannot be measured from
  existing data.** `max_cost_usd` is never written to any durable event payload
  (`grep -rn max_cost_usd src/` → only `costs.py` and `app.js`), so the ledger
  can tell you actual-vs-*estimate* and never actual-vs-*max*. Decide the
  semantics before building.
- **#203 — credential probe cannot distinguish a proxy 403 from a provider 403.**
  REAL, live, but not firing today (prod reads `state: live`). Its stated blocker
  has **dissolved**: since ADR-0012 the repo holds a real captured OpenRouter
  error envelope and a byte- and time-bounded body sniffer
  (`providers._billing_evidence_shape`, `_read_within_budget`). The honest fix is
  a one-sided classifier — treat 401/403 as `unauthorized` only when the body
  parses as OpenRouter's envelope, `unknown` otherwise, which fails safe.
- **#167 — recommend CLOSING, not building.** Everything actionable is done: all
  3 named defects fixed, option 1's tool built (`tests/code_text.py`), option 1's
  lint measured and rejected. What remains is gated by the issue's own homework
  ("replay it: how many of the last N guard tests would it have caught?"), which
  AGENTS.md's own rule binds. Close it with the evidence, or re-scope.

**Deliberately NOT recommended, with reasons:**
- **#105** — step 2 requires "a week of production logs" and **nothing retains
  them**: no log drain (`DEPLOY.md:206` lists it as future work), and the records
  are `WARNING`, so Sentry's default `ERROR` threshold turns them into
  breadcrumbs only. Blocked on infrastructure, not effort.
- **#216** — zero exposure while `judge_enabled: false` in production.

---

## 5. Traps measured 2026-08-07/08 — these cost real time

Each is a mistake the previous session actually made.

- **A mutation that does not apply looks exactly like a test that does not
  bite.** A nested-quoting `python3 -c` inside a shell loop silently no-op'd and
  reported a false "8 passed". **Assert the anchor exists before mutating**, and
  use a heredoc rather than nested quotes.

- **`cd /tmp && ... ; rm -rf build` deletes `/tmp/build`, not the repo's.** A
  compound command's `cd` persists through the whole line. Use absolute paths for
  anything destructive.

- **`--limit 200` is a SAMPLE, not the population.** "Zero failures in 200 runs"
  was written as "had never once executed"; there were 27 failed runs in history.
  Scope every count to a window and say which.

- **The Actions API keeps a ROLLING window**, so run counts are not reproducible
  later. Label them a dated snapshot with the command, or a reviewer will refute
  them correctly.

- **A worktree does not share `.venv` or `.env`.** With no `.python-version`, a
  fresh worktree built on **CPython 3.14.5** while CI runs **3.12** — tests there
  were not running what CI runs. Always `uv venv --python 3.12` in a new worktree
  and check `uv run python -V`.

- **`git worktree remove` needs `--force` if the worktree has a `.venv`.**

- **The ADR index conflicts on every stacked PR.** It is DERIVED — resolve by
  running `python3 scripts/generate_adr_index.py`, never by hand (rule 16d).

- **Elapsed wall-clock is much shorter than it feels.** Several times the session
  judged CI "stuck" when three minutes had passed. Run `date -u` before
  concluding anything is hung.

- **`e2e/tests/review/` makes `make quality` RED locally and green in CI.**
  Gitignored; a fresh worktree does not have it, so the worktree is green and the
  main checkout is red. Run `ls e2e/tests/review/` before blaming your diff.

---

## 6. How to work

- **Ask before**: any paid API call, any deploy, any push, any PR, any merge, any
  destructive delete. Commit locally freely.
- **One concern per PR** (rule 17). Dedicated `git worktree`, never the main
  checkout. Merge `main` in **before** starting.
- **Fan out for review, never for building** (rule 9). Tell every reviewer **IN
  CAPITALS** not to write, edit, `git checkout`, `git stash` or `sed -i`.
  **Two lenses, not five** (rule 10). Cap at **two rounds** (rule 12) and budget
  one for the defect your own fix introduces — it happened three times running.
- **Tell reviewers to audit the diff's PROSE** (rule 11a), verbatim: *"for every
  number, superlative, and causal claim in the diff's comments, commit body and
  PR description, name the command that produces it — or mark it UNVERIFIED."*
  This was the single highest-yield instruction of the last session: every one of
  the six false claims lived in prose, none in code.
- **Test the WIRE, not just the decision.** A pure function with a thorough test
  table still shipped two mutations that survived: deleting the `$GITHUB_OUTPUT`
  write, and renaming its key. Both would have made the gate permanently green.
  Write one test that drives the real entrypoint and asserts the observable
  artifact, and one that pins the contract on **both** sides.
- **An ADR in the same PR as the decision** (rule 16d).
- **Close more than you open** (rule 19).

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

`docker-build` is covered by **nothing local**. Run e2e per rule 13 if you
touched UI, specs or fixtures.

### Close-out, every time (rule 18a)

1. Local gates green and every review finding resolved
2. Merge with an **explicit** squash message (rule 17c)
3. **Verify the deploy**: the deploy **job** ran (read the job, not the rollup),
   `/status.build_sha` equals the merged SHA, and the thing you built fires.
   Expect 3-5 Deploy runs per SHA now; several are cancelled or PR-branch skips.
   The reliable resolution is `scripts/deploy_drift_check.py`.
4. `git merge --ff-only origin/main`, delete the branch local **and** remote,
   remove the worktree

### Your first four commands

```bash
cd /Users/rohitagrawal/Projects/quorum-ai
git fetch origin && git status && git log --oneline -8
gh issue list --state open --limit 60
uv run python scripts/deploy_drift_check.py --repo imrohitagrawal/quorum-ai
```

Then re-derive §2, pick a work package, and **state in one line why it outranks
the top of the backlog**. If that line cannot be written honestly, re-rank.
