import { test, expect, Page } from "@playwright/test";
import {
  boot,
  goldenCreateResp,
  goldenCompletedResp,
  withEvaluation,
  goldenEvaluation,
  EVAL_ALL_VARIANTS,
  EVAL_CLEAN,
  EVAL_UNKNOWN_GROUNDING_REFUSAL,
  EVAL_VERIFIED_HIGH,
  EVAL_S2_SHAPED,
} from "../../fixtures/golden-run";
import { readTokens, scanSubtreeForGreen } from "../../fixtures/tokens";

/**
 * FR-016 (S3) — the trust-score surface rendering contract (BLOCKING).
 *
 * The surface renders the S2 evaluation to a user under a deliberately BLUNT
 * contract (D-2): ZERO digits and ZERO advisory-label words, so no arithmetic
 * and no engine label can leak as a confident claim. A blunt rule a test can
 * check beats a nuanced one a reviewer must remember.
 *
 * Anti-vacuity: the absence-shaped assertions ("no digits", "no green") are
 * trivially satisfied by an EMPTY surface, so each is paired with a
 * discriminating POSITIVE — two fixtures in the same family must produce
 * DIFFERENT state lines and DIFFERENT why-line sets, and each variant's surface
 * must be visible with non-empty text.
 */

const SURFACE = "#result-trust-score";

// R2 — the confident-label words (plan D-2, table R2).
const LABEL_WORDS =
  /\bfaithful\b|\bunfaithful\b|\bpartial\b|low risk|medium risk|high risk|hallucination|confiden|accurac|trustworth|reliab|\bscore\b|\bgrade\b/i;

// R3 — raw signal identifiers (the seven LAYER_A_WEIGHTS keys + the two
// unverifiable-marker fields). None may appear in the surface innerText.
const SIGNAL_IDENTIFIERS = [
  "citation_marker_grounding",
  "live_ratio",
  "citation_coverage_ratio",
  "completeness",
  "disagreement_integrity",
  "uncertainty_surfaced",
  "decision_support_framing_present",
  "unverifiable_marker_count",
  "unverifiable_marker_ratio",
];

// R4 — the standing disclosure literal (must match app.js exactly).
const DISCLOSURE =
  "Not verified — these are automated structural checks, not a fact-check.";

// P1 / FR-015 — the VERIFIED disclosure literal (must match app.js exactly).
const VERIFIED_DISCLOSURE =
  "Citation support was checked by an independent judge model — an automated review, not a human fact-check.";

const VIEWPORTS = [375, 768, 1440] as const;
const THEMES = ["light", "dark"] as const;

const fulfil = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const costEstimateEnvelope = () => ({
  correlation_id: "corr-trust-est",
  cost_estimate: goldenCreateResp().cost_estimate,
  model_slots: goldenCreateResp().model_slots,
  reasons: [],
});

/** Drive composer → run → result with a specific evaluation body injected.
 *  Pass the sentinel "__omit__" to leave the `evaluation` key absent entirely. */
async function driveWithEval(page: Page, ev: unknown) {
  await boot(page);
  await Promise.all([
    page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(costEstimateEnvelope()))),
    page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
    page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
  ]);
  const completed =
    ev === "__omit__" ? goldenCompletedResp() : withEvaluation(goldenCompletedResp(), ev);
  await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => r.fulfill(fulfil(completed)));
  await page.route(/\/v1\/query-runs$/, (r) =>
    r.request().method() === "POST" ? r.fulfill(fulfil(goldenCreateResp())) : r.continue(),
  );
  await page.getByRole("textbox").first().fill("What are the key metrics for measuring SaaS retention?");
  await page.locator("#run-now").click();
  await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
}

async function setTheme(page: Page, theme: "light" | "dark") {
  await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
}

async function surfaceText(page: Page): Promise<string> {
  return page.locator(SURFACE).innerText();
}

