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
      // Issue #127: Tab ONCE then Shift+Tab asserts an impossible focus
      // state — Shift+Tab from the FIRST focusable element in the document
      // has nothing in-page to land on (focus legitimately leaves the
      // document), so `:focus` correctly resolves to nothing. Reproduced
      // directly: this always timed out regardless of the button-name drift
      // fixed elsewhere in this file. Tab twice (landing on the SECOND
      // focusable element), then Shift+Tab once, so the reverse step has a
      // real in-page predecessor to return to.
      await page.keyboard.press("Tab");
      await page.keyboard.press("Tab");
      const secondElement = page.locator(":focus");
      await expect(secondElement).toBeVisible();

      // Go backwards
      await page.keyboard.press("Shift+Tab");
      await page.waitForTimeout(100); // Wait for focus change
      const firstElement = page.locator(":focus");
      await expect(firstElement).toBeVisible();
    });

    test("should allow Enter key to activate elements", async ({ page }) => {
      const testQuestion = "Test accessibility";
      await page.getByRole("textbox").fill(testQuestion);

      // Issue #127: the accessible name drifted from "estimate cost" to
      // "See the estimate →" (workspace.html's actual button label); the old
      // regex never matched, so `.focus()` waited the full test timeout for
      // an element that was never going to appear. Matches WorkspacePage.ts's
      // own already-correct pattern.
      const estimateButton = page.getByRole("button", { name: /see the estimate|estimate cost/i });
      await estimateButton.focus();
      await page.keyboard.press("Enter");

      // Issue #127: "See the estimate" ALWAYS opens the cost-gate view (even
      // for a cheap allow-band estimate) — app.js's own contract comment.
      // `#cost-confirmation-message` is dead markup (declared, never
      // written to or shown).
      await expect(
        page.locator("#gate-confirm")
      ).toBeVisible({ timeout: 5000 });
    });

    test.describe("Screen Reader Support", () => {
      test("should have proper ARIA landmarks", async ({ page }) => {
        // Check for main content landmark
        await expect(page.locator('main')).toBeVisible();

        // Issue #127: `.count()` counts every matching element regardless
        // of visibility, so this guard ("only check if present") never
        // actually filtered anything out. `<nav class="workflow-progress">`
        // IS present in the DOM but is permanently `display: none` in CSS
        // (app.css: a superseded "legacy section", per its own comment —
        // "the result view now renders its own synthesis block ... nothing
        // is lost by hiding the legacy sections"). A landmark that will
        // never be shown is not a real navigation landmark to assert
        // visibility on. Scope to VISIBLE navs only.
        const visibleNav = page.locator('nav:visible');
        if (await visibleNav.count() > 0) {
          await expect(visibleNav.first()).toBeVisible();
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
        await expect(page.getByRole("button", { name: /see the estimate|estimate cost/i })).toBeVisible();
      });
    });
  });

  test.describe("Focus Management", () => {
    test("should maintain focus on interaction", async ({ page }) => {
      // Click on an element
      await page.getByRole("button", { name: /see the estimate|estimate cost/i }).click();

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
      // This asserted `expect(getByRole("alert")).toHaveCount(0)` on a clean
      // page — the OPPOSITE of the test's own name, and vacuous besides:
      // `#error-region` ships `hidden` (workspace.html:121) and `getByRole`
      // skips hidden nodes, so the count is 0 no matter what the app does.
      // The #131 guard caught it. What this test is actually for — and what
      // the sibling above does not cover — is that the error reaches a screen
      // reader BY ROLE, not merely that it is painted.
      await page.route("**/v1/query-runs", (route) => {
        route.fulfill({
          status: 500,
          body: JSON.stringify({ error: "Internal Server Error" }),
        });
      });

      await page.getByRole("textbox").fill("Test error");
      await page.getByRole("button", { name: /run now/i }).click();

      // NOT `getByRole("alert").first()`. `.first()` resolves in DOM order and
      // `#toast-region` (workspace.html:80) precedes `#error-region`
      // (workspace.html:121), while app.js:850 gives an error-tone toast
      // `role="alert"` too. That version bit today only by accident: a
      // reviewer kept a mutation that broke the banner, added the error toast
      // `handleError` already raises elsewhere (app.js:6949, :910), and the
      // test went green on the toast while the banner stayed hidden. Naming
      // the region keeps the role assertion — the point of this test — without
      // letting a different alert stand in for it.
      const errorAlert = page.locator("#error-region[role='alert']");
      await expect(errorAlert).toBeVisible();
      await expect(errorAlert).not.toBeEmpty();
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
      await expect(page.getByRole("button", { name: /see the estimate|estimate cost/i })).toBeVisible();
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