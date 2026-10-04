import { test, expect, Page, Response } from "@playwright/test";
import { boot } from "../../fixtures/golden-run";
import { LIMIT_RESPONSES } from "../../fixtures/limit-responses";

/**
 * W33 slice C, the page half (ADR-0141 decisions 5 and 6, with 2's
 * `bounded_by` and 7's larger-than-a-day case).
 *
 * The page must choose its words from `cost_estimate.block_reason`, never from
 * prose, and show the daily allowance before any block. Written BEFORE the
 * page code: every test below names, in its first line, the change that turns
 * it red.
 *
 * REAL BACKEND FIRST. The first describe drives the real FastAPI app that
 * Playwright's webServer starts (live execution off, so runs are simulated and
 * charged in full, ADR-0074), with NO `page.route`: the same guard as
 * `page-journey.spec.ts` fails a test if one is added. Reached that way: the
 * daily cap (default-panel runs until the server blocks; at about $0.105 a run
 * that is the fourth), the allowance after one run, and the composer footer.
 *
 * The second describe uses `page.route` ONLY for states a browser cannot reach
 * deterministically, each with the reason. The e2e server prices from the LIVE
 * OpenRouter catalog (measured 2026-10-03: the model menu lists 459 ids, not
 * the static catalog), so the per-run cap and the larger-than-a-day case,
 * which need an expensive panel at a chosen length, would move with live
 * prices; no default panel reaches either. The bodies are RESPONSES THE REAL
 * SERVER RETURNED (`fixtures/limit-responses.ts` records how each was
 * produced), so no test renders a combination the server cannot send
 * (failure-mode row 14).
 *
 * Exact copy is asserted only where ADR-0141 gives it: decision 6's
 * "$X of $0.40 left in the last 24 hours; this run uses about $Y". Everything
 * else is a key phrase or a structural fact (an element hidden, a figure
 * present), and each test says which.
 */

const QUESTIONS = [
  "What are the key metrics for measuring SaaS customer retention?",
  "How should a small team choose between Postgres and MySQL?",
  "What is a sensible on-call rotation for a team of five engineers?",
  "Which questions should we ask before adopting a feature-flag service?",
  "How do we decide when a monolith should be split into services?",
  "What should a first incident post-mortem template contain?",
];

// A cap printed with one decimal ("$0.5", "$0.4"): decision 5 says caps print
// with two. Matches "$0.5" and "$0.4" not followed by another digit.
const SHORT_CAP = /\$0\.[45](?!\d)/;
// "$0.00" as a whole figure. NOT a substring check: real breakdown rows print "$0.0078".
const ZERO_CAP = /\$0\.00(?!\d)/;
// Wording that tells the person to wait for spend to free up (decision 7 must
// never say it). Phrases, not sentences.
const WAIT_PHRASES = [/frees up/i, /24 hours old/i, /window resets/i];
// Decision 6's sentence, verbatim except for the two figures.
const ALLOWANCE_SENTENCE = /\$(\d+\.\d{2}) of \$0\.40 left in the last 24 hours; this run uses about \$(\d+(?:\.\d+)?)/;

/** Fail the test if anything installs a page-level mock (best effort, as in page-journey). */
function forbidRoutes(page: Page): () => boolean {
  let mocked = false;
  const origRoute = page.route.bind(page);
  (page as unknown as { route: typeof page.route }).route = ((...args: Parameters<typeof origRoute>) => {
    mocked = true;
    return origRoute(...args);
  }) as typeof page.route;
  return () => mocked;
}

const card = (page: Page) => page.locator("#cost-review-card");
const headline = (page: Page) => page.locator("#cost-review-band-label");
const rail = (page: Page) => page.locator("#cost-gate-rail");
const cheaperModels = (page: Page) => page.locator("#gate-block-models");
const shorten = (page: Page) => page.locator("#gate-block-shorten");
const gateView = (page: Page) => page.locator('[data-view="cost-gate"]');
const banner = (page: Page) => page.locator("#error-region");
const footerNotice = (page: Page) => page.locator('[data-view="composer"] .composer-footer-notice');

/** The VISIBLE text of the cost card (innerText skips hidden nodes such as a hidden rail). */
const cardText = (page: Page) => card(page).innerText();

// Round 2: the gate's own heading and lede are approval copy; a block approves nothing.
const APPROVAL_COPY = [/Approve before anything runs/, /Approving authorises/];
/**
 * The gate's heading plus its lede, as the person sees them. A node that is not rendered counts as
 * "" (innerText of a display:none element falls back to its textContent, so it is checked first).
 */
const gateIntro = (page: Page) =>
  page.evaluate(() => {
    const view = document.querySelector('[data-view="cost-gate"]');
    const nodes = [document.getElementById("cost-gate-heading"), ...Array.from(view?.querySelectorAll(".lede") ?? [])];
    return nodes
      .map((n) => (n && (n as HTMLElement).checkVisibility() ? (n as HTMLElement).innerText : ""))
      .join(" \n ");
  });

/** A deep copy of a real server response with fields replaced (round 2's edge shapes). */
function reshaped<T>(base: T, edit: (copy: any) => void): T {
  const copy = structuredClone(base) as any;
  edit(copy);
  return copy as T;
}

