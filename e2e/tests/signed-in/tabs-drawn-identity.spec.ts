import { test, expect, type Browser, type BrowserContext, type Page } from "@playwright/test";
import {
  ESTIMATE,
  estimateWrite,
  expectReady,
  instrument,
  markSeen,
  recordWire,
  recorded,
  settle,
  typeQuestion,
  type Wire,
} from "../../fixtures/tabs-share-token";

/**
 * THE SIGNED-IN BROWSER LANE (ADR-0142) — the W105 drawn-account guard (plan
 * addendum revision 3; round-2 break-it F1, probe S1). A tab drawn for a
 * known identity never keeps a renewed token for another known identity:
 * its next write is refused with "Security check failed", it saves nothing
 * and restores nothing, and it still passes the token to the answer's own
 * tabs. Runs ONLY under `playwright.signed-in.config.ts`.
 *
 * Written by the test designer before the build. Nothing is mocked but
 * Google's consent page and, where named, a DELAY on a request (never its
 * answer). The loopback token stub's TEST-ONLY `/session-account` (port 18097,
 * never the app) says which account a session belongs to.
 */

const STUB = "http://127.0.0.1:18097";
const KEY = "quorum.lateRunQuestion";
const DELIVERY_MS = 500;
const HOLD_MS = 7000;

let counter = 0;
/** A Google subject and email no other test in the run uses. */
function freshAccount(label: string): { sub: string; email: string } {
  counter += 1;
  const sub = `3105${Date.now()}${counter}`;
  return { sub, email: `${label}.${sub}@example.com` };
}

async function routeGoogle(page: Page, account: { sub: string; email: string }) {
  await page.route("https://accounts.google.com/**", async (route) => {
    const asked = new URL(route.request().url());
    const back = new URL(asked.searchParams.get("redirect_uri") ?? "");
    back.searchParams.set("code", `${account.sub}|${account.email}`);
    back.searchParams.set("state", asked.searchParams.get("state") ?? "");
    await route.fulfill({ status: 302, headers: { location: back.href } });
  });
}

/** Who each `/v1/session` answer of this page named: "account", "anonymous" or "unknown". */
function answersOf(page: Page): string[] {
  const seen: string[] = [];
  page.on("response", (response) => {
    const request = response.request();
    if (new URL(request.url()).pathname !== "/v1/session" || request.method() !== "GET") return;
    if (!response.ok()) return;
    response
      .json()
      .then((body) => seen.push(body.account_id ? "account" : body.anonymous === true ? "anonymous" : "unknown"))
      .catch(() => undefined);
  });
  return seen;
}

async function prep(page: Page): Promise<Wire> {
  const wire = recordWire(page);
  await instrument(page);
  await markSeen(page);
  return wire;
}

async function openTab(context: BrowserContext): Promise<{ page: Page; wire: Wire }> {
  const page = await context.newPage();
  const wire = await prep(page);
  await page.goto("/ui", { waitUntil: "domcontentloaded" });
  await expectReady(page);
  await settle(wire);
  return { page, wire };
}

async function signIn(page: Page, wire: Wire, account: { sub: string; email: string }) {
  await routeGoogle(page, account);
  const loaded = page.waitForEvent("load");
  await page.locator("#sign-in-google").click();
  await loaded;
  await expect(page.locator("#account-email")).toHaveText(account.email);
  await expectReady(page);
  await settle(wire);
}

async function shown(page: Page) {
  return page.evaluate(() => ({
    email: document.querySelector("#account-email")?.textContent ?? null,
    signInButton: !!document.querySelector("#sign-in-google"),
  }));
}

/** The account id behind `account`, learned in a context of its own (the account is keyed by the Google subject). */
async function accountIdOf(browser: Browser, account: { sub: string; email: string }): Promise<string> {
  const context = await browser.newContext();
  const { page, wire } = await openTab(context);
  await signIn(page, wire, account);
  const cookie = (await context.cookies()).find((c) => c.name === "quorum_session" || c.name === "__Host-quorum_session");
  const answer = await context.request.post(`${STUB}/session-account`, { data: { session_id: cookie?.value ?? "" } });
  expect(answer.status(), "the lane's test-only handler found the session").toBe(200);
  const id = String((await answer.json()).account_id);
  await context.close();
  return id;
}

