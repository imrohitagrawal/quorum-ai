import { test, expect, Page } from "@playwright/test";
import {
  driveToResult,
  goldenCompletedResp,
  RAW_MARKDOWN_PATTERNS,
} from "../../fixtures/golden-run";

/**
 * THE RESULT VIEW MUST SHOW WHAT THE PANEL ACTUALLY ARGUED.
 *
 * Measured on this branch's parent (568dd10), driving the golden fixture to the
 * completed result view in Chromium:
 *
 *   #debate-output   → 470 chars of round critique, rendered, 0 x 0 px
 *   #result-positions→ 910 x 532 px of "How positions moved"
 *
 * The round critiques WERE built into the DOM on every poll — into
 * `.panel.panel-section`, which `app.css` sets to `display: none` with no view
 * qualifier, so no user has ever seen them on any screen. The 532px the result
 * view did spend went to a table whose "After round 1" column is a pure dict
 * lookup on the FINAL alignment state (`debate.py::_stance_texts`) that never
 * reads a round-1 output — three of its five possible strings literally begin
 * with the word "Opening".
 *
 * These specs pin the replacement: the round-level critique is on the completed
 * result view, rendered as Markdown, and captioned as round-level because the
 * backend records ONE `critique_text` per round with NO per-model attribution
 * (see the HONESTY note at app.js's transcript section). #290 (real peer
 * critique) is NOT built; nothing here may imply it is.
 */

const ROUNDS_IN_FIXTURE = (goldenCompletedResp() as any).result.debate_outputs.length;

