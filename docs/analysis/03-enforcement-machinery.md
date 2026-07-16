# Category 3 — Enforcement machinery (built + proven red this session)

The below-the-line gates that make the principles automatic. Unlike the rest of
this analysis, **this category is already implemented** — the files below exist,
run, and were proven RED against current code.

## What was built

| Sub-module | File | Purpose | Mechanism | Enforcement gate | Status |
|-----------|------|---------|-----------|------------------|--------|
| Golden realistic fixture | `e2e/fixtures/golden-run.ts` | One canonical blob of messy real-shaped output (line-start `##` headings, `**bold**`, ordered lists, bare URLs, a ~450-word answer, an empty-citation slot) mirroring the OpenAPI QueryRun* schema | Test data | Feeds every invariant + snapshot | **DONE** |
| Rendering invariants | `e2e/tests/invariants/rendering-invariants.spec.ts` | Walks the whole rendered DOM: (a) no raw Markdown, (b) no horizontal overflow, (c) monotonic elapsed across a decreasing poll sequence | Playwright test | CI (non-blocking until fixes land) | **DONE — RED-PROVEN** |
| Visual snapshots | `e2e/tests/invariants/visual-snapshots.spec.ts` | `toHaveScreenshot` baselines for result + transcript (masked dynamic regions) — the human-reviewed guard, primary catch for #33 | Playwright visual regression | CI once baselines seeded | **DONE — baseline seed pending** |
| Real-integration smoke | `e2e/tests/invariants/real-integration-smoke.spec.ts` | Drives the REAL sim backend end-to-end with NO `page.route` mock; asserts a run reaches a populated verdict | Playwright test | CI (blocking) | **DONE — PASSING** |
| CI wiring | `.github/workflows/e2e.yml` | Smoke added to the blocking run; invariants added as a non-blocking step | GitHub Actions (tracked = shared) | The shared gate | **DONE** |

## Prove-red evidence (recorded this session, against current `app.js`/`app.css`)

Running `rendering-invariants.spec.ts` on chromium: **3 failed, 1 passed.**

- **#30 (no raw Markdown) — RED.** `**`/`## ` leaked into rendered text on
  every genuine provider-**prose** surface: `.result-verdict-text`
  ("## Recommendation / **Proceed**"), `.result-verdict-caveat`
  ("**High-stakes:**"), `.result-trust-caption`, `.result-positions-cell`
  ("**Position:**"), `.result-synth-body`, `.callout-high-stakes .callout-body`,
  the live-debate `.live-round-body`, and the transcript
  `.transcript-opening-body` / `.transcript-round-body`. This confirms the blast
  radius across the result, transcript, and live-debate views.
- **Greenability was hardened after adversarial review.** Source-citation
  titles/labels are provider *metadata*, not prose — a prose formatter must not
  (and structurally cannot) render bold inside a link label. Seeding `**` there
  would make the gate **non-greenable**, so the fixture now keeps source titles
  plain text; the gate flags only prose surfaces. Verified: **zero**
  `result-source-label` / `source-list` offenders remain after the fix.
- **#29 (monotonic timer) — RED.** Sampled `#live-elapsed` across a scripted
  poll sequence `12s → 3s → 4s → 5s → 6s`: samples `[12000,…,3300,…]`, a **8700ms
  backward jump** (> the 150ms parse tolerance).
- **no-horizontal-overflow — PASSED** (correct: today's layout does not overflow;
  #33 is *under-use* of width, caught by the visual snapshot, not this invariant).

Crucially, the gate is **greenable**: the already-formatted answer surface
(`.answer-section-body.q-prose`) produced **zero** false positives, and the
fixture uses only valid Markdown (line-start headings + inline bold) on genuine
prose surfaces — which a correct #30 fix provably converts. The fix is not "route
everything through the block formatter" but **route each surface through the
appropriate renderer**: the block formatter (`formatAnswerText`) for prose blocks
(verdict/synthesis/critiques/transcript answers/caveat), and an *inline* renderer
(`mdInline`) for inline/cell surfaces (the positions cell). Source titles stay
plain. With that fix every flagged surface loses its raw markers and the test
turns GREEN.

**Honest coverage limits (from the adversarial review):**
- Ordered-list markers are deliberately NOT asserted (browser `<ol>` numbers are
  `::marker` pseudo-elements, not text nodes; asserting `1.` risks a
  non-greenable gate). A fix that converts `**`/`##` but not lists would pass here
  — lists are covered by the visual snapshot instead.
- `renderStubSource` titles (`app.js:3369`, only for `local_simulation` /
  `fallback_search` providers) are not exercised — the golden sources use
  `openrouter_search`. A follow-up fixture variant should cover the stub path.

## Why the invariants are wired NON-BLOCKING today

They are RED on purpose (the bugs are unfixed). Making them blocking now would
freeze `main`. So `e2e.yml` runs them under `continue-on-error: true`, surfacing
the red in logs without blocking merges. **The PR that fixes #29/#30/#33 must
delete that `continue-on-error` line** — flipping the gate to hard is the
enforcement handoff, and it can only be done honestly once the tests pass. The
smoke, which passes now, is already blocking.

## Follow-ups to fully close the machinery

1. **Seed visual-snapshot baselines in CI.** `toHaveScreenshot` needs Linux
   baselines generated in the CI container (mac baselines are platform-suffixed
   and unused on ubuntu, per memory `manual-live-check-is-browser-dependent`).
   Run once with `--update-snapshots`, commit the `*-linux.png` files, add the
   spec to the `e2e.yml` run, mask timer/run-id/cost regions.
2. **Land #30/#29/#33 fixes and flip the invariants to blocking** (remove
   `continue-on-error`). #30 = route all provider text through one `renderProse()`
   renderer (which already HTML-escapes, so no XSS regression); #29 = monotonic
   clamp on the elapsed base; #33 = widen the transcript container / responsive
   columns.
3. **Optional local speed-up:** a `.claude/settings.json` hook that runs the
   invariants on UI-file changes — but note `.claude/` is gitignored, so it is
   LOCAL-ONLY, never a substitute for the CI gate (see `04-mechanism-map.md`).

## Note on backend-dimension gates (not built this run)

The search (#31/#32), cost (#18–#20), observability (#26), and persistence (#27)
dimensions need their own gates (contract test, cost unit tests, degraded-mode
signal, post-deploy persistence smoke). They are specified in the ledger and
mechanism map but were out of scope for this run's UI-focused harness.
