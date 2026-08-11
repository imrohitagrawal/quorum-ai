# WP-B — RESULT, and the fresh-session handoff for WP-C

> **Status:** WP-A + WP-B COMPLETE, green, and **COMMITTED as `b176d49`** on
> `feat/ui-pr1-quickfixes`. CI is still red on validate/lint/format-check/type-check — all
> four are green on `origin/main` and were broken by EARLIER commits on this branch, not by
> `b176d49`. Clearing them is Task 0 (§7).
> **Branch:** `feat/ui-pr1-quickfixes` (carries WP-A + WP-B, both uncommitted).
> **Written:** 2026-07-27. Companion to `UI-REMEDIATION-MASTER-PLAN-ULTRACODE-PROMPT.md`,
> which remains the plan of record for WP-C..WP-H.

---

## 1. What WP-B shipped

Every item below landed RED-first and, where the RED run did not already constitute
the proof, was mutation-proved by copying the file aside and restoring from the copy
(never `git checkout`).

| Finding | Fix | Evidence |
|---|---|---|
| **F-26 / F-25** branch CI-red on `openapi-check` | `make openapi-export` — added `synthesis_mode` + `context` | `openapi-check` passes |
| **F-04** coverage line + badge at **1.15:1** on the green band | `[data-consensus="true"]` overrides | RED measured 1.15:1 → **5.10:1** / **5.21:1** |
| **F-04 (second half — found by LIVE screenshot, not by a test)** the entire recommendation's Markdown painted dark ink on dark green | `[data-consensus="true"] .q-prose` palette re-map (h4–h6, strong, a, em, blockquote, code, li::marker) | RED measured STRONG **2.77:1**, CODE **2.59:1**, BLOCKQUOTE/EM **1.11:1** |
| **F-21** provenance badge rendered full-width | `.result-verdict-content > .badge { align-self: flex-start }` | RED **710px of 710px** → 150px |
| **F-22** agreement-led in DOM order only | serif display moved to `.result-verdict-agreement`; prose demoted to 1.05rem | RED **16.8px under 23.2px** → 23.2 / 16.8 |
| **F-18** fabricated `Only 0%` | `coverageRatioOrNull`; **same bug fixed in the trust triangle** | RED ×3 (`""`, `null`, `"   "`); over-rejection of a real `0.00` also proved |
| **F-27** silently deleted R1 digit assertion | restored alongside the element-count poll | poll-only passes **all 13** tampered shapes on a leak; restored line fails them |
| **F-23** vacuous assertions; untested views | existence guards before every ordering/absence assertion; live-run + cost-gate tests | deleting `#theme-toggle-live` left **all 8** original tests green; the 2 new ones catch it |
| **F-15** gates written but never registered | both specs added to the first BLOCKING step of `e2e.yml` | |

### Found during WP-B by adversarial review + live drive (all fixed, all RED-proved)

- **My own contrast gate was vacuous for pseudo-elements.** Deleting the
  `li::marker` override left all 27 tests green. The gate now measures
  `::marker` / `::before` / `::after`; machinery verified end-to-end by injecting
  a real `<ol><li>` (`getComputedStyle(el,"::marker").color` → `color(srgb 1 1 1 / 0.8)`).
- **First-visit double toggle.** `html[data-first-visit="true"] .theme-toggle-floating`
  was written on the false premise that the top bar is hidden pre-hydration. It is not
  (`data-active-view` is unset until `app.js` runs), so **two** toggles were visible.
  Rule deleted; RED-proved (`Expected 1, Received 2`).
- **Empty-recommendation placeholder at 1.11:1.** `setProse`'s placeholder branch swaps
  `q-prose` for `muted`, escaping every prose override. Fixed; RED-proved (1.11 light / 2.02 dark).

### Corrections made to my own claims

- `coverage_ratio` is a **required `Decimal` bounded `ge=0, le=1`** (`providers.py:97`), so
  F-18 is **defence in depth**, not an observed production bug. Comments corrected.
- `clamp01` **removed**. Clamping `16` would print `Only 100% …` — indistinguishable from a
  legitimate 100%. Out-of-range now returns `null` → the `—` no-data treatment.

---

## 2. Verification state

