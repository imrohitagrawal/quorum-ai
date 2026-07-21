import { test, expect, Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { withEvaluation, EVAL_MISSING_HIGH_STAKES } from "../../fixtures/golden-run";

/**
 * AC-035 accessibility gate — a REAL axe-core drive over every SPA view in
 * BOTH themes. This is the committed, reproducible counterpart to the Slice V
 * manual axe drive: it renders each view with mocked backend responses (so the
 * data-driven views actually populate), freezes timers/transitions to avoid
 * mid-animation contrast false-positives, and asserts NO critical/serious
 * WCAG 2.0/2.1 A+AA violation on the core workflow.
 *
 * Regression guard: this would have caught the dark-mode theming bug (inline
 * <style> hardcoding light body/panel colours) and the workflow-step
 * aria-controls-to-nowhere bug that the Slice V drive found.
 *
 * Chromium only (reference engine + the browser provisioned in this repo).
 */

const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

// ---- mock fixtures (openapi QueryRun* shapes; canonical cost numbers) -------
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
  { stage: "initial_answers", usd: "0.120" },
  { stage: "debate", usd: "0.046" },
  { stage: "synthesis", usd: "0.024" },
];
const breakdown = (total = "0.190") => ({ by_model: BY_MODEL, by_stage: BY_STAGE, total });
const costEstimate = (total: string, action: string) => ({
  estimated_cost_usd: total, currency: "USD", threshold_action: action,
  confirmation_token: "tok-abc123",
  reasons: action === "block" ? ["Estimated spend exceeds the $0.25 hard cap."] : [],
  breakdown: breakdown(total),
});
const estimateResp = (total: string, action: string) => ({
  correlation_id: "corr-est-0001", cost_estimate: costEstimate(total, action), model_slots: SLOTS,
  reasons: action === "block" ? ["Estimated spend exceeds the $0.25 hard cap."] : [],
});
const answer = (i: number, status = "completed") => ({
  slot_number: i + 1, model_id: SLOTS[i].model_id,
  answer_text: status === "completed" ? `Model ${SLOTS[i].display_label} answer text with a material claim [1].` : "",
  sources: status === "completed"
    ? [{ title: "Source A", url: "https://example.com/a", provider: "openrouter_search" },
       { title: "Source B", url: "https://example.com/b", provider: "openrouter_search" }]
    : [],
  provider_attempt_order: ["openrouter_search"], provider_path: "openrouter_search",
  fallback_used: false, status, latency_ms: 2200 + i * 100, citation_coverage: CC,
});
const debateOutputs = () => [
  { round_number: 1, status: "completed", critique_text: "Round 1 critique: models largely align on the core recommendation.", focus_areas: ["scope", "evidence"], contributing_models: SLOTS.map((s) => s.model_id), latency_ms: 3100 },
  { round_number: 2, status: "completed", critique_text: "Round 2 critique: residual disagreement resolved; citations verified.", focus_areas: ["citations"], contributing_models: SLOTS.map((s) => s.model_id), latency_ms: 2800 },
];
const positionMovements = (revised: number) => SLOTS.map((s, i) => ({
  slot_number: s.slot_number, model_id: s.model_id, display_name: s.display_label,
  opening: `Opening synopsis for ${s.display_label}.`,
  after_round_1: i < revised ? "Moved toward the panel position." : "Held its opening position.",
  final: "Aligned with the final synthesis.", revised: i < revised,
  revision_note: i < revised ? "Adjusted after round 1 critique." : null,
}));
const finalSynthesis = (falseConsensusPreserved: boolean) => ({
  status: "completed", consensus: "The models agree on the primary recommendation.",
  disagreement: falseConsensusPreserved ? "Two models dissent on the secondary point, preserved here." : "Minor wording differences only.",
  source_support: "Backed by cited sources across all responding models.",
  uncertainty: "Confidence is moderate to high given corroborating citations.",
  recommendation: "Proceed with the recommended approach.", citation_coverage: CC,
  quality_checks: { citation_coverage_target_met: true, false_consensus_preserved: falseConsensusPreserved, decision_support_framing_present: true, high_stakes_warning_required: false },
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
const runningResp = () => ({
  query_run_id: "11111111-1111-4111-8111-111111111111", status: "initial_answers_running", correlation_id: "corr-run-0001",
  model_slots: SLOTS, cost_estimate: costEstimate("0.100", "allow"), elapsed_time_ms: 4200,
  failed_steps: [], missing_steps: [], progress: progress("initial_answers", ["running", "pending", "pending", "pending"]),
  partial_failure_notice: null, provider_failure_notices: [],
  result: { model_answers: [answer(0), answer(1)], debate_outputs: [], final_synthesis: null, agreement: { aligned: 0, total: 4 }, position_movements: [] },
  result_generated_at_utc: "2026-07-10T12:00:00Z", demo_mode: false, live_count: 2, local_count: 0, material_claim_count: 6,
  actual_cost_usd: "0.000", actual_breakdown: null,
});
const completedResp = (consensus: boolean) => ({
  query_run_id: "11111111-1111-4111-8111-111111111111", status: "completed", correlation_id: "corr-run-0001",
  model_slots: SLOTS, cost_estimate: costEstimate("0.190", "require_confirmation"), elapsed_time_ms: 41200,
  failed_steps: [], missing_steps: [], progress: progress("synthesis", ["completed", "completed", "completed", "completed"]),
  partial_failure_notice: null, provider_failure_notices: [],
  result: {
    model_answers: [answer(0), answer(1), answer(2), answer(3)], debate_outputs: debateOutputs(),
    final_synthesis: finalSynthesis(!consensus), agreement: consensus ? { aligned: 4, total: 4 } : { aligned: 2, total: 4 },
    position_movements: positionMovements(consensus ? 2 : 3),
  },
  result_generated_at_utc: "2026-07-10T12:00:00Z", demo_mode: false, live_count: 4, local_count: 0, material_claim_count: 12,
  actual_cost_usd: "0.188", actual_breakdown: breakdown("0.188"),
});
const fulfil = (body: unknown, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify(body) });

// ---- helpers ----------------------------------------------------------------
const QUESTION = "What are the key metrics for measuring SaaS customer retention?";
const FREEZE = "*,*::before,*::after{transition:none !important;animation:none !important;transition-duration:0s !important;animation-duration:0s !important;}";

async function freeze(page: Page) {
  await page.addStyleTag({ content: FREEZE });
  // Stop the live-run poll/ticker timers so nothing re-renders mid-scan.
  await page.evaluate(() => { for (let i = 1; i < 100000; i++) { clearInterval(i); clearTimeout(i); } });
}
async function setTheme(page: Page, theme: "light" | "dark") {
  await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await page.waitForTimeout(150);
}
async function scanBothThemes(page: Page, label: string) {
  for (const theme of ["light", "dark"] as const) {
    await setTheme(page, theme);
    await freeze(page);
    const results = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
    const serious = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
    expect(serious, `${label} [${theme}] critical/serious axe violations:\n` +
      serious.map((v) => `  ${v.impact} ${v.id} @ ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`).join("\n")
    ).toEqual([]);
  }
}
async function fill(page: Page) { await page.getByRole("textbox").first().fill(QUESTION); }
async function boot(page: Page) {
  // Seed the first-visit gate's "workspace seen" flag so boot lands on the
  // composer directly (returning-visitor path). The landing is still scanned by
  // the dedicated "landing" test below via the "How it works" affordance.
  await page.addInitScript(() => {
    try { window.localStorage.setItem("quorum.workspaceSeen", "1"); } catch (_) {}
  });
  await page.goto("/ui", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-view="composer"]')).toBeVisible();
  // Wait until the four model slots are populated before interacting. The
  // estimate handler calls getModelIds() → renderModelInputs(); clicking
  // before the slots carry values makes it resolve display names for empty
  // ids and throw. This is the deterministic "composer ready" signal.
  await page.waitForFunction(() => {
    const slots = [...document.querySelectorAll("[data-model-slot]")];
    return slots.length === 4 && slots.every((s) => (s as HTMLInputElement).value?.trim().length > 0);
  }, { timeout: 15000 });
}
async function routeRun(page: Page, pollBody: unknown) {
  await page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(estimateResp("0.100", "allow"))));
  await page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] })));
  await page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null })));
  await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => r.fulfill(fulfil(pollBody)));
  await page.route(/\/v1\/query-runs$/, (r) =>
    r.request().method() === "POST" ? r.fulfill(fulfil(createResp())) : r.continue());
}
async function clickEstimate(page: Page) {
  await page.getByRole("button", { name: /see the estimate|estimate cost/i }).click();
}
// "Run now" is the direct-run CTA: on the mocked allow band it auto-proceeds
// straight to the run (live-run → result → error views). "See the estimate" now
// always stops at the cost gate, so it can no longer be used to reach those
// post-run views — use this helper for them.
async function clickRunNow(page: Page) {
  await page.locator("#run-now").click();
}

