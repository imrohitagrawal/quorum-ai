import { test, expect, Page } from "@playwright/test";

/**
 * Issue #117 — the readiness banner must not FLASH and reflow.
 *
 * The workspace rendered readiness twice on load: once from the
 * server-rendered `window.LIVE_READINESS` seed, then again from `GET /ready`.
 * The credential probe runs on a background thread at startup (#112), so a
 * page served inside that window carries a seed that can disagree with the
 * verdict landing moments later. Measured on the issue: a healthy deployment
 * with a momentarily-stale seed flashed "Live execution is unavailable" and
 * then reflowed 137px on desktop, 319px on mobile.
 *
 * WHY THIS SPEC IS SHAPED LIKE THIS. `readiness-banner.spec.ts`'s `live` case
 * uses `toBeHidden()`, which AUTO-RETRIES — so it cannot observe a transient
 * flash by construction, and it stayed green throughout the defect. Catching
 * a state that exists for ~100ms needs a recorder that runs during the paint,
 * not an assertion sampled after it. So a `MutationObserver` is installed via
 * `addInitScript` — before app.js executes — and counts every transition of
 * the banner into a visible state. The assertion is on that COUNT.
 *
 * The suppression is only half the contract, so both halves are asserted: a
 * deployment that is genuinely offline must still show the banner, or "never
 * flash" would be trivially satisfied by never rendering it at all.
 *
 * WHICH TEST BITES, MEASURED. Removing the suppression turns the FIRST test
 * red and leaves the other two green. That is expected and stated rather than
 * implied: the second and third are the no-false-fire partners — they exist
 * so the fix cannot satisfy the first by suppressing the banner out of
 * existence — not additional guards on the defect itself.
 */

type Readiness = {
  state: string;
  reasons?: string[];
  catalog_drift_ids?: string[];
  global_spend_ceiling_reached?: boolean;
};

/** Install the recorder BEFORE app.js runs, so nothing is missed. */
async function recordBannerVisibility(page: Page): Promise<void> {
  await page.addInitScript(() => {
    (window as any).__bannerShows = 0;
    const start = () => {
      const el = document.getElementById("readiness-banner");
      if (!el) return;
      const visible = () => !el.hidden && getComputedStyle(el).display !== "none";
      let wasVisible = visible();
      if (wasVisible) (window as any).__bannerShows++;
      new MutationObserver(() => {
        const now = visible();
        // Count only OFF -> ON edges: that is what a user perceives as the
        // banner appearing, and it is what a flash-then-retract produces.
        if (now && !wasVisible) (window as any).__bannerShows++;
        wasVisible = now;
      }).observe(el, { attributes: true, attributeFilter: ["hidden", "style", "class"] });
    };
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", start, { once: true });
    } else {
      start();
    }
  });
}

/**
 * Serve /ui with a DISAGREEING seed: the page is stamped offline while
 * /ready answers `live`. That is the exact production race #112 describes.
 */
async function bootWithSeedDisagreement(
  page: Page,
  seedState: string,
  readyState: Readiness,
): Promise<void> {
  await recordBannerVisibility(page);

  await page.route("**/ready", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "ready",
        environment: "test",
        live_readiness: { reasons: [], catalog_drift_ids: [], ...readyState },
      }),
    }),
  );

  await page.route("**/ui", async (route) => {
    const response = await route.fetch();
    const html = await response.text();
    const seeded = html.replace(
      /window\.LIVE_READINESS = .*?;/s,
      `window.LIVE_READINESS = ${JSON.stringify({
        state: seedState,
        reasons: [],
        catalog_drift_ids: [],
        global_spend_ceiling_reached: false,
      })};`,
    );
    // Guard: if the island's shape ever changes, this test would silently
    // stop seeding anything and pass for the wrong reason.
    expect(seeded).not.toBe(html);
    await route.fulfill({ response, body: seeded, headers: response.headers() });
  });

  await page.goto("/ui", { waitUntil: "domcontentloaded" });
}

const banner = (page: Page) => page.locator("#readiness-banner");

test.describe("readiness banner does not flash (#117)", () => {
  test("a stale offline seed on a healthy deployment never paints the banner", async ({ page }) => {
    await bootWithSeedDisagreement(page, "offline_by_bad_key", { state: "live" });

    // Let /ready land and the app settle.
    await expect(banner(page)).toBeHidden();
    await page.waitForTimeout(500);

    const shows = await page.evaluate(() => (window as any).__bannerShows);
    expect(
      shows,
      "the banner appeared at least once before /ready settled — that is the flash",
    ).toBe(0);
    await expect(banner(page)).toBeHidden();
  });

  test("a genuinely offline deployment still shows the banner", async ({ page }) => {
    // The positive partner. Without it, "never flashes" is satisfied by a
    // banner that never renders at all — which would hide the one surface
    // that explains why every answer on screen is simulated.
    await bootWithSeedDisagreement(page, "live", { state: "offline_by_bad_key" });

    await expect(banner(page)).toBeVisible();
    await expect(page.locator("#readiness-banner-title")).toContainText(
      "Live execution is unavailable",
    );

    // And it appeared exactly once — arriving late is fine, arriving twice
    // is the reflow this issue is about.
    const shows = await page.evaluate(() => (window as any).__bannerShows);
    expect(shows, "the banner should appear once, not flicker").toBe(1);
  });

  test("an agreeing offline seed still yields a single appearance", async ({ page }) => {
    // Seed and /ready agree, so the old code painted twice with the same
    // content. Suppression must collapse that to one appearance rather than
    // leaving a redundant paint behind.
    await bootWithSeedDisagreement(page, "offline_by_no_key", { state: "offline_by_no_key" });

    await expect(banner(page)).toBeVisible();
    const shows = await page.evaluate(() => (window as any).__bannerShows);
    expect(shows).toBe(1);
  });
});
