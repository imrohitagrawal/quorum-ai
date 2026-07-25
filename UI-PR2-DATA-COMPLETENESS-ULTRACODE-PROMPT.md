# Ultracode Prompt — UI-PR2 Data Completeness

## Mission
Make sure no player silently drops sources or truncates their claims.
Triage analysis proved truncation is server-side data caps (`excerpt_length`), not CSS.
Shrink this surface to zero: show full text everywhere a real user can read it,
with explicit (shortened) markers so users can see when a provider returned partial text.
## Scope & non-goals
**IN scope (the six changes below, listed so you can verify each is done before stopping):**

1. `src/product_app/providers.py` — raise or remove excerpt/output text caps so full
   provider text reaches the UI (not just longer caps: the data layer must pass the
   entire answer through).
2. `src/product_app/debate.py` — raise `DEBATE_ROUND_MAX_TOKENS` from 700 to 2000 so the
   critique/response calls can finish without silent truncation.
3. `src/product_app/synthesis.py` — remove per-answer and per-round excerpt slicing
   (pass full `answer_text` and full `critique_text` into `synthesize_*`); raise
   `SYNTHESIS_SECTION_MAX_TOKENS` from 800 to 3000 so synthesis can use the additional
   tokens without truncating.
4. `src/product_app/templates/workspace.html` + `src/product_app/static/app.js` — ensure
   the full-text data fields render into the visible transcript + synthesis accordion
   sections (truncation should only ever come from the server returning partial data,
   never from UI-side slicing).
5. `src/product_app/synthesis_length.py` — raise length caps to match the new token
   ceiling (the synthesizer builds paragraph-length prose, not tokens, but the two caps
   must not fight each other).
