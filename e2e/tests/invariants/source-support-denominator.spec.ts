import { test, expect, Page } from "@playwright/test";
import { boot, goldenCreateResp, goldenCompletedResp } from "../../fixtures/golden-run";

/**
 * Issue #193 — the Source support trust card must state its denominator.
 *
 * The card rendered a bare `"75%"`. #171's own rule is that a share is not
 * reported without saying what it is a share OF, and this panel is FOUR
 * answers: "3 of 4" and "18 of 25" are very different claims wearing the same
 * number, and the smaller one should not read as authoritative.
 *
 * Both counts (`citation_coverage.answer_count`,
 * `.sourced_answer_count`) are already REQUIRED fields on the served payload,
 * so this computes nothing new — the UI was simply discarding them.
 *
 * The golden fixture's final synthesis uses `CC_BELOW`
 * (4 answers, 3 sourced, ratio 0.75), so the expected rendering is exactly
 * `75% (3 of 4 answers)`.
 */

const CARD = '#result-trust .result-trust-card[data-accent="source"]';

const fulfil = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

/** Drive composer -> run -> result, optionally overriding citation_coverage. */
async function driveToResult(page: Page, coverage?: unknown) {
  await boot(page);
  await Promise.all([
    page.route("**/v1/query-runs/estimate", (r) =>
      r.fulfill(
        fulfil({
          correlation_id: "corr-193",
          cost_estimate: goldenCreateResp().cost_estimate,
          model_slots: goldenCreateResp().model_slots,
          reasons: [],
        }),
      ),
    ),
    page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
    page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
  ]);

  const completed = goldenCompletedResp() as Record<string, any>;
  if (coverage !== undefined) {
    // NOTE the nesting: `final_synthesis` lives under `result`, not at the
    // top level. Writing `completed.final_synthesis` instead silently leaves
    // the default fixture in place, and three tests here passed against
    // 75% (3 of 4 answers) while claiming to assert other shapes.
    completed.result.final_synthesis = {
      ...completed.result.final_synthesis,
      citation_coverage: coverage,
    };
  }
  await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => r.fulfill(fulfil(completed)));
  await page.route(/\/v1\/query-runs$/, (r) =>
    r.request().method() === "POST" ? r.fulfill(fulfil(goldenCreateResp())) : r.continue(),
  );

  await page
    .getByRole("textbox")
    .first()
    .fill("What are the key metrics for measuring SaaS retention?");
  await page.locator("#run-now").click();
  await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
}

test.describe("source support states its denominator (#193)", () => {
  test("the golden run renders the count, not a bare percentage", async ({ page }) => {
    await driveToResult(page);
    const card = page.locator(CARD);
    await expect(card).toBeVisible();

    // The whole point: the number and what it is a share of, together.
    await expect(card).toContainText("75% (3 of 4 answers)");
  });

  test("a single-answer panel is not pluralised", async ({ page }) => {
    // Grammar is not cosmetic here — "1 of 1 answers" reads like a rounding
    // artefact and undermines the number it is meant to qualify.
    await driveToResult(page, {
      answer_count: 1,
      sourced_answer_count: 1,
      sourced_answer_ratio: "1.00",
      target_ratio: "0.80",
      target_met: true,
    });
    await expect(page.locator(CARD)).toContainText("100% (1 of 1 answer)");
  });

  test("an absent ratio still renders the no-data dash, never a fabricated 0%", async ({
    page,
  }) => {
    // The pre-existing WP-B/F-18 contract, asserted here so the denominator
    // work cannot quietly resurrect a fabricated zero.
    await driveToResult(page, {
      answer_count: 4,
      sourced_answer_count: 0,
      sourced_answer_ratio: null,
      target_ratio: "0.80",
      target_met: false,
    });
    const text = (await page.locator(CARD).innerText()).trim();
    expect(text).toContain("—");
    expect(text).not.toMatch(/\b0%/);
  });

  test("a zero denominator falls back to the percentage alone", async ({ page }) => {
    // "(0 of 0 answers)" would be worse than the bare percentage this issue
    // exists to replace, so the counts are dropped rather than printed.
    await driveToResult(page, {
      answer_count: 0,
      sourced_answer_count: 0,
      sourced_answer_ratio: "0.00",
      target_ratio: "0.80",
      target_met: false,
    });
    const text = (await page.locator(CARD).innerText()).trim();
    expect(text).toContain("0%");
    expect(text).not.toContain("of 0 answer");
  });

  test("a malformed count is not printed", async ({ page }) => {
    // Refuse to display a number the server did not clearly send, rather than
    // rendering "(2.5 of -1 answers)".
    await driveToResult(page, {
      answer_count: -1,
      sourced_answer_count: 2.5,
      sourced_answer_ratio: "0.75",
      target_ratio: "0.80",
      target_met: false,
    });
    const text = (await page.locator(CARD).innerText()).trim();
    expect(text).toContain("75%");
    expect(text).not.toContain("-1");
    expect(text).not.toContain("2.5");
  });
});