/** Scale a real breakdown so both partitions re-sum to `total` exactly (the server's invariant). */
function rescaleBreakdown(breakdown: any, total: string) {
  const want = Math.round(Number(total) * 10_000);
  for (const key of ["by_model", "by_stage"]) {
    const rows = breakdown[key] as { usd: string }[];
    const have = rows.reduce((sum, row) => sum + Math.round(Number(row.usd) * 10_000), 0);
    let left = want;
    rows.forEach((row, i) => {
      const units = i === rows.length - 1 ? left : Math.round((Number(row.usd) * 10_000 * want) / have);
      left -= units;
      row.usd = (units / 10_000).toFixed(4);
    });
  }
  breakdown.total = total;
}

const isEstimate = (r: Response) => r.url().includes("/v1/query-runs/estimate") && r.request().method() === "POST";

/** Wait for a real run started from the composer to reach the result view, then go back to an empty composer. */
async function realRun(page: Page, question: string) {
  await page.locator("#query-text").fill(question);
  await page.locator("#run-now").click();
  await expect(
    page.locator('#result-verdict[data-consensus]:visible, #gate-confirm:visible').first(),
  ).toBeVisible({ timeout: 30000 });
  const confirm = page.locator("#gate-confirm");
  if (await confirm.isVisible()) await confirm.click();
  await expect(page.locator('[data-view="result"] #result-verdict[data-consensus]')).toBeVisible({ timeout: 30000 });
  await page.locator('[data-view="result"]').getByRole("button", { name: "New question", exact: true }).click();
  await expect(page.locator('[data-view="composer"]')).toBeVisible();
}

/** Ask for the estimate of `question` and return the server's estimate JSON (read, not mocked). */
async function seeEstimate(page: Page, question: string): Promise<Record<string, any>> {
  await page.locator("#query-text").fill(question);
  const answered = page.waitForResponse(isEstimate);
  await page.locator("#estimate-run").click();
  const body = await (await answered).json();
  await expect(gateView(page)).toBeVisible({ timeout: 15000 });
  await expect(card(page)).toHaveAttribute("data-band", body.cost_estimate.threshold_action);
  return body;
}

const centsUp = (usd: string) => (Math.ceil(Number(usd) * 100 - 1e-9) / 100).toFixed(2);
const centsDown = (usd: string) => (Math.floor(Number(usd) * 100 + 1e-9) / 100).toFixed(2);

/** The per-run-cap furniture decision 5 keeps for per_run_cap ONLY. */
async function expectNoHardCapFurniture(page: Page) {
  await expect(headline(page)).not.toContainText(/hard cap/i);
  await expect(rail(page), "the cost rail is drawn only for per_run_cap").toBeHidden();
  await expect(cheaperModels(page), '"Choose cheaper models" is offered only for per_run_cap').toBeHidden();
  await expect(shorten(page), '"Shorten the question" is offered only for per_run_cap').toBeHidden();
  expect(await cardText(page)).not.toMatch(/is over the \$0\.50? hard cap/);
}

// W47 (ADR-0144 decision 6): an anonymous allowance is its NETWORK's. Key phrases, not sentences; the
// offer `\bsign in\b` is not matched by "signed in".
const SIGN_IN_OFFER = /\bsign in\b/i;

