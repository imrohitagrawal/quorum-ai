import { test, expect } from "@playwright/test";

/**
 * Issue #222 + the CTA occlusion bug: the landing call-to-action must be
 * REACHABLE on a phone.
 *
 * WHY A HIT TEST AND NOT `toBeInViewport` / `toHaveScreenshot`.
 * Both are structurally blind to paint order. MEASURED on this branch before
 * the fix: with the density rules applied but the trail-panel hide removed,
 * `#landing-run` sits at y=616-660 — inside a 664px fold, so `toBeInViewport`
 * PASSES — while `document.elementFromPoint` over its centre returns
 * `div.session-trail-head`, because `.session-trail-panel` is
 * `position: fixed; bottom: 0; z-index: 100` at this width and covers
 * y=610-664. A real click does nothing. A viewport assertion would have
 * called that a success. This asserts who actually receives the click.
 *
 * WHY NOT A FOLD ASSERTION. PR #238 proposed one and it is not robust.
 * MEASURED with readiness stubbed `live` (the production condition — prod
 * reports `state: live`, so no banner): the CTA clears the 664px fold by
 * exactly **4px** at 390x664, and MISSES it by +37 at 375x667 and +64 at
 * 360x640. A gate with 4px of slack that already fails at two common phone
 * sizes is a flake waiting to happen, so the fold is measured in the
 * `landing density` test below and reported, never gated.
 */

const PHONE = { width: 390, height: 664 };

/** The production readiness condition: live, so no banner. */
async function stubReadinessLive(page: import("@playwright/test").Page) {
  await page.route("**/ready", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "ready",
        environment: "test",
        live_readiness: {
          state: "live",
          reasons: [],
          catalog_drift_ids: [],
          checked_at_utc: new Date(0).toISOString(),
        },
      }),
    }),
  );
}

test.describe("landing CTA is reachable on a phone (#222)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "geometry gate is chromium-only");

  for (const size of [
    { width: 390, height: 664 },
    { width: 375, height: 667 },
    { width: 360, height: 640 },
  ]) {
    test(`a click on the CTA reaches the CTA @ ${size.width}x${size.height}`, async ({ page }) => {
      await stubReadinessLive(page);
      await page.setViewportSize(size);
      await page.goto("/ui");
      await expect(page.locator("#landing-run")).toBeAttached();

      const cta = page.locator("#landing-run");
      await cta.scrollIntoViewIfNeeded();

      const hit = await page.evaluate(() => {
        const el = document.querySelector("#landing-run") as HTMLElement;
        const r = el.getBoundingClientRect();
        const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return {
          reaches: Boolean(top && (top === el || el.contains(top))),
          actual: top ? `${top.tagName.toLowerCase()}${top.id ? "#" + top.id : ""}` : "null",
        };
      });

      // RED IF: `[data-active-view="landing"] .session-trail-panel { display: none }`
      // is removed from app.css — `actual` becomes `div.session-trail-head`.
      //
      // MEASURED, and stated because it is a limit of this assertion rather
      // than a property of the fix: removing that rule reddens this test at
      // **390x664 and 375x667 only**. At 360x640 it stays GREEN, because the
      // CTA is 64px below the fold there, so `scrollIntoViewIfNeeded` scrolls
      // it clear of the bottom-pinned panel and it really is reachable — for a
      // different reason than the fix. The 360x640 case therefore proves
      // reachability but does NOT exercise the occlusion. The assertion that
      // bites at every viewport is the `display` check in the next test; this
      // loop is the user-facing property, that one is the mechanism.
      expect(hit.actual).not.toBe("null");
      expect(hit, `a click at the CTA centre landed on ${hit.actual}`).toMatchObject({
        reaches: true,
      });
    });
  }

  test("the trail panel is hidden on landing and SHOWN in the workspace", async ({ page }) => {
    await stubReadinessLive(page);
    await page.setViewportSize(PHONE);
    await page.goto("/ui");
    await expect(page.locator("#landing-run")).toBeAttached();

    const onLanding = await page.evaluate(() => {
      const t = document.querySelector(".session-trail-panel");
      return {
        inDom: Boolean(t),
        display: t ? getComputedStyle(t).display : "absent",
        activeView: document.getElementById("main-content")?.dataset.activeView ?? null,
      };
    });
    expect(onLanding.inDom).toBe(true);
    expect(onLanding.activeView).toBe("landing");
    // RED IF: the hide rule is removed — `display` becomes `flex`.
    expect(onLanding.display).toBe("none");

    // POSITIVE PARTNER. Without this, `display === "none"` would pass just as
    // happily against a panel deleted from the product entirely, or against a
    // blanket `.session-trail-panel { display: none }` that breaks the trail
    // everywhere. The hide must be scoped to the landing view and nothing else.
    await page.locator("#landing-query").fill("Compare two database options");
    await page.locator("#landing-run").click();
    await expect
      .poll(async () =>
        page.evaluate(
          () => document.getElementById("main-content")?.dataset.activeView ?? null,
        ),
      )
      .not.toBe("landing");

    const offLanding = await page.evaluate(() => {
      const t = document.querySelector(".session-trail-panel");
      return t ? getComputedStyle(t).display : "absent";
    });
    expect(offLanding).not.toBe("none");
  });

  test("landing density: the page is not multiples of the fold", async ({ page }) => {
    await stubReadinessLive(page);
    await page.setViewportSize(PHONE);
    await page.goto("/ui");
    await expect(page.locator("#landing-run")).toBeAttached();

    const m = await page.evaluate(() => ({
      scrollHeight: document.documentElement.scrollHeight,
      fold: window.innerHeight,
      ctaBelowFold: Math.round(
        (document.querySelector("#landing-run") as HTMLElement).getBoundingClientRect().bottom -
          window.innerHeight,
      ),
      horizontalOverflow:
        document.documentElement.scrollWidth > document.documentElement.clientWidth,
    }));

    // Reported, never gated — see the file header for why the fold itself is
    // not a safe assertion (4px of slack at this viewport).
    console.log(`landing @390x664: ${JSON.stringify(m)}`);

    // RED IF: the density block in app.css is removed. MEASURED with the
    // readiness banner present, before the fix, the page was 1848px against a
    // 664px fold (2.78x); after, 1422px (2.14x). The bound below is set at 2.4x
    // — comfortably clear of the measured "after" and comfortably below the
    // measured "before", so it is not pinned to either number (rule 7a).
    expect(m.scrollHeight).toBeLessThan(m.fold * 2.4);
    // Never a horizontal scrollbar on a phone.
    expect(m.horizontalOverflow).toBe(false);
  });
});
