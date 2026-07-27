# UI Remediation — Master Plan & Fresh-Session ULTRACODE Prompt

> **Status:** PLANNING COMPLETE — no implementation started beyond WP-A (already on the tree).
> **Branch:** `feat/ui-pr1-quickfixes` (contains everything; a strict superset of the
> `feat/ui-pr5/5b/6/7/8-*` branches, which hold **0** commits not already here).
> **Written:** 2026-07-27. Supersedes the "PR2–PR4" split in
> `UI-BUG-TRIAGE-2026-07-23-ANALYSIS.md`, which remains the source of truth for the
> original 16 issues but **misdiagnoses #8/#15** (see F-03).
>
> **Fresh-session start-up (in this order):**
> 1. `AGENTS.md`, `docs/00-factory-console.md`, `docs/session-handoff.md` — the repo mandates
>    these before editing.
> 2. `UI-BUG-TRIAGE-2026-07-23-ANALYSIS.md` — the original 16 issues (note: it **misdiagnoses
>    #8/#15**; see F-03).
> 3. **This file** — it supersedes that doc's PR2–PR4 split.
> 4. `make next` and `make skill-route` — the repo's deterministic router. If it disagrees
>    with §9 here, follow AGENTS.md precedence (safety → human approval → source of truth →
>    local policy) and say so out loud rather than silently picking one.
> 5. Start at **WP-B**.
>
> **Do NOT** run `make validate`/`make quality` expecting green before WP-B: the branch is
> CI-red on `make openapi-check` today (F-26). That is a known starting condition.

---

## 0. How this plan was produced

- Direct verification of every claim against code (`file:line`), never from the triage doc's summary.
- A 10-agent read-only recon fan-out: 4 planners (exact edit sites), 3 bug hunters with
  independent lenses (backend correctness / security / product honesty), 2 adversarial
  reviewers of the uncommitted diff, 1 synthesizer.
- **Every P0 finding below was re-verified by hand after the agents reported it.** Two agent
  claims were downgraded on inspection; agent output is a lead, not a verdict.

---

## 1. Current state of the branch

### Already done (on the working tree, uncommitted)

| Item | Evidence |
|---|---|
| **#8/#15** verdict band restructured — agreement-led, separate coverage line, provenance badge | `app.js:2536-2650`, `app.css:2500-2560`; `e2e/tests/invariants/verdict-band.spec.ts` 8 tests, RED→GREEN proven |
| `TEMPLATED_FALLBACK_PREFIX` removed at the **producer** | `synthesis.py:80`; pinned by `tests/unit/test_synthesis.py::test_no_templating_prefix_leaks_into_sections`, **mutation-proved** |
| **#6** theme toggle reachable on every view + pre-paint script | `workspace.html:43-70,87,495,436,638`; `theme-toggle.spec.ts` 7 tests, RED→GREEN proven |

### ALREADY SHIPPED — do NOT redo *(deployed in PR #93, prod `build_sha 359ce5f`)*

These original triage issues are **closed and live**. A fresh session that "fixes" them is
wasting effort and will fight passing tests.

| # | Issue | Where |
|---|---|---|
| **#1** | Suggested-question chips skip the Run/Estimate hand-off | `app.js:6745-6777` |
| **#9** | Stacked "Failed to fetch" toasts | `app.js:758-770` + sticky indicator |
| **#10** | Old question lingers in the composer | `app.js:5887-5895` |
| **#13** | Run ID looks clickable, nothing happens | `app.js:4116-4151`, `app.css:2899-2903` |
| **#14** | "Please enter a question" fires on Start fresh | `app.js:5863`, `:6814` |
| **#12** | No conversation trail | `workspace.html:805-815`, `app.js:3775-3850,5931` |

### Full coverage matrix — all 16 triage issues

| # | Status | Carried by |
|---|---|---|
| 1, 9, 10, 13, 14 | ✅ shipped + deployed | PR #93 |
| 12 | ✅ shipped (unmerged) | on this branch |
| 6 | ✅ done this session | WP-A |
| 8 / 15 | ⚠️ presentation done (WP-A); **root cause open** | WP-A + **WP-C (F-03)** |
| 2 | ⛔ open | WP-E (F-09) |
| 3 | ⛔ open — server caps + UI expanders | WP-D (F-07) + WP-F (F-12) |
| 4 | ⛔ open | WP-D (F-07) |
| 5 | ⚠️ bullets done; stray `*` open | WP-F (F-13) |
| 7 | ⛔ open | WP-D (F-08) |
| 11 | ⛔ open (non-functional stub) | WP-G2 (F-10) |
| 16 | ⚠️ id set, plumbing open | WP-G1 (F-11) |
| — export | ⛔ open | WP-F (F-12) |

### WP-A — completed this session (context only, no action needed)

Verdict-band restructure + `TEMPLATED_FALLBACK_PREFIX` removal + theme toggle. Both RED→GREEN
proven; the prefix removal additionally mutation-proved. **WP-B repairs the regressions WP-A
introduced** (F-04, F-18, F-21, F-22, F-23) — that is not rework, it is the review catching up.

### Measured baseline (do not re-litigate)

- `tests/unit`: **805 passed, 11 failed** — all 11 pre-existing, none introduced.
- e2e structural blocking gates: **74/74 pass** (`--workers=1`).
- **Local e2e requires `SESSION_RATE_LIMIT_PER_MINUTE=600`** (CI sets it; without it 429s
  produce ~57 phantom failures) **and `--workers=1`** (CI uses 1 worker; local default is
  unbounded and produces ~38 more phantom failures). Always run:
  `cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 npx playwright test <spec> --project=chromium --workers=1`
- Pre-existing failures: 6 × `accessibility.spec.ts`, 3 × `ui-parity` vendor-tint (caused by
  the half-done #16 swap), 2 × stale visual baselines.

---

## 2. Verified findings ledger

Severity is **user impact**, not effort. `[V]` = personally re-verified beyond the agent report.

### P0 — must fix; actively wrong in production or blocks the branch

| ID | Finding | Evidence | Why P0 |
|---|---|---|---|
| **F-01** `[V]` | **Every run is billed twice against the daily cap.** `/estimate` records a `cost_guardrail_accepted` event (`query_runs.py:888`) and `create` records another (`:1018`); `_cumulative_spend_for` (`costs.py:823`) sums all events. | Both call sites confirmed; ALLOW+`confirmed=False` falls to the `else` branch → `cost_guardrail_accepted` (`costs.py:443`) | Two demo runs can lock an account out for 24h. Silent, user-facing, trivially reproducible. |
| **F-02** `[V]` | **Session fixation.** The unprefixed-cookie fallback nullifies the `__Host-` prefix, letting an attacker pin a victim to the attacker's session. | `auth.py:77` | Security-critical; `__Host-` exists precisely to prevent this. |
| **F-03** `[V]` | **Citation coverage is mathematically unreachable — and it is the ROOT CAUSE of #8/#15.** The ratio divides *answers-that-have-a-source* by *estimated material claims*. `cited_claim_count = 1 if primary_source_count > 0 else 0` (`providers.py:471`) is a **boolean**; `material_claim_count` is ~1 per 200 chars (`providers.py:466`). Measured: 4 answers × 1500 chars → **4/32 = 12.5% max** vs an 80% target. | Computed via `estimate_material_claim_count` | Every run is labelled provisional → the recommendation always says "pause for human review" → that is exactly the "do not act while 4 of 4 aligned" contradiction the user reported. **The triage doc blamed `:online` annotations; that diagnosis is wrong.** |
| **F-04** `[V]` | **My own regression:** the new `.result-verdict-coverage` (amber) and `.badge-summary` (blue) have **no `[data-consensus="true"]` override**, so on the dark-green consensus band they render at ~1.15:1 — invisible. Sibling elements (eyebrow/agreement/caveat/caption) all have overrides at `app.css:2507,2533,2559,2572`. | grep confirms the two are absent | I introduced it; found by two independent reviewers. Blocks the branch. **`synthesis_mode` defaults to `"simulated"` (`synthesis.py:162`), so the invisible chip is on nearly every prod run.** |
| **F-26** `[V]` | **The branch is CI-red right now.** `make openapi-check` is blocking (`ci.yml:38`) and `grep -c synthesis_mode openapi.yaml` → **0**, while `FinalSynthesis` already serves the field and the new badge consumes it. | verified both | Merge is impossible until `python scripts/export_openapi.py` is run. Was mis-ranked as low in the first draft. |
| **F-27** `[V]` | **A blocking trust gate was silently weakened — and it is NOT mine.** `trust-score-invariants.spec.ts:445` had `expect(text).not.toMatch(/\d/)` **deleted**, replaced by an element-count poll, while the test title still claims "zero digits". Present as an uncommitted `M` in `git status` **before this session began**. | `git diff` of that file | A regression emitting the score into `.result-trust-score-state` now passes all ten tampered-shape tests — precisely the FR-016 failure the gate exists to stop. Keep the poll, **restore the digit assertion**. |
| **F-05** | **Cancel is silently reverted.** A cancel landing mid-stage is overwritten; the pipeline keeps making billed calls and the run ends `completed` after the user was told `cancelled`. | `query_runs.py:582` | User is billed for work they cancelled and told the opposite. |
| **F-06** | **`measured` cost is a lie.** `_actual_cost` labels a run `measured` while dropping billed calls whose usage wasn't captured (empty-content / timed-out); the capture gate is vacuously true. | `query_runs.py:2077` | Directly contradicts the product's cost-honesty claim. |

### P1 — the original remediation (tasks #3–#10)

| ID | Item | Files |
|---|---|---|
| **F-07** | **#4** enforced caps 700→**2000**, 800→**3000**; `finish_reason` capture → `is_truncated`/`shortened` | `debate.py:52`, `synthesis.py:95`, `providers.py:989,145,429,805` |
| **F-08** | **#7** excerpt slices `[:200]`/`[:600]`/`[:700]` → 8000 chars | `debate.py:459`, `synthesis.py:508,526` |
| **F-09** | **#2** provider notice copy — 9 strings + 8 pinned assertions + 2 runbook quotes | `providers.py:328-420,529,573,609` |
| **F-10** | **#11** context wiring end-to-end (client body, synthesis call, initial answers, `prior_synthesis` placement) | `app.js:5392,5754`, `query_runs.py:1357,1525`, `providers.py`, `costs.py` |
| **F-11** | **#16** nvidia plumbing → **`nvidia/nemotron-3-nano-30b-a3b`** (paid, decided) | `model_slots.py:64,357`, `catalog_fetcher.py:51,153`, `app.js:1176,612,622,2210,3932` |
| **F-12** | **#3** full export + expanders (incl. **F-19** "+N more") | `app.js:2272-2289`, `app.css:2651,3308` |
| **F-13** | **#5** stray-asterisk render + widen `RAW_MARKDOWN_PATTERNS` | `app.js:4584-4621`, `golden-run.ts:63` |
| **F-14** | **#10** readiness honesty — real key-auth probe, `offline_by_bad_key` | `readiness.py:40,56,152`, `main.py:307,608` |

### P2 — quality/UX, found during review

| ID | Finding | Evidence |
|---|---|---|
| **F-15** | New e2e specs **not registered in the blocking CI lane** (but *are* swept by baseline seeding) | `.github/workflows/e2e.yml:177` |
| **F-16** | Only **darwin** baselines regenerated; **linux** baselines (what CI compares) untouched | `*-chromium-linux.png` |
| **F-17** | `trust-score-invariants.spec.ts:445` — R1 "zero digits" invariant **silently weakened** to an element-count check while the title still claims digit coverage | pre-existing gate erosion |
| **F-18** | Null/empty `coverage_ratio` renders a fabricated **"Only 0% …"** (`Number("")===0` is finite) | `app.js:2588` — mine |
| **F-19** | **"+N more" sources are unreachable** — dead `<span>`, `slice(0,3)`; and the golden fixture dedupes to 2 sources so **no test can ever exercise it** | `app.js:2397,2421`, `app.css:3357` |
| **F-20** | UX batch: singular/plural "the rest", orphaned landing toggle, invisible dark toggle, mobile toasts covering content, empty session panel on landing, duplicated "Recommendation" label | user review |
| **F-21** | Badge renders **full-width** (flex `align-items: stretch`) | `app.css:4128` |
| **F-22** | Band is agreement-led in **DOM order only** — prose is still 1.45rem serif vs 1.05rem agreement line | `app.css:2527` |
| **F-23** | Two verdict-band assertions **vacuous**; theme-toggle spec never exercises live-run/cost-gate | my specs |
| **F-24** | 4 of 6 a11y failures are **stale copy drift** (no `/estimate cost/i` button); 1 asserts an impossible focus state; 1 fails on `display:none` nav | `accessibility.spec.ts:41,52,70` |
| **F-25** | `openapi.yaml` lacks `synthesis_mode`; exact-bytes drift guard red → run `make openapi-export` | `openapi.yaml:566` |

### P3 — real, but explicitly deferred (file as issues)

- `main.py:731` GET `/ui` mints unlimited sessions, bypassing the per-IP limiter.
- `main.py:772` `/feedback/audit`'s session gate is not access control.
- `main.py:367` CSP keeps `script-src 'unsafe-inline'` on a justification that is factually wrong.
- `providers.py:889` simulated sources flagged `is_fallback=False` → inflate the trust surface.
- `app.js:2481,3185,3169` estimate shown as "actual"; fabricated est→actual reconciliation.
- `feedback_store.py:286` no retention; daily-cap check rescans all events.
- `auth.py:200` GC daemon purges without the lock.

---

## 3. Priority & sequencing rationale

**Two independent streams. Do not mix them in one PR — a reviewer cannot audit a billing
fix and a CSS rename in the same diff.**

- **Stream A — finish the UI remediation** (this branch). F-04, F-18, F-21, F-22, F-23 first
  (they are *my* regressions and block everything), then F-07→F-14, then P2 polish.
- **Stream B — newly discovered P0 defects** (fresh branch off `main`). F-01, F-02, F-05, F-06.
  These are unrelated to the UI triage, are independently shippable, and are **more urgent
  than any remaining UI work**.

**F-03 is the exception that must sit in Stream A**: it is the root cause of #8/#15, which is
squarely in scope. But it changes every trust number on screen, so it gets its **own PR**
immediately after the band work, with its own baseline reseed.

**Recommended order:** `WP-B → WP-C → (Stream B in parallel by a human/second session) →
WP-D → WP-E → WP-F → WP-G → WP-H`.

---

## 4. Work packages

Each WP = one PR. Each **must** land with a RED-proven test and a green
`make validate && make quality`.

### WP-B — Unblock the branch *(blocks everything; ~1 session)*
- **Scope:** F-26 (CI-red **first**), F-04, F-27, F-18, F-21, F-22, F-23, F-15, F-25.
- **Also:** the golden fixture carries no `synthesis_mode`, `target_met: true`, and 3/4
  aligned — so it **never renders the consensus band, the caution line, or the badge**.
  F-04 and F-21 shipped fully green because of this. Extending the fixture is part of the
  fix, not a nicety.
- **Also:** `theme-toggle.spec.ts` claims "every view" but never asserts
  `#theme-toggle-live`; live-run hides the topbar and no longer gets the float, so deleting
  that button reproduces #6 with a green gate. Add the assertion.
- **How:** add `[data-consensus="true"]` overrides for `.result-verdict-coverage` and
  `.badge-summary`; guard `coverage_ratio` against `""`/null (parse, then reject non-finite
  *and* empty-string input — not `Number.isFinite` alone); `align-self: flex-start` on the
  badge; make the agreement line visually dominant (raise it above the prose's 1.45rem or
  demote the prose); replace the two vacuous assertions; register both specs in
  `e2e.yml`; `make openapi-export`.
- **RED proof:** a contrast assertion on the consensus band (computed colour vs background
  ≥ 4.5:1) that fails today; a spec feeding `coverage_ratio: ""` that renders "Only 0%" today.
- **Exit:** contrast ≥ 4.5:1 both consensus states; no vacuous assertion; specs in the
  blocking lane.

### WP-C — Citation coverage math *(the real #8/#15 fix; own PR)*
- **Scope:** F-03.
- **How:** the numerator and denominator must share units. Either (a) count *cited claims*
  properly, or (b) redefine coverage as *fraction of answers carrying primary sources* and
  rename the field + UI copy to match. **(b) is far cheaper and honest**; (a) needs a real
  claim-extraction pass. **Recommend (b), and say so in the UI copy.**
- **Blast radius:** `target_met` flips on many runs → verdict band, trust triangle,
  recommendation template, `synthesis.py:701-737`, evaluation signals, **visual baselines**.
- **RED proof:** a test asserting an all-cited 4-answer run reaches `target_met = True`.
  It cannot pass today at any answer length > ~250 chars.
- **Exit:** a fully-cited run reports ≥80%; a zero-source run reports 0%; the recommendation
  stops unconditionally saying "pause".

### WP-D — Data completeness *(F-07, F-08)*
- Caps 700→2000, 800→3000; `finish_reason` → `is_truncated`/`shortened`; excerpts → 8000.
- Greens 6 of the 11 failing unit tests. **Note the two open decisions the planner surfaced:**
  (i) `test_estimate_token_model.py:149` needs an explicit BLOCK/keep decision — do not
  silently flip; (ii) `shortened` is **inert until the UI renders it** — WP-F must consume it.
- **Watch:** prompt-injection surface widens (the `[:200]` slice incidentally capped
  attacker-controlled text) and debate latency rises ~2.9×; check `DEBATE_HARD_TIMEOUT`.

### WP-E — Copy + readiness *(F-09, F-14)*
- Disjoint files (`providers.py` vs `readiness.py`) → the only two WPs that may run in
  parallel worktrees. Change producer **and all 8 pinned assertions + 2 runbook quotes** in
  one diff.
- Readiness: add `key_auth` + `offline_by_bad_key`; probe `GET /api/v1/key` (auth-required,
  **zero token cost**) on a background daemon thread — `main.py:302` already blocks on the
  catalog fetch at import time, so do **not** add another synchronous boot call.
- **Watch:** `/status.live_execution` is a **monitoring contract** consumed by `ops.js:308`.

### WP-F — Frontend completeness *(F-12, F-13, F-19, and consume `shortened`)*
- Full Markdown export; expanders for synthesis sections / transcript rounds / trust captions;
  make "+N more" an inline expander; stray-asterisk fix + a **greenable** new
  `RAW_MARKDOWN_PATTERNS` entry.
- **Fixture work is mandatory, not optional:** the golden fixture dedupes to 2 sources, so
  F-19 is invisible to every test. Extend to >3 unique sources. `MESSY_BULLET_LIST` is
  currently **dead** (one occurrence, never rendered) — wire it or delete it.
- **Order within the WP:** land fixture seeds + the new pattern **alone first** and record the
  RED run; the bite proof cannot be reconstructed afterwards.

### WP-G — Context carry + model swap *(F-10, F-11)*
- **Ordering trap (hard 402 loop):** shipping the client `context` on the create body without
  also adding it to the **estimate** body makes the estimate and the run disagree → permanent
  `COST_CONFIRMATION_REQUIRED`. Both edits **must be in the same commit**.
- Decide where `prior_synthesis` actually goes in the prompt and make `costs.py` price
  *that* placement — today it is billed but never sent.
- Slot 4 → `nvidia/nemotron-3-nano-30b-a3b`. **Do not delete the deepseek
  `_FALLBACK_CATALOG` entry** — it breaks ~40 test files at once; migrate references first.
- Synthesis model → `openai/gpt-5-mini` (measured: $0.055/$0.102, stays under the gate;
  `gpt-5` is **blocked** by the $0.25 cap at $0.195/$0.284). Debate stays `claude-haiku-4.5`.

### WP-H — UX polish + gate repair *(F-20, F-17, F-24, F-16)*
- The UX batch; restore the weakened R1 trust invariant (F-17); fix or delete the 6 stale a11y
  tests (4 are copy drift, 1 asserts an impossible state, 1 targets `display:none` markup);
  **then** seed linux baselines once, at the very end.

---

## 5. Skill mapping — which skill does what

| Phase | Skill | Used for |
|---|---|---|
| Before any fix | **systematic-debugging** | F-01/F-03/F-05/F-06 — reproduce before changing. F-03 already shows why: the triage doc's stated cause was wrong. |
| Locating edit sites | **codebase-intel** | Blast radius for F-03 (`target_met` consumers) and F-11 (~40 deepseek refs) before editing. |
| WP-B, WP-H | **ui-ux-pro-max** | Contrast tokens for the consensus band, visual hierarchy for F-22, mobile toast placement. |
| Every WP | **e2e-testing-patterns** | RED-then-GREEN, non-vacuous assertions (F-23 is exactly the failure this prevents), greenable gate patterns. |
| WP-B/F/H | **webapp-testing** | Drive the real UI; **the repo's own rule**: a green unit test on clean sim data has repeatedly hidden real-output bugs. |
| After each WP | **taste-check** | Keep the diff honest — no defensive special-casing to dodge a failing test. |
| WP-D..WP-G | **subagent-driven-development** | Only where files are genuinely disjoint (see §6). |
| Before merge | **security-review** | Mandatory for WP-E (copy touches notices) and all of Stream B (F-02). |
| Before deploy | **deploy-checklist** | Deploy verified by the **deploy JOB running** + `/status.build_sha == merged SHA`, never by a `/health` 200. |
| Docs at the end | **doc-critic** | The runbook quotes notice strings verbatim (F-09) and describes the removed prefix (`synthesis.py:935`). |

---

## 6. ULTRACODE / subagent strategy

**The single most important constraint: subagents share ONE working tree. Parallel writers
corrupt each other.**

- **Fan out WIDE (read-only, always safe):** recon, blast-radius mapping, adversarial review,
  bug hunting, verification. This is where the value was — the fan-out found F-01, F-02,
  F-03 and my own F-04, none of which I would have found alone.
- **Serialize ALL writes.** Tasks collide heavily: `providers.py` (WP-D, WP-E, WP-G),
  `synthesis.py` (WP-C, WP-D, WP-G), `app.js` (WP-B, WP-F, WP-G, WP-H).
- **The only safe parallel build:** WP-E's two halves (`providers.py` vs `readiness.py`) in
  **separate worktrees** (`isolation: "worktree"`), merged by one writer.
- **Per-WP shape:** `plan (1 agent) → build (1 sole writer) → verify (3-5 parallel adversarial
  reviewers, each told to REFUTE) → fix → re-verify`.
- **Keep a UI surface and the specs asserting its DOM in ONE builder.** Splitting them across
  agents is how F-23 (vacuous assertions) happens.
- **Never let an agent run `--update-snapshots`, `git checkout`, or `git stash`** — the tree
  carries uncommitted work.

---

## 7. Quality strategy

1. **RED before GREEN, always.** Every behavioural change ships with a test that fails without
   it. F-23 exists because two assertions were written that pass against the broken code.
2. **Prove the bite by mutation.** Re-introduce the defect and watch the test fail.
   **Copy the file aside and restore from the copy — never `git checkout <file>`**, which
   discards uncommitted work.
3. **Both directions when loosening a check.** The false positive is gone AND every genuine
   case is still caught.
4. **Fixtures gate coverage.** A gate only catches surfaces the golden fixture exercises.
   F-19 was invisible for months because the fixture dedupes to 2 sources; `MESSY_BULLET_LIST`
   is dead. **Adding a surface means adding its shape to the fixture — same PR.**
5. **Run e2e the way CI does:** `SESSION_RATE_LIMIT_PER_MINUTE=600` + `--workers=1`.
   Without both, ~95 phantom failures appear and will send you chasing ghosts.
6. **Screenshots for human review must settle first.** `page.screenshot()` does **not**
   disable animations (`toHaveScreenshot()` does). An unsettled capture showed a 75% ring as
   25% and cost a review cycle.
7. **Distrust agent findings until verified.** Two of ten claims did not survive inspection.

### Prevention playbook — retrofitting THIS repo

- **Unit-mismatch guard.** F-03 survived because nothing asserts numerator/denominator share
  units. Add a property test: an all-cited run reaches `target_met`, at every answer length.
  Any ratio in this codebase deserves the same "can it reach its target?" test.
- **Double-count guard.** F-01 survived because no test asserts *how many* cost events one
  run produces. Add: one run → exactly one accepted event.
- **Gate-erosion guard.** F-17 shows a test title outliving its assertion. Any invariant
  weakened must rename the test in the same diff; add a CI check that fails when a spec's
  title says "digits" and it asserts only counts.
- **Dead-fixture guard.** Fail CI on a `MESSY_*` constant with no reference in a spec.
- **Contract-drift guard.** `openapi.yaml` already has an exact-bytes guard — F-25 proves it
  works. Extend the same pattern to the `/status` monitoring contract consumed by `ops.js`.

### The rule that outranks the rest: fan out, or you are grading your own homework

**Measured on this work, twice.** Two adversarial fan-outs (4-6 read-only
refuters with distinct lenses + an adjudicator told to reject its own reviewers)
found **12 confirmed defects in code that had already been RED/GREEN-proved,
mutation-proved, and driven in a browser.** Six of them were introduced by the
very commit under review, including:

- a **money bug** — the cost accumulation rails added a worst-case *bound* to a
  meter of *point* spend, so an account that had spent nothing could be told it
  was out of budget, and the daily cap admitted one fewer run than it pays for;
- a UI surface rendering `Source support 100%` directly above `3 of 4 models`,
  under a tooltip *the same commit had just written* naming the wrong
  denominator;
- **three separate tests that could not fail**, each written by the author as
  proof of the fix it was covering.

It also **falsified a stated root cause**: "all 14 failures share one cause" was
wrong, and a two-variable probe run by a reviewer showed a second defect masking
them.

The lesson is not "review is good". It is that **an author cannot see these
classes of defect in their own work** — a vacuous test looks green, a wrong
denominator looks consistent with the number beside it, and a confident
attribution feels settled. Self-review, mutation proofs and a screenshot are all
necessary here and were all insufficient.

So: **no non-trivial change is done until an independent fan-out has tried to
break it — including the fixes from the previous fan-out.** The second review
existed only because the first review's fixes went unreviewed, and three of its
findings were in exactly that code.

Practical shape: distinct lenses beat headcount (money / "the author rewrote
failing tests" / the gates themselves / contracts and persistence / scope); every
finding must state inputs → wrong output; and any anomaly the author could not
explain goes in as an **explicit target** — both times a reviewer bisected it to
a single line.

### Prevention playbook — for a new project

- **Budget for the fan-out from day one** (see above). Treat "the author says it
  is done" as the *start* of verification, not the end. Encode it: a
  non-trivial PR is not reviewable until an independent adversarial pass has run
  over it, and over the fixes it produced.
- **Assume your own tests are vacuous until mutated.** Every test ships with the
  mutation that proves it fails without the change. Three tests in this project
  passed against the exact defect they existed to catch.
- **Never state a root cause without the probe that could falsify it.** If the
  claim is "these N failures share one cause", revert that one cause and count
  what remains. Twice here the answer was "nothing changed".
- Decide the **honesty invariants first** ("no number on screen the data cannot support"),
  encode them as blocking tests before the UI exists.
- Build the **messy golden fixture on day one** from real provider output — headings, bold,
  inline code, links, ordered lists, blockquotes, empty-citation slots, >3 sources, long
  multi-paragraph answers. Clean sim data hides the bugs that matter.
- Make every ratio/threshold ship with a reachability test.
- Put enforcement in **CI and hooks, never prose**. `AGENTS.md` is influence; CI is the gate.
- One writer per file per change; fan out review, never construction.

---

## 8. Operator-gated items (needs a human)

| Item | What is needed |
|---|---|
| **Working OpenRouter key** | Current key 401s on *every* model and on `GET /api/v1/key`. Needed to verify nvidia auth, whether `:online` works for nvidia, and one ~$0.02 full-pipeline run. Do this **after** WP-G. |
| **Visual baselines** | Run `seed-visual-baselines.yml` (workflow_dispatch, glob-driven) **once, at the very end** (WP-H). It commits `*-linux.png`. Review each PNG per §5.3 before merge. Do not reseed per-WP. |
| **F-03 decision** | Approve redefining coverage as *fraction of answers carrying primary sources* (recommended) vs. building real claim extraction. |
| **Stream B ownership** | F-01/F-02/F-05/F-06 are more urgent than the remaining UI work. Decide whether this session or another takes them. |
| **Cost acceptance** | Caps 700→2000 / 800→3000 mean real bills rise toward the estimate (up to ~3.75× on synthesis). Already accepted by the user; recorded here for the audit trail. |

---

## 9. Execution order (fresh session starts here)

```
WP-B  Unblock the branch      F-26 F-04 F-27 F-18 F-21 F-22 F-23 F-15   BLOCKS ALL
                              (openapi regen FIRST — CI is red today)
WP-C  Citation coverage math  F-03                        own PR + reseed
WP-D  Data completeness       F-07 then F-08              (STRICT: #3 before #4 —
                              SYNTHESIS_DEBATE_EXCERPT_MAX_CHARS derives from
                              DEBATE_ROUND_MAX_TOKENS; #4 alone needs 2800, not 8000)
WP-G1 Slot-4 nano migration   F-11    _FALLBACK_CATALOG entry FIRST, else slot 4
                              prices at the 0.0008 default (16x). BEFORE WP-G2 so
                              cost-test deltas have ONE cause. ~32 `nemotron-3-super`
                              literals + feedback_audit.py:436.
WP-E  Copy + readiness        F-09 F-14   (only safe parallel build; after WP-D so it
                              rebases onto the final providers.py shape)
WP-F  Frontend completeness   F-13 then F-12 F-19 + consume `shortened`
                              (asterisk BEFORE export, so the export carries fixed prose)
WP-G2 Context carry           F-10        (same-commit trap: estimate + create bodies
                              together, or a permanent 402 loop)
WP-H  UX polish + gate repair F-20 F-17 F-24 F-16 → seed baselines LAST
--- operator: key → one $0.02 live run → deploy-verify ---
Stream B (separate branch off main)    F-01 F-02 F-05 F-06
```

**Prompt-injection note:** WP-D removes the `[:200]` slice that *incidentally* capped
attacker-controlled provider text. While those builders are open, adopt the untrusted-text
fencing pattern already used at `evaluation.py:1175`. Full multi-line provider answers are
attacker-shaped input once they flow into debate/synthesis prompts.

**Per-WP loop:** systematic-debugging → RED test → single-writer build → `make validate &&
make quality` → parallel adversarial review (refute-by-default) → mutation bite-proof →
`git commit`.

**Do not** start WP-C..WP-H before WP-B is green: every later WP touches the same band/CSS
and would rebase onto a known-broken contrast state.

---

## 10. Decisions already locked (do not re-open)

| Decision | Value | Basis |
|---|---|---|
| Slot 4 model | **`nvidia/nemotron-3-nano-30b-a3b`** (paid, no `:free`) | User-approved. `:free` breaks `:online` (`providers.py:681` builds `id:free:online`, invalid) and the 401 risk is unmeasured. |
| Synthesis model | **`openai/gpt-5-mini`** | Measured $0.055 point / $0.102 bound → stays `allow`. `gpt-5` is **BLOCKED** by the $0.25 cap ($0.195/$0.284). |
| Debate model | **keep `anthropic/claude-haiku-4.5`** | Opus 4.8 forces `require_confirmation` on *every* run at 5× price. |
| Enforced caps | debate **2000**, synthesis **3000** | Matches `config.py:305,309`, which is already pricing them. |
| Cost consequence | **accepted** — real bills rise toward the estimate (up to ~3.75× on synthesis) | User: "showing half the information … is not a great product experience." |
| Coverage redefinition (F-03) | **pending operator approval** — recommend option (b) | See WP-C. |

## 11. Cleanup owed

- `e2e/tests/review/layout-review.spec.ts`, `e2e/tests/review/ring-probe.spec.ts` and
  `e2e/review-screenshots/*` are **throwaway** — delete once the layout is signed off, or
  gitignore them (F-23 flagged them as untracked).
- `feat/ui-pr5b-cost-guard-diff` (`be0dbea`) is a stale parallel draft that would *remove*
  1,059 lines. Delete the branch.
