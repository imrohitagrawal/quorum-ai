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
 * SCOPE, STATED HONESTLY — AND THE FIX IS PARTIAL. Adversarial review
 * measured the fold across realistic conditions, and the result only holds
 * at the issue's own reference viewport with default text:
 *
 *     390x664 (iPhone 13, 16px)   bottom 660   FITS, by 4px
 *     375x667 (iPhone SE)         bottom 704   over by 37
 *     360x640 (Android)           bottom 704   over by 64
 *     390x600 (URL bar showing)   bottom 660   over by 60
 *     320x568 (SE 1st gen)        bottom 728   over by 160
 *     390x664 @ 18px root font    bottom 751   over by 87
 *     390x664 @ 20px root font    bottom 839   over by 175
 *
 * So "#222 is fixed" would be false. What IS delivered: the page is
 * substantially denser (CTA bottom 830 -> 660 at the reference viewport) and
 * the CTAs are no longer covered by the session trail. Making the fold hold
 * across phones and text-scaling needs content removed from above the run
 * bar, which is a landing-page design decision, not a density tweak.
 *
 * The offline case: with a readiness banner present the CTAs are still below
 * the fold, and that is deliberate — a ~159px disclosure saying every answer
 * will be simulated is meant to be read before running one. Shrinking THAT
 * was #116's scope. Note review also found the banner is NOT the only thing
 * that pushes them down (catalog drift and the spend-ceiling banner do too),
 * so the third test asserts only that the banner IS a difference, not that it
 * is the sole one.
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

  test("the CTAs are actually CLICKABLE, not merely inside the viewport", async ({ page }) => {
    // THE TEST THAT WOULD HAVE CAUGHT THE FIRST VERSION OF THIS FIX.
    //
    // The density rules alone brought the CTAs to y=616-660 — inside the
    // 664px fold, and every arithmetic assertion passed. They were also
    // covered 100% by `.session-trail-panel`, which is `position: fixed;
    // z-index: 100` occupying 610-664 at this width. A real click on "Run the
    // debate" hit `session-trail-head` and did nothing.
    //
    // `toBeInViewport({ ratio: 1 })` was the original partner here and cannot
    // see this: it is an IntersectionObserver against the VIEWPORT, and has
    // no notion of paint order. Hit-testing does.
    await landingAt(page, "live");

    const occlusion = await page.evaluate(() =>
      ["landing-estimate", "landing-run"].map((id) => {
        const el = document.getElementById(id)!;
        const r = el.getBoundingClientRect();
        let covered = 0;
        let sampled = 0;
        // Inset by 4px so the shared edge with the adjacent button does not
        // count as occlusion.
        for (let x = r.left + 4; x < r.right - 4; x += 8) {
          for (let y = r.top + 4; y < r.bottom - 4; y += 8) {
            sampled++;
            const top = document.elementFromPoint(x, y);
            if (top && !el.contains(top)) covered++;
          }
        }
        return { id, sampled, coveredPct: Math.round((100 * covered) / sampled) };
      }),
    );

    for (const { id, sampled, coveredPct } of occlusion) {
      expect(sampled, `#${id}: nothing sampled — the box must be on screen`).toBeGreaterThan(0);
      expect(coveredPct, `#${id} is ${coveredPct}% covered by something else`).toBe(0);
    }
  });

  test("an offline banner is one of the things that pushes them down", async ({ page }) => {
    // Pins that the disclosure moves the CTAs down. Deliberately NOT phrased
    // as "and only that": review measured the catalog-drift banner (902) and
    // the global-spend-ceiling banner (842) doing the same on a `live`
    // deployment, so an exclusivity claim would be false.
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
