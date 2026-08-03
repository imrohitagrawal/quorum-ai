import type { Page } from "@playwright/test";
import { test, expect } from "../../fixtures/test-data";
import { WorkspacePage } from "../../pages/WorkspacePage";

/**
 * Put the page into catalog-drift, the only way that actually works.
 *
 * `renderDriftBanner()` reads `state.lastStaleModelIds`, seeded at boot from
 * the `window.STALE_MODEL_IDS` data island the SERVER renders into the initial
 * HTML — so the HTML itself must be patched before the page parses it. Then
 * `refreshDefaults()` re-seeds the same state from the live
 * `/v1/models/defaults` response within the same boot, overwriting the island,
 * so BOTH need the same stale id. The id must be a real default
 * (`model_slots.DEFAULT_MODEL_IDS` slot 1); the banner intersects it with the
 * user's selection, so an arbitrary string never matches.
 */
async function seedCatalogDrift(page: Page): Promise<void> {
  await page.route("**/v1/models/defaults", async (route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        model_slots: [
          { slot_number: 1, model_id: "openai/gpt-4o-mini", search: true },
          { slot_number: 2, model_id: "anthropic/claude-haiku-4.5", search: true },
          { slot_number: 3, model_id: "google/gemini-2.5-flash", search: true },
          { slot_number: 4, model_id: "nvidia/nemotron-3-nano-30b-a3b", search: true },
        ],
        stale_model_ids: ["openai/gpt-4o-mini"],
      }),
    });
  });
  await page.route("**/ui", async (route) => {
    const response = await route.fetch();
    const body = await response.text();
    const patched = body.replace(
      /window\.STALE_MODEL_IDS\s*=\s*\[[^\]]*\];/,
      'window.STALE_MODEL_IDS = ["openai/gpt-4o-mini"];'
    );
    await route.fulfill({ response, body: patched });
  });

  await page.reload();
  await page.waitForLoadState("networkidle");
}

/**
 * End-to-end tests for the Quorum-AI workspace UI
 */
