import { Page, Locator, expect } from "@playwright/test";

/**
 * Page Object for the Quorum-AI Workspace UI
 * Encapsulates all interactions with the workspace page
 */
export class WorkspacePage {
  readonly page: Page;

  // Question input
  readonly questionInput: Locator;

  // Action buttons
  readonly runNowButton: Locator;
  readonly estimateCostButton: Locator;
  readonly cancelRunButton: Locator;

  // Theme toggle
  readonly themeToggle: Locator;

  // Info/help buttons
  readonly costInfoButton: Locator;
  readonly runIdInfoButton: Locator;
  readonly synthesisInfoButton: Locator;
  readonly modelOutputsInfoButton: Locator;

  // Status elements
  readonly errorBanner: Locator;
  readonly driftBanner: Locator;
  readonly readyBanner: Locator;

  // Run ID display
  readonly runIdDisplay: Locator;

  // Cost display
  readonly costDisplay: Locator;

  // Proceed/Cancel modal buttons
  readonly proceedButton: Locator;
  readonly cancelModalButton: Locator;

  // Toast region for notifications
  readonly toastRegion: Locator;

  constructor(page: Page) {
    this.page = page;

    // Question input
    this.questionInput = page.getByRole("textbox", {
      name: /query|question|ask/i,
    });

    // Action buttons - using role and accessible names. The composer exposes
    // two run CTAs: "Run now" (direct) and "See the estimate →" (opens the
    // itemized cost gate first).
    this.runNowButton = page.getByRole("button", { name: /run now/i });
    this.estimateCostButton = page.getByRole("button", { name: /see the estimate|estimate cost/i });
    this.cancelRunButton = page.getByRole("button", { name: /cancel run/i });

    // Theme toggle
    this.themeToggle = page.getByRole("button", { name: /switch to (dark|light) theme/i });

    // Info buttons
    this.costInfoButton = page.getByRole("button", {
      name: /what does this cost estimate mean/i,
    });
    this.runIdInfoButton = page.getByRole("button", {
      name: /what is the run id/i,
    });
    this.synthesisInfoButton = page.getByRole("button", {
      name: /what is the synthesis/i,
    });
    this.modelOutputsInfoButton = page.getByRole("button", {
      name: /what are the model outputs/i,
    });

    // Status elements
    this.errorBanner = page.locator("#error-region");
    this.driftBanner = page.locator("#drift-region");
    this.readyBanner = page.locator("#readiness-banner");

    // Run ID
    this.runIdDisplay = page.getByRole("button", { name: /not started|copy run id/i });

    // Cost display
    this.costDisplay = page.locator("#cost-confirmation-message");

    // Modal buttons
    this.proceedButton = page.getByRole("button", { name: /proceed/i });
    this.cancelModalButton = page.getByRole("button", { name: /cancel/i }).nth(1);

    // Toast region
    this.toastRegion = page.locator(".toast-region, [aria-live]");
  }

  async goto() {
    await this.page.goto("/ui");
    await this.page.waitForLoadState("networkidle");
  }

  /**
   * Fill in a question and optionally submit it
   */
  async askQuestion(question: string, submit: boolean = false) {
    await this.questionInput.fill(question);
    if (submit) {
      await this.questionInput.press("Control+Enter");
      // Or click run button
      // await this.runNowButton.click();
    }
  }

  /**
   * Wait for the page to be fully loaded and ready
   */
  async waitForReady() {
    await this.page.waitForLoadState("networkidle");
    // Wait for any initial loading states to resolve
    await this.page.waitForTimeout(500);
  }

  /**
   * Check if an error is displayed
   */
  async hasError(): Promise<boolean> {
    return await this.errorBanner.isVisible().catch(() => false);
  }

  /**
   * Check if a drift warning is displayed
   */
  async hasDriftWarning(): Promise<boolean> {
    return await this.driftBanner.isVisible().catch(() => false);
  }

  /**
   * Dismiss any visible banners
   */
  async dismissBanners() {
    const dismissButtons = this.page.getByRole("button", { name: /dismiss/i });
    const count = await dismissButtons.count();
    for (let i = 0; i < count; i++) {
      await dismissButtons.nth(i).click().catch(() => {});
    }
  }

  /**
   * Toggle between light and dark theme
   */
  async toggleTheme() {
    await this.themeToggle.click();
    await this.page.waitForTimeout(300);
  }

  /**
   * Get current theme (light or dark)
   */
  async getCurrentTheme(): Promise<"light" | "dark"> {
    const htmlTheme = await this.page.locator("html").getAttribute("data-theme");
    return (htmlTheme === "dark" ? "dark" : "light") as "light" | "dark";
  }

  /**
   * Click estimate cost and return the cost estimate text
   */
  async estimateCost(): Promise<string> {
    await this.estimateCostButton.click();
    await this.page.waitForTimeout(1000); // Wait for cost calculation
    const costText = await this.costDisplay.textContent().catch(() => "");
    return costText || "";
  }

  /**
   * Get the run ID if one exists
   */
  async getRunId(): Promise<string | null> {
    const runId = await this.runIdDisplay.textContent().catch(() => null);
    if (runId && runId !== "Not started" && runId.trim() !== "") {
      return runId.trim();
    }
    return null;
  }
}