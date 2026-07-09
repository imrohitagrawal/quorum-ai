# Quorum R1 UI — Slice State & Integrity Anchor

> **Every fresh context (chat or subagent) reads this FIRST**, before touching code.
> It is the single source of truth for what's done, what's next, and the
> invariants no slice may violate. Update it at every slice boundary.

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
4. Adversarial review panel (isolated subagents, each told to REFUTE):
   `taste-check` · `code-review` · design-fidelity-vs-dc.html · `accessibility-testing`
   · `security-review` (money/key slices). Fix confirmed findings; re-verify.
5. **Pause for user review** at the boundary. Commit only on approval.
6. Update this file (Done/Next), then hand off to the next fresh context.

## Test command
`UV_CACHE_DIR=.uv-cache uv run --extra dev pytest`  ·  lint `uv run ruff check .`  ·  types `uv run mypy src tests`  ·  e2e `cd e2e && npm test`

## Canonical numbers from the mock (screen 03 / 05)
- by_model: GPT-4o-mini $0.034 · Claude Haiku 4.5 $0.062 · Gemini 2.5 Flash $0.031 · DeepSeek V3.1 $0.039 · **Synthesis writer $0.024** · total **$0.190**
- by_stage: Initial×4 $0.078 · Debate R1 $0.044 · Debate R2 $0.044 · Synthesis $0.024 · total $0.190
- receipt reconciliation: est $0.190 → actual $0.171 (under approved $0.19, green delta)

## Slice ledger
| # | Slice | Status | Notes |
|---|-------|--------|-------|
| 0 | Design system + view switch | **DONE — awaiting user sign-off** | Tokens+fonts+components+header+setView scaffold. 4 adversarial reviews run; confirmed fixes applied (brand-tile theme-locked to #0E6B50 both themes; composer h2→h1; dead CSS cleaned; header-bg/inset light counterparts; CTA hover no longer pure-black). 34/34 contract tests green, /ui 200. OPEN: `--muted` #7A8089 fails AA (3.65:1) — deferred to user decision (see below). Pre-existing app.js edits (Number.isFinite guard, boot() reorder) present — keep/revert TBD. |
| B1 | Backend: CostBreakdown | pending | by_model incl. Synthesis-writer row; by_stage query→initial→debate(2/3 split r1=r2)→synthesis(1/3); re-sum-to-total after quantize. |
| B2 | Backend: agreement + positions + actual cost | pending | per-model positions emitted in debate.py (real when keyed / templated in demo); demo → actual=estimate; demo-mode caveat in UI. |
| 1 | 02 Composer (draft) | pending | reconcile brand-lede test (pre-existing red) here. |
| 2 | 03 Cost gate | pending | needs B1. |
| 3 | 04 Live run | pending | |
| 4a | 05 Result: verdict band + trust triangle | pending | needs B2. reduced-motion guard on ring. |
| 4b | 05 Result: receipt + positions table + cost reconciliation | pending | needs B1+B2. |
| 5 | 06 Transcript | pending | |
| 6 | 07 Edge states (seven) | pending | |
| 7 | 08 Dark + 01 Landing | pending | |
| V | Verify + ui-state-matrix + PR | pending | fill docs/32-ui-state-matrix.md; map AC-001…036. |

## Known pre-existing issues (not caused by this work)
- `test_workspace_html_has_brand_lede` was already red on clean checkout (template lede
  ≠ EXPECTED_BRAND_LEDE "One question. Four models. One answer you can verify."). Fix in Slice 1.
