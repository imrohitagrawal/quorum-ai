import { test, expect, Page } from "@playwright/test";

/**
 * Issue #222 — the landing page's own content must fit a phone.
 *
 * #116 collapsed the readiness banner (319px -> ~159px), which brought the
 * hero heading above the fold. It did NOT bring the run bar's CTAs into view,
 * because they were never going to fit: measured with NO banner present at
 * all, `#landing-estimate` / `#landing-run` sat at y=830 against a 664px
 * viewport — 166px below the fold on the page's own content. The banner was
 * the straw, not the cause.
 *
 * SCOPE, STATED HONESTLY. This asserts the page's OWN baseline height, which
 * is what #222 measured and what it asks for. With an offline readiness
 * banner present the CTAs are still below the fold, and that is deliberate:
 * a ~159px disclosure saying every answer on screen will be simulated is
 * meant to be read before running one. Shrinking THAT was #116's scope and is
 * already done. So the assertion below is on the `live` state, and the
 * offline case is asserted only to pin that the banner is the difference —
 * not to claim it fits.
 */

const MOBILE = { width: 390, height: 664 }; // iPhone 13, the issue's own viewport

async function mockReadiness(page: Page, state: string): Promise<void> {
  await page.route("**/ready", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "ready",
        environment: "test",
        live_readiness: { state, reasons: [], catalog_drift_ids: [] },
      }),
    }),
  );
}

/** A FIRST visit: no `quorum.workspaceSeen`, so the landing view is shown. */
async function landingAt(page: Page, state: string): Promise<void> {
  await page.setViewportSize(MOBILE);
  await mockReadiness(page, state);
  await page.goto("/ui", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-view="landing"]')).toBeVisible();
  await settle(page);
}

/**
 * Wait for the layout the USER sees, not the pre-font-load transient.
 *
 * Measured while writing this: without it the CTA bottom reads 679px, with it
 * 660px — a 19px difference caused entirely by the serif heading reflowing
 * once its webfont loads. Asserting on the earlier number would fail a page
 * that is actually fine, and would have sent me tuning CSS against a layout
 * no user ever sees.
 */
async function settle(page: Page): Promise<void> {
  await page.evaluate(() => (document as any).fonts?.ready);
  // One frame after fonts, so the reflow they trigger has been applied.
  await page.evaluate(
    () => new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => r()))),
  );
}

async function ctaBottom(page: Page, id: string): Promise<number> {
  const box = await page.locator(`#${id}`).boundingBox();
  expect(box, `#${id} must have a bounding box`).not.toBeNull();
  return Math.round(box!.y + box!.height);
}

test.describe("landing fits a 390x664 phone (#222)", () => {
  test("both run-bar CTAs are fully above the fold on a healthy deployment", async ({ page }) => {
    await landingAt(page, "live");

    // FULLY visible, not merely started: asserting on the bottom edge, because
    // a button whose top is on-screen and whose label is cut off is not "in
    // view" in any sense a user would accept.
    for (const id of ["landing-estimate", "landing-run"]) {
      const bottom = await ctaBottom(page, id);
      expect(
        bottom,
        `#${id} bottom edge is ${bottom}px, below the ${MOBILE.height}px fold ` +
          `(was 830 before #222)`,
      ).toBeLessThanOrEqual(MOBILE.height);
    }
  });

  test("the CTAs are visible without scrolling, as the browser sees it", async ({ page }) => {
    // The no-false-fire partner for the arithmetic above: a bounding box can
    // be in-range while the element is clipped, translated or hidden by an
    // ancestor. This asks the browser instead.
    await landingAt(page, "live");
    for (const id of ["landing-estimate", "landing-run"]) {
      await expect(page.locator(`#${id}`)).toBeInViewport({ ratio: 1 });
    }
  });

  test("an offline banner is what still pushes them down, and only that", async ({ page }) => {
    // Pins the SCOPE claim in the file docstring: with the disclosure present
    // the CTAs move below the fold again. If this ever stops being true, the
    // docstring's reasoning needs revisiting rather than silently rotting.
    await landingAt(page, "live");
    const clean = await ctaBottom(page, "landing-run");

    await landingAt(page, "offline_by_no_key");
    await expect(page.locator("#readiness-banner")).toBeVisible();
    const withBanner = await ctaBottom(page, "landing-run");

    expect(withBanner).toBeGreaterThan(clean);
    expect(clean).toBeLessThanOrEqual(MOBILE.height);
  });

  test("desktop keeps the full-size hero treatment", async ({ page }) => {
    // The density rules are scoped to <=600px on purpose. Without this, a
    // future "simplification" that drops the media query and shrinks the
    // heading everywhere would pass every assertion above.
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockReadiness(page, "live");
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await settle(page);

    const fontSize = await page
      .locator(".landing .landing-h1")
      .evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    expect(fontSize, "the comp-01 52px heading must survive on desktop").toBeGreaterThan(44);
  });
});
