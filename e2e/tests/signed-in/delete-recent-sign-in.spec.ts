import { test, expect, type APIRequestContext, type Page, type Route } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { markHelpSeen } from "../../fixtures/help";

/**
 * THE SIGNED-IN BROWSER LANE (ADR-0142) — W87-2 (ADR-0175): deleting an
 * account needs a Google sign-in within the last 10 minutes.
 *
 * Runs ONLY under `playwright.signed-in.config.ts`. Nothing is mocked but
 * Google's consent page (caught with `page.route` and sent to the local
 * callback, as in session-max-age.spec.ts). A session is made OLD through the
 * lane's TEST-ONLY `/age-sessions` handler on the loopback token stub
 * (`e2e/servers/signed_in_server.py`, port 18097, never the app). The
 * server's own clock is real.
 *
 * The owner's words, verbatim:
 *   - CHG-063 (f)(1): the sentence before a deletion that needs a new sign-in;
 *   - CHG-073 (d): the line after another account came back;
 *   - CHG-063 (e): the 2-Step line beside "Sign in with Google".
 */

const AGE_SESSIONS = "http://127.0.0.1:18097/age-sessions";
const HOUR = 3600;
const MINUTE = 60;
const KEY = "quorum.lateRunQuestion";

const RECENT_SIGN_IN =
  "For your safety, sign in with Google again before deleting your account. " +
  "If you are still signed in to Google it takes one click.";
const TWO_STEP = "We sign you in with Google. Turn on 2-Step Verification in your Google account to protect it.";
const SIGN_IN_FAILED = "Sign-in did not complete. Please try again.";
const SIGNED_IN_LATE_RUN = "Your session ends in less than 12 minutes. Sign in again, then run this question.";
const ANONYMOUS_LATE_RUN =
  "This session ends in less than 12 minutes, so this question cannot run now. " +
  "Sign in to keep going, or reload the page after the session ends.";
const SIGN_IN_LABEL = "Sign in with Google";
const QUESTION = "Which is older, the Great Wall or the pyramids at Giza?";

function switchedLine(email: string): string {
  return `You are now signed in as ${email}. Nothing was deleted. To delete this account, press "Delete my account" again.`;
}

let counter = 0;
/** A Google subject and email no other test in the run uses. */
function freshAccount(label: string): { sub: string; email: string } {
  counter += 1;
  const sub = `1088${Date.now()}${counter}`;
  return { sub, email: `${label}.${sub}@example.com` };
}

type Account = { sub: string; email: string };

/** Send Google's consent page straight back to the local callback. */
async function backToCallback(route: Route, params: Record<string, string>) {
  const asked = new URL(route.request().url());
  const state = asked.searchParams.get("state");
  expect(state, "the app's authorization URL carries a state").toBeTruthy();
  const back = new URL(asked.searchParams.get("redirect_uri") ?? "");
  for (const [name, value] of Object.entries(params)) back.searchParams.set(name, value);
  back.searchParams.set("state", state ?? "");
  await route.fulfill({ status: 302, headers: { location: back.href } });
}

