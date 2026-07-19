# Category 3 — Enforcement machinery (built + proven red this session)

The below-the-line gates that make the principles automatic. Unlike the rest of
this analysis, **this category is already implemented** — the files below exist,
run, and were proven RED against current code.

## What was built

| Sub-module | File | Purpose | Mechanism | Enforcement gate | Status |
|-----------|------|---------|-----------|------------------|--------|
| Golden realistic fixture | `e2e/fixtures/golden-run.ts` | One canonical blob of messy real-shaped output (line-start `##` headings, `**bold**`, ordered lists, bare URLs, a ~450-word answer, an empty-citation slot) mirroring the OpenAPI QueryRun* schema | Test data | Feeds every invariant + snapshot | **DONE** |
| Rendering invariants | `e2e/tests/invariants/rendering-invariants.spec.ts` | Walks the whole rendered DOM: (a) no raw Markdown, (b) no horizontal overflow, (c) monotonic elapsed across a decreasing poll sequence | Playwright test | CI — **BLOCKING** | **DONE — RED-PROVEN, now GREEN + hard** |
| Visual snapshots | `e2e/tests/invariants/visual-snapshots.spec.ts` | `toHaveScreenshot` baselines for result + transcript (masked dynamic regions) — the human-reviewed guard, primary catch for #33 | Playwright visual regression | CI — **BLOCKING** (Linux baselines seeded by `seed-visual-baselines.yml` and committed) | **DONE** |
| Real-integration smoke | `e2e/tests/invariants/real-integration-smoke.spec.ts` | Drives the REAL sim backend end-to-end with NO `page.route` mock; asserts a run reaches a populated verdict | Playwright test | CI — **BLOCKING** | **DONE — PASSING** |
| CI wiring | `.github/workflows/e2e.yml` | Smoke, rendering invariants and visual snapshots all run as **blocking** steps — `continue-on-error` appears nowhere in the file | GitHub Actions (tracked = shared) | The shared gate | **DONE** |

## Prove-red evidence (recorded this session, against current `app.js`/`app.css`)

Running `rendering-invariants.spec.ts` on chromium: **3 failed, 1 passed.**

- **#30 (no raw Markdown) — RED.** `**`/`## ` leaked into rendered text on
  every genuine provider-**prose** surface: `.result-verdict-text`
  ("## Recommendation / **Proceed**"), `.result-verdict-caveat`
  ("**High-stakes:**"), `.result-trust-caption`, `.result-positions-cell`
  ("**Position:**"), `.result-synth-body`, `.callout-high-stakes .callout-body`,
  and the transcript `.transcript-opening-body` / `.transcript-round-body`.
  The `.live-round-body` (app.js:1579) content is ALSO flagged because the
  populated live-debate DOM persists in `#main-content` after the run — so the
  walk catches it incidentally. It is NOT RED-proven via a dedicated live-run
  driver (there is none); treat 1579's coverage as opportunistic, not asserted.
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

**Measured determinism (adversarial reviewer ran the specs 3×, not predicted):**
the three runs were bit-identical — `worstDrop = 8700ms` (12000→3300) on runs
1/2/3, backward jump detected 3/3, `#30` failing 3/3, overflow passing 3/3. The
real-integration smoke ran in **1.2–2.4s** vs its 90s verdict budget (~36×
headroom; sim `stage_delay_ms`=5ms). Two false-green holes the reviewer found
were then fixed: the timer test now asserts it witnessed the ~12s pre-drop value,
and `driveToResult` waits on a late-rendered surface before the markdown walk.

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

**Greenability — empirically proven (not just argued).** A throwaway fix that
routes the flagged prose surfaces through `formatAnswerText` was applied to
`app.js`, the gate re-run, then reverted (app.js left pristine). Result: **#30
RESULT and #30 TRANSCRIPT flipped RED → GREEN**, while **#29 (timer) stayed RED**
— proving the gate both *can* go green on a correct fix AND *discriminates*
(it is not a blanket always-fail). This is the "perform, don't preach" evidence
that the gate is honest.

**EXACT coverage (do NOT read the gate as "no raw Markdown, full stop").** A
performing adversarial hunt (probes injected one marker at a time, driven through
the real UI) proved the gate's true reach. It now asserts **six** constructs, all
greenable via the real renderer (`mdInline`/`formatAnswerText` convert each) —
verified against `RAW_MARKDOWN_PATTERNS` in `e2e/fixtures/golden-run.ts`:
`**bold**`, line-start `#{1,6}` heading, `` `inline code` ``, `[link](url)`
(`](`), `_underscore_` / `__underscore__` emphasis, and line-start `>` blockquote.
It is a snapshot of `#main-content` text nodes, and it skips any node inside
`<code>`/`<pre>` — literal markers in inline code (`__init__`) are *correct*, not
a bypassed formatter.

