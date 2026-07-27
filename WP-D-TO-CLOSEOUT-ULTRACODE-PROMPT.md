# UI Remediation — WP-D to close-out, and Stream B

> **Written:** 2026-07-27, at the close of the WP-C session.
> **Branch:** `feat/ui-pr1-quickfixes` — pushed, **PR #96 open against `main`**.
> **Plan of record:** `UI-REMEDIATION-MASTER-PLAN-ULTRACODE-PROMPT.md` (§4 work
> packages, §9 execution order, §10 locked decisions). This file supersedes its
> §9 only for what is already done.
> **Previous handoff:** `WP-B-RESULT-AND-WP-C-HANDOFF.md` — still accurate for
> WP-A/WP-B detail and for the D-1..D-4 findings.

---

## 1. State — verified, not assumed

Everything below was measured at the end of the WP-C session. **Re-verify before
building on it** (`make validate lint format-check type-check openapi-check`,
then the two e2e lanes); a stale baseline is how a regression gets mistaken for
a known failure.

| Gate | Result |
|---|---|
| `make validate` / `lint` / `format-check` / `type-check` / `openapi-check` | **all green** |
| e2e blocking invariants lane (5 specs) | **96 passed / 0 failed** |
| e2e axe + parity + docs + smoke + degraded + ops lane | **94 passed / 0 failed** |
| `pytest tests` | **1462 passed / 13 failed / 10 skipped** (merged with `main` @ `025bd83`) |

Both e2e lanes are fully green for the first time on this branch.

### The 13 failing tests are WP-D's — and this is now VERIFIED, not assumed

```
tests/unit/test_providers.py                         6   is_truncated / shortened do not exist yet
tests/unit/test_debate_orchestration.py              2   DEBATE_ROUND_MAX_TOKENS, full answer excerpt
tests/unit/test_estimate_token_model.py              1   bound-cap assumptions vs enforced caps
tests/integration/test_query_run_cost_guardrails.py  3   cost bands moved; incl. the PINNED envelope
tests/unit/test_cost_breakdown.py                    1   same
```

**How this was verified** (an earlier draft of this file asserted it and was
wrong): with `costs.py`'s unit bug fixed AND `config.py`'s caps reverted to
main's 700/800, exactly **10** failures remain — the genuine WP-D truncation
set. Reverting the caps *alone* previously fixed **nothing**, because a separate
defect was masking them. Re-run that two-variable probe if you doubt the
attribution; do not take it on trust.

**The pinned envelope: the unit bug is FIXED, the re-measure is still owed.**
`test_daily_cap_admits_the_number_of_runs_its_dollar_value_pays_for` was
reporting *"7 runs completed, expected 8"*. Root cause found by review and fixed
in `6f5179e`: `costs.py` added the worst-case **bound** to a meter of **point**
spend, so the cap admitted `floor((CAP - bound)/unit) + 1` runs. It also meant an
account that had spent nothing could be refused outright.

What remains for WP-D is the honest part: the unit price itself still moves with
the caps, so `PINNED_DEFAULT_MIX_UNIT_USD` must be **re-measured and ratified**,
not edited to whatever the suite prints. Measured attribution:

```
pinned constant on main             0.0244
main caps (700/800)  + deepseek     0.0262
main caps (700/800)  + nvidia nano  0.0252   <- the slot swap alone LOWERS it
branch caps (2000/3000) + deepseek  0.0328
branch caps (2000/3000) + nano      0.0318
```

Note also `tests/integration/test_query_run_cost_guardrails.py:28-33` still
carries its own `DEFAULT_MODEL_IDS` ending in `deepseek/deepseek-chat-v3.1` — a
mix the product no longer ships. Re-measure against the real default mix.

`config.py` **already carries the raised cost caps** (`cost_debate_output_tokens_cap`
700→2000, `cost_synthesis_output_tokens` 800→3000) from an earlier commit on this
branch, while the *enforced* caps in `debate.py` / `synthesis.py` and the
`finish_reason` plumbing do not exist yet. That split is the whole story.

