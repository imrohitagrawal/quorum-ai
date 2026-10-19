import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { markHelpSeen } from "../../fixtures/help";

/**
 * THE SIGNED-IN BROWSER LANE (ADR-0142) — W87-1 (ADR-0174): a session ends at
 * a maximum age, 12 hours after sign-in or 24 hours after an anonymous mint.
 *
 * Runs ONLY under `playwright.signed-in.config.ts`. Nothing is mocked but
 * Google's consent page (caught with `page.route` and sent to the local
 * callback, as in history-refresh.spec.ts). A session is made OLD through the
 * lane's TEST-ONLY `/age-sessions` handler on the loopback token stub
 * (`e2e/servers/signed_in_server.py`, port 18097, never the app), which moves
 * the session's start back on the server. The server's own clock is real.
 *
 * The owner's words, verbatim:
 *   - CHG-066 (a): the warning 5 minutes before the 12 hours end;
 *   - CHG-063 (f)(2): the sentence after the 12 hours have ended;
 *   - CHG-066 (b): a signed-in run refused in the session's last 12 minutes;
 *   - CHG-069: an anonymous run refused in the session's last 12 minutes.
 */

const AGE_SESSIONS = "http://127.0.0.1:18097/age-sessions";
const HOUR = 3600;

const WARNING_AT_FIVE_MINUTES =
  "You will be signed out in about 5 minutes because 12 hours have passed since you signed in.";
const TWELVE_HOURS_ENDED =
  "You were signed out because 12 hours have passed since you signed in. Reload the page to sign in again.";
const SIGNED_IN_LATE_RUN = "Your session ends in less than 12 minutes. Sign in again, then run this question.";
/** CHG-070 (a): the refusal card's title, signed in and anonymous. */
const LATE_RUN_TITLE = "Your session ends soon";
/** CHG-070 (b): long enough that a person would mind retyping it. */
const LONG_QUESTION =
  "My grandmother's recipe for lemon cake uses 250 g of butter, 200 g of sugar, four eggs and the zest of " +
  "two lemons. If I swap half the butter for olive oil, how will the crumb, the rise and the keeping time " +
  "change, and should I lower the oven from 180 °C?";
const ANONYMOUS_LATE_RUN =
  "This session ends in less than 12 minutes, so this question cannot run now. " +
  "Sign in to keep going, or reload the page after the session ends.";
/** CHG-070 (c): the anonymous text where this page offers no sign-in. */
const NO_SIGN_IN_LATE_RUN =
  "This session ends in less than 12 minutes, so this question cannot run now. " +
  "Reload the page after the session ends.";
/** The top bar's own label (COPY-015): the card's action uses the same words. */
const SIGN_IN_LABEL = "Sign in with Google";

let counter = 0;
/** A Google subject and email no other test in the run uses. */
function freshAccount(label: string): { sub: string; email: string } {
  counter += 1;
  const sub = `1087${Date.now()}${counter}`;
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

/** The page's session now started `ageSeconds` ago, on the server. */
async function ageSession(page: Page, request: APIRequestContext, ageSeconds: number) {
  const cookies = await page.context().cookies();
  const session = cookies.find((c) => c.name === "quorum_session" || c.name === "__Host-quorum_session");
  expect(session, "the page holds a session cookie").toBeTruthy();
  const aged = await request.post(AGE_SESSIONS, {
    data: { session_id: session?.value ?? "", age_seconds: ageSeconds },
  });
  expect(aged.status(), "the lane's test-only handler found the session").toBe(200);
  expect((await aged.json()).cached, "the running app's own copy was aged").toBe(true);
}

/** Whether any value this tab holds in sessionStorage contains `text`. */
async function sessionStorageHolds(page: Page, text: string): Promise<boolean> {
  return page.evaluate(
    (wanted) =>
      Object.keys(window.sessionStorage).some((key) => (window.sessionStorage.getItem(key) ?? "").includes(wanted)),
    text,
  );
}

/**
 * Click a button that leaves for Google and comes back, and wait for the
 * page that comes back to finish loading. The page before the click already
 * shows the same email, so checking the email alone can pass before the
 * navigation and the next `page.evaluate` then dies with it (round 1: 2 of 9
 * runs, "Execution context was destroyed").
 */
async function clickThenNextPage(page: Page, button: ReturnType<Page["locator"]>) {
  const loaded = page.waitForEvent("load");
  await button.click();
  await loaded;
}

async function pressRun(page: Page, question: string) {
  await page.locator("#query-text").fill(question);
  await page.locator("#run-now").click();
}

/** Ask a question through the real composer and wait for the real result. */
async function runQuestion(page: Page, question: string) {
  await pressRun(page, question);
  const gateConfirm = page.locator("#gate-confirm");
  if (await gateConfirm.isVisible({ timeout: 8000 }).catch(() => false)) {
    await gateConfirm.click();
  }
  await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 60000 });
}

