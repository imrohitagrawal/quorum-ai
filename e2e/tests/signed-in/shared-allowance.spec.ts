import { test, expect, type Browser, type Page, type Response } from "@playwright/test";

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

    // The top bar's "Sign in with Google" is on every view; signing in reloads /ui on the composer.
    await signInFromHere(newcomer, freshAccount("w47-own-back"));
    const own = await seeEstimate(newcomer, QUESTIONS[1]);

    expect(own.cost_estimate.threshold_action).toBe("allow");
    expect(own.cost_estimate.daily_allowance.shared_by_network).toBe(false);
    expect(own.cost_estimate.daily_allowance.spent_usd).toBe("0.0000");
    expect(await allowanceLine(newcomer).innerText()).not.toMatch(/network/i);
    await newcomer.context().close();
  });
});
