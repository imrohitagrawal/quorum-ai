# AC-035 Accessibility Evidence (axe drive)

Auditable evidence for **AC-035** ("no critical or serious accessibility
violation remains on the core workflow"). This replaces the ephemeral Slice V
manual drive with a **committed, reproducible** axe test.

## Committed test
`e2e/tests/accessibility/axe-all-views.spec.ts` — a real `@axe-core/playwright`
`AxeBuilder` drive with tags `wcag2a, wcag2aa, wcag21a, wcag21aa`. It:
- reaches **every** SPA view (mocking the backend so the data-driven views
  actually populate), and **asserts a key element is visible before scanning**
  (so it cannot false-pass on an empty/errored view);
- freezes CSS transitions + timers before each scan (mid-animation reads
  produce bogus contrast values otherwise);
- asserts **zero** `critical`/`serious` violations per view, in **both** themes.

Run it: `cd e2e && npx playwright test tests/accessibility/axe-all-views.spec.ts`
(the config's `webServer` self-starts the app on :18085). Chromium is the
reference engine; the spec skips the other projects.

## Result — 0 critical/serious violations, every view × both themes

| View / sub-state | light | dark |
|---|---|---|
| composer (default) | ✅ 0 | ✅ 0 |
| landing | ✅ 0 | ✅ 0 |
| cost-gate — confirm ($0.190) | ✅ 0 | ✅ 0 |
| cost-gate — block ($0.300) | ✅ 0 | ✅ 0 |
| live-run — running (blue) | ✅ 0 | ✅ 0 |
| result — consensus (green verdict band) | ✅ 0 | ✅ 0 |
| result — Run details expanded (receipt + positions) | ✅ 0 | ✅ 0 |
| transcript | ✅ 0 | ✅ 0 |
| result — divided (amber) | ✅ 0 | ✅ 0 |
| error-region — 500 / 409 / 422 / 404 | ✅ 0 | ✅ 0 |

Latest run: **11 test cases passed** (≈13 view-states × 2 themes = 26 axe scans),
0 violations.

## Real defects this drive found and fixed (Slice V, commit 578d537)
These were **not** caught by the pre-existing static-string a11y tests — the
axe drive is what surfaced them:
1. **Dark-mode theming (serious, every view):** an inline `<style>` in
   `workspace.html` hardcoded light `body`/`.panel`/`.topbar` colours,
   overriding the dark tokens → light-mode text colours were rendering on a
   still-light background in "dark" mode. Fixed to `var(--token, #lightFallback)`.
2. **Critical `aria-valid-attr-value` (both themes):** four workflow-step
   `role="tab"` elements had `aria-controls` pointing at non-existent panel
   ids. Removed the dead refs.
3. **Dark contrast (serious):** muted small text (`#8A9099`) on faintly-lit
   dark insets measured 4.3–4.47:1 (just under AA) on the status-pill quiet
   states, the char counter, and the landing caption. Bumped to
   `--text-secondary` in dark.

## Known non-axe follow-up (tracked, non-blocking)
The workflow-progress stepper (`workspace.html` `nav.workflow-progress`) uses
`role="tablist"`/`role="tab"` for what is really a **progress indicator** — it
controls no tabpanels and has no activation handler, so a screen reader
announces "tab, N of 4, selected" for a non-interactive control. This is
**pre-existing** (predates the R1 slices), axe-clean, and out of scope for
Slice V. Durable fix: convert to `role="list"` + `aria-current="step"` (and
drop the roving-tabindex keyboard nav). Tracked for a follow-up PR.
