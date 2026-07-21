import { expect, Page } from "@playwright/test";

/**
 * GOLDEN REALISTIC FIXTURE — real-shaped, "messy" LLM output.
 *
 * WHY THIS EXISTS
 * ---------------
 * The existing e2e mocks (see api-mocking.spec.ts, axe-all-views.spec.ts) feed
 * CLEAN, short, Markdown-free text ("Model X answer text with a material claim
 * [1]."). Clean mocks made a whole class of real-data bugs INVISIBLE to CI:
 *   - #30 raw Markdown (`##`/`**`) rendered literally on ~11 provider-text
 *     surfaces that bypass the Markdown formatter,
 *   - #29 a non-monotonic live-run timer (only visible on a long, multi-poll run),
 *   - #33 a cramped transcript layout (only stressed by long, wrapping answers).
 *
 * This fixture is the antidote required by docs/day-one-quality-standard.md: a
 * single canonical blob of REAL, messy provider output (headings, bold, ordered
 * lists, bare URLs, long paragraphs, an empty-citation case) that every view
 * renders against — so those bugs become catchable OFFLINE, with no paid run.
 *
 * Schema note: these builders mirror the OpenAPI QueryRun* shapes used by
 * e2e/tests/accessibility/axe-all-views.spec.ts (kept deliberately in sync); the
 * ONLY difference is the text content, which here is intentionally messy.
 */

