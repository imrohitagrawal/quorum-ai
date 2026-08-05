import { test, expect, Page } from "@playwright/test";
import { boot, goldenCreateResp, goldenCompletedResp } from "../../fixtures/golden-run";

/**
 * Issue #193 — the Source support card must state what its percentage is a
 * share OF.
 *
 * The card rendered a bare `"75%"`. This panel is FOUR answers: "3 of 4" and
 * "15 of 20" are both 75% and are very different claims.
 *
 * #171's rule, quoted in full from issue #193 so the gap is visible: "every
 * user-facing trust number must state its denominator AND WHAT IT EXCLUDED —
 * 'coverage 100% (4 of 4 answers, 0 excluded)', never a bare '100%'." This
 * change builds the denominator half only. The exclusion count is deliberately
 * NOT built: it is not a field on `CitationCoverage` (it would be the slot count
 * minus `answer_count`, and the slot count lives on a different object), and a
 * third number on this card is the density the issue's own reporter objected
 * to. See docs/adr/0008 — that is a decision, and a reversible one.
 *
 * WHERE the counts go is the whole design question, and the first attempt got
 * it wrong. It put them on the VALUE line as `75% (3 of 4 answers)` — directly
 * beside the Agreement card, whose value is literally `3 of 4` (app.js, the
 * `accent: "agreement"` card). Two cards in one 3-up grid, both headlining
 * "3 of 4", measuring completely unrelated things: how many models AGREED
 * versus how many answers CITED A SOURCE. The value line also already carries
 * `· N sources cited`, so `75% (3 of 4 answers) · 5 sources cited` invites
 * reading the 75% against the 5.
 *
 * So the counts go in the CAPTION, as a sentence that names its own subject.
 * The caption already existed and said the same thing without the numbers
 * ("Share of the answers that came back carrying a primary source."), so this
 * replaces a generic sentence rather than adding a fourth number to the card.
 * The value line is untouched: no new width in a 3-up grid, no bare fraction
 * next to the Agreement card's bare fraction.
 *
 * Nothing is computed here. `answer_count` and `sourced_answer_count` are
 * already REQUIRED fields on the served payload (providers.py, CitationCoverage)
 * and the ratio the card already prints is derived from them. The UI was
 * discarding them.
 *
 * INPUT-CLASS TABLE for the caption decision — 18 rows, each a test. The file
 * holds 20 tests: the other two are the anti-collision pair at the bottom, which
 * assert where the counts must NOT appear and are not input classes.
 * The fallback is the pre-existing generic caption, which states the meaning
 * without numbers — always safe, never fabricated.
 *
 *  #  class                     answer_count  sourced_count  caption
 *  1  normal, plural            4             3              "3 of 4 answers came back…"
 *  2  singular denominator      1             1              "1 of 1 answer came back…"   (no "answers")
 *  3  genuine zero numerator    4             0              "0 of 4 answers came back…"  (a real 0 is reported)
 *  4  fully sourced             4             4              "4 of 4 answers came back…"
 *  5  zero denominator          0             0              fallback — never "0 of 0"
 *  6  counts absent             null          null           fallback
 * 7a  fractional                4.5           3              fallback — never "4.5"
 * 7b  negative                  -1            -1             fallback — never "of -1"
 * 7c  empty-string numerator    4             ""             fallback — never "0 of 4"  (Number("") === 0)
 * 7d  whitespace numerator      4             "   "          fallback — never "0 of 4"
 * 7e  unsafe integer            1e21          3              fallback — never "1e+21"
 *  8  numerator > denominator   4             5              fallback — incoherent, never printed
 *  9  citation_coverage absent  —             —              fallback
 *
 * And the caption must AGREE with the percentage printed above it, so the ratio
 * is an input to this decision too (these vary it independently of the counts,
 * which the rows above never do):
 *
 * 10a  ratio absent             4  / 3  ratio ""      fallback — value line shows "—"
 * 10b  ratio out of range       4  / 3  ratio "1.6"   fallback — value line shows "—"
 * 10c  ratio contradicts counts 4  / 3  ratio "0.10"  fallback — never "3 of 4" under "10%"
 * 10d  ratio agrees to 2dp      3  / 1  ratio "0.33"  "1 of 3 answers came back…"
 * 10e  absent ratio, ZERO num.  4  / 0  ratio ""      fallback — never "0 of 4" under "—"
 *
 * Row 10 exists because a reviewer found the card could print "—" (we have no
 * measurement) directly above "3 of 4 answers came back carrying a primary
 * source" (from which the reader recovers the very percentage the card just
 * refused to state). ``CitationCoverage`` validates ``sourced <= answer`` but
 * never checks the ratio against the counts, so no server-side guard covers it.
 *
 * Row 8 is not reachable from a well-behaved server (CitationCoverage rejects
 * it), which is exactly why the client must not trust it — but see that test's
 * own comment: the guard that ACTUALLY catches it is the row-10 agreement
 * check, not the `sourced > total` clause, which no input can isolate.
 *
 * WHAT TURNS EACH TEST RED. `sourceSupportCaption` is a top-level function in
 * `src/product_app/static/app.js` (NOT inside `renderTrustTriangle`; it is
 * called from the `accent: "source"` card there).
 *
 *   rows 1-4, 10d   make its final `return` yield SOURCE_SUPPORT_CAPTION_FALLBACK
 *   row 5           delete `total === 0` from the guard
 *   rows 6, 9       make `countOrNull` / the `!coverage` check return a value
 *   rows 7a, 7e     `Number.isSafeInteger` -> `Number.isInteger`
 *   row 7b          drop `&& n >= 0`
 *   rows 7c, 7d     delete `if (trimmed === "") return null;`
 *   rows 10a/10b/10e delete the `ratio === null` gate
 *   row 10c         delete the COVERAGE_RATIO_TOLERANCE comparison
 *   row 8           NOTHING in `sourceSupportCaption` isolates it — see its comment
 *   the two anti-collision tests: put the counts back on the value line
 *
 * Every line above except row 8's was RUN, `cp` aside and restored from the
 * copy, and confirmed red. Row 8's is stated as unprovable rather than claimed.
 */

