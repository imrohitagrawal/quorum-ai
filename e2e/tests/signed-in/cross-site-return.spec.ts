import { test, expect, type Page } from "@playwright/test";
import { markHelpSeen } from "../../fixtures/help";
import { recordWire, type WireLog } from "../../fixtures/wire-headers";

/**
 * W88 (CHG-067, failure mode F2): Google's return to the app is a CROSS-SITE
 * navigation, and the page it lands on must still work.
 *
 * Runs ONLY under `playwright.signed-in.config.ts` (app on 127.0.0.1:18096,
 * its loopback token stub on 18097). The other signed-in specs answer
 * Google's consent page with `route.fulfill({ status: 302 })` straight to the
 * callback, and Chromium then reports the return as same-origin, so they
 * would stay green if W88 refused every real return. Here the fulfilled 302
 * goes to the stub's TEST-ONLY `/bounce`, addressed as `localhost`, which
 * 302s to the app's callback: a real hop from another host, as from Google.
 * Each test checks the callback and the `/ui` after it were sent
 * `sec-fetch-site: cross-site` (read from the DevTools protocol, see
 * `fixtures/wire-headers.ts`), so it cannot pass on a same-origin return.
 */

const BOUNCE = "http://localhost:18097/bounce";

let counter = 0;
function freshAccount(label: string): { sub: string; email: string } {
  counter += 1;
  const sub = `1088${Date.now()}${counter}`;
  return { sub, email: `${label}.${sub}@example.com` };
}

/** Answer Google's consent page with a 302 to the bounce, which sends the browser to the callback. */
async function routeGoogleThroughBounce(
  page: Page,
  answer: { code: string } | { error: string },
): Promise<void> {
  await page.route("https://accounts.google.com/**", async (route) => {
    const asked = new URL(route.request().url());
    const state = asked.searchParams.get("state");
    expect(state, "the app's authorization URL carries a state").toBeTruthy();
    const back = new URL(asked.searchParams.get("redirect_uri") ?? "");
    if ("code" in answer) back.searchParams.set("code", answer.code);
    else back.searchParams.set("error", answer.error);
    back.searchParams.set("state", state ?? "");
    await route.fulfill({ status: 302, headers: { location: `${BOUNCE}?to=${encodeURIComponent(back.href)}` } });
  });
}

async function openAnonymous(page: Page): Promise<void> {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem("quorum.workspaceSeen", "1");
    } catch (_) {}
  });
  await markHelpSeen(page);
  await page.goto("/ui", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-view="composer"]')).toBeVisible();
}

/** The callback and the /ui after it, both sent as cross-site navigations. */
async function expectCrossSiteReturn(log: WireLog, landing: string): Promise<void> {
  const path = (h: { url: string }) => new URL(h.url).pathname;
  await expect
    .poll(() => {
      const hops = log();
      const at = hops.findIndex((h) => path(h) === "/v1/auth/google/callback");
      return at >= 0 && hops.slice(at + 1).some((h) => path(h) === "/ui");
    }, { timeout: 15000, message: "the browser went through the callback and on to /ui" })
    .toBe(true);
  const hops = log();
  const at = hops.findIndex((h) => path(h) === "/v1/auth/google/callback");
  const callback = hops[at];
  const after = hops.slice(at + 1).find((h) => path(h) === "/ui")!;
  expect(callback.status).toBe(303);
  expect(callback.sent["sec-fetch-site"]).toBe("cross-site");
  expect(new URL(after.url).search).toBe(landing);
  expect(after.sent["sec-fetch-site"]).toBe("cross-site");
  expect(after.sent["sec-fetch-mode"]).toBe("navigate");
  expect(after.sent["sec-fetch-dest"]).toBe("document");
  expect(after.status).toBe(200);
}

test.describe("Google's return arrives cross-site (W88)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "the lane runs on the reference engine only");

  test("a sign-in that returns from another site lands signed in on a working page", async ({ page }) => {
    // RED-IF: /ui refuses the cross-site navigation that follows Google's return, so every real sign-in ends on a 403 (F2).
    const account = freshAccount("w88");
    const log = await recordWire(page);
    await routeGoogleThroughBounce(page, { code: `${account.sub}|${account.email}` });
    await openAnonymous(page);
    await page.locator("#sign-in-google").click();
    await expect(page.locator("#account-email")).toHaveText(account.email);
    await expectCrossSiteReturn(log, "");
    await expect(page.locator("html")).toHaveAttribute("data-app-state", "ready");
    await expect(page.locator("#connection-pill-text")).toContainText("Session active");
    await expect(page.locator("#sign-out")).toBeVisible();
  });

  test("a sign-in cancelled at Google returns from another site to the failure notice", async ({ page }) => {
    // RED-IF: /ui?sign_in=failed reached cross-site from Google is refused, so a cancel ends on a 403 instead of the notice.
    const log = await recordWire(page);
    await routeGoogleThroughBounce(page, { error: "access_denied" });
    await openAnonymous(page);
    await page.locator("#sign-in-google").click();
    await expect(page.locator("#sign-in-notice")).toHaveText("Sign-in did not complete. Please try again.");
    await expectCrossSiteReturn(log, "?sign_in=failed");
    await expect(page.locator("#sign-in-google")).toBeVisible();
    await expect(page.locator("#connection-pill-text")).toContainText("Session active");
  });
});