| Gate | Result |
|---|---|
| e2e blocking invariants lane (4 specs) | **88/88 pass** |
| e2e second CI step (axe/parity/docs/degraded/ops) | 91 pass / **3 fail — all pre-existing** `ui-parity` vendor-tint (→ WP-G1) |
| `theme-toggle` flake scan | **160/160** (10× then 5× after adding a test) |
| `make openapi-check` | **green** (was the F-26 blocker) |
| `tests/unit` | 806 pass / 10 fail — **all 10 are WP-D** items (caps 700→2000, `finish_reason`→`is_truncated`) |
| Visual baselines | 5 fail pre-existing at HEAD; WP-B adds 2 (trust-score @1440). **Not reseeded — that is WP-H, once.** |

Always run e2e as: `cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 npx playwright test <spec> --project=chromium --workers=1`

**Operational gotcha:** a stray Playwright `webServer` on port **18085** produces a mass
phantom failure (one run showed 31 failures; another showed 14 from a stale stylesheet).
If a run reds unexpectedly, `lsof -ti tcp:18085 | xargs -r kill -9` and re-run before
believing it.

---

## 3. Live UI acceptance walkthrough

`e2e/tests/review/wpb-acceptance.spec.ts` (throwaway) drives every view in both themes at
1440 and 375 and prints a PASS/FAIL line per claim. Screenshots in
`e2e/review-screenshots/acceptance/`.

**Result: 29/29 PASS** (was 27/29; the 2 failures were the mobile overflow, now fixed — §5, D-2).

---

## 4. ⚠️ WHY THE BRANCH CANNOT MERGE YET (corrected 2026-07-27)

**Correction to an earlier draft of this file.** Three claims were wrong and are fixed here:
the commit hook is NOT armed; the lint/format/type-check failures are NOT ambient debt; and
the 4 vendored doc skills must NOT be removed.

### 4.1 Committing is NOT blocked

`.claude/settings.json` has a `PreToolUse` hook that would deny `git commit` when
`make validate` + pytest are red — but it short-circuits on
`[ "$QUORUM_PRECOMMIT_HOOK" = "1" ] || exit 0`, and that variable is **not set** (no `env`
block in either settings file). `.git/hooks/` contains only `*.sample`, and
`.pre-commit-config.yaml` (ruff) is **not installed** into `.git/hooks`. So a local commit
works today. **The blocker is CI, not the commit.**

### 4.2 Every failing gate is a REGRESSION vs `main`, not pre-existing debt

Measured on an `origin/main` worktree versus this branch:

| Gate | `origin/main` | this branch | Blocking in `ci.yml` |
|---|---|---|---|
| `make validate` | **green** | RED | yes (`:36`) |
| `make lint` | **green** (0 errors) | RED (81) | yes (`:42`) |
| `make format-check` | **green** | RED (6 files) | yes (`:40`) |
| `make type-check` | **green** (178 files) | RED (36) | yes (`:44`) |
| `make openapi-check` | green | **green** (fixed in WP-B) | yes (`:38`) |

Commit **`f25696e`** introduced the `validate` failure *and* all 81 lint errors. The format
drift accumulated across `abc2429 → 774fda3`. So this is not "cleanup we might do" — the
branch cannot merge until each is green.

### 4.3 The 4 doc-suite skills STAY — they are intentional

`architecture-and-decisions`, `doc-critic`, `onboarding-companion`, `operations-runbook`
are **FIRST-PARTY**, not third-party. Evidence: `assets/project-profile.md` records
`owner_name: "Rohit Agrawal"` and `github: imrohitagrawal`; there is no upstream source URL,
no vendored/fetched marker and no third-party licence anywhere in the bundles. Each carries
its own CHANGELOG (v0.1.0 / 1.1.0 / 1.3.0). They were authored by the operator via Codex to
raise and hold documentation quality.

**They STAY, and they stay COMMITTED.** An earlier draft of this file recommended removing
them; that was wrong, and was made without asking why they were there. They are tracked in
git (added in `f25696e`, not gitignored) — which is exactly why CI sees them.

**Operating model (operator-confirmed):** they are maintained in a separate skills repo and
copied in; a new upstream version REPLACES the folder wholesale. Two consequences:
- Reformatting the bundles is wrong — every update would undo it. Exclude, don't conform.
- Their provenance is currently unrecorded. Add an entry per skill to
  `configs/external-skill-registry.json` (name, source, version from CHANGELOG) per
  AGENTS.md §V5.2, so a stale copy is detectable.

