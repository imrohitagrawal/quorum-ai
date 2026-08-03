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
      const obs = new MutationObserver(() => {
        const now = visible();
        // Count only OFF -> ON edges: that is what a user perceives as the
        // banner appearing, and it is what a flash-then-retract produces.
        if (now && !wasVisible) (window as any).__bannerShows++;
        wasVisible = now;
      });
      obs.observe(el, { attributes: true, attributeFilter: ["hidden", "style", "class"] });
      // Also watch the ANCESTOR whose attribute can hide this banner:
      // app.css has `#main-content[data-active-view="result"] #readiness-banner
      // { display: none }`, so a view switch changes visibility WITHOUT
      // mutating the banner itself. Review caught that watching only the
      // element left that trigger uncounted -- `visible()` computed the right
      // answer, but nothing woke it up.
      const main = document.getElementById("main-content");
      if (main) obs.observe(main, { attributes: true, attributeFilter: ["data-active-view"] });
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
    // ANCHORED TO END OF LINE, not to the first `;`. Review caught that a
    // lazy `.*?;` stops at the first semicolon -- and a real readiness reason
    // contains one (REASON_CATALOG_UNREACHABLE: "...will still be served;
    // live pricing is unavailable."). That truncation left broken JS, which
    // killed the whole inline island, so LIVE_READINESS / DEFAULT_MODEL_IDS /
    // COST_MODEL were all undefined and the "banner hidden" assertion passed
    // VACUOUSLY.
    const seeded = html.replace(
      /window\.LIVE_READINESS = .*;$/m,
      `window.LIVE_READINESS = ${JSON.stringify({
        state: seedState,
        reasons: [],
        catalog_drift_ids: [],
        global_spend_ceiling_reached: false,
      })};`,
    );
    // Guards. The first alone is not enough -- it only proves SOMETHING was
    // replaced, which the truncating regex above also satisfied. The second
    // proves the result still parses and carries the state we asked for.
    expect(seeded).not.toBe(html);
    const seededState = seeded.match(/window\.LIVE_READINESS = (\{.*?\});/s);
    expect(seededState, "the seeded island must be findable and well-formed").not.toBeNull();
    expect(JSON.parse(seededState![1]).state).toBe(seedState);
    await route.fulfill({ response, body: seeded, headers: response.headers() });
  });

  await page.goto("/ui", { waitUntil: "domcontentloaded" });
}

const banner = (page: Page) => page.locator("#readiness-banner");

test.describe("readiness banner does not flash (#117)", () => {
  test("a stale offline seed on a healthy deployment never paints the banner", async ({ page }) => {
    await bootWithSeedDisagreement(page, "offline_by_bad_key", { state: "live" });

    // Positive partner (#131). `toBeHidden()` is also satisfied by a page that
    // never booted at all — and "app.js threw, so the disclosure stayed hidden
    // forever" is the exact defect this file exists to prevent, which makes
    // that blind spot self-defeating. `data-active-view` is written ONLY by
    // app.js's setView() (app.js:302) and is never server-rendered, so its
    // presence proves the app ran before we assert what it did not paint.
    await expect(page.locator("#main-content[data-active-view]")).toBeVisible();

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

test.describe("suppression can never outlive boot (#117 review)", () => {
  test("a boot failure still shows the offline disclosure", async ({ page }) => {
    // THE REGRESSION THIS SUPPRESSION COULD HAVE CAUSED, and the reason it is
    // worth a dedicated test: boot()'s own try block does not open until long
    // after applyReadinessState() runs. A throw in the unguarded wiring region
    // between them means refreshReadiness() is never reached — so before the
    // fix, the banner stayed hidden for the life of the page on a genuinely
    // offline deployment. The pre-change seed paint would have shown it.
    // Trading a cosmetic flash for a silent disclosure failure is strictly the
    // wrong direction.
    //
    // The throw is injected by removing an element boot() wires a listener
    // onto, which is exactly the "renamed id / template change" shape app.js's
    // own comment calls realistic — not a synthetic error.
    await recordBannerVisibility(page);
    // Strip the element from the SERVED HTML, not at DOMContentLoaded: app.js
    // is `defer`, so it runs BEFORE that event and would already have wired
    // its listener. Removing it from the markup is also the more faithful
    // simulation of the "renamed id / template change" this guards against.
    await page.route("**/ui", async (route) => {
      const response = await route.fetch();
      const html = await response.text();
      let stripped = html.replace(/id="estimate-run"/, 'id="estimate-run-RENAMED"');
      expect(stripped, "the injection must actually change the markup").not.toBe(html);
      // Seed an OFFLINE state too. boot() never reaches refreshReadiness on
      // this path, so /ready is never fetched — the seed is the only
      // disclosure available, which is exactly the point being tested.
      stripped = stripped.replace(
        /window\.LIVE_READINESS = .*;$/m,
        `window.LIVE_READINESS = ${JSON.stringify({
          state: "offline_by_no_key",
          reasons: [],
          catalog_drift_ids: [],
          global_spend_ceiling_reached: false,
        })};`,
      );
      await route.fulfill({ response, body: stripped, headers: response.headers() });
    });
    await page.route("**/ready", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "ready",
          environment: "test",
          live_readiness: { state: "offline_by_no_key", reasons: [], catalog_drift_ids: [] },
        }),
      }),
    );

    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await expect(banner(page)).toBeVisible({ timeout: 10000 });
    await expect(page.locator("#readiness-banner-title")).toContainText(
      "Live execution is unavailable",
    );
  });

  test("a /ready probe that rejects still shows the seeded disclosure", async ({ page }) => {
    // The other unguarded exit: toast() is called from INSIDE refreshReadiness's
    // first catch, so a throw there escapes before any trailing statement. That
    // path is precisely "the probe failed" — when the page-load seed is the
    // only disclosure available. The flag is set in a `finally` for this.
    await bootWithSeedDisagreement(page, "offline_by_no_key", { state: "live" });
    await page.route("**/ready", (route) => route.abort("failed"));
    await page.reload({ waitUntil: "domcontentloaded" });

    await expect(banner(page)).toBeVisible({ timeout: 10000 });
  });
});

