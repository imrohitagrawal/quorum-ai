# ultracode — continue with #402, then #290 (bounded), unattended

You are the MAIN ORCHESTRATOR for an unattended autonomous run on quorum-ai.
I am not available. Nobody will answer a question. Do not wait for one — if you
hit a genuine STOP condition, log it plainly, skip that item, and move to the
next. Never guess your way past a STOP.

Read `AGENTS.md` first — every rule in it applies to you AND to every
sub-orchestrator you spawn. This prompt sequences work across it; it does not
override it.

## Non-negotiables (same as the last run — do not relax these)

- **SPEND NOTHING.** `OPENROUTER_LIVE_EXECUTION_ENABLED` stays `false`. If an
  item needs spend to validate, build it hermetically, mark that validation
  UNVERIFIED, and say so. **Never open a live-execution window unattended, and
  never make the "one deliberate paid probe" #290 describes — that is an
  explicit STOP condition for this run, see Item 2 below.**
- **One work package at a time, fully closed before the next starts.**
- **Fan out for review, never for building.** Subagents share one working tree.
- **Cap review at two rounds per package.** If a third would be needed, STOP
  that package, write up exactly where it stands, and move on.
- **Never move a money/safety constant. Never touch W3 or W13/#268.**
- **Verify by executing, never by reading** — including your sub-orchestrators'
  self-reports. "Merged and deployed" is a claim; you re-run the check yourself.
- **A background-task notification's "exit code 0" can be the WRAPPER's exit
  code, not the command's.** Measured this session: a compound command
  (`make quality > log 2>&1; echo "EXIT=$?"; tail log`) backgrounded, then
  reported "exit code 0" while `make quality` had actually failed (`Error 1`,
  8 failed tests) — the reported code was the last command in the chain
  (`tail`), not `make`'s. **Always grep the log itself for the make target's
  own terminal line (`make: *** [test] Error` or the pytest summary line) —
  never trust a wrapper's reported exit code.**
- **Local gate commands finish in minutes — run them in the foreground and
  read the exit code directly. Do NOT background a local `make` target and
  end your turn waiting for a notification.** That pattern is reserved
  ONLY for the GitHub CI-checks loop and the Fly.io deploy-wait loop (both
  take many minutes of genuine external wait). Measured this session: both
  sub-orchestrators repeatedly backgrounded local gates and stopped their
  turn, requiring the orchestrator to resume them each time — wasted several
  round trips for no reason. Don't repeat it.

## Starting state (verify before trusting — do not assume anything below is
## still true; the last run ended at a known point but time has passed)

```bash
git -C . fetch origin && git status -sb && git worktree list
python3 scripts/check_open_work.py --check
gh issue list --state open
curl -s https://quorum.stackclimb.com/status | jq '{build_sha, live_execution}'
```

Expected as of the end of the last run (2026-09-01): `origin/main` build_sha
`0d5be18f2a831abf2e0fe67a082d8cf35103889a`; board 22 rows, 3 PENDING / 14 DONE;
local `main` several commits ahead of `origin/main` with docs-only commits
(the prior run's log plus the `#402` design postmortem) — **check whether
those have since been pushed; if `git status -sb` shows `ahead N`, that is
expected and fine, do not try to "fix" it by force-pushing or rebasing away
history.** Open issues expected: `#402` `#290` `#268` `#105` (`#418` closed
last run).

**Do not touch or rebase away `docs/analysis/2026-09-01-overnight-run.md`,
`docs/analysis/2026-09-01-402-freshness-gate-design.md`, or
`docs/analysis/2026-09-01-autonomous-run.md`.** Confirm all three still exist
before starting and after every `git rebase origin/main` you run.

## Your job vs. the sub-orchestrator's job

You NEVER write code, run tests, or touch git yourself, with the exception of
read-only verification commands, and you own the CI/deploy waiting.

Loop per item: re-verify it's still real and still open → spawn ONE
sub-orchestrator with a self-contained brief → wait for genuine progress
(not premature stop-and-wait on local commands) → INDEPENDENTLY verify every
claim it makes → append one entry to the run log → next item.

Each sub-orchestrator is a FRESH `Agent` call (`subagent_type:
"general-purpose"`, full tools — never `"fork"`).

## Run log

Continue `docs/analysis/<today>-autonomous-run.md` if today's date matches
the prior run's file, otherwise create a new dated file (do not overwrite
`2026-09-01-autonomous-run.md`). Same structure as before: a Summary section
at the top (shipped/verified, stopped/why, left for human), then one Package
log entry per item with the full independent-verification subsection —
command run, output, conclusion — separate from what the sub-orchestrator
self-reported. Commit it LOCALLY ONLY. Do not push anything without explicit
human approval (rule 17b) — that includes any commits from the PRIOR run
still sitting unpushed on `main`; leave those exactly as you find them unless
told otherwise.