async function routeGoogle(page: Page, account: Account) {
  await page.unroute("https://accounts.google.com/**");
  await page.route("https://accounts.google.com/**", (route) =>
    backToCallback(route, { code: `${account.sub}|${account.email}` }),
  );
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

async function signIn(page: Page, account: Account) {
  await routeGoogle(page, account);
  await openWorkspace(page);
  await page.locator("#sign-in-google").click();
  await expect(page.locator("#account-email")).toHaveText(account.email);
  await expect(page.locator('[data-view="composer"]')).toBeVisible();
}

async function sessionCookie(page: Page) {
  const cookies = await page.context().cookies();
  const session = cookies.find((c) => c.name === "quorum_session" || c.name === "__Host-quorum_session");
  expect(session, "the page holds a session cookie").toBeTruthy();
  return session!;
}

async function ageById(request: APIRequestContext, sessionId: string, ageSeconds: number) {
  const aged = await request.post(AGE_SESSIONS, { data: { session_id: sessionId, age_seconds: ageSeconds } });
  expect(aged.status(), "the lane's test-only handler found the session").toBe(200);
}

/** The page's session now started `ageSeconds` ago, on the server. */
async function ageSession(page: Page, request: APIRequestContext, ageSeconds: number) {
  await ageById(request, (await sessionCookie(page)).value, ageSeconds);
}

async function clickThenNextPage(page: Page, button: ReturnType<Page["locator"]>) {
  const loaded = page.waitForEvent("load");
  await button.click();
  await loaded;
}

async function openAccountPanel(page: Page) {
  const history = page.locator("#account-history");
  if ((await history.getAttribute("open")) === null) {
    await page.locator("#account-history > summary").click();
  }
  await expect(history).toHaveAttribute("open", "");
}

async function pressRun(page: Page, question: string) {
  await page.locator("#query-text").fill(question);
  await page.locator("#run-now").click();
}

async function runQuestion(page: Page, question: string) {
  await pressRun(page, question);
  const gateConfirm = page.locator("#gate-confirm");
  if (await gateConfirm.isVisible({ timeout: 8000 }).catch(() => false)) {
    await gateConfirm.click();
  }
  await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 60000 });
}

/** Walk the three delete steps with `email` and press "Delete permanently". */
async function deleteWith(page: Page, email: string): Promise<number> {
  await page.locator("#account-delete-start").click();
  await expect(page.locator("#account-delete-reminder")).toBeVisible();
  await page.locator("#account-delete-email").fill(email);
  await page.locator("#account-delete-continue").click();
  await expect(page.locator("#account-delete-final")).toBeVisible();
  const answered = page.waitForResponse((r) => r.url().endsWith("/v1/account/delete"));
  await page.locator("#account-delete-confirm").click();
  return (await answered).status();
}

async function savedQuestion(page: Page): Promise<string | null> {
  return page.evaluate((key) => window.sessionStorage.getItem(key), KEY);
}