test.describe("AC-035 — axe over every view (both themes)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "axe reference run is chromium-only");

  test("composer (default)", async ({ page }) => {
    await boot(page); await fill(page);
    await scanBothThemes(page, "composer");
  });

  test("landing", async ({ page }) => {
    await boot(page);
    // ``#show-landing`` is the visible top-bar "How it works" link; clicking it
    // reopens the marketing landing (screen 01) for a returning visitor.
    await page.locator("#show-landing").click();
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await scanBothThemes(page, "landing");
  });

  test("landing — empty-submit error state", async ({ page }) => {
    // The empty-submit guard renders net-new ARIA/colour (a danger ring on the
    // runbar, a role=alert "!" message, aria-invalid on the input). Scan it.
    await boot(page);
    await page.locator("#show-landing").click();
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await page.locator("#landing-run").click(); // empty → error state
    await expect(page.locator("#landing-query-error")).toBeVisible();
    await scanBothThemes(page, "landing-empty-error");
  });

  test("landing — hand-off transition note", async ({ page }) => {
    // The role=status hand-off note is a net-new rendered element. Reveal it
    // deterministically (the live flow hides it after a dwell) and scan it.
    await boot(page);
    await page.locator("#show-landing").click();
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await page.evaluate(() => {
      const t = document.getElementById("landing-handoff-note-text");
      const n = document.getElementById("landing-handoff-note");
      if (t) t.textContent = "Got your question. Taking you to review your four models and see the itemized cost before anything runs…";
      if (n) (n as HTMLElement).hidden = false;
    });
    await expect(page.locator("#landing-handoff-note")).toBeVisible();
    await scanBothThemes(page, "landing-handoff-note");
  });

  test("cost-gate — confirm", async ({ page }) => {
    await boot(page);
    await page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(estimateResp("0.190", "require_confirmation"))));
    await fill(page); await clickEstimate(page);
    await expect(page.locator("#gate-confirm")).toBeVisible();
    await scanBothThemes(page, "cost-gate-confirm");
  });

  test("cost-gate — allow band (review & run copy)", async ({ page }) => {
    // "See the estimate" on an allow-band estimate now shows the gate with the new
    // "review and run" copy + a plain "Run · $X" CTA — a net-new rendered state.
    await boot(page);
    await page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(estimateResp("0.100", "allow"))));
    await page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] })));
    await fill(page); await clickEstimate(page);
    await expect(page.locator("#gate-confirm .button-label")).toHaveText(/^Run · \$0\.1/);
    await scanBothThemes(page, "cost-gate-allow");
  });

  test("cost-gate — block", async ({ page }) => {
    await boot(page);
    await page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(estimateResp("0.300", "block"))));
    await fill(page); await clickEstimate(page);
    await expect(page.locator('#cost-review-card[data-band="block"]')).toBeVisible();
    await scanBothThemes(page, "cost-gate-block");
  });

  test("live-run — running", async ({ page }) => {
    await boot(page); await routeRun(page, runningResp());
    await fill(page); await clickRunNow(page);
    await expect(page.locator('#live-status-pill[data-state="running"]')).toBeVisible();
    await scanBothThemes(page, "live-run-running");
  });

  test("result — consensus + details expanded + transcript", async ({ page }) => {
    await boot(page); await routeRun(page, completedResp(true));
    await fill(page); await clickRunNow(page);
    await expect(page.locator('#result-verdict[data-consensus="true"]')).toBeVisible();
    await scanBothThemes(page, "result-consensus");
    await page.locator("#result-details-toggle").click();
    await expect(page.locator("#result-receipt")).toBeVisible();
    await scanBothThemes(page, "result-details");
    await page.locator("#result-transcript-link").click();
    await expect(page.locator('[data-view="transcript"]')).toBeVisible();
    await scanBothThemes(page, "transcript");
  });

  // FR-016 (S3): the trust-score surface reuses the alpha-tinted --warning-soft /
  // --info-soft tokens, and axe reports body-text contrast over an alpha layer as
  // INCOMPLETE ("could not tell"), not a violation — so a violations-only filter
  // reads "axe could not tell" as "pass". This scoped scan fails on both a
  // critical/serious violation AND any incomplete `color-contrast` entry, and
  // additionally composites the alpha layers itself to assert >= 4.5:1.
  test("result — trust-score surface (scoped, both themes, contrast composited)", async ({ page }) => {
    await boot(page);
    // Missing-high-stakes carries the amber caveat row + why-lines + the state
    // line, so the scan covers every text-on-tint the surface can render.
    const body = withEvaluation(completedResp(false), EVAL_MISSING_HIGH_STAKES);
    await routeRun(page, body);
    await clickRunNow(page);
    await expect(page.locator("#result-trust-score")).toBeVisible();

    for (const theme of ["light", "dark"] as const) {
      await setTheme(page, theme);
      await freeze(page);
      const results = await new AxeBuilder({ page }).include("#result-trust-score").withTags(AXE_TAGS).analyze();
      const serious = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
      expect(serious, `trust-score [${theme}] critical/serious axe violations:\n` +
        serious.map((v) => `  ${v.impact} ${v.id} @ ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`).join("\n"),
      ).toEqual([]);
      // "axe could not tell" must NEVER read as "pass": fail on incomplete contrast.
      const incompleteContrast = results.incomplete.filter((r) => r.id === "color-contrast");
      expect(incompleteContrast, `trust-score [${theme}] incomplete color-contrast entries must be resolved`).toEqual([]);

      // Deterministic in-spec contrast: composite each text node over its first
      // non-transparent ancestor background and assert >= 4.5:1 (>= 3:1 for
      // >=18.66px bold).
      const failures = await page.locator("#result-trust-score").evaluate((root) => {
        const parseRgba = (s: string) => {
          const m = s.match(/rgba?\(([^)]+)\)/);
          if (!m) return null;
          const p = m[1].split(/[,\s/]+/).map(Number);
          return { r: p[0], g: p[1], b: p[2], a: p.length > 3 && !Number.isNaN(p[3]) ? p[3] : 1 };
        };
        const over = (fg: { r: number; g: number; b: number; a: number }, bg: { r: number; g: number; b: number }) => ({
          r: fg.r * fg.a + bg.r * (1 - fg.a),
          g: fg.g * fg.a + bg.g * (1 - fg.a),
          b: fg.b * fg.a + bg.b * (1 - fg.a),
        });
        const lum = (c: { r: number; g: number; b: number }) => {
          const f = (v: number) => {
            v /= 255;
            return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
          };
          return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
        };
        const bgOf = (el: Element): { r: number; g: number; b: number } => {
          let node: Element | null = el;
          while (node) {
            const c = parseRgba(getComputedStyle(node).backgroundColor);
            if (c && c.a > 0) {
              const parentBg = node.parentElement ? bgOf(node.parentElement) : { r: 255, g: 255, b: 255 };
              return over(c, parentBg);
            }
            node = node.parentElement;
          }
          return { r: 255, g: 255, b: 255 };
        };
        const fails: string[] = [];
        const texts = Array.from(root.querySelectorAll("*")).filter(
          (el) => Array.from(el.childNodes).some((n) => n.nodeType === 3 && (n.textContent || "").trim().length > 0),
        );
        for (const el of texts) {
          const cs = getComputedStyle(el);
          const fg = parseRgba(cs.color);
          if (!fg) continue;
          const composited = fg.a < 1 ? { ...over(fg, bgOf(el)), a: 1 } : fg;
          const bg = bgOf(el);
          const L1 = lum(composited) + 0.05;
          const L2 = lum(bg) + 0.05;
          const ratio = Math.max(L1, L2) / Math.min(L1, L2);
          const px = parseFloat(cs.fontSize);
          const bold = parseInt(cs.fontWeight, 10) >= 700;
          const min = px >= 18.66 && bold ? 3 : 4.5;
          if (ratio < min) fails.push(`${(el.className || el.tagName)}: ${ratio.toFixed(2)} < ${min}`);
        }
        return fails;
      });
      expect(failures, `trust-score [${theme}] contrast failures:\n${failures.join("\n")}`).toEqual([]);
    }
  });

  test("result — divided (amber)", async ({ page }) => {
    await boot(page); await routeRun(page, completedResp(false));
    await fill(page); await clickRunNow(page);
    await expect(page.locator('#result-verdict[data-consensus="false"]')).toBeVisible();
    await scanBothThemes(page, "result-divided");
  });

  const ERRORS = [
    { name: "500", status: 500, code: "INTERNAL", extra: {} },
    { name: "409 active", status: 409, code: "ACTIVE_QUERY_EXISTS", extra: {} },
    { name: "422 slot", status: 422, code: "INVALID_MODEL_SLOT", extra: { slot_errors: [{ slot_number: 2, model_id: "anthropic/claude-haiku-4.5", message: "Model unavailable." }] } },
    { name: "404 not-found", status: 404, code: "QUERY_RUN_NOT_FOUND", extra: {} },
  ];
  for (const e of ERRORS) {
    test(`error-region — ${e.name}`, async ({ page }) => {
      await boot(page);
      await page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(estimateResp("0.100", "allow"))));
      await page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] })));
      await page.route(/\/v1\/query-runs$/, (r) =>
        r.request().method() === "POST"
          ? r.fulfill(fulfil({ detail: { code: e.code, message: "A user-safe error occurred.", ...e.extra } }, e.status))
          : r.continue());
      await fill(page); await clickRunNow(page);
      await expect(page.locator("#error-region")).toBeVisible();
      await scanBothThemes(page, `error-${e.name}`);
    });
  }
});
