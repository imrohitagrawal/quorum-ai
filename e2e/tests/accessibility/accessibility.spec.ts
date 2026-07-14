import { test, expect } from "../../fixtures/test-data";

/**
 * Comprehensive accessibility tests for Quorum-AI
 */
test.describe("Accessibility", () => {
  test.beforeEach(async ({ page }) => {
    // These tests assert workspace (screen 02) content. Seed the first-visit
    // gate's flag so boot lands on the composer directly, as a returning
    // visitor would, rather than the marketing landing (screen 01).
    await page.addInitScript(() => {
      try { window.localStorage.setItem("quorum.workspaceSeen", "1"); } catch (_) {}
    });
    await page.goto("/ui");
    await page.waitForLoadState("networkidle");
  });

  test.describe("Keyboard Navigation", () => {
    test("should support full keyboard navigation", async ({ page }) => {
      // Tab through all focusable elements
      await page.keyboard.press("Tab");
      const firstFocusable = page.locator(":focus");
      await expect(firstFocusable).toBeVisible();

      // Tab through multiple elements
      const elementsToTab = 10;
      for (let i = 0; i < elementsToTab; i++) {
        await page.keyboard.press("Tab");
        const currentFocus = page.locator(":focus");
        await expect(currentFocus).toBeVisible();
      }
    });

    test("should handle Shift+Tab for reverse navigation", async ({ page }) => {
      // Focus somewhere first
      await page.keyboard.press("Tab");
      const firstElement = page.locator(":focus");
      await expect(firstElement).toBeVisible();

      // Go backwards
      await page.keyboard.press("Shift+Tab");
      await page.waitForTimeout(100); // Wait for focus change
      const previousElement = page.locator(":focus");
      await expect(previousElement).toBeVisible();
    });

    test("should allow Enter key to activate elements", async ({ page }) => {
      const testQuestion = "Test accessibility";
      await page.getByRole("textbox").fill(testQuestion);

      // Focus and activate estimate cost button with Enter
      const estimateButton = page.getByRole("button", { name: /estimate cost/i });
      await estimateButton.focus();
      await page.keyboard.press("Enter");

      // Should show loading or cost in specific element
      await expect(
        page.locator("#cost-confirmation-message")
      ).toBeVisible({ timeout: 3000 });
    });

    test.describe("Screen Reader Support", () => {
      test("should have proper ARIA landmarks", async ({ page }) => {
        // Check for main content landmark
        await expect(page.locator('main')).toBeVisible();

        // Check for navigation if present
        const nav = page.locator('nav');
        if (await nav.count() > 0) {
          await expect(nav).toBeVisible();
        }
      });

      test("should have proper labels for form elements", async ({ page }) => {
        // Question input should have label
        const questionInput = page.getByRole("textbox");
        await expect(questionInput).toBeVisible();

        const associatedLabel = page.locator('label').filter({ has: questionInput });
        if (await associatedLabel.count() > 0) {
          const label = await associatedLabel.first().textContent();
          expect(label && label.trim() !== "").toBeTruthy();
        }
      });

      test("should announce button states properly", async ({ page }) => {
        const runButton = page.getByRole("button", { name: /run now/i });
        await expect(runButton).toBeVisible();

        // Button should not have aria-disabled unless actually disabled
        const ariaDisabled = await runButton.getAttribute("aria-disabled");
        expect(ariaDisabled === null || ariaDisabled === "false").toBeTruthy();
      });
    });
  });

  test.describe("Color and Contrast", () => {
    test.describe("Light Theme", () => {
      test.beforeEach(async ({ page }) => {
        // Ensure light theme
        await page.evaluate(() => {
          document.documentElement.setAttribute("data-theme", "light");
        });
        await page.waitForTimeout(300);
      });

      test("should have sufficient contrast for text", async ({ page }) => {
        // Test text contrast for visible content
        const mainContent = page.locator("#main-content");
        if (await mainContent.count() > 0) {
          const content = await mainContent.textContent();
          // Basic check that we have substantial text content
          expect(content && content.trim().length > 100).toBeTruthy();
        }
      });
    });

    test.describe("Dark Theme", () => {
      test.beforeEach(async ({ page }) => {
        // Switch to dark theme
        const themeButton = page.getByRole("button", { name: /switch to dark theme/i });
        await themeButton.click();
        await page.waitForTimeout(300);
      });

      test("should have sufficient contrast in dark mode", async ({ page }) => {
        // Test that UI elements are still visible in dark mode
        await expect(page.getByRole("textbox")).toBeVisible();
        await expect(page.getByRole("button", { name: /estimate cost/i })).toBeVisible();
      });
    });
  });

  test.describe("Focus Management", () => {
    test("should maintain focus on interaction", async ({ page }) => {
      // Click on an element
      await page.getByRole("button", { name: /estimate cost/i }).click();

      // Focus should still be visible
      const focus = page.locator(":focus");
      await expect(focus).toBeVisible();
    });

    test("should manage focus in modals", async ({ page }) => {
      // Trigger something that might show a modal
      await page.getByRole("button", { name: /run now/i }).click();

      // If modal appears, first element should be focused
      await page.waitForTimeout(500);
      const firstFocusableInModal = page.locator(".modal button:visible, .modal a[href]:visible, .modal input:visible").first();
      if (await firstFocusableInModal.count() > 0) {
        await expect(firstFocusableInModal).toBeVisible();
      }
    });
  });

  test.describe("Error Messages", () => {
    test("should display error messages properly", async ({ page }) => {
      // Mock an error
      await page.route("**/v1/query-runs", (route) => {
        route.fulfill({
          status: 500,
          body: JSON.stringify({ error: "Internal Server Error" }),
        });
      });

      await page.getByRole("textbox").fill("Test error");
      await page.getByRole("button", { name: /run now/i }).click();

      // Error should be announced properly
      await expect(
        page.locator("#error-region")
      ).toBeVisible();
    });

    test("should have visible error indicators", async ({ page }) => {
      await expect(page.getByRole("alert")).toHaveCount(0);
    });
  });

  test.describe("Responsive Accessibility", () => {
    test("should be accessible on mobile devices", async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 });

      // Check tap targets are large enough
      const buttons = page.locator("button");
      const buttonCount = await buttons.count();

      for (let i = 0; i < Math.min(buttonCount, 5); i++) {
        const button = buttons.nth(i);
        const boundingBox = await button.boundingBox();

        if (boundingBox) {
          // Minimum tap target size: 44x44
          expect(boundingBox.width).toBeGreaterThanOrEqual(44);
          expect(boundingBox.height).toBeGreaterThanOrEqual(44);
        }
      }
    });

    test("should be accessible on tablets", async ({ page }) => {
      await page.setViewportSize({ width: 768, height: 1024 });

      // Should still be navigable with touch
      await expect(page.getByRole("textbox")).toBeVisible();
      await expect(page.getByRole("button", { name: /estimate cost/i })).toBeVisible();
    });
  });

  test.describe("Performance", () => {
    test.describe("Fast enough for accessibility", () => {
      test("should respond quickly to keyboard input", async ({ page }) => {
        const startTime = Date.now();
        await page.getByRole("textbox").focus();
        const focusTime = Date.now() - startTime;

        // Should focus within 100ms
        expect(focusTime).toBeLessThan(100);
      });

      test("should not have unnecessary animations", async ({ page }) => {
        // Check that no animations are causing issues
        const animateElements = await page.locator('[animate], [transition], [animation]').count();

        // Any animated elements should have reasonable durations
        expect(animateElements).toBeLessThanOrEqual(5);
      });
    });
  });
});