const CARD = '#result-trust .result-trust-card[data-accent="source"]';
const CAPTION = `${CARD} .result-trust-caption`;

/** The pre-existing numberless caption, used whenever counts are unusable. */
const FALLBACK = "Share of the answers that came back carrying a primary source.";

const fulfil = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

/** Drive composer -> run -> result, optionally overriding citation_coverage. */
async function driveToResult(page: Page, coverage?: unknown) {
  await boot(page);
  await Promise.all([
    page.route("**/v1/query-runs/estimate", (r) =>
      r.fulfill(
        fulfil({
          correlation_id: "corr-193",
          cost_estimate: goldenCreateResp().cost_estimate,
          model_slots: goldenCreateResp().model_slots,
          reasons: [],
        }),
      ),
    ),
    page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
    page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
  ]);

  const completed = goldenCompletedResp() as Record<string, any>;
  if (coverage !== undefined) {
    // NOTE the nesting: `final_synthesis` lives under `result`, not at the top
    // level. Writing `completed.final_synthesis` instead silently leaves the
    // default fixture in place, and every override below would then assert
    // against the golden 4/3 values while claiming to test another shape.
    completed.result.final_synthesis = {
      ...completed.result.final_synthesis,
      citation_coverage: coverage,
    };
  }
  await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => r.fulfill(fulfil(completed)));
  await page.route(/\/v1\/query-runs$/, (r) =>
    r.request().method() === "POST" ? r.fulfill(fulfil(goldenCreateResp())) : r.continue(),
  );

  await page
    .getByRole("textbox")
    .first()
    .fill("What are the key metrics for measuring SaaS retention?");
  await page.locator("#run-now").click();
  await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
}

/** Build a citation_coverage payload; ratio defaults to a coherent one. */
const cov = (answer_count: unknown, sourced_answer_count: unknown, ratio = "0.75") => ({
  answer_count,
  sourced_answer_count,
  sourced_answer_ratio: ratio,
  target_ratio: "0.80",
  target_met: false,
});

