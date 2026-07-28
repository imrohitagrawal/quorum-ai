import { test, expect, Page } from "@playwright/test";
import {
  boot,
  driveToResult,
  driveToTranscript,
  driveToLiveRun,
  driveToCostGate,
} from "../../fixtures/golden-run";

/**
 * PR1/#6 — the dark-mode toggle must be reachable on EVERY view.
 *
 * The reported defect: there is no dark-mode toggle on the landing view. Root
 * cause: `#theme-toggle` lives inside `.topbar`, and `app.css` hides `.topbar`
 * on landing / result / live-run / transcript — so the toggle only existed on
 * the composer and cost-gate. A `.theme-toggle-floating` rule was written but
 * NO element ever carried the class, so the CSS was dead in production.
 *
 * These assertions are view-by-view on purpose: a single "a toggle exists"
 * check passes on the composer and would have greened the original bug.
 */

/** A theme toggle that is actually visible to the user on the current view. */
function visibleToggle(page: Page) {
  return page.locator("[data-theme-toggle]:visible");
}

async function currentTheme(page: Page): Promise<string | null> {
  return page.evaluate(() => document.documentElement.dataset.theme || null);
}

test.describe("PR1/#6 — theme toggle reachable on every view", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  test("the composer has a visible toggle", async ({ page }) => {
    await boot(page);
    await expect(visibleToggle(page)).toHaveCount(1);
  });

  test("the LANDING view has a visible toggle", async ({ page }) => {
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await expect(
      visibleToggle(page),
      "landing hides the topbar, so the toggle must come from the floating control",
    ).toHaveCount(1);
  });

  test("the RESULT view has a visible toggle", async ({ page }) => {
    await driveToResult(page);
    await expect(visibleToggle(page)).toHaveCount(1);
  });

  test("the TRANSCRIPT view has a visible toggle", async ({ page }) => {
    await driveToResult(page);
    await driveToTranscript(page);
    await expect(visibleToggle(page)).toHaveCount(1);
  });

  // WP-B/F-23: "every view" was asserted for composer / landing / result /
  // transcript only — the two views the spec skipped are exactly the two that
  // depend on a per-view inline button. The live-run view hides the topbar and
  // does NOT receive the floating control (that rule is landing-only), so
  // deleting `#theme-toggle-live` reproduces #6 with the whole suite green.
  // Pin the ELEMENT, not just "a visible toggle": a floating fallback appearing
  // there instead would be a different (and unreviewed) design, not this fix.
  test("the LIVE-RUN view has a visible toggle", async ({ page }) => {
    await driveToLiveRun(page);
    await expect(visibleToggle(page)).toHaveCount(1);
    await expect(
      page.locator("#theme-toggle-live"),
      "live-run hides the topbar and is not covered by the landing-only float — it needs its own control",
    ).toBeVisible();
  });

  test("the COST-GATE view has a visible toggle", async ({ page }) => {
    await driveToCostGate(page);
    await expect(visibleToggle(page)).toHaveCount(1);
  });

  test("clicking the live-run toggle actually flips the theme", async ({ page }) => {
    // Presence is not reachability: an inline button that is not wired to the
    // shared handler would satisfy the count assertion and still leave the user
    // stuck in light mode mid-run.
    await driveToLiveRun(page);
    const before = await currentTheme(page);
    await page.locator("#theme-toggle-live").click();
    expect(await currentTheme(page), "the live-run toggle must be wired, not just present").not.toBe(before);
  });

  test("exactly one toggle is visible at a time (no duplicate controls)", async ({ page }) => {
    await boot(page);
    await expect(visibleToggle(page)).toHaveCount(1);
    await driveToResult(page);
    await expect(visibleToggle(page)).toHaveCount(1);
  });

  test("clicking the landing toggle flips the theme and persists it", async ({ page }) => {
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="landing"]')).toBeVisible();

    const before = await currentTheme(page);
    await visibleToggle(page).first().click();
    const after = await currentTheme(page);
    expect(after, "clicking the toggle must flip data-theme").not.toBe(before);

    const stored = await page.evaluate(() => window.localStorage.getItem("quorum.theme"));
    expect(stored, "the choice must survive a reload").toBe(after);

    await page.reload({ waitUntil: "domcontentloaded" });
    expect(await currentTheme(page)).toBe(after);
  });

  test("a genuine FIRST visit shows exactly one toggle before hydration", async ({ page }) => {
    // The other "exactly one" test goes through boot(), which sets
    // `quorum.workspaceSeen` — so it never enters the first-visit window and
    // cannot see this. Found by adversarial review, then confirmed live.
    //
    // `html[data-first-visit="true"] .theme-toggle-floating` was written on the
    // premise that a first-time visitor "briefly has no toggle". That premise is
    // false: the topbar is hidden only by `[data-active-view="..."] .topbar`,
    // and `data-active-view` is not set until app.js runs — so in that window
    // the topbar AND its `#theme-toggle` are on screen, and the float made TWO.
    await page.addInitScript(() => {
      try { window.localStorage.removeItem("quorum.workspaceSeen"); } catch (_) {}
    });
    // Block app.js to hold the pre-hydration window open deterministically.
    await page.route("**/static/app.js", (r) => r.abort());
    await page.goto("/ui", { waitUntil: "domcontentloaded" });

    // Anti-vacuity: we must actually be IN the first-visit window.
    await expect(page.locator("html")).toHaveAttribute("data-first-visit", "true");
    await expect(page.locator('[data-view="landing"]')).toBeVisible();

    await expect(
      visibleToggle(page),
      "the first-visit pre-hydration window must not stack the topbar toggle and the floating one",
    ).toHaveCount(1);
  });

  test("a stored dark choice is applied before paint (no light flash)", async ({ page }) => {
    await page.addInitScript(() => {
      try {
        window.localStorage.setItem("quorum.theme", "dark");
      } catch (_) {}
    });
    // Block app.js outright. Whatever theme the document ends up in can then
    // ONLY have been applied by the inline pre-paint snippet — if the snippet
    // were missing, this reads the hardcoded "light" from <html data-theme>,
    // which is exactly the flash a returning dark-mode user used to see.
    // (Racing the parser with waitUntil:"commit" is not a reliable probe: the
    // evaluate can land before the head script has executed.)
    await page.route("**/static/app.js", (r) => r.abort());
    await page.goto("/ui", { waitUntil: "domcontentloaded" });

    expect(
      await page.evaluate(() => document.documentElement.dataset.theme),
      "with app.js blocked, only the inline pre-paint snippet can have set the theme",
    ).toBe("dark");
  });
});
