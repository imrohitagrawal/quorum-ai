import { test, expect, Page } from "@playwright/test";
import {
  boot,
  goldenCreateResp,
  goldenCompletedResp,
  goldenRespWithCritiqueRows,
  SLOTS,
} from "../../fixtures/golden-run";

/**
 * #290 / ADR-0093 decision 3 — the per-critic `kind: "critique"` receipt rows.
 *
 * WHY THIS SPEC EXISTS. ADR-0093 flagged this render as UNVERIFIED in as many
 * words: `app.js`'s mapper reads
 * `row.kind === "synthesis" ? "Synthesis" : row.display_name`, so a
 * `kind: "critique"` row falls through to `display_name` — and that fall-through
 * was READ, not EXECUTED. Nothing in the repo had ever put such a row in front
 * of a browser.
 *
 * WHAT TURNS EACH TEST RED: named per test. File-level: emit critique rows
 * whose `model_id` collides with a slot row under the same `kind`, or drop the
 * "(critique)" marker from `display_name`, and the two below fail.
 *
 * The fixture deliberately REUSES the four slot model ids for the critics,
 * because that is the case that matters: a slot appears once as `model <id>`
 * and once as `critique <id>`, and only the `kind` half keeps them apart. The
 * receipt pairs estimate rows to actual rows with `.find()` (first match wins)
 * and de-duplicates the backfill with a `Set` of those keys, so a collision
 * renders one figure twice and silently loses the other.
 */

const fulfil = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const costEstimateEnvelope = () => ({
  correlation_id: "corr-critique-est",
  cost_estimate: goldenCreateResp().cost_estimate,
  model_slots: SLOTS,
  reasons: [],
});

async function driveWith(page: Page, completed: Record<string, unknown>) {
  await boot(page);
  await Promise.all([
    page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(costEstimateEnvelope()))),
    page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
    page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
  ]);
  await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => r.fulfill(fulfil(completed)));
  await page.route(/\/v1\/query-runs$/, (r) =>
    r.request().method() === "POST" ? r.fulfill(fulfil(goldenCreateResp())) : r.continue(),
  );
  await page.getByRole("textbox").first().fill("What are the key metrics for measuring SaaS retention?");
  await page.locator("#run-now").click();
  await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
}

/**
 * Every visible label in the BY-MODEL cost column, in DOM order.
 *
 * Scoped to that one column by its `aria-label`, not swept off
 * `.result-receipt-row` across the whole receipt. Measured while writing this
 * spec: the unscoped sweep returns 19 labels of which two pairs repeat --
 * "Total" once per column (correct, and pre-existing) and "Synthesis" in both
 * the by-model and by-stage columns (ADR-0095 records this as accepted: two
 * partitions of one total under two headings, the same pattern "Total" already
 * follows). A uniqueness assertion over that sweep asserts something false
 * about the page, and would have read as a defect in this change.
 *
 * The uniqueness that DOES matter is within one column, where a bare short name
 * on a critique row would print the same string twice against two figures.
 */
async function receiptLabels(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const column = document.querySelector(
      '#main-content [aria-label="Cost by model, estimate to actual"]',
    );
    if (!column) return [];
    return Array.from(column.querySelectorAll(".result-receipt-row"))
      .map((row) => (row.querySelector(".result-receipt-label")?.textContent || "").trim())
      .filter(Boolean);
  });
}

test.describe("#290 critique receipt rows", () => {
  test("every critic's row reaches the receipt with its own visible label", async ({ page }) => {
    // RED WHEN: the mapper drops a non-"model"/"synthesis" kind, or the four
    // critique rows collapse onto one label. Presence AND distinctness are
    // asserted together, because presence alone is satisfied by a receipt that
    // renders the same string four times against four different figures.
    await driveWith(page, goldenRespWithCritiqueRows());
    const labels = await receiptLabels(page);
    // EXACT, not a floor. `toBeGreaterThan(4)` left one row of slack against
    // the 6 the moderator shape renders, so a dropped row could hide in it.
    // 4 slot rows + the writer row + 4 critique rows + Total = 10.
    expect(labels).toHaveLength(10);
    const critique = labels.filter((l) => l.includes("(critique)"));
    expect(critique).toHaveLength(4);
    expect(new Set(critique).size).toBe(4);
    // No label is duplicated anywhere on the receipt: a bare short name on a
    // critique row would print the same string twice against two figures.
    expect(new Set(labels).size).toBe(labels.length);
  });

  test("the receipt explains why the Synthesis row looks like a saving", async ({ page }) => {
    // ADR-0100. Under peer critique the two columns are differently shaped: the
    // ESTIMATE prices both debate rounds inside the writer row, while the
    // ACTUAL breakdown itemises a critique row per critic and subtracts them
    // from it. Nothing is lost — Total agrees — but the Synthesis pairing reads
    // as a saving and the critique rows read as unestimated charges.
    //
    // RED WHEN: the note is dropped, or is rendered outside the by-model
    // column where the confusing pairing actually is.
    await driveWith(page, goldenRespWithCritiqueRows());
    const col = page.locator('[aria-label="Cost by model, estimate to actual"]');
    // POSITIVE PARTNER: the column rendered its rows, so the note assertion
    // below is not being made against an empty or unrendered receipt.
    await expect(col.locator(".result-receipt-row")).toHaveCount(10);
    await expect(col.locator(".result-receipt-note")).toHaveText(
      /only the attribution moves/i,
    );
  });

  test("a moderator run gets no attribution note, because nothing moved", async ({
    page,
  }) => {
    // NEGATIVE PARTNER to the test above. The note is keyed on the run's own
    // critique rows, not on a deployment flag, so a run billed no critique
    // charges must not carry an explanation for charges it never had.
    await driveWith(page, goldenCompletedResp());
    const col = page.locator('[aria-label="Cost by model, estimate to actual"]');
    await expect(col.locator(".result-receipt-row")).toHaveCount(6);
    await expect(col.locator(".result-receipt-note")).toHaveCount(0);
  });

  test("a run with no critique rows renders exactly what it rendered before", async ({ page }) => {
    // POSITIVE PARTNER (AGENTS.md rule 7). "No duplicate labels" and "four
    // critique rows" are both satisfiable by a build that renders nothing at
    // all, so the default shape must still render its own rows — and must NOT
    // grow a critique row it was never sent.
    await driveWith(page, goldenCompletedResp());
    const labels = await receiptLabels(page);
    // 4 slot rows + the writer row + Total = 6, exactly.
    expect(labels).toHaveLength(6);
    expect(labels.filter((l) => l.includes("(critique)"))).toHaveLength(0);
    // NOT asserting the writer row's TEXT here. Review showed that would test
    // the fixture, not `src/`: this receipt column renders
    // `line.display_name` straight through, so `toContain("Synthesis")` is
    // satisfied by golden-run.ts's own hard-coded string and cannot go red for
    // any server change. The label is pinned where the override actually lives
    // — `test_cost_gate_js.py::test_the_javascript_writer_label_matches_the_server_constant`,
    // which drives the cost-gate mapper and compares it against
    // `costs.WRITER_ROW_DISPLAY_NAME`.
    expect(labels.filter((l) => l === "Total")).toHaveLength(1);
  });
});