/** Hold C's first `/v1/session` for HOLD_MS, so C holds the lock while other tabs queue behind it. */
async function holdTheLock(context: BrowserContext): Promise<Page> {
  const c = await context.newPage();
  await prep(c);
  let held = 0;
  await c.route("**/v1/session", async (route) => {
    held += 1;
    if (held === 1) await new Promise((r) => setTimeout(r, HOLD_MS));
    await route.continue();
  });
  void c.goto("/ui", { waitUntil: "domcontentloaded" }).catch(() => undefined);
  await c.waitForTimeout(800);
  expect(held, "C's first renewal is being held").toBe(1);
  return c;
}

/** Run one question to its result in `page` (local simulation, $0). */
async function runQuestion(page: Page, question: string) {
  const back = page.locator("#gate-back");
  if (await back.isVisible().catch(() => false)) await back.click();
  await page.locator("#query-text").fill(question);
  await page.locator("#run-now").click();
  const confirm = page.locator("#gate-confirm");
  if (await confirm.isVisible({ timeout: 5000 }).catch(() => false)) await confirm.click();
  await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 60000 });
}

async function historyQuestions(page: Page): Promise<string[]> {
  await page.reload({ waitUntil: "domcontentloaded" });
  await expectReady(page);
  return page.locator("#account-history-list .history-question").allTextContents();
}

