import { test, expect, Page } from "@playwright/test";
import {
  boot,
  driveToCostGate,
  driveToLiveRun,
  driveToResult,
  driveToTranscript,
  goldenCompletedResp,
  goldenCreateResp,
} from "../../fixtures/golden-run";

/**
 * #111 — the offline-mode disclosure must be VISIBLE, not merely present.
 *
 * The reported defect: `#readiness-banner` lived inside
 * `<section class="panel panel-section">`, and app.css has
 *
 *     .layout > aside,
 *     .panel.panel-section { display: none; }
 *
 * a rule the UI-parity redesign added to hide the legacy panels on EVERY
 * screen. So `applyReadinessState()` computed the right severity, title and
 * body, set `hidden = false`... onto an element whose parent is display:none.
 * No user had ever seen it, in ANY offline state.
 *
 * This is the shape of the #6 theme-toggle bug: markup that exists, code that
 * updates it, and a rule that makes it invisible. Two consequences for how
 * this spec is written, both learned the hard way ON THIS FIX:
 *
 *  1. assertions are `toBeVisible()`, never `toBeAttached()` — the original
 *     defect passes `toBeAttached()`, which is why nothing caught it;
 *  2. assertions are PER VIEW. The first attempt at the fix moved the banner
 *     into the composer view and turned this spec green — while the banner was
 *     still invisible on FIRST VISIT, when the landing view is the one showing
 *     and the composer is `hidden`. A browser screenshot caught what the green
 *     suite did not. `boot()` sets `quorum.workspaceSeen`, so any spec that
 *     starts from `boot()` is blind to the landing view by construction.
 *
 * Why it matters: measured 2026-07-28, a valid but UNFUNDED OpenRouter key
 * returns 401 from `GET /api/v1/key`, so an account out of credit lands in
 * `offline_by_bad_key` — and this banner is the one surface that explains why
 * every answer on screen is simulated.
 */

type Readiness = { state: string; reasons?: string[]; catalog_drift_ids?: string[] };

async function mockReadiness(page: Page, readiness: Readiness): Promise<void> {
  await page.route("**/ready", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "ready",
        environment: "test",
        live_readiness: { reasons: [], catalog_drift_ids: [], ...readiness },
      }),
    }),
  );
}

/** A FIRST visit: no `quorum.workspaceSeen`, so the landing view is shown. */
async function bootFirstVisit(page: Page, readiness: Readiness): Promise<void> {
  await mockReadiness(page, readiness);
  await page.goto("/ui", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-view="landing"]')).toBeVisible();
}

const fulfil = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

/**
 * Drive to a RESULT view carrying a specific completed payload — the same
 * local helper `degraded-banner.spec.ts` uses (`fulfil` and the estimate
 * envelope are module-private to the fixture, so this is copied rather than
 * imported). Needed here to reach a DEGRADED result, where #result-degraded
 * actually renders.
 */
async function driveWithCompleted(page: Page, completed: Record<string, unknown>) {
  await boot(page);
  await Promise.all([
    page.route("**/v1/query-runs/estimate", (r) =>
      r.fulfill(
        fulfil({
          correlation_id: "corr-readiness-est",
          cost_estimate: goldenCreateResp().cost_estimate,
          model_slots: goldenCreateResp().model_slots,
          reasons: [],
        }),
      ),
    ),
    page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
    page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
  ]);
  await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => r.fulfill(fulfil(completed)));
  await page.route(/\/v1\/query-runs$/, (r) =>
    r.request().method() === "POST" ? r.fulfill(fulfil(goldenCreateResp())) : r.continue(),
  );
  await page.getByRole("textbox").first().fill("What are the key metrics for SaaS retention?");
  await page.locator("#run-now").click();
  await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
}

const banner = (page: Page) => page.locator("#readiness-banner");

/** Every state in which live execution will NOT happen. */
const OFFLINE_STATES: ReadonlyArray<{ state: string; copy: RegExp }> = [
  { state: "offline_by_no_key", copy: /provider key is missing/i },
  { state: "offline_by_config", copy: /turned off/i },
  { state: "offline_by_bad_key", copy: /rejected the configured key/i },
];

