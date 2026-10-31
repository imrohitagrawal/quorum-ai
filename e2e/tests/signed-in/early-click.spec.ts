import { test, expect, type Page, type Request, type Route } from "@playwright/test";
import { markHelpSeen } from "../../fixtures/help";

/**
 * W121 (ADR-0188): a click made while the workspace is still starting waits
 * for the start-up it needs, instead of acting on a half-built page.
 *
 * Found from a CI trace (2026-10-30): the page's `GET /v1/session` took 411 ms,
 * an Estimate click landed inside that window, and the page showed "Cannot
 * read properties of undefined (reading 'trim')" (the model slots were still
 * placeholders) and never asked for the estimate; a write sent in the same
 * window went without its anti-forgery token and was refused (403). These
 * tests hold the start-up requests open until AFTER the click, check that
 * nothing was sent early, then release them and check the click completes.
 *
 * Runs ONLY under `playwright.signed-in.config.ts` (the real app with Google
 * sign-in on against a loopback stub; Google's consent page is caught with
 * `page.route`).
 */

const QUESTION = "How should a small team choose between Postgres and MySQL?";

let counter = 0;
/** A Google subject and email no other test in the run uses. */
function freshAccount(label: string): { sub: string; email: string } {
  counter += 1;
  const sub = `1121${Date.now()}${counter}`;
  return { sub, email: `${label}.${sub}@example.com` };
}

/** Catch Google's consent page and send the browser to the local callback. */
async function routeGoogle(page: Page, account: { sub: string; email: string }) {
  await page.route("https://accounts.google.com/**", async (route) => {
    const asked = new URL(route.request().url());
    const back = new URL(asked.searchParams.get("redirect_uri") ?? "");
    back.searchParams.set("code", `${account.sub}|${account.email}`);
    back.searchParams.set("state", asked.searchParams.get("state") ?? "");
    await route.fulfill({ status: 302, headers: { location: back.href } });
  });
}

/**
 * Hold every request to `path` until `release()` (or answer it with
 * `fail(status)`). Requests after the release go straight through.
 */
async function hold(page: Page, path: string) {
  let settle: (how: "continue" | number) => void = () => {};
  const decided = new Promise<"continue" | number>((resolve) => {
    settle = resolve;
  });
  let held = 0;
  await page.route(
    (url) => url.pathname === path,
    async (route: Route) => {
      held += 1;
      const how = await decided;
      if (how === "continue") await route.continue();
      else await route.fulfill({ status: how, contentType: "application/json", body: "{}" });
    },
  );
  return {
    release: () => settle("continue"),
    fail: (status: number) => settle(status),
    held: () => held,
  };
}

/** Every write the page sends, by path, in order. */
function recordWrites(page: Page): Request[] {
  const writes: Request[] = [];
  page.on("request", (request) => {
    if (request.method() !== "GET" && request.method() !== "HEAD") writes.push(request);
  });
  return writes;
}

const paths = (writes: Request[]) => writes.map((r) => new URL(r.url()).pathname);

/** The model ids the panel's drawn slots hold, in order. */
async function drawnPanel(page: Page): Promise<string[]> {
  // Read after the estimate: the cost gate then hides the composer, so the
  // selects are drawn but not visible.
  const slots = page.locator("select[data-model-slot]");
  await expect(slots).not.toHaveCount(0);
  return slots.evaluateAll((nodes) => nodes.map((n) => (n as HTMLSelectElement).value));
}

/** The card a failed start-up shows when the session request fails (it offers "Start a session"). */
const START_UP_500 = "Start a session to run a query";
const CRASH = "reading 'trim'";

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