test.describe("a session ends at a maximum age (W87-1)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "the lane runs on the reference engine only");

  test("five minutes before the 12 hours end, the page warns without offering to stay", async ({
    page,
    request,
  }) => {
    // RED-IF: the page schedules its first check from the idle length only
    // (the warning would come ~115 minutes late), the words differ from
    // CHG-066 (a), or "Stay signed in" is offered (it cannot extend the 12
    // hours). Partner: "Sign out now" is still offered.
    const account = freshAccount("max-age-warn");
    await signIn(page, account);
    await ageSession(page, request, 12 * HOUR - 300);
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.locator("#account-email")).toHaveText(account.email);
    await expect(page.locator("#idle-reminder")).toBeVisible();
    await expect(page.locator("#idle-reminder-text")).toHaveText(WARNING_AT_FIVE_MINUTES);
    await expect(page.locator("#idle-sign-out")).toBeVisible();
    await expect(page.locator("#idle-stay")).toBeHidden();
  });

  test("after the 12 hours end, the page says so in the owner's words", async ({ page, request }) => {
    // RED-IF: the page shows the idle sentence ("nothing happening") for a
    // session ended by its 12 hours, or no reload line at all. The page's
    // next check is reached with a fake page clock; the server's end is real
    // (the session is aged past 12 hours on the server).
    const account = freshAccount("max-age-ended");
    await signIn(page, account);
    await ageSession(page, request, 12 * HOUR - 300);
    await page.clock.install();
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.locator("#account-email")).toHaveText(account.email);
    await page.clock.fastForward(2000);
    await expect(page.locator("#idle-reminder-text")).toHaveText(WARNING_AT_FIVE_MINUTES);

    await ageSession(page, request, 12 * HOUR + 1);
    await page.clock.fastForward("00:06:00");
    await expect(page.locator("#idle-reminder-text")).toHaveText(TWELVE_HOURS_ENDED);
    await expect(page.locator("#idle-reload")).toBeVisible();
    await expect(page.locator("#idle-stay")).toBeHidden();
  });

  test("a signed-in run in the last 12 minutes is refused, and runs after signing in again", async ({
    page,
    request,
  }) => {
    // RED-IF: the run starts with 10 minutes left (it could outlive the
    // session), the words differ from CHG-066 (b), there is no "Sign in
    // again", or signing in again does not let the same question run.
    test.setTimeout(120000);
    const account = freshAccount("max-age-late-run");
    const question = "Which is older, the Great Wall or the pyramids at Giza?";
    await signIn(page, account);
    await ageSession(page, request, 12 * HOUR - 600);
    await pressRun(page, question);
    await expect(page.locator("#error-region-title")).toHaveText(LATE_RUN_TITLE);
    await expect(page.locator("#error-region-message")).toHaveText(SIGNED_IN_LATE_RUN);
    const again = page.locator("#error-region-actions").getByRole("button", { name: "Sign in again", exact: true });
    await expect(again).toBeVisible();
    await again.click();
    await expect(page.locator("#account-email")).toHaveText(account.email);
    await runQuestion(page, question);
  });

  test("Sign in again from the late-run refusal keeps the typed question, once", async ({ page, request }) => {
    // CHG-070 (b). RED-IF: the question box is empty after the sign-in round
    // trip (the refusal text "Sign in again, then run this question" would
    // then be untrue for a long question), the saved copy is left in
    // sessionStorage, or a later fresh load of the page fills the box again.
    // Partner: the question really was in the box before the round trip.
    // Round 2 (break-it): RED-IF the question is put back before the model
    // slots exist (a page error, "Cannot read properties of undefined", and
    // the four per-model costs left at "—"). Partner: four cost cells exist.
    test.setTimeout(120000);
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    const account = freshAccount("max-age-keep-question");
    await signIn(page, account);
    await ageSession(page, request, 12 * HOUR - 600);
    await pressRun(page, LONG_QUESTION);
    await expect(page.locator("#query-text")).toHaveValue(LONG_QUESTION);
    await expect(page.locator("#error-region-message")).toHaveText(SIGNED_IN_LATE_RUN);
    await clickThenNextPage(
      page,
      page.locator("#error-region-actions").getByRole("button", { name: "Sign in again", exact: true }),
    );
    await expect(page.locator("html")).toHaveAttribute("data-app-state", "ready");
    await expect(page.locator("#account-email")).toHaveText(account.email);
    await expect(page.locator("#query-text")).toHaveValue(LONG_QUESTION);
    expect(await sessionStorageHolds(page, LONG_QUESTION)).toBe(false);
    const costs = page.locator(".model-slot-estimate");
    await expect(costs).toHaveCount(4);
    for (const cost of await costs.all()) {
      await expect(cost).not.toHaveText("—");
    }
    expect(pageErrors).toEqual([]);

    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await expect(page.locator("#account-email")).toHaveText(account.email);
    await expect(page.locator("#query-text")).toBeVisible();
    await expect(page.locator("#query-text")).toHaveValue("");
  });

  test("a plain sign-in, not from the refusal, puts no question back", async ({ page }) => {
    // CHG-070 (b), "nothing is saved for any other path". RED-IF: a sign-in
    // started from the top bar restores what was typed before it, or leaves a
    // copy in sessionStorage. Partner: the text really was typed, and the
    // sign-in really completed.
    const account = freshAccount("max-age-plain-sign-in");
    await routeGoogle(page, account);
    await openWorkspace(page);
    await page.locator("#query-text").fill(LONG_QUESTION);
    await expect(page.locator("#query-text")).toHaveValue(LONG_QUESTION);
    await page.locator("#sign-in-google").click();
    await expect(page.locator("#account-email")).toHaveText(account.email);
    await expect(page.locator("#query-text")).toBeVisible();
    await expect(page.locator("#query-text")).toHaveValue("");
    expect(await sessionStorageHolds(page, LONG_QUESTION)).toBe(false);
  });

  test("Sign in again as a different Google account does not put the first account's question back", async ({
    page,
    request,
  }) => {
    // Round 1 (journey E38). RED-IF: the question saved by account A's "Sign
    // in again" is restored on account B's page, or a copy of it is left in
    // sessionStorage. Partner: B really is signed in, and the same-account
    // round trip above does restore it.
    test.setTimeout(120000);
    const first = freshAccount("max-age-first-account");
    const second = freshAccount("max-age-second-account");
    await signIn(page, first);
    await ageSession(page, request, 12 * HOUR - 600);
    await pressRun(page, LONG_QUESTION);
    await expect(page.locator("#error-region-message")).toHaveText(SIGNED_IN_LATE_RUN);
    await page.unroute("https://accounts.google.com/**");
    await routeGoogle(page, second);
    await clickThenNextPage(
      page,
      page.locator("#error-region-actions").getByRole("button", { name: "Sign in again", exact: true }),
    );
    await expect(page.locator("#account-email")).toHaveText(second.email);
    await expect(page.locator("#query-text")).toBeVisible();
    await expect(page.locator("#query-text")).toHaveValue("");
    expect(await sessionStorageHolds(page, LONG_QUESTION)).toBe(false);
  });

  test("an anonymous run in the last 12 minutes is refused with its own words, and sign-in lets it run", async ({
    browser,
    request,
  }) => {
    // RED-IF: an anonymous session with 10 minutes left starts a run (its
    // result would be lost when the session ends), the words differ from
    // CHG-069, the action is not the top bar's "Sign in with Google"
    // (COPY-015), or signing in does not let the question run.
    test.setTimeout(120000);
    const context = await browser.newContext();
    const page = await context.newPage();
    const account = freshAccount("max-age-anonymous");
    const question = "How many moons does Mars have?";
    await routeGoogle(page, account);
    await openWorkspace(page);
    await expect(page.locator("#sign-in-google")).toBeVisible(); // anonymous, sign-in offered
    await ageSession(page, request, 24 * HOUR - 600);
    await pressRun(page, question);
    await expect(page.locator("#error-region-title")).toHaveText(LATE_RUN_TITLE);
    await expect(page.locator("#error-region-message")).toHaveText(ANONYMOUS_LATE_RUN);
    const signInAction = page.locator("#error-region-actions").getByRole("button", { name: SIGN_IN_LABEL, exact: true });
    await expect(signInAction).toBeVisible();
    await signInAction.click();
    await expect(page.locator("#account-email")).toHaveText(account.email);
    await runQuestion(page, question);
    await context.close();
  });

  test("on a host that does not offer sign-in, the anonymous refusal does not offer it either", async ({
    browser,
    request,
  }) => {
    // Round 1, CHG-070 (c). Sign-in is on, but this page is served on
    // `localhost`, not the redirect URI's `127.0.0.1`, so the top bar offers
    // no sign-in (as on the fly.dev host in production). RED-IF: the card
    // says "Sign in to keep going" here, or offers a sign-in action.
    // Partners: the composer rendered and the card shows its message, so "no
    // such button" is not true of an empty page.
    const context = await browser.newContext({ baseURL: "http://localhost:18096" });
    const page = await context.newPage();
    await openWorkspace(page);
    await expect(page.locator("#query-text")).toBeVisible(); // partner: the composer rendered
    await expect(page.locator("#sign-in-google")).toHaveCount(0); // not offered on this host
    await ageSession(page, request, 24 * HOUR - 600);
    await pressRun(page, "How many moons does Mars have?");
    await expect(page.locator("#error-region-title")).toHaveText(LATE_RUN_TITLE);
    await expect(page.locator("#error-region-message")).toHaveText(NO_SIGN_IN_LATE_RUN);
    await expect(page.locator("#error-region-actions")).toBeAttached(); // partner: the card's action row exists
    const actions = page.locator("#error-region-actions");
    for (const name of [SIGN_IN_LABEL, "Sign in", "Sign in again"]) {
      await expect(actions.getByRole("button", { name, exact: true })).toHaveCount(0);
    }
    await context.close();
  });

  test("a question saved under one account is not put back when another tab has switched the account", async ({
    browser,
    page,
    request,
  }) => {
    // Round 2 (Codex). Account A's "Sign in again" saves the question and
    // comes back as A, so the HTML shows A; but before the page's session
    // bootstrap answers, another tab has signed the browser in as B. RED-IF
    // the question is put back (it could then be run as B), or a copy is
    // left in sessionStorage. Partners: the page's HTML really is A's, and
    // the bootstrap really answered as B (the account id B's own bootstrap
    // gives). The same-account round trip above does restore the question.
    test.setTimeout(120000);
    const first = freshAccount("max-age-switch-a");
    const second = freshAccount("max-age-switch-b");
    const otherTab = await browser.newContext();
    const otherPage = await otherTab.newPage();
    await signIn(otherPage, second);
    const secondCookie = (await otherTab.cookies()).find(
      (c) => c.name === "quorum_session" || c.name === "__Host-quorum_session",
    );
    expect(secondCookie, "B holds a session cookie").toBeTruthy();
    const secondAccount = (await (await otherPage.request.get("/v1/session")).json()).account_id;
    expect(secondAccount, "B's bootstrap names B").toBeTruthy();

    await signIn(page, first);
    await ageSession(page, request, 12 * HOUR - 600);
    await pressRun(page, LONG_QUESTION);
    await expect(page.locator("#error-region-message")).toHaveText(SIGNED_IN_LATE_RUN);
    let bootstrapAccount = "";
    let switched = 0;
    await page.route("**/v1/session", async (route) => {
      if (switched > 0) {
        await route.continue();
        return;
      }
      switched += 1;
      const origin = new URL(route.request().url()).origin;
      await page.context().addCookies([{ name: secondCookie!.name, value: secondCookie!.value, url: origin }]);
      const headers = { ...(await route.request().allHeaders()) };
      headers["cookie"] = `${secondCookie!.name}=${secondCookie!.value}`;
      const response = await route.fetch({ headers });
      const body = await response.json();
      bootstrapAccount = String(body.account_id ?? "");
      await route.fulfill({ response, json: body });
    });
    await clickThenNextPage(
      page,
      page.locator("#error-region-actions").getByRole("button", { name: "Sign in again", exact: true }),
    );
    await expect(page.locator("html")).toHaveAttribute("data-app-state", "ready");
    await expect(page.locator("#query-text")).toHaveValue("");
    expect(await sessionStorageHolds(page, LONG_QUESTION)).toBe(false);
    await expect(page.locator("#account-email")).toHaveText(first.email); // partner: A's HTML
    expect(switched).toBe(1);
    expect(bootstrapAccount).toBe(secondAccount); // partner: the bootstrap answered as B
    await otherTab.close();
  });

  test("a signed-in page that does not offer sign-in is not told to sign in again", async ({
    browser,
    page,
    request,
  }) => {
    // Round 2 (break-it F2), CHG-070 (c). A signed-in session used on a host
    // that offers no sign-in (`localhost`, not the redirect URI's
    // `127.0.0.1`, as the fly.dev host in production): "Sign in again" would
    // reach a sign-in start that answers 404. RED-IF the card says "Sign in
    // again" or offers any sign-in action here. Partners: the page really is
    // signed in (its email shows), offers no sign-in, and the card shows its
    // message.
    const account = freshAccount("max-age-signed-in-no-sign-in");
    await signIn(page, account);
    const cookie = (await page.context().cookies()).find(
      (c) => c.name === "quorum_session" || c.name === "__Host-quorum_session",
    );
    expect(cookie, "the page holds a session cookie").toBeTruthy();
    const context = await browser.newContext({ baseURL: "http://localhost:18096" });
    await context.addCookies([{ name: cookie!.name, value: cookie!.value, url: "http://localhost:18096" }]);
    const other = await context.newPage();
    await openWorkspace(other);
    await expect(other.locator("#account-email")).toHaveText(account.email); // partner: signed in here
    await expect(other.locator("#sign-in-google")).toHaveCount(0); // not offered on this host
    await ageSession(other, request, 12 * HOUR - 600);
    await pressRun(other, "How many moons does Mars have?");
    await expect(other.locator("#error-region-title")).toHaveText(LATE_RUN_TITLE);
    await expect(other.locator("#error-region-message")).toHaveText(NO_SIGN_IN_LATE_RUN);
    await expect(other.locator("#error-region-actions")).toBeAttached();
    const actions = other.locator("#error-region-actions");
    for (const name of [SIGN_IN_LABEL, "Sign in", "Sign in again"]) {
      await expect(actions.getByRole("button", { name, exact: true })).toHaveCount(0);
    }
    await context.close();
  });
});