test.describe("trust-score invariants (FR-016)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  // ---- R1–R4 + non-emptiness, across all six fixture variants ----
  for (const { name, ev } of EVAL_ALL_VARIANTS) {
    test(`${name}: renders, non-empty, and honours R1–R4`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 1200 });
      await driveWithEval(page, ev);

      const surface = page.locator(SURFACE);
      await expect(surface, `${name}: the surface must be visible`).toBeVisible();
      const text = await surfaceText(page);
      expect(text.trim().length, `${name}: the surface must not be empty`).toBeGreaterThan(0);

      // R1 — no digits anywhere.
      expect(text, `${name}: R1 — no digits`).not.toMatch(/\d/);
      // R2 — no confident label words.
      expect(text, `${name}: R2 — no label words`).not.toMatch(LABEL_WORDS);
      // R3 — no raw signal identifiers.
      for (const id of SIGNAL_IDENTIFIERS) {
        expect(text, `${name}: R3 — identifier "${id}" must not appear`).not.toContain(id);
      }
      // R4 — the standing disclosure literal is present.
      expect(text, `${name}: R4 — standing disclosure`).toContain(DISCLOSURE);
    });
  }

  // ---- Discriminating positive: distinct variants → distinct surfaces ----
  // Kills the `box.textContent = "—"` mutation: an empty/constant surface makes
  // these equal.
  test("distinct variants produce DIFFERENT state lines and why-sets", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1200 });

    await driveWithEval(page, EVAL_CLEAN);
    const cleanState = await page.locator(`${SURFACE} .result-trust-score-state`).innerText();
    const cleanWhy = await page.locator(`${SURFACE} .result-trust-score-why-item`).allInnerTexts();

    await driveWithEval(page, EVAL_UNKNOWN_GROUNDING_REFUSAL);
    const refusalState = await page.locator(`${SURFACE} .result-trust-score-state`).innerText();
    const refusalWhy = await page.locator(`${SURFACE} .result-trust-score-why-item`).allInnerTexts();

    expect(cleanState, "a clean run and a refusal must not read identically").not.toEqual(refusalState);
    expect(cleanWhy.sort(), "their why-line sets must differ").not.toEqual(refusalWhy.sort());
    // Both must be substantive, not empty (guards a vacuous 'different' via empty).
    expect(cleanState.length).toBeGreaterThan(0);
    expect(refusalState.length).toBeGreaterThan(0);
  });

  // ---- R5: the GREEN RULE, in both themes at every viewport ----
  for (const theme of THEMES) {
    for (const width of VIEWPORTS) {
      test(`GREEN RULE — no green paint anywhere [${theme} @ ${width}]`, async ({ page }) => {
        await page.setViewportSize({ width, height: 1200 });
        await driveWithEval(page, EVAL_CLEAN);
        await setTheme(page, theme);
        const violations = await scanSubtreeForGreen(page, SURFACE);
        expect(violations, `green paint found:\n${violations.join("\n")}`).toEqual([]);

        // Belt-and-braces (D-6.5): no consensus/agreement structural markers.
        const structural = await page.locator(SURFACE).evaluate((root) => {
          const bad: string[] = [];
          const all = [root, ...Array.from(root.querySelectorAll("*"))];
          for (const el of all) {
            if (el.hasAttribute("data-consensus")) bad.push("data-consensus");
            if (el.getAttribute("data-accent") === "agreement") bad.push('data-accent="agreement"');
            if (/consensus|agreement/i.test(el.getAttribute("class") || "")) bad.push(`class ${el.getAttribute("class")}`);
          }
          return bad;
        });
        expect(structural, "no consensus/agreement markers may appear on this surface").toEqual([]);
      });
    }
  }

  // ---- R6: no ARIA value-widget lie ----
  test("no ARIA value-widget lie", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1200 });
    await driveWithEval(page, EVAL_CLEAN);
    const bad = await page.locator(SURFACE).evaluate((root) => {
      const out: string[] = [];
      const all = [root, ...Array.from(root.querySelectorAll("*"))];
      for (const el of all) {
        const role = el.getAttribute("role");
        if (role && ["meter", "progressbar", "slider"].includes(role)) out.push(`role=${role}`);
        if (el.hasAttribute("aria-valuenow")) out.push("aria-valuenow");
        if (el.hasAttribute("aria-valuetext")) out.push("aria-valuetext");
      }
      return out;
    });
    expect(bad, "the surface must not claim a value-widget role or value").toEqual([]);
  });

  // ---- R7: computed style is token-sourced (never a retyped literal) ----
  test("state-line colour resolves from the --ink token, not a literal", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1200 });
    await driveWithEval(page, EVAL_CLEAN);
    // Compare the state line's computed colour to a probe painted with var(--ink).
    const { actual, expected } = await page.evaluate((sel) => {
      const state = document.querySelector(`${sel} .result-trust-score-state`) as HTMLElement;
      const probe = document.createElement("span");
      probe.style.color = "var(--ink)";
      document.body.appendChild(probe);
      const expected = getComputedStyle(probe).color;
      probe.remove();
      return { actual: getComputedStyle(state).color, expected };
    }, SURFACE);
    expect(actual, "state line must paint from --ink").toEqual(expected);
    // Token source is readable (guards a hard-coded reviewer literal upstream).
    const tokens = await readTokens(page, ["--ink", "--warning", "--info"]);
    expect(tokens["--ink"].length).toBeGreaterThan(0);
  });

  // ---- R8 + R9: no overlap and no clipping/truncation ----
  for (const width of VIEWPORTS) {
    test(`no overlap and no clipping [@ ${width}]`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1400 });
      await driveWithEval(page, EVAL_UNKNOWN_GROUNDING_REFUSAL);

      // R9 — the surface neither clips nor truncates its own content.
      const clip = await page.locator(SURFACE).evaluate((n) => ({
        sw: n.scrollWidth,
        cw: n.clientWidth,
        sh: n.scrollHeight,
        ch: n.clientHeight,
      }));
      expect(clip.sw, `@${width}: horizontal clip`).toBeLessThanOrEqual(clip.cw + 1);
      expect(clip.sh, `@${width}: vertical clip`).toBeLessThanOrEqual(clip.ch + 1);

      // R8 — the three result regions must not overlap each other.
      const boxes = await page.evaluate(() => {
        const ids = ["result-verdict", "result-trust", "result-trust-score"];
        return ids
          .map((id) => document.getElementById(id))
          .filter((el): el is HTMLElement => !!el && !(el as HTMLElement).hidden)
          .map((el) => {
            const r = el.getBoundingClientRect();
            return { id: el.id, x: r.x, y: r.y, w: r.width, h: r.height };
          })
          .filter((b) => b.w > 0 && b.h > 0);
      });
      for (let i = 0; i < boxes.length; i++) {
        for (let j = i + 1; j < boxes.length; j++) {
          const a = boxes[i];
          const b = boxes[j];
          const ox = Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x));
          const oy = Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
          expect(ox * oy, `@${width}: ${a.id} overlaps ${b.id}`).toBeLessThanOrEqual(1);
        }
      }
    });
  }

  // ---- R10: an absent / null / malformed evaluation renders NOTHING ----
  test("an absent evaluation renders nothing", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1200 });
    for (const ev of ["__omit__", null, {}]) {
      await driveWithEval(page, ev);
      await expect(page.locator(SURFACE), `evaluation=${JSON.stringify(ev)}`).toBeHidden();
      const main = await page.locator("#main-content").innerText();
      // The surface's own vocabulary must not appear from this surface.
      const surfaceInnerText = await page.locator(SURFACE).innerText().catch(() => "");
      expect(surfaceInnerText.trim()).toEqual("");
      expect(main).not.toContain(DISCLOSURE);
    }
  });

  // ---- R11: the fail-closed case degrades (no label_confidence key) ----
  test("a label_confidence-less (s2-shaped) payload fails CLOSED to indeterminate", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1200 });
    await driveWithEval(page, EVAL_S2_SHAPED);
    await expect(page.locator(SURFACE)).toBeVisible();
    await expect(page.locator(`${SURFACE} .result-trust-score-state`)).toHaveText(
      "Some citations on this run point to pages that were never retrieved here, so the structural checks could not be applied.",
    );
  });

  // ---- D-12: the reset is UNCONDITIONAL across same-page re-renders ----
  // renderResult has three call sites and the surface must reset BEFORE the
  // `evaluation == null` early return. R10 above re-navigates each case, so it
  // cannot catch a stale band; this drives TWO runs on ONE page load (via the
  // result view's "Review & run" affordance → composer → run again). If the
  // reset were moved below the early return, run 1's visible band would survive
  // run 2 (which has no evaluation). It must be cleared.
  test("a second same-page run with no evaluation clears the prior visible band", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1200 });
    await boot(page);
    let phaseTwo = false;
    await Promise.all([
      page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(costEstimateEnvelope()))),
      page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
      page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
    ]);
    await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) =>
      r.fulfill(fulfil(phaseTwo ? goldenCompletedResp() : withEvaluation(goldenCompletedResp(), EVAL_CLEAN))),
    );
    await page.route(/\/v1\/query-runs$/, (r) =>
      r.request().method() === "POST" ? r.fulfill(fulfil(goldenCreateResp())) : r.continue(),
    );

    // Run 1 — reportable evaluation ⇒ the surface is visible + populated.
    await page.getByRole("textbox").first().fill("First question about SaaS retention metrics?");
    await page.locator("#run-now").click();
    await expect(page.locator(SURFACE)).toBeVisible();
    expect((await page.locator(SURFACE).innerText()).trim().length).toBeGreaterThan(0);

    // Return to the composer and run AGAIN on the SAME page load — no evaluation.
    phaseTwo = true;
    await page.locator("#result-next-run").click();
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await page.getByRole("textbox").first().fill("A second, entirely different question?");
    await page.locator("#run-now").click();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });

    await expect(page.locator(SURFACE)).toBeHidden();
    expect(await page.locator(SURFACE).innerText().catch(() => "")).toEqual("");
  });

  // ---- Coverage for the `refused` state branch (unreachable by the 6 shared
  // variants: the only refusal fixture also has null grounding, so `no-marker`
  // wins there). A reportable, grounded, refusing run reaches `refused`. ----
  test("a reportable + grounded + refusing run renders the refused state", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1200 });
    const ev = goldenEvaluation({ signals: { refusal_detected: true, run_wholly_refused: true } });
    await driveWithEval(page, ev);
    await expect(page.locator(SURFACE)).toHaveAttribute("data-state", "refused");
    const text = await page.locator(SURFACE).innerText();
    expect(text).toMatch(/declined|Nothing was asserted/i);
    expect(text).not.toMatch(/\d/);
    expect(text).not.toMatch(LABEL_WORDS);
  });

  // ---- P1 / FR-015: the VERIFIED branch --------------------------------
  //
  // EVAL_VERIFIED_HIGH is the ONE shape whose digits are sanctioned: a REAL
  // Layer-B judge verified citation support, so trust.score renders. The
  // zero-digit contract R1 stays binding on every unverified shape — the
  // tamper loop below proves each near-miss falls back to it (both
  // directions of the loosened gate).
  test("EVAL_VERIFIED_HIGH renders the numeric score, band, and verified disclosure", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 1200 });
    await driveWithEval(page, EVAL_VERIFIED_HIGH);

    const surface = page.locator(SURFACE);
    await expect(surface).toBeVisible();
    await expect(surface).toHaveAttribute("data-state", "verified");
    await expect(surface).toHaveAttribute("data-band", "high");

    // The score renders EXACTLY as served — no rounding, no re-derivation.
    await expect(page.locator(`${SURFACE} .result-trust-score-number`)).toHaveText(
      String(EVAL_VERIFIED_HIGH.trust.score),
    );
    const text = await surfaceText(page);
    expect(text).toContain(VERIFIED_DISCLOSURE);
    expect(text, "the unverified disclosure must NOT appear on a verified run").not.toContain(
      DISCLOSURE,
    );
    expect(text).toContain("of 100");
    expect(text).toContain("high trust");
    // Only the sanctioned score reaches the surface — never the diagnostic
    // composite or any contribution arithmetic.
    expect(text).not.toContain("91.75");
    expect(text).not.toContain("24");
    expect(text).not.toContain("12.75");
    // R3 still binds: raw signal identifiers stay off the surface.
    for (const id of SIGNAL_IDENTIFIERS) {
      expect(text, `verified: R3 — identifier "${id}" must not appear`).not.toContain(id);
    }
    // The reasons-to-doubt list still renders (grounding 0.8 / coverage 0.85).
    const whys = await page.locator(`${SURFACE} .result-trust-score-why-item`).allInnerTexts();
    expect(whys.length).toBeGreaterThan(0);
  });

  test("GREEN RULE holds on the verified surface too", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1200 });
    await driveWithEval(page, EVAL_VERIFIED_HIGH);
    const violations = await scanSubtreeForGreen(page, SURFACE);
    expect(violations, "no green paint on a verified surface (green = consensus only)").toEqual(
      [],
    );
  });

  // Every near-miss of the verified shape falls back to the zero-digit
  // unverified treatment — the guard fails CLOSED.
  const TAMPERED: { label: string; mutate: (ev: any) => void; wantState?: string }[] = [
    { label: "score null", mutate: (ev) => (ev.trust.score = null) },
    { label: "score out of range", mutate: (ev) => (ev.trust.score = 250) },
    { label: "score non-integer", mutate: (ev) => (ev.trust.score = 91.75) },
    { label: "band unverified", mutate: (ev) => (ev.trust.band = "unverified") },
    { label: "band unknown", mutate: (ev) => (ev.trust.band = "certified") },
    { label: "support_verified false", mutate: (ev) => (ev.trust.support_verified = false) },
    { label: "support_verified truthy-but-not-true", mutate: (ev) => (ev.trust.support_verified = 1) },
    {
      label: "laundered provenance (label_confidence indeterminate)",
      mutate: (ev) => (ev.label_confidence = "indeterminate"),
      wantState: "indeterminate",
    },
  ];
  for (const { label, mutate, wantState } of TAMPERED) {
    test(`tampered verified shape falls back to zero digits: ${label}`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 1200 });
      const ev = JSON.parse(JSON.stringify(EVAL_VERIFIED_HIGH));
      mutate(ev);
      await driveWithEval(page, ev);
      const surface = page.locator(SURFACE);
      await expect(surface).toBeVisible();
      const state = await surface.getAttribute("data-state");
      expect(state, `${label}: must not render the verified treatment`).not.toEqual("verified");
      if (wantState) expect(state).toEqual(wantState);
      const text = await surfaceText(page);
      expect(text, `${label}: R1 — no digits`).not.toMatch(/\d/);
      expect(text, `${label}: the unverified disclosure returns`).toContain(DISCLOSURE);
    });
  }
});