test.describe("the result view carries the panel's reasoning", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  // RED IF: `renderResult` stops calling `renderResultDebate`, or the section is
  // rendered into a `display:none` container (which is exactly the bug this
  // replaces — a 0x0 box passes a "is it in the DOM" check and fails this one).
  test("the debate section occupies real pixels on the completed result view", async ({
    page,
  }) => {
    await driveToResult(page);
    const section = page.locator("#result-debate");
    await expect(section).toBeVisible();
    const box = await section.boundingBox();
    expect(box, "#result-debate has no layout box at all").not.toBeNull();
    expect(box!.height, "#result-debate rendered 0px tall — the defect this replaces").toBeGreaterThan(0);
    expect(box!.width).toBeGreaterThan(0);
  });

  // RED IF: the section renders one card per MODEL instead of one per ROUND —
  // the #290 fabrication this must never grow into. The backend emits one
  // `critique_text` per round and no per-model attribution, so the card count
  // must track `debate_outputs.length` (2) and never `model_slots.length` (4).
  test("there is exactly one critique card per debate round, not one per model", async ({
    page,
  }) => {
    await driveToResult(page);
    const cards = page.locator("#result-debate .transcript-round");
    // Positive partner: a count assertion over an empty section would be a
    // negative check wearing a number.
    expect(ROUNDS_IN_FIXTURE, "the fixture must carry rounds for this to mean anything").toBeGreaterThan(0);
    await expect(cards).toHaveCount(ROUNDS_IN_FIXTURE);
    const slots = (goldenCompletedResp() as any).model_slots.length;
    expect(
      ROUNDS_IN_FIXTURE,
      "fixture rounds and slots are equal, so this spec cannot tell the two apart — change the fixture",
    ).not.toBe(slots);
  });

  // RED IF: a round card grows a per-model breakdown. One round = one critique
  // body; anything else is attribution the backend does not record.
  test("each round card carries exactly one critique body", async ({ page }) => {
    await driveToResult(page);
    const cards = page.locator("#result-debate .transcript-round");
    const n = await cards.count();
    expect(n, "no round cards to inspect — the check below would be vacuous").toBeGreaterThan(0);
    for (let i = 0; i < n; i++) {
      await expect(
        cards.nth(i).locator(".transcript-round-body"),
        `round card ${i} must carry exactly one critique body`,
      ).toHaveCount(1);
    }
  });

  // RED IF: the critique is written with `textContent`/`mkEl` instead of
  // `setProse`. MESSY_CRITIQUE_1 carries a `##` heading, `**bold**` and a
  // `1.` ordered list; MESSY_CRITIQUE_2 adds a blockquote, a link and inline
  // code. A bypassed formatter renders those as literal characters and produces
  // none of the elements below.
  test("the critique renders as real Markdown structure", async ({ page }) => {
    await driveToResult(page);
    const section = page.locator("#result-debate");
    const shape = await section.evaluate((el) => ({
      headings: el.querySelectorAll("h1,h2,h3,h4,h5,h6").length,
      strongs: el.querySelectorAll("strong").length,
      orderedLists: el.querySelectorAll("ol").length,
      listItems: el.querySelectorAll("ol li").length,
      blockquotes: el.querySelectorAll("blockquote").length,
      links: el.querySelectorAll("a[href]").length,
      code: el.querySelectorAll("code").length,
    }));
    expect(shape.headings, "the `## Round N critique` heading did not become an <h*>").toBeGreaterThan(0);
    expect(shape.strongs, "`**Alignment:**` did not become a <strong>").toBeGreaterThan(0);
    expect(shape.orderedLists, "the `1.` list did not become an <ol>").toBeGreaterThan(0);
    expect(shape.listItems, "the <ol> is empty").toBeGreaterThan(0);
    expect(shape.blockquotes, "round 2's `>` caveat did not become a <blockquote>").toBeGreaterThan(0);
    expect(shape.links, "the round-2 log link did not become an <a>").toBeGreaterThan(0);
    expect(shape.code, "`citation_check` did not become a <code>").toBeGreaterThan(0);
  });

  // RED IF: any Markdown control character survives into a text node inside the
  // new surface. Scoped to #result-debate so a failure names THIS section
  // rather than being diluted across the whole page.
  test("no raw Markdown survives in the debate section's text nodes", async ({ page }) => {
    await driveToResult(page);
    const { offenders, walked } = await page.evaluate(
      ({ patterns }) => {
        const scope = document.querySelector("#result-debate");
        const offenders: { pattern: string; snippet: string }[] = [];
        if (!scope) return { offenders, walked: 0 };
        const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
        let node: Node | null;
        let walked = 0;
        while ((node = walker.nextNode())) {
          const parent = node.parentElement;
          if (!parent) continue;
          // Literal markers inside <code>/<pre> are correct, not a leak.
          if (parent.closest("code, pre")) continue;
          const text = node.textContent || "";
          if (!text.trim()) continue;
          walked += 1;
          for (const p of patterns) {
            if (new RegExp(p.re, p.flags).test(text)) {
              offenders.push({ pattern: p.name, snippet: text.trim().slice(0, 80) });
              break;
            }
          }
        }
        return { offenders, walked };
      },
      { patterns: RAW_MARKDOWN_PATTERNS.map((p) => ({ name: p.name, re: p.re.source, flags: p.re.flags })) },
    );
    // Positive partner: "no offenders" is trivially true of an empty section.
    expect(walked, "walked no text nodes in #result-debate — the check below would be vacuous").toBeGreaterThan(0);
    expect(
      offenders,
      "raw Markdown leaked into the debate section:\n" +
        offenders.map((o) => `  [${o.pattern}] "${o.snippet}"`).join("\n"),
    ).toEqual([]);
  });

  // RED IF: the critique is only reachable behind the transcript link again.
  // This is the operator-facing symptom, asserted without navigating: the
  // substance of round 2 must be readable on the page the run lands on.
  test("round 2's substance is readable without leaving the result view", async ({ page }) => {
    await driveToResult(page);
    await expect(page.locator('[data-view="result"]')).toBeVisible();
    // Seeded verbatim in MESSY_CRITIQUE_2 (golden-run.ts) as the round's
    // resolved-disagreement sentence.
    await expect(
      page.locator("#result-debate").getByText("residual disagreement on sequencing"),
      "the round-2 critique is not on the result view",
    ).toBeVisible();
    // ...and the transcript link is still there, because the transcript still
    // adds the per-model OPENINGS the result view does not carry.
    await expect(page.locator("#result-transcript-link")).toBeVisible();
  });

  // RED IF: the round-level caption is dropped. Without it the section reads as
  // a per-model exchange, which is precisely what the backend cannot support.
  test("the section is captioned as round-level", async ({ page }) => {
    await driveToResult(page);
    const caption = page.locator("#result-debate .result-debate-caption");
    await expect(caption).toBeVisible();
    const text = ((await caption.textContent()) || "").trim();
    expect(text.length, "the caption is empty").toBeGreaterThan(0);
    // The head must name the section for a screen reader too.
    await expect(page.locator("#result-debate")).toHaveAttribute("role", "region");
  });

  // RED IF: `.result-debate` carries an author `display` that beats the UA
  // stylesheet's `[hidden] { display: none }`. Found by mutating
  // `container.hidden = false` -> `true` and watching all 8 specs stay GREEN:
  // the author rule `display: flex` made the `hidden` attribute inert, so a run
  // with no debate rounds would paint an empty bordered card. The table this
  // replaced set no `display` at all, which is why it never had this bug — so
  // the branch is new and needs its own check, not an inherited one.
  test("a run with no debate rounds shows no debate card at all", async ({ page }) => {
    const resp = goldenCompletedResp() as any;
    resp.result.debate_outputs = [];
    await driveToResult(page, resp);
    // Positive partner: the result view really did render.
    await expect(page.locator("#result-verdict")).toBeVisible();
    const section = page.locator("#result-debate");
    await expect(section).toBeHidden();
    // `toBeHidden` passes on the `hidden` ATTRIBUTE alone in some engines, so
    // pin the geometry too — that is what the reader actually experiences.
    const box = await section.boundingBox();
    expect(box, `#result-debate still occupies ${JSON.stringify(box)}`).toBeNull();
  });

  // RED IF: "How positions moved" is restored. The positive partner keeps this
  // from passing on a page that simply failed to render.
  test("the inferred position table is gone, and the critique replaced it", async ({
    page,
  }) => {
    await driveToResult(page);
    // Positive partner FIRST: prove the result view rendered.
    await expect(page.locator("#result-debate .transcript-round").first()).toBeVisible();
    await expect(page.locator("#result-positions")).toHaveCount(0);
    // The column header that promised a round-1 observation the backend never
    // made must not exist anywhere on the view.
    const headers = await columnHeaders(page);
    expect(headers, "an 'After round 1' column header is back").not.toContain("After round 1");
    // Partner for that negative: the page really does have visible text.
    const bodyText = ((await page.locator("#main-content").textContent()) || "").trim();
    expect(bodyText.length, "the page rendered no text at all").toBeGreaterThan(0);
  });
});

async function columnHeaders(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    [...document.querySelectorAll("#main-content th")].map((el) => (el.textContent || "").trim()),
  );
}
