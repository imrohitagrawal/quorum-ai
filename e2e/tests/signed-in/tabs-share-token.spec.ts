import { test, expect, type APIRequestContext, type BrowserContext, type Page } from "@playwright/test";
import {
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
 * THE SIGNED-IN BROWSER LANE (ADR-0142) — W105 (CHG-071, CHG-089): open tabs
 * share a renewed anti-forgery token, the cases that need sign-in or the
 * lane's test-only handlers. Runs ONLY under `playwright.signed-in.config.ts`.
 *
 * Nothing is mocked but Google's consent page (as in history-refresh.spec.ts)
 * and, in E7 only, the idle check's `idle_seconds_left` (as the idle tests in
 * history-refresh.spec.ts do). Two TEST-ONLY handlers on the loopback token
 * stub (port 18097, never the app): `/age-sessions` moves a session's start
 * back (session-max-age.spec.ts), and `/session-account` (added for W105)
 * reads which account a session belongs to, which an anonymous answer never
 * says.
 *
 * The owner's decisions: same person shares (CHG-071); another person does
 * not, "Do not share (Recommended)" (case 1); two anonymous sessions count as
 * the same person, "Accept it (Recommended)" (case 3).
 */

const STUB = "http://127.0.0.1:18097";
const HOUR = 3600;
const DELIVERY_MS = 400;

let counter = 0;
/** A Google subject and email no other test in the run uses. */
function freshAccount(label: string): { sub: string; email: string } {
  counter += 1;
  const sub = `1105${Date.now()}${counter}`;
  return { sub, email: `${label}.${sub}@example.com` };
}

/** Catch Google's consent page and send the browser to the local callback. */
async function routeGoogle(page: Page, account: { sub: string; email: string }) {
  await page.route("https://accounts.google.com/**", async (route) => {
    const asked = new URL(route.request().url());
    const state = asked.searchParams.get("state");
    expect(state, "the app's authorization URL carries a state").toBeTruthy();
    const back = new URL(asked.searchParams.get("redirect_uri") ?? "");
    back.searchParams.set("code", `${account.sub}|${account.email}`);
    back.searchParams.set("state", state ?? "");
    await route.fulfill({ status: 302, headers: { location: back.href } });
  });
}

