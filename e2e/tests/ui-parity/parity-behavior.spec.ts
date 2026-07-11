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
  { model_id: "synthesis", display_name: "Synthesis writer", usd: "0.024", kind: "synthesis" },
];
const BY_STAGE = [
  { stage: "initial_answers", usd: "0.120" }, { stage: "debate", usd: "0.046" }, { stage: "synthesis", usd: "0.024" },
];
const breakdown = (total = "0.190") => ({ by_model: BY_MODEL, by_stage: BY_STAGE, total });
const costEstimate = (total: string, action: string) => ({
  estimated_cost_usd: total, currency: "USD", threshold_action: action, confirmation_token: "tok-abc123",
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
  await fill(page); await clickEstimate(page);
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

  test("next-question: Start fresh clears, Follow up prefills, Estimate & run re-estimates", async ({ page }) => {
    await driveToResult(page, completedResp());
    const nextInput = page.locator("#result-next-input");
    await nextInput.fill("a refinement");
    await page.locator("#result-startfresh").click();
    await expect(page.locator("#result-startfresh")).toHaveAttribute("aria-pressed", "true");
    await expect(nextInput).toHaveValue("");
    // Follow up + Estimate & run returns to composer with the answered question
    // prefilled and fires a fresh estimate request.
    await page.locator("#result-followup").click();
    const estimateReq = page.waitForRequest("**/v1/query-runs/estimate");
    await page.locator("#result-next-run").click();
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await expect(page.getByRole("textbox").first()).toHaveValue(QUESTION);
    await estimateReq;
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
    await fill(page); await clickEstimate(page);
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
    await page.locator("#show-landing").click();
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await expect(page.locator(".landing-preview-badge")).toHaveText("Preview");
    await expect(page.locator(".landing-preview")).toHaveAttribute("aria-label", "Example preview");
    await expect(page.locator(".landing-preview-caption")).toContainText("not a run you started");
    // The global top bar is hidden on landing (no double header).
    await expect(page.locator(".topbar")).toBeHidden();
  });
});
