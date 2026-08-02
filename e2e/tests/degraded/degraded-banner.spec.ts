import { test, expect, Page } from "@playwright/test";
import {
  boot,
  goldenCreateResp,
  goldenCompletedResp,
  withEvaluation,
  goldenEvaluation,
  driveToTranscript,
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
    // Honest narrative: the 1 missing slot must be named separately, NOT folded
    // into "the rest are from local simulation" (which would be false).
    //
    // The copy is deliberately NEUTRAL about why the slot is empty. It used to
    // say "could not be retrieved because the provider failed" — a cause the
    // browser cannot know, and usually the wrong one: a live provider error
    // becomes a SIMULATED answer in production, so an empty slot came from a
    // cancel or the run deadline. Asserting an unverified cause is the defect
    // this work package exists to remove, so the test must not demand it back.
    await expect(banner).toContainText(/1 returned nothing/i);
    await expect(banner).not.toContainText(/the provider failed/i);
    await expect(banner).not.toContainText(/the rest are from Quorum's local simulation/i);
  });

  test("a short panel is disclosed even when NOTHING was simulated", async ({ page }) => {
    // The gap this test exists for. There are two ways a panel comes up short:
    //
    //   * an answer was SIMULATED        -> local_count goes up
    //   * a slot produced NO answer      -> counted in NEITHER count
    //
    // A slot produces no answer when the user cancels it or the run deadline
    // expires. Then local_count is 0, and a banner keyed on "were any answers
    // simulated?" stays hidden — so the reader was shown a verdict and a
    // synthesis built from three of four answers with no disclosure anywhere,
    // while the headline still read "3 of 4 models aligned", which describes a
    // disagreement rather than a missing answer.
    //
    // TURNS RED IF: renderResultDegraded goes back to keying `degraded` on
    // `localCount > 0` alone — the banner is hidden here and toBeVisible fails.
    const completed = {
      ...goldenCompletedResp(),
      demo_mode: false,
      live_count: 3,
      local_count: 0,
    };
    await driveWithCompleted(page, completed);

    const banner = page.locator("#result-degraded");
    await expect(
      banner,
      "a panel missing an answer must be disclosed even though nothing was simulated",
    ).toBeVisible();
    await expect(banner).toContainText(/3 of 4/i);
    await expect(banner).toContainText(/did not respond/i);
    // Nothing was simulated on this run, so NEITHER the message NOR THE TITLE may
    // say otherwise. The title is asserted separately and on purpose: an earlier
    // version of this test used /simulation/i over the whole banner, which does
    // NOT match the word "simulated" — so deleting the title branch left the
    // title reading "Partly simulated result" on a run with nothing simulated,
    // and this test still passed. /simulat/ catches both spellings.
    await expect(banner).not.toContainText(/simulat/i);
    await expect(page.locator("#result-degraded-title")).toHaveText(
      /Incomplete result — not every model answered/,
    );
  });

  test("a run that is PART simulated and PART missing names both, not just the simulation", async ({
    page,
  }) => {
    // 0 live + 2 simulated across 4 slots ⇒ 2 slots returned nothing. The
    // all-simulated copy claims "this WHOLE result ... comes from Quorum's local
    // simulation", which is false here: half the panel came from nothing at all,
    // and the clause that names missing slots was unreachable whenever
    // live_count was 0.
    //
    // TURNS RED IF: describePanelShortfall loses its `noLive && missing > 0`
    // branch and falls through to the fully-simulated sentence — that sentence
    // says "this WHOLE result comes from Quorum's local simulation" and contains
    // no number, so both assertions below fail.
    const completed = {
      ...goldenCompletedResp(),
      demo_mode: true,
      live_count: 0,
      local_count: 2,
    };
    await driveWithCompleted(page, completed);

    const banner = page.locator("#result-degraded");
    await expect(banner).toBeVisible();
    // BOTH shortfalls named, with their own counts: 2 simulated, 2 missing.
    await expect(banner).toContainText(/2 came from Quorum's local simulation/i);
    await expect(banner).toContainText(/2 returned nothing/i);
    // And it must not claim the WHOLE result was simulated, which is the false
    // sentence this case used to fall through to.
    await expect(banner).not.toContainText(/whole result/i);
  });

  test("a run where NO model answered says so, instead of blaming simulation", async ({ page }) => {
    // 0 live + 0 simulated across 4 slots ⇒ every slot returned nothing. Nothing
    // was simulated, so "Simulated result — not from real models" would be false;
    // and "based only on the answers that arrived" would be absurd, because none
    // arrived.
    //
    // TURNS RED IF: describePanelShortfall loses its `allMissing` branch.
    const completed = {
      ...goldenCompletedResp(),
      demo_mode: false,
      live_count: 0,
      local_count: 0,
    };
    await driveWithCompleted(page, completed);

    const banner = page.locator("#result-degraded");
    await expect(banner).toBeVisible();
    await expect(page.locator("#result-degraded-title")).toHaveText(
      /No result — no model answered/,
    );
    await expect(banner).toContainText(/None of the 4 models returned an answer/i);
    await expect(banner).not.toContainText(/simulat/i);
  });
});

