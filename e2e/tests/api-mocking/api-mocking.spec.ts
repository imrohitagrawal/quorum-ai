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

      // Should see some loading indicator in cost confirmation
      await expect(
        page.locator("#cost-confirmation-message")
      ).toBeVisible({ timeout: 5000 });
    });

    test("should display cost when mocked", async ({ page }) => {
      // Mock the cost estimate endpoint
      await page.route("**/v1/query-runs/estimate", (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            cost_estimate: {
              estimated_cost_usd: 0.025,
              breakdown: [
                { model: "claude-3-5-sonnet", cost: 0.015 },
                { model: "gpt-4o", cost: 0.01 },
              ],
              threshold_action: "proceed",
            },
          }),
        });
      });

      await workspacePage.askQuestion("What is AI?");
      await workspacePage.estimateCostButton.click();
      await page.waitForTimeout;

      const costMessage = await page.locator("#cost-confirmation-message").textContent();
      expect(costMessage).toContain("$");
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
    test("should show user-friendly error on 500", async ({ page }) => {
      await page.route("**/v1/query-runs", (route) => {
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
      await page.route("**/v1/query-runs", (route) => {
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
      await page.route("**/v1/query-runs", (route) => {
        route.abort("failed");
      });

      await workspacePage.askQuestion("Test network failure", true);

      await expect(
        page.locator("#error-region")
      ).toBeVisible({ timeout: 5000 });
    });

    test("should handle timeout errors", async ({ page }) => {
      await page.route("**/v1/query-runs", (route) => {
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
      let capturedBody: any = null;

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
      }
    });
  });
});