test.describe("a click while the workspace is still starting (W121)", () => {
  test("Estimate before the session and models load waits, then prices the full panel with the session's token", async ({
    page,
  }) => {
    // RED-IF the click acts on the half-built page (today: the "reading
    // 'trim'" error card and no estimate request), the estimate is sent
    // before the session answers, or it carries no token or an old one.
    // Partner: once released, the estimate is asked for exactly once, with
    // the panel's models and the token the session answer gave.
    await page.setViewportSize({ width: 1440, height: 900 });
    const writes = recordWrites(page);
    const session = await hold(page, "/v1/session");
    await openWorkspace(page);
    await expect.poll(session.held).toBeGreaterThan(0);
    await page.locator("#query-text").fill(QUESTION);
    await page.locator("#estimate-run").click();
    await page.waitForTimeout(1000);
    expect(paths(writes), "nothing is written before the session answers").not.toContain(
      "/v1/query-runs/estimate",
    );
    await expect(page.locator("#error-region")).toBeHidden();

    const sessionAnswer = page.waitForResponse((r) => new URL(r.url()).pathname === "/v1/session");
    const estimate = page.waitForRequest((r) => new URL(r.url()).pathname === "/v1/query-runs/estimate");
    session.release();
    const token = ((await (await sessionAnswer).json()) as { csrf_token: string }).csrf_token;
    const sent = await estimate;
    expect(sent.headers()["x-csrf-token"], "the estimate carries the session's token").toBe(token);
    const body = sent.postDataJSON() as { model_slots: string[] };
    expect(body.model_slots, "the whole drawn panel is priced").toEqual(await drawnPanel(page));
    expect((await sent.response())?.status()).toBe(200);
    await expect(page.locator('[data-view="cost-gate"]')).toBeVisible({ timeout: 15000 });
    await expect(page.locator("#error-region")).toBeHidden();
    expect(paths(writes).filter((p) => p === "/v1/query-runs/estimate")).toHaveLength(1);
  });

  test("Estimate before the model list loads waits for it, then prices the full panel", async ({ page }) => {
    // RED-IF the click reads the model slots before the list is drawn
    // (today: the "reading 'trim'" error card) or prices an empty panel.
    // Partner: the session is not held here, so this is the model wait alone.
    await page.setViewportSize({ width: 1440, height: 900 });
    const writes = recordWrites(page);
    const defaults = await hold(page, "/v1/models/defaults");
    await openWorkspace(page);
    await expect.poll(defaults.held).toBeGreaterThan(0);
    await page.locator("#query-text").fill(QUESTION);
    await page.locator("#estimate-run").click();
    await page.waitForTimeout(1000);
    expect(paths(writes)).not.toContain("/v1/query-runs/estimate");
    await expect(page.locator("#error-region")).toBeHidden();

    const estimate = page.waitForRequest((r) => new URL(r.url()).pathname === "/v1/query-runs/estimate");
    defaults.release();
    const sent = await estimate;
    const body = sent.postDataJSON() as { model_slots: string[] };
    expect(body.model_slots, "the whole drawn panel is priced").toEqual(await drawnPanel(page));
    await expect(page.locator('[data-view="cost-gate"]')).toBeVisible({ timeout: 15000 });
    await expect(page.locator("#error-region")).toBeHidden();
  });

  test('"Sign in with Google" before the session loads waits, then signs in', async ({ page }) => {
    // RED-IF the sign-in start is sent before the session answers (today:
    // without a token, refused, and the visitor stays signed out). Partner:
    // once released, the Google stand-in is reached and the account shows.
    await page.setViewportSize({ width: 1440, height: 900 });
    const account = freshAccount("early-sign-in");
    await routeGoogle(page, account);
    const writes = recordWrites(page);
    const session = await hold(page, "/v1/session");
    await openWorkspace(page);
    await expect.poll(session.held).toBeGreaterThan(0);
    await page.locator("#sign-in-google").click();
    await page.waitForTimeout(1000);
    expect(paths(writes), "the sign-in start waits for the session").not.toContain("/v1/auth/google/start");

    const start = page.waitForRequest((r) => new URL(r.url()).pathname === "/v1/auth/google/start");
    session.release();
    const sent = await start;
    expect(sent.headers()["x-csrf-token"], "the sign-in start carries a token").toBeTruthy();
    await expect(page.locator("#account-email")).toHaveText(account.email, { timeout: 15000 });
  });

  test("a start-up that fails releases a waiting Estimate: it finishes and shows the start-up's error", async ({
    page,
  }) => {
    // RED-IF a failed start-up leaves the waiting click pending forever (the
    // button stays busy), or the released click crashes on the placeholder
    // slots and its "reading 'trim'" card replaces the start-up's own error.
    // Partner: the start-up's error is shown and the button is usable again.
    await page.setViewportSize({ width: 1440, height: 900 });
    const session = await hold(page, "/v1/session");
    await openWorkspace(page);
    await expect.poll(session.held).toBeGreaterThan(0);
    await page.locator("#query-text").fill(QUESTION);
    const button = page.locator("#estimate-run");
    await button.click();
    session.fail(500);
    await expect(button).not.toHaveAttribute("data-loading", "true", { timeout: 15000 });
    await expect(button).toBeEnabled();
    await expect(page.locator("#error-region")).toContainText(START_UP_500);
    await expect(page.locator("#error-region")).not.toContainText(CRASH);
  });

  test("Estimate after a start-up has already failed shows the start-up's error, not a crash", async ({ page }) => {
    // RED-IF a click after a failed start-up reads the placeholder slots
    // (today: the "reading 'trim'" card) or shows nothing at all. Partner:
    // the start-up's own error is shown again.
    await page.setViewportSize({ width: 1440, height: 900 });
    const session = await hold(page, "/v1/session");
    session.fail(500);
    await openWorkspace(page);
    await expect(page.locator("html")).toHaveAttribute("data-app-state", "error");
    await page.locator("#query-text").fill(QUESTION);
    await page.locator("#estimate-run").click();
    await expect(page.locator("#error-region")).toContainText(START_UP_500);
    await expect(page.locator("#error-region")).not.toContainText(CRASH);
    await expect(page.locator("#estimate-run")).toBeEnabled();
  });

  test('after "Start a session" recovers a failed start-up, Estimate prices the panel', async ({ page }) => {
    // RED-IF a recovered session still shows the first start-up's error on
    // Estimate (the start-up outcome read once, at load) instead of pricing
    // the panel the recovery drew. Partner: one estimate request, the cost
    // gate opens, and the start-up's card is gone.
    await page.setViewportSize({ width: 1440, height: 900 });
    let sessionCalls = 0;
    await page.route(
      (url) => url.pathname === "/v1/session",
      async (route) => {
        sessionCalls += 1;
        if (sessionCalls === 1) {
          await route.fulfill({ status: 500, contentType: "application/json", body: "{}" });
        } else {
          await route.continue();
        }
      },
    );
    const writes = recordWrites(page);
    await openWorkspace(page);
    await expect(page.locator("html")).toHaveAttribute("data-app-state", "error");
    const card = page.locator("#error-region");
    await expect(card).toContainText(START_UP_500);
    await card.getByRole("button", { name: "Start a session" }).click();
    await expect(page.getByText("Session started. You can run a query now.")).toBeVisible({ timeout: 15000 });
    await expect(card).toBeHidden();
    await page.locator("#query-text").fill(QUESTION);
    const estimate = page.waitForRequest((r) => new URL(r.url()).pathname === "/v1/query-runs/estimate");
    await page.locator("#estimate-run").click();
    const sent = await estimate;
    expect((sent.postDataJSON() as { model_slots: string[] }).model_slots).toEqual(await drawnPanel(page));
    await expect(page.locator('[data-view="cost-gate"]')).toBeVisible({ timeout: 15000 });
    await expect(card).toBeHidden();
    expect(paths(writes).filter((p) => p === "/v1/query-runs/estimate")).toHaveLength(1);
  });

  test("a model list that fails releases a waiting Estimate without a crash", async ({ page }) => {
    // RED-IF the released click reads the placeholder slots and its "reading
    // 'trim'" card replaces the start-up's error. Partner: the session step
    // succeeded, so this is the model step's failure alone; the button is
    // usable again.
    await page.setViewportSize({ width: 1440, height: 900 });
    const defaults = await hold(page, "/v1/models/defaults");
    await openWorkspace(page);
    await expect.poll(defaults.held).toBeGreaterThan(0);
    await page.locator("#query-text").fill(QUESTION);
    const button = page.locator("#estimate-run");
    await button.click();
    defaults.fail(500);
    await expect(button).not.toHaveAttribute("data-loading", "true", { timeout: 15000 });
    await expect(button).toBeEnabled();
    await expect(page.locator("#error-region")).toBeVisible();
    await expect(page.locator("#error-region")).not.toContainText(CRASH);
  });

  test('a session that fails releases a waiting "Sign in with Google": the start is sent and refused, never left waiting', async ({
    page,
  }) => {
    // RED-IF the session step is released only on success: the start then
    // waits for good and the button stays busy. Partner: the start goes out
    // once (the server refuses it without a token, as before this change)
    // and the button is usable again.
    await page.setViewportSize({ width: 1440, height: 900 });
    const writes = recordWrites(page);
    const session = await hold(page, "/v1/session");
    await openWorkspace(page);
    await expect.poll(session.held).toBeGreaterThan(0);
    const button = page.locator("#sign-in-google");
    await button.click();
    const start = page.waitForRequest((r) => new URL(r.url()).pathname === "/v1/auth/google/start");
    session.fail(500);
    expect([401, 403], "the server refuses a start sent without a session").toContain(
      (await (await start).response())?.status(),
    );
    await expect(button).toBeEnabled({ timeout: 15000 });
    expect(paths(writes).filter((p) => p === "/v1/auth/google/start")).toHaveLength(1);
  });

  test('after a start-up that throws in its own wiring, "Sign in with Google" is not left waiting', async ({
    page,
  }) => {
    // RED-IF a boot that fails before its start-up steps (here: a throw while
    // wiring the info icons, after the sign-in button is wired) leaves the
    // session step unsettled, so a later sign-in start waits for good.
    // Partner: the start goes out once and the button is usable again.
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.addInitScript(() => {
      const original = Document.prototype.querySelectorAll;
      Document.prototype.querySelectorAll = function (this: Document, selector: string) {
        if (typeof selector === "string" && selector.includes("data-info-icon")) {
          throw new Error("wiring broken on purpose (W121 test)");
        }
        return original.call(this, selector);
      } as typeof original;
    });
    const writes = recordWrites(page);
    await openWorkspace(page);
    await expect(page.locator("html")).toHaveAttribute("data-app-state", "error");
    const button = page.locator("#sign-in-google");
    const start = page.waitForRequest((r) => new URL(r.url()).pathname === "/v1/auth/google/start");
    await button.click();
    await start;
    await expect(button).toBeEnabled({ timeout: 15000 });
    expect(paths(writes).filter((p) => p === "/v1/auth/google/start")).toHaveLength(1);
  });
});
