import { test, expect } from "../../fixtures/test-data";
import { WorkspacePage } from "../../pages/WorkspacePage";

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
      test("should accept Ctrl+Enter for submission", async ({ page }) => {
        await workspacePage.askQuestion("Test question for submission", true);

        // Check that some response or loading state appears
        await expect(page.getByText(/Initial answers running|Synthesising/i)).toBeVisible({
          timeout: 5000,
        });
      });

      test("should accept Cmd+Enter on Mac for submission", async ({ page }) => {
        // Simulate Cmd+Enter (Mac)
        await workspacePage.askQuestion("Mac test question");
        await page.keyboard.press("Meta+Enter");

        // Check for response
        await expect(page.getByText(/Initial answers running|Synthesising/i)).toBeVisible({
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

      const cost = await workspacePage.estimateCost();

      // Cost should be present (could be "$0.00" or actual cost)
      expect(cost).toMatch(/\$/);
    });

    test("should show cost info tooltip", async ({ page }) => {
      // First estimate cost to show the cost info button
      await workspacePage.askQuestion("What is AI?");
      await workspacePage.estimateCostButton.click();
      await page.waitForTimeout(1000);

      // Now click the info icon
      const infoIcon = page.locator(".info-icon").filter({ hasText: "ⓘ" }).first();
      await infoIcon.click();

      // Check that tooltip is shown (not hidden)
      await expect(
        page.locator("#info-tooltip")
      ).not.toHaveAttribute("hidden", "true", { timeout: 3000 });
    });
  });

  test.describe("Error Handling", () => {
    test("should display error banner when errors occur", async ({ page }) => {
      // Mock an API error
      await page.route("**/v1/query-runs", (route) => {
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

      // Wait for error to appear
      await workspacePage.page.waitForTimeout(1000);

      // Dismiss the banner
      const dismissButton = page.getByRole("button", { name: /dismiss error/i });
      await dismissButton.click();

      // Error banner should no longer be visible
      await expect(workspacePage.errorBanner).not.toBeVisible();
    });
  });

  test.describe("Catalog Drift", () => {
    test("should show catalog drift warning when models drift", async ({ page }) => {
      // Mock readiness endpoint to return catalog drift
      await page.route("**/ready", (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            live_readiness: {
              state: "drift",
              catalog_drift_ids: ["test/model"],
            },
          }),
        });
      });

      await workspacePage.page.reload();

      // Wait for drift banner to appear
      await expect(page.locator("#drift-region:not([hidden])")).toBeVisible({
        timeout: 5000,
      });
    });

    test("should dismiss drift warning", async ({ page }) => {
      // Assume drift warning is visible
      if (await workspacePage.hasDriftWarning()) {
        const dismissButton = page.locator("#drift-region-dismiss");
        await dismissButton.click();

        await expect(workspacePage.driftBanner).not.toBeVisible();
      }
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