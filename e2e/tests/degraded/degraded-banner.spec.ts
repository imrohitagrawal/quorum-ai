import { test, expect, Page } from "@playwright/test";
import {
  boot,
  goldenCreateResp,
  goldenCompletedResp,
  withEvaluation,
  goldenEvaluation,
  EVAL_LAUNDERED,
  EVAL_UNKNOWN_GROUNDING_REFUSAL,
  EVAL_MISSING_HIGH_STAKES,
  EVAL_SUPPRESSED_DISAGREEMENT,
} from "../../fixtures/golden-run";

/**
 * #26 — degraded-mode banner on the PRIMARY result view.
 *
 * A production run whose live provider is unavailable silently falls back to
 * local simulation; the response marks that via ``live_count``/``local_count``,
 * but the result view rendered the verdict/synthesis as if real. This gate
 * proves the result view now surfaces a prominent "simulated / degraded" banner
 * whenever any answer was not live — and hides it for a fully-live run.
 *
 * It is RED without the fix: with no #result-degraded element (or one left
 * hidden), the simulated-run assertion fails.
 */

const fulfil = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const costEstimateEnvelope = () => ({
  correlation_id: "corr-degraded-est",
  cost_estimate: goldenCreateResp().cost_estimate,
  model_slots: goldenCreateResp().model_slots,
  reasons: [],
});

async function driveWithCompleted(page: Page, completed: Record<string, unknown>) {
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

test.describe("degraded-mode result banner (#26)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  test("a fully-SIMULATED run surfaces the degraded banner on the result view", async ({ page }) => {
    // Simulate the prod silent-fallback: every answer came from local simulation.
    const completed = {
      ...goldenCompletedResp(),
      demo_mode: true,
      live_count: 0,
      local_count: 4,
    };
    await driveWithCompleted(page, completed);

    const banner = page.locator("#result-degraded");
    await expect(banner, "the result view must warn when output is simulated").toBeVisible();
    await expect(banner).toContainText(/simulat/i);
    // The banner must be inside the result body (seen with the verdict), not
    // buried in the composer chrome.
    await expect(page.locator(".result-body #result-degraded")).toBeVisible();
  });

  test("a fully-LIVE run does NOT show the degraded banner", async ({ page }) => {
    const completed = {
      ...goldenCompletedResp(),
      demo_mode: false,
      live_count: 4,
      local_count: 0,
    };
    await driveWithCompleted(page, completed);

    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible();
    await expect(
      page.locator("#result-degraded"),
      "a fully-live run must not claim it is simulated",
    ).toBeHidden();
  });

  test("a PARTLY-simulated run surfaces the mixed degraded banner", async ({ page }) => {
    const completed = {
      ...goldenCompletedResp(),
      demo_mode: true,
      live_count: 2,
      local_count: 2,
    };
    await driveWithCompleted(page, completed);

    const banner = page.locator("#result-degraded");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText(/2 of 4/i);
  });

  test("a run with a FAILED provider slot keeps the honest 'of 4' denominator (RB-5/D3)", async ({
    page,
  }) => {
    // A slot that FAILED on the OpenRouter path is counted in NEITHER live_count
    // nor local_count. With 4 model_slots, live=2 + local=1 leaves 1 failed slot.
    // The denominator must stay the true slot count (4), never live+local (3).
    const completed = {
      ...goldenCompletedResp(),
      demo_mode: true,
      live_count: 2,
      local_count: 1,
    };
    await driveWithCompleted(page, completed);

    const banner = page.locator("#result-degraded");
    await expect(banner).toBeVisible();
    // Honest denominator: 2 of 4 (four slots), not the dishonest 2 of 3.
    await expect(banner).toContainText(/2 of 4/i);
    await expect(banner).not.toContainText(/2 of 3/i);
    // Honest narrative: the 1 failed slot must be named as a failure, NOT
    // folded into "the rest are from local simulation" (which would be false).
    await expect(banner).toContainText(/could not be retrieved because the provider failed/i);
    await expect(banner).not.toContainText(/the rest are from Quorum's local simulation/i);
  });
});

/**
 * RB-5 / D3 — the TRANSCRIPT-view demo-mode banner (#demo-mode-banner, rendered
 * by renderModelPanels) also derives its "N of M" from the served counts. Before
 * the fix it keyed the denominator and the all-live check on live_count +
 * local_count, so a provider-failure run (a FAILED OpenRouter slot is in neither
 * bucket) rendered the self-contradictory "3 of 3 model answers came from a live
 * provider; the remaining 0 are from ... simulation" and silently dropped the
 * failed slot. This gate pins the honest copy: "3 of 4 ... 1 could not be
 * retrieved", never "3 of 3".
 */
test.describe("transcript demo-mode banner — failed-slot honesty (RB-5/D3)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  test("a provider-failure run shows 'N of slotCount' and names the failed slot", async ({
    page,
  }) => {
    // 3 live + 0 local across 4 slots ⇒ 1 slot FAILED (neither live nor local).
    const completed = {
      ...goldenCompletedResp(),
      demo_mode: false,
      live_count: 3,
      local_count: 0,
    };
    await driveWithCompleted(page, completed);

    // Assert on the message target directly — the banner container can flicker
    // hidden→visible as the result settles, but toContainText auto-retries until
    // the honest copy lands.
    const message = page.locator("#demo-mode-banner [data-demo-mode-target]");
    // Honest denominator + the failed slot surfaced.
    await expect(message).toContainText(/3 of 4 model answers came from a live provider/i);
    await expect(message).toContainText(/could not be retrieved because the provider failed/i);
    // The regression this fixes: never the contradictory "3 of 3".
    await expect(message).not.toContainText(/3 of 3/i);
  });
});