6. `src/product_app/config.py` + `src/product_app/costs.py` — raise
   `cost_synthesis_output_tokens` to 3000 so the cost model prices what synthesis
   actually consumes (PR2's new max), not an outdated floor.

**OUT of scope for this PR:**

- The fallback chain / simulated data path. Provider error handling stays intact.
- CSS layout changes (next PR).
- Changing any provider API call shape beyond the token/limit params named above.
- Removing or refactoring `synthesis_length.py`'s structure (just update its constants).

## Working tree

**Do not switch branches.** You are on `feat/ui-pr1-quickfixes` (already checked out).
All listed files are modified (git-tracked), so parallel writers on this branch share
one working tree. Work serially on the source files above — fan out only for read-only
lookups (grep, tests, docs). The changes are in disjoint files; no parallel writers
needed.

## Implementation order

### 1. Raise the server-side data caps first
Source of truth for the truncation problem is `UI-BUG-TRIAGE-2026-07-23-ANALYSIS.md`
("truncation is server-side data caps"). Read it before touching code.

**`providers.py`:**
- Find the per-answer `excerpt_length` or equivalent output cap — the field that slices
  `answer_text` or caps the token response from the initial-answer call.
- Raise it so the full provider response passes through. Target: no per-answer slice;
  rely on `max_tokens` on the provider call itself.
- Add a `shortened: bool` marker on the answer object so the UI can render "(shortened)"
  whenever the provider itself returned less than the full text (detected via
  `finish_reason` like `length` or response token count vs. `max_tokens`).
- Reuse `createSafeLink` from PR1's `app.js` for any new citation links.

**`debate.py`:**
- Raise `DEBATE_ROUND_MAX_TOKENS` from 700 to 2000.
- The `costs.py` file already models `cost_debate_output_tokens_cap = 2000` — the live
  debate call was enforcing 700 (cheaper than the cost model assumed). Sync them.

**`synthesis.py`:**
- Remove `excerpt_length` slicing on the per-answer and per-round critique text
  passed into `synthesize_*`. The full strings should be forwarded.
- Raise `SYNTHESIS_SECTION_MAX_TOKENS` from 800 to 3000 so each of the five section
  calls can produce thorough output without truncating mid-sentence.
- Keep the existing section structure (one call per section), just raise the ceiling.
- Update `synthesize_intro_section`, `synthesize_uncertainty_section`, etc. so their
  prompts reference the full `answer_text` / `critique_text` fields.

**`synthesis_length.py`:**
- Raise `MAX_INITIAL_ANSWER_LENGTH` and `MAX_DEBATE_CRITIQUE_LENGTH` to match the new
  token ceiling (the synthesizer builds prose; these constants gate "long enough to
  bother summarizing").
- They must not be lower than the new `SYNTHESIS_SECTION_MAX_TOKENS = 3000` ceiling —
  guard that relationship explicitly in the module docstring.

**`config.py` + `costs.py`:**
- Raise `cost_synthesis_output_tokens` from 800 to 3000 so the cost model prices what
  synthesis actually consumes (PR2's new max), not an outdated floor.
- The fail-safe `max_cost_usd` bound prices synthesis at `cost_synthesis_sections ×
  cost_synthesis_output_tokens` — raising this from 800 to 3000 raises the bound.
  Verify the bound stays under `$0.25` for typical 4-cheap-model runs (it should: the
  measured cost of a real 4-cheap run is ~$0.02). For mixed opus+cheap runs the bound
  may cross $0.25; that is intentional — the rail is over-protecting, not under.

### 2. Update the UI so full text renders and is readable
**`workspace.html` + `app.js`:**
- Locate the transcript and synthesis rendering surfaces. Confirm they receive the
  full `answer_text` / `critique_text` / `synthesis_sections` content after the
  server-side cap changes above.
- Remove any `substring(0, N)` or similar client-side truncation that would slice
  content the server now sends in full.
- The accordion expanders from PR1 should now surface the entire text (not a
  truncated slice). Verify the collapse state still works — long text should be
  hidden by default but fully visible when expanded.

### 3. Golden fixture + rendering invariants
- Update `e2e/fixtures/golden-run.ts` so the fake provider answers are long enough to
  exercise the new caps (target: 1500+ char answers, 1200+ char critiques).
- Confirm `e2e/tests/invariants/rendering-invariants.spec.ts` still passes — no raw
  Markdown surviving in text nodes, no horizontal overflow, monotonic timer.
- Update `RAW_MARKDOWN_PATTERNS` in the test to match any new patterns exposed by
  the longer text.

## Test plan (execute every step, in order)
### Unit tests (fastest feedback)
- `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_cost_breakdown.py -q --no-cov`
- `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_synthesis.py -q --no-cov`
- `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_providers.py -q --no-cov`
- `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/ -q --no-cov` (full unit suite)
- **No PR2 source change is complete until the full unit suite passes (excluding the
  pre-existing `anthropic/claude-opus-4` / `google/gemini-2.5-flash` catalog
  failures that existed before PR2 and are unrelated to this work).**

### E2E / invariants
- Update golden fixture and run: `PYTHONPATH=src .venv/bin/python -m e2e/run_invariants.py`
- Verify rendering-invariants, degraded-banner, and visual-snapshots specs.

### RED-GREEN proof (required)
Before merging, prove each change bites:
1. **RED**: Temporarily revert the cap raise (e.g. reset `SYNTHESIS_SECTION_MAX_TOKENS` to
   800, restore the excerpt slice), run the affected tests + rendering invariants — they
   must FAIL (e.g. truncated content in prompt, cost floor mismatch, overflow).
2. **GREEN**: Re-apply the fix, re-run — all must PASS.
3. Document the RED/GREEN transition in the closeout summary.

## Quality gates
- `make validate` must pass (formatting, linting, type checking, secrets scan).
- `make quality` must pass (unit, e2e, invariants).
- `make mutation-baseline` — the suite must collect and score mutants (not abort).
- Zero new warnings in CI.

## Definition of done
- [ ] All six source files listed above updated per the spec.
- [ ] Unit suite passes (excluding the pre-existing catalog failures).
- [ ] E2E invariants pass (rendering, degraded-banner, visual-snapshots).
- [ ] RED-GREEN proof documented for each change.
- [ ] Cost model tests updated and passing (breakdown reconciliation verifies
      `cost_synthesis_output_tokens == 3000`).
- [ ] `make validate && make quality` green locally.
- [ ] Closeout PR authored with the exact diff + verification output.

## Final handoff
After green gates, update `UI-PR2-DATA-COMPLETENESS-ULTRACODE-PROMPT.md`:
- Add a short "What changed" paragraph.
- Attach the verify output (pytest summary, cost breakdown, e2e invariants result).
- Link to the PR and note the deploy SHA when it ships.
- Move on to `UI-PR3` (CSS layout fixes) for the next session.


## Handoff

The remainder of this work is documented in
`UI-PR2-PR4-HANDOFF-ULTRACODE-PROMPT.md`. A fresh chat should read that file
and continue from Step 2 (model swap) through Step 9 (PR4 closeout).
