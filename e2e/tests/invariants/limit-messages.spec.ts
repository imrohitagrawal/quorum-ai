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

test.describe("W33 slice C — limit messages on the real backend (no page.route)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

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
});