**Do not "fix" the cost-band fixtures by recalibrating them.** Master plan §4
WP-D requires an explicit BLOCK/keep decision on
`tests/unit/test_estimate_token_model.py`, and silently moving a guardrail
fixture into a passing band is exactly the flip it warns against. Decide, record
the decision, then change the test.

### Done this session (do not redo)

| Commit | What |
|---|---|
| `905090e` | Task 0b — ruff excludes `.agents/skills/*/scripts`; provenance registered for the 4 first-party doc-suite skills |
| `14d15db` | Task 0a — the 13 required contract sections authored per doc-suite skill, as an appended block that leaves the upstream body byte-identical |
| `8283a69` | Task 0c — real-code lint/format/type fixes (26 of 36 mypy errors were `context: dict` → `dict[str, Any]`) |
| `b2bf08d` | **WP-C / F-03** — coverage counts answers, not characters |
| `e6b489f` | WP-C adversarial-review fixes (six confirmed findings) |
| `f7e3ca3` | Gate integrity — `session-trail.spec.ts` registered in `e2e.yml`; skill-contract check anchored to `^##` |
| `3bf13a6` | **WP-G1 / F-11** — slot 4 → `nvidia/nemotron-3-nano-30b-a3b`, vendor plumbing, tints, fixture |
| `6f5179e` | Adversarial-review fixes — **the cost accumulation rails' unit bug**, a vacuous blocking gate removed, a weakened cross-check restored, wrong model labels, two doc contradictions |

**⚠️ The doc-suite skills' contract block is repo-added.** An upstream refresh
replaces those folders wholesale and `make validate` goes red again. Each block
says so in its own text.

---

## 2. Remaining work

### Stream A — this branch, in this order

**WP-D — data completeness (F-07 then F-08). Closes all 13 failing tests.**
- Enforced caps: debate 700→**2000**, synthesis 800→**3000** (`config.py` is
  already pricing them). `finish_reason` capture → `is_truncated` on
  `LiveProviderResult` → `shortened` on `InitialModelAnswer`.
- Excerpt slices `[:200]` / `[:600]` / `[:700]` → 8000 chars.
- **STRICT ORDER: #3 before #4.** `SYNTHESIS_DEBATE_EXCERPT_MAX_CHARS` derives
  from `DEBATE_ROUND_MAX_TOKENS`; #4 alone needs 2800, not 8000.
- Two open decisions the planner surfaced: (i) `test_estimate_token_model.py`
  needs an explicit BLOCK/keep decision — **do not silently flip**; (ii)
  `shortened` is inert until the UI renders it — WP-F must consume it.
- **Watch:** debate latency rises ~2.9× (check `DEBATE_HARD_TIMEOUT`), and
  removing the `[:200]` slice widens the prompt-injection surface. Adopt the
  untrusted-text fencing already used at `evaluation.py:1175`. Full multi-line
  provider answers are attacker-shaped input once they reach debate/synthesis.
- `tests/unit/test_providers.py` carries `# type: ignore` comments for the
  not-yet-existing fields. mypy runs with `warn_unused_ignores`, so **WP-D
  cannot land without deleting them** — the file header says so.

**WP-E — copy + readiness (F-09, F-14).** The only WP whose halves may run in
parallel worktrees (`providers.py` vs `readiness.py`). Change the producer **and
all 8 pinned assertions + 2 runbook quotes in one diff**. Readiness: add
`key_auth` + `offline_by_bad_key`, probing `GET /api/v1/key` (auth-required,
zero token cost) on a **background daemon thread** — `main.py:302` already blocks
on the catalog fetch at import time. `/status.live_execution` is a monitoring
contract consumed by `ops.js:308`.