// ---- markdown-marker detector (the invariant used by the rendering gate) -----
// A rendered DOM should contain NO literal Markdown control syntax in its text
// nodes: the formatter must have turned `##`/`**`/`1.` into real <h*>/<strong>/
// <li> elements. If a raw marker survives into a text node, a surface bypassed
// the formatter (bug #30).
// Only the two markers that ANY correct #30 fix provably eliminates from text
// nodes: inline bold (`**` → <strong>) and a line-START heading (`## ` → <h*>).
// We deliberately do NOT flag ordered-list markers: a correctly rendered <ol>
// exposes its numbers as CSS ::marker pseudo-elements, not text nodes, so a
// text-node walker never sees them — flagging "1." would risk a non-greenable
// gate. Mid-line `##` is likewise avoided in the fixture, because valid Markdown
// headings must start a line; a formatter legitimately leaves mid-sentence `##`
// alone, so seeding it would make the gate impossible to turn green.
export const RAW_MARKDOWN_PATTERNS: { name: string; re: RegExp }[] = [
  { name: "bold asterisks (**)", re: /\*\*/ },
  { name: "line-start heading (## )", re: /(^|\n)#{1,6}\s/ },
  // Also greenable via the real renderer (mdInline converts these to
  // <code>/<a>, leaving no marker in any text node):
  { name: "inline code (`...`)", re: /`[^`]+`/ },
  { name: "markdown link (](url))", re: /\]\([^)]+\)/ },
  // Now asserted too — the formatter was extended (mdInline gained word-boundary
  // underscore emphasis; formatAnswerText gained a `>` blockquote block), so a
  // correct render leaves NO marker in any text node:
  //   underscore emphasis: matches a space/start-anchored `_x_` / `__x__` run
  //   (word-boundary, so intra-word `retention_flag` / `snake_case` never match);
  //   blockquote: a line that STARTS with `> ` (mid-line `>` — e.g. "> 100%" — is
  //   not a blockquote and is intentionally not matched).
  { name: "underscore emphasis (_x_ / __x__)", re: /(^|\s)_{1,2}[^\s_][^_]*_{1,2}(?=[\s.,!?)]|$)/ },
  { name: "line-start blockquote (> )", re: /(^|\n)>\s/ },
];
// STRUCTURAL limits of this gate (documented, not silently implied):
//   (a) scope — it walks `#main-content` (where provider prose renders); app
//       chrome (toasts/header/aria-live) is app-authored text, not provider
//       markdown, so it is intentionally out of scope;
//   (b) timing — it is a single post-hydration snapshot; streamed/late renders
//       after the walk are not covered.

// ---- messy, real-shaped provider text ---------------------------------------
// Deliberately seeded into the RAW surfaces (verdict recommendation/summary/
// caveat, trust-card captions, source titles, debate critiques, transcript
// openings) so the no-raw-markdown invariant goes RED on today's code.
const MESSY_RECOMMENDATION =
  "## Recommendation\n\n**Proceed** with the phased rollout, but stage it. The panel converges on three points:\n\n" +
  "1. Ship the retention-instrumentation slice first — it de-risks every later decision.\n" +
  "2. Only then enable the cohort export; it depends on the events above.\n" +
  "3. Keep the $0.25 spend cap until a measured run confirms the estimate.\n\n" +
  "> Treat this as _decision support_, __not__ a mandate — a human still owns the call.\n\n" +
  "See the [full playbook](https://example.com/retention/playbook), set `retention_flag=true`, and wire `__init__`. **Do not** skip step 1.";

// Inline surface: bold only (no line-start heading — a one-line span).
const MESSY_SUMMARY =
  "**Bottom line:** four of four models agree on the primary recommendation, with one dissent on sequencing.";
const MESSY_CAVEAT =
  "**High-stakes:** treat the cost figure as an estimate, not a bill — verify against a real run before relying on it.";
const MESSY_CONSENSUS =
  "The models **agree** on the primary recommendation: instrument first, export second. This is the core finding and it is well supported.";
const MESSY_DISAGREEMENT =
  "Two models **dissent** on the secondary point (whether to gate the export behind a manual review). Preserved here rather than smoothed over.";
const MESSY_SOURCE_SUPPORT =
  "Backed by **cited** sources across all responding models. Coverage ratio 0.85 against a 0.80 target.";
// Deliberately > 180 chars with a `**bold**` run STRADDLING character 180
// (opening `**` at index 167, closing at 229): the old
// `truncateText(uncertaintyText, 180)` sliced here mid-run, leaving a dangling
// `**` in a text node that the no-raw-markdown invariant catches. See D-16.
const MESSY_UNCERTAINTY =
  "Confidence is moderate-to-high given corroborating citations across every " +
  "responding model, though the secondary sequencing point about the cohort " +
  "export gate remains **genuinely contested and unresolved between two of the " +
  "panels** even after both debate rounds concluded.";

// Block surfaces: a line-START heading + inline bold + an ordered list. A correct
// fix routes these through the block formatter (heading→<h*>, **→<strong>,
// list→<ol>), leaving no `**`/`## ` in any text node.
const MESSY_CRITIQUE_1 =
  "## Round 1 critique\n\n**Alignment:** the models largely agree on the core recommendation. Residual gaps:\n\n1. Scope of the export slice.\n2. Whether citations meet the 0.80 target (they do — 0.85).";
const MESSY_CRITIQUE_2 =
  "## Round 2 critique\n\n**Resolved:** the residual disagreement on sequencing; citations _re-verified_. See the [round-2 log](https://example.com/round2) and the `citation_check` output.\n\n> Residual __caveat__: the export slice still needs a manual review gate.";

// Inline surface (table cell): bold only.
const MESSY_OPENING = (label: string) =>
  `**Position:** ${label} argues for instrumenting retention events before any cohort export, citing https://example.com/${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.`;

// Source titles are provider METADATA, not prose: the correct rendering is plain
// text (escaped), NOT Markdown. So we deliberately do NOT seed `**`/`##` here —
// asserting bold-rendered source titles would mandate a dubious design and make
// the gate non-greenable (a block/inline prose fix does not, and should not,
// reach a link label or citation chip). Realistic messy-but-plain titles:
const MESSY_SOURCE_TITLE_A =
  "Smith et al. (2024) — Retention benchmarks for SaaS (working paper, v2)";
const MESSY_SOURCE_TITLE_B =
  "Jones & Lee — Cohort export patterns [preprint]";

// A genuinely long, multi-paragraph answer (~450 words) to stress the transcript
// layout (#33) and the answer-section formatter. This surface IS formatted, so
// its `##`/`**` should render as real HTML (the "good path" the gate confirms).
const LONG_MESSY_ANSWER = (label: string) =>
  `## ${label} — analysis\n\n` +
  "**Summary:** measuring SaaS customer retention well means separating *logo* retention from *net-revenue* retention, and instrumenting the events that drive each before you try to move them.\n\n" +
  "### Why the distinction matters\n\n" +
  "Logo retention counts whether an account still exists; net-revenue retention (NRR) counts whether the dollars stayed or grew. A business can lose small accounts while expanding large ones, posting > 100% NRR alongside falling logo retention. Reporting only one number hides that. The panel recommends tracking **both**, on the same cohort definition, so the two curves are comparable.\n\n" +
  "### The events to instrument first\n\n" +
  "1. **Activation** — the first time an account reaches the value milestone you believe predicts retention.\n" +
  "2. **Habit** — recurring usage at whatever cadence is natural for the product (daily, weekly, monthly).\n" +
  "3. **Expansion / contraction** — seat, usage, or tier changes, timestamped and attributable to a cohort.\n" +
  "4. **Churn signal** — the leading indicators (support escalations, usage decay) that precede a cancellation.\n\n" +
  "Without those events, every retention metric is a lagging autopsy. With them, you can build cohorted curves and, more importantly, intervene while a save is still possible. See https://example.com/retention/instrumentation for a reference event schema.\n\n" +
  "### Cohorting and the common trap\n\n" +
  "Cohort by **signup month** for acquisition-quality questions, but cohort by **activation month** for product questions — mixing the two is the single most common source of misleading retention charts. Always state the cohort definition on the chart itself; a curve without a stated denominator is not interpretable.\n\n" +
  "### What good looks like\n\n" +
  "A mature setup reports monthly logo retention and NRR side by side, per activation cohort, with the raw event counts one click away so anyone can audit the number. The **worst** anti-pattern is a single blended percentage with no cohort, no denominator, and no link to the underlying events — it looks authoritative and means almost nothing.\n\n" +
  `Confidence for ${label}: moderate-to-high, contingent on the events above actually being instrumented.`;

// ---- schema builders (mirror axe-all-views.spec.ts; messy content) ----------
export const SLOTS = [
  { slot_number: 1, model_id: "openai/gpt-4o-mini", display_label: "GPT-4o-mini" },
  { slot_number: 2, model_id: "anthropic/claude-haiku-4.5", display_label: "Claude Haiku 4.5" },
  { slot_number: 3, model_id: "google/gemini-2.5-flash", display_label: "Gemini 2.5 Flash" },
  { slot_number: 4, model_id: "deepseek/deepseek-v3.1", display_label: "DeepSeek V3.1" },
];
const CC = { material_claim_count: 12, cited_claim_count: 10, coverage_ratio: "0.85", target_ratio: "0.80", target_met: true };
// The empty-citation case (#31 shape): a slot that answered but returned NO sources.
const CC_EMPTY = { material_claim_count: 9, cited_claim_count: 0, coverage_ratio: "0.00", target_ratio: "0.80", target_met: false };
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
const goldenAnswer = (i: number) => ({
  slot_number: i + 1, model_id: SLOTS[i].model_id,
  answer_text: LONG_MESSY_ANSWER(SLOTS[i].display_label),
  // Slot 3 is the empty-citation case (#31): answered, zero sources.
  sources: i === 2
    ? []
    : [{ title: MESSY_SOURCE_TITLE_A, url: "https://example.com/a", provider: "openrouter_search" },
       { title: MESSY_SOURCE_TITLE_B, url: "https://example.com/b", provider: "openrouter_search" }],
  provider_attempt_order: ["openrouter_search"], provider_path: "openrouter_search",
  fallback_used: false, status: "completed", latency_ms: 2200 + i * 100,
  citation_coverage: i === 2 ? CC_EMPTY : CC,
});
const goldenDebate = () => [
  { round_number: 1, status: "completed", critique_text: MESSY_CRITIQUE_1, focus_areas: ["scope", "evidence"], contributing_models: SLOTS.map((s) => s.model_id), latency_ms: 3100 },
  { round_number: 2, status: "completed", critique_text: MESSY_CRITIQUE_2, focus_areas: ["citations"], contributing_models: SLOTS.map((s) => s.model_id), latency_ms: 2800 },
];
const goldenMovements = (revised: number) => SLOTS.map((s, i) => ({
  slot_number: s.slot_number, model_id: s.model_id, display_name: s.display_label,
  opening: MESSY_OPENING(s.display_label),
  after_round_1: i < revised ? "Moved toward the panel position." : "Held its opening position.",
  final: "Aligned with the final synthesis.", revised: i < revised,
  revision_note: i < revised ? "Adjusted after round 1 critique." : null,
}));
const goldenSynthesis = () => ({
  status: "completed", consensus: MESSY_CONSENSUS, disagreement: MESSY_DISAGREEMENT,
  source_support: MESSY_SOURCE_SUPPORT, uncertainty: MESSY_UNCERTAINTY,
  recommendation: MESSY_RECOMMENDATION, citation_coverage: CC,
  quality_checks: { citation_coverage_target_met: true, false_consensus_preserved: false, decision_support_framing_present: true, high_stakes_warning_required: true },
  high_stakes_notice: MESSY_CAVEAT, latency_ms: 4200, summary: MESSY_SUMMARY,
});
const progress = (stage: string, states: string[]) => ({
  current_stage: stage,
  stages: [
    { stage: "initial_answers", state: states[0] }, { stage: "debate_round_1", state: states[1] },
    { stage: "debate_round_2", state: states[2] }, { stage: "synthesis", state: states[3] },
  ],
});
export const goldenCreateResp = () => ({
  query_run_id: "22222222-2222-4222-8222-222222222222", status: "accepted", correlation_id: "corr-golden-0001",
  model_slots: SLOTS, cost_estimate: costEstimate("0.100", "allow"),
  progress: progress("initial_answers", ["running", "pending", "pending", "pending"]), initial_answers: [],
});
// Running poll with a caller-supplied elapsed_time_ms — used to script a
// DECREASING elapsed sequence that exposes the non-monotonic timer (#29).
export const goldenRunningResp = (elapsedMs: number) => ({
  query_run_id: "22222222-2222-4222-8222-222222222222", status: "initial_answers_running", correlation_id: "corr-golden-0001",
  model_slots: SLOTS, cost_estimate: costEstimate("0.100", "allow"), elapsed_time_ms: elapsedMs,
  failed_steps: [], missing_steps: [], progress: progress("initial_answers", ["running", "pending", "pending", "pending"]),
  partial_failure_notice: null, provider_failure_notices: [],
  result: { model_answers: [goldenAnswer(0), goldenAnswer(1)], debate_outputs: [], final_synthesis: null, agreement: { aligned: 0, total: 4 }, position_movements: [] },
  result_generated_at_utc: "2026-07-10T12:00:00Z", demo_mode: false, live_count: 2, local_count: 0, material_claim_count: 6,
  actual_cost_usd: "0.000", actual_breakdown: null,
});
export const goldenCompletedResp = () => ({
  query_run_id: "22222222-2222-4222-8222-222222222222", status: "completed", correlation_id: "corr-golden-0001",
  model_slots: SLOTS, cost_estimate: costEstimate("0.190", "require_confirmation"), elapsed_time_ms: 41200,
  failed_steps: [], missing_steps: [], progress: progress("synthesis", ["completed", "completed", "completed", "completed"]),
  partial_failure_notice: null, provider_failure_notices: [],
  result: {
    model_answers: [goldenAnswer(0), goldenAnswer(1), goldenAnswer(2), goldenAnswer(3)], debate_outputs: goldenDebate(),
    final_synthesis: goldenSynthesis(), agreement: { aligned: 3, total: 4 },
    position_movements: goldenMovements(3),
  },
  result_generated_at_utc: "2026-07-10T12:00:00Z", demo_mode: false, live_count: 4, local_count: 0, material_claim_count: 12,
  actual_cost_usd: "0.188", actual_breakdown: breakdown("0.188"),
});

const fulfil = (body: unknown, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify(body) });

// ---- FR-016 (S3) evaluation fixtures (D-13) ---------------------------------
// goldenCompletedResp() deliberately carries NO `evaluation` key — it IS the
// canonical ABSENT case the "hide, don't render —" rule (D-14) is about, and it
// is consumed unchanged by the degraded/invariants/visual/a11y/ui-parity specs.
//
// The six named variants are loaded from a SHARED JSON (evaluation-variants.json)
// that the Python contract test validates against the real
// QueryRunEvaluationProjection, so a shape the server can never emit fails in
// Python rather than greening a mocked e2e run. Import them from that single
// source; do not hand-duplicate the shapes here.
import EVAL_VARIANTS from "./evaluation-variants.json";

/** The served QueryRunEvaluationProjection shape. */
export type EvaluationProjection = (typeof EVAL_VARIANTS)["EVAL_CLEAN"];

export const EVAL_CLEAN = EVAL_VARIANTS.EVAL_CLEAN as EvaluationProjection;
export const EVAL_NON_CONSENSUS = EVAL_VARIANTS.EVAL_NON_CONSENSUS as EvaluationProjection;
export const EVAL_UNKNOWN_GROUNDING_REFUSAL =
  EVAL_VARIANTS.EVAL_UNKNOWN_GROUNDING_REFUSAL as EvaluationProjection;
export const EVAL_LAUNDERED = EVAL_VARIANTS.EVAL_LAUNDERED as EvaluationProjection;
export const EVAL_MISSING_HIGH_STAKES =
  EVAL_VARIANTS.EVAL_MISSING_HIGH_STAKES as EvaluationProjection;
export const EVAL_SUPPRESSED_DISAGREEMENT =
  EVAL_VARIANTS.EVAL_SUPPRESSED_DISAGREEMENT as EvaluationProjection;

/** The six well-formed variants, in a stable order — for parameterised specs. */
export const EVAL_ALL_VARIANTS: { name: string; ev: EvaluationProjection }[] = [
  { name: "EVAL_CLEAN", ev: EVAL_CLEAN },
  { name: "EVAL_NON_CONSENSUS", ev: EVAL_NON_CONSENSUS },
  { name: "EVAL_UNKNOWN_GROUNDING_REFUSAL", ev: EVAL_UNKNOWN_GROUNDING_REFUSAL },
  { name: "EVAL_LAUNDERED", ev: EVAL_LAUNDERED },
  { name: "EVAL_MISSING_HIGH_STAKES", ev: EVAL_MISSING_HIGH_STAKES },
  { name: "EVAL_SUPPRESSED_DISAGREEMENT", ev: EVAL_SUPPRESSED_DISAGREEMENT },
];

/**
 * The FAIL-CLOSED case (D-3): a persisted `s2-eval-v2`-shaped row read back,
 * whose `label_confidence` field does not exist. The whitelist
 * (`label_confidence === "reportable"`) must render the INDETERMINATE treatment
 * on it, not the confident branch. Deliberately NOT in EVAL_ALL_VARIANTS and NOT
 * validated by the Python contract test — it is by construction invalid under
 * the current required schema (label_confidence has no default), which is the
 * whole point.
 */
export const EVAL_S2_SHAPED = (() => {
  const ev = JSON.parse(JSON.stringify(EVAL_CLEAN)) as Record<string, unknown>;
  delete ev.label_confidence;
  return ev;
})();

/** Build a clean evaluation projection, with shallow overrides for ad-hoc cases. */
export function goldenEvaluation(
  overrides: Partial<EvaluationProjection> & { signals?: Record<string, unknown> } = {},
): EvaluationProjection {
  const base = JSON.parse(JSON.stringify(EVAL_CLEAN)) as EvaluationProjection;
  const { signals, ...top } = overrides;
  return {
    ...base,
    ...top,
    signals: { ...base.signals, ...(signals ?? {}) },
  } as EvaluationProjection;
}

/** Attach an evaluation projection to a completed response (top-level key). */
export function withEvaluation<T extends Record<string, unknown>>(resp: T, ev: unknown): T {
  return { ...resp, evaluation: ev };
}

// ---- navigation helpers (self-contained; mirror axe-all-views patterns) -----
export async function boot(page: Page) {
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
async function fill(page: Page) {
  await page.getByRole("textbox").first().fill("What are the key metrics for measuring SaaS customer retention?");
}
async function clickRunNow(page: Page) {
  await page.locator("#run-now").click();
}
function baseRoutes(page: Page) {
  return Promise.all([
    page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(costEstimateEnvelope()))),
    page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
    page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
  ]);
}
const costEstimateEnvelope = () => ({
  correlation_id: "corr-golden-est", cost_estimate: costEstimate("0.100", "allow"), model_slots: SLOTS, reasons: [],
});

