import { test, expect } from "@playwright/test";
import { driveToResult, driveToTranscript } from "../../fixtures/golden-run";
import { stabilize, masks } from "../../fixtures/stabilize";

/**
 * VISUAL REGRESSION baselines (toHaveScreenshot) for the two views where the
 * rendering bugs live — result (verdict + trust) and transcript. Rendered
 * against the golden messy fixture, so the baseline captures how REAL output
 * looks, not clean sim text.
 *
 * This is the human-reviewed half of the gate (Pattern 1 in the e2e-testing
 * skill): a pixel diff a reviewer eyeballs on every PR. It is the primary
 * automated guard for the cramped-transcript layout (#33), which the DOM
 * invariants do not judge (space usage is a visual property).
 *
 * Baselines are environment-sensitive (fonts/AA differ across machines) — per
 * the memory `manual-live-check-is-browser-dependent`, baselines must be
 * generated in CI's own container. Locally, run with `--update-snapshots` once
 * to seed them; CI compares like-for-like. Dynamic regions (timer, run id,
 * cost) are masked so they never flake the diff.
 */

// `stabilize` (freeze + stop timers + hide toasts) and `masks` live in the
// shared fixture so this baseline and the axe scan freeze the page the SAME
// way — a divergent freeze is its own flake source (RB-4).

test.describe("visual snapshots (golden fixture)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "visual baselines are chromium-only");

  test("result view — verdict + trust triangle", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1200 });
    await driveToResult(page);
    await stabilize(page);
    await expect(page).toHaveScreenshot("result-verdict.png", {
      fullPage: true,
      mask: masks(page),
      maxDiffPixelRatio: 0.01,
    });
  });

  test("transcript view — full debate", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1200 });
    await driveToResult(page);
    await driveToTranscript(page);
    await stabilize(page);
    await expect(page).toHaveScreenshot("transcript-full.png", {
      fullPage: true,
      mask: masks(page),
      maxDiffPixelRatio: 0.01,
    });
  });
});