**WP-F — frontend completeness (F-13, then F-12, F-19) + consume `shortened`.**
- **D-1 is the blocker and it is a root cause, not a symptom:**
  `formatAnswerText` can NEVER emit `<ul>`/`<ol>`. `flushParagraph()` and
  `flushList()` share one buffer and both the blank-line branch (`app.js:4513`)
  and the tail (`app.js:4541`) call `flushParagraph()` first, so a pending list
  always emits as `<p>`. This is why `MESSY_BULLET_LIST` is dead.
- Land fixture seeds + the new `RAW_MARKDOWN_PATTERNS` entry **alone first and
  record the RED run** — the bite proof cannot be reconstructed afterwards.
- The golden fixture dedupes to 2 sources, so F-19's "+N more" is invisible to
  every test. Extend to >3 unique sources in the same change.
- `[data-consensus="true"] .q-prose li::marker` is deliberately kept and
  commented as unexercised-until-WP-F; the contrast gate already measures
  `::marker`, so lists are gated automatically the moment they render.

**WP-G2 — context carry (F-10).**
- **Hard 402 trap:** shipping the client `context` on the create body without
  also adding it to the **estimate** body makes the two disagree → permanent
  `COST_CONFIRMATION_REQUIRED`. Both edits **must be in the same commit**.
- Decide where `prior_synthesis` actually goes in the prompt and make `costs.py`
  price *that* placement — today it is billed but never sent.

**WP-H — UX polish + gate repair (F-20, F-17, F-24, F-16).** The UX batch;
fix or delete the 6 stale a11y tests (4 are copy drift, 1 asserts an impossible
focus state, 1 targets `display:none` markup); **then seed linux visual
baselines once, at the very end.** They are deliberately unseeded right now and
WP-C changed rendered numbers, so expect a large, legitimate diff — review every
PNG before merge.

### Stream B — separate branch off `main`, more urgent than the remaining UI work

- **F-02 session fixation — DONE**, merged as PR #94.
- **F-01 double billing — DONE**, merged as PR #95 (`025bd83`) during this
  session. It is already in this branch via the `main` merge, and it is what
  added the pinned cost envelope described in §1.
- **F-05 — a cancel is silently reverted.** `query_runs.py:582`. A cancel landing
  mid-stage is overwritten; the pipeline keeps making billed calls and the run
  ends `completed` after the user was told `cancelled`. **Not started.**
- **F-06 — `measured` cost is a lie.** `query_runs.py:2077` labels a run
  `measured` while dropping billed calls whose usage was not captured; the
  capture gate is vacuously true. **Not started.**

### Operator-gated (needs a human, not an agent)

- A working **OpenRouter key** — the current one 401s on every model and on
  `GET /api/v1/key`. Needed to verify nvidia auth, whether `:online` works for
  nvidia, and one ~$0.02 full-pipeline run. Do this **after** WP-G.
- **One deliberate live run**, then deploy-verify. Confirm the deploy by
  `/status.build_sha == merged SHA` and by the deploy JOB actually running —
  never by an unchanged `/health` 200.
- **Visual baseline seeding** via `seed-visual-baselines.yml` (workflow_dispatch)
  — once, at WP-H, never per-WP.

### Cleanup owed

- `e2e/tests/review/` and `e2e/review-screenshots/` are throwaway and now
  gitignored. Delete them once the layout is signed off.
- `feat/ui-pr5b-cost-guard-diff` (`be0dbea`) is a stale parallel draft that would
  *remove* 1,059 lines. Delete the branch.

---

## 3. Rules that earned their place

1. **RED before GREEN, always**, and prove the bite by mutation — copy the file
   aside and restore from the copy. **Never `git checkout <file>`**; the tree
   carries uncommitted work.
2. **A green test is not proof. Look at a screenshot.** In these sessions a
   contrast gate passed while every word of the recommendation was illegible; a
   second gate passed while 353px of provider text was silently clipped; and a
   coverage fix passed while the UI showed `100%` above `3 of 4 models`.
3. **Measure before classifying a failure.** "Pre-existing" must mean *measured
   against a specific commit*, and say which. Six failures this session were
   pre-existing relative to the branch's parent and **regressions relative to
   `main`** — a distinction that changes what blocks a merge.
