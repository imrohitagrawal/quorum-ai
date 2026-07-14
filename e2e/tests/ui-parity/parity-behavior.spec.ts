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

  test("composer 'Run now' is a solid secondary button, not a borderless ghost", async ({ page }) => {
    // The ghost variant renders as plain text until hover — it did not read as a
    // button. It must be a solid secondary CTA (visible surface + border) beside
    // the primary "See the estimate".
    await boot(page);
    const runNow = page.locator("#run-now");
    await expect(runNow).toHaveClass(/button-secondary/);
    await expect(runNow).not.toHaveClass(/button-ghost/);
  });

  test("next-question: Start fresh clears, Follow up prefills, Estimate & run re-estimates", async ({ page }) => {
    await driveToResult(page, completedResp());
    const nextInput = page.locator("#result-next-input");
    await nextInput.fill("a refinement");
    await page.locator("#result-startfresh").click();
    await expect(page.locator("#result-startfresh")).toHaveAttribute("aria-pressed", "true");
    await expect(nextInput).toHaveValue("");
    // Follow up + Estimate & run routes the answered question back through the
    // composer's own gated estimate button. Assert only the DURABLE outcomes,
    // never the transient view: on the mocked "allow" band the re-estimate
    // auto-proceeds (proceedWithRun) and flips the view composer→result almost
    // immediately, so any assertion on composer visibility or on
    // ``getByRole("textbox").first()`` (which then resolves to the empty
    // ``#result-next-input``) races and flakes under load. The two things that
    // deterministically prove the behaviour are: a fresh estimate fired, and the
    // composer's own ``#query-text`` carries the prefilled question — its value
    // is set synchronously on the follow-up and is never cleared by the run, so
    // it holds regardless of how the view has since transitioned.
    await page.locator("#result-followup").click();
    const estimateReq = page.waitForRequest("**/v1/query-runs/estimate");
    await page.locator("#result-next-run").click();
    await estimateReq;
    await expect(page.locator("#query-text")).toHaveValue(QUESTION);
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

    // A landing CTA hands off to the workspace and records the visit.
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
});