test.describe("W33 slice C — limit messages on the real backend (no page.route)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  test("W47: an anonymous allowance line says it is shared by everyone on this network who is not signed in", async ({ page }) => {
    // RED-IF: an anonymous allow-band estimate's allowance line does not say the allowance is shared on
    // this network by people who are not signed in, or the server does not flag it `shared_by_network:
    // true`, or the line offers signing in on a page that has no way to sign in (ADR-0144 decision 6:
    // the offer only "when sign-in is available"). Placed FIRST in this describe: the daily-cap test
    // below spends this network's allowance. The signed-in lane (tests/signed-in/shared-allowance.spec.ts)
    // covers the page WITH sign-in.
    const mocked = forbidRoutes(page);
    await boot(page);
    const signInOffered = (await page.locator("#sign-in-google").count()) > 0;

    const body = await seeEstimate(page, QUESTIONS[0]);

    expect(body.cost_estimate.threshold_action, "an estimate that can run shows the allowance line").not.toBe("block");
    await expect(page.locator("#cost-gate-allowance")).toBeVisible();
    const line = await page.locator("#cost-gate-allowance").innerText();
    // Partner (green today): it is decision 6's allowance sentence, unchanged.
    expect(line).toMatch(ALLOWANCE_SENTENCE);
    expect(line).toMatch(/this network/i);
    expect(line).toMatch(/not signed in/i);
    if (signInOffered) expect(line).toMatch(SIGN_IN_OFFER);
    else expect(line, "no sign-in offer where the page has no sign-in").not.toMatch(SIGN_IN_OFFER);
    expect(body.cost_estimate.daily_allowance.shared_by_network).toBe(true);
    expect(mocked()).toBe(false);
  });

  test("a daily-cap block names the $0.40 daily cap, what was used, that simulated runs count, and that it frees up", async ({ page }) => {
    // RED-IF: the daily block still wears the hard-cap headline, note, rail or "cheaper models"/"shorten"
    // actions, or its card does not name $0.40, the spend rounded UP to cents, simulated runs, and the
    // 24-hour release (ADR-0141 decision 5; the owner's bug 3).
    const mocked = forbidRoutes(page);
    await boot(page);
    // Spend the session's real $0.40: run each allowed estimate from the gate until the server blocks.
    // At today's ~$0.105 a run the fourth estimate blocks; the loop keeps that true if live prices move.
    let body: Record<string, any> = {};
    let ran = 0;
    for (const question of QUESTIONS) {
      body = await seeEstimate(page, question);
      if (body.cost_estimate.threshold_action === "block") break;
      await page.locator("#gate-confirm").click();
      await expect(page.locator('[data-view="result"] #result-verdict[data-consensus]')).toBeVisible({ timeout: 30000 });
      await page.locator('[data-view="result"]').getByRole("button", { name: "New question", exact: true }).click();
      await expect(page.locator('[data-view="composer"]')).toBeVisible();
      ran += 1;
    }
    expect(ran, "real runs before the block").toBeGreaterThanOrEqual(3);

    // Partners (green today): the real server blocked on the daily cap, after real spend.
    expect(body.cost_estimate.block_reason).toBe("daily_cap");
    const spent = body.cost_estimate.daily_allowance.spent_usd as string;
    expect(Number(spent)).toBeGreaterThan(0.3);
    await expect(card(page)).toHaveAttribute("data-band", "block");

    await expectNoHardCapFurniture(page);
    const text = await cardText(page);
    expect(text).toContain("$0.40");
    expect(text, `the amount used (${spent}) rounded UP to cents`).toContain(`$${centsUp(spent)}`);
    expect(text).toMatch(/simulated/i);
    expect(text).toMatch(/frees up as each run turns 24 hours old/i);
    expect(text).not.toMatch(SHORT_CAP);
    // W47 (ADR-0144 decision 6). RED-IF: an anonymous daily block does not say the allowance is shared by
    // everyone on this network who is not signed in, or the server does not flag it shared.
    expect(text).toMatch(/this network/i);
    expect(text).toMatch(/not signed in/i);
    expect(body.cost_estimate.daily_allowance.shared_by_network).toBe(true);

    // Round 2. RED-IF: a daily block that still has allowance left (the real fourth run: about
    // $0.08) is headlined as if the allowance were used up, or the gate still asks for approval.
    const remaining = body.cost_estimate.daily_allowance.remaining_usd as string;
    expect(Number(remaining), "the partner: some allowance really is left").toBeGreaterThan(0);
    await expect(headline(page)).toContainText("Not enough allowance left");
    await expect(headline(page)).not.toContainText(/allowance used/i);
    const intro = await gateIntro(page);
    for (const phrase of APPROVAL_COPY) expect(intro).not.toMatch(phrase);
    expect(mocked(), "this test must NOT use page.route").toBe(false);
  });

  test("before any block the estimate card shows what is left of the $0.40 and what this run uses", async ({ page }) => {
    // RED-IF: an allow-band estimate after one run does not say, verbatim, "$X of $0.40 left in the last
    // 24 hours; this run uses about $Y" with X the server's remaining rounded DOWN to cents and Y this
    // run's estimate (decision 6).
    const mocked = forbidRoutes(page);
    await boot(page);
    await realRun(page, QUESTIONS[0]);

    const body = await seeEstimate(page, QUESTIONS[1]);

    // Partners (green today): one real charge is on the ledger and the run is allowed.
    const allowance = body.cost_estimate.daily_allowance;
    expect(body.cost_estimate.threshold_action).toBe("allow");
    expect(allowance.bounded_by).toBe("daily_cap");
    expect(Number(allowance.spent_usd)).toBeGreaterThan(0);

    const match = (await gateView(page).innerText()).match(ALLOWANCE_SENTENCE);
    expect(match, "decision 6's allowance sentence").not.toBeNull();
    expect(match![1], `remaining ${allowance.remaining_usd} rounded DOWN to cents`).toBe(
      centsDown(allowance.remaining_usd),
    );
    expect(Math.abs(Number(match![2]) - Number(body.cost_estimate.estimated_cost_usd))).toBeLessThan(0.01);
    // Round 2's positive partner (green today): an estimate that CAN run keeps the approval copy.
    const intro = await gateIntro(page);
    for (const phrase of APPROVAL_COPY) expect(intro).toMatch(phrase);
    expect(mocked()).toBe(false);
  });

  test("the composer footer names the $0.40 / 24-hour rule in one fixed sentence with no personal number", async ({ page }) => {
    // RED-IF: the composer footer does not name the $0.40 cap, the 24 hours and that simulated runs
    // count, or its text changes when this session spends (a personal figure leaked in, decision 6).
    const mocked = forbidRoutes(page);
    await boot(page);
    const before = (await footerNotice(page).innerText()).trim();

    await realRun(page, QUESTIONS[0]);
    const after = (await footerNotice(page).innerText()).trim();

    expect(before).toContain("$0.40");
    expect(before).toMatch(/24 hours/);
    expect(before).toMatch(/simulated/i);
    expect(before).not.toMatch(SHORT_CAP);
    expect(after, "the footer must not carry a figure that moves with this session's spend").toBe(before);
    expect(mocked()).toBe(false);
  });

  test("the composer footer says you can spend UP TO $0.40 in 24 hours", async ({ page }) => {
    // RED-IF: the footer states the $0.40 as a flat amount; the running total can block earlier, so it
    // must say "up to $0.40" (review round 2). Partner (green today): the footer names $0.40 at all.
    const mocked = forbidRoutes(page);
    await boot(page);
    const footer = (await footerNotice(page).innerText()).trim();

    expect(footer).toContain("$0.40");
    expect(footer).toContain("up to $0.40");
    expect(mocked()).toBe(false);
  });
});