test.describe("deleting an account needs a recent sign-in (W87-2)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "the lane runs on the reference engine only");

  test("signed in 11 minutes ago, Delete my account asks for a new sign-in and then deletes", async ({
    page,
    request,
  }) => {
    // CHG-056 (d). RED-IF: the reminder opens without a new sign-in, the
    // words differ from CHG-063 (f)(1), the same account does not come back
    // with the panel open and focus on "Delete my account…", the
    // `account=` marker stays in the address, or the deletion then fails.
    // Partner: the reminder step stays hidden while the sign-in step shows.
    test.setTimeout(120000);
    const account = freshAccount("recent-delete");
    await signIn(page, account);
    await ageSession(page, request, 11 * MINUTE);
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.locator("#account-email")).toHaveText(account.email);
    await openAccountPanel(page);
    await page.locator("#account-delete-start").click();
    const step = page.locator("#account-delete-reauth-step");
    await expect(step).toBeVisible();
    await expect(step).toContainText(RECENT_SIGN_IN);
    await expect(page.locator("#account-delete-reminder")).toBeHidden();

    await clickThenNextPage(page, page.locator("#account-delete-reauth"));
    await expect(page.locator("html")).toHaveAttribute("data-app-state", "ready");
    await expect(page.locator("#account-email")).toHaveText(account.email);
    await expect(page.locator("#account-history")).toHaveAttribute("open", "");
    await expect(page.locator("#account-delete-start")).toBeFocused();
    expect(page.url()).not.toContain("account=");
    expect(page.url()).toContain("/ui");

    expect(await deleteWith(page, account.email)).toBe(200);
    await expect(page.locator("#sign-in-google")).toBeVisible();
  });

  test("a page loaded fresh and then aged past 10 minutes is refused by the server and shows the same step", async ({
    page,
    request,
  }) => {
    // FM-14, FM-52: the page's own deadline is only for the visitor; the
    // server is the control. RED-IF: "Delete permanently" deletes a session
    // signed in more than 10 minutes ago, or the refusal shows anything but
    // the sign-in step. Partner: the account is still signed in after it.
    test.setTimeout(120000);
    const account = freshAccount("recent-delete-late");
    await signIn(page, account);
    await openAccountPanel(page);
    await page.locator("#account-delete-start").click();
    await expect(page.locator("#account-delete-reminder")).toBeVisible();
    await page.locator("#account-delete-email").fill(account.email);
    await page.locator("#account-delete-continue").click();
    await expect(page.locator("#account-delete-final")).toBeVisible();
    await ageSession(page, request, 11 * MINUTE);
    const answered = page.waitForResponse((r) => r.url().endsWith("/v1/account/delete"));
    await page.locator("#account-delete-confirm").click();
    const response = await answered;
    expect(response.status()).toBe(403);
    expect((await response.json()).detail.code).toBe("RECENT_SIGN_IN_REQUIRED");
    const step = page.locator("#account-delete-reauth-step");
    await expect(step).toBeVisible();
    await expect(step).toContainText(RECENT_SIGN_IN);
    await expect(page.locator("#account-delete-final")).toBeHidden();
    await expect(page.locator("#account-email")).toHaveText(account.email);
  });

  test("another account at the new sign-in is told nothing was deleted, and A is kept", async ({
    page,
    request,
  }) => {
    // CHG-066 (c), CHG-073 (d). RED-IF: the other account is refused,
    // the panel does not say (in the owner's words, with B's email) that
    // nothing was deleted, A is deleted or loses its history, or B is asked
    // to sign in again before deleting with B's own email. Partners: B is
    // really signed in; A's history really lists A's question afterwards.
    test.setTimeout(240000);
    const first = freshAccount("recent-delete-a");
    const second = freshAccount("recent-delete-b");
    await signIn(page, first);
    await runQuestion(page, QUESTION);
    await ageSession(page, request, 11 * MINUTE);
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await expect(page.locator("#account-email")).toHaveText(first.email);
    await openAccountPanel(page);
    await page.locator("#account-delete-start").click();
    await expect(page.locator("#account-delete-reauth-step")).toBeVisible();
    await routeGoogle(page, second);
    await clickThenNextPage(page, page.locator("#account-delete-reauth"));
    await expect(page.locator("html")).toHaveAttribute("data-app-state", "ready");
    await expect(page.locator("#account-email")).toHaveText(second.email);
    await expect(page.locator("#account-history")).toHaveAttribute("open", "");
    const line = page.locator("#account-history").getByRole("status").filter({ hasText: "Nothing was deleted." });
    await expect(line).toHaveCount(1);
    await expect(line).toHaveText(switchedLine(second.email));
    expect(page.url()).not.toContain("account=");

    expect(await deleteWith(page, second.email)).toBe(200);
    await expect(page.locator("#sign-in-google")).toBeVisible();

    await routeGoogle(page, first);
    await page.locator("#sign-in-google").click();
    await expect(page.locator("#account-email")).toHaveText(first.email);
    await openAccountPanel(page);
    await expect(page.locator("#account-history-list .history-question").first()).toHaveText(QUESTION);
  });

  test("a cancel at Google shows the failure notice on the signed-in page", async ({ page, request }) => {
    // FM-48. RED-IF: a signed-in visitor who cancels at Google comes back to
    // a page that says nothing. Partner: the page is still signed in.
    const account = freshAccount("recent-delete-cancel");
    await signIn(page, account);
    await ageSession(page, request, 11 * MINUTE);
    await page.reload({ waitUntil: "domcontentloaded" });
    await openAccountPanel(page);
    await page.locator("#account-delete-start").click();
    await expect(page.locator("#account-delete-reauth-step")).toBeVisible();
    await page.unroute("https://accounts.google.com/**");
    await page.route("https://accounts.google.com/**", (route) => backToCallback(route, { error: "access_denied" }));
    await clickThenNextPage(page, page.locator("#account-delete-reauth"));
    await expect(page.locator("#account-email")).toHaveText(account.email);
    await expect(page.locator("#sign-in-notice")).toHaveText(SIGN_IN_FAILED);
  });

  test("a sign-in that crosses the 12 hours brings the visitor back signed in", async ({ page, request }) => {
    // FM-47. The session is at 12 h - 60 s when "Sign in again" leaves for
    // Google, and Google's page (the route handler) ages it past 12 hours
    // before it sends the browser back. RED-IF: the visitor comes back to
    // "Sign-in did not complete" or signed out. Partners: the handler really
    // aged the session; the same account's question is put back.
    test.setTimeout(120000);
    const account = freshAccount("recent-delete-cross");
    await signIn(page, account);
    await ageSession(page, request, 12 * HOUR - MINUTE);
    await pressRun(page, QUESTION);
    await expect(page.locator("#error-region-message")).toHaveText(SIGNED_IN_LATE_RUN);
    const cookie = await sessionCookie(page);
    let agedOnTheWay = 0;
    await page.unroute("https://accounts.google.com/**");
    await page.route("https://accounts.google.com/**", async (route) => {
      await ageById(request, cookie.value, 12 * HOUR + MINUTE);
      agedOnTheWay += 1;
      await backToCallback(route, { code: `${account.sub}|${account.email}` });
    });
    await clickThenNextPage(
      page,
      page.locator("#error-region-actions").getByRole("button", { name: "Sign in again", exact: true }),
    );
    await expect(page.locator("html")).toHaveAttribute("data-app-state", "ready");
    expect(agedOnTheWay).toBe(1);
    await expect(page.locator("#account-email")).toHaveText(account.email);
    expect(page.url()).not.toContain("sign_in=failed");
    await expect(page.locator("#sign-in-notice")).toHaveCount(0);
    await expect(page.locator("#query-text")).toHaveValue(QUESTION);
  });

  test("the 2-Step line sits beside Sign in with Google at 1440 and 390 px", async ({ browser }) => {
    // CHG-063 (e), CHG-073 (e). RED-IF: the line is missing from the
    // anonymous top bar, is not in the header, makes the page scroll
    // sideways at either width, or fails axe there. Partner: axe judged some
    // nodes at each width.
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    await openWorkspace(page);
    const header = page.locator("header");
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await expect(header.locator("#sign-in-google"), `${width} px`).toBeVisible();
      await expect(header.getByText(TWO_STEP, { exact: true }), `${width} px`).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, `${width} px: no sideways scroll`).toBeLessThanOrEqual(0);
      const results = await new AxeBuilder({ page }).include("header").withTags(["wcag2a", "wcag2aa"]).analyze();
      const judged = [...results.passes, ...results.violations].reduce((n, r) => n + r.nodes.length, 0);
      expect(judged, `${width} px: axe judged the header`).toBeGreaterThan(0);
      expect(
        results.violations.map((v) => v.id),
        `${width} px`,
      ).toEqual([]);
    }
    await context.close();
  });

  test("the anonymous card saves under the account the bootstrap names, not the markup", async ({
    browser,
    page,
    request,
  }) => {
    // Codex finding 2. The page's HTML is anonymous, but its session
    // bootstrap is answered with signed-in account B's cookie. RED-IF the
    // card's "Sign in with Google" saves the question as anonymous (it could
    // then be put back for another account), or saves nothing. Partners: the
    // HTML really is anonymous, and the bootstrap really named B.
    test.setTimeout(120000);
    const other = await browser.newContext();
    const otherPage = await other.newPage();
    const b = freshAccount("recent-delete-stale-b");
    await signIn(otherPage, b);
    const bCookie = await sessionCookie(otherPage);
    const bAccount = (await (await otherPage.request.get("/v1/session")).json()).account_id;
    expect(bAccount, "B's bootstrap names B").toBeTruthy();

    let bootstrapAccount = "";
    await page.route("**/v1/session", async (route) => {
      const origin = new URL(route.request().url()).origin;
      await page.context().addCookies([{ name: bCookie.name, value: bCookie.value, url: origin }]);
      const headers = { ...(await route.request().allHeaders()) };
      headers["cookie"] = `${bCookie.name}=${bCookie.value}`;
      const response = await route.fetch({ headers });
      const body = await response.json();
      bootstrapAccount = String(body.account_id ?? "");
      await route.fulfill({ response, json: body });
    });
    await page.route("https://accounts.google.com/**", (route) => route.fulfill({ status: 204 }));
    await openWorkspace(page);
    await expect(page.locator("#sign-in-google")).toHaveCount(1); // partner: anonymous HTML
    await expect(page.locator("#account-email")).toHaveCount(0);
    await expect(page.locator("html")).toHaveAttribute("data-app-state", "ready");
    expect(bootstrapAccount).toBe(bAccount); // partner: the bootstrap named B

    await ageById(request, bCookie.value, 12 * HOUR - 10 * MINUTE);
    await pressRun(page, QUESTION);
    await expect(page.locator("#error-region-message")).toHaveText(SIGNED_IN_LATE_RUN);
    const started = page.waitForResponse((r) => r.url().endsWith("/v1/auth/google/start"));
    await page.locator("#error-region-actions").getByRole("button", { name: SIGN_IN_LABEL, exact: true }).click();
    expect((await started).status()).toBe(200);
    await expect.poll(() => savedQuestion(page)).not.toBeNull();
    const saved = JSON.parse((await savedQuestion(page)) ?? "{}");
    expect(saved.account).toBe(bAccount);
    expect(saved.question).toBe(QUESTION);
    expect(saved).not.toHaveProperty("anonymous");
    await other.close();
  });

  test("a bootstrap that cannot tell the session's kind saves nothing", async ({ page, request }) => {
    // Codex re-check (CRITICAL_BLOCKER). The anonymous page's bootstrap comes
    // back with neither `anonymous` nor `account_id`. RED-IF the card's "Sign
    // in with Google" saves the question anyway (a missing account read as
    // anonymous). Partner, in the same test: a second load with the real
    // answer (`anonymous: true`) saves an anonymous entry.
    test.setTimeout(120000);
    let stripped = 0;
    await page.route("**/v1/session", async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      delete body.anonymous;
      delete body.account_id;
      stripped += 1;
      await route.fulfill({ response, json: body });
    });
    await page.route("https://accounts.google.com/**", (route) => route.fulfill({ status: 204 }));
    await openWorkspace(page);
    await expect(page.locator("#sign-in-google")).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-app-state", "ready");
    expect(stripped).toBeGreaterThan(0);
    await ageSession(page, request, 24 * HOUR - 10 * MINUTE);
    await pressRun(page, QUESTION);
    await expect(page.locator("#error-region-message")).toHaveText(ANONYMOUS_LATE_RUN);
    const card = page.locator("#error-region-actions").getByRole("button", { name: SIGN_IN_LABEL, exact: true });
    let started = page.waitForResponse((r) => r.url().endsWith("/v1/auth/google/start"));
    await card.click();
    expect((await started).status()).toBe(200);
    expect(await savedQuestion(page)).toBeNull();

    await page.unroute("**/v1/session");
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.locator("html")).toHaveAttribute("data-app-state", "ready");
    await pressRun(page, QUESTION);
    await expect(page.locator("#error-region-message")).toHaveText(ANONYMOUS_LATE_RUN);
    started = page.waitForResponse((r) => r.url().endsWith("/v1/auth/google/start"));
    await card.click();
    expect((await started).status()).toBe(200);
    await expect.poll(() => savedQuestion(page)).not.toBeNull();
    const saved = JSON.parse((await savedQuestion(page)) ?? "{}");
    expect(saved.anonymous).toBe(true);
    expect(typeof saved.saved_at).toBe("number");
    expect(saved.question).toBe(QUESTION);
    expect(saved).not.toHaveProperty("account");
  });
});