test.describe("the drawn-account guard (W105)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "the lane runs on the reference engine only");

  test("S1 (G4): a tab drawn signed out and answered as Y after the lock wait is refused, saves nothing and restores nothing", async ({
    browser,
  }) => {
    // F1, probe S1-W105: A's estimate got 200, its run completed and its
    // question landed in Y's History. RED-IF: A keeps the token its first
    // answer brought for Y (the guard is missing, or the locked path skips
    // it), A puts Y's saved question back, or A's run reaches Y's History.
    // Partners: A's answer really named an account (the timing happened);
    // B (Y) runs and its own question IS in History; "Refresh session"
    // recovers A as Y.
    test.setTimeout(180000);
    const y = freshAccount("w105g-s1y");
    const yId = await accountIdOf(browser, y);
    const context = await browser.newContext();
    const { page: b, wire: wireB } = await openTab(context);
    await holdTheLock(context);
    const a = await context.newPage();
    const wireA = await prep(a);
    const aAnswers = answersOf(a);
    const savedAsY = `kept for Y ${Date.now()}`;
    await a.addInitScript(
      ([key, entry]) => {
        try {
          if (!sessionStorage.getItem("w105g.planted")) {
            sessionStorage.setItem("w105g.planted", "1");
            sessionStorage.setItem(key, entry);
          }
        } catch (_) {}
      },
      [KEY, JSON.stringify({ account: yId, question: savedAsY })],
    );
    await a.goto("/ui", { waitUntil: "commit" });
    await a.waitForSelector("#sign-in-google", { state: "attached" });
    await signIn(b, wireB, y);
    await expectReady(a);
    await settle(wireA);
    expect(aAnswers[0], "precondition: A's first answer came after the sign-in, for Y").toBe("account");
    expect(await shown(a), "A's page still shows the signed-out controls").toEqual({ email: null, signInButton: true });
    // Nothing restored from Y, and the entry is gone.
    await expect(a.locator("#query-text")).toHaveValue("");
    expect(await a.evaluate((key) => sessionStorage.getItem(key), KEY)).toBeNull();

    await a.waitForTimeout(DELIVERY_MS);
    await typeQuestion(a, wireA);
    const refused = await estimateWrite(a, wireA);
    expect(refused.status).toBe(403);
    await expect(a.locator("#error-region-title")).toHaveText("Security check failed");
    await expect(a.locator("#error-region-actions").getByRole("button", { name: "Refresh session", exact: true })).toBeVisible();

    // A tries to run: nothing it sends is accepted.
    const askedInA = `asked in the signed-out tab ${Date.now()}`;
    await a.locator("#error-region").isVisible();
    const back = a.locator("#gate-back");
    if (await back.isVisible().catch(() => false)) await back.click();
    await a.locator("#query-text").fill(askedInA);
    await a.locator("#run-now").click();
    await a.waitForTimeout(3000);
    await settle(wireA);
    const accepted = wireA.writes.filter(
      (w) => (w.path === ESTIMATE || w.path === "/v1/query-runs") && w.status !== null && w.status < 300,
    );
    expect(accepted, "no estimate or run from A was accepted").toEqual([]);

    // B, signed in as Y, works, and History holds B's question and not A's.
    const askedInB = `asked as Y in B ${Date.now()}`;
    await b.bringToFront();
    await runQuestion(b, askedInB);
    const history = await historyQuestions(b);
    expect(history, "partner: B's own question is in Y's History").toContain(askedInB);
    expect(history).not.toContain(askedInA);
    expect(history).not.toContain(savedAsY);

    // "Refresh session" recovers A, now drawn as Y.
    await a.bringToFront();
    const reloaded = a.waitForEvent("load");
    await a.locator("#error-region-actions").getByRole("button", { name: "Refresh session", exact: true }).click();
    await reloaded;
    await expectReady(a);
    await settle(wireA);
    await expect(a.locator("#account-email")).toHaveText(y.email);
    await typeQuestion(a, wireA);
    expect((await estimateWrite(a, wireA)).status).toBe(200);
    await context.close();
  });

  test("S1 partner (G2): the same lock wait with no sign-in is not refused", async ({ browser }) => {
    // The 403 in S1 is the identity rule, not the timing. RED-IF: a tab
    // drawn anonymous and answered anonymous after the same 7 s lock wait is
    // refused.
    test.setTimeout(120000);
    const context = await browser.newContext();
    await openTab(context);
    await holdTheLock(context);
    const a = await context.newPage();
    const wireA = await prep(a);
    const aAnswers = answersOf(a);
    await a.goto("/ui", { waitUntil: "domcontentloaded" });
    await expectReady(a);
    await settle(wireA);
    expect(aAnswers[0]).toBe("anonymous");
    expect(wireA.sessionRequestsAt.length).toBe(1);
    await typeQuestion(a, wireA);
    const write = await estimateWrite(a, wireA);
    expect(write.status).toBe(200);
    expect(write.header).toBe(wireA.sessionAnswers[0]);
    await context.close();
  });

  test("G4b: with sharing turned off in the page, a late app.js answered as Y is refused", async ({ browser }) => {
    // ADR-0178's first known limit, the older case (probe S1-todaySlowAppJs:
    // 200, the run completed, the question in Y's History). The page has no
    // Web Lock and no channel, so its renewal goes through `renewAlone`.
    // RED-IF: `renewAlone` keeps the token without the guard. Partners: A's
    // answer named an account, and A posted nothing (no channel).
    test.setTimeout(120000);
    const y = freshAccount("w105g-g4b");
    const context = await browser.newContext();
    const { page: b, wire: wireB } = await openTab(context);
    const a = await context.newPage();
    const wireA = await prep(a);
    const aAnswers = answersOf(a);
    await a.addInitScript(() => {
      Object.defineProperty(Navigator.prototype, "locks", { get: () => undefined, configurable: true });
      (window as unknown as { BroadcastChannel?: unknown }).BroadcastChannel = undefined;
    });
    let release: () => void = () => undefined;
    const gate = new Promise<void>((r) => (release = r));
    await a.route("**/static/app.js", async (route) => {
      await gate;
      await route.continue();
    });
    await a.goto("/ui", { waitUntil: "commit" });
    await a.waitForSelector("#sign-in-google", { state: "attached" });
    await signIn(b, wireB, y);
    release();
    await expectReady(a);
    await settle(wireA);
    expect(aAnswers[0], "precondition: A's first answer was Y's").toBe("account");
    expect(await shown(a)).toEqual({ email: null, signInButton: true });
    expect((await recorded(a)).posts).toEqual([]);
    await typeQuestion(a, wireA);
    const refused = await estimateWrite(a, wireA);
    expect(refused.status).toBe(403);
    await expect(a.locator("#error-region-title")).toHaveText("Security check failed");
    await context.close();
  });

  test("G7: B, signed in as Y, keeps working after A's refused renewal, with the token A passed on", async ({
    browser,
  }) => {
    // Design point 4 (Codex finding 5): `/v1/session` rotated the server's
    // token when A renewed, so B's own token is retired. RED-IF: the refused
    // tab A posts nothing, or posts under its drawn identity (B would hold a
    // retired token and get 403). Partners: A's own write is refused, and
    // B's write carries A's token, not B's own.
    test.setTimeout(120000);
    const y = freshAccount("w105g-g7");
    const context = await browser.newContext();
    const { page: b, wire: wireB } = await openTab(context);
    const a = await context.newPage();
    const wireA = await prep(a);
    const aAnswers = answersOf(a);
    let release: () => void = () => undefined;
    const gate = new Promise<void>((r) => (release = r));
    await a.route("**/static/app.js", async (route) => {
      await gate;
      await route.continue();
    });
    await a.goto("/ui", { waitUntil: "commit" });
    await a.waitForSelector("#sign-in-google", { state: "attached" });
    await signIn(b, wireB, y);
    await typeQuestion(b, wireB);
    const bOwn = wireB.sessionAnswers[wireB.sessionAnswers.length - 1];
    release();
    await expectReady(a);
    await settle(wireA);
    expect(aAnswers[0]).toBe("account");
    const aPosts = (await recorded(a)).posts;
    expect(aPosts.length, "A posted its renewal once").toBe(1);
    expect(typeof aPosts[0].identity).toBe("string");
    expect(aPosts[0].identity, "under the answer's identity, not the drawn one").not.toBe("anonymous");
    await b.waitForTimeout(DELIVERY_MS);

    const bWrite = await estimateWrite(b, wireB);
    expect(bWrite.header, "B took A's token").toBe(wireA.sessionAnswers[0]);
    expect(bWrite.header).not.toBe(bOwn);
    expect(bWrite.status).toBe(200);

    await a.bringToFront();
    await typeQuestion(a, wireA);
    expect((await estimateWrite(a, wireA)).status, "A itself stays refused").toBe(403);
    await context.close();
  });

  test("partner (G1): two tabs of one signed-in account still share the token", async ({ browser }) => {
    // E1's shape for a signed-in account. RED-IF: the guard refuses a tab
    // drawn and answered as the same account, or stops it taking a
    // same-account token.
    test.setTimeout(120000);
    const x = freshAccount("w105g-g1");
    const context = await browser.newContext();
    const { page: a, wire: wireA } = await openTab(context);
    await signIn(a, wireA, x);
    await typeQuestion(a, wireA);
    const { page: b, wire: wireB } = await openTab(context);
    await expect(b.locator("#account-email")).toHaveText(x.email);
    await a.waitForTimeout(DELIVERY_MS);
    const write = await estimateWrite(a, wireA);
    expect(write.header, "A took B's token").toBe(wireB.sessionAnswers[0]);
    expect(write.status).toBe(200);
    await context.close();
  });

  test("partner (G1): a same-account reload is not refused, and passes its token on", async ({ browser }) => {
    // RED-IF: a reload drawn and answered as the same account is refused,
    // or the reloaded tab stops posting to the account's other tab.
    test.setTimeout(120000);
    const x = freshAccount("w105g-reload");
    const context = await browser.newContext();
    const { page: a, wire: wireA } = await openTab(context);
    await signIn(a, wireA, x);
    const { page: b, wire: wireB } = await openTab(context);
    await typeQuestion(b, wireB);
    await a.reload({ waitUntil: "domcontentloaded" });
    await expectReady(a);
    await settle(wireA);
    await expect(a.locator("#account-email")).toHaveText(x.email);
    await typeQuestion(a, wireA);
    const aWrite = await estimateWrite(a, wireA);
    expect(aWrite.status).toBe(200);
    expect(aWrite.header).toBe(wireA.sessionAnswers[wireA.sessionAnswers.length - 1]);
    await b.waitForTimeout(DELIVERY_MS);
    const bWrite = await estimateWrite(b, wireB);
    expect(bWrite.header, "B took the reloaded tab's token").toBe(wireA.sessionAnswers[wireA.sessionAnswers.length - 1]);
    expect(bWrite.status).toBe(200);
    await context.close();
  });
});