test.describe("W33 slice C — limit messages for states a browser cannot reach deterministically (server-shaped mocks)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  const fulfil = (body: unknown, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify(body) });

  /** Serve `body` as the answer to every estimate, then open the estimate gate. */
  async function mockedEstimate(page: Page, body: unknown) {
    await boot(page);
    await page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(body)));
    await page.locator("#query-text").fill(QUESTIONS[0]);
    await page.locator("#estimate-run").click();
    await expect(gateView(page)).toBeVisible({ timeout: 15000 });
  }

  test("a per-run-cap block keeps the hard-cap headline, the rail and both recovery actions", async ({ page }) => {
    // Positive partner of every "no hard-cap furniture" check in this file (green today).
    // Mocked because no default panel reaches the per-run cap, and an expensive panel's price
    // moves with the live catalog the e2e server reads.
    // RED-IF: the per_run_cap block loses its hard-cap headline, its rail, or "Choose cheaper models" /
    // "Shorten the question" — the one block where they are the right advice.
    const body = LIMIT_RESPONSES.perRunCap;
    await mockedEstimate(page, body);

    expect(body.cost_estimate.block_reason).toBe("per_run_cap");
    expect(Number(body.cost_estimate.max_cost_usd)).toBeGreaterThan(0.5);
    await expect(card(page)).toHaveAttribute("data-band", "block");
    await expect(headline(page)).toContainText(/hard cap/i);
    await expect(rail(page)).toBeVisible();
    await expect(cheaperModels(page)).toBeVisible();
    await expect(shorten(page)).toBeVisible();
  });

  test("the per-run-cap card prints its caps with two decimals", async ({ page }) => {
    // RED-IF: any cap on the per_run_cap card prints as "$0.5" or "$0.4" (decision 5: "$0.50", "$0.40").
    // Mocked for the same reason as the test above.
    const body = LIMIT_RESPONSES.perRunCap;
    await mockedEstimate(page, body);

    expect(body.cost_estimate.block_reason).toBe("per_run_cap");
    const text = await cardText(page);
    expect(text).toContain("$0.50");
    expect(text).not.toMatch(SHORT_CAP);
  });

  test("a run larger than a whole day's allowance is a daily block that never says to wait", async ({ page }) => {
    // RED-IF: the larger-than-a-day block (estimate alone above $0.40, worst case under $0.50) is shown
    // as the hard cap, or tells the person spend frees up / to wait for the window (decision 7).
    // Mocked because it needs an expensive panel at a chosen length (live prices, as above).
    const body = LIMIT_RESPONSES.dailyCapLargerThanADay;
    await mockedEstimate(page, body);

    // Partners: the server's own classification of this run (the fixture is its response).
    expect(body.cost_estimate.block_reason).toBe("daily_cap");
    expect(Number(body.cost_estimate.estimated_cost_usd)).toBeGreaterThan(0.4);
    expect(Number(body.cost_estimate.max_cost_usd)).toBeLessThanOrEqual(0.5);
    await expect(headline(page)).not.toContainText(/hard cap/i);
    await expect(rail(page)).toBeHidden();
    const text = await cardText(page);
    for (const phrase of WAIT_PHRASES) expect(text).not.toMatch(phrase);
    expect(text).toContain("$0.40");
    expect(text).not.toMatch(SHORT_CAP);
  });

  test("the running-total block names the running limit and makes no 24-hour claim", async ({ page }) => {
    // Mocked because it needs an in-memory total above $0.50 minus one run while the 24-hour ledger is
    // under its cap — only an earlier day's runs in the same server process do that.
    // RED-IF: the account_running_total block wears the hard-cap furniture, or claims anything about
    // "24 hours" when bounded_by is running_total (decisions 2 and 5).
    await mockedEstimate(page, LIMIT_RESPONSES.accountRunningTotal);
    expect(LIMIT_RESPONSES.accountRunningTotal.cost_estimate.daily_allowance.bounded_by).toBe("running_total");
    await expect(card(page)).toHaveAttribute("data-band", "block");

    await expectNoHardCapFurniture(page);
    const text = await cardText(page);
    expect(text).toContain("$0.50");
    expect(text).not.toMatch(/24 hours/i);
    expect(text).not.toMatch(SHORT_CAP);
  });

  test("the ledger-unavailable block says it is a storage fault, not a limit reached", async ({ page }) => {
    // Mocked because the real ledger cannot be made untrustworthy from a browser.
    // RED-IF: the ledger_unavailable block wears the hard-cap furniture, stops saying it is a storage
    // fault and not a limit this account reached, or shows an allowance figure it does not have.
    await mockedEstimate(page, LIMIT_RESPONSES.ledgerUnavailable);
    await expect(card(page)).toHaveAttribute("data-band", "block");

    await expectNoHardCapFurniture(page);
    const text = await cardText(page);
    expect(text).toMatch(/storage fault/i);
    expect(text).toMatch(/not a limit/i);
    expect(text).not.toMatch(/left in the last 24 hours/i);
    expect(text).not.toMatch(SHORT_CAP);
  });

  test("with no allowance the estimate card says it cannot be checked right now", async ({ page }) => {
    // Mocked because the ADR-0016 degrade path (a ledger that cannot be metered) is not reachable from a browser.
    // RED-IF: an allow estimate with daily_allowance null does not say the allowance cannot be checked
    // right now, or invents a figure (decision 6).
    await mockedEstimate(page, LIMIT_RESPONSES.allowAllowanceUnavailable);
    await expect(card(page)).toHaveAttribute("data-band", "allow");
    // Positive partner: the gate rendered this estimate (its run button names the price).
    await expect(page.locator("#gate-confirm")).toBeVisible();

    const text = await gateView(page).innerText();
    expect(text).toMatch(/cannot be checked right now/i);
    expect(text).not.toMatch(ALLOWANCE_SENTENCE);
  });

  test("an allowance set by the running total is not called '… of $0.40 in the last 24 hours'", async ({ page }) => {
    // Mocked for the same reason as the running-total block above.
    // RED-IF: with bounded_by running_total the card still says the figure is "of $0.40" "in the last
    // 24 hours" (decision 2: that figure does not free with time), or drops the figure (rounded DOWN).
    await mockedEstimate(page, LIMIT_RESPONSES.allowBoundedByRunningTotal);
    await expect(card(page)).toHaveAttribute("data-band", "allow");
    const allowance = LIMIT_RESPONSES.allowBoundedByRunningTotal.cost_estimate.daily_allowance;
    expect(allowance.bounded_by).toBe("running_total");

    const text = await gateView(page).innerText();
    expect(text).toContain(`$${centsDown(allowance.remaining_usd)}`);
    expect(text).not.toMatch(ALLOWANCE_SENTENCE);
    expect(text).not.toMatch(/of \$0\.40[^.]*24 hours/);
  });

  /**
   * Run now on the REAL estimate (allow band), with only the create answered by `detail` once.
   * Mocked because the charge-time refusal needs a second tab to charge between this request's
   * estimate and its charge.
   */
  async function refusedCreate(page: Page, detail: unknown) {
    await boot(page);
    let served = 0;
    await page.route("**/v1/query-runs", (r) => {
      if (r.request().method() !== "POST" || served > 0) return r.continue();
      served += 1;
      return r.fulfill(fulfil(detail, 402));
    });
    await page.locator("#query-text").fill(QUESTIONS[0]);
    await page.locator("#run-now").click();
    await expect(banner(page)).toBeVisible({ timeout: 15000 });
    expect(served, "the create was answered by the mock exactly once").toBe(1);
  }

  test("the charge-time daily-cap refusal names the daily cap, not 'Hard cap $0.5 · no override'", async ({ page }) => {
    // RED-IF: the create-time COST_LIMIT_EXCEEDED banner for a daily_cap refusal still says
    // "Over the hard cap" / "Hard cap $0.5 · no override", or does not name the $0.40 cap (decision 3).
    await refusedCreate(page, LIMIT_RESPONSES.createChargeTimeDailyCap);
    const text = await banner(page).innerText();

    await expect(page.locator("#error-region-title")).not.toContainText(/hard cap/i);
    expect(text).not.toMatch(/Hard cap/);
    expect(text).not.toMatch(/no override/i);
    expect(text).toContain("$0.40");
    expect(text).not.toMatch(SHORT_CAP);
  });

  test("the charge-time refusal with no allowance still names the daily cap and shows no figure", async ({ page }) => {
    // RED-IF: the daily_cap refusal whose fresh allowance read failed (daily_allowance null, decision 8)
    // falls back to the hard-cap banner, or shows any dollar figure other than the $0.40 cap.
    await refusedCreate(page, LIMIT_RESPONSES.createChargeTimeDailyCapNoAllowance);
    const text = await banner(page).innerText();

    await expect(page.locator("#error-region-title")).not.toContainText(/hard cap/i);
    expect(text).toContain("$0.40");
    const figures = text.match(/\$\d+(?:\.\d+)?/g) ?? [];
    expect(figures.length, "the positive partner: the cap itself is printed").toBeGreaterThan(0);
    expect(new Set(figures)).toEqual(new Set(["$0.40"]));
  });

  // --- review round 2 ------------------------------------------------------------------

  for (const [name, body] of [
    ["per_run_cap", LIMIT_RESPONSES.perRunCap],
    ["daily_cap", LIMIT_RESPONSES.dailyCap],
    ["daily_cap, larger than a day", LIMIT_RESPONSES.dailyCapLargerThanADay],
    ["account_running_total", LIMIT_RESPONSES.accountRunningTotal],
    ["ledger_unavailable", LIMIT_RESPONSES.ledgerUnavailable],
  ] as const) {
    test(`a ${name} block card does not ask for approval`, async ({ page }) => {
      // RED-IF: the gate's heading or lede still says "Approve before anything runs" / "Approving
      // authorises" on a block card, where nothing can be approved. Its partner is the allow-band
      // assertion in "before any block the estimate card shows …" above (green today).
      await mockedEstimate(page, body);
      await expect(card(page)).toHaveAttribute("data-band", "block");
      await expect(page.locator("#cost-gate-heading")).toBeVisible();

      const intro = await gateIntro(page);
      for (const phrase of APPROVAL_COPY) expect(intro).not.toMatch(phrase);
    });
  }

  test("a daily block with nothing left may say the allowance is used", async ({ page }) => {
    // Partner of the real fourth-run block's "Not enough allowance left" (green today).
    // Mocked from the real dailyCap response with spent 0.4100 and remaining 0.0000 — a live run
    // reconciled above its estimate (failure-mode row 10); a browser cannot make that happen.
    // RED-IF: the remaining-is-zero headline stops saying the allowance is used.
    const body = reshaped(LIMIT_RESPONSES.dailyCap, (c) => {
      c.cost_estimate.daily_allowance.spent_usd = "0.4100";
      c.cost_estimate.daily_allowance.remaining_usd = "0.0000";
    });
    await mockedEstimate(page, body);
    await expect(card(page)).toHaveAttribute("data-band", "block");

    await expect(headline(page)).toContainText(/allowance used/i);
    await expect(headline(page)).not.toContainText("Not enough allowance left");
  });

  test("a malformed cap_usd prints no cap figure, and never $0.00", async ({ page }) => {
    // Mocked: the real server never sends a non-decimal cap; this pins the page's guard.
    // RED-IF: `cap_usd: "bogus"` renders as "$0.00" (or any cap figure) on the daily-block card.
    const body = reshaped(LIMIT_RESPONSES.dailyCap, (c) => {
      c.cost_estimate.daily_allowance.cap_usd = "bogus";
    });
    await mockedEstimate(page, body);
    await expect(card(page)).toHaveAttribute("data-band", "block");
    // Partner: the card still says what was used (the spend figure is well formed).
    const spent = body.cost_estimate.daily_allowance.spent_usd as string;
    const text = await cardText(page);
    expect(text).toContain(`$${centsUp(spent)}`);

    expect(text).not.toMatch(ZERO_CAP);
    expect(text, "no cap figure without a well-formed cap").not.toMatch(/\$0\.40(?!\d)/);
  });

  test("a malformed cap_usd prints no cap figure in the allowance line either", async ({ page }) => {
    // Mocked as above, on an allow estimate whose allowance the daily cap set.
    // RED-IF: the allowance line prints "of $0.00" (or any cap figure) for `cap_usd: "bogus"`.
    const body = reshaped(LIMIT_RESPONSES.allowBoundedByRunningTotal, (c) => {
      c.cost_estimate.daily_allowance = {
        cap_usd: "bogus",
        spent_usd: "0.1052",
        remaining_usd: "0.2948",
        bounded_by: "daily_cap",
      };
    });
    await mockedEstimate(page, body);
    await expect(card(page)).toHaveAttribute("data-band", "allow");
    // Partner: the gate rendered this estimate (its run button names the price).
    await expect(page.locator("#gate-confirm")).toBeVisible();

    const text = await gateView(page).innerText();
    expect(text).not.toMatch(ZERO_CAP);
    expect(text, "no cap figure without a well-formed cap").not.toMatch(/\$0\.40(?!\d)/);
  });

  test("a daily block whose run costs exactly $0.40 prints the run's cost with two decimals", async ({ page }) => {
    // Mocked from the real dailyCap response with the estimate set to 0.4000 (its breakdown rescaled to
    // match) and 0.1052 already on the ledger; the live catalog cannot be steered to that figure.
    // RED-IF: the run's own cost prints as "$0.4" anywhere on the card (decision 5's two decimals
    // apply to the run's cost too, not only to the caps).
    const body = reshaped(LIMIT_RESPONSES.dailyCap, (c) => {
      c.cost_estimate.estimated_cost_usd = "0.4000";
      c.cost_estimate.max_cost_usd = "0.4400";
      rescaleBreakdown(c.cost_estimate.breakdown, "0.4000");
      c.cost_estimate.daily_allowance.spent_usd = "0.1052";
      c.cost_estimate.daily_allowance.remaining_usd = "0.2948";
    });
    await mockedEstimate(page, body);
    await expect(card(page)).toHaveAttribute("data-band", "block");
    // Partner (green today): the run's cost is rendered, in one form or the other.
    const total = page.locator("#cost-gate-total");
    await expect(total).toHaveText(/^\$0\.40?$/);

    await expect(total).toHaveText("$0.40");
    expect(await cardText(page)).not.toMatch(SHORT_CAP);
  });
});