/**
 * OC-5 — the misleading-output gate (S3, FR-016). The DEBT-012 laundering shape
 * is the strongest possible case for it: a run whose engine labels read
 * confident but whose provenance is unknown must never present as trustworthy.
 * Unlike the #26 count-driven banner above, this is FAITHFULNESS-driven — a
 * fully-LIVE unfaithful run has no simulated count to trip on.
 */
const SURFACE = "#result-trust-score";

test.describe("misleading-output gate (OC-5)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  test("a fully-LIVE unfaithful run renders the caution treatment", async ({ page }) => {
    const ev = goldenEvaluation({
      faithfulness_label: "unfaithful",
      hallucination_risk: "high",
      signals: { citation_marker_grounding: 0.2, citation_coverage_ratio: 0.3 },
    });
    const completed = withEvaluation(
      { ...goldenCompletedResp(), demo_mode: false, live_count: 4, local_count: 0 },
      ev,
    );
    await driveWithCompleted(page, completed);

    // The simulated-count path CANNOT fire on a fully-live run — so this is a
    // genuinely new, faithfulness-driven gate.
    await expect(page.locator("#result-degraded"), "fully-live: no simulated banner").toBeHidden();

    const surface = page.locator(SURFACE);
    await expect(surface).toBeVisible();
    await expect(surface).toHaveAttribute("data-state", "caution");
    const text = await surface.innerText();
    expect(text).not.toMatch(/\d/);
    expect(text).not.toMatch(/\bfaithful\b|low risk|trustworth|confiden/i);
  });

  test("the laundered evaluation renders the degraded treatment and no confident token", async ({ page }) => {
    const completed = withEvaluation(goldenCompletedResp(), EVAL_LAUNDERED);
    await driveWithCompleted(page, completed);

    const surface = page.locator(SURFACE);
    await expect(surface).toBeVisible();
    await expect(surface).toHaveAttribute("data-state", "indeterminate");
    const text = await surface.innerText();
    expect(text).not.toContain("100");
    expect(text).not.toContain("82");
    expect(text).not.toMatch(/\bfaithful\b/i);
  });

  test("a refusal renders a neutral state, never a trust word", async ({ page }) => {
    const completed = withEvaluation(goldenCompletedResp(), EVAL_UNKNOWN_GROUNDING_REFUSAL);
    await driveWithCompleted(page, completed);

    const surface = page.locator(SURFACE);
    await expect(surface).toBeVisible();
    // Grounding is null on this fixture, so the higher-priority no-marker branch
    // wins over refused — pin it so the two neutral states can't be conflated.
    await expect(surface).toHaveAttribute("data-state", "no-marker");
    const text = await surface.innerText();
    expect(text).toMatch(/could be checked/i);
    expect(text).not.toMatch(/low risk|trustworth|confiden|\bfaithful\b/i);
  });

  test("a missing mandatory safety caveat is surfaced (with a paired negative)", async ({ page }) => {
    // Required && absent ⇒ the amber row is visible.
    await driveWithCompleted(page, withEvaluation(goldenCompletedResp(), EVAL_MISSING_HIGH_STAKES));
    await expect(page.locator(`${SURFACE} .result-trust-score-missing-caveat`)).toBeVisible();

    // Paired negative: required && present ⇒ the row is absent (not vacuous).
    const present = goldenEvaluation({
      signals: { high_stakes_warning_required: true, high_stakes_warning_present: true },
    });
    await driveWithCompleted(page, withEvaluation(goldenCompletedResp(), present));
    await expect(page.locator(`${SURFACE} .result-trust-score-missing-caveat`)).toHaveCount(0);
  });

  test("a suppressed disagreement loses the green Agreement treatment (with a paired positive)", async ({ page }) => {
    const base = goldenCompletedResp();
    // 4/4 aligned + false_consensus_preserved:false ⇒ isConsensus true, so the
    // ONLY thing that can flip the green treatment is disagreement_suppressed.
    const fourFour = { ...base, result: { ...base.result, agreement: { aligned: 4, total: 4 } } };
    const agreementCard = page.locator('#result-trust [data-accent="agreement"]');
    const chip = agreementCard.locator(".result-trust-chip");

    // Suppressed ⇒ the card loses green.
    await driveWithCompleted(page, withEvaluation(fourFour, EVAL_SUPPRESSED_DISAGREEMENT));
    await expect(agreementCard).toHaveAttribute("data-consensus", "false");
    const suppressedChip = await chip.evaluate((n) => getComputedStyle(n).backgroundColor);

    // Paired positive ⇒ not suppressed keeps green.
    await driveWithCompleted(page, withEvaluation(fourFour, goldenEvaluation()));
    await expect(agreementCard).toHaveAttribute("data-consensus", "true");
    const keptChip = await chip.evaluate((n) => getComputedStyle(n).backgroundColor);

    expect(suppressedChip, "suppression must change the agreement chip colour").not.toEqual(keptChip);
  });
});