4. **A hardcoded expectation can invert underneath a test.** Three tests here
   failed on *correct* behaviour because ids they named as "legacy" had become
   the defaults. Assert the invariant, derive the literals.
5. Run e2e exactly as CI does:
   `cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 npx playwright test <spec> --project=chromium --workers=1`
   Kill a stray server first: `lsof -ti tcp:18085 | xargs -r kill -9`. Without
   both flags ~95 phantom failures appear.
6. **Adding a UI surface means adding its shape to `e2e/fixtures/golden-run.ts`
   in the SAME change**, or the gate cannot see it.
7. **Fan out review, never construction.** Subagents share one working tree.
   Read-only recon and adversarial review in parallel; one sole tree-writer.
   The WP-C review — five refuters plus an adjudicator told to reject its own
   reviewers — found a genuine blocker the author had missed.
8. **Don't counter-tune a safety weight** to hold a metric constant. Record the
   shift and leave the weight alone.

---

## 4. Fresh-session prompt

```text
Read AGENTS.md, then UI-REMEDIATION-MASTER-PLAN-ULTRACODE-PROMPT.md, then
WP-D-TO-CLOSEOUT-ULTRACODE-PROMPT.md in full before editing anything.

STATE: branch feat/ui-pr1-quickfixes, PR #96 open against main and merged up to
main @ 025bd83. WP-A, WP-B, Task 0, WP-C and WP-G1 are COMPLETE and committed.
All five gates are green and BOTH e2e lanes are fully green. pytest is 1458
passed / 13 failed, and all 13 are WP-D (config.py's cost caps were raised
ahead of the enforcement and the is_truncated/shortened
plumbing) — VERIFIED by a two-variable probe, not assumed. Visual-snapshot
baselines are a THIRD, separate blocking CI step inside the "e2e axe + parity"
job and are deliberately unseeded until WP-H — expect that step red until then.

FIRST: re-verify that state yourself before building on it — make validate lint
format-check type-check openapi-check, then both e2e lanes, then pytest. If the
numbers differ from §1, find out why before writing any code.

THEN WP-D (F-07 then F-08), which closes all 13. Strict order #3 before #4:
SYNTHESIS_DEBATE_EXCERPT_MAX_CHARS derives from DEBATE_ROUND_MAX_TOKENS, and #4
alone needs 2800 not 8000. Two decisions are yours to surface, not to make
silently: the BLOCK/keep call on tests/unit/test_estimate_token_model.py, and
the cost-band fixtures now sitting in BLOCK. Do NOT recalibrate a guardrail
fixture into a passing band without recording the decision.

Delete the `# type: ignore` comments in tests/unit/test_providers.py as part of
WP-D — mypy runs with warn_unused_ignores, so it cannot land with them.

Watch two things: debate latency rises ~2.9x (check DEBATE_HARD_TIMEOUT), and
removing the [:200] excerpt slice widens the prompt-injection surface — adopt
the untrusted-text fencing already used at evaluation.py:1175.

Then WP-E, WP-F, WP-G2, WP-H in that order. Do NOT reseed visual baselines
before WP-H.

RULES: RED test before each fix; bite-proof by mutation, copying the file aside
and restoring from the copy, never `git checkout`. ONE tree-writer; fan out
subagents only for read-only recon and adversarial review, and have the
adjudicator reject its own reviewers' unverified claims. A green test is not
proof — look at a screenshot. Run e2e as:
  cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 npx playwright test <spec> --project=chromium --workers=1
Stop after WP-D is green and report before starting WP-E.

SEPARATELY, and more urgent than the remaining UI work: Stream B's F-05 (a
cancel is silently reverted — the pipeline keeps making billed calls and the run
ends `completed` after the user was told `cancelled`, query_runs.py:582) and
F-06 (`measured` cost is a lie, query_runs.py:2077). Fresh branch off main, not
this one. F-01 is DONE (PR #95, merged as 025bd83).
```
