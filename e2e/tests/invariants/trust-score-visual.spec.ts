import { test, expect, Page } from "@playwright/test";
import {
  boot,
  goldenCreateResp,
  goldenCompletedResp,
  withEvaluation,
  EVAL_MISSING_HIGH_STAKES,
} from "../../fixtures/golden-run";
import { pinGoogleFonts } from "../../fixtures/pinned-fonts";

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
  // W41 (ADR-0149): the same fonts every run, whatever Google answers.
  await pinGoogleFonts(page);
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

        // CHG-031: a second guard beside the 120 px pixel compare below, and a
        // deterministic one: it does not depend on fonts or pixels. It pins
        // every line of the card, exact, in order, and no more or fewer lines.
        // Its limits: it reads innerText, so it does NOT see text added by CSS
        // `::before`/`::after` (the bullets are CSS list markers, so they are
        // not in the lines either), and it DOES see text hidden with
        // `opacity: 0`, which innerText still returns. Text under
        // `display: none` or `visibility: hidden` is not in the lines.
        // Red if: any line's wording changes, a line is added, removed or
        // reordered (e.g. "Structural checks passed" -> "Structural check passed"
        // in app.js).
        const cardLines = async () =>
          (await surface.innerText())
            .split("\n")
            .map((line) => line.trim())
            .filter((line) => line !== "");
        await expect
          .poll(cardLines)
          .toEqual([
            "Not verified — these are automated structural checks, not a fact-check.",
            "Structural checks passed — citations were not verified against their sources.",
            "Some citation markers did not point at a source on this run.",
            "Not every answer that came back carried a primary source.",
            "This question needed a safety caveat and the synthesis did not include one.",
          ]);

        await expect(surface).toHaveScreenshot(`trust-score-${theme}-${width}.png`, {
          maxDiffPixels: 120,
        });
      });
    }
  }
});