/*
 * #115 — the transcript view's OWN disclosure banner (`#demo-mode-banner`).
 *
 * Until this fix, `#demo-mode-banner` sat inside `section.panel.panel-section`,
 * which `app.css` hides on every view by design (screen-isolation parity).
 * `renderModelPanels` kept it correctly up to date (right hidden state, right
 * copy) but no user could ever see it — and the blocking gate that used to
 * assert on it (RB-5 / D3) used `toContainText`, which does not require
 * visibility, so it certified the honesty of markup nobody could read. That
 * half was removed above; the property it pinned now lives on `#result-degraded`
 * (the two tests above asserting `toBeVisible()`).
 *
 * `#demo-mode-banner` itself is NOT redundant with `#result-degraded` — WP-H
 * measured a real run (3 live, 0 simulated, 1 slot that produced no answer) where
 * `#result-degraded` stayed correctly scoped to the result view and the
 * transcript view had no run-level disclosure of its own at all. So #115 moves
 * the banner out of the hidden section into the transcript view's own markup
 * (`.transcript-body`, above the opening positions), giving the transcript a
 * disclosure surface that matches the result view's.
 *
 * These tests assert `toBeVisible()`, never `toContainText` alone — the exact
 * failure mode this file already lived through once.
 */
test.describe("transcript-view disclosure banner (#115)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  test("a run with a FAILED provider slot shows the transcript's own disclosure banner", async ({
    page,
  }) => {
    // 2 live + 1 simulated across 4 slots leaves 1 slot that returned nothing.
    const completed = {
      ...goldenCompletedResp(),
      demo_mode: true,
      live_count: 2,
      local_count: 1,
    };
    await driveWithCompleted(page, completed);
    await driveToTranscript(page);

    const banner = page.locator("#demo-mode-banner");
    // TURNS RED IF #demo-mode-banner is left inside the hidden
    // `.panel.panel-section` — this is exactly the #115 defect.
    await expect(banner, "the transcript view must disclose a short panel").toBeVisible();
    await expect(page.locator("#demo-mode-banner-title")).toHaveText(/Partly simulated result/);
    await expect(banner).toContainText(/2 of 4 model answers came from a live provider/i);
    await expect(banner).toContainText(/1 returned nothing/i);
  });

  test("a short panel with NOTHING simulated is still disclosed in the transcript view", async ({
    page,
  }) => {
    // 3 live + 0 simulated across 4 slots ⇒ 1 slot returned nothing, and
    // nothing was simulated — the case the old `localCount > 0` gating missed.
    const completed = {
      ...goldenCompletedResp(),
      demo_mode: false,
      live_count: 3,
      local_count: 0,
    };
    await driveWithCompleted(page, completed);
    await driveToTranscript(page);

    const banner = page.locator("#demo-mode-banner");
    await expect(
      banner,
      "a panel missing an answer must be disclosed in the transcript view too, even though nothing was simulated",
    ).toBeVisible();
    await expect(page.locator("#demo-mode-banner-title")).toHaveText(
      /Incomplete result — not every model answered/,
    );
    await expect(banner).toContainText(/3 of 4 model answers came from a live provider/i);
    await expect(banner).toContainText(/1 returned nothing/i);
  });

  test("a fully-LIVE run does NOT show the transcript disclosure banner", async ({ page }) => {
    const completed = {
      ...goldenCompletedResp(),
      demo_mode: false,
      live_count: 4,
      local_count: 0,
    };
    await driveWithCompleted(page, completed);
    await driveToTranscript(page);

    await expect(
      page.locator("#demo-mode-banner"),
      "a fully-live run must not claim a shortfall in the transcript view",
    ).toBeHidden();
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
