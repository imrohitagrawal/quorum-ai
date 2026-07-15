import { test, expect, Page } from "@playwright/test";

/**
 * Behavioural regression suite for the design-comp parity change.
 *
 * The axe suite (axe-all-views.spec.ts) proves the views are accessible; this
 * suite proves they actually WORK as intended: screen isolation, the new result
 * synthesis card + follow-up block, cost-gate band button visibility, vendor
 * tints, friendly model names, and — critically — that untrusted source URLs
 * can never become a javascript: anchor.
 *
 * Chromium only (the browser provisioned in this repo). Reuses the same mock
 * fixtures/shapes as the axe suite so the data-driven views populate offline.
 */

const SLOTS = [
  { slot_number: 1, model_id: "openai/gpt-4o-mini", display_label: "GPT-4o-mini" },
  { slot_number: 2, model_id: "anthropic/claude-haiku-4.5", display_label: "Claude Haiku 4.5" },
  { slot_number: 3, model_id: "google/gemini-2.5-flash", display_label: "Gemini 2.5 Flash" },
  { slot_number: 4, model_id: "deepseek/deepseek-v3.1", display_label: "DeepSeek V3.1" },
];
const CC = { material_claim_count: 12, cited_claim_count: 10, coverage_ratio: "0.85", target_ratio: "0.80", target_met: true };
const BY_MODEL = [
  { model_id: "openai/gpt-4o-mini", display_name: "GPT-4o-mini", usd: "0.034", kind: "model" },
  { model_id: "anthropic/claude-haiku-4.5", display_name: "Claude Haiku 4.5", usd: "0.062", kind: "model" },
  { model_id: "google/gemini-2.5-flash", display_name: "Gemini 2.5 Flash", usd: "0.031", kind: "model" },
  { model_id: "deepseek/deepseek-v3.1", display_name: "DeepSeek V3.1", usd: "0.039", kind: "model" },
  { model_id: "synthesis", display_name: "Debate + synthesis", usd: "0.024", kind: "synthesis" },
];
const BY_STAGE = [
  { stage: "initial_answers", usd: "0.120" }, { stage: "debate", usd: "0.046" }, { stage: "synthesis", usd: "0.024" },
];
const breakdown = (total = "0.190") => ({ by_model: BY_MODEL, by_stage: BY_STAGE, total });
const costEstimate = (total: string, action: string) => ({
  estimated_cost_usd: total,
  // issue #16: the fail-safe "up to $Y" bound the guardrail evaluates. Set a
  // clear worst-case above the point estimate so the confirm-band range renders
  // the real point→bound span (0.190 → ~0.23).
  max_cost_usd: (Number(total) * 1.2).toFixed(4),
  currency: "USD", threshold_action: action, confirmation_token: "tok-abc123",
  reasons: action === "block" ? ["Estimated spend exceeds the $0.25 hard cap."] : [], breakdown: breakdown(total),
});
const estimateResp = (total: string, action: string) => ({
  correlation_id: "corr-est-0001", cost_estimate: costEstimate(total, action), model_slots: SLOTS,
  reasons: action === "block" ? ["Estimated spend exceeds the $0.25 hard cap."] : [],
});
// ``sources`` overridable so the security test can inject a hostile URL.
const answer = (i: number, sources?: unknown[]) => ({
  slot_number: i + 1, model_id: SLOTS[i].model_id,
  answer_text: `Model ${SLOTS[i].display_label} answer text with a material claim [1].`,
  sources: sources ?? [
    { title: "Source A", url: "https://example.com/a", provider: "openrouter_search" },
    { title: "Source B", url: "https://example.com/b", provider: "openrouter_search" },
  ],
  provider_attempt_order: ["openrouter_search"], provider_path: "openrouter_search",
  fallback_used: false, status: "completed", latency_ms: 2200 + i * 100, citation_coverage: CC,
});
const debateOutputs = () => [
  { round_number: 1, status: "completed", critique_text: "Round 1 critique: models largely align on the core recommendation.", focus_areas: ["scope", "evidence"], contributing_models: SLOTS.map((s) => s.model_id), latency_ms: 3100 },
  { round_number: 2, status: "completed", critique_text: "Round 2 critique: residual disagreement resolved; citations verified.", focus_areas: ["citations"], contributing_models: SLOTS.map((s) => s.model_id), latency_ms: 2800 },
];
const positionMovements = () => SLOTS.map((s, i) => ({
  slot_number: s.slot_number, model_id: s.model_id, display_name: s.display_label,
  opening: `Opening synopsis for ${s.display_label}.`,
  after_round_1: i < 2 ? "Revised after round 1 critique." : "Held its opening position.",
  final: "Aligned with the final synthesis.", revised: i < 2, revision_note: i < 2 ? "Adjusted after round 1 critique." : null,
}));
const finalSynthesis = () => ({
  status: "completed", consensus: "The models agree on the primary recommendation.",
  disagreement: "Minor wording differences only.", source_support: "Backed by cited sources across all responding models.",
  uncertainty: "Confidence is moderate to high given corroborating citations.",
  recommendation: "Proceed with the recommended approach.", citation_coverage: CC,
  quality_checks: { citation_coverage_target_met: true, false_consensus_preserved: false, decision_support_framing_present: true, high_stakes_warning_required: false },
  high_stakes_notice: null, latency_ms: 4200,
});
const progress = (stage: string, states: string[]) => ({
  current_stage: stage,
  stages: [
    { stage: "initial_answers", state: states[0] }, { stage: "debate_round_1", state: states[1] },
    { stage: "debate_round_2", state: states[2] }, { stage: "synthesis", state: states[3] },
  ],
});
const createResp = () => ({
  query_run_id: "11111111-1111-4111-8111-111111111111", status: "accepted", correlation_id: "corr-run-0001",
  model_slots: SLOTS, cost_estimate: costEstimate("0.100", "allow"),
  progress: progress("initial_answers", ["running", "pending", "pending", "pending"]), initial_answers: [],
});
const completedResp = (sourcesForSlot0?: unknown[]) => ({
  query_run_id: "11111111-1111-4111-8111-111111111111", status: "completed", correlation_id: "corr-run-0001",
  model_slots: SLOTS, cost_estimate: costEstimate("0.190", "require_confirmation"), elapsed_time_ms: 41200,
  failed_steps: [], missing_steps: [], progress: progress("synthesis", ["completed", "completed", "completed", "completed"]),
  partial_failure_notice: null, provider_failure_notices: [],
  result: {
    model_answers: [answer(0, sourcesForSlot0), answer(1), answer(2), answer(3)], debate_outputs: debateOutputs(),
    final_synthesis: finalSynthesis(), agreement: { aligned: 4, total: 4 }, position_movements: positionMovements(),
  },
  result_generated_at_utc: "2026-07-10T12:00:00Z", demo_mode: false, live_count: 4, local_count: 0, material_claim_count: 12,
  actual_cost_usd: "0.188", actual_breakdown: breakdown("0.188"),
});
const fulfil = (body: unknown, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify(body) });

const QUESTION = "What are the key metrics for measuring SaaS customer retention?";

async function boot(page: Page) {
  // These suites exercise the WORKSPACE (screen 02). Seed the first-visit gate's
  // "workspace seen" flag so every boot lands on the composer directly, exactly
  // as a returning visitor would — the landing front-door path is covered by its
  // own dedicated test below. addInitScript runs before app.js on every load.
  await page.addInitScript(() => {
    try { window.localStorage.setItem("quorum.workspaceSeen", "1"); } catch (_) {}
  });
  await page.goto("/ui", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-view="composer"]')).toBeVisible();
  await page.waitForFunction(() => {
    const slots = [...document.querySelectorAll("[data-model-slot]")];
    return slots.length === 4 && slots.every((s) => (s as HTMLInputElement).value?.trim().length > 0);
  }, { timeout: 15000 });
}
async function fill(page: Page) { await page.getByRole("textbox").first().fill(QUESTION); }
async function clickEstimate(page: Page) {
  await page.getByRole("button", { name: /see the estimate|estimate cost/i }).click();
}
// "Run now" is the direct-run composer CTA: for an allow-band estimate it
// auto-proceeds straight to the run (no gate), so it is the fast path for
// tests that only need to REACH the result view. "See the estimate" now always
// opens the cost gate — even on the allow band — so it is no longer the way to
// drive to a result without a click-through.
async function clickRunNow(page: Page) {
  await page.locator("#run-now").click();
}
async function routeRun(page: Page, pollBody: unknown) {
  await page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(estimateResp("0.100", "allow"))));
  await page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] })));
  await page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null })));
  await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => r.fulfill(fulfil(pollBody)));
  await page.route(/\/v1\/query-runs$/, (r) =>
    r.request().method() === "POST" ? r.fulfill(fulfil(createResp())) : r.continue());
}
async function driveToResult(page: Page, pollBody: unknown) {
  await boot(page);
  await routeRun(page, pollBody);
  // Use "Run now" (direct auto-proceed on the mocked allow band) to reach the
  // result. "See the estimate" would stop at the gate — that path has its own
  // dedicated tests below.
  await fill(page); await clickRunNow(page);
  await expect(page.locator('#result-verdict[data-consensus="true"]')).toBeVisible();
}

