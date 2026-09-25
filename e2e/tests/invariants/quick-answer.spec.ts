// W5, third of four pull requests (ADR-0128): the quick answer in the workspace.
//
// The owner decided the control's words, "Quick answer — one model, no debate",
// the info line "four models by default, 2 debates and 1 sourced answer", that
// the judge's verdict shows as "Judge: well supported / partly supported / not
// supported" with its reasons and evidence, and that a quick answer shows no
// agreement figure (CHG-012 D1; docs/analysis/2026-09-24-w5-parked.md). The
// layout below is the session's design, recorded in ADR-0128.
//
// Every ABSENCE asserted here has a positive partner: the same selector on a
// panel result is present, so a check that could pass on an empty page cannot.
import { test, expect, Page } from "@playwright/test";
import {
  boot,
  driveToResult,
  driveToQuickResult,
  goldenCompletedResp,
  goldenCreateResp,
  goldenQuickResp,
  goldenQuickRespSimulated,
  goldenQuickCreateResp,
  quickEstimateEnvelope,
  withEvaluation,
  EVAL_CLEAN,
  QUICK_SAFETY_NOTICE,
  QUICK_VERDICT_WELL_SUPPORTED,
  QUICK_VERDICT_CONTRADICTED,
  RAW_MARKDOWN_PATTERNS,
  SLOTS,
} from "../../fixtures/golden-run";

const QUICK_LABEL = "Quick answer — one model, no debate";
const QUICK_INFO_LINE = "four models by default, 2 debates and 1 sourced answer";

// The panel-only surfaces a quick result must not show (the owner: no
// agreement figure; the session: no debate, no transcript, no panel trust).
const PANEL_ONLY = [
  "#result-verdict",
  "#result-trust",
  "#result-trust-score",
  "#result-debate",
  "#result-transcript-link",
  "#result-synthesis",
];

const json = (body: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

async function rawMarkdownIn(page: Page, scope: string) {
  return page.evaluate(
    ({ scope, patterns }) => {
      const root = document.querySelector(scope) || document.body;
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      const offenders: string[] = [];
      let walked = 0;
      let node: Node | null;
      while ((node = walker.nextNode())) {
        const parent = node.parentElement;
        if (!parent || parent.closest("code, pre")) continue;
        const text = node.textContent || "";
        if (!text.trim()) continue;
        walked += 1;
        for (const p of patterns) {
          if (new RegExp(p.re, p.flags).test(text)) {
            offenders.push(`[${p.name}] ${text.trim().slice(0, 80)}`);
            break;
          }
        }
      }
      return { offenders, walked };
    },
    { scope, patterns: RAW_MARKDOWN_PATTERNS.map((p) => ({ name: p.name, re: p.re.source, flags: p.re.flags })) },
  );
}

async function stubCopyAndExport(page: Page) {
  await page.evaluate(() => {
    const w = window as unknown as { __exported?: Promise<string>; __copied?: string };
    const real = URL.createObjectURL.bind(URL);
    URL.createObjectURL = (blob: Blob) => {
      w.__exported = blob.text();
      return real(blob);
    };
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: (text: string) => { w.__copied = text; return Promise.resolve(); } },
    });
  });
}

async function exportedAndCopied(page: Page) {
  await stubCopyAndExport(page);
  await page.locator("#result-export").click();
  await page.locator("#result-copy").click();
  await expect.poll(() => page.evaluate(() => (window as any).__copied ?? "")).not.toEqual("");
  const exported: string = await page.evaluate(() => (window as any).__exported ?? Promise.resolve(""));
  const copied: string = await page.evaluate(() => (window as any).__copied ?? "");
  return { exported, copied };
}

