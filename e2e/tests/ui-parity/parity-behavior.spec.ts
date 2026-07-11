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
    // ``#show-landing`` is intentionally visually hidden (sr-only) after the
    // item-2 top-bar change. Dispatch the click straight to the element (a
    // coordinate click would land on the overlapping status pill instead).
    await page.locator("#show-landing").dispatchEvent("click");
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await expect(page.locator(".landing-preview-badge")).toHaveText("Preview");
    await expect(page.locator(".landing-preview")).toHaveAttribute("aria-label", "Example preview");
    await expect(page.locator(".landing-preview-caption")).toContainText("not a run you started");
    // The global top bar is hidden on landing (no double header).
    await expect(page.locator(".topbar")).toBeHidden();
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

  test("item 2 — top bar shows a single session pill + theme toggle; no visible 'How it works'", async ({ page }) => {
    await boot(page);
    const pill = page.locator("#connection-pill");
    await expect(pill).toBeVisible();
    await expect(pill).toHaveClass(/status-pill-session/);
    // Honest wording: "Session active · <capability>" — provider configured when
    // live, local simulation when degraded. Either way it starts "Session active".
    await expect(page.locator("#connection-pill-text")).toHaveText(/^Session active · (provider configured|local simulation)$/);
    // The theme toggle is preserved (a real feature the comp doesn't depict).
    await expect(page.locator("#theme-toggle")).toBeVisible();
    // The "How it works" control is no longer visible chrome — it survives as a
    // visually-hidden (sr-only) button so the landing view stays reachable and
    // the landing tests keep working. Assert it renders at ~0 visual size.
    const box = await page.locator("#show-landing").boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeLessThanOrEqual(2);
    expect(box!.height).toBeLessThanOrEqual(2);
    // It must still exist exactly once (reachability contract).
    await expect(page.locator("#show-landing")).toHaveCount(1);
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

  test("item 4 — the four example chips lay out 2×2 (two rows of two)", async ({ page }) => {
    await boot(page);
    const chips = page.locator(".composer-examples-row .landing-chip");
    await expect(chips).toHaveCount(4);
    const boxes = await chips.evaluateAll((els) =>
      els.map((e) => {
        const r = e.getBoundingClientRect();
        return { x: Math.round(r.left), y: Math.round(r.top) };
      }),
    );
    const rows = [...new Set(boxes.map((b) => b.y))].sort((a, b) => a - b);
    expect(rows.length, "chips should occupy exactly two rows").toBe(2);
    const rowCount = (y: number) => boxes.filter((b) => b.y === y).length;
    expect(rowCount(rows[0]), "row 1 should hold two chips").toBe(2);
    expect(rowCount(rows[1]), "row 2 should hold two chips").toBe(2);
    // The two columns line up (left edges match across rows) — a real grid.
    const cols = [...new Set(boxes.map((b) => b.x))].sort((a, b) => a - b);
    expect(cols.length).toBe(2);
  });
});