test.describe("UI parity — behaviour", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "chromium-only reference run");

  test("composer isolates itself — no legacy aside/panel-sections/stepper; example + disclaimer chips work", async ({ page }) => {
    await boot(page);
    await expect(page.locator(".workflow-progress")).toBeHidden();
    await expect(page.locator(".layout > aside")).toBeHidden();
    for (const s of await page.locator(".panel-section").all()) await expect(s).toBeHidden();
    // Example chips present and fill the textarea.
    const chips = page.locator(".composer-examples .landing-chip");
    await expect(chips).toHaveCount(4);
    await chips.first().click();
    await expect(page.getByRole("textbox").first()).toHaveValue(/Usage-based vs seat pricing\?/);
    // Disclaimer chips present.
    await expect(page.locator(".composer-disclaimers .landing-disclaimer")).toHaveCount(3);
  });

  test("model slots carry per-vendor tints", async ({ page }) => {
    await boot(page);
    const vendors = await page.locator("#model-inputs .model-slot-avatar").evaluateAll(
      (els) => els.map((e) => (e as HTMLElement).dataset.vendor));
    expect(vendors).toEqual(["openai", "anthropic", "google", "deepseek"]);
  });

  test("cost-gate confirm band shows only Confirm/Back; block-band buttons hidden", async ({ page }) => {
    await boot(page);
    await page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(estimateResp("0.190", "require_confirmation"))));
    await page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] })));
    await fill(page); await clickEstimate(page);
    await expect(page.locator("#gate-confirm")).toBeVisible();
    await expect(page.locator("#gate-back")).toBeVisible();
    await expect(page.locator("#gate-block-models")).toBeHidden();
    await expect(page.locator("#gate-block-shorten")).toBeHidden();
    await expect(page.locator("#gate-confirm")).toContainText(/Confirm & run/);
    await expect(page.locator("#cost-gate-total")).toContainText("$0.19");
    // The range shows the REAL point→bound span (typical $0.19 → up to ~$0.23),
    // not a fabricated ±band, so the confirmation is legible.
    await expect(page.locator("#cost-gate-range")).toContainText("$0.23");
  });

  test("cost-gate block band shows recovery buttons; confirm hidden", async ({ page }) => {
    await boot(page);
    await page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(estimateResp("0.300", "block"))));
    await page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] })));
    await fill(page); await clickEstimate(page);
    await expect(page.locator('#cost-review-card[data-band="block"]')).toBeVisible();
    await expect(page.locator("#gate-block-models")).toBeVisible();
    await expect(page.locator("#gate-block-shorten")).toBeVisible();
    await expect(page.locator("#gate-confirm")).toBeHidden();
  });

  test("composer offers both a Run now and a See the estimate CTA, both enabled", async ({ page }) => {
    await boot(page);
    const runNow = page.locator("#run-now");
    const seeEstimate = page.locator("#estimate-run");
    await expect(runNow).toBeVisible();
    await expect(runNow).toBeEnabled();
    await expect(runNow).toContainText(/run now/i);
    await expect(seeEstimate).toBeVisible();
    await expect(seeEstimate).toBeEnabled();
    await expect(seeEstimate).toContainText(/see the estimate/i);
  });

  test("See the estimate ALWAYS opens the cost gate — even for an allow-band run (never a hidden auto-run)", async ({ page }) => {
    // The footer promises the user can review an itemized estimate before a run.
    // A cheap (allow-band) run used to skip the gate and execute immediately,
    // contradicting that promise. "See the estimate" must now stop at the gate
    // for every band; the allow band shows a non-alarming "review and run" CTA.
    await boot(page);
    await page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(estimateResp("0.100", "allow"))));
    await page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] })));
    // If it wrongly auto-proceeded, THIS create POST would fire — assert it does not.
    let created = false;
    await page.route(/\/v1\/query-runs$/, (r) => {
      if (r.request().method() === "POST") created = true;
      return r.fulfill(fulfil(createResp()));
    });
    await fill(page); await clickEstimate(page);
    // The gate is shown with the allow-band review copy and a plain "Run" CTA
    // (not "Confirm & run", which is the require_confirmation band).
    await expect(page.locator("#cost-review-card")).toBeVisible();
    await expect(page.locator("#gate-confirm")).toBeVisible();
    // Allow-band CTA reads "Run · $X" (a plain start), never the
    // require_confirmation band's "Confirm & run · $X". Assert on the label span
    // so the spinner sibling's whitespace never pollutes the match.
    await expect(page.locator("#gate-confirm .button-label")).toHaveText(/^Run · \$0\.1\d*$/);
    await expect(page.locator("#gate-confirm .button-label")).not.toContainText(/Confirm & run/);
    // And nothing ran on its own.
    await page.waitForTimeout(200);
    expect(created, "See the estimate must not auto-start an allow-band run").toBe(false);
  });

  test("HARDENING: while one CTA's estimate is in flight, BOTH composer CTAs lock and only ONE create is ever POSTed", async ({ page }) => {
    // The two-button composer widened a pre-existing re-entrancy window: only the
    // clicked button was disabled during the estimate round-trip, so the sibling
    // (or Ctrl/Cmd+Enter) could fire a second concurrent flow, and ``isRunning``
    // (which locks everything) is only set after the create POST returns. Hold
    // the estimate open with a controlled gate so the window is deterministic,
    // and prove both CTAs are locked and no second create escapes.
    await boot(page);
    let createCount = 0;
    let releaseEstimate!: () => void;
    const estimateGate = new Promise<void>((res) => { releaseEstimate = res; });
    await page.route("**/v1/query-runs/estimate", async (r) => {
      await estimateGate; // hold the estimate open to freeze the re-entrancy window
      await r.fulfill(fulfil(estimateResp("0.100", "allow")));
    });
    await page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] })));
    await page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null })));
    await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => r.fulfill(fulfil(completedResp())));
    await page.route(/\/v1\/query-runs$/, (r) => {
      if (r.request().method() === "POST") { createCount++; return r.fulfill(fulfil(createResp())); }
      return r.continue();
    });

    await fill(page);
    await page.locator("#run-now").click();
    // Estimate is held open → both composer CTAs are locked for the whole window.
    await expect(page.locator("#run-now")).toBeDisabled();
    await expect(page.locator("#estimate-run")).toBeDisabled();
    // Release the estimate; the Run-now allow-band path auto-proceeds to a run.
    releaseEstimate();
    await expect(page.locator('#result-verdict[data-consensus="true"]')).toBeVisible();
    // Exactly one create was POSTed — the single-create latch held.
    expect(createCount, "exactly one create must be POSTed").toBe(1);
  });

  test("REGRESSION: a completed run whose slots carry a provider_notice renders with no 'runStatusValue is not defined' toast storm", async ({ page }) => {
    // The toast storm fired ONLY when a model slot carried a ``provider_notice``:
    // the guard that reads it was the sole reader of a variable that had been
    // ``const``-scoped to a sibling branch, so on a completed run it threw
    // ``ReferenceError: runStatusValue is not defined`` once per card on every
    // poll tick — each surfaced as a toast. The mock ``answer()`` has no
    // provider_notice, so the storm was invisible to this suite; set one here so
    // the completed-run render actually exercises the guarded branch.
    const withNotice = completedResp();
    (withNotice.result as { model_answers: { provider_notice: string }[] }).model_answers.forEach(
      (a) => { a.provider_notice = "Answer produced by local simulation."; },
    );

    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    await driveToResult(page, withNotice);

    // The provider notice renders on the cards — proving the guarded branch ran.
    await expect(page.locator(".model-card-notice").first()).toContainText("local simulation");
    // No "... is not defined" surfaced as a toast (the pre-fix storm) ...
    await expect(page.locator(".toast", { hasText: /is not defined/i })).toHaveCount(0);
    // ... and no uncaught page error slipped through either.
    expect(pageErrors, `unexpected page errors: ${JSON.stringify(pageErrors)}`).toEqual([]);
  });

  test("result renders the synthesis card + next-question block + footer; legacy sections hidden", async ({ page }) => {
    await driveToResult(page, completedResp());
    const synth = page.locator("#result-synthesis");
    await expect(synth).toBeVisible();
    for (const label of ["Consensus", "Disagreement", "Uncertainty", "Recommendation", "Sources"]) {
      await expect(synth.locator(".result-synth-label", { hasText: new RegExp(`^${label}$`, "i") })).toBeVisible();
    }
    await expect(synth.locator(".result-synth-body").first()).toContainText("The models agree on the primary recommendation.");
    await expect(page.locator(".result-next")).toBeVisible();
    await expect(page.locator("#result-followup")).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".result-footer")).toContainText(/Ephemeral/);
    // Legacy scaffolding stays hidden on the result screen too.
    for (const s of await page.locator(".panel-section").all()) await expect(s).toBeHidden();
  });

  test("result header labels the Run ID with a copy affordance and an explanatory info icon", async ({ page }) => {
    // A bare ``qr_…`` / ``corr-…`` value means nothing on its own. The header
    // must label it "Run ID", make it click-to-copy, and attach an info icon
    // that explains its significance (quote it to support). The aside that used
    // to carry this is hidden in the parity design, so the header is the only
    // place a user sees the id.
    await driveToResult(page, completedResp());
    const runId = page.locator(".result-meta-runid");
    await expect(runId).toBeVisible();
    await expect(runId.locator(".result-meta-runid-label")).toHaveText("Run ID");
    const copy = runId.locator(".result-meta-runid-copy");
    await expect(copy).toHaveText("corr-run-0001");
    await expect(copy).toHaveAttribute("aria-label", /copy run id/i);
    const info = runId.locator(".info-icon-inline");
    await expect(info).toBeVisible();
    await expect(info).toHaveAttribute("data-info-text", /quote it if you report a problem to support/i);
    await expect(info).toHaveAttribute("aria-label", /what is the run id/i);
  });

  test("Run ID is ONE id everywhere: the receipt shows a single friendly Run ID (qr_ form) with an info icon and NO redundant raw-UUID row", async ({ page }) => {
    // correlation_id = "qr_" + query_run_id.hex — the SAME id in two formats. The
    // user sees ONE "Run ID" (the friendly qr_/correlation form) in the header AND
    // the receipt. The raw UUID adds a second ID-looking value for no user benefit,
    // so it is dropped from the user-facing receipt entirely.
    await driveToResult(page, completedResp());
    // Header "Run ID" copy value is the correlation id.
    await expect(page.locator(".result-meta-runid-copy")).toHaveText("corr-run-0001");
    await page.locator("#result-details-toggle").click();
    await expect(page.locator("#result-receipt")).toBeVisible();
    // Exactly one row labelled "Run ID" in the receipt, and it shows the SAME id
    // as the header (not the UUID), with an info icon.
    const runIdLabel = page.locator("#result-receipt .result-receipt-label", { hasText: /^Run ID\b/ });
    await expect(runIdLabel).toHaveCount(1);
    const runIdRow = page
      .locator("#result-receipt .result-receipt-row")
      .filter({ hasText: "Run ID" })
      .filter({ hasText: "corr-run-0001" });
    await expect(runIdRow).toHaveCount(1);
    await expect(runIdRow.locator(".info-icon")).toBeVisible();
    // The raw UUID is NOT shown at all — no "Internal reference" row and the UUID
    // string appears nowhere in the receipt.
    await expect(page.locator("#result-receipt .result-receipt-label", { hasText: /internal reference/i })).toHaveCount(0);
    await expect(page.locator("#result-receipt")).not.toContainText("11111111-1111-4111-8111-111111111111");
    // The old "Correlation" label is gone too (it was the same id under a confusing name).
    await expect(page.locator("#result-receipt .result-receipt-label", { hasText: /^Correlation$/ })).toHaveCount(0);
  });

  test("Run ID is ONE id everywhere: the provider-failure footer quotes the single friendly Run ID, not the raw UUID too", async ({ page }) => {
    // A failed run's support footer used to quote BOTH ids ("qr_… · <uuid>"),
    // re-introducing the same two-competing-ids confusion the receipt fix removed.
    // It must quote ONE friendly Run ID, matching the header/receipt.
    await boot(page);
    const failed = {
      query_run_id: "11111111-1111-4111-8111-111111111111",
      status: "failed",
      correlation_id: "corr-run-0001",
      model_slots: SLOTS,
      failed_steps: ["synthesis"],
      missing_steps: [],
      provider_failure_notices: ["The synthesis provider was temporarily unavailable."],
      partial_failure_notice: null,
      progress: progress("synthesis", ["completed", "completed", "completed", "failed"]),
      // A failed run still carries a (synthesis-less) result object; pollRun
      // dereferences result.result.model_answers before the terminal branch.
      result: {
        model_answers: [answer(0), answer(1), answer(2), answer(3)],
        debate_outputs: [],
        final_synthesis: null,
        agreement: { aligned: 0, total: 4 },
        position_movements: [],
      },
    };
    await routeRun(page, failed);
    await fill(page);
    await clickRunNow(page);
    const footer = page.locator("#error-region-footer");
    await expect(footer).toBeVisible();
    await expect(footer).toContainText("Run ID corr-run-0001");
    await expect(footer).toContainText("quote when reporting");
    // The raw UUID is NOT quoted alongside it.
    await expect(footer).not.toContainText("11111111-1111-4111-8111-111111111111");
  });

  test("Run details receipt: est→actual values never overflow their column into the next section", async ({ page }) => {
    // The receipt is a 4-column grid and the "$X → $Y" values are nowrap; on a
    // constrained width they used to overflow their column into the neighbouring
    // section (measured up to ~35px). Drive at a deliberately narrow-but-still-4-col
    // width so the pre-fix overflow condition is present, and assert none overflow.
    await page.setViewportSize({ width: 900, height: 900 });
    await driveToResult(page, completedResp());
    await page.locator("#result-details-toggle").click();
    await expect(page.locator("#result-receipt")).toBeVisible();
    const overflows = await page.locator(".result-receipt-col").evaluateAll((cols) => {
      const bad: { txt: string; overflow: number }[] = [];
      for (const col of cols) {
        const colR = col.getBoundingClientRect();
        for (const v of col.querySelectorAll(".result-receipt-value, .result-receipt-label")) {
          const vr = v.getBoundingClientRect();
          if (vr.right - colR.right > 1) {
            bad.push({ txt: (v.textContent || "").trim().slice(0, 24), overflow: Math.round(vr.right - colR.right) });
          }
        }
      }
      return bad;
    });
    expect(overflows, `receipt values overflow their column: ${JSON.stringify(overflows)}`).toEqual([]);
  });

  test("composer 'Run now' is a solid secondary button, not a borderless ghost", async ({ page }) => {
    // The ghost variant renders as plain text until hover — it did not read as a
    // button. It must be a solid secondary CTA (visible surface + border) beside
    // the primary "See the estimate".
    await boot(page);
    const runNow = page.locator("#run-now");
    await expect(runNow).toHaveClass(/button-secondary/);
    await expect(runNow).not.toHaveClass(/button-ghost/);
  });

  test("next-question: Start fresh clears, Follow up prefills, and Review & run lands on page B with editable models (no auto-estimate)", async ({ page }) => {
    await driveToResult(page, completedResp());
    const nextInput = page.locator("#result-next-input");
    await nextInput.fill("a refinement");
    await page.locator("#result-startfresh").click();
    await expect(page.locator("#result-startfresh")).toHaveAttribute("aria-pressed", "true");
    await expect(nextInput).toHaveValue("");
    // Follow up + Review & run drops the user back on the composer (page B) with
    // the question pre-filled and the four model slots visible/editable — and it
    // must NOT auto-fire an estimate, so the user can change models before
    // running (they click See the estimate / Run now themselves).
    let estimateFired = false;
    page.on("request", (r) => { if (r.url().includes("/v1/query-runs/estimate")) estimateFired = true; });
    await page.locator("#result-followup").click();
    await page.locator("#result-next-run").click();
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await expect(page.locator("#query-text")).toHaveValue(QUESTION);
    // The four model slots are present and enabled on page B.
    const slots = page.locator("[data-model-slot]");
    await expect(slots).toHaveCount(4);
    await expect(slots.first()).toBeEnabled();
    await page.waitForTimeout(300);
    expect(estimateFired, "Review & run must not auto-fire an estimate — the user picks models then runs").toBe(false);
  });

  test("SECURITY: a javascript: source URL never becomes a clickable anchor", async ({ page }) => {
    const hostile = [
      { title: "Evil", url: "javascript:alert(document.cookie)", provider: "openrouter_search" },
      { title: "Good", url: "https://example.com/ok", provider: "openrouter_search" },
    ];
    await driveToResult(page, completedResp(hostile));
    const synth = page.locator("#result-synthesis");
    await expect(synth).toBeVisible();
    // No anchor anywhere on the page points at a javascript: (or data:) URL.
    await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0);
    await expect(page.locator('a[href^="data:"]')).toHaveCount(0);
    // The hostile source still shows as a NON-link chip (span, not <a>).
    const evilChip = synth.locator(".result-source-chip", { hasText: "Evil" });
    await expect(evilChip).toHaveCount(1);
    expect(await evilChip.first().evaluate((el) => el.tagName)).toBe("SPAN");
    // The safe https source IS a real anchor.
    const goodChip = synth.locator("a.result-source-chip", { hasText: "Good" });
    await expect(goodChip).toHaveAttribute("href", "https://example.com/ok");
  });

  test("SECURITY: a crafted markdown link in model answer text cannot inject a javascript: anchor, a control-char-obfuscated scheme, or an event-handler breakout", async ({ page }) => {
    // A model's answer_text is rendered as inline markdown (formatAnswerText →
    // mdInline). It is untrusted (model/synthesis output). Craft hostile
    // markdown links and prove none of them become a script vector.
    //   Browsers strip control characters before resolving a scheme, so a
    //   URL like "java\tscript:" (interior TAB, 0x09) or "\x01javascript:"
    //   (leading C0 control) would execute if the renderer allow-listed it as
    //   a scheme-less (relative) URL. These are the cases that must fail
    //   against a naive regex allow-list and pass after the URL()-based fix
    //   that strips the SAME control set the browser does.
    const TAB = "\t";
    const CTRL = "\u0001";
    const hostileAnswer =
      `Links: [tab](java${TAB}script:alert(1)) ` +
      `[ctrl](${CTRL}javascript:alert(2)) ` +
      `[plain](javascript:alert(3)) ` +
      `[data](data:text/html,<script>alert(4)</script>) ` +
      `[quote](https://a" onmouseover="alert(5)) ` +
      `[protorel](//evil.example/x) ` +
      // Backslash-folded authority: browsers fold "\\" to "/" in the
      // authority, so "/\\evil" navigates OFF-ORIGIN (open redirect) if it
      // were allowed as a relative URL.
      `[backslash](/\\evil.example/x) ` +
      // Entity-reintroduced tab: raw "&#9;" survives HTML-escaping as
      // "&amp;#9;"; only re-escaping the href on emit stops the browser
      // decoding it back to a TAB and running "javascript:".
      `[entity](java&#9;script:alert(6)) ` +
      `[ok](https://example.com/ok).`;
    const resp = completedResp();
    (resp.result as { model_answers: { answer_text: string }[] }).model_answers[0].answer_text =
      hostileAnswer;
    await driveToResult(page, resp);

    const grid = page.locator("#model-grid");
    // (1) No anchor may resolve to a dangerous scheme once the browser's own
    // pre-navigation normalisation (strip ALL C0 controls + DEL, then leading
    // whitespace) is applied — mirror that here so an obfuscated scheme can't
    // hide behind a control char the naive /^\s*/ would miss.
    const dangerous = await grid.locator("a").evaluateAll((anchors) =>
      anchors
        .map((a) => a.getAttribute("href") || "")
        .filter((h) =>
          /^(javascript|data|vbscript):/i.test(
            h.replace(/[\u0000-\u001F\u007F]/g, "").replace(/^\s+/, ""),
          ),
        ),
    );
    expect(dangerous, `dangerous anchors rendered: ${JSON.stringify(dangerous)}`).toEqual([]);
    // Belt-and-braces: no javascript:/data: anchor anywhere on the page.
    await expect(page.locator('a[href*="javascript"]')).toHaveCount(0);
    await expect(page.locator('a[href^="data:"]')).toHaveCount(0);
    // (2) The quote-breakout attempt must not have produced a real event-handler
    // attribute — the URL stays inside the href value, it never becomes markup.
    const injected = await grid
      .locator("[onmouseover], [onclick], [onerror], [onload]")
      .count();
    expect(injected, "a markdown URL broke out into an event-handler attribute").toBe(0);
    // (3) No anchor RESOLVES off-origin to the attacker host — catches the
    // protocol-relative and backslash-folded-authority open-redirect vectors,
    // whose danger is in resolution, not a dangerous scheme. ``.href`` is the
    // browser's own resolved absolute URL.
    const offOrigin = await grid.locator("a").evaluateAll((anchors) =>
      anchors.map((a) => (a as HTMLAnchorElement).href).filter((h) => /evil\.example/i.test(h)),
    );
    expect(offOrigin, `open-redirect anchors to evil.example: ${JSON.stringify(offOrigin)}`).toEqual([]);
    // (4) The one legitimate https link still renders as a working anchor.
    const ok = grid.locator('a[href="https://example.com/ok"]');
    await expect(ok).toHaveCount(1);
    await expect(ok).toHaveText("ok");
  });

  test("transcript openings show friendly names, never a raw vendor/model slug", async ({ page }) => {
    await driveToResult(page, completedResp());
    await page.locator("#result-transcript-link").click();
    await expect(page.locator('[data-view="transcript"]')).toBeVisible();
    const names = page.locator(".transcript-opening-name");
    await expect(names).toHaveCount(4);
    for (const n of await names.allTextContents()) {
      expect(n, `opening name leaked a raw slug: ${n}`).not.toContain("/");
    }
  });

  test("synthesis card renders rows but NO source chips when the run cited nothing (never invents sources)", async ({ page }) => {
    // Completed run WITH a synthesis, but every model returned zero sources.
    const noSources = completedResp();
    (noSources.result as { model_answers: { sources: unknown[] }[] }).model_answers.forEach((a) => { a.sources = []; });
    await boot(page);
    await routeRun(page, noSources);
    await fill(page); await clickRunNow(page);
    await expect(page.locator('#result-verdict[data-consensus="true"]')).toBeVisible();
    // The synthesis card still shows its labelled rows...
    await expect(page.locator("#result-synthesis")).toBeVisible();
    await expect(page.locator('.result-synth-row[data-section="consensus"]')).toBeVisible();
    // ...it surfaces the real source_support prose as a caption...
    await expect(page.locator(".result-source-support")).toContainText("Backed by cited sources");
    // ...but fabricates NO citation chips when the models cited nothing.
    await expect(page.locator(".result-source-chip")).toHaveCount(0);
  });

  test("next-question: Estimate & run with an empty box is a no-op (no estimate fired)", async ({ page }) => {
    await driveToResult(page, completedResp());
    let estimatesAfter = 0;
    page.on("request", (r) => { if (r.url().includes("/v1/query-runs/estimate")) estimatesAfter++; });
    await page.locator("#result-startfresh").click(); // clears box + follow-up off
    await expect(page.locator("#result-next-input")).toHaveValue("");
    await page.locator("#result-next-run").click();
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await expect(page.getByRole("textbox").first()).toHaveValue("");
    await page.waitForTimeout(300);
    expect(estimatesAfter, "an empty follow-up must not fire an estimate").toBe(0);
  });

  test("landing preview badge reads Preview but keeps the illustrative accessible name", async ({ page }) => {
    await boot(page);
    // ``#show-landing`` is the visible top-bar "How it works" link; a returning
    // visitor clicks it to reopen the marketing landing (screen 01).
    await page.locator("#show-landing").click();
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await expect(page.locator(".landing-preview-badge")).toHaveText("Preview");
    await expect(page.locator(".landing-preview")).toHaveAttribute("aria-label", "Example preview");
    await expect(page.locator(".landing-preview-caption")).toContainText("not a run you started");
    // The global top bar is hidden on landing (no double header).
    await expect(page.locator(".topbar")).toBeHidden();
  });

  test("first-visit gate: landing is the front door on the first visit, workspace on return", async ({ page }) => {
    // FRESH visitor — no ``quorum.workspaceSeen`` flag. Do NOT use boot() here
    // (it seeds the flag); navigate clean so the gate takes the first-visit path.
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await expect(page.locator('[data-view="composer"]')).toBeHidden();
    // The flag is not set until the visitor actually enters the workspace.
    expect(await page.evaluate(() => localStorage.getItem("quorum.workspaceSeen"))).toBeNull();
    // boot() clears the pre-paint gate attribute once setView has run, so the
    // ``!important`` gate CSS can never trap the composer hidden after the
    // visitor navigates into it.
    expect(await page.locator("html").getAttribute("data-first-visit")).toBeNull();
    // Ctrl/Cmd+Enter on the landing is a no-op: no empty-run, no error banner.
    await page.keyboard.press("Control+Enter");
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await expect(page.locator("#error-region")).toBeHidden();

    // A landing CTA hands off to the workspace and records the visit. A question
    // is now required first (the empty-submit guard has its own test below).
    await page.locator("#landing-query").fill("Should we adopt passkeys by 2027?");
    await page.locator("#landing-run").click();
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    expect(await page.evaluate(() => localStorage.getItem("quorum.workspaceSeen"))).toBe("1");

    // RETURN visit — the persisted flag boots straight into the workspace, and
    // the landing stays reachable via the visible "How it works" link.
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await expect(page.locator('[data-view="landing"]')).toBeHidden();
    await page.locator("#show-landing").click();
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
  });

  test("landing empty-submit guard: Estimate/Run with no question shows the error and does not navigate", async ({ page }) => {
    // Fresh visitor → landing is the front door.
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    const err = page.locator("#landing-query-error");
    await expect(err).toBeHidden();

    // Run with an empty field: all cues fire together and it does NOT navigate.
    await page.locator("#landing-run").click();
    await expect(err).toBeVisible();
    await expect(err).toHaveText(/enter a question/i);
    await expect(page.locator(".landing-runbar")).toHaveAttribute("data-invalid", "true");
    await expect(page.locator("#landing-query")).toHaveAttribute("aria-invalid", "true");
    await expect(page.locator("#landing-query-error")).toHaveAttribute("role", "alert");
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await expect(page.locator('[data-view="composer"]')).toBeHidden();

    // Estimate behaves identically.
    await page.locator("#landing-estimate").click();
    await expect(err).toBeVisible();
    await expect(page.locator('[data-view="landing"]')).toBeVisible();

    // Typing clears every error cue immediately.
    await page.locator("#landing-query").fill("Should we adopt passkeys?");
    await expect(err).toBeHidden();
    await expect(page.locator(".landing-runbar")).not.toHaveAttribute("data-invalid", "true");
    await expect(page.locator("#landing-query")).toHaveAttribute("aria-invalid", "false");
  });

  test("landing Estimate shows the transition message ON page A, then hands off to the composer (no note on page B)", async ({ page }) => {
    const Q = "Should we migrate our monolith to microservices this year?";
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await page.locator("#landing-query").fill(Q);
    await page.locator("#landing-estimate").click();
    // The tailored message appears on the LANDING (page A) so the user learns WHY
    // they are being moved — BEFORE the view changes.
    const note = page.locator("#landing-handoff-note");
    await expect(note).toBeVisible();
    await expect(note).toContainText(/itemized cost before anything runs/i);
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    // Then it hands off to the composer with the question carried over.
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await expect(page.locator("#query-text")).toHaveValue(Q);
    // There is NO hand-off note on page B — the message lives on page A now, so it
    // can never overlap the composer's privacy notice.
    await expect(page.locator("#composer-handoff-note")).toHaveCount(0);
  });

  test("landing Run shows the run-tailored message ON page A, then hands off to the composer", async ({ page }) => {
    const Q = "Is passwordless auth worth the migration cost?";
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await page.locator("#landing-query").fill(Q);
    await page.locator("#landing-run").click();
    const note = page.locator("#landing-handoff-note");
    await expect(note).toBeVisible();
    // Run's message is honest about the cost-approval step (it does not run from A).
    await expect(note).toContainText(/price it and run once you approve/i);
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await expect(page.locator("#query-text")).toHaveValue(Q);
    await expect(page.locator("#composer-handoff-note")).toHaveCount(0);
  });

  test("HARDENING: a landing example-chip clicked during the Estimate dwell cancels the pending hand-off — no stray scroll-to-top later", async ({ page }) => {
    // handoffFromLanding schedules a ~2.8s dwell then goToComposer(). The landing
    // example chips also call goToComposer() and are NOT disabled during the
    // dwell, so a chip click mid-dwell navigates immediately — and the stray
    // dwell timer used to fire a SECOND goToComposer later, yanking the
    // viewport back to the top after the user had scrolled into the composer.
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await page.locator("#landing-query").fill("Question A");
    await page.locator("#landing-estimate").click(); // starts the dwell
    // Immediately click a landing example chip → lands on the composer now.
    await page.locator(".landing-chips [data-landing-chip]").first().click();
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    // The visitor scrolls down to review their models.
    await page.evaluate(() => window.scrollTo(0, 400));
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(50);
    // Wait well past the (now ~2.8s) dwell window; the cancelled hand-off must
    // NOT fire and scroll the viewport back to the top.
    await page.waitForTimeout(3200);
    expect(
      await page.evaluate(() => window.scrollY),
      "the stray landing hand-off scrolled the composer back to the top",
    ).toBeGreaterThan(50);
  });

  test("landing empty-submit error is cleared when the visitor returns to the landing", async ({ page }) => {
    // Regression: the error state used to persist across a How-it-works round-trip.
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await page.locator("#landing-run").click(); // empty → error
    await expect(page.locator("#landing-query-error")).toBeVisible();
    // Leave to the workspace, then come back via the "How it works" link.
    await page.locator("#landing-open-workspace").click();
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await page.locator("#show-landing").click();
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    // The stale error must be gone.
    await expect(page.locator("#landing-query-error")).toBeHidden();
    await expect(page.locator(".landing-runbar")).not.toHaveAttribute("data-invalid", "true");
    await expect(page.locator("#landing-query")).toHaveAttribute("aria-invalid", "false");
  });

  // ---- PR #23 regression-review follow-ups (full-sweep coverage) -----------
  //
  // Each test below closes a behaviour the review found shipping WITHOUT a test
  // that fails on revert. They are written to exercise the actual wiring, not
  // just static markup, so reverting the corresponding source line turns them red.

  test("Run ID info icons are actually wired: clicking the header + receipt info icon opens the tooltip", async ({ page }) => {
    // The info icons are created dynamically by renderResultMeta/the receipt and
    // wired into the shared tooltip ONLY by the initInfoIcons() calls after each.
    // Asserting the markup exists does NOT prove the click opens the tooltip —
    // deleting those calls leaves the markup and the attribute assertions green
    // while the tooltips silently stop working. Click them to prove the wiring.
    await driveToResult(page, completedResp());
    const tooltip = page.locator("#info-tooltip");

    // Header Run ID info icon.
    const headerInfo = page.locator(".result-meta-runid .info-icon-inline");
    await expect(headerInfo).toBeVisible();
    await headerInfo.dispatchEvent("mouseenter");
    await expect(tooltip).not.toBeHidden();
    await expect(tooltip).toContainText(/audit handle for this run/i);
    await headerInfo.dispatchEvent("mouseleave");

    // Receipt Run ID info icon (created when the details disclosure opens).
    await page.locator("#result-details-toggle").click();
    await expect(page.locator("#result-receipt")).toBeVisible();
    const receiptInfo = page
      .locator("#result-receipt .result-receipt-row")
      .filter({ hasText: "Run ID" })
      .locator(".info-icon");
    await expect(receiptInfo).toBeVisible();
    await receiptInfo.dispatchEvent("mouseenter");
    await expect(tooltip).not.toBeHidden();
  });

  test("header Run ID copy button announces 'Copied' to screen readers, then restores its label", async ({ page }) => {
    // The header copy button confirmed a copy only via title + a colour flip, with
    // no accessible-name change — an SR user got no confirmation (WCAG 4.1.3). It
    // now flips aria-label to 'Copied' on success (matching the shared helper the
    // aside/live-card buttons use), and restores the idle label after.
    await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
    await driveToResult(page, completedResp());
    const copy = page.locator(".result-meta-runid-copy");
    await expect(copy).toHaveAttribute("aria-label", /^Copy run ID /);
    await copy.click();
    // The accessible name becomes "Copied" (announced), not just the title.
    await expect(copy).toHaveAttribute("aria-label", "Copied");
    await expect(copy).toHaveAttribute("data-copied", "true");
    // …and is restored to the idle copy label afterwards.
    await expect(copy).toHaveAttribute("aria-label", /^Copy run ID /);
  });

  test("header Run ID copy FAILURE is also announced to screen readers (not silent)", async ({ page }) => {
    // If the clipboard write rejects (permission denied), an SR user must still
    // learn it failed — the old catch set only the unspoken title attribute.
    await page.addInitScript(() => {
      // Force navigator.clipboard.writeText to reject for this page.
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: { writeText: () => Promise.reject(new Error("denied")) },
      });
    });
    await driveToResult(page, completedResp());
    const copy = page.locator(".result-meta-runid-copy");
    await copy.click();
    await expect(copy).toHaveAttribute("aria-label", /copy failed/i);
    // …then restored to the idle copy label.
    await expect(copy).toHaveAttribute("aria-label", /^Copy run ID /);
  });

  test("single-create latch: two independent confirm entry points POST only ONE create", async ({ page }) => {
    // proceedWithRun latches on state.creatingRun BEFORE its first await, so two
    // concurrent entry points (the cost-gate confirm and the legacy #proceed-run,
    // which setButtonLoading does NOT both disable) cannot each POST a create. The
    // create POST is held open to freeze the window; a second entry is dispatched
    // before release. Reverting the latch makes createCount === 2.
    await boot(page);
    let createCount = 0;
    let releaseCreate!: () => void;
    const createGate = new Promise<void>((res) => { releaseCreate = res; });
    await page.route("**/v1/query-runs/estimate", (r) =>
      r.fulfill(fulfil(estimateResp("0.190", "require_confirmation"))));
    await page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] })));
    await page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null })));
    await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => r.fulfill(fulfil(completedResp())));
    await page.route(/\/v1\/query-runs$/, async (r) => {
      if (r.request().method() === "POST") {
        createCount++;
        await createGate; // hold the FIRST create open to widen the re-entrancy window
        return r.fulfill(fulfil(createResp()));
      }
      return r.continue();
    });

    await fill(page);
    await clickEstimate(page);
    await expect(page.locator("#gate-confirm")).toBeVisible();
    // Entry A: the cost-gate confirm (kicks off proceedWithRun; its create is held).
    await page.locator("#gate-confirm").click();
    // Entry B: the legacy #proceed-run button fires proceedWithRun again while A's
    // create is still in flight. setButtonLoading(gateConfirm) does not disable it,
    // so only the state.creatingRun latch prevents a second create POST.
    await page.locator("#proceed-run").dispatchEvent("click");
    // Give any (unwanted) second create a chance to be POSTed before releasing.
    await page.waitForTimeout(200);
    releaseCreate();
    await expect(page.locator('#result-verdict[data-consensus="true"]')).toBeVisible();
    expect(createCount, "exactly one create must be POSTed even with a concurrent entry").toBe(1);
  });

  test("high-stakes gate disables BOTH composer CTAs (Run now included) until acknowledged", async ({ page }) => {
    // applyHighStakesGate disables #run-now (not just #estimate-run) when a
    // high-stakes topic is unacknowledged — a safety-adjacent gate on the direct-run
    // path. No test exercised the high-stakes branch (every mock returned no
    // warnings). Drive it: a high_stakes warning must block Run now until the ack.
    await boot(page);
    await page.route("**/v1/query-runs/warnings", (r) =>
      r.fulfill(fulfil({ warnings: [{ warning_type: "high_stakes", version: "1" }] })));
    await fill(page);
    // The debounced probe raises the gate.
    await expect(page.locator("#high-stakes-gate")).toBeVisible();
    const runNow = page.locator("#run-now");
    const estimate = page.locator("#estimate-run");
    await expect(runNow).toBeDisabled();
    await expect(runNow).toHaveAttribute("data-gate-blocked", "true");
    await expect(estimate).toBeDisabled();
    await expect(estimate).toHaveAttribute("data-gate-blocked", "true");
    // Acknowledging re-enables both.
    await page.locator("#high-stakes-ack").check();
    await expect(runNow).toBeEnabled();
    await expect(runNow).toHaveAttribute("data-gate-blocked", "false");
    await expect(estimate).toBeEnabled();
  });

  test("live-run card labels the run id 'Run ID …' (not a bare 'run …') and stashes the raw id to copy", async ({ page }) => {
    // renderLiveRun unified the live card's correlation readout to 'Run ID {id}';
    // nothing asserted #live-corr, so reverting the label re-introduced the exact
    // inconsistency this PR set out to fix, on the live surface.
    await boot(page);
    // Hold the run on a non-terminal poll so the live-run view stays put.
    const running = { ...(createResp() as Record<string, unknown>), status: "running" };
    await routeRun(page, running);
    await fill(page); await clickRunNow(page);
    await expect(page.locator('[data-view="live-run"]')).toBeVisible();
    const corr = page.locator("#live-corr");
    await expect(corr).toContainText(/^Run ID corr-run-0001$/);
    await expect(corr).toHaveAttribute("data-correlation-id", "corr-run-0001");
  });

  test("receipt collapses to a single column on a narrow (phone) viewport with no value overflow", async ({ page }) => {
    // The existing overflow test runs at width 900 (the receipt stays 4-col there),
    // so the phone single-column layout was unguarded. On a phone the nowrap money
    // columns re-cram/overflow unless the grid stacks to one column. (Note: the PR
    // added a redundant @media(max-width:720px) stacking block that was dead — the
    // pre-existing @media(max-width:760px) block already stacks it and wins the
    // cascade — so that redundant block was removed; this test guards the real
    // 760px phone-stacking behaviour, which is what actually protects the layout.)
    await page.setViewportSize({ width: 480, height: 900 });
    await driveToResult(page, completedResp());
    await page.locator("#result-details-toggle").click();
    await expect(page.locator("#result-receipt")).toBeVisible();
    // The grid resolves to a single column at this width.
    const columns = await page.locator("#result-receipt .result-receipt-grid").first().evaluate(
      (grid) => getComputedStyle(grid).gridTemplateColumns.trim().split(/\s+/).length,
    );
    expect(columns, "receipt grid must stack to one column ≤720px").toBe(1);
    // And no value/label overflows its column horizontally.
    const overflows = await page.locator(".result-receipt-col").evaluateAll((cols) =>
      cols.flatMap((col) => {
        const cb = col.getBoundingClientRect();
        return [...col.querySelectorAll(".result-receipt-value, .result-receipt-label")]
          .filter((v) => v.getBoundingClientRect().right > cb.right + 1)
          .map((v) => (v as HTMLElement).textContent || "");
      }),
    );
    expect(overflows, `receipt values overflow at 480px: ${JSON.stringify(overflows)}`).toEqual([]);
  });

  test("landing Ctrl/Cmd+Enter hands off to the composer with the typed question (not a dead key)", async ({ page }) => {
    // The landing added a real textarea, but the global Ctrl/Cmd+Enter handler
    // no-ops on the landing view, so the natural submit gesture did nothing. It
    // now routes through the same estimate-first hand-off as the button.
    const Q = "Is a four-day work week worth trialling for our team?";
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await page.locator("#landing-query").fill(Q);
    await page.locator("#landing-query").press("ControlOrMeta+Enter");
    await expect(page.locator("#landing-handoff-note")).toBeVisible();
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await expect(page.locator("#query-text")).toHaveValue(Q);
  });

  test("a question refined DURING the hand-off dwell is carried into the composer (not the click-time snapshot)", async ({ page }) => {
    // The landing field stays focused through the (now ~2.8s) dwell, so the visitor
    // can keep typing. Their latest text must reach the composer — an edit made
    // during the dwell must never be silently discarded.
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await page.locator("#landing-query").fill("First draft");
    await page.locator("#landing-estimate").click();
    await expect(page.locator("#landing-handoff-note")).toBeVisible();
    // Refine the question while the dwell is still running.
    await page.locator("#landing-query").fill("First draft, refined during the dwell");
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await expect(page.locator("#query-text")).toHaveValue("First draft, refined during the dwell");
  });

  test("clicking 'How it works' during the hand-off dwell cancels the pending hand-off (stays on the landing)", async ({ page }) => {
    // A visitor who clicks Estimate then 'How it works' wants to read the example,
    // not be yanked to the composer a beat later. The dwell must be cancelled.
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await page.locator("#landing-query").fill("Question during dwell");
    await page.locator("#landing-estimate").click(); // starts the ~2.8s dwell
    await expect(page.locator("#landing-handoff-note")).toBeVisible();
    await page.locator("#landing-howitworks").click(); // cancels the pending hand-off
    // The note is hidden and the CTAs are re-enabled immediately.
    await expect(page.locator("#landing-handoff-note")).toBeHidden();
    await expect(page.locator("#landing-estimate")).toBeEnabled();
    // Wait well past the original dwell — the cancelled hand-off must NOT navigate.
    await page.waitForTimeout(3200);
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await expect(page.locator('[data-view="composer"]')).toBeHidden();
  });

  test("landing hand-off keeps keyboard focus on a visible element (not dropped to <body>) during the dwell", async ({ page }) => {
    // Disabling the CTA the user just activated blurred it, orphaning focus to
    // <body> for the whole dwell. Focus is re-homed onto the question field.
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await page.locator("#landing-query").fill("Keep my focus somewhere sensible");
    await page.locator("#landing-estimate").click();
    // During the dwell, focus must be on the still-visible landing question field,
    // never on <body>.
    const active = await page.evaluate(() => document.activeElement?.id || document.activeElement?.tagName);
    expect(active, "focus must not be orphaned to <body> during the hand-off dwell").toBe("landing-query");
  });

  test("a bare 'Open the workspace' (empty composer) does NOT flash the question-handoff highlight", async ({ page }) => {
    // The accent flash cues 'your question landed here'. 'Open the workspace' carries
    // no question, so flashing an empty field is a spurious cue over nothing.
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    // Record whether the flash class is EVER applied — a plain not.toHaveClass
    // auto-retries and would pass once the 1.4s flash times out, missing it. A
    // MutationObserver catches an add-then-remove within the window.
    await page.evaluate(() => {
      (window as unknown as { __flashed: boolean }).__flashed = false;
      const el = document.getElementById("query-text");
      if (!el) return;
      new MutationObserver(() => {
        if (el.classList.contains("question-handoff-focus")) {
          (window as unknown as { __flashed: boolean }).__flashed = true;
        }
      }).observe(el, { attributes: true, attributeFilter: ["class"] });
    });
    await page.locator("#landing-open-workspace").click();
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await expect(page.locator("#query-text")).toHaveValue("");
    // The composer is empty, so the highlight flash must never have been applied.
    expect(
      await page.evaluate(() => (window as unknown as { __flashed: boolean }).__flashed),
      "a bare skip-to-workspace must not flash the empty composer",
    ).toBe(false);
  });

  // ---- Design-comp parity closeout: the 4 remaining visual-parity gaps -----

  test("item 1 — main content sits in a centered, constrained column (not full-width)", async ({ page }) => {
    await boot(page);
    // The comp centers content in a symmetric column narrower than the shell.
    // Audited widths: composer 800, result 960. The top bar stays shell-wide.
    const geom = async (view: string) => {
      const layout = page.locator(`[data-active-view="${view}"] .layout`).first();
      const shell = page.locator("#main-content");
      const l = await layout.boundingBox();
      const s = await shell.boundingBox();
      if (!l || !s) throw new Error("missing box");
      return { width: l.width, left: l.x - s.x, right: s.x + s.width - (l.x + l.width), shell: s.width };
    };
    const composer = await geom("composer");
    // Constrained well below the shell width, and symmetrically centered.
    expect(composer.width).toBeLessThanOrEqual(840);
    expect(composer.width).toBeLessThan(composer.shell - 200);
    expect(Math.abs(composer.left - composer.right)).toBeLessThanOrEqual(4);
    expect(composer.left).toBeGreaterThan(120);
    // The top bar itself is NOT constrained to the content column — it keeps the
    // full shell width (comp: wide bar over a centered column).
    const topbar = await page.locator(".topbar").boundingBox();
    expect(topbar!.width).toBeGreaterThan(composer.width + 150);
    // Result view is centered too (comp: 960), and wider than the composer.
    await driveToResult(page, completedResp());
    const result = await geom("result");
    expect(Math.abs(result.left - result.right)).toBeLessThanOrEqual(4);
    expect(result.width).toBeGreaterThan(composer.width);
    expect(result.width).toBeLessThanOrEqual(1000);
  });

  test("item 2 — top bar shows a session pill + theme toggle + a visible 'How it works' link", async ({ page }) => {
    await boot(page);
    const pill = page.locator("#connection-pill");
    await expect(pill).toBeVisible();
    await expect(pill).toHaveClass(/status-pill-session/);
    // Honest wording: "Session active · <capability>" — provider configured when
    // live, local simulation when degraded. Either way it starts "Session active".
    await expect(page.locator("#connection-pill-text")).toHaveText(/^Session active · (provider configured|local simulation)$/);
    // The theme toggle is preserved (a real feature the comp doesn't depict).
    await expect(page.locator("#theme-toggle")).toBeVisible();
    // The "How it works" control is now a real, visible, keyboard-reachable link
    // (the return path to the marketing landing) — no longer sr-only. Assert it
    // renders at a genuine tap-target size and is exposed to the tab order.
    const how = page.locator("#show-landing");
    await expect(how).toHaveCount(1);
    await expect(how).toBeVisible();
    await expect(how).toHaveText("How it works");
    await expect(how).not.toHaveClass(/sr-only/);
    await expect(how).not.toHaveAttribute("tabindex", "-1");
    const box = await how.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThan(40);
    expect(box!.height).toBeGreaterThanOrEqual(40);
  });

  test("item 3 — each slot shows a real per-model estimate that MATCHES the server estimate (never a fake number)", async ({ page }) => {
    await boot(page);
    // A longer question so the figures are clearly non-zero and differentiated.
    const longQ =
      "Should our 200-person company adopt passkeys and phase out passwords by the end of 2027? " +
      "What is the safest migration sequence, what are the top three rollout risks, and how should " +
      "we stage enrollment across engineering, sales, and support so nobody is locked out mid-migration?";
    await page.getByRole("textbox").first().fill(longQ);
    const cells = page.locator("#model-inputs .model-slot-estimate");
    await expect(cells).toHaveCount(4);
    // Every slot shows a real ``~$0.NNN`` figure — not the "—" placeholder.
    for (const text of await cells.allTextContents()) {
      expect(text.trim(), `slot estimate was not a real figure: ${text}`).toMatch(/^~\$\d+\.\d{3}$/);
    }
    // HONESTY GUARD: the client figures must equal what the REAL server
    // ``/v1/query-runs/estimate`` returns for the same query + models (the
    // by_model rows, formatted the same way). This is an UNMOCKED cross-check —
    // if the server formula ever drifts from the client mirror, this fails.
    const cross = await page.evaluate(async (q) => {
      const ids = [...document.querySelectorAll("[data-model-slot]")].map(
        (s) => (s as HTMLSelectElement).value,
      );
      const client = [...document.querySelectorAll("#model-inputs .model-slot-estimate")].map(
        (e) => (e as HTMLElement).textContent!.trim(),
      );
      const sess = await (await fetch("/v1/session", { credentials: "same-origin" })).json();
      const resp = await fetch("/v1/query-runs/estimate", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": sess.csrf_token },
        body: JSON.stringify({ query_text: q, model_slots: ids }),
      });
      const j = await resp.json();
      const server = (j.cost_estimate.breakdown.by_model || [])
        .filter((r: { kind: string }) => r.kind !== "synthesis")
        .map((r: { usd: string }) => Number(r.usd));
      return { client, server };
    }, longQ);
    // The client mirrors the RAW by_model arithmetic; the server additionally
    // runs a largest-remainder reconciliation that can nudge any single line by
    // at most one display quantum ($0.0001). So the honest guard is agreement
    // within a cent-fraction, not byte-identical strings: each client figure
    // must be within $0.001 of the server's by_model row for the same slot.
    const clientUsd = cross.client.map((t) => Number(t.replace(/[^0-9.]/g, "")));
    expect(clientUsd).toHaveLength(cross.server.length);
    clientUsd.forEach((c, i) => {
      expect(
        Math.abs(c - cross.server[i]),
        `slot ${i}: client ${c} vs server ${cross.server[i]} exceeds tolerance`,
      ).toBeLessThanOrEqual(0.001);
    });
    // Clearing the box drops the figures back to the neutral placeholder.
    await page.getByRole("textbox").first().fill("");
    for (const text of await cells.allTextContents()) {
      expect(text.trim()).toBe("—");
    }
  });

  test("item 3 (honesty) — a paid model never renders as $0.000 or a free-looking figure", async ({ page }) => {
    await boot(page);
    // issue #16: the per-model estimate now prices the injected web-search
    // context (~2,000 prompt tokens/slot), so even a tiny question is ~$0.001
    // per slot — no longer sub-cent. The honesty guarantee is unchanged: a
    // paid model is NEVER shown as free ("~$0.000") and always renders a real
    // positive figure (the "<$0.001" marker survives for the rare truly
    // sub-cent slot, but is no longer required for a tiny query).
    await page.getByRole("textbox").first().fill("hi there?");
    const cells = page.locator("#model-inputs .model-slot-estimate");
    await expect(cells).toHaveCount(4);
    for (const text of await cells.allTextContents()) {
      const t = text.trim();
      expect(t, `slot rendered a free-looking figure: ${t}`).not.toBe("~$0.000");
      expect(t, `unexpected slot estimate: ${t}`).toMatch(/^(<\$0\.001|~\$\d+\.\d{3})$/);
    }
  });

  test("item 3 (recompute) — swapping a model slot recomputes that slot's estimate", async ({ page }) => {
    await boot(page);
    await page.getByRole("textbox").first().fill(
      "What are the tradeoffs between usage-based and seat pricing for a 30k-seat SaaS with heavy API usage across three products, and how should we stage a migration?",
    );
    const cells = page.locator("#model-inputs .model-slot-estimate");
    // Swap slot 1 to slot 4's model (guaranteed present in the catalog — it is
    // already selected — and differently priced; cross-slot duplicates are
    // allowed). Slot 1's estimate must recompute to match slot 4's, proving the
    // figure tracks the selected model rather than the slot position.
    const slot4Model = await page.locator("[data-model-slot]").nth(3).inputValue();
    const slot4Estimate = (await cells.nth(3).textContent())!.trim();
    await page.locator("#model-1").selectOption(slot4Model);
    await expect(cells.first()).toHaveText(slot4Estimate);
  });

  test("item 4 — the four example chips lay out 2×2 (two rows of two)", async ({ page }) => {
    await boot(page);
    const chips = page.locator(".composer-examples-row .landing-chip");
    await expect(chips).toHaveCount(4);
    const boxes = await chips.evaluateAll((els) =>
      els.map((e) => {
        const r = e.getBoundingClientRect();
        return { x: r.left, y: r.top };
      }),
    );
    // Cluster by coordinate with a tolerance so a sub-pixel layout shift does
    // not flip the count — two chips are "in the same row/column" when their
    // top/left are within a few px of each other.
    const cluster = (vals: number[], tol = 6) => {
      const sorted = [...vals].sort((a, b) => a - b);
      const groups: number[] = [];
      for (const v of sorted) {
        if (!groups.length || v - groups[groups.length - 1] > tol) groups.push(v);
      }
      return groups;
    };
    const rowBands = cluster(boxes.map((b) => b.y));
    const colBands = cluster(boxes.map((b) => b.x));
    expect(rowBands.length, "chips should occupy exactly two rows").toBe(2);
    expect(colBands.length, "chips should occupy exactly two columns").toBe(2);
    // Each row holds exactly two chips.
    for (const band of rowBands) {
      const inRow = boxes.filter((b) => Math.abs(b.y - band) <= 6).length;
      expect(inRow, "each row should hold two chips").toBe(2);
    }
  });

  // ---- Reported issues follow-up: hand-off focus, positions colour, retention ----

  test("item 3.2 — 'How positions moved' avatars carry the SAME per-vendor tint as the composer slots, not a flat grey", async ({ page }) => {
    // The composer's four model slots each get a per-vendor tint (openai teal /
    // anthropic amber / google blue / deepseek purple). The "How positions moved"
    // avatars used to render a single flat grey (no data-vendor), losing that
    // colour identity — so a model that is teal in the composer went grey here.
    await driveToResult(page, completedResp());
    const pos = page.locator("#result-positions");
    await expect(pos).toBeVisible();
    const avatars = pos.locator(".result-pos-avatar");
    await expect(avatars).toHaveCount(4);
    // Each avatar is tagged with its model's vendor, matching the SLOTS order.
    const vendors = await avatars.evaluateAll((els) =>
      els.map((e) => (e as HTMLElement).dataset.vendor));
    expect(vendors).toEqual(["openai", "anthropic", "google", "deepseek"]);
    // ...and they render four DISTINCT tints (the vendor colours), not one grey.
    const bgs = await avatars.evaluateAll((els) =>
      els.map((e) => getComputedStyle(e as HTMLElement).backgroundColor));
    expect(new Set(bgs).size, `expected 4 distinct vendor tints, got ${JSON.stringify(bgs)}`).toBe(4);
    // Cross-check: the positions tint for each vendor equals the composer slot
    // tint for the same vendor (the colour is retained across the two surfaces).
    const slotBgByVendor: Record<string, string> = await page
      .locator("#model-inputs .model-slot-avatar")
      .evaluateAll((els) =>
        Object.fromEntries(
          els.map((e) => [
            (e as HTMLElement).dataset.vendor,
            getComputedStyle(e as HTMLElement).backgroundColor,
          ]),
        ));
    const posPairs: [string, string][] = await avatars.evaluateAll((els) =>
      els.map((e) => [
        (e as HTMLElement).dataset.vendor || "",
        getComputedStyle(e as HTMLElement).backgroundColor,
      ]));
    for (const [vendor, bg] of posPairs) {
      expect(slotBgByVendor[vendor], `positions tint for ${vendor} must match the composer slot tint`).toBe(bg);
    }
  });

  test("item 2.4 — clicking a composer example chip fills the question AND scrolls it into view (focus not left off-screen)", async ({ page }) => {
    await boot(page);
    // The example chips sit near the page bottom; scroll to one as a user would,
    // so the question textarea is above the fold before the click.
    const chip = page.locator(".composer-examples .landing-chip").first();
    await chip.scrollIntoViewIfNeeded();
    await expect
      .poll(() => page.evaluate(() => window.scrollY))
      .toBeGreaterThan(2); // we are genuinely scrolled away from the top
    await chip.click();
    const ta = page.locator("#query-text");
    await expect(ta).toBeFocused();
    await expect(ta).toHaveValue(/Usage-based vs seat pricing\?/);
    // A brief highlight flash makes the (programmatically) focused field visible.
    await expect(ta).toHaveClass(/question-handoff-focus/);
    // The fix brings the composer back to the top so the filled+focused field is
    // actually visible (a bare focus({preventScroll}) left it off-screen).
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeLessThanOrEqual(2);
    const inView = await ta.evaluate((el) => {
      const r = el.getBoundingClientRect();
      return r.top >= 0 && r.bottom <= window.innerHeight;
    });
    expect(inView, "composer question must be visible after a chip fill").toBe(true);
  });

  test("item 2.2 — a follow-up 'Review & run' lands on the composer scrolled to the top with the question focused (not mid-page)", async ({ page }) => {
    await driveToResult(page, completedResp());
    // Scroll to the follow-up block near the bottom of the (long) result view.
    const nextRun = page.locator("#result-next-run");
    await nextRun.scrollIntoViewIfNeeded();
    await page.locator("#result-followup").click();
    await page.locator("#result-next-input").fill("What about hardware security keys?");
    await nextRun.click();
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    const ta = page.locator("#query-text");
    await expect(ta).toBeFocused();
    await expect(ta).toHaveValue("What about hardware security keys?");
    // The composer is scrolled to the top so its heading + the pre-filled question
    // are framed together — the pre-fix path left the viewport where the user had
    // scrolled on the result, with the composer heading off the top of the screen.
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeLessThanOrEqual(2);
    const headingTop = await page
      .locator("#composer-heading")
      .evaluate((el) => el.getBoundingClientRect().top);
    expect(headingTop, "the composer heading must be on-screen after a follow-up hand-off").toBeGreaterThanOrEqual(0);
  });

  test("item 3.1 — the composer keeps the typed question across a 'How it works' round-trip (typed work is never discarded)", async ({ page }) => {
    await boot(page);
    const ta = page.locator("#query-text");
    const q = "Should we migrate our public API from REST to GraphQL this year?";
    await ta.fill(q);
    // Leave to the marketing landing via the top-bar link, then return.
    await page.locator("#show-landing").click();
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await page.locator("#landing-open-workspace").click();
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await expect(ta).toHaveValue(q);
  });
});