test.describe("a hung probe cannot silence the disclosure (#117 review 2)", () => {
  /** Serve /ui with an explicit seed, and hang the named endpoint forever. */
  async function bootWithHungEndpoint(page: Page, hang: string, seedState: string): Promise<void> {
    await recordBannerVisibility(page);
    // Never resolve and never reject: `api()` uses a bare fetch with no
    // timeout, so this is the shape a `finally` cannot rescue.
    await page.route(hang, () => {});
    await page.route("**/ui", async (route) => {
      const response = await route.fetch();
      const html = await response.text();
      const seeded = html.replace(
        /window\.LIVE_READINESS = .*;$/m,
        `window.LIVE_READINESS = ${JSON.stringify({
          state: seedState,
          reasons: [],
          catalog_drift_ids: [],
          global_spend_ceiling_reached: false,
        })};`,
      );
      expect(seeded).not.toBe(html);
      await route.fulfill({ response, body: seeded, headers: response.headers() });
    });
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
  }

  test("a hung /ready still discloses, from the seed", async ({ page }) => {
    // Measured before the fix: hidden indefinitely. `api()` has no timeout, so
    // the request never settles and neither the finally nor boot().catch runs.
    await bootWithHungEndpoint(page, "**/ready", "offline_by_bad_key");
    await expect(banner(page)).toBeVisible({ timeout: 10000 });
    await expect(page.locator("#readiness-banner-title")).toContainText(
      "Live execution is unavailable",
    );
  });

  test("a hung /v1/models/defaults does not silence the disclosure either", async ({ page }) => {
    // Review's worst case was "the server gave the correct offline verdict and
    // the banner was STILL suppressed". Measuring it turned up something
    // sharper: `boot()` awaits `refreshDefaults()` BEFORE it ever calls
    // `refreshReadiness()`, so hanging that endpoint stalls boot earlier still
    // and `/ready` is never even requested. The disclosure therefore cannot
    // come from the verdict — only from the seed — which is precisely why the
    // time-bounded fallback exists. Asserting a `/ready` verdict here would be
    // asserting a value the page never fetched.
    await recordBannerVisibility(page);
    await page.route("**/v1/models/defaults", () => {});
    await bootWithHungEndpoint(page, "**/v1/models/defaults", "offline_by_bad_key");

    await expect(banner(page)).toBeVisible({ timeout: 10000 });
    await expect(page.locator("#readiness-banner-title")).toContainText(
      "Live execution is unavailable",
    );
  });

  test("a hung probe on a HEALTHY seed still does not paint", async ({ page }) => {
    // The no-false-fire partner: the time-bounded fallback paints the SEED, so
    // it must not invent a warning when the seed says the deployment is fine.
    await bootWithHungEndpoint(page, "**/ready", "live");
    // Positive partner (#131) — same reasoning as the first test: prove app.js
    // booted, or "hidden" could just mean "nothing rendered".
    await expect(page.locator("#main-content[data-active-view]")).toBeVisible();
    await page.waitForTimeout(3000); // past READINESS_DISCLOSURE_FALLBACK_MS
    await expect(banner(page)).toBeHidden();
    expect(await page.evaluate(() => (window as any).__bannerShows)).toBe(0);
  });
});