test.describe("Quorum-AI Workspace", () => {
  let workspacePage: WorkspacePage;

  test.beforeEach(async ({ page }) => {
    workspacePage = new WorkspacePage(page);
    await workspacePage.goto();
  });

  test("should load the workspace page with all expected elements", async ({ page }) => {
    // Check page title
    await expect(page).toHaveTitle(/quorum|workspace/i);

    // Check main content is visible
    await expect(page.locator("#main-content")).toBeVisible();

    // Check question input exists and is accessible
    await expect(workspacePage.questionInput).toBeVisible();
    await expect(workspacePage.questionInput).toBeEditable();

    // Check main action buttons
    await expect(workspacePage.estimateCostButton).toBeVisible();
    await expect(workspacePage.estimateCostButton).toBeEnabled();
    await expect(workspacePage.runNowButton).toBeVisible();
    await expect(workspacePage.runNowButton).toBeEnabled();

    // Check theme toggle
    await expect(workspacePage.themeToggle).toBeVisible();
  });

  test.describe("Question Input", () => {
    test("should allow typing questions", async ({ page }) => {
      const testQuestion = "What is artificial intelligence?";
      await workspacePage.askQuestion(testQuestion);

      // Verify input has the text
      await expect(workspacePage.questionInput).toHaveValue(testQuestion);
    });

    test("should handle very long questions", async ({ page }) => {
      const longQuestion = "A".repeat(1000);
      await workspacePage.askQuestion(longQuestion);

      // Verify it was accepted (no error)
      await expect(workspacePage.questionInput).toBeVisible();
    });

    test.describe("Keyboard Shortcuts", () => {
      // Issue #127: both shortcuts map to the ESTIMATE-first path, not to
      // running a query directly — the composer's own keyboard hint says so
      // ("Ctrl+Enter shows the estimate"), and app.js documents it explicitly
      // ("Ctrl/Cmd+Enter maps to the estimate-first path"). "See the
      // estimate" always opens the cost-gate view, even for a cheap
      // allow-band estimate, so these assert on that view opening rather
      // than a run actually starting.
      test("should accept Ctrl+Enter for submission", async ({ page }) => {
        await workspacePage.askQuestion("Test question for submission", true);

        await expect(page.locator("#gate-confirm")).toBeVisible({
          timeout: 5000,
        });
      });

      test("should accept Cmd+Enter on Mac for submission", async ({ page }) => {
        // Simulate Cmd+Enter (Mac)
        await workspacePage.askQuestion("Mac test question");
        await page.keyboard.press("Meta+Enter");

        await expect(page.locator("#gate-confirm")).toBeVisible({
          timeout: 5000,
        });
      });
    });
  });

  test.describe("Theme Functionality", () => {
    test("should toggle between light and dark themes", async ({ page }) => {
      const initialTheme = await workspacePage.getCurrentTheme();

      await workspacePage.toggleTheme();
      const newTheme = await workspacePage.getCurrentTheme();

      expect(newTheme).toBe(initialTheme === "light" ? "dark" : "light");
    });

    test("should have proper contrast in both themes", async ({ page }) => {
      // Test light theme
      if (await workspacePage.getCurrentTheme() === "dark") {
        await workspacePage.toggleTheme();
      }

      // Check that content is visible in light theme
      await expect(workspacePage.questionInput).toBeVisible();
      await expect(workspacePage.estimateCostButton).toBeVisible();

      // Test dark theme
      await workspacePage.toggleTheme();

      // Check that content is still visible in dark theme
      await expect(workspacePage.questionInput).toBeVisible();
      await expect(workspacePage.estimateCostButton).toBeVisible();
    });
  });

  test.describe("Cost Estimation", () => {
    test("should display cost estimates", async ({ page }) => {
      await workspacePage.askQuestion("What is the capital of France?");

      // Issue #127: this used to read `#cost-confirmation-message`, an
      // element `app.js` declares (`el("cost-confirmation-message")`) but
      // never writes to or shows anywhere — dead markup from a superseded
      // single-step flow. The live estimate total renders into the cost-gate
      // view's `#cost-gate-total`, which `estimateCost()` now waits on.
      const cost = await workspacePage.estimateCost();

      // Cost should be present (could be "$0.00" or actual cost)
      expect(cost).toMatch(/\$/);
    });

    // Issue #127: "should show cost info tooltip" is deleted, not fixed.
    // It targeted `.info-icon[aria-label="What does this cost estimate
    // mean?"]`, which lives only inside the same dead `#cost-confirmation`
    // block as `#cost-confirmation-message` above (grep confirms exactly one
    // occurrence of that aria-label in workspace.html, inside that block,
    // and app.js never shows that block). There is no live equivalent
    // surface today — the cost-gate view explains the estimate as static
    // prose (`#cost-gate-reason`, `.cost-review-card-note`), with no
    // click-to-reveal tooltip. Reassigning this test to different markup
    // would test a feature invented for the occasion, not the one this test
    // was written for.
  });

  test.describe("Error Handling", () => {
    test("should display error banner when errors occur", async ({ page }) => {
      // Issue #127: `askQuestion(text, true)` sends Ctrl+Enter, which maps
      // to the ESTIMATE-first path (see the Keyboard Shortcuts tests above),
      // so the request that actually fires is POST /v1/query-runs/estimate,
      // not /v1/query-runs. The exact-path pattern below never matched it,
      // so this 500 mock never fired and no error ever occurred. Widened to
      // match both, the same way the "should dismiss error banners" test
      // below already does.
      await page.route("**/v1/query-runs/**", (route) => {
        route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ error: "Internal Server Error" }),
        });
      });

      await workspacePage.askQuestion("Test error handling", true);

      // Error banner should appear
      await expect(workspacePage.errorBanner).toBeVisible();
    });

    test("should dismiss error banners", async ({ page }) => {
      // Mock an API error
      await page.route("**/v1/query-runs/**", (route) => {
        route.fulfill({
          status: 500,
          body: "{}",
        });
      });

      await workspacePage.askQuestion("Test dismissal", true);

      // The positive partner (#131). Without it a run where the error never
      // rendered at all would sail through the `not.toBeVisible()` below and
      // report that dismissal works. This also replaces a bare
      // `waitForTimeout(1000)` — an assertion that retries beats a fixed sleep
      // that is either flaky or wasted.
      await expect(workspacePage.errorBanner).toBeVisible({ timeout: 10000 });

      await page.getByRole("button", { name: /dismiss error/i }).click();

      // Error banner should no longer be visible
      await expect(workspacePage.errorBanner).not.toBeVisible();
    });
  });

  test.describe("Catalog Drift", () => {
    test("should show catalog drift warning when models drift", async ({ page }) => {
      // Issue #127: mocking /ready's `catalog_drift_ids` (as this test
      // originally did) can never trigger `#drift-region` — that field feeds a
      // DIFFERENT banner (`#readiness-banner`, covered by
      // `tests/invariants/readiness-banner.spec.ts`). See `seedCatalogDrift`
      // above for what actually drives this one, and why.
      await seedCatalogDrift(page);

      // Wait for drift banner to appear
      await expect(page.locator("#drift-region:not([hidden])")).toBeVisible({
        timeout: 5000,
      });
    });

    test("should dismiss drift warning", async ({ page }) => {
      // This test read `if (await hasDriftWarning()) { ... }` and nothing in
      // it ever CREATED the drift, so the condition was false on every run
      // and the whole body — click, assertion and all — was skipped while the
      // test reported green. The #131 negative-assertion guard caught it: an
      // `expect(...).not.toBeVisible()` with no partner proving the banner was
      // ever visible. Driving the same seed as the test above makes the
      // dismissal real, and the `toBeVisible` below is the partner.
      await seedCatalogDrift(page);
      await expect(page.locator("#drift-region:not([hidden])")).toBeVisible({
        timeout: 5000,
      });

      await page.locator("#drift-region-dismiss").click();

      await expect(workspacePage.driftBanner).not.toBeVisible();
    });
  });

  test.describe("Accessibility", () => {
    test("should have all interactive elements accessible", async ({ page }) => {
      // Check that all buttons have proper ARIA labels
      const buttons = page.locator("button");
      const count = await buttons.count();

      for (let i = 0; i < count; i++) {
        const button = buttons.nth(i);
        const role = await button.getAttribute("role");
        const ariaLabel = await button.getAttribute("aria-label");
        const buttonText = await button.textContent();

        // Button should have either aria-label or inner text
        expect(
          ariaLabel !== null || (buttonText && buttonText.trim() !== "")
        ).toBe(true);

        // Interactive elements should be focusable
        const tabIndex = await button.getAttribute("tabindex");
        expect(tabIndex === null || tabIndex === "0").toBe(true);
      }
    });

    test("should support keyboard navigation", async ({ page }) => {
      // Tab through all focusable elements
      await page.keyboard.press("Tab");
      const firstElement = page.locator(":focus");
      await expect(firstElement).toBeVisible();

      // Verify we can tab through multiple elements
      await page.keyboard.press("Tab");
      const secondElement = page.locator(":focus");
      await expect(secondElement).not.toEqual(firstElement);
    });
  });

  test.describe("Responsive Design", () => {
    test("should work on mobile viewport", async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 });

      // Check that main elements are still visible and usable
      await expect(workspacePage.questionInput).toBeVisible();
      await expect(workspacePage.estimateCostButton).toBeVisible();
      await expect(workspacePage.runNowButton).toBeVisible();
    });

    test("should work on tablet viewport", async ({ page }) => {
      await page.setViewportSize({ width: 768, height: 1024 });

      // Check layout adapts correctly
      await expect(workspacePage.questionInput).toBeVisible();
      await expect(workspacePage.estimateCostButton).toBeVisible();
    });
  });
});