# UI Remediation — WP-E to close-out

> **Written:** 2026-07-28, at the close of the WP-D session.
> **Branch:** `feat/ui-pr1-quickfixes` — **PR #96 open against `main`**.
> **Plan of record:** `UI-REMEDIATION-MASTER-PLAN-ULTRACODE-PROMPT.md` (§4 work
> packages, §9 execution order, §10 locked decisions).
> **Previous handoff:** `WP-D-TO-CLOSEOUT-ULTRACODE-PROMPT.md` — still accurate
> for WP-A/B/C detail. This file supersedes its §2 "Stream A" ordering.

---

## 1. State — measured at the close of the WP-D session

| Gate | Result |
|---|---|
| `make validate` / `lint` / `format-check` / `type-check` / `openapi-check` | **all green** |
| `pytest tests` | **1632 passed / 0 failed / 10 skipped** |
| e2e blocking invariants lane (5 specs) | **95 passed / 0 failed** |
| e2e axe + parity + docs + smoke + degraded + ops lane | **94 passed / 0 failed** |
| `make diff-cover DIFF_BASE=origin/main` | **96%** (blocking min 95) |

**Re-verify before building on this.** A stale baseline is how a regression gets
mistaken for a known failure. Note the e2e invariants lane contains exactly
**95** tests — an earlier handoff said 96, which was never achievable.

`WP-A`, `WP-B`, `Task 0`, `WP-C`, `WP-G1` and now `WP-D` are COMPLETE and
committed. WP-D is commit `70dd7d4`; read its message before touching
`costs.py`, `providers.py`, `synthesis.py` or `debate.py` — it records why each
money decision landed the way it did.

