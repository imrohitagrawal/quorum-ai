import { test, expect } from "@playwright/test";
import { boot } from "../../fixtures/golden-run";

/**
 * REAL-INTEGRATION SMOKE — the counter to the "e2e that isn't e2e" problem.
 *
 * Every other spec in this repo mocks the backend with `page.route`, so they
 * verify the frontend against synthetic JSON and never exercise the real
 * request/response/poll contract. This spec drives the ACTUAL FastAPI backend
 * that Playwright's webServer already self-starts in local-simulation mode
 * (OPENROUTER_LIVE_EXECUTION_ENABLED=false — free, deterministic, no live LLM),
 * with NO page.route anywhere. It proves the composer → estimate → run → poll →
 * result pipeline works end-to-end against a real server.
 *
 * Deliberately asserts on user-visible behaviour, not on mocked shapes.
 */

test.describe("real-integration smoke (no mocks)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "smoke runs on the reference engine only");

  test("a question drives a real backend run to the result view", async ({ page }) => {
    // Guard: fail loudly if anyone adds a page-level mock to this spec later.
    // (Best-effort: catches the common `page.route(...)`; does not intercept
    // context-level / HAR routing — documented, not claimed airtight.)
    let mocked = false;
    const origRoute = page.route.bind(page);
    (page as unknown as { route: typeof page.route }).route = ((...args: Parameters<typeof origRoute>) => {
      mocked = true;
      return origRoute(...args);
    }) as typeof page.route;

    await boot(page);
    await page.getByRole("textbox").first().fill(
      "What are the key metrics for measuring SaaS customer retention?"
    );

    // Direct-run CTA. Against the real sim backend the estimate is computed
    // server-side; on an allow-band estimate it auto-proceeds to the live run.
    // If it lands in a confirm band, clear the gate first.
    await page.locator("#run-now").click();
    const gateConfirm = page.locator("#gate-confirm");
    if (await gateConfirm.isVisible({ timeout: 8000 }).catch(() => false)) {
      await gateConfirm.click();
    }
    // Fast-fail instead of hanging to the 90s verdict wait if the real sim
    // estimate ever lands in the hard-block band (no confirm button to click).
    const blocked = page.locator('#cost-review-card[data-band="block"]');
    if (await blocked.isVisible().catch(() => false)) {
      throw new Error("sim estimate hit the block band — smoke query needs a cheaper fixture");
    }

    // The real run must reach a POPULATED terminal result via genuine polling.
    // `data-consensus` is set only once the backend synthesis lands — the same
    // "result is ready" signal the mocked suites key on.
    const verdict = page.locator("#result-verdict[data-consensus]");
    await expect(verdict).toBeVisible({ timeout: 90000 });
    await expect(verdict).not.toBeEmpty();

    expect(mocked, "this smoke must NOT use page.route — it exercises the real backend").toBe(false);
  });
});
