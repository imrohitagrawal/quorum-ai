import { test, expect, type APIRequestContext, type BrowserContext, type Page } from "@playwright/test";
import { markHelpSeen } from "../../fixtures/help";

/**
 * THE SIGNED-IN BROWSER LANE (ADR-0142) — the W87-3 follow-up (CHG-088,
 * ADR-0176 amendment; plan §5): a signed-in cookie the server could not check
 * keeps its cookie and creates nothing.
 *
 * Runs ONLY under `playwright.signed-in.config.ts`. Nothing is mocked but
 * Google's consent page (caught with `page.route`, as in history-refresh.spec.ts)
 * and, in J5 only, the ORDER of one request (the page's first `/v1/session` is
 * held until the store is made not ready; its answer is the server's). The
 * store is put into each state through the lane's TEST-ONLY seams on the
 * loopback stub (`e2e/servers/signed_in_server.py`, port 18097, never the app):
 *   - `POST /store-ready` `{ready}`: the session store's readiness flag;
 *   - `POST /hold-store-lock` `{seconds}`: a thread holds the store lock;
 *   - `POST /unchecked-refresh-seconds` `{seconds}`: the page's refresh;
 *   - `GET /session-counts`: `{cached, mints}`.
 *
 * The owner's words, verbatim (CHG-088): the page's heading and body
 * ("Same, plus auto-reload"), the 401's sentence ("New code, retry in
 * place"), and the sign-in sentence ("Accept all", (1)). The card title
 * "Briefly unavailable" is the session's (plan §2.1.6).
 *
 * Every test restores the store and the refresh interval afterwards.
 */

const STUB = "http://127.0.0.1:18097";
const HEADING = "Your account is briefly unavailable";
const BODY =
  "Quorum could not check your sign-in just now. This usually clears within a minute. Nothing has been deleted.";
const UNCHECKED_401 = "We could not check your sign-in just now. Try again in a minute.";
const SIGN_IN_UNAVAILABLE = "Sign-in is briefly unavailable. Try again in a minute.";
const CARD_TITLE = "Briefly unavailable";
const CAPPED_HEADING_WORDS = "limit";
const SIGNED_OUT_AFTER = "You were signed out after";
const QUESTION =
  "Which is better for a small vegetable garden in a windy spot: raised beds or containers, and why?";

let counter = 0;
/** A Google subject and email no other test in the run uses. */
function freshAccount(label: string): { sub: string; email: string } {
  counter += 1;
  const sub = `1088${Date.now()}${counter}`;
  return { sub, email: `${label}.${sub}@example.com` };
}

/** Catch Google's consent page and send the browser to the local callback;
 * returns how many times it was asked. */
async function routeGoogle(page: Page, account: { sub: string; email: string }): Promise<{ hits: number }> {
  const seen = { hits: 0 };
  await page.route("https://accounts.google.com/**", async (route) => {
    seen.hits += 1;
    const asked = new URL(route.request().url());
    const state = asked.searchParams.get("state");
    expect(state, "the app's authorization URL carries a state").toBeTruthy();
    const back = new URL(asked.searchParams.get("redirect_uri") ?? "");
    back.searchParams.set("code", `${account.sub}|${account.email}`);
    back.searchParams.set("state", state ?? "");
    await route.fulfill({ status: 302, headers: { location: back.href } });
  });
  return seen;
}

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

async function signIn(page: Page, account: { sub: string; email: string }) {
  await routeGoogle(page, account);
  await openWorkspace(page);
  await page.locator("#sign-in-google").click();
  await expect(page.locator("#account-email")).toHaveText(account.email);
  await expect(page.locator('[data-view="composer"]')).toBeVisible();
}

async function seam(request: APIRequestContext, path: string, data: Record<string, unknown>) {
  const answer = await request.post(STUB + path, { data });
  expect(answer.status(), `the lane's test-only ${path} answered`).toBe(200);
  return answer.json();
}

async function counts(request: APIRequestContext): Promise<{ cached: number; mints: number }> {
  const answer = await request.get(STUB + "/session-counts");
  expect(answer.ok(), "the lane's test-only /session-counts answered").toBe(true);
  return answer.json();
}

async function sessionCookie(context: BrowserContext): Promise<string> {
  const cookies = await context.cookies();
  const session = cookies.find((c) => c.name === "quorum_session" || c.name === "__Host-quorum_session");
  expect(session, "the browser holds a session cookie").toBeTruthy();
  return session?.value ?? "";
}

async function expectUncheckedPage(page: Page) {
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(HEADING);
  await expect(page.getByText(BODY)).toBeVisible();
  await expect(page.locator("#unchecked-try-again")).toHaveText("Try again");
  await expect(page.locator("#unchecked-try-again")).toHaveAttribute("href", "/ui");
}