test.describe("W5 quick answer (ADR-0128)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "chromium-only gate");

  test("the control shows one slot and the owner's info line, and OFF restores the panel byte for byte", async ({ page }) => {
    await boot(page);
    const fieldset = page.locator("fieldset.field-group");
    const before = await fieldset.evaluate((node) => node.outerHTML);
    await expect(page.locator('label[for="quick-mode-input"]')).toHaveText(QUICK_LABEL);
    const note = page.locator("#quick-mode-note");
    await expect(note).toBeHidden();
    // Positive partner for every "hidden" below: the panel composer shows them.
    await expect(page.locator("#model-inputs .model-slot")).toHaveCount(4);
    await expect(page.locator("#panel-shape-line")).toBeVisible();

    await page.locator("#quick-mode-input").check();
    await expect(note).toBeVisible();
    await expect(note).toHaveText(QUICK_INFO_LINE);
    await expect(page.locator("#model-inputs .model-slot").first()).toBeVisible();
    for (const i of [1, 2, 3]) {
      await expect(page.locator("#model-inputs .model-slot").nth(i)).toBeHidden();
    }
    await expect(page.locator("#model-inputs .model-slot-remove").first()).toBeHidden();
    await expect(page.locator("#model-slot-add")).toBeHidden();
    await expect(page.locator("#panel-shape-line")).toBeHidden();

    // RED IF: turning the control off leaves any trace on the panel composer.
    await page.locator("#quick-mode-input").uncheck();
    const after = await fieldset.evaluate((node) => node.outerHTML);
    expect(after).toEqual(before);
    await expect(page.locator("#panel-shape-line")).toBeVisible();
  });

  test("a quick run sends mode quick and one model to the estimate and the create; a panel run sends neither", async ({ page, context }) => {
    const bodies = await driveToQuickResult(page);
    const estimate = bodies.find((b) => b.url === "estimate");
    const create = bodies.find((b) => b.url === "create");
    // RED IF: the control stops reaching the wire, or sends the whole panel.
    expect(estimate?.body).toEqual({
      query_text: "What are the key metrics for measuring SaaS customer retention?",
      model_slots: [SLOTS[0].model_id],
      mode: "quick",
    });
    expect(Object.keys(create?.body ?? {})).toEqual([
      "query_text", "model_slots", "mode", "safety_acknowledgements", "cost_confirmation",
    ]);
    expect(create?.body.mode).toEqual("quick");
    expect(create?.body.model_slots).toEqual([SLOTS[0].model_id]);
    // A quick request with follow-up context is refused server-side (ADR-0126).
    expect("context" in (create?.body ?? {})).toBe(false);

    // Positive partner: a panel run from a fresh page sends no mode and four models.
    const panelPage = await context.newPage();
    const panelBodies: Record<string, unknown>[] = [];
    panelPage.on("request", (r) => {
      if (r.method() === "POST" && /\/v1\/query-runs(\/estimate)?$/.test(r.url())) {
        panelBodies.push(JSON.parse(r.postData() || "{}"));
      }
    });
    await driveToResult(panelPage);
    expect(panelBodies.length).toBe(2);
    for (const body of panelBodies) {
      expect("mode" in body).toBe(false);
      expect(body.model_slots).toEqual(SLOTS.map((s) => s.model_id));
    }
  });

  test("the quick result renders the answer as Markdown, its sources, the caveat and the judge's verdict with reasons", async ({ page }) => {
    await driveToQuickResult(page);
    const quick = page.locator("#result-quick");
    // The answer goes through the markdown renderer: its headings and bold
    // arrive as elements, and no raw marker survives anywhere on the page.
    const answer = quick.locator(".result-quick-answer");
    await expect(answer.locator("h1, h2, h3, h4, h5, h6").first()).toBeVisible();
    await expect(answer.locator("li").first()).toBeVisible();
    await expect(answer.locator("strong").first()).toBeVisible();
    const { offenders, walked } = await rawMarkdownIn(page, "#main-content");
    expect(walked).toBeGreaterThan(0);
    expect(offenders).toEqual([]);
    await expect(quick.locator(".result-quick-attr")).toHaveText("GPT-4o mini · one model, no debate");

    // Sources: the answer's two citations as the shared safe chips.
    const chips = quick.locator(".result-source-chip");
    await expect(chips).toHaveCount(2);
    await expect(chips.first()).toHaveAttribute("href", "https://example.com/a");
    await expect(quick.locator(".result-quick-coverage")).toHaveText("The answer cites 2 sources, including a primary source.");

    await expect(quick.locator(".result-quick-safety")).toHaveText(QUICK_SAFETY_NOTICE);

    // The judge's verdict, in the owner's words, with the app-written reasons.
    const verdict = quick.locator(".result-quick-verdict");
    await expect(verdict).toHaveAttribute("data-level", "well_supported");
    await expect(verdict.locator(".result-quick-verdict-heading")).toHaveText("Judge: Well supported");
    await expect(verdict.locator(".result-quick-reasons li")).toHaveText(QUICK_VERDICT_WELL_SUPPORTED.reasons as string[]);
    await expect(verdict.locator(".result-quick-scores")).toHaveText(
      "Faithfulness 5 out of 5 · Grounding 4 out of 5 · Risk of unsupported claims: low",
    );
    // The sources the judge was shown, as plain text: title and address.
    const checked = verdict.locator(".result-quick-checked li");
    await expect(checked).toHaveCount(2);
    await expect(checked.first()).toHaveText(
      `${QUICK_VERDICT_WELL_SUPPORTED.sources_checked[0].title} — https://example.com/a`,
    );
    await expect(verdict.locator(".result-quick-checked a")).toHaveCount(0);
  });

  test("a quick result shows none of the panel's surfaces; a panel result shows every one of them", async ({ page, context }) => {
    // Positive partner first: each selector IS visible on a panel result
    // (with an evaluation, so the trust score renders too).
    const panelPage = await context.newPage();
    await driveToResult(panelPage, withEvaluation(goldenCompletedResp(), EVAL_CLEAN));
    for (const selector of PANEL_ONLY) {
      await expect(panelPage.locator(selector), `${selector} on a panel result`).toBeVisible();
    }
    await expect(panelPage.locator("#result-verdict .result-ring")).toBeVisible();
    await expect(panelPage.locator("#result-quick")).toBeHidden();

    await driveToQuickResult(page);
    for (const selector of PANEL_ONLY) {
      await expect(page.locator(selector), `${selector} on a quick result`).toBeHidden();
    }
    await expect(page.locator(".result-ring")).toHaveCount(0);
    // RED IF: an agreement figure reaches the quick page (the owner's decision).
    const text = (await page.locator('[data-view="result"]').innerText()).toLowerCase();
    expect(text).not.toContain("opening positions");
    expect(text).not.toContain("carried");
    expect(text).not.toMatch(/models? (agree|aligned)/);
    // Its own partner: the panel page does carry the figure.
    const panelText = (await panelPage.locator("#result-verdict").innerText()).toLowerCase();
    expect(panelText).toContain("carried");
  });

  test("a panel run after a quick one gets its ring, band and debate back", async ({ page }) => {
    await driveToQuickResult(page);
    await expect(page.locator("#result-verdict")).toBeHidden();
    // Later routes win in Playwright, so these answer the second run as a panel.
    await page.route("**/v1/query-runs/estimate", (r) =>
      r.fulfill(json({ ...quickEstimateEnvelope(), cost_estimate: goldenCreateResp().cost_estimate, model_slots: SLOTS })));
    await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => r.fulfill(json(goldenCompletedResp())));
    await page.route(/\/v1\/query-runs$/, (r) =>
      r.request().method() === "POST" ? r.fulfill(json(goldenCreateResp())) : r.continue());
    await page.locator("#result-next-run").click();
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await page.locator("#quick-mode-input").uncheck();
    await page.locator("#run-now").click();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
    await expect(page.locator("#result-trust")).toBeVisible();
    await expect(page.locator("#result-debate")).toBeVisible();
    await expect(page.locator("#result-transcript-link")).toBeVisible();
    await expect(page.locator("#result-quick")).toBeHidden();
  });

  test("Copy and Export have a quick shape with the verdict and no agreement figure", async ({ page }) => {
    await driveToQuickResult(page);
    const { exported, copied } = await exportedAndCopied(page);
    expect(copied).toContain("Quick answer (one model, no debate) from GPT-4o mini:");
    expect(copied).toContain("Judge: Well supported");
    expect(exported).toContain("## Judge: Well supported");
    expect(exported).toContain("## The answer");
    expect(exported).toContain(QUICK_SAFETY_NOTICE);
    // ADR-0129: the claims the judge checked travel with the verdict.
    const firstClaim = QUICK_VERDICT_WELL_SUPPORTED.claims[0];
    expect(copied).toContain(`- "${firstClaim.quote}" — Supported · source 1`);
    expect(exported).toContain("### Claims the judge checked");
    expect(exported).toContain("1 claim the judge named is not shown");
    for (const reason of QUICK_VERDICT_WELL_SUPPORTED.reasons as string[]) {
      expect(exported).toContain(reason);
    }
    // RED IF: either artefact carries an agreement figure.
    for (const text of [copied, exported]) {
      expect(text).not.toContain("Opening positions");
      expect(text).not.toMatch(/\b\d+ of \d+\b/);
    }
  });

  test("the judge's claims show the answer's own sentences as text, each with its support and source", async ({ page }) => {
    // W5, fourth pull request (ADR-0129). The fixture is what
    // build_quick_verdict serves for a judge answer with three real quotes and
    // one it wrote itself (dropped), rebuilt in tests/unit/test_quick_answer_ui.py.
    await driveToQuickResult(page);
    const verdict = page.locator("#result-quick .result-quick-verdict");
    const claims = verdict.locator(".result-quick-claim");
    const expected = QUICK_VERDICT_WELL_SUPPORTED.claims;
    expect(expected.length).toBe(3);
    await expect(claims).toHaveCount(expected.length);
    await expect(verdict.locator(".result-quick-claims-title")).toHaveText("Claims the judge checked");
    await expect(verdict.locator(".result-quick-claim-quote")).toHaveText(expected.map((c) => c.quote));
    await expect(verdict.locator(".result-quick-claim-support")).toHaveText([
      "Supported · source 1",
      "Supported · source 2",
      "No source cited",
    ]);
    await expect(claims.nth(0)).toHaveAttribute("data-support", "supported");
    await expect(claims.nth(2)).toHaveAttribute("data-support", "unsourced");
    // RED IF a quote becomes markup: the quote nodes hold text only.
    await expect(verdict.locator(".result-quick-claim-quote *")).toHaveCount(0);
    // The text shown is text already on the page: every quote is in the
    // rendered answer (whitespace collapsed on both sides).
    const answerText = (await page.locator("#result-quick .result-quick-answer").innerText()).replace(/\s+/g, " ");
    for (const claim of expected) {
      expect(answerText, claim.quote).toContain(claim.quote.replace(/\s+/g, " "));
    }
    // "source N" names a line of the numbered list of sources the judge checked.
    const checkedCount = await verdict.locator(".result-quick-checked li").count();
    for (const claim of expected) {
      if (claim.source !== null) expect(claim.source).toBeLessThanOrEqual(checkedCount);
    }
    await expect(verdict.locator(".result-quick-claims-dropped")).toHaveText(
      "1 claim the judge named is not shown, because it did not pass the app's checks for showing a quote exactly as the answer shows it.",
    );
    await expect(verdict.locator(".result-quick-claims-note")).toHaveText(
      "The judge saw each source's title and address, not the page itself.",
    );
    const { offenders, walked } = await rawMarkdownIn(page, "#main-content");
    expect(walked).toBeGreaterThan(0);
    expect(offenders).toEqual([]);
  });

  test("a served contradicted claim reads 'Contradicted' and caps the verdict at partly supported", async ({ page }) => {
    await driveToQuickResult(page, { ...goldenQuickResp(), quick_verdict: QUICK_VERDICT_CONTRADICTED });
    const verdict = page.locator("#result-quick .result-quick-verdict");
    await expect(verdict.locator(".result-quick-verdict-heading")).toHaveText("Judge: Partly supported");
    await expect(verdict.locator(".result-quick-claim")).toHaveCount(1);
    await expect(verdict.locator(".result-quick-claim")).toHaveAttribute("data-support", "contradicted");
    await expect(verdict.locator(".result-quick-claim-support")).toHaveText("Contradicted · source 2");
    // Nothing was dropped, so no dropped line (its partner is the test above).
    await expect(verdict.locator(".result-quick-claims-dropped")).toHaveCount(0);
  });

  test("a simulated quick answer reads 'Not checked' and a one-model degraded banner", async ({ page }) => {
    await driveToQuickResult(page, goldenQuickRespSimulated());
    const verdict = page.locator("#result-quick .result-quick-verdict");
    await expect(verdict.locator(".result-quick-verdict-heading")).toHaveText("Judge: Not checked");
    await expect(verdict.locator(".result-quick-unchecked")).toHaveText(
      "No judge verdict is available for this answer, so nothing on this page has been checked against its sources.",
    );
    await expect(verdict.locator(".result-quick-reasons li")).toHaveCount(0);
    // ADR-0129: no verdict, no claims and no claim lines (partner: the
    // claims test above renders them on a checked answer).
    await expect(verdict.locator(".result-quick-claims")).toHaveCount(0);
    await expect(verdict.locator(".result-quick-claims-dropped")).toHaveCount(0);
    await expect(verdict.locator(".result-quick-claims-note")).toHaveCount(0);
    await expect(page.locator("#result-quick .result-quick-safety")).toBeHidden();
    await expect(page.locator("#result-degraded")).toBeVisible();
    await expect(page.locator("#result-degraded-title")).toHaveText("Simulated result — not from a real model");
    await expect(page.locator("#result-degraded-message")).not.toContainText("1 models");
    await expect(page.locator("#result-quick .result-quick-coverage")).toHaveText(
      "The answer cites no primary source.",
    );
  });

  test("the cost gate names a quick run's shape; the live view shows one stage and no debate", async ({ page }) => {
    await boot(page);
    await page.route("**/v1/query-runs/estimate", (r) => r.fulfill(json(quickEstimateEnvelope())));
    await page.route("**/v1/query-runs/warnings", (r) => r.fulfill(json({ warnings: [] })));
    await page.route("**/v1/query-runs/active", (r) => r.fulfill(json({ query_run_id: null })));
    await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) =>
      r.fulfill(json({ ...goldenQuickCreateResp(), status: "initial_answers_running", elapsed_time_ms: 1200,
        failed_steps: [], missing_steps: [], partial_failure_notice: null, provider_failure_notices: [],
        result: { model_answers: [], debate_outputs: [], final_synthesis: null, agreement: null, position_movements: [], safety_notice: null },
        result_generated_at_utc: "2026-09-25T12:00:00Z", demo_mode: false, live_count: 0, local_count: 0 })));
    await page.route(/\/v1\/query-runs$/, (r) =>
      r.request().method() === "POST" ? r.fulfill(json(goldenQuickCreateResp())) : r.continue());
    await page.locator("#quick-mode-input").check();
    await page.getByRole("textbox").first().fill("What is the capital of Australia and why was it chosen?");
    await page.getByRole("button", { name: /see the estimate|estimate cost/i }).click();
    await expect(page.locator("#gate-confirm")).toBeVisible({ timeout: 15000 });
    await expect(page.locator("#cost-gate-question-meta")).toHaveText(
      "1 model · no debate · no judge configured · sourced answer where search succeeds",
    );
    await expect(page.locator("#cost-by-stage")).toContainText("The answer");
    await expect(page.locator("#cost-by-stage")).not.toContainText("× 4");
    await page.locator("#gate-confirm").click();
    await expect(page.locator('[data-view="live-run"]')).toBeVisible({ timeout: 15000 });
    await expect(page.locator("#live-stage-strip .live-stage")).toHaveCount(1);
    await expect(page.locator("#live-debate")).toBeHidden();
    await expect(page.locator(".live-debate-caption")).toBeHidden();
  });
});
