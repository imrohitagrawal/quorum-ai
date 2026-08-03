import { test, expect } from "../../fixtures/test-data";
import { WorkspacePage } from "../../pages/WorkspacePage";

/**
 * Tests using network mocking to simulate various scenarios
 */
test.describe("Network Mocking", () => {
  let workspacePage: WorkspacePage;

  test.beforeEach(async ({ page }) => {
    workspacePage = new WorkspacePage(page);
    await workspacePage.goto();
  });

  test.describe("API Response Mocking", () => {
    test("should handle slow API responses gracefully", async ({ page }) => {
      // Slow down the API response
      await page.route("**/v1/query-runs/estimate", async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 3000));
        await route.continue();
      });

      await workspacePage.askQuestion("Test slow response");

      // Click estimate and wait - should show loading state
      await workspacePage.estimateCostButton.click();

      // Issue #127: `#cost-confirmation-message` is dead markup (declared in
      // app.js, never written to or shown). "See the estimate" always opens
      // the cost-gate view once the (slowed) response lands; that view's
      // total renders into `#cost-gate-total`.
      await expect(
        page.locator("#cost-gate-total")
      ).toBeVisible({ timeout: 5000 });
    });

    test("should display cost when mocked", async ({ page }) => {
      // Mock the cost estimate endpoint. Issue #127: the original body's
      // `breakdown` was a bare array of `{model, cost}` objects; the real
      // schema (golden-run.ts's `breakdown()`, and `QueryRunEstimateResponse`
      // in openapi.yaml) is `{by_model: [...], by_stage: [...], total}` --
      // `renderCostGate` reads `breakdown.by_model`/`by_stage`, which was
      // `undefined` against the old shape.
      await page.route("**/v1/query-runs/estimate", (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            correlation_id: "corr-api-mocking-est",
            cost_estimate: {
              estimated_cost_usd: "0.025",
              currency: "USD",
              threshold_action: "allow",
              confirmation_token: "tok-api-mocking",
              breakdown: {
                by_model: [
                  { model_id: "openai/gpt-4o-mini", display_name: "GPT-4o-mini", usd: "0.009", kind: "model" },
                  { model_id: "anthropic/claude-haiku-4.5", display_name: "Claude Haiku 4.5", usd: "0.008", kind: "model" },
                  { model_id: "google/gemini-2.5-flash", display_name: "Gemini 2.5 Flash", usd: "0.004", kind: "model" },
                  { model_id: "nvidia/nemotron-3-nano-30b-a3b", display_name: "Nemotron 3 Nano", usd: "0.004", kind: "model" },
                ],
                by_stage: [{ stage: "initial_answers", usd: "0.025" }],
                total: "0.025",
              },
            },
            model_slots: [],
            reasons: [],
          }),
        });
      });

      await workspacePage.askQuestion("What is AI?");
      await workspacePage.estimateCostButton.click();

      const costMessage = page.locator("#cost-gate-total");
      await expect(costMessage).toBeVisible({ timeout: 5000 });
      await expect(costMessage).toContainText("$");
    });

    test("should handle model unavailability", async ({ page }) => {
      // Mock all models as unavailable
      await page.route("**/v1/models/defaults", (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            models: [],
            error: "All models are currently unavailable",
          }),
        });
      });

      await workspacePage.page.reload();

      // Should show some indication of unavailability
      const content = await page.content();
      expect(
        content.toLowerCase().includes("unavailable") ||
          content.toLowerCase().includes("error") ||
          content.toLowerCase().includes("drift")
      ).toBeTruthy();
    });
  });

  test.describe("Error State Mocking", () => {
    // Issue #127: `askQuestion(text, true)` sends Ctrl+Enter, which maps to
    // the ESTIMATE-first path (workspace.spec.ts's Keyboard Shortcuts
    // tests), so the request that actually fires is
    // POST /v1/query-runs/estimate, not /v1/query-runs. The exact-path
    // pattern below never matched it, so none of these mocks ever fired.
    // Widened to `**/v1/query-runs/**`, matching what the api-mocking spec's
    // OWN passing sibling further up this file already relies on for the
    // same reason.
    test("should show user-friendly error on 500", async ({ page }) => {
      await page.route("**/v1/query-runs/**", (route) => {
        route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({
            error: "Internal Server Error",
            message: "Something went wrong on our end",
          }),
        });
      });

      await workspacePage.askQuestion("Test 500 error", true);

      // Error banner should appear with user-friendly message
      await expect(
        page.locator("#error-region")
      ).toBeVisible({ timeout: 5000 });
    });

    test("should show user-friendly error on 403", async ({ page }) => {
      await page.route("**/v1/query-runs/**", (route) => {
        route.fulfill({
          status: 403,
          body: JSON.stringify({
            error: "Forbidden",
            message: "API key invalid or expired",
          }),
        });
      });

      await workspacePage.askQuestion("Test 403 error", true);

      await expect(
        page.locator("#error-region-message")
      ).toBeVisible({ timeout: 5000 });
    });

    test("should handle network failures", async ({ page }) => {
      await page.route("**/v1/query-runs/**", (route) => {
        route.abort("failed");
      });

      await workspacePage.askQuestion("Test network failure", true);

      await expect(
        page.locator("#error-region")
      ).toBeVisible({ timeout: 5000 });
    });

    test("should handle timeout errors", async ({ page }) => {
      await page.route("**/v1/query-runs/**", (route) => {
        route.abort("timedout");
      });

      await workspacePage.askQuestion("Test timeout", true);

      await expect(
        page.locator("#error-region")
      ).toBeVisible({ timeout: 5000 });
    });
  });

  test.describe("Request Modification", () => {
    test("should log outgoing requests", async ({ page }) => {
      const requests: string[] = [];

      page.on("request", (request) => {
        if (request.url().includes("/v1/")) {
          requests.push(request.url());
        }
      });

      await workspacePage.askQuestion("Test request logging");
      await workspacePage.estimateCostButton.click();

      await page.waitForTimeout(1000);

      // Should have made at least one API request
      expect(requests.length).toBeGreaterThan(0);
    });

    test("should verify request payload structure", async ({ page }) => {
      let capturedBody: string | null = null;

      await page.route("**/v1/query-runs/estimate", async (route) => {
        capturedBody = route.request().postData();
        await route.continue();
      });

      await workspacePage.askQuestion("Test payload structure");
      await workspacePage.estimateCostButton.click();

      await page.waitForTimeout(1000);

      if (capturedBody) {
        const body = JSON.parse(capturedBody);
        // Should have query_text field
        expect(body).toHaveProperty("query_text");
      } else {
        // If no body was captured, the test setup failed
        expect(capturedBody).not.toBeNull();
      }
    });
  });
});