**`main` IS MERGED IN, as of `c8c41ee`** (main `1792655`), so Stream B's F-05
(#98) and F-06 (#99) are already here. Read that merge commit too: it was not
clean, and it records a product-honesty defect the merge CREATED which existed
in neither branch alone — `synthesis_mode` labelled a fully-templated run as
`"live"` because F-06 returns a billed-but-blank live result while WP-A had
made that field the provenance channel. Provenance now counts sections with
USABLE TEXT; `live_call_usages` is untouched so F-06's cost contract stands.

### The visual-snapshot step is expected RED

`visual-snapshots.spec.ts` + `trust-score-visual.spec.ts` are a THIRD blocking
CI step inside the "e2e axe + parity" job. Linux baselines are deliberately
unseeded until WP-H. Expect that step red until then; it is not your bug.

---

## 2. What WP-D changed that you will trip over

- **Enforced caps** are now debate **2000** / synthesis **3000**. Excerpt sizes
  are DERIVED constants (`DEBATE_ANSWER_EXCERPT_MAX_CHARS`,
  `SYNTHESIS_ANSWER_EXCERPT_MAX_CHARS`, `SYNTHESIS_DEBATE_EXCERPT_MAX_CHARS`),
  not literals. Do not hardcode 8000 anywhere.
- **`InitialModelAnswer.shortened`** exists and crosses the API boundary, but
  **nothing renders it**. WP-F owes that.
- **`src/product_app/untrusted_text.py`** is the single fencing primitive.
  Provider/user text reaching ANY prompt must go through `fence()`, and the
  stage's system prompt must carry `UNTRUSTED_DATA_SYSTEM_RULE`. Both halves or
  neither — delimiters without the rule protect nothing.
- **`max_cost_usd` is priced on the bound path only** via
  `_cost_components(price_round_two_prior_critique=True)`. Do not move that term
  to the point path: it either hard-refuses affordable runs or breaks the
  breakdown's reconciliation invariant. Both were measured.
- **Cost-band fixtures may only use price-exact models.**
  `test_cost_band_fixtures_are_built_from_price_exact_models` enforces it, and
  its two classification sets must together cover the whole catalog — so adding
  a catalog model forces someone to classify its price.

---

## 3. Remaining work, in order

### WP-E — copy + readiness (F-09, F-14)
The only WP whose halves may run in parallel worktrees (`providers.py` vs
`readiness.py`). Change the producer **and all 8 pinned assertions + 2 runbook
quotes in one diff**. Readiness: add `key_auth` + `offline_by_bad_key`, probing
`GET /api/v1/key` (auth-required, **zero token cost**) on a **background daemon
thread** — `main.py:302` already blocks on the catalog fetch at import time, so
do not add another synchronous boot call. `/status.live_execution` is a
monitoring contract consumed by `ops.js:308`.

### WP-F — frontend completeness (F-13, then F-12, F-19) + consume `shortened`
- **D-1 is the blocker and it is a root cause:** `formatAnswerText` can NEVER
  emit `<ul>`/`<ol>`. `flushParagraph()` and `flushList()` share one buffer and
  both the blank-line branch (`app.js:4513`) and the tail (`app.js:4541`) call
  `flushParagraph()` first, so a pending list always emits as `<p>`. This is why
  `MESSY_BULLET_LIST` is dead.
- Land fixture seeds + the new `RAW_MARKDOWN_PATTERNS` entry **alone first and
  record the RED run** — the bite proof cannot be reconstructed afterwards.
- The golden fixture dedupes to 2 sources, so F-19's "+N more" is invisible to
  every test. Extend to >3 unique sources in the same change.
- **Also raise `synthesis_length.DEFAULT_SECTION_MAX_CHARS` here.** A
  3000-token section is ~12 000 chars but storage still hard-cuts at 4000, so
  ~67% of the newly-budgeted (and billed) output is discarded. WP-F is where the
  expanders that make long sections readable land, so raise it with them.
- Render `shortened` — it has been inert since WP-D.

### WP-G2 — context carry (F-10)
**Hard 402 trap:** shipping the client `context` on the create body without also
adding it to the **estimate** body makes the two disagree → permanent
`COST_CONFIRMATION_REQUIRED`. Both edits **must be in the same commit**.
Also owed here:
- `QueryRunEstimateRequest` has no `context` field, so `query_runs.py:894`
  always reads `None`. Reproduced: preview `200 allow est=0.0316`, create
  `402 COST_LIMIT_EXCEEDED est=0.2066`, same account and query.
- Non-string `context` values 500 the create endpoint (`{'prior_question': 5}`,
  `['a']`, `{'a': 1}`); should be 422. `query_runs.py:276-285` validates keys
  only, then `costs.py` calls `.strip()`. **No length bound either** — unlike
  `query_text`'s `_QUERY_TEXT_MAX_LENGTH`.
- `prior_synthesis` is **billed but never sent** (`providers.py:766-769` injects
  only `prior_question` while `costs.py:779-780` prices the full context).
  Decide where it goes in the prompt and price *that* placement.

### WP-H — UX polish + gate repair (F-20, F-17, F-24, F-16)
The UX batch; fix or delete the 6 stale a11y tests (4 are copy drift, 1 asserts
an impossible focus state, 1 targets `display:none` markup); **then seed linux
visual baselines once, at the very end.** WP-C and WP-D changed rendered
numbers, so expect a large, legitimate diff — review every PNG before merge.

Add here (from WP-D's review): when a run is BLOCKed, the UI should say **which
slot is expensive and that swapping it will let the run proceed**. BLOCK is a
hard refusal with no confirmation token — that is deliberate and the rail stays,
but a dead end with no explanation is a poor product surface.

---

## 4. Open items WP-D did not close (deliberately)

1. **`max_cost_usd` still omits source-line tokens.** Worst case ~2 400
   unpriced tokens per synthesis section, ≈ **2.4%** overshoot. Now *bounded*
   by the title (300) and URL (500) caps; it was unbounded. Fixing it means
   another cost-model change — group it with the cost work, not with UI.
2. **`evaluation.py:1229`** builds `f"[{index}] {source.title} :: {source.url}"`
   with no flatten and no cap. It is the one consumer the shared primitive has
   not reached. Small, and it belongs with a security pass.
3. **The daily meter accumulates the point estimate**, which under-models worst
   case (measured +62% before F-08, +137% after). F-06 (now merged) fixed how a
   failed call is CLASSIFIED, but the meter still sums the estimate. Do not
   "fix" it by accumulating the bound: that is precisely the money bug commit
   `6f5179e` removed. Belongs with the Stream B chat's E2.
4. **No deployment-wide spend ceiling — [issue #100](https://github.com/imrohitagrawal/quorum-ai/issues/100).**
   `DAILY_CAP_USD` is per-account and accounts are free to self-issue, so
   exposure is (accounts mintable × $0.20). Harmless today because the key is
   unfunded and every run simulates. **Wanted BEFORE the key is funded.**
5. **UNPROVEN: the 180s run deadline at the new caps.** Worst case ~156s
   (debate serial +63s, synthesis concurrent across a 20-worker pool +49s), but
   extrapolated from a run at the OLD caps. Only a live run settles it.
   Note `openrouter_timeout_seconds = 8.0` is a per-socket-read timeout, NOT a
   total-call deadline — measured: four live calls at 4.1–21.3s all succeeded
   under it. Do not "fix" that value on the assumption that it caps generation.

---

## 5. Stream B — separate branch off `main`, more urgent than remaining UI work

- **F-02** session fixation — DONE (PR #94).
- **F-01** double billing — DONE (PR #95, `025bd83`).
- **F-05 — DONE** (PR #98, `651cbb9`). A terminal run is now final in every
  field, not just its label.
- **F-06 — DONE** (PR #99, `1792655`). A provider failure is classified by
  whether it could have BILLED: `_DispatchedUnmeasured` means "dispatched, so
  possibly charged, but unmeasurable", distinct from `None` = "refused before
  inference, nothing billed".

**Both are merged into this branch** (`c8c41ee`). Open item 3 below is
therefore PARTLY addressed — F-06 fixed the classification, but the daily
meter still accumulates the point estimate.

Still open on the cost layer, being carried by the Stream B chat (do NOT start
these here; that chat holds the design context):
- **P1 — the spend cap fails OPEN.** A locked feedback DB makes `get_store()`
  return `None` and `costs.py` guards on `if store is not None:`, so the 24h
  cap silently vanishes. Related to issue #100 below — same rail, different
  failure mode. Recommend failing CLOSED: a guardrail that disappears when
  storage is unavailable is worse than a refused run.
- **E2 — positive evidence in `_actual_cost`**, retiring the "some path forgot
  to record" class rather than playing whack-a-mole.

Also off `main`, its own small PR: the **five remaining stale
`_FALLBACK_CATALOG` prices + drift detection**. Measured 2026-07-27 against the
live public catalog:

| model | fallback in/out | live in/out |
|---|---|---|
| `openai/o3` | 0.015 / 0.06 | 0.002 / 0.008 (**650% OVER**) |
| `google/gemini-2.5-pro` | 0.00125 / 0.005 | 0.00125 / 0.01 |
| `google/gemini-2.5-flash-lite` | 0.000075 / 0.0003 | 0.0001 / 0.0004 |
| `deepseek/deepseek-chat-v3.1` | 0.00014 / 0.00028 | 0.00025 / 0.00095 |
| `meta-llama/llama-3.1-8b-instruct` | 0.00005 / 0.00005 | 0.00005 / 0.00008 |

Price-exact and safe for band fixtures: `openai/gpt-4o-mini`, `openai/gpt-4.1`,
`anthropic/claude-haiku-4.5`, `anthropic/claude-3-haiku`,
`anthropic/claude-opus-4`, `google/gemini-2.5-flash`,
`nvidia/nemotron-3-nano-30b-a3b`. **Correcting any drifting row requires
updating `test_cost_band_fixtures_are_built_from_price_exact_models` and
re-measuring `PINNED_DEFAULT_MIX_UNIT_USD`.**

---

## 6. Operator-gated (needs a human, not an agent)

- **A working OpenRouter key.** The current one 401s on every model and on
  `GET /api/v1/key`. Do this **after** WP-G. Batch all three things that need
  it into ONE deliberate ~$0.02 run: verify nvidia auth, whether `:online` works
  for nvidia, and **measure real latency at the new caps** (open item 5).
- **Before funding that key: issue #100.**
- **Visual baseline seeding** via `seed-visual-baselines.yml`
  (workflow_dispatch) — once, at WP-H, never per-WP.
- Confirm any deploy by `/status.build_sha == merged SHA` **and** the deploy JOB
  actually running — never by an unchanged `/health` 200.

---

## 7. Rules that earned their place

1. **RED before GREEN, always**, and prove the bite by mutation — copy the file
   aside and restore from the copy. **Never `git checkout <file>`**; the tree
   carries uncommitted work.
2. **A green test is not proof. Look at a screenshot.**
3. **Measure before classifying a failure.** "Pre-existing" must mean *measured
   against a specific commit*, and say which. WP-D asserted an 8→6 envelope drop
   was its own; measurement showed it predated the session.
4. **A hardcoded expectation can invert underneath a test.** Assert the
   invariant, derive the literals. WP-D rewrote a band test that pinned
   `REQUIRE_CONFIRMATION` when its actual subject was *which figure the rail
   reads* — a correct fix had reddened it.
5. Run e2e exactly as CI does:
   `cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 npx playwright test <spec> --project=chromium --workers=1`
   Kill a stray server first: `lsof -ti tcp:18085 | xargs -r kill -9`. Without
   both flags ~95 phantom failures appear.
6. **`make quality` / `make validate` do NOT include the blocking changed-lines
   coverage gate.** Run `make diff-cover DIFF_BASE=origin/main` before pushing.
   WP-D found it CI-red at 94% while every local gate was green.
7. **Adding a UI surface means adding its shape to `e2e/fixtures/golden-run.ts`
   in the SAME change**, or the gate cannot see it.
8. **Fan out review, never construction — and treat it as MANDATORY.** Three
   fan-outs over WP-A..WP-D found defects in code that was already RED/GREEN-
   proved, mutation-proved and browser-checked: a money bug, a UI surface
   contradicting itself on screen, an order-dependent test, and **five separate
   tests that could not fail**. Distinct lenses beat headcount; the adjudicator
   must be told to reject its own reviewers. **Review the FIXES too** — WP-D's
   second pass found a regression introduced by its own first pass.
9. **Verify a reviewer before acting on it.** Roughly a fifth of agent findings
   here did not survive inspection, and several were measured under conditions
   the real test never runs in (a different catalog cache state). Reproduce the
   way the REAL TEST runs it.
10. **Don't counter-tune a safety weight** to hold a metric constant.

---

## 8. Fresh-session prompt

> The leading `ultracode` is deliberate and should not be stripped. It turns the
> multi-agent opt-in on for the WHOLE session, which is what §7 rule 8 requires:
> fan out for read-only recon, again over the build, and again over the fixes
> that review produces.

```text
ultracode

Read AGENTS.md, then UI-REMEDIATION-MASTER-PLAN-ULTRACODE-PROMPT.md, then
WP-E-TO-CLOSEOUT-ULTRACODE-PROMPT.md in full before editing anything.

STATE: branch feat/ui-pr1-quickfixes, PR #96 open against main. WP-A, WP-B,
Task 0, WP-C, WP-G1 and WP-D are COMPLETE and committed (WP-D is 70dd7d4).
main is MERGED IN at c8c41ee, so Stream B's F-05 (#98) and F-06 (#99) are
already here — read BOTH those commit messages before touching costs.py,
providers.py, synthesis.py or debate.py. All five gates are green, BOTH e2e
lanes are green (95/0 and 94/0), pytest is 1632 passed / 0 failed, diff-cover
is 96%.

FIRST: re-verify that state yourself — make validate lint format-check
type-check openapi-check, then both e2e lanes, then pytest, then
make diff-cover DIFF_BASE=origin/main. If the numbers differ from §1, find out
why before writing any code. Do not take the previous session's numbers on
trust; several were proved wrong by review.

THEN WP-E (F-09 copy + F-14 readiness). It is the only WP whose halves may run
in parallel worktrees (providers.py vs readiness.py). Change the producer AND
all 8 pinned assertions + 2 runbook quotes in ONE diff. Readiness probes
GET /api/v1/key (auth-required, zero token cost) on a BACKGROUND DAEMON
THREAD — main.py:302 already blocks on the catalog fetch at import time.
/status.live_execution is a monitoring contract consumed by ops.js:308.

Then WP-F, WP-G2, WP-H in that order. Do NOT reseed visual baselines before
WP-H; that CI step is expected red until then.

WATCH (all measured, all in §2/§4):
  - untrusted_text.fence() + UNTRUSTED_DATA_SYSTEM_RULE are inseparable; any
    new provider text reaching any prompt needs both halves.
  - excerpt sizes are DERIVED constants — never hardcode 8000.
  - max_cost_usd is priced on the BOUND path only; moving that term to the
    point path either hard-refuses affordable runs or breaks the breakdown's
    reconciliation invariant. Both were measured.
  - cost-band fixtures may only use price-exact models; a test enforces it.
  - `shortened` is inert until WP-F renders it.

RULES: RED test before each fix; bite-proof by mutation, copying the file aside
and restoring from the copy, never `git checkout`. ONE tree-writer; fan out
subagents only for read-only recon and adversarial review, with the adjudicator
told to reject its own reviewers. A green test is not proof — look at a
screenshot. make quality/validate do NOT include the blocking changed-lines
coverage gate: run make diff-cover DIFF_BASE=origin/main before pushing.
Run e2e as:
  cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 npx playwright test <spec> --project=chromium --workers=1

MANDATORY before calling WP-E done: run an adversarial fan-out over it (4-6
read-only refuters with distinct lenses + an adjudicator told to reject its own
reviewers), and review the FIXES it produces too. Three such reviews on the
preceding work found defects that RED/GREEN proofs, mutation proofs and a
browser check had all missed — including a money bug and five tests that could
not fail. WP-D's second pass found a regression introduced by its own first
pass. Verify every reviewer claim before acting on it: about a fifth do not
survive inspection.

Stop after WP-E is green AND reviewed, then report before starting WP-F.

DO NOT start the remaining cost-layer work (the fail-open spend cap, positive
evidence in _actual_cost, the five stale catalog prices). A separate chat owns
Stream B and holds the design context; F-05 and F-06 are already done and
merged here. If you find something in that area, file it rather than fixing
it.
```
