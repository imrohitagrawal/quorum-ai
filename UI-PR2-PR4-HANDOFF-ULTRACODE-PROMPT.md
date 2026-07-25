# Ultracode Prompt — PR2 Completion + PR3 CSS Layout + PR4 Data Completeness Closeout

## Where We Are

You are on branch `feat/ui-pr1-quickfixes`. PR2 (data completeness) is **partially shipped**.
The following PR2 changes are **already committed**:

| File | Change |
|------|--------|
| `config.py` | `cost_synthesis_output_tokens`: 800 → 3000; `cost_debate_output_tokens_cap`: 700 → 2000 |
| `model_slots.py` | `DEFAULT_MODEL_IDS` updated: haiku-4.5, gemini-2.5-flash, nemotron-3-super-120b-a12b (replaces claude-3-haiku / gemini-2.5-flash-lite / deepseek-chat-v3.1). Validator unions fallback catalog into `known_ids`. |
| `synthesis.py` | `SYNTHESIS_SECTION_MAX_TOKENS`: 800 → 3000; per-answer `[:600]` and per-round `[:700]` excerpt slicing removed |
| `debate.py` | `DEBATE_ROUND_MAX_TOKENS`: 700 → 2000 |
| `synthesis_length.py` | `DEFAULT_SECTION_MAX_CHARS`: 280 → 4000; `RECOMMENDATION_MAX_CHARS`: 420 → 2000 |

**NOT yet done (the gap you must close):**

| # | File | Missing Change |
|---|------|----------------|
| 1 | `providers.py` | Remove any per-answer `excerpt_length` / output text cap that slices `answer_text` before it reaches the UI. Add a `shortened: bool` field on `InitialModelAnswer` so the UI can show "(shortened)" when the provider itself returned partial text (detected via `finish_reason == "length"` or `token_usage` hitting `max_tokens`). |
| 2 | `workspace.html` + `app.js` | Confirm no client-side truncation (`.slice(0, N)`, `substring(0, N)`) is slicing content the server now sends in full. Remove any such slicing. Ensure accordion expanders surface the full text (hidden by default, fully visible when expanded). Verify `createSafeLink` is used for any new citation links. |
| 3 | `costs.py` | The file reads `cost_synthesis_output_tokens` and `cost_debate_output_tokens_cap` from `config.py` — verify no hardcoded stale constants remain (e.g. an 800-token floor that bypasses config). |
| 4 | Golden fixture + e2e invariants | Update `e2e/fixtures/golden-run.ts` with 1500+ char answers and 1200+ char critiques. Run `PYTHONPATH=src .venv/bin/python -2e/run_invariants.py` and verify rendering-invariants, degraded-banner, and visual-snapshots all pass. |
| 5 | RED-GREEN proof | For each PR2 change, document the RED (revert the change, run affected tests — they must FAIL) then GREEN (re-apply, they PASS) transition. |

## Scope for This Session

Work through these phases **in order**:

### Phase 1: Close PR2 gaps (items 1–4 above)

**Step 1 — providers.py:**
- Read `providers.py` and find any `excerpt_length`, `max_length`, or similar cap on the initial-answer `answer_text` before it reaches the `InitialModelAnswer` constructor.
- Raise or remove the cap so the full provider response passes through.
- Add `shortened: bool = False` to `InitialModelAnswer`. Set it to `True` when the provider response indicates truncation (`finish_reason == "length"` or `token_usage` is present and `token_usage.completion_tokens >= max_tokens`).
- Write unit tests in `tests/unit/test_providers.py`:
  - A test that proves a `finish_reason="length"` response sets `shortened=True`.
  - A test that proves a normal response has `shortened=False`.

