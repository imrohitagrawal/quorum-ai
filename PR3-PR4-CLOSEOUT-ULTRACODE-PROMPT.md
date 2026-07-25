# Ultracode Prompt — PR3 CSS + E2E Invariants + RED-GREEN Proof + Closeout

## Where We Are

You are on branch `feat/ui-pr1-quickfixes`. PR2 (data completeness) is **fully
committed**. All 796 unit tests pass. The remaining work is:

1. **PR3** — CSS layout pass so 3000-token synthesis + 1500-char answers don't clip
2. **E2E invariants** — rendering-invariants, degraded-banner, visual-snapshots
3. **RED-GREEN proof** — document the RED→GREEN transition for each PR2 change
4. **Cost guardrail target verification** — confirm DEFAULT_MODEL_IDS bound
5. **Full gate suite** — `make validate && make quality`
6. **Commit + handoff** — closeout message, `make handoff`, update this file

---

## Phase 1: PR3 — CSS Layout Pass for Long-Form Content

**Context:** PR2 raised token caps (synthesis 800→3000, debate 700→2000) and
removed excerpt slicing. The golden fixture now carries 2173-char answers and
2000-char critiques. CSS rules that clip, truncate, or hide overflow on the
result/transcript surfaces will now hide content from users.

### Step 1 — Audit CSS for content-clipping rules

1. Run `grep -n "max-height\|overflow: hidden\|text-overflow: ellipsis\|white-space: nowrap" src/product_app/static/app.css`
2. For each match, read the surrounding context (the selector block). Determine:
   - **SAFE to keep**: accessibility-only (`sr-only`, `clip: rect(0,0,0,0)`), progress
     bars, loading skeletons, cost-gate single-line inputs
   - **NEEDS FIX**: rules on synthesis sections, answer text, debate critique text,
     trust-card captions, transcript openings, source lists — any surface that
     renders provider prose
3. For each rule that NEEDS FIX:
   - Remove `max-height` + `overflow: hidden` (let content flow naturally)
   - Remove `text-overflow: ellipsis` + `white-space: nowrap` on prose surfaces
   - If a rule was intentionally constraining a single-line chip/badge, scope it
     tighter (add a class selector) so it doesn't catch prose containers
4. **Do NOT** change rules on:
   - Accessibility utilities (`.sr-only`, `[aria-hidden]`)
   - Progress bars, spinners, loading states
   - Single-line input fields in the cost gate
   - Source citation chips (short labels, not prose)

### Step 2 — Verify CSS changes

After edits, run the rendering-invariants e2e (see Phase 2, Step 5). If it
passes, the CSS is good. If overflow is flagged, the e2e output names the
specific selector — fix it and re-run.

---

## Phase 2: E2E Invariants

### Step 3 — Extend e2e fixture model lists

The golden fixture (`e2e/fixtures/golden-run.ts`) and several e2e test files
still reference `deepseek/deepseek-v3.1`. Update ALL of these to
`nvidia/nemotron-3-super-120b-a12b`:

- `e2e/fixtures/golden-run.ts` — SLOTS, BY_MODEL (already done in working tree)
- `e2e/tests/ui-parity/parity-behavior.spec.ts` — SLOTS, BY_MODEL, vendor array
- `e2e/tests/accessibility/axe-all-views.spec.ts` — SLOTS, BY_MODEL

Verify: `grep -rn "deepseek" e2e/tests/` should return zero matches after edits.

### Step 4 — Run e2e invariants

```bash
cd /Users/rohitagrawal/Projects/quorum-ai
PYTHONPATH=src .venv/bin/python -m e2e/run_invariants.py
```

This runs:
- `rendering-invariants.spec.ts` — walks `#main-content`, asserts NO raw Markdown
  markers in text nodes, monotonic elapsed timer, no horizontal overflow
- `degraded-banner.spec.ts` — degraded banner visible when `live_count < 4`
- `visual-snapshots.spec.ts` — `toHaveScreenshot` against baselines

**If rendering-invariants fails:** the failure message names the specific
surface and marker. Fix the surface in `app.js` or `workspace.html`, re-run.
Do NOT relax the invariant.

**If visual-snapshots fails due to layout changes from longer text or CSS
fixes:** update the baselines by re-running with `UPDATE_SNAPSHOTS=1` (check
the workflow in `.github/workflows/seed-visual-baselines.yml` for the exact
env var name). Document the baseline update in the closeout note.

**If degraded-banner fails:** investigate whether the banner is hidden by a
new CSS rule. Fix the CSS, re-run.

### Step 5 — Drive the real UI at 1440px and 375px

After invariants pass, do a manual browser check:

1. Start the dev server: `uv run python -m product_app.app` (or your project's
   dev server command)
2. Open `http://localhost:8000/ui` at 1440px width
3. Submit the test query: "What are the key metrics for measuring SaaS customer retention?"
4. Let the golden fixture drive the run to completion
5. Verify visually:
   - Synthesis accordion sections expand to show full 2000-char text (no clipping)
   - Answer text in transcript wraps naturally (no horizontal scroll)
   - Source citations render as links (not truncated strings)
   - Degraded banner visible above the fold if `live_count < 4`
6. Resize to 375px and re-verify

---

## Phase 3: RED-GREEN Proof

### Step 6 — Document RED→GREEN for each PR2 change

