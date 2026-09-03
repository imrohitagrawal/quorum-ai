# Autonomous run — build W2 (#290 peer critique), then W3 (the money constants)

You are the MAIN ORCHESTRATOR for an unattended run on quorum-ai. The owner is
NOT available. Nobody will answer a question. If you hit a genuine STOP
condition, log it plainly, skip that item, move to the next. **Never guess your
way past a STOP.**

Read `AGENTS.md` IN FULL first. Every rule in it binds you AND every
sub-orchestrator you spawn. This prompt sequences work; it does not override
`AGENTS.md`.

---

## Non-negotiables

- **SPEND NOTHING WITHOUT A DECLARED WINDOW.** `OPENROUTER_LIVE_EXECUTION_ENABLED`
  stays `false` except inside Item 3's explicitly authorised window. Never open a
  window for convenience.
- **One work package at a time, fully closed before the next starts.**
- **Fan out for REVIEW, never for BUILDING.** Subagents share one working tree.
- **Cap review at TWO rounds per package** (rule 12). A third means STOP, write
  up where it stands, move on.
- **Verify by executing, never by reading** — including your sub-orchestrators'
  self-reports. "Merged and deployed" is a claim; re-run the check yourself.
- **A background task's reported "exit code 0" can be the WRAPPER's.** Always
  grep the log for the target's own terminal line (`make: *** [test] Error`, or
  the pytest summary). Never trust the wrapper.
- **Run local `make` targets in the FOREGROUND.** They finish in minutes.
  Backgrounding-and-waiting is ONLY for the GitHub CI loop and the Fly deploy
  loop.
- **Never read a gate's exit status through a pipe** (rule 13f). Write:
  `make <t> > /tmp/g.log 2>&1; echo "EXIT=$?"; tail -40 /tmp/g.log`
- **Push, PR, merge and deploy are AUTHORISED for branches you create in this
  run.** Do NOT push anything else.

## Standing traps (all measured — do not re-learn them)

- `uv sync --all-extras --python 3.12` BEFORE any `uv run` in a fresh worktree.
  A bare `uv run` builds a 3.14 venv with no pytest and fakes failures.
- `e2e/tests/review/` holds gitignored scratch specs that make
  `test_no_orphaned_e2e_specs` RED locally and green in CI (rule 13a).
  `ls e2e/tests/review/` before blaming your diff.
- The macOS visual lane fails 8/8 on clean `main` (rule 13e). **Never**
  `--update-snapshots`.
- `timeout` does not exist on this box (rule 13c). Use
  `perl -e 'alarm shift; exec @ARGV'`.
- `ruff check` printing `All checks passed!` does NOT mean `make quality`
  passed — mypy runs after ruff.
- COMMIT before trusting `make diff-cover` (rule 15a); run it serially with
  pytest (rule 15).
- One merge yields 3-5 deploy runs, most `cancelled` by concurrency. Resolve the
  NEWEST by `createdAt` and read its **Deploy JOB**, never the run rollup.
- `gh run list --commit <SHA>` is unreliable; cross-check with `--branch main`
  and a SHA match.
- Squash-merge with an EXPLICIT subject and body (rule 17c), vetted by
  `make close-guard` with the text passed through the ENVIRONMENT.
- **Assign ADR numbers CENTRALLY before dispatch.** Read `docs/adr/` on
  `origin/main`, not in a stale checkout — that mistake produced a duplicate
  ADR-0092 in a prior run.
- Do NOT run `git branch -f main origin/main` or `git merge --ff-only origin/main`
  if local `main` has diverged with unpushed commits. Check first.

---

## Item 1 — build W2 / #290, peer critique

**Read first, in full:** `gh issue view 290 --comments`,
`docs/adr/0093-a-peer-critique-nests-inside-its-round-and-a-critics-spend-gets-its-own-row.md`,
`docs/adr/0094-the-post-290-money-constants-are-pre-computed-and-wait-for-the-feature.md`,
and the W2 narrative in `docs/65-open-work.md`.

ADR-0093 is the APPROVED shape. Build it; do not redesign it. Its five decisions:

1. `DebateOutput` keeps ONE element per round; peer detail nests behind a
   `critique_shape` discriminator. **Do NOT use one row per (round, model)** —
   `app.js:1829` keys a Map by `round_number` and would silently keep only the
   last critic, and `app.js:4816` would report "8 rounds" for a 2-round run.