**Step 2 — workspace.html + app.js:**
- Search `workspace.html` and `app.js` for any client-side truncation: `slice(0,`, `substring(0,`, `.slice(0`, `truncate`, `excerpt`.
- Remove any slicing on the full answer text, critique text, or synthesis sections. The only acceptable truncation is the server-side soft cap in `synthesis_length.py` (which adds a `…`).
- Confirm the accordion expanders (PR1's `createSafeLink` pattern) render full text when expanded.
- Run the rendering invariants e2e to confirm no raw Markdown or overflow.

**Step 3 — costs.py audit:**
- Grep `costs.py` for any hardcoded 800, 700, 250, 300 token constants that might bypass the config values.
- If found, replace with `settings.cost_synthesis_output_tokens` or `settings.cost_debate_output_tokens_cap`.
- Add a test assertion in `test_cost_guardrails.py` that `cost_estimation_service._cost_components(...)` uses the configured values, not stale literals.

**Step 4 — Golden fixture + e2e invariants:**
- Read `e2e/fixtures/golden-run.ts`. Extend the fake provider answers to 1500+ chars and critiques to 1200+ chars.
- Run `PYTHONPATH=src .venv/bin/python -m e2e/run_invariants.py`. Verify all invariants pass (rendering-invariants, degraded-banner, visual-snapshots).
- If visual-snapshots fail due to layout changes from longer text, update the baselines (seed-visual-baselines.yml workflow) and document the new baselines.

**Step 5 — RED-GREEN proof:**
- For each of the five PR2 changes (synthesis excerpt removal, synthesis token raise, debate token raise, providers.py cap removal, synthesis_length.py raises), write a brief proof:
  - **RED**: Revert the change temporarily, run the affected test(s), capture the failure output.
  - **GREEN**: Re-apply the change, run the same tests, capture the pass output.
- Document this in a `PR2-RED-GREEN-PROOF.md` file at the repo root.

### Phase 2: PR3 — CSS Layout Fixes

**Context:** PR1 shipped quickfixes (noopener, result copy button, chip rapid-click, ✓ glyph). PR2 shipped data completeness. PR3 is the CSS pass that makes long-form content readable.

**Step 6 — Audit CSS for long-form readability:**
- Read `src/product_app/static/app.css`. Identify any `max-height`, `overflow: hidden`, `text-overflow: ellipsis`, `white-space: nowrap`, or fixed-height containers that would clip 3000-token synthesis output or 1500-char answers.
- Add or adjust rules so:
  - Synthesis accordion sections expand to fit their content (no fixed max-height that clips).
  - Answer text in the transcript view wraps naturally (no horizontal overflow).
  - Source citations render as links, not truncated strings.
  - The degraded banner (for `live_count < 4`) remains visible above the fold.

**Step 7 — Verify CSS changes:**
- Run the e2e invariants again (rendering-invariants catches overflow, visual-snapshots catches layout regressions).
- Manually render the golden fixture at 1440px and 375px viewport widths. Confirm no horizontal scroll, no clipped text, accordion expand/collapse works.

### Phase 3: PR4 — Data Completeness Closeout

**Step 8 — Verify the full data path:**
- Trace the full path: provider returns full answer → `InitialModelAnswer.answer_text` carries it → synthesis `_user_prompt` threads it → synthesis sections produce output → `synthesis_length.py` soft-caps → `workspace.html` / `app.js` renders it → user sees it.
- Confirm there is no truncation at any layer except the intentional soft cap in `synthesis_length.py`.
- If you find a truncation layer, fix it.

**Step 9 — Cost reconciliation final check:**
- Run `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_cost_breakdown.py tests/unit/test_cost_guardrails.py tests/unit/test_estimate_token_model.py -q --no-cov`. All must pass.
- Verify the cost guardrail bound for the new DEFAULT_MODEL_IDS (4 cheap models) stays under $0.15 (ALLOW). It should: ~$0.076.
- Verify a mixed opus+cheap run lands in the CONFIRM band (0.15, 0.25], not BLOCK. If it crosses $0.25, document why and whether that's acceptable.

### Phase 4: Quality Gates + Handoff

**Step 10 — Run the full gate suite:**
```bash
make validate
make quality
```
Both must pass. If `make quality` includes `make mutation-baseline`, ensure it collects and scores mutants (not abort).

**Step 11 — Commit and closeout:**
- Stage all changes.
- Commit with message: `feat(PR2-PR4): data completeness closeout — full-text pipeline, CSS layout, cost reconciliation`
- Run `make handoff` to update `docs/00-factory-console.md` and `docs/session-handoff.md`.
- Update `UI-PR2-DATA-COMPLETENESS-ULTRACODE-PROMPT.md` with the "What changed" paragraph, verify output, and PR/deploy links.
- Update `UI-PR2-PR4-HANDOFF-ULTRACODE-PROMPT.md` (this file) with "COMPLETE" and the deploy SHA.

## Good Practices (enforce these throughout)

1. **TDD**: Write the test first, watch it FAIL, then make it pass. A test that passes without the change is worthless.
2. **Evidence-first**: Verify before claiming. Run the single cheapest command that confirms/refutes a hypothesis before stating it as fact.
3. **No claim without a check**: Never assert a cost, status, or behavior as settled without running the command that proves it.
4. **Adversarial review**: Before calling done, run an independent review pass on your own diff — look for what you missed, not what you got right.
5. **Cost model integrity**: Every token-cap change must be reflected in `costs.py`. The guardrail bounds must be re-verified after any token change.
6. **RED-GREEN proof**: Every behavioral change ships with a test that fails without it. Document the RED→GREEN transition.
7. **No paid runs for routine checks**: Use local sim, e2e, and estimate gates. One deliberate live run only for measured-cost verification.
8. **Report faithfully**: If a test fails, say so with the output. If a step was skipped, say so. Done-and-verified = plain statement, no hedging.

## Key Reference Values

| Setting | Current | Target |
|---------|---------|--------|
| `SYNTHESIS_SECTION_MAX_TOKENS` | 3000 | 3000 (done) |
| `DEBATE_ROUND_MAX_TOKENS` | 2000 | 2000 (done) |
| `cost_synthesis_output_tokens` | 3000 | 3000 (done) |
| `cost_debate_output_tokens_cap` | 2000 | 2000 (done) |
| `DEFAULT_SECTION_MAX_CHARS` | 4000 | 4000 (done) |
| `RECOMMENDATION_MAX_CHARS` | 2000 | 2000 (done) |
| `InitialModelAnswer.shortened` | **MISSING** | Add it |
| `providers.py` excerpt cap | **UNKNOWN** | Remove/replace it |
| Client-side truncation in app.js | **UNKNOWN** | Remove any found |

## Definition of Done

- [ ] `providers.py`: excerpt cap removed, `shortened: bool` added with tests
- [ ] `workspace.html` + `app.js`: no client-side truncation, full text renders
- [ ] `costs.py`: no stale hardcoded constants, uses config values
- [ ] Golden fixture updated (1500+ char answers, 1200+ char critiques)
- [ ] E2E invariants pass (rendering, degraded-banner, visual-snapshots)
- [ ] RED-GREEN proof documented for all PR2 changes
- [ ] CSS layout pass (PR3) — no overflow, accordion works, citations render
- [ ] Full data path verified (provider → UI, no silent truncation)
- [ ] Cost guardrail verified for new DEFAULT_MODEL_IDS
- [ ] `make validate && make quality` green
- [ ] Committed with closeout message
- [ ] `make handoff` run
- [ ] This prompt file updated to COMPLETE with deploy SHA
