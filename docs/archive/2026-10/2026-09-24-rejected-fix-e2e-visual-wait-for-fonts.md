# Rejected fix: the visual baselines wait for the page's web fonts (PR #500, closed 2026-09-24)

Archived on 2026-10-16 from branch `fix/e2e-visual-wait-for-fonts` (commit `650ba4f`), so the branch
can be deleted without losing it (ADR-0168, CHG-047). **Nothing here is active.** Review rejected the
fix because its stated cause was false.

The closing note on PR #500, verbatim:

> **Closing: the stated cause is false, so this is not a fix.** Found by review (two lenses) and
> reproduced by me from the failing run's own trace (run 35978152640, `trust-score — dark @ 1440`,
> `trace.zip`):
>
> - the three font files (Newsreader, Geist, Geist Mono) all returned HTTP 200 at 09:08:26.2Z, at page
>   load, minutes before the capture;
> - Playwright's screenshotter logged `waiting for fonts to load...` / `fonts loaded` before each
>   capture, because `toHaveScreenshot` already awaits `document.fonts.ready`.
>
> So the added wait cannot change what CI captures, and the commit body's "a screenshot taken before
> the last weight file lands" is contradicted by the evidence (all Geist weights also ship in one
> variable-font file). The one green CI run on this branch is the flake not firing (2 green, 3 red
> today across branches, all with fonts loaded), not a fix.
>
> **What is true:** on 2026-09-24 the visual lane fails nondeterministically on one line's tail of the
> trust-score surface (589 and 644 pixels, ratio 0.01, against `maxDiffPixels: 120`), on `main` itself
> (re-run of 42cd965) as much as on branches. The rendering shift's cause is UNKNOWN. Whether the
> tolerance should move is an owner decision (a threshold), recorded in the session handoff, not taken
> here.

The note ends "Branch deleted."; the branch was in fact still on GitHub until this archive was made.

The patch, against its merge base `42cd965`:

```diff
diff --git a/e2e/fixtures/stabilize.ts b/e2e/fixtures/stabilize.ts
index 6642379..3b49c3d 100644
--- a/e2e/fixtures/stabilize.ts
+++ b/e2e/fixtures/stabilize.ts
@@ -53,9 +53,35 @@ export async function freeze(page: Page): Promise<void> {
 export async function stabilize(page: Page): Promise<void> {
   await freeze(page);
   await page.addStyleTag({ content: ".toast-region{display:none !important;}" });
+  await waitForFonts(page);
   await page.waitForTimeout(100);
 }
 
+/**
+ * Block until every web font the page asked for has finished loading.
+ *
+ * The workspace loads Geist (400 to 700), Geist Mono and Newsreader from
+ * Google Fonts with `display=swap` (workspace.html, the `<link>` in `<head>`).
+ * `swap` paints text immediately in whatever is available and re-paints when
+ * each weight file arrives, so a screenshot taken before the last file lands
+ * captures a SYNTHESISED bold or a fallback face on some lines and the real
+ * one on others. Measured 2026-09-24: three CI runs in a row (two on a
+ * branch that changed no markup, one re-run of a previously green `main`
+ * commit) failed `trust-score-visual.spec.ts` on ONE bold line by 589 and
+ * 644 pixels, while the seed workflow on the same day reproduced the
+ * committed baselines byte-exact — the same page, rendered with the fonts
+ * either all present or not yet. `document.fonts.ready` resolves once every
+ * pending font load has settled, which is the state the baselines were
+ * seeded in.
+ *
+ * Bounded: `document.fonts.ready` settles on failure as well as success, so
+ * an unreachable font host cannot hang the capture; Playwright's expect
+ * timeout still bounds the whole step.
+ */
+export async function waitForFonts(page: Page): Promise<void> {
+  await page.evaluate(() => document.fonts.ready.then(() => undefined));
+}
+
 /**
  * Block until the composer is genuinely usable, or fail fast saying why.
  *
diff --git a/e2e/tests/invariants/trust-score-visual.spec.ts b/e2e/tests/invariants/trust-score-visual.spec.ts
index 36fbc8f..4b1b8c4 100644
--- a/e2e/tests/invariants/trust-score-visual.spec.ts
+++ b/e2e/tests/invariants/trust-score-visual.spec.ts
@@ -6,6 +6,7 @@ import {
   withEvaluation,
   EVAL_MISSING_HIGH_STAKES,
 } from "../../fixtures/golden-run";
+import { stabilize } from "../../fixtures/stabilize";
 
 /**
  * FR-016 (S3) — trust-score element visual baselines.
@@ -27,20 +28,9 @@ import {
  * This is also the repo's first dark-theme pixel coverage.
  */
 
-const FREEZE =
-  "*,*::before,*::after{transition:none !important;animation:none !important;transition-duration:0s !important;animation-duration:0s !important;caret-color:transparent !important;}";
-
-async function stabilize(page: Page) {
-  await page.addStyleTag({ content: FREEZE });
-  await page.evaluate(() => {
-    for (let i = 1; i < 100000; i++) {
-      clearInterval(i);
-      clearTimeout(i);
-    }
-  });
-  await page.addStyleTag({ content: ".toast-region{display:none !important;}" });
-  await page.waitForTimeout(100);
-}
+// `stabilize` is the shared fixture (freeze + stop timers + hide toasts +
+// wait for web fonts). This spec used to carry its own copy, which the
+// fixture's own header names as a flake source; one definition, imported.
 
 const fulfil = (body: unknown, status = 200) => ({
   status,
```
