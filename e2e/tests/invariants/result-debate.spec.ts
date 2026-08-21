import { test, expect, Page } from "@playwright/test";
import {
  driveToResult,
  goldenCompletedResp,
  goldenRespWithTemplatedDebate,
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
    // A review lens showed the count above alone is satisfiable by a card that
    // ALSO carries four per-model paragraphs under any other class name — the
    // rule was pinned at one class rather than at the card's shape. So pin the
    // shape: a round card's direct element children are exactly the head and
    // the body, in that order, and nothing else.
    // First class token only: `setProse` appends `q-prose` to the body it
    // fills, so the full className is not stable and is not what is being
    // asserted — WHICH children exist is.
    const shapes = await cards.evaluateAll((els) =>
      els.map((el) =>
        [...el.children].map((c) => String(c.className).trim().split(/\s+/)[0]),
      ),
    );
    expect(shapes.length, "no cards to inspect").toBeGreaterThan(0);
    for (const [i, children] of shapes.entries()) {
      expect(
        children,
        `round card ${i} grew a child beyond its head and body — a per-model ` +
          `breakdown is attribution the backend does not record`,
      ).toEqual(["transcript-round-head", "transcript-round-body"]);
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
    // The HEADING is its own element and needs its own assertion. A round-2
    // review lens emptied it and every check here stayed green, because the
    // only other test reading this region asserts on the head's COMBINED text,
    // which the caption alone satisfies.
    const title = page.locator("#result-debate .result-debate-title");
    await expect(title).toBeVisible();
    expect(
      ((await title.textContent()) || "").trim().length,
      "the debate section heading is empty",
    ).toBeGreaterThan(0);
    // The head must name the section for a screen reader too.
    await expect(page.locator("#result-debate")).toHaveAttribute("role", "region");
  });

  // RED IF: the caption or heading drifts toward implying the four models read
  // and answered each other — i.e. toward describing #290, which is not built.
  //
  // The previous version of the test above asserted only `length > 0`. A review
  // lens demonstrated that replacing the caption with "Each model read the other
  // three answers and replied in turn — Round 2 is their rebuttal to Round 1."
  // kept all nine specs GREEN. Dropping the caption was caught; FALSIFYING it
  // was not. This pins the meaning, not merely the presence.
  //
  // The forbidden phrases are written out here rather than imported from app.js
  // on purpose (AGENTS.md rule 7a): a test that reads the string it is checking
  // asserts nothing.
  test("neither the heading nor the caption claims the models answered each other", async ({
    page,
  }) => {
    await driveToResult(page);
    const head = page.locator("#result-debate .result-debate-head");
    await expect(head).toBeVisible();
    const text = (((await head.textContent()) || "").trim()).toLowerCase();
    // Positive partner FIRST: there IS copy here to judge.
    expect(text.length, "no heading/caption text to judge — the checks below would be vacuous").toBeGreaterThan(20);
    expect(text, "the caption must still state the round-level shape").toContain("per round");
    const FORBIDDEN = [
      "each other",
      "read the other",
      "rebuttal",
      "replied",
      "reply to",
      "responded to",
      "in turn",
      "back and forth",
      "argued with",
      "peer critique",
    ];
    const hits = FORBIDDEN.filter((phrase) => text.includes(phrase));
    expect(
      hits,
      `the debate section implies a per-model exchange that never happened (#290 is not built): ${JSON.stringify(hits)}\n  in: "${text}"`,
    ).toEqual([]);
    // An authorship claim is only safe when it is conditioned on `debate_mode`,
    // which this copy is not — so it must not make one at all.
    expect(text, "the caption must not attribute the critique to a model unconditionally").not.toContain("written by the moderator");
  });

  // RED IF: a round whose critique came from Quorum's own template is presented
  // as if a model wrote it. `debate_mode` is "live" ONLY when the configured
  // moderator's own response supplied the text; on "fallback" `critique_text` is
  // `debate.py::_build_round_one_text`. Before this, the UI read that field in
  // zero places, so a run with LIVE answers and a fallen-back moderator carried
  // no disclosure anywhere on the result view.
  test("a template-written round says so, and a model-written one does not", async ({
    page,
  }) => {
    // Live rounds: no marker.
    await driveToResult(page);
    const liveCards = page.locator("#result-debate .transcript-round");
    await expect(liveCards).toHaveCount(ROUNDS_IN_FIXTURE);
    await expect(
      page.locator("#result-debate .transcript-round-templated"),
      "a live moderator round must NOT be labelled as Quorum-written",
    ).toHaveCount(0);

    // Fallback rounds: every card marked. Same page, same builder — the only
    // difference is `debate_mode`, which is what makes this pair a control.
    await driveToResult(page, goldenRespWithTemplatedDebate());
    await expect(page.locator("#result-debate .transcript-round")).toHaveCount(ROUNDS_IN_FIXTURE);
    const markers = page.locator("#result-debate .transcript-round-templated");
    await expect(markers).toHaveCount(ROUNDS_IN_FIXTURE);
    await expect(markers.first()).toBeVisible();
  });

  // RED IF: an absent `debate_mode` is treated as live. The API schema's default
  // for that field is "fallback", so unknown provenance must fail CLOSED — the
  // reader is told Quorum may have written it, rather than silently told a model
  // did. The golden fixture carried no `debate_mode` at all until this change.
  test("a round with no debate_mode recorded fails closed", async ({ page }) => {
    const resp = goldenCompletedResp() as any;
    for (const round of resp.result.debate_outputs) delete round.debate_mode;
    await driveToResult(page, resp);
    await expect(page.locator("#result-debate .transcript-round")).toHaveCount(ROUNDS_IN_FIXTURE);
    await expect(
      page.locator("#result-debate .transcript-round-templated"),
      "an absent debate_mode must be treated as NOT live",
    ).toHaveCount(ROUNDS_IN_FIXTURE);
  });

  // RED IF: the constant `focus_areas` line is put back on the result view.
  // `debate.py` passes the module constant FOCUS_AREAS to BOTH rounds, so the
  // line is byte-identical on every card of every run; under a "Round N" header
  // it reads as per-round metadata. That is the same "constant dressed as an
  // observation" defect this change removed the position table for.
  test("the constant focus line is not promoted onto the result view", async ({
    page,
  }) => {
    await driveToResult(page);
    // Positive partner: the cards rendered, so the absence below is meaningful.
    await expect(page.locator("#result-debate .transcript-round")).toHaveCount(ROUNDS_IN_FIXTURE);
    await expect(page.locator("#result-debate .transcript-round-focus")).toHaveCount(0);
    // ...and the transcript, a drill-down the reader chose to open, still has it:
    // this is a placement decision, not a deletion, and the partner proves the
    // selector is not simply wrong.
    await page.locator("#result-transcript-link").click();
    await expect(page.locator("#transcript-rounds .transcript-round-focus").first()).toBeVisible();
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
    // ...including one built from ARIA rather than <th>, which the selector
    // above cannot see.
    const ariaHeaders = await page.evaluate(() =>
      [...document.querySelectorAll('#main-content [role="columnheader"]')].map(
        (el) => (el.textContent || "").trim(),
      ),
    );
    expect(ariaHeaders, "an ARIA column header is back").not.toContain("After round 1");

    // The strongest form: the movement DATA itself must not be rendered
    // anywhere on the view, whatever markup or id it is wrapped in. These two
    // strings are `goldenMovements()`'s own `after_round_1` / `final` values,
    // so they can only appear if something is reading `position_movements`
    // again. Quoted from the FIXTURE, not from the app, so this is not a test
    // parametrised over the constant it tests.
    const viewText = ((await page.locator("#main-content").textContent()) || "").trim();
    // Partner for the negatives: the page really does have visible text.
    expect(viewText.length, "the page rendered no text at all").toBeGreaterThan(0);
    for (const movementOnly of ["Held its opening position", "Aligned with the final synthesis"]) {
      expect(
        viewText,
        `the result view is rendering position_movements again (found "${movementOnly}")`,
      ).not.toContain(movementOnly);
    }
  });
});

async function columnHeaders(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    [...document.querySelectorAll("#main-content th")].map((el) => (el.textContent || "").trim()),
  );
}
