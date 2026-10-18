import { test, expect, type Page } from "@playwright/test";
import { markHelpSeen } from "../../fixtures/help";

/**
 * W87-1 (ADR-0174; CHG-070 a, c): with Google sign-in switched OFF, the
 * anonymous late-run refusal must not offer to sign in.
 *
 * Runs on the main lane's server (`playwright.config.ts`), which configures no
 * Google client, so the page renders no "Sign in with Google" (checked below).
 * ONE route is mocked, and only because no seam can age a session on this
 * server: `/v1/query-runs/estimate` answers with the 409 the server sends for
 * an anonymous session with less than 12 minutes left while sign-in is off.
 * That body is pinned against the real server by
 * `tests/integration/test_late_run_refusal.py::
 * test_with_sign_in_off_the_anonymous_refusal_does_not_offer_sign_in`.
 */

const LATE_RUN_TITLE = "Your session ends soon";
const SIGN_IN_OFF_TEXT =
  "This session ends in less than 12 minutes, so this question cannot run now. " +
  "Reload the page after the session ends.";

async function openWorkspace(page: Page) {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem("quorum.workspaceSeen", "1");
    } catch (_) {}
  });
  await markHelpSeen(page);
  await page.goto("/ui", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-view="composer"]')).toBeVisible();
}

test.describe("the late-run refusal with sign-in off (W87-1, CHG-070)", () => {
  test("the anonymous card has the owner's title and words and no Sign in action", async ({ page }) => {
    // RED-IF: the card's title is not "Your session ends soon" (today it
    // would be "Something went wrong"), or the card offers "Sign in" /
    // "Sign in again" on a server where nobody can sign in. Partners: the
    // composer rendered, and the card itself is shown with the message, so
    // "no such button" is not true of an empty page.
    let refused = 0;
    await page.route("**/v1/query-runs/estimate", async (route) => {
      refused += 1;
      await route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({ detail: { code: "SESSION_ENDS_SOON", message: SIGN_IN_OFF_TEXT } }),
      });
    });
    await openWorkspace(page);
    await expect(page.locator("#sign-in-google")).toHaveCount(0); // sign-in is off on this server
    await page.locator("#query-text").fill("How many moons does Mars have?");
    await page.locator("#run-now").click();
    await expect(page.locator("#error-region-message")).toHaveText(SIGN_IN_OFF_TEXT);
    await expect(page.locator("#error-region-title")).toHaveText(LATE_RUN_TITLE);
    expect(refused).toBe(1);
    const actions = page.locator("#error-region-actions");
    await expect(actions.getByRole("button", { name: "Sign in", exact: true })).toHaveCount(0);
    await expect(actions.getByRole("button", { name: "Sign in again", exact: true })).toHaveCount(0);
  });
});