**Widened after the formatter extension (was a documented gap).** Underscore
emphasis and blockquotes originally rendered raw even in the *formatted* answer
surfaces, because `mdInline` handled only asterisk emphasis and `formatAnswerText`
had no blockquote block — asserting them then would have been **non-greenable**.
The #30 fix extended the formatter, so the gate was widened to cover both; the
inline-code exemption keeps it honest.

**Not asserted — real gaps, documented not hidden:**
- **Ordered/bulleted list markers** (`1.`, `- `, `* `) are not asserted (a correct
  `<ol>`/`<ul>` exposes markers as `::marker` pseudo-elements, not text; a partial
  fix that skips lists would pass). Lists are covered by the visual snapshot.
- **Scope:** the walk covers `#main-content` (where provider prose renders). App
  chrome (toasts, header, `aria-live`, error banners) is app-authored text, not
  provider markdown — intentionally out of scope.
- **Timing:** single post-hydration snapshot; streamed/late renders after the walk
  are not covered (the anchored waits cover result/transcript hydration only).
- `renderStubSource` titles (`app.js:3369`, `local_simulation`/`fallback_search`
  providers) are not exercised — golden sources use `openrouter_search`.

## The invariants are BLOCKING (the enforcement handoff is DONE)

> **Corrected 2026-07-19 (finding EN-6).** This section previously said the
> invariants were wired NON-BLOCKING. That is **stale and was false** — a stale
> "non-blocking" note undercuts a gate that is in fact hard, and teaches readers
> to discount it. Verified against the actual workflow: **`continue-on-error`
> appears nowhere in `.github/workflows/e2e.yml`** (only inside two header/step
> comments describing its removal), and the two steps are literally named
> `Run UI rendering invariants (BLOCKING)` and `Run visual snapshots (BLOCKING)`.

The original reasoning, kept for the record: the invariants started RED on
purpose (#29/#30/#33 were unfixed) and making them blocking then would have
frozen `main`, so they ran under `continue-on-error: true` — red surfaced in logs
without blocking merges. **That handoff has since happened.** The #29 (monotonic
timer) and #30 (route every provider-prose surface through the markdown renderer,
plus the underscore/blockquote formatter extension) fixes landed, the specs went
green, and `continue-on-error` was deleted. The visual-snapshot baselines were
seeded as `*-linux.png` in the CI container by `seed-visual-baselines.yml`,
committed, and are now compared like-for-like — so that step is blocking too.
Every invariant step, plus the real-integration smoke, now fails the build.

**Consequence for anyone editing the UI:** a red rendering invariant or a pixel
diff is a real regression and blocks the merge. It cannot be waved through; fix
the defect, or change the baseline deliberately with a human review of the new
screenshot.

## Follow-ups to fully close the machinery

1. ~~**Seed visual-snapshot baselines in CI.**~~ **DONE** — `seed-visual-baselines.yml`
   generated the Linux baselines in the CI container (mac baselines are
   platform-suffixed and unused on ubuntu, per memory
   `manual-live-check-is-browser-dependent`), the `*-linux.png` files are
   committed, the spec runs in `e2e.yml`, and timer/run-id/cost regions are
   masked. Remaining: `maxDiffPixels` is not yet set from a **measured** noise
   floor — re-run the unchanged spec N≥10× in the CI container and set the
   threshold just above the observed max diff (`DAY-ONE-PROMPT.md` §4a).
2. ~~**Land #30/#29/#33 fixes and flip the invariants to blocking.**~~ **DONE** —
   #30 routed each prose surface through the appropriate renderer (block
   `formatAnswerText` / inline `mdInline`, both already HTML-escaping, so no XSS
   regression; source titles stay plain) and extended the formatter for
   underscore emphasis + blockquotes; #29 clamped the elapsed base monotonic;
   #33 widened the transcript container. `continue-on-error` was then removed.
3. **Optional local speed-up:** a `.claude/settings.json` hook that runs the
   invariants on UI-file changes — but note `.claude/` is gitignored, so it is
   LOCAL-ONLY, never a substitute for the CI gate (see `04-mechanism-map.md`).

## Note on backend-dimension gates (not built this run)

The search (#31/#32), cost (#18–#20), observability (#26), and persistence (#27)
dimensions need their own gates (contract test, cost unit tests, degraded-mode
signal, post-deploy persistence smoke). They are specified in the ledger and
mechanism map but were out of scope for this run's UI-focused harness.