/** A page in `context`, recorded and instrumented, at a booted `/ui`. */
async function openTab(context: BrowserContext): Promise<{ page: Page; wire: Wire }> {
  const page = await context.newPage();
  const wire = recordWire(page);
  await instrument(page);
  await markSeen(page);
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

async function sessionCookie(context: BrowserContext): Promise<string> {
  const cookie = (await context.cookies()).find(
    (c) => c.name === "quorum_session" || c.name === "__Host-quorum_session",
  );
  expect(cookie, "the browser holds a session cookie").toBeTruthy();
  return cookie?.value ?? "";
}

/** The account the browser's current session belongs to, on the server. */
async function sessionAccount(context: BrowserContext, request: APIRequestContext) {
  const sessionId = await sessionCookie(context);
  const answer = await request.post(`${STUB}/session-account`, { data: { session_id: sessionId } });
  expect(answer.status(), "the lane's test-only handler found the session").toBe(200);
  return { sessionId, accountId: String((await answer.json()).account_id) };
}

test.describe("open tabs share a renewed token, signed in (W105)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "the lane runs on the reference engine only");

  test("E2: a tab signed in as X takes X's token, and not the token of a tab that signed out", async ({
    context,
  }) => {
    // Case 1, "Do not share (Recommended)" (FM-1). RED-IF: the receiver
    // takes another identity's token (A, still showing X, would then write
    // as the new anonymous session). Partner, first: B's signed-in boot DID
    // pass its token to A (A's write carries it and succeeds), so the
    // refusal below is the identity rule, not a channel that never works.
    test.setTimeout(120000);
    const account = freshAccount("w105-other");
    const { page: a, wire: wireA } = await openTab(context);
    await signIn(a, wireA, account);
    await typeQuestion(a, wireA);

    const { page: b, wire: wireB } = await openTab(context);
    await expect(b.locator("#account-email")).toHaveText(account.email);
    const signedInToken = wireB.sessionAnswers[0];
    await a.waitForTimeout(DELIVERY_MS);
    const shared = await estimateWrite(a, wireA);
    expect(shared.header, "partner: B's signed-in renewal reached A").toBe(signedInToken);
    expect(shared.status).toBe(200);
    const signedInPost = (await recorded(b)).posts;
    expect(signedInPost.map((p) => p.kind)).toEqual(["csrf-token"]);
    expect(typeof signedInPost[0].identity).toBe("string");
    expect(signedInPost[0].identity).not.toBe("anonymous");

    const left = b.waitForEvent("load");
    await b.locator("#sign-out").click();
    await left;
    await expect(b.locator("#sign-in-google")).toBeVisible();
    await expectReady(b);
    await settle(wireB);
    const anonymousToken = wireB.sessionAnswers[wireB.sessionAnswers.length - 1];
    expect(anonymousToken).not.toBe(signedInToken);
    expect((await recorded(b)).posts.map((p) => p.identity), "B passed on an anonymous token").toEqual([
      "anonymous",
    ]);
    await a.waitForTimeout(DELIVERY_MS);

    const refused = await estimateWrite(a, wireA);
    expect(refused.header, "A kept X's token").toBe(signedInToken);
    expect(refused.header).not.toBe(anonymousToken);
    expect(refused.status).toBe(403);
    await expect(a.locator("#account-email")).toHaveText(account.email);
  });

  test("E6: an anonymous tab takes the token of a REPLACED anonymous session (case 3's known limit)", async ({
    browser,
    request,
  }) => {
    // Case 3, "Accept it (Recommended)", Codex finding 5: the page cannot
    // tell one anonymous session from another. A's session ends at its 24
    // hours (moved back with /age-sessions), B's /ui is given a new session
    // with a NEW account. RED-IF: A refuses B's token (the owner accepted
    // this limit; the ordinary anonymous case is the nav lane's E1). The
    // replacement is shown first: another session id AND another account.
    test.setTimeout(120000);
    const context = await browser.newContext();
    const { page: a, wire: wireA } = await openTab(context);
    await expect(a.locator("#sign-in-google")).toBeVisible(); // anonymous
    await typeQuestion(a, wireA);
    const before = await sessionAccount(context, request);
    const aged = await request.post(`${STUB}/age-sessions`, {
      data: { session_id: before.sessionId, age_seconds: 24 * HOUR + 60 },
    });
    expect(aged.status()).toBe(200);

    const { page: b, wire: wireB } = await openTab(context);
    const after = await sessionAccount(context, request);
    expect(after.sessionId, "B's /ui replaced the ended session").not.toBe(before.sessionId);
    expect(after.accountId, "with a different anonymous account").not.toBe(before.accountId);
    await a.waitForTimeout(DELIVERY_MS);

    const write = await estimateWrite(a, wireA);
    expect(write.header, "A took the replacement session's token").toBe(wireB.sessionAnswers[0]);
    expect(write.status).toBe(200);
    expect((await recorded(b)).posts.map((p) => p.identity)).toEqual(["anonymous"]);
    await context.close();
  });

  test("E7: after sharing, Stay signed in succeeds with the shared token and shows no failure", async ({
    context,
  }) => {
    // FM-15: the keep-active POST is protected by the token. The idle
    // reminder is reached as in history-refresh.spec.ts: a fake clock
    // (installed, then the page reloaded) jumped past the idle check, whose
    // REAL answer has `idle_seconds_left` set to 240 (the one mock).
    // "Stay signed in" then goes to the real keep-active. RED-IF: A's
    // keep-active carries A's retired token (403 and the toast "Could not
    // keep you signed in. Please try again."). Partner: the keep-active
    // request was sent, once, and the reminder closed.
    test.setTimeout(120000);
    const account = freshAccount("w105-stay");
    const { page: a, wire: wireA } = await openTab(context);
    await signIn(a, wireA, account);
    await a.route(
      (url) => url.pathname === "/v1/session/idle",
      async (route) => {
        const real = await route.fetch();
        const body = await real.json();
        expect(body.signed_in, "the real idle answer is for a signed-in session").toBe(true);
        await route.fulfill({ response: real, json: { ...body, idle_seconds_left: 240 } });
      },
    );
    await a.clock.install();
    await a.reload({ waitUntil: "domcontentloaded" });
    await expect(a.locator("#account-email")).toHaveText(account.email);
    await expectReady(a);

    const { wire: wireB } = await openTab(context);
    const sharedToken = wireB.sessionAnswers[0];
    await a.waitForTimeout(DELIVERY_MS);

    const reminder = a.locator("#idle-reminder");
    await expect(reminder).toBeHidden();
    await a.clock.fastForward("02:00:00");
    await expect(reminder).toBeVisible();
    const answered = a.waitForResponse((r) => new URL(r.url()).pathname === "/v1/session/keep-active");
    await a.locator("#idle-stay").click();
    expect((await answered).status()).toBe(200);
    await settle(wireA);
    const kept = wireA.writes.filter((w) => w.path === "/v1/session/keep-active");
    expect(kept).toHaveLength(1);
    expect(kept[0].header, "Stay signed in sent the token B passed on").toBe(sharedToken);
    await expect(reminder).toBeHidden();
    await expect(a.locator(".toast", { hasText: "Could not keep you signed in" })).toHaveCount(0);
  });
});
