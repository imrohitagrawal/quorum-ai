import { test, expect, Page } from "@playwright/test";
import { boot, goldenCreateResp, goldenCompletedResp } from "../../fixtures/golden-run";

/**
 * #26 — degraded-mode banner on the PRIMARY result view.
 *
 * A production run whose live provider is unavailable silently falls back to
 * local simulation; the response marks that via ``live_count``/``local_count``,
 * but the result view rendered the verdict/synthesis as if real. This gate
 * proves the result view now surfaces a prominent "simulated / degraded" banner
 * whenever any answer was not live — and hides it for a fully-live run.
 *
 * It is RED without the fix: with no #result-degraded element (or one left
 * hidden), the simulated-run assertion fails.
 */

const fulfil = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const costEstimateEnvelope = () => ({
  correlation_id: "corr-degraded-est",
  cost_estimate: goldenCreateResp().cost_estimate,
  model_slots: goldenCreateResp().model_slots,
  reasons: [],
});

async function driveWithCompleted(page: Page, completed: Record<string, unknown>) {
  await boot(page);
  await Promise.all([
    page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(costEstimateEnvelope()))),
    page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
    page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
  ]);
  await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => r.fulfill(fulfil(completed)));
  await page.route(/\/v1\/query-runs$/, (r) =>
    r.request().method() === "POST" ? r.fulfill(fulfil(goldenCreateResp())) : r.continue(),
  );
  await page.getByRole("textbox").first().fill("What are the key metrics for measuring SaaS retention?");
  await page.locator("#run-now").click();
  await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
}

test.describe("degraded-mode result banner (#26)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  test("a fully-SIMULATED run surfaces the degraded banner on the result view", async ({ page }) => {
    // Simulate the prod silent-fallback: every answer came from local simulation.
    const completed = {
      ...goldenCompletedResp(),
      demo_mode: true,
      live_count: 0,
      local_count: 4,
    };
    await driveWithCompleted(page, completed);

    const banner = page.locator("#result-degraded");
    await expect(banner, "the result view must warn when output is simulated").toBeVisible();
    await expect(banner).toContainText(/simulat/i);
    // The banner must be inside the result body (seen with the verdict), not
    // buried in the composer chrome.
    await expect(page.locator(".result-body #result-degraded")).toBeVisible();
  });

  test("a fully-LIVE run does NOT show the degraded banner", async ({ page }) => {
    const completed = {
      ...goldenCompletedResp(),
      demo_mode: false,
      live_count: 4,
      local_count: 0,
    };
    await driveWithCompleted(page, completed);

    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible();
    await expect(
      page.locator("#result-degraded"),
      "a fully-live run must not claim it is simulated",
    ).toBeHidden();
  });

  test("a PARTLY-simulated run surfaces the mixed degraded banner", async ({ page }) => {
    const completed = {
      ...goldenCompletedResp(),
      demo_mode: true,
      live_count: 2,
      local_count: 2,
    };
    await driveWithCompleted(page, completed);

    const banner = page.locator("#result-degraded");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText(/2 of 4/i);
  });
});