/** Drive composer → run → completed RESULT view with the golden (messy) payload. */
export async function driveToResult(page: Page) {
  await boot(page);
  await baseRoutes(page);
  await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => r.fulfill(fulfil(goldenCompletedResp())));
  await page.route(/\/v1\/query-runs$/, (r) =>
    r.request().method() === "POST" ? r.fulfill(fulfil(goldenCreateResp())) : r.continue());
  await fill(page);
  await clickRunNow(page);
  // Anchor on a POPULATED, late-rendered result: `[data-consensus]` is set only
  // once synthesis lands, and `#result-transcript-link` is rendered at the end
  // of the result pass. Waiting on both (not merely verdict visibility) ensures
  // the whole result DOM has hydrated before the no-raw-markdown walk runs, so a
  // late-rendering surface cannot slip past as a spurious pass.
  await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
  await expect(page.locator("#result-transcript-link")).toBeVisible({ timeout: 20000 });
}

/** From the result view, open the full debate transcript view. */
export async function driveToTranscript(page: Page) {
  await page.locator("#result-transcript-link").click();
  await expect(page.locator('[data-view="transcript"]')).toBeVisible();
}

/**
 * Drive a live run whose successive polls report a DECREASING elapsed_time_ms,
 * then complete. Exposes the non-monotonic timer (#29): the readout should never
 * tick backwards, but today it snaps down when a lower server elapsed arrives.
 * The `elapsedSequence` is consumed one value per poll; once exhausted the run
 * completes.
 */
export async function driveDecreasingTimer(page: Page, elapsedSequence: number[]) {
  await boot(page);
  await baseRoutes(page);
  let poll = 0;
  await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => {
    const idx = poll++;
    if (idx < elapsedSequence.length) {
      r.fulfill(fulfil(goldenRunningResp(elapsedSequence[idx])));
    } else {
      r.fulfill(fulfil(goldenCompletedResp()));
    }
  });
  await page.route(/\/v1\/query-runs$/, (r) =>
    r.request().method() === "POST" ? r.fulfill(fulfil(goldenCreateResp())) : r.continue());
  await fill(page);
  await clickRunNow(page);
  await expect(page.locator("#live-elapsed")).toBeVisible({ timeout: 15000 });
}

/** Parse the "#live-elapsed" readout ("12.0s elapsed" / "1m 05s elapsed") → ms. */
export function parseElapsedMs(text: string | null): number | null {
  if (!text) return null;
  const min = text.match(/(\d+)m\s+(\d+)s/);
  if (min) return (Number(min[1]) * 60 + Number(min[2])) * 1000;
  const sec = text.match(/([\d.]+)s\s+elapsed/);
  if (sec) return Math.round(Number(sec[1]) * 1000);
  return null;
}