---

## Item 1 — #402: the board-anchor freshness gate cannot see a squash-discarded commit

**Read `docs/analysis/2026-09-01-402-freshness-gate-design.md` IN FULL before
writing anything.** This is not optional background — it is the record of two
prior fix rounds, each of which shipped a test suite that was 100% green and
13/13 mutation-killed while pinning the WRONG contract (§5, §8, §12). Skipping
it means repeating exactly that.

### The bug

`scripts/check_open_work.py::check_freshness` requires the `Verified at:`
anchor in `docs/65-open-work.md` to be an ancestor of `HEAD` and within
`MAX_DRIFT_COMMITS` of it. On a feature branch, a commit made on that branch
IS an ancestor of `HEAD` — so the gate passes on the PR. This repo
squash-merges, discarding the branch commit, so on `main` after merge the
anchor is neither present nor an ancestor, and the gate refuses far too late
(after merge, not before). Reproduced live on PR #399 → `main` red.

### The shape that survived measurement (§9 of the design doc) — build THIS, not a new idea

1. Resolve a "known `main`" in this order: `refs/remotes/origin/main`, then
   any other remote-tracking `*/main`, then local `refs/heads/main`.
2. If NO `main` is resolvable anywhere (a `git init` sandbox with no remote
   and no local `main`), skip — and SAY SO in the report line, not silently.
3. If more than one is resolvable and they disagree, the anchor must be an
   ancestor of AT LEAST ONE (covers the fork-behind-upstream topology without
   a heuristic).
4. A stale `origin/main` producing a false refusal is an ACCEPTED, hedged
   limitation — name `git fetch` as the remedy, but never claim one fetch
   always clears it (the design doc's §9.4 — the fork-behind case can still
   need more than one fetch).
5. Every skip path needs a same-shape POSITIVE partner: a branch-only anchor
   must still be caught as a failure through that same path (rule 7).

### Known-bad shapes — do NOT rebuild these, they were measured and killed

- Comparing against `HEAD` alone (the original bug).
- Comparing against `merge-base(HEAD, origin/main)` alone — §1/H1 of the
  design doc proved this is strictly WEAKER than comparing against
  `origin/main` directly (it can only refuse MORE often), so it does not
  escape the stale-remote false positive; it is not an "escape hatch."
- A `_origin_tracks_main` refspec-parsing helper that only reads the FIRST
  line of `remote.origin.fetch` — §12 of the design doc found a live
  regression here: `git remote set-branches --add origin main` (the exact
  remedy an affected user would run) puts `main` on the SECOND line, and the
  helper silently mis-answers. If you build any refspec-matching logic,
  parse ALL lines, and add the four disagreement cases from §12's table as
  test cases:
  | `remote.origin.fetch` | naive parse says | git actually does |
  |---|---|---|
  | `refs/heads/main` (no colon) | tracks | ref stays ABSENT after fetch |
  | `+*:refs/remotes/origin/*` | tracks | ref ABSENT after fetch |
  | `+main:refs/remotes/origin/main` | does not track (no `*`) | git DOES create the ref |
  | refspec has `[`/`?` metacharacters | no exception | git rejects it outright |

### Procedure

1. **Plan** — read the design doc, `scripts/check_open_work.py` in full
   (especially `check_freshness` and any refspec-parsing helper), and
   `docs/65-open-work.md`'s `Verified at:` line and the two sentences
   explaining it. List, in your own words, the §9 shape's four steps and the
   §12 refspec table BEFORE writing code — this is rule 16e for a change to
   the gate every other package's merge safety depends on.