What they actually broke, and the honest fix for each:

**(a) `make validate` — 4 × `SKILL.md` lack the repo's 12 required `## ` contract sections.**
`scripts/validate_quality_contracts.py:35-53` requires them on every
`.agents/skills/*/SKILL.md`. These 4 carry their own 6–8 section structure instead.
Fix: **author the 12 sections for each**, grounded in what each skill actually does. Do
NOT use `scripts/fix_skill_contracts.py` — `configs/external-skill-registry.json` says its
injected sections prove "shape, NOT depth", and boilerplate in a doc-QUALITY skill is
self-defeating. Consider also registering them in the registry per AGENTS.md §V5.2, which
records provenance and review mode.

**(b) `make lint` — 72 of the 81 errors are in the 4 skills' own `scripts/verify.py`**
(18 each: `E501` line-too-long, `I001` unsorted imports). Ruff excludes only `mutants`, so
`.agents/skills/**` IS linted — and `webapp-testing`, the only other skill shipping Python,
passes clean. Two defensible options:
  - **Conform** (matches existing precedent): `ruff check --fix` + `ruff format` on those 4
    files. Mechanical, no behaviour change.
  - **Exclude** `.agents/skills/*/scripts/` in `pyproject.toml`, on the rationale that
    vendored skill bundles are regenerated from Codex and reformatting them creates drift
    against their source. **Operator decision** — it depends on whether these skills will be
    re-generated. If they will, exclude; if they are now repo-owned, conform.

**(c) The remaining 9 lint errors, all 6 format files, and all 36 type errors are in REAL
code** (`src/product_app/query_runs.py`, `costs.py`, `tests/unit/*`) — nothing to do with the
skills. `mypy` only scans `src tests`, so none of the 36 come from skill bundles. These need
a genuine fix, in their own PR, separate from both the UI work and the skill work.

### 4.4 The 10 failing unit tests are deliberate

`tests/unit/test_providers.py` is **new on this branch** and its 6 truncation/`shortened`
tests are RED-by-design, waiting on WP-D (caps 700→2000, `finish_reason` → `is_truncated`).
The other 4 are in files modified on this branch for the same work. Master plan: WP-D
"greens 6 of the 11". Do not treat them as breakage.

## 5. NEW findings for later work packages (verified, with root cause)

