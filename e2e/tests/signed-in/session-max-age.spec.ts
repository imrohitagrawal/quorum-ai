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
const ANONYMOUS_LATE_RUN =
  "This session ends in less than 12 minutes, so this question cannot run now. " +
  "Sign in to keep going, or reload the page after the session ends.";

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
    await expect(page.locator("#error-region-message")).toHaveText(SIGNED_IN_LATE_RUN);
    const again = page.locator("#error-region-actions").getByRole("button", { name: "Sign in again", exact: true });
    await expect(again).toBeVisible();
    await again.click();
    await expect(page.locator("#account-email")).toHaveText(account.email);
    await runQuestion(page, question);
  });

  test("an anonymous run in the last 12 minutes is refused with its own words, and sign-in lets it run", async ({
    browser,
    request,
  }) => {
    // RED-IF: an anonymous session with 10 minutes left starts a run (its
    // result would be lost when the session ends), the words differ from
    // CHG-069, the action is not "Sign in", or signing in does not let the
    // question run.
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
    await expect(page.locator("#error-region-message")).toHaveText(ANONYMOUS_LATE_RUN);
    const signInAction = page.locator("#error-region-actions").getByRole("button", { name: "Sign in", exact: true });
    await expect(signInAction).toBeVisible();
    await signInAction.click();
    await expect(page.locator("#account-email")).toHaveText(account.email);
    await runQuestion(page, question);
    await context.close();
  });
});