For each of these five changes, write a proof that shows the test failing
(RED) then passing (GREEN):

| # | Change | Key test to prove it |
|---|--------|---------------------|
| 1 | synthesis.py: removed `[:600]` and `[:700]` excerpt slicing | `test_user_prompt_includes_full_600_char_excerpt` |
| 2 | synthesis.py: `SYNTHESIS_SECTION_MAX_TOKENS` 800→3000 | `test_synthesis_section_max_tokens_is_3000` |
| 3 | debate.py: `DEBATE_ROUND_MAX_TOKENS` 700→2000 | `test_debate_round_max_tokens_is_2000` |
| 4 | debate.py: removed `[:200]` answer slice | No dedicated test yet — write one |
| 5 | providers.py: `shortened` field + finish_reason detection | `test_shortened_true_when_finish_reason_length` |

For each change:
1. **RED**: Temporarily revert the change. Run the specific test. Capture the
   failure output (the assertion error message).
2. **GREEN**: Re-apply the change. Run the same test. Capture the pass output.
3. Write a one-paragraph entry in `PR2-RED-GREEN-PROOF.md` at the repo root.

**For change #4 (debate.py `[:200]` removal):** if no test exists, write one
in `tests/unit/test_debate.py` that proves the debate prompt includes the full
answer text (not just the first 200 chars). The test should fail when the
slice is present and pass when removed.

---

## Phase 4: Cost Guardrail Target Verification

### Step 7 — Verify DEFAULT_MODEL_IDS guardrail bound

The new DEFAULT_MODEL_IDS (4 cheap models: gpt-4o-mini, haiku-4.5, gemini-2.5-flash,
nemotron-3-super-120b-a12b) must have a bound under $0.15 (ALLOW band).

Run:
```bash
uv run pytest tests/unit/test_cost_breakdown.py::test_breakdown_shape_and_reconciliation -v --tb=short --no-cov -p no:randomly
```

Verify the output shows all parametrized variants with `threshold_action == ALLOW`
and `max_cost_usd < $0.15`. If any variant exceeds $0.15, document which model
causes it and whether it should be swapped for a cheaper alternative.

---

## Phase 5: Quality Gates + Handoff

### Step 8 — Full gate suite

```bash
make validate
make quality
```

Both must pass cleanly. If `make quality` includes mutation testing, ensure
it scores mutants (doesn't abort on threshold). If mutation score is below
threshold, investigate which mutants survive and whether they represent
real gaps or false positives.

### Step 9 — Commit and handoff

```bash
git add -A
git diff --cached --stat  # review what's staged
git commit -m "feat(PR2-PR4): data completeness closeout — full-text pipeline, CSS layout, cost reconciliation

Co-Authored-By: Claude <noreply@anthropic.com>"
```

Then run:
```bash
make handoff
```

This updates `docs/00-factory-console.md` and `docs/session-handoff.md`.

### Step 10 — Update handoff prompt files

Update `UI-PR2-PR4-HANDOFF-ULTRACODE-PROMPT.md`:
- Change all checklist items from `[ ]` to `[x]`
- Add a "COMPLETE" section with:
  - Commit SHA
  - Deploy SHA (if deployed)
  - Brief summary of what shipped
  - Link to PR

Update `UI-PR2-DATA-COMPLETENESS-ULTRACODE-PROMPT.md`:
- Add a "What changed" paragraph summarizing the PR2 closeout
- Add deploy verification status

---

## Good Practices (enforce these throughout)

1. **TDD**: Write the test first, watch it FAIL, then make it pass.
2. **Evidence-first**: Verify before claiming. Run the cheapest check first.
3. **No claim without a check**: Never assert a cost/status/behavior without
   running the command that proves it.
4. **Adversarial review**: Before calling done, review your own diff for what
   you missed, not what you got right.
5. **Cost model integrity**: Every token-cap change is reflected in costs.py.
6. **RED-GREEN proof**: Every behavioral change ships with a test that fails
   without it.
7. **No paid runs**: Use local sim, e2e, and estimate gates.
8. **Report faithfully**: If a test fails, say so with the output. If a step
   was skipped, say so. Done-and-verified = plain statement.

---

## Key Reference Values

| Setting | Value |
|---------|-------|
| SYNTHESIS_SECTION_MAX_TOKENS | 3000 |
| DEBATE_ROUND_MAX_TOKENS | 2000 |
| DEFAULT_SECTION_MAX_CHARS | 4000 |
| RECOMMENDATION_MAX_CHARS | 2000 |
| InitialModelAnswer.shortened | True (added) |
| Golden fixture answer length | ~2173 chars |
| Golden fixture critique 1 length | ~2000+ chars |
| Golden fixture critique 2 length | ~800+ chars |

---

## Definition of Done

- [ ] PR3 CSS pass — no content clipping on result/transcript surfaces
- [ ] E2E invariants pass (rendering, degraded-banner, visual-snapshots)
- [ ] Golden fixture e2e model lists updated (deepseek → nvidia)
- [ ] RED-GREEN proof documented in PR2-RED-GREEN-PROOF.md
- [ ] Cost guardrail bound verified under $0.15 for DEFAULT_MODEL_IDS
- [ ] `make validate && make quality` green
- [ ] Committed with closeout message
- [ ] `make handoff` run
- [ ] Handoff prompt files updated to COMPLETE with deploy SHA