**D-1 — `formatAnswerText` can NEVER emit `<ul>`/`<ol>`. → WP-F (F-13/#5).**
`flushParagraph()` and `flushList()` share one `buffer`, and both the blank-line branch
(`app.js:4513`) and the tail (`app.js:4541`) call `flushParagraph()` **first** — so a
pending list is always emitted as `<p>`. Verified live: the golden recommendation's
`1./2./3.` lines render as three `<p>`. **This is the root cause of `MESSY_BULLET_LIST`
being dead**, which the master plan records as a symptom only. The
`[data-consensus="true"] .q-prose li::marker` override is deliberately kept and commented as
unexercised-until-WP-F; the contrast gate already measures `::marker`, so the moment lists
render it is gated automatically.

**D-2 — mobile horizontal overflow. → FIXED in WP-B (operator asked for it).**
Two independent defects, both RED-proved and mutation-proved:

1. **Result view, 77px at 375px.** `.result-synth-row` was
   `grid-template-columns: 132px 1fr` with no mobile breakpoint. `1fr` is
   `minmax(auto, 1fr)` and that `auto` minimum is the track's MIN-CONTENT, so a long
   unbreakable token in the synthesis body forced the row past the viewport.
   → `grid-template-columns: 132px minmax(0, 1fr)`.
2. **Transcript view, 43px at 375px** (masked until the first was fixed). Opening cards are
   grid items, so `min-width: auto` = min-content and they refused to shrink.
   → `.transcript-openings > * { min-width: 0 }`.

**Plus a third defect that no page-level gate could see:** with the cards able to shrink, a
long token still overflowed its own card — `clientWidth 271` vs `scrollWidth 624`, i.e.
**353px of provider text silently clipped** while `document.scrollWidth` stayed clean.
→ `.q-prose { overflow-wrap: break-word }`.

**Three gate gaps closed:**
- `pageScrollsHorizontally` never called `setViewportSize` — it had only ever asserted at
  Playwright's 1280px default. Now swept at **375 / 768 / 1440**.
- Nothing asserted element-level clipping. New invariant: *no element silently clips its own
  content* (375/768), exempting genuine `overflow-x: auto/scroll` containers.
- The golden fixture carried no token long enough to exercise wrapping. Added a realistic
  long identifier + URL to `LONG_MESSY_ANSWER`; without it the `overflow-wrap` rule would
  have shipped untested.

**Also fixed: my own F-21 assertion was threshold-based.** It compared the badge to
`column * 0.6`, which held at 1280px and broke at 375px when the column legitimately
narrowed to 209px — the badge was correctly shrink-to-fit at 150px throughout. Now compared
against the badge's own `max-content` width, and run at **1440 and 375**. Mutation-proved:
deleting `align-self: flex-start` fails at both widths.

**D-3 — mobile toasts cover the verdict headline.** Visible at 375px in
`result-light-375.png`. Already on the plan as F-20 → WP-H; now has visual evidence.

**D-4 — why slot 4 still shows DeepSeek. → WP-G1 (F-11). Answers an operator question.**
The swap is **half-done**: the model ID was changed, the vendor plumbing never was.

| Where | State |
|---|---|
| `model_slots.py:64` | ✅ `nvidia/nemotron-3-super-120b-a12b` — the ID **was** updated |
| `catalog_fetcher.py:51` | ❌ `DEFAULT_VENDORS` still ends `"deepseek"` |
| `catalog_fetcher.py:154` | ❌ `_FALLBACK_CATALOG` still ships `deepseek/deepseek-chat-v3.1`, `vendor="deepseek"` |
| `app.js:1176` | ❌ vendor-tint map returns `"deepseek"`; **no `nvidia` branch** |
| `tokens.css:48` | ❌ `--vendor-deepseek-*` tints exist; **no `--vendor-nvidia-*` pair** |
| `e2e/fixtures/golden-run.ts` `SLOTS[3]` | ❌ hardcodes `deepseek/deepseek-v3.1` |

**So there are two different reasons DeepSeek is still visible.** In the *real app* the
default ID is nvidia but it renders untinted/grey because no vendor mapping or token pair
exists — which is exactly why the **3 `ui-parity` vendor-tint tests fail**. In *screenshots
and e2e*, it literally says DeepSeek because the golden fixture hardcodes it.

Note also: master plan §10 locks slot 4 to **`nvidia/nemotron-3-nano-30b-a3b`** (nano), but
the code carries **`nemotron-3-super-120b-a12b`** (super). WP-G1 must do super→nano **and**
the vendor plumbing — 59 files still reference deepseek. Migrate `_FALLBACK_CATALOG` FIRST
or slot 4 prices at the 0.0008 default (16×).

---

## 6. Cleanup owed (adds to master plan §11)

`e2e/tests/review/` is throwaway: `layout-review.spec.ts`, `ring-probe.spec.ts`,
`wpb-band-review.spec.ts`, `wpb-acceptance.spec.ts`, plus `e2e/review-screenshots/`.
Delete or gitignore once the layout is signed off. None are registered in CI.

---

## 7. Fresh-session prompt for WP-C

Paste this verbatim into the new chat.

```text
Read AGENTS.md, then UI-REMEDIATION-MASTER-PLAN-ULTRACODE-PROMPT.md, then
WP-B-RESULT-AND-WP-C-HANDOFF.md in full before editing anything.

STATE: WP-A and WP-B are COMPLETE and green on the working tree, UNCOMMITTED, on
branch feat/ui-pr1-quickfixes. Do not redo them. Blocking e2e lane is 88/88; the
live acceptance walkthrough is 29/29. The only e2e reds are 3 pre-existing
ui-parity vendor-tint failures (they belong to WP-G1) and the visual baselines,
which are deliberately NOT reseeded until WP-H.

TASK 0 — get the branch CI-clean before any WP-C work. Three SEPARATE PRs; do
not bundle them, a reviewer cannot audit skill governance and a CSS rename in
one diff. Every gate below is GREEN on origin/main and RED here, so these are
branch regressions, not ambient debt. Committing locally is NOT blocked (the
PreToolUse commit hook short-circuits on QUORUM_PRECOMMIT_HOOK, which is unset,
and .git/hooks has no installed hooks) — CI is the blocker. See §4.

  0a. The 4 doc-suite skills in .agents/skills/ (architecture-and-decisions,
      doc-critic, onboarding-companion, operations-runbook) are INTENTIONAL —
      the operator authored them via Codex to hold documentation quality. DO NOT
      REMOVE THEM. They fail make validate only because each SKILL.md lacks the
      repo's 12 required "## " contract sections
      (scripts/validate_quality_contracts.py:35-53). Author those 12 sections
      genuinely per skill, grounded in what each one actually does. Do NOT run
      scripts/fix_skill_contracts.py — the registry itself says its injected
      sections prove "shape, NOT depth", and boilerplate inside a doc-QUALITY
      skill is self-defeating. Optionally also register them in
      configs/external-skill-registry.json per AGENTS.md §V5.2.

  0b. make lint: 72 of the 81 errors are E501/I001 inside those 4 skills' own
      scripts/verify.py. DECIDED BY THE OPERATOR — do NOT re-ask:
      add `.agents/skills/*/scripts/` to ruff's extend-exclude in pyproject.toml.
      Do NOT reformat the bundles: a new upstream version replaces the folder
      wholesale, so any reformatting would be undone on every update.
      Also add a registry entry per skill in configs/external-skill-registry.json
      (name, source, version from each CHANGELOG) per AGENTS.md §V5.2.

  0c. The remaining 9 lint errors, all 6 make format-check files, and all 36
      make type-check errors are in REAL code (src/product_app/query_runs.py,
      costs.py, tests/unit/*) and have nothing to do with the skills — mypy only
      scans src and tests. Fix them properly in their own PR.

NOTE: the 10 failing unit tests are DELIBERATE. tests/unit/test_providers.py is
new on this branch and its truncation/`shortened` tests are RED-by-design,
waiting on WP-D. Do not "fix" them here.

THEN WP-C = F-03, citation coverage math, the real root cause of #8/#15.
Numerator and denominator do not share units: cited_claim_count is a BOOLEAN per
answer (providers.py:471) while material_claim_count is ~1 per 200 chars
(providers.py:466), so a 4x1500-char run tops out at 12.5% against an 80%
target — which is why every run says "pause for human review".
The master plan recommends option (b): redefine coverage as the fraction of
answers carrying primary sources, and rename the field + UI copy to match.
OPTION (b) IS APPROVED BY THE OPERATOR — implement it, do not re-ask. Rename the
field and every piece of UI copy so the label says exactly what it measures.
Blast radius: target_met flips on many runs -> verdict band, trust triangle,
recommendation template, synthesis.py:701-737, evaluation signals, baselines.

RULES (from the plan, and they earned their place this session):
- RED test before each fix; mutation bite-proof by copying the file aside and
  restoring from the copy — never `git checkout <file>`, the tree has
  uncommitted work.
- ONE tree-writer for all edits. Fan out subagents only for read-only review.
- Run e2e as:
  cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 npx playwright test <spec> --project=chromium --workers=1
  Kill any stray server first: lsof -ti tcp:18085 | xargs -r kill -9
  A stray server or a cached stylesheet produces mass PHANTOM failures (one run
  showed 31, another 14). Re-run before believing a red.
- A green test is not proof. Look at a screenshot. This session, a contrast gate
  passed while every word of the recommendation was illegible, and a second gate
  passed while 353px of provider text was silently clipped.
- Adding a UI surface means adding its shape to e2e/fixtures/golden-run.ts in
  the SAME change, or the gate cannot see it.
- Do NOT reseed visual baselines. That is WP-H, once, at the very end.

Stop after WP-C is green and report before starting WP-D.

FYI, answered this session and recorded in §5 of the handoff:
- D-1: formatAnswerText can never emit <ul>/<ol> (flushParagraph runs before
  flushList on a shared buffer, app.js:4513 and :4541) — root cause of the dead
  MESSY_BULLET_LIST. Belongs to WP-F/F-13.
- D-4: slot 4 still shows DeepSeek because only the model ID was migrated; the
  vendor plumbing, tint tokens and the e2e fixture were not. Belongs to WP-G1,
  which must ALSO change super -> nano per master plan §10.
- Cleanup owed: e2e/tests/review/*.spec.ts and e2e/review-screenshots/ are
  throwaway; delete or gitignore once the layout is signed off.
```