2. **Worktree**: `git fetch origin && git worktree add ../quorum-ai-402-freshness -b fix/402-board-anchor-freshness origin/main`.
   `uv sync --all-extras --python 3.12` BEFORE any `uv run`. `PYTHONPATH=src`
   for `import product_app`.
3. **TDD with bite-proof**, informed directly by the design doc's measured
   requirements list (§6 in the doc — re-read it for the full 11-requirement
   table if present, or reconstruct the "known main resolution + at-least-one
   ancestor + explicit skip + refspec multi-line" requirements from §9/§12
   above) and its mutation table (§8) — your new tests must kill the FOUR
   specific mutants the design doc's own late addendum (§12) found surviving
   the prior 46-test suite (the two behaviour-changing mutants: moving
   `_origin_tracks_main` inside the missing-ref branch, and `splitlines()[:1]`).
   RED first, capture verbatim output, GREEN it, then mutation-prove with
   `PYTHONDONTWRITEBYTECODE=1`, restore via `cp` copy (never `git checkout`).
   The design doc's §7 test-helper hardening (pin `-c commit.gpgsign=false`,
   build test remotes with `git remote add` + `git update-ref` not a push,
   set `GIT_COMMITTER_NAME/EMAIL` explicitly, never `-c core.hooksPath=/dev/null`)
   is worth reusing verbatim — it is called out as salvageable in §12's last
   paragraph.
4. **Gates**, foreground, exit code read directly from the log's own terminal
   line (see Non-negotiables above): `make quality`, `make validate`,
   `make diff-cover DIFF_BASE=origin/main`, `make openapi-check`,
   `make security-scan`, `make api-contract`. Known local-only noise:
   `e2e/tests/review/` (check `ls e2e/tests/review/` first), macOS visual
   lane, W23 advisory mutation gate.
5. **Review — max 2 rounds, and this is attempt #3 overall.** If a real
   defect survives 2 rounds, or two fix rounds in a row each add a new one,
   **STOP per rule 12 — do not attempt a 4th time in this run.** Write a
   `docs/analysis/<today>-402-attempt-3.md` in the same style as the existing
   postmortem (provenance-tagged claims, [me]/[reviewer]/UNVERIFIED, the
   mutation table, what specifically broke) and move to Item 2. This is a
   legitimate, good outcome per AGENTS.md — not a failure of the run.
   Reviewer instructions: at minimum one reviewer whose SPECIFIC job is to
   try the four requirement classes above (stale remote, fork-behind
   upstream, no-remote sandbox, multi-line refspec) against your actual
   implementation, not just read the diff. Verbatim IN CAPITALS to every
   reviewer: "YOU ARE READ-ONLY. DO NOT WRITE, EDIT, `git checkout`,
   `git stash`, `sed -i`, OR RUN pytest IN THE SHARED WORKTREE. If you must
   run or mutate anything, make your OWN copy with `git archive HEAD | tar -x
   -C <your dir>` and work there." And: "for every number, superlative, and
   causal claim in the diff's comments, commit body and PR description, name
   the command that produces it — or mark it UNVERIFIED."
6. **Board.** `docs/65-open-work.md`'s `Verified at:` anchor stamping logic —
   confirm `python3 scripts/check_open_work.py --check` exits 0 after your
   fix, from a state that mimics a POST-merge `main` checkout (not the
   worktree with the branch commit still fresh), since that is exactly the
   scenario the original bug hid in.
7. **PR + close-guard + merge + deploy-verify + close-out** — same procedure,
   recipes, and exact order as the prior run (CI-checks loop keyed on
   `bucket`, deploy-wait loop requiring non-zero AND complete, per-run Deploy
   JOB conclusion never the rollup, `curl /status` build_sha match). Ask for
   `EXPECT_CLOSE="402"` if the fix ships; if you STOP instead, no PR to merge
   — just the postmortem, locally committed only.

---

## Item 2 — #290: peer critique (BOUNDED unattended scope — read this before starting)

**This item has a hard boundary you must not cross unattended.** Read the
full issue body (`gh issue view 290`) before starting. It already contains a
worked design (fan-out inside `DebateOrchestrationService`, reusing
`_call_debate_model` with a required `model_id` param, `DebateOutput` gaining
a nested critiques list with a shape discriminator, eligibility gating on
"answer completed and actually invoked").

