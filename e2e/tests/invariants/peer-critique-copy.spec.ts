import { test, expect, Page } from "@playwright/test";
import {
  boot,
  goldenCreateResp,
  goldenCompletedResp,
  goldenRespWithPeerDebate,
  SLOTS,
} from "../../fixtures/golden-run";

/**
 * #290 / ADR-0095 — the copy must not contradict the receipt.
 *
 * THE DEFECT THIS PREVENTS, stated concretely. Under the peer shape a run makes
 * eight critique calls, the backend records `slot_critiques` (a genuine
 * per-model record), and the receipt itemises a `(critique)` charge PER MODEL.
 * Three surfaces nevertheless told the reader:
 *
 *   "Quorum does not record a per-model, line-by-line exchange."
 *   "Quorum does not record a per-model, line-by-line transcript."
 *   "The moderator model is critiquing the four answers for this round."
 *
 * The first two are false statements about the reader's OWN MONEY, printed
 * directly above four per-model critique charges. The third names a call that
 * under this shape is never made.
 *
 * All three were true under the moderator shape, which is why they shipped and
 * why the fix is SHAPE-AWARE rather than a rewrite: both shapes ship, and a
 * caption that is false under either is a caption that has to branch.
 *
 * WHAT TURNS EACH TEST RED: named per test. File-level: make either caption a
 * fixed string again and the peer half fails.
 */

const fulfil = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const costEstimateEnvelope = () => ({
  correlation_id: "corr-peer-copy",
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

/** The DENIAL that becomes false under the peer shape, on either surface. */
const DENIAL = /does not record a per-model/i;

test.describe("#290 peer-critique copy", () => {
  test("a peer run never denies keeping a per-model record", async ({ page }) => {
    // RED WHEN: the result caption goes back to a fixed string.
    await driveWith(page, goldenRespWithPeerDebate());
    const caption = page.locator(".result-debate-caption");
    await expect(caption).toBeVisible();
    await expect(caption).not.toHaveText(DENIAL);
    // ... and says something true instead, rather than merely saying nothing.
    await expect(caption).toContainText(/critiqued the others/i);
  });

  test("a MODERATOR run still keeps the denial, because it is true there", async ({ page }) => {
    // POSITIVE PARTNER (AGENTS.md rule 7). "Never denies" is trivially
    // satisfied by deleting the caption; the shipped default must still carry
    // the honest disclosure that the backend keeps no per-model attribution.
    await driveWith(page, goldenCompletedResp());
    const caption = page.locator(".result-debate-caption");
    await expect(caption).toBeVisible();
    await expect(caption).toHaveText(DENIAL);
  });

  test("the transcript caption follows the same shape", async ({ page }) => {
    // RED WHEN: the static caption in workspace.html is left uncorrected.
    // It is server-rendered once and cannot branch, so renderTranscript has to
    // fix it at the only point that knows what this run did.
    await driveWith(page, goldenRespWithPeerDebate());
    await page.locator("#result-transcript-link").click();
    const caption = page.locator(".transcript-debate-caption");
    await expect(caption).toBeVisible();
    await expect(caption).not.toHaveText(DENIAL);
    await expect(caption).toContainText(/critiqued the others/i);
  });

  test("no surface names the moderator as the critic", async ({ page }) => {
    // RED WHEN: any surface names the moderator on a peer run.
    // Under the peer shape no moderator call is made at all, so naming one is
    // a claim about work that did not happen.
    //
    // The bare `not.toContain` below is NOT the test — on its own it would
    // pass against a page that rendered nothing at all, which is exactly what
    // `check-negative-assertions.mjs` flagged when this spec was first
    // written. The two POSITIVE assertions around it are what make the
    // absence meaningful: the debate section must have rendered, and must be
    // saying the true thing, before "does not say the false thing" carries
    // any weight (AGENTS.md rule 7).
    await driveWith(page, goldenRespWithPeerDebate());
    const main = page.locator("#main-content");
    await expect(main.locator(".result-debate-caption")).toBeVisible();
    const body = (await main.innerText()).toLowerCase();
    expect(body).toContain("critiqued the others");
    expect(body).not.toContain("the moderator model is critiquing");
  });
});
