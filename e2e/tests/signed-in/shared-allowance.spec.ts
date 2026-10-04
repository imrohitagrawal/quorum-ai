import { test, expect, type Browser, type Page, type Response } from "@playwright/test";
import { LIMIT_RESPONSES } from "../../fixtures/limit-responses";

/**
 * W47 (ADR-0144 decision 6) on the SIGNED-IN lane: the page says the anonymous
 * allowance is shared by everyone on this network who is not signed in and,
 * because sign-in is available here, that signing in gives a person their own
 * $0.40; a signed-in page's allowance never mentions the network.
 *
 * Runs ONLY under `playwright.signed-in.config.ts` (fresh temporary databases
 * per launch, live execution off, $0). Every browser of this lane connects
 * from 127.0.0.1, so every ANONYMOUS session here is on ONE network and shares
 * one allowance -- which is exactly what the last test drives: one anonymous
 * session spends the network's $0.40, a brand-new anonymous session is blocked
 * by it at once, and signing in gives that person their own allowance back.
 * The only mock is Google's consent page, as in `history-refresh.spec.ts`.
 *
 * ORDER MATTERS: the tests that need an anonymous estimate that is NOT blocked
 * come before the one that spends the network's allowance (workers: 1,
 * fullyParallel: false in this lane's config).
 *
 * Copy is asserted as key phrases (ADR-0144 gives no sentence): "this
 * network", "not signed in", and the offer `\bsign in\b`, which "signed in"
 * does not match.
 */

const ESTIMATE = "/v1/query-runs/estimate";
const QUESTIONS = [
  "What are the key metrics for measuring SaaS customer retention?",
  "How should a small team choose between Postgres and MySQL?",
  "What is a sensible on-call rotation for a team of five engineers?",
  "Which questions should we ask before adopting a feature-flag service?",
  "How do we decide when a monolith should be split into services?",
  "What should a first incident post-mortem template contain?",
];
const SIGN_IN_OFFER = /\bsign in\b/i;

let counter = 0;
/** A Google subject and email no other test in the run uses. */
function freshAccount(label: string): { sub: string; email: string } {
  counter += 1;
  const sub = `1094${Date.now()}${counter}`;
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
  await page.goto("/ui", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-view="composer"]')).toBeVisible();
}

async function signInFromHere(page: Page, account: { sub: string; email: string }) {
  await routeGoogle(page, account);
  await page.locator("#sign-in-google").click();
  await expect(page.locator("#account-email")).toHaveText(account.email);
  await expect(page.locator('[data-view="composer"]')).toBeVisible();
}

/** A new browser (its own cookie jar, so a new anonymous session) on this lane's one network. */
async function newAnonymousPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext();
  const page = await context.newPage();
  await openWorkspace(page);
  return page;
}

const isEstimate = (r: Response) => new URL(r.url()).pathname === ESTIMATE && r.request().method() === "POST";
const gateView = (page: Page) => page.locator('[data-view="cost-gate"]');
const card = (page: Page) => page.locator("#cost-review-card");
const allowanceLine = (page: Page) => page.locator("#cost-gate-allowance");
/** A control INSIDE the cost card that starts sign-in (W47 review round 1): the offer must be actionable where it is read. */
const cardSignIn = (page: Page) =>
  card(page).getByRole("button", { name: /sign in/i }).or(card(page).getByRole("link", { name: /sign in/i }));
const isSignInStart = (r: { url(): string; method(): string }) =>
  new URL(r.url()).pathname === "/v1/auth/google/start" && r.method() === "POST";

/** Ask for the estimate of `question` from the composer; returns the server's estimate JSON (read, not mocked). */
async function seeEstimate(page: Page, question: string): Promise<Record<string, any>> {
  await page.locator("#query-text").fill(question);
  const answered = page.waitForResponse(isEstimate);
  await page.locator("#estimate-run").click();
  const body = await (await answered).json();
  await expect(gateView(page)).toBeVisible({ timeout: 15000 });
  await expect(card(page)).toHaveAttribute("data-band", body.cost_estimate.threshold_action);
  return body;
}

/** From the gate: run it, wait for the result, and go back to an empty composer. */
async function confirmAndReturn(page: Page) {
  await page.locator("#gate-confirm").click();
  await expect(page.locator('[data-view="result"] #result-verdict[data-consensus]')).toBeVisible({ timeout: 60000 });
  await page.locator('[data-view="result"]').getByRole("button", { name: "New question", exact: true }).click();
  await expect(page.locator('[data-view="composer"]')).toBeVisible();
}