/**
 * W47 review round 1 (ADR-0144 decision 6): the copy for a SHARED (network) allowance.
 *
 * Server-shaped mocks: each body is a real response from `fixtures/limit-responses.ts` (recorded before
 * W47) with ONE field changed, `daily_allowance.shared_by_network`, which the W47 server sends `true` for
 * an anonymous session and `false` for a signed-in one. Mocked because a shared daily block or running
 * total on the real backend needs this lane's one network to be spent, which the e2e lanes' LOCAL-only
 * override (decision 7) prevents. The main lane offers no sign-in, so these pages have no
 * `#sign-in-google`; the sign-in control is pinned in tests/signed-in/shared-allowance.spec.ts.
 */
test.describe("W47 — the words for a shared (network) allowance (server-shaped mocks)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  const fulfil = (body: unknown, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify(body) });
  const shared = <T,>(base: T, value: boolean, where: "estimate" | "detail" = "estimate"): T =>
    reshaped(base, (c) => {
      if (where === "estimate") c.cost_estimate.daily_allowance.shared_by_network = value;
      else c.detail.daily_allowance.shared_by_network = value;
    });
  // The network's spend named next to its figure, in either order, inside one sentence.
  const networkSpend = (figure: string) =>
    new RegExp(`\\${figure}[^.]*network|network[^.]*\\${figure}`, "i");
  const live = (page: Page) => page.locator("#cost-gate-live");
  const signInControl = (page: Page) => card(page).getByRole("button", { name: /sign in/i }).or(card(page).getByRole("link", { name: /sign in/i }));

  async function mockedEstimate(page: Page, body: unknown) {
    await boot(page);
    await page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(body)));
    await page.locator("#query-text").fill(QUESTIONS[0]);
    await page.locator("#estimate-run").click();
    await expect(gateView(page)).toBeVisible({ timeout: 15000 });
  }

  async function refusedCreate(page: Page, detail: unknown) {
    await boot(page);
    let served = 0;
    await page.route("**/v1/query-runs", (r) => {
      if (r.request().method() !== "POST" || served > 0) return r.continue();
      served += 1;
      return r.fulfill(fulfil(detail, 402));
    });
    await page.locator("#query-text").fill(QUESTIONS[0]);
    await page.locator("#run-now").click();
    await expect(banner(page)).toBeVisible({ timeout: 15000 });
    expect(served, "the create was answered by the mock exactly once").toBe(1);
  }

  test("a shared daily block does not tell a person who ran nothing 'You have used'; it names the network's spend", async ({ page }) => {
    // RED-IF: the daily-cap block card for `shared_by_network: true` still says "You have used $0.32 …"
    // (the network spent it, maybe not this person), or does not put the $0.32 in a sentence that names
    // the network. Partner: the next test, where the same body unshared still says "You have used".
    await mockedEstimate(page, shared(LIMIT_RESPONSES.dailyCap, true));
    await expect(card(page)).toHaveAttribute("data-band", "block");
    const text = await cardText(page);

    expect(text, "the spend figure is on the card").toContain("$0.32");
    expect(text).toMatch(networkSpend("$0.32"));
    expect(text).not.toMatch(/you have used/i);
  });

  test("an own (signed-in) daily block keeps 'You have used' and never names the network", async ({ page }) => {
    // Partner of the test above. RED-IF the own-allowance copy loses "You have used $0.32" or gains
    // the network wording (decision 3: a signed-in allowance is the person's own).
    await mockedEstimate(page, shared(LIMIT_RESPONSES.dailyCap, false));
    await expect(card(page)).toHaveAttribute("data-band", "block");
    const text = await cardText(page);

    expect(text).toMatch(/You have used \$0\.32/);
    expect(text).not.toMatch(/network/i);
  });

  test("the late daily-cap refusal for a shared allowance names the network's spend, not 'You have used'", async ({ page }) => {
    // The charge-time OVER_DAILY_CAP 402 banner ("… Nothing ran and nothing was charged."), which the
    // product reviewer saw saying "You have used $0.35 of the $0.40". RED-IF that banner says
    // "You have used" for `shared_by_network: true`, or does not name the network next to the $0.35.
    // Partner: the unshared body below keeps "You have used $0.35".
    await refusedCreate(page, shared(LIMIT_RESPONSES.createChargeTimeDailyCap, true, "detail"));
    const text = await banner(page).innerText();

    expect(text).toContain("$0.35");
    expect(text).toMatch(networkSpend("$0.35"));
    expect(text).not.toMatch(/you have used/i);
  });

  test("the late daily-cap refusal for an own allowance keeps 'You have used'", async ({ page }) => {
    // Partner of the test above. RED-IF the signed-in banner loses "You have used $0.35" or names the network.
    await refusedCreate(page, shared(LIMIT_RESPONSES.createChargeTimeDailyCap, false, "detail"));
    await expect(banner(page)).toBeVisible();
    const text = await banner(page).innerText();

    expect(text).toMatch(/You have used \$0\.35/);
    expect(text).not.toMatch(/network/i);
  });

  test("a shared running-total block does not say 'Your recent runs' and says the allowance is shared", async ({ page }) => {
    // RED-IF: the account_running_total block for `shared_by_network: true` says "Your recent runs …"
    // (the network's runs, not this person's), or lacks the shared sentence (who shares it: everyone on
    // this network who is not signed in). Partner: the next test keeps "Your recent runs" for an own one.
    await mockedEstimate(page, shared(LIMIT_RESPONSES.accountRunningTotal, true));
    await expect(card(page)).toHaveAttribute("data-band", "block");
    const text = await cardText(page);

    expect(text, "the running limit is named").toContain("$0.50");
    expect(text).toMatch(/this network/i);
    expect(text).toMatch(/not signed in/i);
    expect(text).not.toMatch(/your recent runs/i);
  });

  test("an own running-total block keeps 'Your recent runs' and never names the network", async ({ page }) => {
    // Partner of the test above. RED-IF the own-allowance running-total copy changes.
    await mockedEstimate(page, shared(LIMIT_RESPONSES.accountRunningTotal, false));
    await expect(card(page)).toHaveAttribute("data-band", "block");
    const text = await cardText(page);

    expect(text).toMatch(/Your recent runs/);
    expect(text).not.toMatch(/network/i);
  });

  test("a shared daily block's screen-reader announcement says the allowance is shared on this network", async ({ page }) => {
    // RED-IF: `#cost-gate-live` (the gate's polite live region) announces a shared daily block without
    // saying the allowance is the network's. Partners: it announces the daily allowance at all, and the
    // own-allowance announcement (second half) does not mention a network.
    await mockedEstimate(page, shared(LIMIT_RESPONSES.dailyCap, true));
    await expect(live(page)).toContainText(/daily allowance/i);
    await expect(live(page)).toContainText(/this network/i);

    await page.goto("about:blank");
    await mockedEstimate(page, shared(LIMIT_RESPONSES.dailyCap, false));
    await expect(live(page)).toContainText(/daily allowance/i);
    await expect(live(page)).not.toContainText(/network/i);
  });

  test("the shared sentence is set in body type, not the monospace figure line", async ({ page }) => {
    // RED-IF: the sentence "shared by everyone on this network …" on an allow card is rendered in the
    // allowance line's monospace face (it is prose, not a figure). Partners: the shared sentence is on
    // the card, and the figure line itself IS monospace.
    const body = reshaped(LIMIT_RESPONSES.allowBoundedByRunningTotal, (c) => {
      c.cost_estimate.daily_allowance = {
        cap_usd: "0.40",
        spent_usd: "0.1052",
        remaining_usd: "0.2948",
        bounded_by: "daily_cap",
        shared_by_network: true,
      };
    });
    await mockedEstimate(page, body);
    await expect(card(page)).toHaveAttribute("data-band", "allow");
    await expect(page.locator("#cost-gate-allowance")).toBeVisible();

    const fonts = await page.evaluate(() => {
      const gate = document.querySelector('[data-view="cost-gate"]') as HTMLElement;
      const all = Array.from(gate.querySelectorAll<HTMLElement>("*")).filter(
        (n) => n.checkVisibility() && /shared by everyone on this network/i.test(n.textContent ?? ""),
      );
      // The innermost element holding the sentence.
      const holder = all.find((n) => !all.some((m) => m !== n && n.contains(m)));
      const figure = document.getElementById("cost-gate-allowance") as HTMLElement;
      return {
        sentence: holder ? getComputedStyle(holder).fontFamily : null,
        figure: getComputedStyle(figure).fontFamily,
        figureText: figure.innerText,
      };
    });

    expect(fonts.sentence, "the shared sentence is on the card").not.toBeNull();
    expect(fonts.figureText).toMatch(/left in the last 24 hours/);
    expect(fonts.figure.toLowerCase()).toMatch(/mono/);
    expect(fonts.sentence).not.toBe(fonts.figure);
  });

  test("with no sign-in on the page, a shared card offers no sign-in control", async ({ page }) => {
    // Partner of tests/signed-in/shared-allowance.spec.ts's in-card sign-in control (decision 6: the
    // offer only "when sign-in is available"). RED-IF a sign-in control appears on a page that has no
    // way to sign in. Positive partner: this page really has no `#sign-in-google`, and the shared
    // sentence IS on the card (the control's absence is not the card's absence).
    await mockedEstimate(page, shared(LIMIT_RESPONSES.dailyCap, true));
    await expect(card(page)).toHaveAttribute("data-band", "block");

    await expect(page.locator("#sign-in-google")).toHaveCount(0);
    await expect(card(page)).toContainText(/this network/i);
    await expect(signInControl(page)).toHaveCount(0);
  });

  test("a shared 'larger than a day' block does not say 'you can spend' and says the allowance is shared", async ({ page }) => {
    // Review round 2, C. A run whose estimate ALONE is above the whole $0.40 (decision 7's early branch of
    // the daily-cap copy). RED-IF, for `shared_by_network: true`, the card still says "the whole $0.40
    // you can spend in 24 hours" (it is the network's $0.40) or lacks the shared sentence. Partners: it IS
    // that block (its headline), and the next test keeps the own-allowance wording.
    await mockedEstimate(page, shared(LIMIT_RESPONSES.dailyCapLargerThanADay, true));
    await expect(card(page)).toHaveAttribute("data-band", "block");
    await expect(headline(page)).toContainText(/larger than a day/i);
    const text = await cardText(page);

    expect(text).toMatch(/this network/i);
    expect(text).toMatch(/not signed in/i);
    expect(text).not.toMatch(/you can spend/i);
  });

  test("an own 'larger than a day' block keeps 'you can spend in 24 hours' and never names the network", async ({ page }) => {
    // Partner of the test above. RED-IF the own-allowance wording of decision 7 changes.
    await mockedEstimate(page, shared(LIMIT_RESPONSES.dailyCapLargerThanADay, false));
    await expect(card(page)).toHaveAttribute("data-band", "block");
    await expect(headline(page)).toContainText(/larger than a day/i);
    const text = await cardText(page);

    expect(text).toMatch(/you can spend in 24 hours/);
    expect(text).not.toMatch(/network/i);
  });

  test("the composer footer says the $0.40 is shared on the network when not signed in", async ({ page }) => {
    // RED-IF: the composer footer still describes the $0.40 as if it were the visitor's own, with no
    // word that it is the network's while not signed in. Partners (green today): it still names the
    // $0.40, the 24 hours and simulated runs (the W33 slice C checks above).
    await boot(page);
    const footer = (await footerNotice(page).innerText()).trim();

    expect(footer).toContain("$0.40");
    expect(footer).toMatch(/24 hours/);
    expect(footer).toMatch(/simulated/i);
    expect(footer).toMatch(/network/i);
  });
});
