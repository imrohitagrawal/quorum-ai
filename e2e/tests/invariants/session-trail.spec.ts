import { test, expect, Page } from "@playwright/test";
import {
  boot,
  goldenCreateResp,
  goldenCompletedResp,
} from "../../fixtures/golden-run";

const fulfil = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const costEstimateEnvelope = () => ({
  correlation_id: "corr-trail-est",
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

/** Navigate from result view back to the composer. Clicks "Start fresh"
    then "Review & run" so we land at the composer. */
async function goBackToComposer(page: Page) {
  await page.locator("#result-startfresh").click();
  await page.locator("#result-next-run").click();
  await expect(page.locator("#query-text")).toBeVisible({ timeout: 10000 });
}

test.describe("PR8 — Conversation trail UI", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  test("a completed run adds an entry to the trail panel", async ({ page }) => {
    await driveWithCompleted(page, goldenCompletedResp());

    const list = page.locator("#session-trail-list");
    await expect(list, "trail list must be visible after a completed run").toBeVisible();
    await expect(list).not.toBeHidden();
    const entries = list.locator(".session-trail-entry");
    await expect(entries).toHaveCount(1);
    const q = await entries.first().locator(".session-trail-question").textContent();
    expect(q).toContain("What are the key metrics");
  });

  test("a simulated run gets a muted trail entry", async ({ page }) => {
    await driveWithCompleted(page, {
      ...goldenCompletedResp(),
      demo_mode: true,
      live_count: 0,
      local_count: 4,
    });

    const entry = page.locator(".session-trail-entry");
    await expect(entry).toHaveCount(1);
    await expect(entry).toHaveClass(/session-trail-entry--muted/);
    const status = await entry.locator(".session-trail-status").textContent();
    expect(status?.toLowerCase()).toBe("simulated");
  });

  test("a failed run gets a muted trail entry", async ({ page }) => {
    await driveWithCompleted(page, {
      ...goldenCompletedResp(),
      demo_mode: false,
      live_count: 0,
      local_count: 0,
      status: "failed",
      failed_steps: ["synthesis"],
    });

    const entry = page.locator(".session-trail-entry");
    await expect(entry).toHaveCount(1);
    await expect(entry).toHaveClass(/session-trail-entry--muted/);
  });

  test("clicking a trail entry restores the result view", async ({ page }) => {
    await driveWithCompleted(page, goldenCompletedResp());
    // Click the trail entry and wait for the result to re-render.
    await page.locator(".session-trail-entry").first().click();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 10000 });
    // The trail must still be visible after restore.
    await expect(page.locator("#session-trail-list")).toBeVisible();
    await expect(page.locator(".session-trail-entry")).toHaveCount(1);
  });

  // REMOVED: "the trail is capped at 10 entries". It could not fail, and this
  // spec is now in the BLOCKING lane, so it was a gate enforcing nothing.
  //
  // Proved by mutation, twice over. Deleting the cap branch outright
  // (app.js:3882) left it green, because the assertion was `count <= 10` while
  // `count` is always 1: every run calls clearSessionTrail() (app.js:5823,
  // and again via "Start fresh" at :6903), AND appendSessionTrailEntry dedupes
  // by runId (app.js:3880) while the golden fixture returns the same
  // query_run_id every time. Two independent reasons the trail cannot grow.
  //
  // So SESSION_TRAIL_CAP is unreachable dead code today: the trail is REPLACED
  // per run, never appended across runs. Reaching it from a test needs either a
  // test-only hook in production JS or distinct per-run ids in the shared
  // golden fixture — neither is worth it for dead code, and a fake gate is
  // worse than no gate. The remaining cases in this file are real: disabling
  // the clear at app.js:6903 fails "'Start fresh' clears the session trail".
  //
  // WP-F owns this surface. Decide there whether the cap should exist at all;
  // if the trail is ever changed to accumulate, add a real test with it.

  test("long questions are truncated to 80 characters", async ({ page }) => {
    const longQuestion = "A".repeat(200);
    await boot(page);
    await Promise.all([
      page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(costEstimateEnvelope()))),
      page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
      page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
    ]);
    await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => r.fulfill(fulfil(goldenCompletedResp())));
    await page.route(/\/v1\/query-runs$/, (r) =>
      r.request().method() === "POST" ? r.fulfill(fulfil(goldenCreateResp())) : r.continue(),
    );
    await page.getByRole("textbox").first().fill(longQuestion);
    await page.locator("#run-now").click();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
    const text = await page.locator(".session-trail-question").first().textContent();
    expect(text!.length).toBeLessThanOrEqual(81); // 80 + ellipsis
    expect(text).toContain("…");
  });

  test("'Start fresh' clears the session trail", async ({ page }) => {
    await driveWithCompleted(page, goldenCompletedResp());
    await expect(page.locator(".session-trail-entry")).toHaveCount(1);
    // Click "Start fresh".
    await page.locator("#result-startfresh").click();
    // The trail list must now be hidden (empty after clear).
    await expect(page.locator("#session-trail-list")).toBeHidden();
  });

  test("starting a new run replaces the trail with the new entry", async ({ page }) => {
    await driveWithCompleted(page, goldenCompletedResp());
    await expect(page.locator(".session-trail-entry")).toHaveCount(1);
    // Navigate back to composer and start another run — the old entry should be
    // replaced by the new one (trail is not permanently hidden, just refreshed).
    await goBackToComposer(page);
    await page.getByRole("textbox").first().fill("Second question here?");
    await page.locator("#run-now").click();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
    // Trail must show exactly one entry (the new run), not the old one.
    await expect(page.locator("#session-trail-list")).toBeVisible();
    await expect(page.locator(".session-trail-entry")).toHaveCount(1);
    const q = await page.locator(".session-trail-question").first().textContent();
    expect(q).toContain("Second question here?");
  });
});
