# Session handoff — 2026-09-15 (the #471 rework, the #105 activation, the #290 close)

**Written 2026-09-15 by the session that reworked PR #471, took the #105
activation branch through five review rounds, and closed #290. Every number
below is paired with the command that produced it; if a command disagrees with
this file, this file is wrong.**

Read `AGENTS.md` first. Then this. Do not start from the code.

## 0. Preconditions for the next session

```bash
cd /Users/rohitagrawal/Projects/quorum-ai
git status --porcelain            # expect only CONTINUE-105-BACKLOG-ULTRACODE-PROMPT.md (untracked)
git rev-parse --short origin/main # expect e05950b or later
curl -s https://quorum.stackclimb.com/status | jq '{build_sha,live_execution,peer_critique_enabled}'
git worktree list                 # expect quorum-ai (main) and quorum-wt-105a (feat/105a-activate-search-fee @ 0e5fb94); the handoff worktree is removed in this PR's close-out
gh issue list --state open --limit 100 --json number | jq length   # expect 10
```

`live_execution` is **false**. `docs/session-handoff.md`'s "Production vs. last
`src/` commit: unavailable: could not reach https://quorum-ai.fly.dev/status"
line is #467's known bug in `scripts/session_handoff.py`'s probe (a reviewer
traced it to the module never being registered in `sys.modules` before
`exec_module`; that URL answers 200), not a production outage — read `/status`
directly. Nothing this session opened, extended or
re-affirmed a window, and nothing flipped `OPENROUTER_LIVE_EXECUTION_ENABLED`
or `PEER_CRITIQUE_ENABLED`.

## 1. What is merged and running in production

| what | merge SHA | deploy | verified how |
|---|---|---|---|
| PR #471 rework: the `:online` fee is FLAT per request; DEBT-014 measured; response key list committed; Part D4 ties evidence to the export | `5497e55` | Deploy job `success` (run 34886130740; two concurrent runs cancelled) | `/status.build_sha` = `5497e55…` read after the deploy |
| #290 closed (PR #472): board says peer critique has run in production, W3 money block records ADR-0102; live-run prompt archived | `e05950b` | Deploy job `success` (run 35022287018; two concurrent runs cancelled) | `/status.build_sha` = `e05950b…` read after the deploy |

`git branch -r` should no longer show `docs/debt-014-generation-endpoint-measured`
or `docs/290-peer-critique-built-close`.

## 2. What is PARKED — the #105 activation branch, and exactly what is left

`feat/105a-activate-search-fee` at **`0e5fb94`**, in worktree
`/Users/rohitagrawal/Projects/quorum-wt-105a`, **local only, never pushed this
session** (the remote still holds the 2026-09-13 tip `5d56a37`).

**The decision is TAKEN.** The product owner approved activating the fee at
$0.007 on 2026-09-15, in session, and re-confirmed it after being shown the
corrected cost (see §4). CHG-007 and ADR-0113 on the branch record it as
Accepted with the session reference. Do not write PROPOSED again.

**Gates on `0e5fb94` are green**: `make quality` EXIT=0 (4499 passed),
`make validate`, `make diff-cover` (1 executable line, 100%),
`make api-contract` (52 executed). Reverting the default to 0.0
(`Field(default=0.007, …)` → `default=0.0` in `config.py`) turns **18 tests red
in the full suite** and none green — 4 in `test_search_fee_is_activated.py`,
3 in `test_open_work_matches_reality.py` (the W24 needle flips), 2 each in
`test_bound_covers_the_judge.py`, `test_estimate_prices_the_judge.py` and
`test_peer_bound_is_a_true_ceiling.py`, 1 each in `test_cost_breakdown.py`,
`test_search_fee_field_validation.py`, `test_mutation_copy_completeness.py`,
`test_query_run_cost_guardrails.py` and `test_doc_gate_consistency.py`
(measured 2026-09-16, file restored byte-exact). All measured on this box;
re-run before trusting.

**Why it is parked.** Five three-lens review rounds. The fee change itself
(one `Field(default=0.007, ge=0, allow_inf_nan=False)` line) never changed
after round 1 and no round found a money defect. Every round after that was
about the decision RECORD, and fix rounds 2, 3 and 4 each introduced a
defect of their own (rule 12), so the owner's instruction "merge only if round
5 is clean" was not met. Round 5 left **two REQUIRED_CONTRACT findings, both
prose, and two advisory**:

