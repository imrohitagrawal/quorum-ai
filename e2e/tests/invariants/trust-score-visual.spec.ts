import { test, expect, Page } from "@playwright/test";
import {
  boot,
  goldenCreateResp,
  goldenCompletedResp,
  withEvaluation,
  EVAL_MISSING_HIGH_STAKES,
} from "../../fixtures/golden-run";

/**
 * FR-016 (S3) — trust-score element visual baselines.
 *
 * BLOCKING alongside visual-snapshots (the repo forbids continue-on-error in
 * e2e.yml). Its baselines are OPERATOR-GATED: seed-visual-baselines.yml (glob)
 * generates the PNGs and a HUMAN reviews every one before merge (§5.3). Until
 * the operator seeds and accepts them, this compare is red — that is the
 * intended gate, not an oversight.
 *
 * Why `maxDiffPixels`, not a ratio: the repo's other visual gate uses
 * `maxDiffPixelRatio: 0.01` with `fullPage: true`, which on the 1440×2943 result
 * view tolerates ~42k changed pixels — a 240×80 chip can render wrong, or vanish,
 * and stay green. A small per-element budget catches that. And because a
 * *vanished* surface would trivially pass a screenshot of an empty box, we also
 * assert non-visually that it is visible and non-empty, so a disappearance fails
 * DETERMINISTICALLY rather than statistically.
 *
 * This is also the repo's first dark-theme pixel coverage.
 */

const FREEZE =
  "*,*::before,*::after{transition:none !important;animation:none !important;transition-duration:0s !important;animation-duration:0s !important;caret-color:transparent !important;}";

async function stabilize(page: Page) {
  await page.addStyleTag({ content: FREEZE });
  await page.evaluate(() => {
    for (let i = 1; i < 100000; i++) {
      clearInterval(i);
      clearTimeout(i);
    }
  });
  await page.addStyleTag({ content: ".toast-region{display:none !important;}" });
  await page.waitForTimeout(100);
}

const fulfil = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

async function driveToTrustSurface(page: Page) {
  await boot(page);
  await Promise.all([
    page.route("**/v1/query-runs/estimate", (r) =>
      r.fulfill(fulfil({ correlation_id: "c", cost_estimate: goldenCreateResp().cost_estimate, model_slots: goldenCreateResp().model_slots, reasons: [] })),
    ),
    page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
    page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
  ]);
  const completed = withEvaluation(goldenCompletedResp(), EVAL_MISSING_HIGH_STAKES);
  await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => r.fulfill(fulfil(completed)));
  await page.route(/\/v1\/query-runs$/, (r) =>
    r.request().method() === "POST" ? r.fulfill(fulfil(goldenCreateResp())) : r.continue(),
  );
  await page.getByRole("textbox").first().fill("What are the key metrics for measuring SaaS retention?");
  await page.locator("#run-now").click();
  await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
}

test.describe("trust-score visual baselines (FR-016, advisory)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "visual baselines are chromium-only");

  for (const theme of ["light", "dark"] as const) {
    for (const width of [375, 768, 1440] as const) {
      test(`trust-score — ${theme} @ ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 1200 });
        await driveToTrustSurface(page);
        await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
        await stabilize(page);

        const surface = page.locator("#result-trust-score");
        // Deterministic guard: a vanished surface must fail here, not silently
        // pass an empty screenshot.
        await expect(surface).toBeVisible();
        await expect(surface).not.toBeEmpty();

        await expect(surface).toHaveScreenshot(`trust-score-${theme}-${width}.png`, {
          maxDiffPixels: 120,
        });
      });
    }
  }
});