### What you MAY do unattended (hermetic, no spend, no shipped billing-schema change)

1. **Rule 16e failure-mode enumeration**, in writing, before any code: for
   the billing change specifically (`DebateResult.live_call_usages` gaining a
   `model_id` per record; the "Debate + synthesis" cost-breakdown row at its
   two sites — the estimate path and the measured path). Enumerate at least:
   what happens to an in-flight run's existing usage records that predate
   this field (schema/back-compat), what happens if a critique call is
   cancelled mid-flight (billing partial critiques correctly — the issue
   already names `should_stop` un-billing undispatched critics as a
   requirement), what happens if two slot models are actually the SAME
   `model_id` (do NOT double-charge or conflate their usage rows), and
   whether the cost-breakdown UI can render a per-model breakdown or only a
   pooled one.
2. **A design write-up ADR** (`docs/adr/`) proposing the exact schema for the
   critique-carrying `DebateOutput` and the `model_id`-carrying usage record,
   WITHOUT implementing it — this is a decision doc for the human to read and
   approve or redirect, per rule 16d. Include the rejected alternative (one
   row per (round, model), which the issue itself already rules out because
   `app.js` keys a Map by round number and would silently keep only the last
   critic — verify this claim by reading the actual `app.js` Map-keying code,
   don't just repeat the issue's assertion unverified).
3. **Hermetic scaffolding only if it can be built and tested with NO real
   provider call and NO change to what a real run bills**: e.g., the new
   `DebateOutput` dataclass/schema shape with unit tests against synthetic
   data, the eligibility-gating logic (only completed+invoked slots
   critique) as a pure function with unit tests, updated `app.js` Map-keying
   to handle a critiques-list shape (tested against synthetic fixtures, not
   a live run). Each such piece, if built, still follows full TDD +
   mutation-proof + the two-round review cap, and still needs its own
   decision on whether it's shippable alone (a schema change with no
   feature wired to it yet, correctly gated so it changes no runtime
   behavior) or whether it must wait for the full feature — decide from the
   code and state the reasoning, same as the W21/W22 clubbing decision last
   run.

### What you MUST NOT do unattended — STOP and hand back instead

- **Do not make the "one deliberate paid probe"** the issue names (a real
  provider call to measure critique latency against the 8s timeout at the
  2000-token cap). This requires `OPENROUTER_LIVE_EXECUTION_ENABLED` and
  real spend — it is explicitly out of scope for an unattended run under
  this repo's hermetic/$0 default and this run's own non-negotiables.
  **When you reach the point where the timeout risk must be settled to
  proceed, STOP THERE.** Write up exactly what's built, what the ADR
  proposes, and that the probe is the next human-gated step. This is the
  correct, expected stopping point for this item in an unattended run — not
  a failure.
- **Do not merge any change to the billing/cost-breakdown SHAPE that a real
  run's users would see** without it being reviewed as a deliberate decision
  by a human — an ADR proposing it is fine and expected; actually flipping
  what a receipt shows for real traffic is not, without sign-off.
- **Do not attempt the full multi-model fan-out mechanism inside
  `DebateOrchestrationService`** in this run if it cannot be verified without
  a real provider call — a debate orchestration change is exactly the kind
  of thing that looks right against a mock and is wrong against real
  multi-model timing/formatting, which is the whole reason the issue asks
  for a probe first.

### Procedure for whatever hermetic slice you do build

Same worktree/TDD/mutation-proof/gates/two-round-review/PR/close-guard/merge/
deploy-verify/close-out procedure as every other package this run and last.
If you ship nothing (only the ADR + failure-mode doc, no code), say so
plainly — writing the design and stopping at the paid-probe boundary is a
complete and correct outcome for this item, not a partial one.

---

## Stop conditions for the whole run

Stop early if two packages in a row fail to close cleanuly — pause, write
both up, end the session. Otherwise: attempt #402 to a clean close or a
documented stop (attempt #3, do not go to #4), then #290 up to its ADR/design
boundary (do not cross into the paid probe or the full feature), then write
the final summary — what shipped and is verified in production, what
stopped and why, what needs your decision (the paid-probe go/no-go for #290
foremost among them).

Never push, merge, or deploy anything you have not personally verified
through a command's actual output. Rule 18: done means merged AND verified
running in production.