test.describe("#111 — the offline disclosure is visible where a user decides to run", () => {
  for (const { state, copy } of OFFLINE_STATES) {
    test(`${state}: visible on the LANDING view (first visit)`, async ({ page }) => {
      // The case the first fix attempt got wrong. A first-time visitor is
      // exactly who needs to be told the answers are simulated.
      await bootFirstVisit(page, { state, reasons: ["operator reason"] });

      await expect(banner(page)).toBeVisible();
      await expect(page.locator("#readiness-banner-message")).toContainText(copy);
      const box = await banner(page).boundingBox();
      expect(box, "no layout box").not.toBeNull();
      expect(box!.height).toBeGreaterThan(0);
    });

    test(`${state}: visible on the COMPOSER view`, async ({ page }) => {
      await mockReadiness(page, { state, reasons: ["operator reason"] });
      await boot(page);
      await page.reload();
      await expect(page.locator('[data-view="composer"]')).toBeVisible();

      await expect(banner(page)).toBeVisible();
      await expect(page.locator("#readiness-banner-message")).toContainText(copy);
    });
  }

  test("rendered on the COST-GATE view (reachable, though scrolled above the fold)", async ({
    page,
  }) => {
    // Named for what it actually proves. An earlier version of this test was
    // called "the moment money is approved" and asserted only toBeVisible() —
    // which in Playwright means "has a box and is not display:none", NOT "on
    // screen". Measured: entering the cost gate scrolls to #cost-gate-heading,
    // leaving the banner ~240px above the viewport on desktop and ~800px on
    // mobile. The test could not fail for the property its name advertised.
    await mockReadiness(page, { state: "offline_by_bad_key", reasons: ["r"] });
    await driveToCostGate(page);

    await expect(banner(page)).toBeVisible();
  });

  test("on the views a user READS FIRST, the banner is actually on screen", async ({
    page,
  }) => {
    // The assertion toBeVisible() cannot make. Landing is the front door, and
    // it is where the disclosure has to land without scrolling.
    await bootFirstVisit(page, { state: "offline_by_bad_key", reasons: ["r"] });

    await expect(banner(page)).toBeInViewport();
  });

  test("visible on the LIVE-RUN view", async ({ page }) => {
    await mockReadiness(page, { state: "offline_by_bad_key", reasons: ["r"] });
    await driveToLiveRun(page);

    await expect(banner(page)).toBeVisible();
  });

  test("the TRANSCRIPT view still discloses — it has no run-level banner", async ({
    page,
  }) => {
    // The regression this spec missed the first time. The step-aside rule
    // originally covered transcript too, justified by a comment claiming the
    // transcript "owns a run-specific #result-degraded". It does not:
    // #result-degraded is declared inside <div data-view="result">. The result
    // was a view with NO disclosure of any kind — on the one screen that
    // renders the simulated model-vs-model debate in full.
    await mockReadiness(page, { state: "offline_by_bad_key", reasons: ["r"] });
    await driveToResult(page);
    await driveToTranscript(page);

    await expect(banner(page)).toBeVisible();
  });

  test("steps aside on the RESULT view, where the run-level banner speaks", async ({
    page,
  }) => {
    // PAIRED, deliberately. An earlier version drove the all-live golden run
    // (live_count 4, local_count 0), where #result-degraded does not render
    // either — so it asserted the deployment-level banner steps aside for a
    // run-level banner that was itself absent, and called that correct. Green
    // for the wrong reason. A degraded run is the case the rule exists for.
    await mockReadiness(page, { state: "offline_by_bad_key", reasons: ["r"] });
    await driveWithCompleted(page, {
      ...goldenCompletedResp(),
      demo_mode: true,
      live_count: 2,
      local_count: 2,
    });

    await expect(banner(page)).toBeHidden();
    // ...and the surface it defers to must actually be speaking.
    await expect(page.locator("#result-degraded")).toBeVisible();
  });

  test("live: no offline disclosure anywhere", async ({ page }) => {
    // The paired negative. Without it, a banner hardcoded visible would pass
    // every assertion above.
    await bootFirstVisit(page, { state: "live" });

    await expect(banner(page)).toBeHidden();
  });

  test("an unrecognised state still discloses rather than staying silent", async ({
    page,
  }) => {
    await bootFirstVisit(page, { state: "something_the_server_invented" });

    await expect(banner(page)).toBeVisible();
  });
});