/** Ask a question through the real composer and wait for the real result. */
async function runQuestion(page: Page, question: string) {
  await page.locator("#query-text").fill(question);
  await page.locator("#run-now").click();
  const gateConfirm = page.locator("#gate-confirm");
  if (await gateConfirm.isVisible({ timeout: 8000 }).catch(() => false)) {
    await gateConfirm.click();
  }
  await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 60000 });
}

test.describe("a signed-in cookie the server could not check (W87-3 follow-up)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "the lane runs on the reference engine only");

  test.afterEach(async ({ request }) => {
    // The window never outlives its test (a later spec must find the store ready).
    await request.post(STUB + "/store-ready", { data: { ready: true } });
    await request.post(STUB + "/unchecked-refresh-seconds", { data: { seconds: 60 } });
  });

  for (const [width, height] of [
    [1440, 900],
    [390, 844],
  ] as const) {
    test(`J1 at ${width}: three reloads in the window keep her cookie and mint nothing, then the page comes back by itself`, async ({
      page,
      request,
    }, testInfo) => {
      // RED-IF: a reload in the window gets a new anonymous session (today:
      // 200 with a new cookie, then the 429 capped page on the third), sets a
      // cookie, or the page does not reload itself into her same sign-in.
      // Partners: the healthy reload DOES set a cookie; a cookie-less load
      // DOES move the mint count by 1.
      test.setTimeout(120000);
      await page.setViewportSize({ width, height });
      const account = freshAccount(`j1w${width}`);
      await signIn(page, account);
      const cookie = await sessionCookie(page.context());
      const healthy = await page.reload({ waitUntil: "domcontentloaded" });
      expect(await healthy?.headerValue("set-cookie"), "partner: a healthy load sets the cookie").toBeTruthy();
      await seam(request, "/store-ready", { ready: false });
      const before = await counts(request);
      for (let load = 1; load <= 3; load += 1) {
        const response = await page.reload({ waitUntil: "domcontentloaded" });
        expect(response?.status(), `load ${load} is the briefly-unavailable page`).toBe(503);
        expect(await response?.headerValue("set-cookie"), `load ${load} sets no cookie`).toBeNull();
        await expectUncheckedPage(page);
        await expect(page.getByRole("heading", { level: 1 })).not.toContainText(CAPPED_HEADING_WORDS);
      }
      const after = await counts(request);
      expect(after.mints - before.mints, "no mint in the window").toBe(0);
      expect(after.cached - before.cached, "no new cached session in the window").toBe(0);
      expect(await sessionCookie(page.context())).toBe(cookie);
      await page.screenshot({ path: testInfo.outputPath(`j1-unchecked-${width}.png`), fullPage: true });
      const fresh = await request.get("/ui");
      expect(fresh.status()).toBe(200);
      expect((await counts(request)).mints - after.mints, "partner: a cookie-less load mints exactly 1").toBe(1);
      await seam(request, "/unchecked-refresh-seconds", { seconds: 2 });
      await page.reload({ waitUntil: "domcontentloaded" });
      await expectUncheckedPage(page);
      const reloaded = page.waitForEvent("load", { timeout: 15000 });
      await seam(request, "/store-ready", { ready: true });
      await reloaded;
      // Settles plan §2.1.4's UNVERIFIED: Chromium follows a meta refresh on
      // a 503, and W88 lets that same-origin navigation through.
      await expect(page.locator("#account-email")).toHaveText(account.email, { timeout: 15000 });
      expect(await sessionCookie(page.context()), "her same cookie after the window").toBe(cookie);
    });
  }

  test("J1p at 390: the page fits the phone and follows the stored theme, light and dark", async ({
    page,
    request,
  }, testInfo) => {
    // RED-IF: the page scrolls sideways at 390 px, its heading or "Try again"
    // is below the first screen, or a stored dark theme is ignored (today the
    // page is not shown at all: the reload is the anonymous workspace).
    // Partner: the light theme is light.
    await page.setViewportSize({ width: 390, height: 844 });
    await signIn(page, freshAccount("j1p"));
    await seam(request, "/store-ready", { ready: false });
    for (const theme of ["light", "dark"] as const) {
      await page.evaluate((stored) => window.localStorage.setItem("quorum.theme", stored), theme);
      const response = await page.reload({ waitUntil: "domcontentloaded" });
      expect(response?.status()).toBe(503);
      await expectUncheckedPage(page);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      expect(scrollWidth, "no sideways scroll at 390 px").toBeLessThanOrEqual(390);
      for (const target of [page.getByRole("heading", { level: 1 }), page.locator("#unchecked-try-again")]) {
        const box = await target.boundingBox();
        expect(box, "the element is laid out").not.toBeNull();
        expect((box?.y ?? 9999) + (box?.height ?? 0), "inside the first screen").toBeLessThanOrEqual(844);
      }
      await page.screenshot({ path: testInfo.outputPath(`j1p-unchecked-390-${theme}.png`), fullPage: true });
    }
  });

  test("J2: Run in an open tab during the window keeps the question and retries in place", async ({
    page,
    request,
  }, testInfo) => {
    // RED-IF: the card is "Session expired" with "Refresh session" (today),
    // its action reloads the page, the question box is emptied, or "Try
    // again" does not send the same question. Partner: after the window the
    // retried request carries the question and is answered 200/202.
    test.setTimeout(120000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, freshAccount("j2"));
    await page.locator("#query-text").fill(QUESTION);
    await seam(request, "/store-ready", { ready: false });
    await page.locator("#run-now").click();
    await expect(page.locator("#error-region")).toBeVisible();
    await expect(page.locator("#error-region-title")).toHaveText(CARD_TITLE);
    await expect(page.locator("#error-region-message")).toHaveText(UNCHECKED_401);
    const retry = page.locator("#error-region-actions").getByRole("button", { name: "Try again" });
    await expect(retry).toHaveCount(1);
    await expect(page.locator("#query-text")).toHaveValue(QUESTION);
    await page.screenshot({ path: testInfo.outputPath("j2-card-1440.png") });
    await seam(request, "/store-ready", { ready: true });
    const carried = page.waitForRequest(
      (r) =>
        r.method() === "POST" &&
        new URL(r.url()).pathname.startsWith("/v1/query-runs") &&
        (r.postDataJSON() as { query_text?: string } | null)?.query_text === QUESTION,
      { timeout: 15000 },
    );
    const loaded = { reloaded: false };
    page.once("load", () => {
      loaded.reloaded = true;
    });
    await retry.click();
    const sent = await carried;
    const answered = await sent.response();
    expect([200, 202]).toContain(answered?.status());
    expect(loaded.reloaded, "retry in place: the page did not reload").toBe(false);
  });

  for (const [width, height] of [
    [1440, 900],
    [390, 844],
  ] as const) {
    test(`J3 at ${width}: "Sign in with Google" during the window stays on Quorum and says why`, async ({
      page,
      request,
    }, testInfo) => {
      // RED-IF: the visitor is sent to Google (today: the start answers 200
      // and the sign-in fails only on the way back), the toast is not the
      // owner's sentence, the button stays disabled, or the toast is off
      // screen at 390. Partner: ready, the same button reaches the Google
      // stand-in and signs in.
      await page.setViewportSize({ width, height });
      const account = freshAccount(`j3w${width}`);
      const google = await routeGoogle(page, account);
      await openWorkspace(page);
      await seam(request, "/store-ready", { ready: false });
      const button = page.locator("#sign-in-google");
      await button.click();
      const toast = page.locator("#toast-region").getByText(SIGN_IN_UNAVAILABLE);
      await expect(toast).toBeVisible();
      expect(google.hits, "no request reached the Google stand-in").toBe(0);
      expect(new URL(page.url()).pathname).toBe("/ui");
      await expect(button).toBeEnabled();
      const box = await toast.boundingBox();
      expect(box, "the toast is laid out").not.toBeNull();
      expect((box?.x ?? -1) >= 0 && (box?.x ?? 0) + (box?.width ?? 0) <= width, "inside the viewport").toBe(true);
      await page.screenshot({ path: testInfo.outputPath(`j3-toast-${width}.png`) });
      await seam(request, "/store-ready", { ready: true });
      await button.click();
      await expect(page.locator("#account-email")).toHaveText(account.email);
      expect(google.hits, "partner: the Google stand-in was reached").toBe(1);
    });
  }

  test("J4: a History refresh during the window keeps the rows and offers Try again", async ({ page, request }) => {
    // RED-IF: the rows are removed and "Your sign-in has changed ... Reload
    // the page" is shown (today's 401 handling), or "Try again" does not
    // refresh. Partner: after the window, Try again brings the fresh rows.
    test.setTimeout(150000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, freshAccount("j4"));
    await runQuestion(page, QUESTION);
    await expect(async () => {
      await openWorkspace(page);
      await expect(page.locator("#account-history-list .history-question").first()).toHaveText(QUESTION, {
        timeout: 1000,
      });
    }).toPass({ timeout: 20000 });
    const panel = page.locator("#account-history");
    const summary = page.locator("#account-history > summary");
    await summary.click();
    await expect(panel).toHaveAttribute("open", "");
    await expect(panel.locator(".history-question")).toHaveCount(1);
    await summary.click();
    await seam(request, "/store-ready", { ready: false });
    const refused = page.waitForResponse((r) => new URL(r.url()).pathname === "/v1/account/history");
    await summary.click();
    expect((await refused).status()).toBe(401);
    await expect(panel.getByText(UNCHECKED_401)).toBeVisible();
    await expect(page.locator("#account-history-reload")).toHaveCount(0);
    await expect(panel.locator(".history-question")).toHaveCount(1);
    const retry = panel.getByRole("button", { name: "Try again" });
    await expect(retry).toHaveCount(1);
    await seam(request, "/store-ready", { ready: true });
    const fresh = page.waitForResponse((r) => new URL(r.url()).pathname === "/v1/account/history");
    await retry.click();
    expect((await fresh).status()).toBe(200);
    await expect(panel.getByText(UNCHECKED_401)).toHaveCount(0);
    await expect(panel.locator(".history-question").first()).toHaveText(QUESTION);
  });

  test("J4c: the idle check during the window keeps checking and never says signed out", async ({
    page,
    request,
  }) => {
    // RED-IF: the idle reminder shows "You were signed out after ..." and
    // stops checking (today's 401 handling). Partners: a second idle request
    // goes out within 60 s of page time; after the window the check answers
    // 200 and the reminder stays hidden as before.
    test.setTimeout(120000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, freshAccount("j4c"));
    const idle: number[] = [];
    page.on("response", (r) => {
      if (new URL(r.url()).pathname === "/v1/session/idle") idle.push(r.status());
    });
    await page.clock.install();
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.locator("#account-email")).toBeVisible();
    await seam(request, "/store-ready", { ready: false });
    await page.clock.fastForward(2 * 60 * 60 * 1000);
    await expect.poll(() => idle.length, { message: "the first idle check went out" }).toBeGreaterThanOrEqual(1);
    expect(idle[0]).toBe(401);
    await expect(page.getByText(SIGNED_OUT_AFTER)).toHaveCount(0);
    await page.clock.runFor(61 * 1000);
    await expect.poll(() => idle.length, { message: "it checked again within 60 s" }).toBeGreaterThanOrEqual(2);
    await expect(page.getByText(SIGNED_OUT_AFTER)).toHaveCount(0);
    await seam(request, "/store-ready", { ready: true });
    const answered = idle.length;
    await page.clock.runFor(61 * 1000);
    await expect.poll(() => idle.length).toBeGreaterThan(answered);
    expect(idle[idle.length - 1]).toBe(200);
    await expect(page.locator("#idle-reminder")).toBeHidden();
  });

  test('J5: "Start a session" from the boot card during the window lands on the page, then her same sign-in', async ({
    page,
    request,
  }) => {
    // The owner's "Both doors" example: Asha's open tab presses "Start a
    // session" during the window. RED-IF: the tab's /v1/session gets a new
    // anonymous session (today: 200, so no card at all), or "Start a session"
    // does not land on the briefly-unavailable page. Partner: after the
    // window, "Try again" brings back her same sign-in.
    test.setTimeout(120000);
    await page.setViewportSize({ width: 1440, height: 900 });
    const account = freshAccount("j5");
    await signIn(page, account);
    const cookie = await sessionCookie(page.context());
    let held = false;
    await page.route("**/v1/session", async (route) => {
      if (!held) {
        // Only the ORDER changes: the store goes not ready before the page's
        // first /v1/session reaches the server; the answer is the server's.
        held = true;
        await seam(request, "/store-ready", { ready: false });
      }
      await route.continue();
    });
    await page.reload({ waitUntil: "domcontentloaded" });
    const start = page.locator("#error-region-actions").getByRole("button", { name: "Start a session" });
    await expect(start).toBeVisible();
    await page.unroute("**/v1/session");
    const landed = page.waitForEvent("load");
    await start.click();
    await landed;
    await expectUncheckedPage(page);
    await seam(request, "/store-ready", { ready: true });
    await page.locator("#unchecked-try-again").click();
    await expect(page.locator("#account-email")).toHaveText(account.email);
    expect(await sessionCookie(page.context())).toBe(cookie);
  });

  test("J6: a 3 s store-lock hold delays the reload but keeps her signed in", async ({ page, request }) => {
    // RED-IF: the reload gives a new anonymous cookie (today's 1.0 s bound
    // refuses after 1 s and mints, D2), or it does not wait out the hold.
    // Partner: the reload took at least about the hold, so the hold was met.
    test.setTimeout(90000);
    await page.setViewportSize({ width: 1440, height: 900 });
    const account = freshAccount("j6");
    await signIn(page, account);
    const cookie = await sessionCookie(page.context());
    await seam(request, "/hold-store-lock", { seconds: 3 });
    const started = Date.now();
    const response = await page.reload({ waitUntil: "domcontentloaded" });
    const took = Date.now() - started;
    expect(response?.status()).toBe(200);
    expect(took, "the reload met the hold").toBeGreaterThanOrEqual(2500);
    await expect(page.locator("#account-email")).toHaveText(account.email);
    expect(await sessionCookie(page.context()), "her same cookie").toBe(cookie);
  });
});
