import { Page, Locator, expect } from "@playwright/test";

/**
 * Shared determinism helpers for specs that must observe a STILL page.
 *
 * Extracted from `tests/invariants/visual-snapshots.spec.ts` and
 * `tests/accessibility/axe-all-views.spec.ts`, which had each grown their own
 * copy of the freeze CSS. A divergent freeze between a spec and the baseline
 * it compares against is itself a flake source: one copy suppressed the caret
 * blink and the other did not, so the same view was "frozen" two different
 * ways depending on which spec looked at it. One definition, imported.
 */

/**
 * Kill every source of sub-second visual motion: transitions, animations, and
 * the text caret. Applied as a stylesheet so it wins over element styles.
 */
export const FREEZE =
  "*,*::before,*::after{transition:none !important;animation:none !important;transition-duration:0s !important;animation-duration:0s !important;caret-color:transparent !important;}";

/**
 * Freeze motion and stop the app's own timers.
 *
 * The live-run poller and the elapsed ticker re-render mid-observation, which
 * is fatal for both a pixel diff and an axe tree walk. Clearing the whole
 * timer id space is blunt but exhaustive — the app allocates its ids from the
 * same counter, and the page is torn down straight after.
 *
 * This is the WEAKER of the two helpers: it hides nothing, so an
 * accessibility scan still sees every element the user would.
 */
export async function freeze(page: Page): Promise<void> {
  await page.addStyleTag({ content: FREEZE });
  await page.evaluate(() => {
    for (let i = 1; i < 100000; i++) {
      clearInterval(i);
      clearTimeout(i);
    }
  });
}

/**
 * `freeze`, plus the extra suppression a PIXEL BASELINE needs.
 *
 * Run toasts are timer-driven overlays whose presence depends on run timing,
 * so baking one into a baseline guarantees a future diff. They are app chrome,
 * not the layout under test.
 *
 * Deliberately NOT used by the axe scan: hiding an element removes it from the
 * accessibility tree, so reusing this there would silently shrink the scan's
 * coverage. Visual specs hide the toast region; the axe spec keeps scanning it.
 */
export async function stabilize(page: Page): Promise<void> {
  await freeze(page);
  await page.addStyleTag({ content: ".toast-region{display:none !important;}" });
  await page.waitForTimeout(100);
}

/**
 * Block until the composer is genuinely usable, or fail fast saying why.
 *
 * The four model slots are painted by `refreshDefaults()`, which runs after
 * `initSession()` — two network round-trips deep into `boot()`. Interacting
 * before they carry values makes the estimate handler resolve display names
 * for empty ids and throw, so every workspace spec must wait here first.
 *
 * The wait is on `data-app-state`, the signal `boot()` stamps on <html> for
 * BOTH outcomes. That matters: the previous version waited on the slots
 * themselves, so a bootstrap that *threw* — the actual failure mode — was
 * indistinguishable from one that was merely slow, and the spec burned its
 * whole test timeout before reporting a generic "timed out" with no cause.
 *
 * (It also passed its options object in the `arg` position —
 * `waitForFunction(fn, arg, options)` — so the intended 15s budget was never
 * applied. `timeout` there "Defaults to `0` - no timeout", and this repo sets
 * no `actionTimeout`, so the wait became UNBOUNDED and could only be killed by
 * the 60s whole-test timeout — which is why it always reported as a generic
 * test timeout rather than as this wait failing.)
 */
export async function waitForComposerReady(page: Page): Promise<void> {
  const state = await page
    .waitForFunction(
      () => document.documentElement.dataset.appState ?? null,
      undefined,
      { timeout: 15_000 },
    )
    .then((handle) => handle.jsonValue());
  expect(
    state,
    "app bootstrap did not succeed — the model slots will never populate",
  ).toBe("ready");
  const slots = page.locator("[data-model-slot]");
  await expect(slots).toHaveCount(4);
  await expect
    .poll(
      () =>
        slots.evaluateAll((els) =>
          els.every(
            (s) => ((s as HTMLInputElement).value ?? "").trim().length > 0,
          ),
        ),
      { timeout: 5_000, message: "model slots never received their default ids" },
    )
    .toBe(true);
}

/**
 * Regions whose text legitimately changes run-to-run (elapsed time, run ids).
 * Masked out of a screenshot so a real layout regression is the only thing
 * that can move the diff.
 */
export function masks(page: Page): Locator[] {
  return [
    page.locator("#live-elapsed"),
    page.locator("[data-run-id]"),
    page.locator("#result-run-id"),
  ];
}