1a. **Renderers read `critique_text`; DECIDERS read `slot_critiques`.** This is
   the distinction two CRITICAL_BLOCKERs turned on. `synthesis_consensus.py:641`
   (`_debate_signals_convergence`, reached from `:426`) is a DECIDER — pooling
   four critics there lets any one flip the panel and bypass #185's guard.
   `SYNTHESIS_DEBATE_EXCERPT_MAX_CHARS` (`synthesis.py:203`) is the bound that a
   naive digest falsifies, silently dropping ~3 of 4 PAID critics at
   `synthesis.py:785-787`.
2. The usage tuple does NOT widen. Attribution rides on `TokenUsage.model_id`,
   which already exists and is stamped at `debate.py:935`.
3. Critique spend gets its own `kind="critique"` `by_model` row per critic.
   `model_id` = the critic's; `display_name` = catalog short name PLUS a
   critique marker (`app.js:6519` and `:4364` use `display_name` as the ENTIRE
   label, so a bare name prints twice with two different figures); critique rows
   go LAST. The composite key `${kind} ${model_id}` (`app.js:4350`) must stay
   unique — it resolves with `.find()` (`:4359`) and de-duplicates with a `Set`
   (`:4384`), so a collision renders one figure twice and loses the other.
4. **Rename the writer row `Debate + synthesis` -> `Synthesis`** (two sites:
   `costs.py:1533` estimate path, `costs.py:2220` measured path, plus the
   `app.js:6519` ternary). Under a fully-eligible peer run that row holds NO
   debate spend at all.
5. **The telemetry record gains `query_run_id` + `stage`/`round`, IN THIS WORK
   PACKAGE.** `TELEMETRY_FIELD_NAMES` (`telemetry_sink.py`) currently has none of
   `query_run_id`, `stage`, `round`, `slot_number`, `finish_reason`, elapsed —
   verified by grep, zero hits each. **Also add `finish_reason`** (ADR-0094's
   consequences require it): truncation is currently INFERRED from
   `completion_tokens == max_tokens`, and Item 3 is blind without it.

Other binding constraints:
- Only ELIGIBLE slots critique — answer completed AND actually invoked. Keep the
  moderator path for when zero slots were invoked.
- Round cardinality stays 2. `debate_round_1`/`debate_round_2` are stage names in
  the API, UI and cost breakdown.
- `should_stop` must un-bill undispatched critics. Note `synthesis.py:1424` is a
  `ThreadPoolExecutor(max_workers=20)`, so "un-bills up to three" holds only for
  a SEQUENTIAL dispatch — the count is a race, the contract is per-round.
- `model_slots.py:378-386` REJECTS two slots sharing a model id, so that case is
  unreachable. The real duplicate is moderator-vs-slot and it ships by default
  (`config.py:544` == `model_slots.py:69`).
- `openapi.yaml` is generated and byte-compared. `make openapi-check`.
- Two gates pin OPPOSITE `by_model` orderings:
  `tests/integration/test_cost_gate_js.py:145` (`labels[4] == "Debate + synthesis"`)
  and `tests/unit/test_cost_breakdown.py:129-133` (`len == 5`, `by_model[-1]`).
  ADR-0093 keeps the index-4 pin because it is shared with the JS consumer. One
  of them MUST move; say which and why.

**Procedure.** Rule 16e failure-mode list in writing FIRST. Dedicated worktree
(rule 17a). Strict TDD: RED with verbatim output captured, GREEN, then mutation-
prove with `PYTHONDONTWRITEBYTECODE=1`, restoring from a `cp` copy — **never**
`git checkout <file>`. Report every mutation with BOTH fail and pass counts.
All six gates. Two review rounds max, reviewers READ-ONLY and told IN CAPITALS
not to write, edit, `git checkout`, `git stash`, `sed -i`, or run pytest in the
shared worktree; and told verbatim: *"for every number, superlative, and causal
claim in the diff's comments, commit body and PR description, name the command
that produces it — or mark it UNVERIFIED."*

**This is a large package.** Spawning a workflow or ultracode fan is explicitly
authorised for the REVIEW phase and for read-only analysis. Building stays
single-writer.

**`EXPECT_CLOSE="290"`** if it ships. Update W2's board row.

---

## Item 2 — the deferred UI/telemetry follow-ons, only if Item 1 closed cleanly

If Item 1 STOPPED, skip this entirely and go to the write-up.

- Verify the `kind="critique"` row renders end to end. ADR-0093 flags this as
  UNVERIFIED: `app.js:6519`'s ternary falls through to `row.display_name` for a
  non-`"synthesis"` kind, which was READ, not executed. Extend
  `tests/integration/test_cost_gate_js.py`.
