# Quorum R1 UI — Slice State & Integrity Anchor

> **Every fresh context (chat or subagent) reads this FIRST**, before touching code.
> It is the single source of truth for what's done, what's next, and the
> invariants no slice may violate. Update it at every slice boundary.

## ▶ FRESH-CHAT HANDOFF (read this, then the rest of the file)
- **Branch:** `feat/quorum-r1-ui`. **Committed & reviewed:** Slice 0 (`3132548`) · B1 (`d46cb42`) · B2 (`5a5b9e8`) · Slice 1 (`15d4636`) · **Slice 2 (03 Cost gate) — `054669a`** · **Slice 3 (04 Live run) — `2aa50b5`** · **Slice 4a (05 verdict band) — `afbe0ea`** · **Slice 4b (05 receipt+positions) — `e520824`** · **Slice 5 (06 Transcript) — REVIEWED & COMMITTED** (this commit; SHA backfilled at Slice 6). Screens 03·04·05·06 COMPLETE. Backend extension COMPLETE.
- **NEXT ACTION: build Slice 6 (07 Edge states — seven).** Read the `.dc.html` `#07` section (lines 672+). It shows SEVEN edge states (e.g. cost-blocked/COPY-004, provider failure/AC-015, partial result/AC-022, active-query-exists/AC-003, wrong-session/AC-032, empty/anonymous, timeout/AC-021 — confirm the exact seven from the mock). Many already have partial handling (block band stub in 03 w/ `TODO(Slice 6 / COPY-004)`; live-run `#live-notices` for partial/failed; error banner). This slice makes each a first-class, honest, on-brand state. COPY-004 verbatim for cost-blocked (docs/33-content-design.md). No secrets in any error; correlation_id + query_run_id on every error state. Implement, self-verify, adversarial panel, re-review until clean, commit + ledger (backfill Slice 5's SHA).
  - **Slice 3 review outcome (for context):** implemented as a full-width honest live-run hero (5-reviewer panel + 2-reviewer re-review + a 2-item tightening pass). HONESTY: renders ONLY server-backed data — status/elapsed (`elapsed_time_ms`, live-ticking + frozen at terminal), 5-stage strip (keys match backend), per-model status (pending→done/failed +latency +search-fallback), debate at ROUND granularity (`debate_outputs`, honest "per-model debate detail not captured" caption), approved CAP (`estimated_cost_usd`, no fabricated accrual/spend-bar). DROPPED as mock-only: per-model debate stances, streaming/typing, "spend so far", per-stage timing/cost, queued/responding statuses. Running=BLUE (`--info`), NO green (added `--info-glow` both themes). Key fixes: `#live-notices` surfaces partial/failed disclosure IN the live card (aside is `display:none` while active — CSS `[data-active-view]`); focus→live `h1` + scrollIntoView on entry; per-region change-detection signatures (`state.liveSig`) kill 750ms churn; copyable `#live-corr` run-id; `.live-*.mono` compound selectors beat the shared `.mono`; `liveNoticesHaveContent()` keeps toast copy honest. **Full suite 68 failed = clean baseline; 0 new failures.** CARRY-FWD: debate double-renders on terminal (live card + persistent `#debate-output`) — Slice 4a consolidates into the result view; cost-estimate notices still only in the hidden aside during a run (planning info, not failure disclosure).
- **Then remaining, in order:** Slice 3 (04 Live run) → 4a (05 verdict+trust) → 4b (05 receipt+positions+reconciliation — see its HONESTY carry-forwards below) → 5 (06 Transcript) → 6 (07 Edge states ×7) → 7 (08 Dark + 01 Landing) → **industrial PR gate** → open PR.
- **Workflow (user-confirmed):** orchestrate each slice + its adversarial review panel in isolated subagents; **do NOT pause between slices**; commit each slice after fixes. Prioritize the PRE-INSTALLED specialized skills (Read their SKILL.md).
- **Fresh-container skill re-install:** `uiux-*` + `taste-check` were installed to `~/.claude/skills` (container-local — NOT in the repo, so a fresh session lacks them). Re-install once at session start: `git clone --depth 1 https://github.com/nextlevelbuilder/ui-ux-pro-max-skill /tmp/uiux && cp -r /tmp/uiux/.claude/skills/* ~/.claude/skills/` (prefix names `uiux-`), and `git clone --depth 1 https://github.com/kingkongshot/prompts /tmp/pv && cp /tmp/pv/.src/templates/knowledge/taste-review/content.md ~/.claude/skills/taste-check/SKILL.md` (add `name:`/`description:` frontmatter). If that's blocked, reviewers just `Read` the in-repo `.agents/skills/*/SKILL.md` instead.
- **Continuity is via THIS file + committed branch only** — the plan file (`/root/.claude/plans/…`) is container-local and does NOT survive to a new session. Everything needed is in the repo.
- **Sandbox limits:** proxy blocks `openrouter.ai:443` → any test POSTing a query-run fails at `validate_model_slots` (pre-existing/CI-only; always `git stash`-confirm a failure is pre-existing before chasing it). No browser MCP → do the Playwright/axe browser drive in the final verification (Slice V), not per-slice. Test cmd: `UV_CACHE_DIR=.uv-cache uv run --extra dev pytest`.
- **Open design decision (vetoable):** Slice 1 removed model-slot vendor-scoping for free choice (honors "duplicates allowed"); `bug10` test rewritten.

## Non-negotiable invariants (audit every slice against these)
1. **Green rule:** green `#0E6B50` means *minds agree* — brand mark + agreement/
   consensus/completed ONLY. Exactly ONE large green surface per journey (the
   verdict band). Money CTAs move on **ink** `#14171C`, never green. Running is
   **blue** `#47689E`. Green never appears until agreement.
2. **Tokens are locked** to `app.css` `:root` / `html[data-theme="dark"]`. No raw
   hex in components — use the semantic vars. Newsreader (serif) / Geist (UI) /
   Geist Mono (money·IDs·timings·counters).
3. **Copy is verbatim** from `docs/33-content-design.md` (COPY-001…006).
4. **a11y literal strings** asserted by `tests/accessibility/test_browser_ui_accessibility_contract.py`
   must survive; if one must change, update that test in the SAME commit.
5. **Pixel source of truth:** `docs/design-handoff/Quorum Final Review.dc.html`
   (open the numbered `#01`…`#08` section for the slice you're building).
6. **No secrets/provider keys** in any error state; correlation_id + query_run_id
   surfaced on receipt and every error.

## Per-slice workflow (do NOT skip a step)
1. Read this file + the matching `.dc.html` section + the slice's AC IDs.
2. Implement in the existing no-build stack (edit app.css / workspace.html / app.js).
3. Self-verify: `verify` skill (drive the real /ui flow) + `UV_CACHE_DIR=.uv-cache uv run --extra dev pytest` + `cd e2e && npm test`.
4. Adversarial review panel (isolated subagents, each told to REFUTE). **Use the
   PRE-INSTALLED specialized skill for each dimension — do NOT reinvent as a generic
   reviewer, and do NOT author a new custom skill (the repo library already covers
   every dimension). MECHANISM: the `.agents/skills/<name>/` skills are NOT
   Skill-tool-registered this session — the reviewer must `Read`
   `/home/user/repo/.agents/skills/<name>/SKILL.md` and APPLY its checklist. Only
   `taste-check` + `uiux-*` + built-ins (`code-review`, `security-review`) are
   Skill-tool-invokable.**
   - Backend slices → `code-quality-review` + `python-fastapi-backend-guardrails`;
     `clean-architecture-enforcer`; `api-contract-governance` + `contract-testing`
     (response/contract compat); `security-threat-modeling` + `owasp-control-mapper`
     (money/provider-key boundary); `test-architecture`.
   - UI slices → `ux-design` + `design-system-governance` + `uiux-*`;
     `accessibility-testing`; `code-quality-review`; design-fidelity-vs-dc.html.
   - Every slice → `taste-check` + `fanatic-critic` (ruthless).
   VERIFY each finding before applying (reviewers err — re-check the claim against the
   code; some findings are wrong). Fix confirmed findings; re-verify (tests/build).
   **RE-REVIEW LOOP (required): after applying fixes, run a focused adversarial
   re-review of the fixed areas until a pass returns NO new confirmed findings.**
   Do not commit a slice while any confirmed finding is open. Scale the loop to risk:
   money/security/honesty-touching slices get a full second panel; low-risk cosmetic
   fixes get a single focused re-check.

### Industrial PR-review gate (run BEFORE opening the PR)
`enterprise-quality-gatekeeper` → `fanatic-critic` → `nfr-measurability-gate` (AC-035
a11y + perf) → `devsecops` (secrets/scanning) → `traceability-management` +
`acceptance-criteria-quality-gate` (AC-001…036 crosswalk) → `production-readiness-review`
/ `release-readiness` (go/no-go + evidence + rollback in PR body).
5. **Do NOT pause for per-slice approval** (user relaxed this) — once the re-review
   loop is clean, commit the slice yourself and continue to the next.
6. **MANDATORY on every slice commit:** update this file's ledger row (status →
   DONE + commit SHA, key decisions, carry-forwards) IN THE SAME commit as the slice.
   A slice is not "done" until its ledger row is updated. Never let the ledger drift
   from the branch.

## PR strategy — 2–3 cohesive PRs (NOT per-slice, NOT one giant PR)
The frontend slices edit the same 3 files in a dependency chain, so per-slice PRs would
be stacked and churny; the rigorous review is already per-slice (adversarial panels on
each commit), so the PR is the FINAL external gate. Open at cohesive boundaries:
- **PR-A — Backend** (B1 `d46cb42` + B2 `5a5b9e8`): self-contained, no UI; mergeable to
  `main` first, independently.
- **PR-B — Money-path UI** (Slices 0→4b): the reviewable core.
- **PR-C — Remaining** (Slices 5–7 + `docs/32-ui-state-matrix.md`).
Run the **Industrial PR-review gate** (above) before opening EACH PR; put its go/no-go
evidence + AC-001…036 crosswalk + green-rule audit + rollback in the PR body. After a PR
merges to `main`, rebase the remaining branch onto the new `main` before continuing.

## Test command
`UV_CACHE_DIR=.uv-cache uv run --extra dev pytest`  ·  lint `uv run ruff check .`  ·  types `uv run mypy src tests`  ·  e2e `cd e2e && npm test`

## Canonical numbers from the mock (screen 03 / 05)
- by_model: GPT-4o-mini $0.034 · Claude Haiku 4.5 $0.062 · Gemini 2.5 Flash $0.031 · DeepSeek V3.1 $0.039 · **Synthesis writer $0.024** · total **$0.190**
- by_stage: Initial×4 $0.078 · Debate R1 $0.044 · Debate R2 $0.044 · Synthesis $0.024 · total $0.190
- receipt reconciliation: est $0.190 → actual $0.171 (under approved $0.19, green delta)

## Slice ledger
| # | Slice | Status | Notes |
|---|-------|--------|-------|
| 0 | Design system + view switch | **DONE — committed 3132548** | Tokens+fonts+components+header+setView scaffold. 4 adversarial reviews; all confirmed fixes applied. USER DECISIONS: --muted WCAG-corrected to AA (#5F6570 light / #8A9099 dark, clears AA on every surface incl. pill/line); pre-existing app.js edits KEPT + boot() hardened. 44 contract tests pass; 2 unrelated pre-existing failures untouched (422 backend contract; drift-banner stale-id — both reproduce on clean tree). /ui 200. |
| B1 | Backend: CostBreakdown | **DONE — committed d46cb42** | by_model (4 + Synthesis-writer, `kind` field); by_stage keys initial_answers/debate_round_1/debate_round_2/synthesis; sign-safe largest-remainder reconciliation (no negative lines), Field(ge=0), display names via lookup_short_name. 14 adversarial tests. CARRY-FWD to Slice 2: fix e2e/tests/api-mocking mock breakdown shape (currently wrong legacy array). |
| B2 | Backend: agreement + positions + actual cost | **DONE — committed 5a5b9e8** | agreement + position_movements on ResultProjection (INFERRED, honesty-reframed — no fabricated concession; banned-verb guard test); actual_cost_usd (required) + actual_breakdown, demo→actual=estimate. openapi.yaml regenerated; make validate passes. Backend extension COMPLETE. |
| 1 | 02 Composer (draft) | **DONE — committed 15d4636** | COPY-001/002, high-stakes gate (race-fixed), 2×2 slots w/ per-slot estimates from breakdown.by_model, free-choice swap (vendor-scoping/bug10 removed — DESIGN DECISION, vetoable), dead runNow removed, "See the estimate →" ink CTA. |
| 2 | 03 Cost gate | **DONE — committed 054669a** | `data-view="cost-gate"`: serif question echo, 42px mono total, dataviz threshold rail (ink-tint/amber/red, NO green — deviates from the green-tinted mock per the green rule), itemized by-model/by-stage from `breakdown` via pure `costGatePartitions()`, COPY-003 verbatim reason band, ink `#gate-confirm`. 2 adversarial panels + re-review-until-clean. DECISIONS: 5 new per-theme cost tokens (no raw literals in `.cost-*`; themes in dark); ±15% "estimated range" is CLIENT-illustrative — upper clamped to $0.25, 2dp, hidden in block band; persistent aria-live region (outside swapped views) + rAF announce + h1 focus on entry; `proceedWithRun` block early-return; `formatUsd({suffix})`; per-column aligned decimals. CARRY-FWD: block band is a minimal stub w/ `TODO(Slice 6 / COPY-004)`; confirm→run returns to composer (Slice 3 live-run placeholder); client thresholds ($0.15/$0.25) duplicate backend `SOFT/HARD_LIMIT` — consistent + commented, unguarded (would need estimate payload to emit thresholds). |
| 3 | 04 Live run | **DONE — committed (this commit; SHA backfilled at Slice 4a)** | Full-width honest live-run hero (`data-view="live-run"` spans `.layout`, hides the redundant Run-controls aside via `[data-active-view="live-run"]` CSS). Renders ONLY real poll data (status/elapsed/5-stage strip/per-model status/round-level debate/approved cap); mock-only richness (per-model stances, streaming, spend-so-far, per-stage timing/cost) deliberately DROPPED for honesty. Running=BLUE `--info` (NO green until verdict); `--info-glow` token added both themes. Live elapsed ticker (rebased to server `elapsed_time_ms`, frozen at terminal). 5-reviewer panel + 2-reviewer re-review + tightening. Key fixes: `#live-notices` failure disclosure in-card; focus→live h1 + scroll on entry; `state.liveSig` per-region change-detection (no 750ms churn/announce-spam); copyable `#live-corr`; `.live-*.mono` compounds; `liveNoticesHaveContent()` honest toast copy; `formatElapsed` guards; N/4 counts completed-only. CARRY-FWD: terminal→result transition + debate de-dup → Slice 4a (`TODO(Slice 4a)` in pollRun). |
| 4a | 05 Result: verdict band + trust triangle | **DONE — committed (this commit; SHA backfilled at Slice 4b)** | Result-view skeleton (header, "You asked" serif question, meta row) + VERDICT BAND (the ONE large green surface) + TRUST TRIANGLE (Agreement/Source support/Open uncertainty), driven by real `agreement`/`final_synthesis`/`citation_coverage`. GREEN GATE (AC-019, airtight + fail-safe, verified): band+ring+Agreement-accent green ONLY when `agreement.total>0 && aligned===total && quality_checks.false_consensus_preserved===false && status==="completed" && no failed_steps` — else neutral/amber (a divided panel still has a `recommendation`, so green is NEVER derived from that). Verdict text = `recommendation` verbatim; eyebrow "The panel's verdict"/"The panel's leaning" conditional. HONESTY (4-reviewer panel + honesty re-review, all confirmed): dropped hardcoded "after two debate rounds"; "N revised their position" (no direction, no banned verbs); agreement caption states what N IS (inferred, not a tallied vote); source card = claim-coverage % + DISTINCT non-fallback source count; uncertainty = real prose, no fabricated flag count. Copy/Export functional (label mirrors consensus). Terminal→result transition (only when `final_synthesis` exists; else stays on live-run). `--verdict-surface`/`--verdict-on` theme-invariant tokens; ring reduced-motion-guarded; a11y region roles; contrast ≥5.4:1 on the green band. CARRY-FWD: "Run details" toggle + receipt/positions/synthesis-in-view + terminal-debate de-dup → Slice 4b. |
| 4b | 05 Result: receipt + positions table + cost reconciliation | **DONE — committed (this commit; SHA backfilled at Slice 5)** | Added into the 05 result view: "Run details ▴" disclosure toggle (collapsed by default, aria-expanded/controls) → collapsed RUN-RECEIPT (4 role=group cols: Run receipt w/ copyable Run ID+Correlation · Cost by model est→actual · Cost by stage est→actual · Pipeline states) + "HOW POSITIONS MOVED" as a NATIVE `<table>` (th scope col/row, sr-only mobile headers + data-label, overflow-x wrapper). HONESTY (3-reviewer panel + re-review, all confirmed): positions caption "Inferred from opening answers and panel consensus — not a quoted transcript" ALWAYS rendered (not demo-gated), cells verbatim, no banned verbs, no fabricated direction; reconciliation null-guards `actual_breakdown`→"pending"/"—", demo→"Matched estimate", delta on INK (money-on-ink, not green); **FABRICATED "Tavily" provider REMOVED → "Fallback search ×N"** (backend fallback is a local stub, no Tavily API — OQ-008/DEBT-002); per-stage pipeline durations DROPPED as mock-only (no field), only real whole-run elapsed shown; est↔actual matched by model_id/stage KEY not index. GREEN-CREEP fixed: pipeline done glyph → --muted, copy copied-state → --info (only the ✓Revised chip stays green = agreement). Toggle node-move made robust (module-level ref). CARRY-FWD: transcript "Read the full debate →" link + the synthesis-in-view consolidation → Slice 5; caption not `aria-describedby`-bound (LOW, within criteria). |
| 5 | 06 Transcript | **DONE — committed (this commit; SHA backfilled at Slice 6)** | New `data-view="transcript"` (full-width, aside hidden), reachable from the 05 result view's "Read the full debate transcript →" link (wired) + "← Back to verdict"/footer → result. HONESTY (2-reviewer panel, both verdicts ship-ready): OPENING POSITIONS are REAL per-model (`model_answers`: display_name, answer_text, honest provider tag live/fallback/simulated w/ `fallback_used` cross-check, non-fallback src count); THE DEBATE renders ROUND-level `critique_text`+`focus_areas` ONLY with a permanent caption "…does not record a per-model, line-by-line transcript" — the mock's per-model exchanges + conceded/refined chips are DROPPED as mock-only, NOT fabricated. Green status chip "Consensus reached"/footer ONLY on real consensus (shared `isConsensusResult` gate — EXTRACTED as the single source of truth, now called by BOTH renderResult + renderTranscript, no more duplicated AC-019 gate); amber "Panel divided" otherwise. "converged" avoided (banned). `state.lastResult` captured at terminal (final_synthesis present), reset on run start, null-guarded. BONUS honesty fix: 05 synthesis tooltip "four refined answers"→"four opening answers and the round-level debate critiques" (matches synthesis.py:228). CARRY-FWD: transcript link over-promises on a no-debate partial (graceful empty state, LOW); caption not aria-describedby-bound (LOW). |
| 6 | 07 Edge states (seven) | pending | |
| 7 | 08 Dark + 01 Landing | pending | |
| V | Verify + ui-state-matrix + PR | pending | fill docs/32-ui-state-matrix.md; map AC-001…036. |

## Known pre-existing issues (not caused by this work)
- `test_workspace_html_has_brand_lede` was already red on clean checkout (template lede
  ≠ EXPECTED_BRAND_LEDE "One question. Four models. One answer you can verify."). Fix in Slice 1.