test.describe("W47 — the allowance is shared by the network while not signed in", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "the lane runs on the reference engine only");

  test("an anonymous estimate says the allowance is shared on this network and offers signing in for your own", async ({ browser }) => {
    // RED-IF: an anonymous allow-band estimate's allowance line does not say it is shared by everyone on
    // this network who is not signed in, or (sign-in being available here) does not offer signing in
    // (ADR-0144 decision 6), or the server does not flag the allowance `shared_by_network: true`.
    const page = await newAnonymousPage(browser);
    // Partner: this page really is anonymous with sign-in on offer.
    await expect(page.locator("#sign-in-google")).toBeVisible();

    const body = await seeEstimate(page, QUESTIONS[0]);

    expect(body.cost_estimate.threshold_action, "an allow-band estimate (nothing spent on this network yet)").toBe("allow");
    await expect(allowanceLine(page)).toBeVisible();
    const line = await allowanceLine(page).innerText();
    // Partner (green today): it is still decision 6's allowance line, with the figure of $0.40 left.
    expect(line).toMatch(/of \$0\.40 left in the last 24 hours/);
    expect(line).toMatch(/this network/i);
    expect(line).toMatch(/not signed in/i);
    expect(line).toMatch(SIGN_IN_OFFER);
    expect(body.cost_estimate.daily_allowance.shared_by_network).toBe(true);
    await page.context().close();
  });

  test("the shared card's sign-in offer is a control in the card that starts sign-in", async ({ browser }) => {
    // RED-IF: the shared allowance's "Sign in to get your own $0.40 a day" is only text (the one way to
    // act on it is the top bar's button, scrolled out of sight on a long card), or the in-card control
    // does not start the same sign-in as `#sign-in-google` (POST /v1/auth/google/start, then Google's
    // consent page, caught here). Partners: the top-bar sign-in exists, the card shows the shared
    // sentence, and the person ends up signed in.
    const page = await newAnonymousPage(browser);
    const account = freshAccount("w47-card-sign-in");
    await routeGoogle(page, account);
    await expect(page.locator("#sign-in-google")).toBeVisible();

    const body = await seeEstimate(page, QUESTIONS[2]);
    expect(body.cost_estimate.threshold_action).toBe("allow");
    await expect(card(page)).toContainText(/this network/i);

    const control = cardSignIn(page);
    await expect(control).toBeVisible();
    const started = page.waitForRequest(isSignInStart);
    await control.click();
    await started;
    await expect(page.locator("#account-email")).toHaveText(account.email);
    await page.context().close();
  });

  test("a signed-in estimate's allowance line does not mention the network", async ({ page }) => {
    // RED-IF: a signed-in account's allowance line says "network" (its $0.40 is its own, ADR-0144
    // decision 3), or the server flags it shared. Partner: the line is shown and is the allowance line.
    await openWorkspace(page);
    await signInFromHere(page, freshAccount("w47-own"));

    const body = await seeEstimate(page, QUESTIONS[1]);

    await expect(allowanceLine(page)).toBeVisible();
    const line = await allowanceLine(page).innerText();
    expect(line).toMatch(/left in the last 24 hours/);
    expect(line).not.toMatch(/network/i);
    expect(body.cost_estimate.daily_allowance.shared_by_network).toBe(false);
    // W47 review round 1: an own allowance offers no sign-in in the card (partner of the test above).
    await expect(cardSignIn(page)).toHaveCount(0);
  });

  test("a new anonymous session is blocked by the network's spend, the block says so, and signing in gives an own allowance", async ({ browser }) => {
    // RED-IF: after one anonymous session spends the network's $0.40, a brand-new anonymous session on the
    // same network is NOT blocked with `daily_cap` (today it starts fresh), or its block card does not say
    // the allowance is shared on this network by people not signed in and offer signing in; or, once that
    // person signs in, the allowance is not their own whole $0.40 with no mention of the network.
    const spender = await newAnonymousPage(browser);
    let body: Record<string, any> = {};
    let ran = 0;
    for (const question of QUESTIONS) {
      body = await seeEstimate(spender, question);
      if (body.cost_estimate.threshold_action === "block") break;
      await confirmAndReturn(spender);
      ran += 1;
    }
    // Partners: real runs were charged, and the spender itself ends on the daily cap.
    expect(ran, "real runs before the block").toBeGreaterThanOrEqual(3);
    expect(body.cost_estimate.block_reason).toBe("daily_cap");
    await spender.context().close();

    const newcomer = await newAnonymousPage(browser);
    const blocked = await seeEstimate(newcomer, QUESTIONS[0]);

    expect(blocked.cost_estimate.threshold_action).toBe("block");
    expect(blocked.cost_estimate.block_reason).toBe("daily_cap");
    expect(blocked.cost_estimate.daily_allowance.shared_by_network).toBe(true);
    expect(Number(blocked.cost_estimate.daily_allowance.spent_usd), "the network's spend, not this session's").toBeGreaterThan(0.3);
    const text = await card(newcomer).innerText();
    expect(text).toMatch(/this network/i);
    expect(text).toMatch(/not signed in/i);
    expect(text).toMatch(SIGN_IN_OFFER);
    // W47 review round 1: the block card's offer is a control in the card, not only words.
    await expect(cardSignIn(newcomer)).toBeVisible();

    // The top bar's "Sign in with Google" is on every view; signing in reloads /ui on the composer.
    await signInFromHere(newcomer, freshAccount("w47-own-back"));
    const own = await seeEstimate(newcomer, QUESTIONS[1]);

    expect(own.cost_estimate.threshold_action).toBe("allow");
    expect(own.cost_estimate.daily_allowance.shared_by_network).toBe(false);
    expect(own.cost_estimate.daily_allowance.spent_usd).toBe("0.0000");
    expect(await allowanceLine(newcomer).innerText()).not.toMatch(/network/i);
    await newcomer.context().close();
  });

  /**
   * Review round 2, B: the card's sign-in control only where signing in can help. Server-shaped mocks
   * (`fixtures/limit-responses.ts`, real responses with `shared_by_network` set as the W47 server sends
   * it for an anonymous session): the per-run cap and a run larger than a whole day's allowance need an
   * expensive panel whose price moves with the live catalog, and neither is lifted by an own $0.40.
   * This lane is used because its pages offer sign-in (`#sign-in-google`); the main lane's do not.
   */
  const sharedBody = (base: any) => {
    const copy = structuredClone(base);
    copy.cost_estimate.daily_allowance.shared_by_network = true;
    return copy;
  };
  const gateSignIn = (page: Page) => page.locator("#gate-sign-in");

  async function mockedBlock(browser: Browser, body: unknown): Promise<Page> {
    const page = await newAnonymousPage(browser);
    await page.route("**/v1/query-runs/estimate", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) }),
    );
    await page.locator("#query-text").fill(QUESTIONS[0]);
    await page.locator("#estimate-run").click();
    await expect(gateView(page)).toBeVisible({ timeout: 15000 });
    await expect(card(page)).toHaveAttribute("data-band", "block");
    // Partner: this page offers sign-in, so a hidden card control is the card's choice, not the page's.
    await expect(page.locator("#sign-in-google")).toBeVisible();
    return page;
  }

  for (const [name, base] of [
    ["the per-run cap", LIMIT_RESPONSES.perRunCap],
    ["a run larger than a whole day's allowance", LIMIT_RESPONSES.dailyCapLargerThanADay],
  ] as const) {
    test(`the card offers no sign-in on ${name}, where an own allowance cannot help`, async ({ browser }) => {
      // RED-IF `#gate-sign-in` ("Sign in for your own allowance") is shown on this block: signing in gives
      // a person their own $0.40 a day, which lifts neither the $0.50 per-run cap nor a run that alone
      // costs more than $0.40. Partners: the block rendered on a page that offers sign-in, and the
      // shared daily-cap test below shows the control.
      const page = await mockedBlock(browser, sharedBody(base));

      await expect(gateSignIn(page)).toHaveCount(1);
      await expect(gateSignIn(page)).toBeHidden();
      await page.context().close();
    });
  }

  test("the card offers sign-in on a shared daily-cap block", async ({ browser }) => {
    // Partner of the two tests above (green on 626c916): the control is shown where an own $0.40 helps.
    const page = await mockedBlock(browser, sharedBody(LIMIT_RESPONSES.dailyCap));

    await expect(gateSignIn(page)).toBeVisible();
    await page.context().close();
  });
});