- Add the eligibility-outcome field to telemetry (why a slot did NOT critique),
  so "3 critiques, not 4" is explicable after the fact.

---

## Item 3 — W3: the money constants, with a measurement window

**Do NOT start this unless Item 1 MERGED and is verified running in production.**
If Item 1 stopped, W3 stays STOP; say so and finish.

`docs/adr/0094-*.md` has the whole method and the pre-computed targets. **Do not
trust its table — re-derive it**, because #290 changes debate volume from one
call per run to eight.

1. **Open a declared window.** `configs/live-execution-windows.json` needs an
   entry in the SAME pull request that flips
   `OPENROUTER_LIVE_EXECUTION_ENABLED = "true"` in `fly.toml`, or the blocking
   posture gate refuses the merge. Fields: `owner`, `reason`, `mode`
   (`time_boxed`), `judge` (must match production's `judge_enabled`),
   `opened_at`, `expires_at`, ISO-8601 with explicit offset.
2. **Budget it BEFORE opening.** Price each question with the free
   `POST /v1/query-runs/estimate`. `DAILY_CAP_USD` is PER ACCOUNT and it
   reconciles to ACTUAL spend after each run completes (measured — the docstring
   implying the point estimate is misleading). `SESSION_MINT_CAP_PER_IP = 2`, so
   you get two cookie-less sessions per IP per 24h. **Rehearse the whole flow
   against a LOCAL instance first** — it costs nothing and no mint.
   The API: `GET /v1/session` -> cookie + `csrf_token`; then
   `POST /v1/query-runs/estimate` and `POST /v1/query-runs` with an
   `x-csrf-token` header AND a `safety_acknowledgements` entry
   (`{"warning_type":"sensitive_data","version":"2026-06-17","acknowledged":true}`).
   Set `slot_search: [true,true,true,true]` or no `:online` context is injected.
3. **Capture the baseline** (`flyctl ssh console -a quorum-ai -C "wc -l
   /data/telemetry-tokens.jsonl"`) so new rows are separable.
4. **Run at least three VARIED question shapes** — broad comparative, ambiguous
   low-signal, narrow factual. With ADR-0093 decision 5 shipped you can now group
   by `query_run_id` and `stage`/`round` instead of inferring from `model_id`.
5. **CLOSE THE WINDOW with `make close-window`** — it flips the flag AND expires
   the window atomically. Flipping the flag alone is REFUSED (#407). Verify
   `/status.live_execution` is `false` and that
   `gh issue list --label live-posture --state open` is EMPTY.
6. **Re-run the 715-mix sweep** (method in ADR-0094) against the post-#290
   numbers. **Parse JSON, never `grep` numeric fields** — a `grep -o
   '[0-9][0-9]*'` silently drops NEGATIVE values, which are real.
7. Land both token constants and all three thresholds in ONE pull request with
   the sweep as evidence. `SOFT < DAILY_CAP < HARD` is mandatory.
   `GLOBAL_DAILY_CEILING_USD` stays **$5.00** — owner constraint, do not move it.
   Token constants move in PAIRS with their enforced twins (`synthesis.py:140`,
   `debate.py:60` both carry "MUST stay in sync" and a test pins them).
   Write the ADR superseding ADR-0094's table with measured values.

---

## Item 4 — if time remains

`#105` (5xx classified as possibly-billed on a premise with no evidence) is open
and untouched. It needs production 5xx events, which the prior window gathered
ZERO of — so it is NOT a hermetic item. Assess and report; do not open a window
for it.

Also unowned and worth an issue: **220 of 715 catalog mixes (31%) are already
hard-refused today**, before any constant moves. Pre-existing, measured in
ADR-0094, nobody's item.

---

## Run log

Write `docs/analysis/<today>-autonomous-run.md`. Structure: a Summary at the top
(shipped and verified / stopped and why / left for the owner), then one entry per
package with an INDEPENDENT-VERIFICATION subsection — the command you ran, its
output, your conclusion — kept SEPARATE from what the sub-orchestrator reported.
Record your own errors; the prior run's log is the model. Commit locally.
Publish it only if the owner's rule applies: ADR-related, defines the shape of
the repo, a decisive move, or something to learn from. **Never push
`*-ULTRACODE-PROMPT.md` files** — they are executable procedure and stay local.

## Stop conditions

Stop the whole run if two packages in a row fail to close cleanly. Otherwise:
Item 1 to a clean close or a documented stop, then Item 2, then Item 3 ONLY if
Item 1 is in production, then the summary. Never push, merge or deploy anything
you have not personally verified through a command's actual output.
**Done means merged AND verified running in production.**