1. ADR-0113 lines ~41-43 and ~128, and the activation test module
   (`test_search_fee_is_activated.py` under `tests/unit/`, on the branch only)
   lines ~33-34, still say in the PRESENT tense that OpenRouter's rate card
   implies ~$0.02/request, "3x the charge". The schedule read 2026-09-14 prices
   exa `auto` at $0.007 per request (DEBT-014 on main; CHG-007 on the branch
   cites it as corroboration). Rewrite as: the ~$0.02 was the July rate-card
   reading AC-037 carried; the current schedule matches the bill.
2. `docs/12-acceptance-criteria.md` line ~294 ("activation is now an open
   product-owner decision") and ADR-0110's Status block still describe the
   decision as open in the present tense. Rewrite as "was then open; taken
   2026-09-15 (CHG-007)".
3. (advisory) ADR-0113 §Consequences "every re-baselined literal moved by …
   and nothing else moved" over-reaches for two literals; soften.
4. (advisory) `tests/integration/test_query_run_cost_guardrails.py` comment
   "a seventh run it could not afford" — it was three runs (5th–7th).

**To finish (one bounded round):** apply 1–4 in the worktree, `make quality`,
one three-lens review on the result, and if ZERO REQUIRED_CONTRACT survive:
`git push origin feat/105a-activate-search-fee` (follow-up commits, no force),
`gh pr create` with `docs/analysis/2026-09-15-pr105-body-draft.md` as the body's
shape (it carries the five-round record; fill in the final round and gates), wait for the six required contexts, `make close-guard`
with `EXPECT_CLOSE=""` (activation closes nothing; #105's W14 stays open),
squash-merge, verify the Deploy JOB and `/status.build_sha`, then remove the
worktree and delete the branch local + remote. If anything survives, stop and
ask; do not run a sixth round on your own.

**Do not transcribe the consequence figures anywhere.** They live in ONE
place, ADR-0113 §"What it cost" (live catalog, 2026-09-15: point estimate
$0.0756 → $0.1036, runs 5 → 3, 106 mixes change band). Three transcriptions
were wrong in three different ways this session (judge OFF; judge
`gpt-4o-mini`; judge priced at the unknown-model fallback). The sweep now
refuses to run when the configured judge is not in the price table it was
told to use, and restores the globals it mutates; production's judge
(`openai/gpt-4.1-mini`, 4 of 4 judge rows in the 2026-09-10 telemetry) is NOT
in `_FALLBACK_CATALOG`, so there is no honest offline figure for production's
posture and the ADR says so.

## 3. What the survey items look like now

- **#471 (item 1)** — merged `5497e55`. Round-3 advisory leftovers recorded in
  the PR body, not fixed: no offline test computes the `0.007000` residual;
  the regex prose gate's known misses are pinned, not closed; ADR-0110's
  Consequences still carries the `estimate()`-raises sentence DEBT-015
  records as refuted (DEBT-015's concern); `config.py` says "PER SEARCHING
  CALL" where the register gate reds "per call" (unit-word inconsistency);
  every exa-mode enumeration omits `deep-lite`; **the provider now marks the
  `:online` suffix DEPRECATED in favour of its `openrouter:web_search` server
  tool** (recorded in DEBT-014's row on the branch; on main only in the PR
  body) — that is the largest staleness risk on the fee and belongs in a
  follow-up.
- **#105/W24 (item 2)** — decided and built; parked at `0e5fb94`, see §2.
- **#290 (item 3)** — closed by PR #472 (`e05950b`), four review rounds (the third escalated the board's stale W3 money block, rewritten at the owner's instruction; the fourth left only advisories, recorded in the PR). The prompt's "every claim refuted, close as
  stale" was HALF right: the mechanism was built, but the board said no
  peer-shaped run had happened, and the telemetry shows FOUR (2026-09-06,
  09-08, 09-10 ×2; three with both rounds to all four models, `fcca9510` round
  1 only). The board now says so.
- **#448, #458, #447 (piece 1 only), #467, #268, W23 → #464, #459** — NOT started. #458's doc half:
  `docs/10` FR-008 and `docs/faq` say peer critique is enabled in production
  and `/status` confirms `peer_critique_enabled: true` today, so those lines are
  not stale; the code-and-gate half (coupling to the window, the landing
  subhead gate that reds on the fix) is untouched.
- **`docs/65-open-work.md` W3 block (~221–274)** — REWRITTEN by PR #472
  (`e05950b`, review round 3 of the #290 close): it now quotes the ADR-0102
  ladder `SOFT_THRESHOLD_USD = 0.30`, `DAILY_CAP_USD = 0.40`,
  `HARD_LIMIT_USD = 0.50` (matches `costs.py`), records that the 0.15 ladder
  was stale from 2026-09-07 until that merge, re-measures the headroom, and
  names ADR-0094's two token constants as W3's remainder (W13/#268). Still
  open: the W3 row's needle (`PRESENT … DAILY_CAP_USD = Decimal("0.20")`)
  matches only a COMMENT at `costs.py:121`, so the row derives DONE for the
  wrong reason; replacing that needle is a follow-up. Also still stale, out
  of #472's scope: the W13 paragraph one hop away says the debate cap is 2000
  and quotes 495 mixes; `README.md` and `CONTINUE-OPEN-WORK-ULTRACODE-PROMPT.md`
  still call peer critique unbuilt and the ladder 0.15/0.25/0.20; the board's
  Order section still calls W3 "formally deferred (ADR-0081)".

## 3a. The root prompt file

`CONTINUE-105-BACKLOG-ULTRACODE-PROMPT.md` stays at root, untracked, as the
executable procedure for items 4–10 (#448, #458, #447 piece 1, #467, #268,
W23 → #464, #459). Its items 1–3 are done or parked as recorded above. One
correction was made to it in place on 2026-09-14, and nothing else: its
`grep -c "0.0014"` line (the bare pattern matches a token price
`0.00000014`). Its §7 claim
that the W3 block is stale is now discharged by `e05950b`; its §2 claim that
#105/W24 is "purely the human's" decision is discharged — the decision is
taken and recorded, and §2 above says what remains.

## 4. Traps measured this session (all reproduced)

- **Editing a PR body re-runs CI and blocks the merge.** `ci.yml` fires on
  `pull_request: [opened, synchronize, reopened, edited]`; after
  `gh pr edit --body-file` the merge was refused with "4 of 6 required status
  checks have not succeeded: 3 expected" until the re-run finished (~10 min).
  Finish the body before the last push.
- **`make type-check` after a `;` in a chain does not stop the commit.** One
  commit body on the 105a branch claims a green type-check it did not have
  (`0669e9e`); the next commit records the correction. Use `set -e` or `&&`.
- **A `git archive` copy has no `.git`.** A plain `pytest` there is INTERRUPTED
  at collection — `tests/repo_root.py` raises `RuntimeError: no .git ancestor`
  in the modules that import it — and zero tests run; with
  `--continue-on-collection-errors` the rest run and a further set fail on
  "not a git repository". Measured on an archive of `e05950b` on 2026-09-16:
  `pytest --collect-only -q tests` → `4296 tests collected, 12 errors`,
  `Interrupted: 12 errors during collection`. Every reviewer was told to ignore
  those; re-measure before quoting the counts.
- **`pytest.MonkeyPatch.setattr` on an inherited method leaves an INSTANCE
  attribute holding the bound method after undo.** Five files before
  `test_search_fee_band_sweep_refuses_an_unpriced_judge.py` in alphabetical
  order do that to the catalog singleton's `price_index`, so "is there an
  override?" is true in suite order and false alone. Restore VALUES, not
  presence; and run a new test after its alphabetical neighbours, not alone.
- **A proof script prices any model id missing from the price table at a
  silent fallback** (`costs.py` `_DEFAULT_PRICE_PER_1K_*`); a nonsense judge id
  reproduced a "production" table byte for byte. The sweep now refuses.
- **The `_FEE_STATEMENT` prose gate parses only "<amount> per <unit>"
  spellings**; the reversed order (pinned as `a "per-result rate" of $0.0014`),
  `$0.0014 per one result` and `$0.0014 per search` are pinned as known misses. A regex over prose can never be
  complete; the partner test makes the gap visible.
- **`$B:tests/...` in zsh applies the `:t` modifier** and mangles the path;
  write `"${B}:tests/..."`.

## 5. Sanity checks a reader can run

```bash
# the fee is flat per request (free, unauthenticated)
curl -s https://openrouter.ai/docs/llms-full.txt | grep -n "per request. This includes up to"
# the :online suffix is deprecated upstream
curl -s https://openrouter.ai/docs/llms-full.txt | grep -n -m2 ':online.*deprecated'
# four peer-shaped runs in the telemetry
python3 - <<'PY'
import json, collections
rows=[json.loads(l) for l in open("docs/analysis/2026-09-10-telemetry-tokens.jsonl") if l.strip()]
by=collections.defaultdict(list)
for r in rows:
    if r.get("query_run_id"): by[r["query_run_id"]].append(r)
for rid,rs in by.items():
    print(rid[:8], min(r["timestamp"] for r in rs)[:10],
          len({r["model_id"] for r in rs if r.get("stage")=="debate_round_1"}),
          len({r["model_id"] for r in rs if r.get("stage")=="debate_round_2"}))
PY
# the board is live
python3 scripts/check_open_work.py --check
```
