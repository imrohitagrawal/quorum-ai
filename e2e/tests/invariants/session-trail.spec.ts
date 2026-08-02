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

  // STILL REMOVED: "the trail is capped at 10 entries". #126 fixed the bug
  // documented below (a follow-up run now appends instead of replacing — see
  // "a follow-up run (not Start fresh) appends to the trail instead of
  // replacing it"), so SESSION_TRAIL_CAP is no longer unreachable dead code
  // in principle. A dedicated 11-distinct-run cap test is still not added
  // here: it needs 11 distinct create+complete route cycles (expensive, and
  // out of #126's scope, which was the single-entry defect, not the cap).
  // Leaving this noted rather than silently dropped, per #126's own finding
  // that WP-F's original "if the trail is ever changed to accumulate, add a
  // real test with it" condition is now true.

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

  test("'Start fresh' followed by a new run replaces the trail with the new entry", async ({ page }) => {
    await driveWithCompleted(page, goldenCompletedResp());
    await expect(page.locator(".session-trail-entry")).toHaveCount(1);
    // Navigate back to composer via "Start fresh" and start another run — the
    // old entry should be replaced by the new one (Start fresh explicitly
    // clears the trail; this is a genuinely new session thread).
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

  // #126: a FOLLOW-UP run (the "Follow up" mode is the default on the result
  // view's next-run panel — distinct from "Start fresh") is explicitly the
  // SAME session thread continuing, not a new one. Before this fix,
  // `clearSessionTrail()` fired unconditionally on every run creation
  // (app.js, inside the submit handler), so a follow-up silently dropped the
  // prior entry exactly like Start fresh did — the trail could never hold
  // more than 1 entry regardless of which button the user clicked.
  //
  // The two prior tests above use the SAME golden `query_run_id` for every
  // run, so `appendSessionTrailEntry`'s runId-dedupe alone would keep the
  // count at 1 even with the clear removed — they cannot distinguish
  // "cleared" from "deduped-and-replaced". This test uses two DISTINCT run
  // ids so only the clear-on-every-run bug can collapse the count.
  test("a follow-up run (not Start fresh) appends to the trail instead of replacing it", async ({ page }) => {
    await boot(page);
    const runIds = [
      "11111111-1111-4111-8111-111111111111",
      "22222222-2222-4222-8222-222222222222",
    ];
    let createCount = 0;
    await Promise.all([
      page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(costEstimateEnvelope()))),
      page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
      page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
    ]);
    await page.route(/\/v1\/query-runs$/, (r) => {
      if (r.request().method() !== "POST") return r.continue();
      const id = runIds[Math.min(createCount, runIds.length - 1)];
      createCount += 1;
      return r.fulfill(fulfil({ ...goldenCreateResp(), query_run_id: id, correlation_id: `corr-${id}` }));
    });
    await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => {
      const url = r.request().url();
      const id = runIds.find((rid) => url.includes(rid)) ?? runIds[0];
      return r.fulfill(fulfil({ ...goldenCompletedResp(), query_run_id: id, correlation_id: `corr-${id}` }));
    });

    await page.getByRole("textbox").first().fill("First question here?");
    await page.locator("#run-now").click();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
    await expect(page.locator(".session-trail-entry")).toHaveCount(1);

    // "Follow up" is the DEFAULT next-run mode (not "Start fresh") — click
    // straight through to the composer without touching #result-startfresh.
    await page.locator("#result-next-run").click();
    await expect(page.locator("#query-text")).toBeVisible({ timeout: 10000 });
    await page.getByRole("textbox").first().fill("Second question here?");
    await page.locator("#run-now").click();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });

    // Both entries must be present — the follow-up continues the same
    // session thread, it does not start a new one.
    await expect(page.locator(".session-trail-entry")).toHaveCount(2);
    const questions = await page.locator(".session-trail-question").allTextContents();
    expect(questions.some((q) => q.includes("First question here?"))).toBe(true);
    expect(questions.some((q) => q.includes("Second question here?"))).toBe(true);
  });
});