test.describe("the Source support card names its denominator (#193)", () => {
  // ---- rows 1-4: the counts are printed, as a sentence -------------------

  test("row 1 — the golden run's caption states the counts", async ({ page }) => {
    await driveToResult(page); // golden fixture is CC_BELOW: 4 answers, 3 sourced
    await expect(page.locator(CARD)).toBeVisible();
    await expect(page.locator(CAPTION)).toHaveText(
      "3 of 4 answers came back carrying a primary source.",
    );
  });

  test("row 2 — a single-answer panel is not pluralised", async ({ page }) => {
    // "1 of 1 answers" reads like a rounding artefact and undermines the very
    // number it exists to qualify.
    await driveToResult(page, cov(1, 1, "1.00"));
    await expect(page.locator(CAPTION)).toHaveText(
      "1 of 1 answer came back carrying a primary source.",
    );
  });

  test("row 3 — a genuine zero numerator IS reported", async ({ page }) => {
    // The other direction of the WP-B/F-18 guard: refusing to fabricate a
    // number from missing data must not also suppress a real measured zero.
    await driveToResult(page, cov(4, 0, "0.00"));
    await expect(page.locator(CAPTION)).toHaveText(
      "0 of 4 answers came back carrying a primary source.",
    );
  });

  test("row 4 — a fully sourced panel reads 4 of 4", async ({ page }) => {
    await driveToResult(page, cov(4, 4, "1.00"));
    await expect(page.locator(CAPTION)).toHaveText(
      "4 of 4 answers came back carrying a primary source.",
    );
  });

  // ---- rows 5-9: the counts are refused, and nothing is invented ---------

  test("row 5 — a zero denominator falls back, never '0 of 0'", async ({ page }) => {
    await driveToResult(page, cov(0, 0, "0.00"));
    // Satisfies the negative-assertion guard, which flags the `not.toContainText`
    // below. NOTE the honest reason: the guard does not recognise `toHaveText` as
    // a liveness partner, and CAPTION is a DESCENDANT of CARD, so the caption
    // assertion already could not pass over a missing card. This line is
    // mechanical appeasement, not the closing of a real hole — measured by
    // rendering with the card absent (CARD 0, CAPTION 0).
    await expect(page.locator(CARD)).toBeVisible();
    await expect(page.locator(CAPTION)).toHaveText(FALLBACK);
    await expect(page.locator(CARD)).not.toContainText("of 0 answer");
  });

  test("row 6 — absent counts fall back", async ({ page }) => {
    await driveToResult(page, cov(null, null));
    await expect(page.locator(CAPTION)).toHaveText(FALLBACK);
  });

  // Row 7 is split by which GUARD each input isolates. The first draft used a
  // single `(-1, 2.5)` case and it proved nothing about `countOrNull`: the
  // incoherence guard catches it first (2.5 > -1), so the test stayed green
  // with the integer check deleted. Each case below is chosen so that ONLY
  // `countOrNull` can reject it — verified by mutating `countOrNull` and
  // watching each one go red. The `(-1, 2.5)` case was removed rather than
  // kept: it survived every mutation of `countOrNull`, and row 8 already owns
  // the coherence guard it was actually exercising.
  //
  // Each row also carries a RATIO chosen to AGREE with the counts a permissive
  // `countOrNull` would produce. Without that the row-10 agreement check
  // rejects the input first and the row proves nothing about `countOrNull`
  // again — the same masking bug one layer down, found by re-running the
  // mutations after row 10 was added rather than by assuming they still bit.
  for (const [label, total, sourced, ratio, forbidden] of [
    ["fractional", 4.5, 3, "0.67", "4.5"],
    // (-1, -1), not (-1, 0): the latter trips `sourced > total` (0 > -1) and so
    // never reaches the non-negativity check it was meant to isolate.
    ["negative", -1, -1, "1.00", "of -1"],
    ["empty string numerator", 4, "", "0.00", "0 of 4"],
    ["whitespace numerator", 4, "   ", "0.00", "0 of 4"],
    ["unsafe integer", 1e21, 3, "0.00", "1e+21"],
  ] as [string, unknown, unknown, string, string][]) {
    test(`row 7 — ${label} counts are never printed`, async ({ page }) => {
      // The empty/whitespace cases are the sharp ones: Number("") is a finite,
      // non-negative INTEGER 0, so an integer check alone renders "0 of 4
      // answers came back carrying a primary source" — a measured-looking zero
      // invented from a missing field, on the trust panel.
      await driveToResult(page, cov(total, sourced, ratio));
      // Satisfies the negative-assertion guard; see row 5 for why this is
      // mechanical rather than a real vacuity fix.
      await expect(page.locator(CARD)).toBeVisible();
      await expect(page.locator(CAPTION)).toHaveText(FALLBACK);
      await expect(page.locator(CARD)).not.toContainText(forbidden);
    });
  }

  test("row 8 — a numerator above the denominator is refused", async ({ page }) => {
    // CitationCoverage rejects this server-side. The client must not print it
    // either: the validator is the only thing between the payload and this
    // sentence, and "5 of 4 answers" is a claim no data can support.
    //
    // WHICH GUARD ACTUALLY CATCHES THIS: the agreement check, not the
    // `sourced > total` clause. 5/4 = 1.25 and the served ratio cannot exceed 1
    // (`coverageRatioOrNull` rejects out-of-unit-range), so the two can never
    // agree. Deleting `sourced > total` leaves this test GREEN — measured, not
    // assumed. The clause is kept as defence in depth and is documented in
    // app.js as unprovable while the agreement check stands. This test asserts
    // the OUTCOME (an incoherent pair is never printed), which is the contract
    // that matters; it does not pin which line delivers it.
    await driveToResult(page, cov(4, 5, "1.00"));
    // Satisfies the negative-assertion guard; see row 5 for why this is
    // mechanical rather than a real vacuity fix.
    await expect(page.locator(CARD)).toBeVisible();
    await expect(page.locator(CAPTION)).toHaveText(FALLBACK);
    await expect(page.locator(CARD)).not.toContainText("5 of 4");
  });

  test("row 9 — an absent citation_coverage falls back", async ({ page }) => {
    await driveToResult(page, null);
    await expect(page.locator(CAPTION)).toHaveText(FALLBACK);
  });

  // ---- row 10: the caption must agree with the percentage above it -------

  for (const [label, ratio] of [
    ["absent", ""],
    ["out of range", "1.6"],
  ] as [string, unknown][]) {
    test(`row 10 — a ${label} ratio suppresses the counts, not just the percentage`, async ({
      page,
    }) => {
      // The value line renders "—" because, per WP-B/F-18, suppressing the
      // figure is the honest failure mode. A caption that then says "3 of 4"
      // hands the reader back the 75% the card just refused to claim.
      await driveToResult(page, cov(4, 3, ratio));
      const card = page.locator(CARD);
      await expect(card).toBeVisible();
      await expect(page.locator(`${CARD} .result-trust-value`)).toContainText("—");
      await expect(page.locator(CAPTION)).toHaveText(FALLBACK);
      await expect(card).not.toContainText("3 of 4");
    });
  }

  test("row 10e — an absent ratio suppresses a ZERO numerator too", async ({ page }) => {
    // Isolates the usable-ratio gate, which rows 10a/10b do NOT: with counts
    // 4/3 the agreement check catches an absent ratio on its own (null coerces
    // to 0 in arithmetic, and |0 - 0.75| > tolerance). With a zero numerator
    // 0/4 = 0, so that coercion AGREES and the counts would print under a "—".
    // Found by mutating the gate away and watching 10a/10b stay green.
    await driveToResult(page, cov(4, 0, ""));
    const card = page.locator(CARD);
    await expect(card).toBeVisible();
    await expect(page.locator(`${CARD} .result-trust-value`)).toContainText("—");
    await expect(page.locator(CAPTION)).toHaveText(FALLBACK);
    await expect(card).not.toContainText("0 of 4");
  });

  test("row 10c — counts that contradict the printed percentage are refused", async ({ page }) => {
    // CitationCoverage validates sourced <= answer but never checks the ratio
    // against the counts, so "10%" over "3 of 4 answers" passes every
    // server-side guard. Two numbers on one card that contradict each other are
    // worse than one number with no denominator — the complaint this issue
    // exists to answer.
    await driveToResult(page, cov(4, 3, "0.10"));
    const card = page.locator(CARD);
    await expect(card).toBeVisible();
    await expect(page.locator(`${CARD} .result-trust-value`)).toContainText("10%");
    await expect(page.locator(CAPTION)).toHaveText(FALLBACK);
    await expect(card).not.toContainText("3 of 4");
  });

  test("row 10d — a ratio that agrees to 2dp still prints the counts", async ({ page }) => {
    // The other direction: the agreement check must tolerate the upstream 2dp
    // quantisation (1/3 = 0.3333... is served as "0.33"), or it would suppress
    // every panel whose fraction does not divide evenly.
    await driveToResult(page, cov(3, 1, "0.33"));
    await expect(page.locator(CAPTION)).toHaveText(
      "1 of 3 answers came back carrying a primary source.",
    );
  });

  // ---- the value line must NOT gain the counts --------------------------

  test("the value line stays a bare percentage, not a second '3 of 4'", async ({ page }) => {
    // The regression this design exists to prevent. The Agreement card's value
    // is `3 of 4`; putting the same shape on Source support's value line puts
    // two unrelated fractions side by side in one grid.
    await driveToResult(page);
    const value = page.locator(`${CARD} .result-trust-value`);
    await expect(value).toBeVisible();
    const valueText = (await value.innerText()).trim();
    // Positive partner first: prove the value line rendered its number at all,
    // so the negative assertions below are not trivially true over nothing.
    expect(valueText).toContain("75%");
    expect(valueText).not.toMatch(/\bof\s+4\b/);
    expect(valueText).not.toContain("answers)");
  });

  test("the Agreement card still owns the bare '3 of 4'", async ({ page }) => {
    // Positive partner for the test above: the fraction did not simply vanish
    // from the grid — it lives on the card it actually describes.
    await driveToResult(page);
    const agreement = page.locator(
      '#result-trust .result-trust-card[data-accent="agreement"] .result-trust-value',
    );
    await expect(agreement).toContainText("3 of 4");
  });
});
