import { test, expect, Page } from "@playwright/test";
import {
  driveToResult,
  driveToTranscript,
  driveDecreasingTimer,
  parseElapsedMs,
  goldenRespWithBlockStructure,
  goldenCompletedResp,
  RAW_MARKDOWN_PATTERNS,
} from "../../fixtures/golden-run";

/**
 * GLOBAL RENDERING INVARIANTS — the below-the-line gate that breaks the
 * recurring-UI-bug cycle (see docs/analysis/03-enforcement-machinery.md and
 * docs/day-one-quality-standard.md).
 *
 * These walk the WHOLE rendered DOM against the golden (messy, real-shaped)
 * fixture and assert class-wide truths, instead of checking one surface at a
 * time. They are designed to go RED on today's shipping bugs:
 *   - no-raw-markdown  → #30 (raw `##`/`**` on ~11 provider-text surfaces)
 *   - monotonic-timer  → #29 (live-run elapsed snaps backwards on a lower poll)
 *   - no-horizontal-overflow → the standard's "nothing overflows" invariant
 *
 * Chromium is the reference engine (matches the axe gate). The whole point is
 * that these fail NOW; the fixes (#29/#30/#33) turn them green.
 */

test.describe("rendering invariants (golden fixture)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  // --- collect literal Markdown markers surviving in text nodes ---------------
  async function collectRawMarkdown(page: Page, scopeSelector: string) {
    return page.evaluate(
      ({ scopeSelector, patterns }) => {
        const scope = document.querySelector(scopeSelector) || document.body;
        const offenders: { pattern: string; snippet: string; where: string }[] = [];
        const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
        let node: Node | null;
        // A short path so failures point at the surface, not just the text.
        const pathOf = (el: Element | null): string => {
          const parts: string[] = [];
          let cur: Element | null = el;
          for (let i = 0; cur && i < 4; i++) {
            const cls = (cur.className && typeof cur.className === "string")
              ? "." + cur.className.trim().split(/\s+/).slice(0, 2).join(".")
              : "";
            parts.unshift(cur.id ? `${cur.tagName.toLowerCase()}#${cur.id}` : `${cur.tagName.toLowerCase()}${cls}`);
            cur = cur.parentElement;
          }
          return parts.join(" > ");
        };
        let walked = 0;
        while ((node = walker.nextNode())) {
          // Skip hidden subtrees so we only judge what a user can see.
          const parent = node.parentElement;
          if (!parent) continue;
          // Skip verbatim code: literal markdown markers inside <code>/<pre> are
          // CORRECT (inline code is not formatted), not a bypassed-formatter bug.
          // e.g. `__init__` must render literally, so the underscore/backtick
          // patterns must not flag it here.
          if (parent.closest("code, pre")) continue;
          const text = node.textContent || "";
          if (!text.trim()) continue;
          walked += 1;
          for (const p of patterns) {
            if (new RegExp(p.re, p.flags).test(text)) {
              offenders.push({
                pattern: p.name,
                snippet: text.trim().slice(0, 80),
                where: pathOf(parent),
              });
              break;
            }
          }
        }
        return { offenders, walked };
      },
      {
        scopeSelector,
        patterns: RAW_MARKDOWN_PATTERNS.map((p) => ({ name: p.name, re: p.re.source, flags: p.re.flags })),
      }
    );
  }

  test("no raw Markdown control syntax survives in the RESULT view (#30)", async ({ page }) => {
    await driveToResult(page);
    const { offenders, walked } = await collectRawMarkdown(page, "#main-content");
    // Positive partner (#131/#226): "no offenders" is trivially true of a page
    // that rendered nothing at all. This was one of the 16 violations the
    // negative-assertion guard reports repo-wide; it blocked this merge, so it
    // is fixed here rather than filed.
    expect(walked, "walked no text nodes — the check below would be vacuous").toBeGreaterThan(0);
    expect(
      offenders,
      `Raw Markdown leaked into rendered text (a surface bypassed the formatter):\n` +
        offenders.map((o) => `  [${o.pattern}] "${o.snippet}"  @ ${o.where}`).join("\n")
    ).toEqual([]);
  });

  test("no raw Markdown control syntax survives in the TRANSCRIPT view (#30)", async ({ page }) => {
    await driveToResult(page);
    await driveToTranscript(page);
    const { offenders, walked } = await collectRawMarkdown(page, "#main-content");
    expect(walked, "walked no text nodes — the check below would be vacuous").toBeGreaterThan(0);
    expect(
      offenders,
      `Raw Markdown leaked into the transcript (openings/critiques/source titles):\n` +
        offenders.map((o) => `  [${o.pattern}] "${o.snippet}"  @ ${o.where}`).join("\n")
    ).toEqual([]);
  });

  // ---- WP-F / F-13: list STRUCTURE, not just the absence of markers -------
  //
  // The no-raw-markdown walk above is a text-node check, so it is blind to
  // markup that is structurally wrong but leaks no marker: a list split into
  // one single-item list per line leaves no "- " behind, and neither does a
  // paragraph silently turned into a bullet. Both were live in the shipped UI
  // and both passed that gate. These assert the structure itself.

  test("an ordered list renders as a real <ol> (F-13)", async ({ page }) => {
    await driveToResult(page);
    // Seeded verbatim in MESSY_RECOMMENDATION as "1. Ship the retention-…".
    const item = page
      .locator("#main-content ol li")
      .filter({ hasText: "Ship the retention-instrumentation slice first" });
    // The recommendation is rendered on more than one surface of this view, so
    // this pins "at least one, and the user can see it" rather than an exact
    // count that would break the next time a surface is added.
    await expect(
      item.first(),
      "the recommendation's numbered steps must be <li> inside an <ol>. " +
        "Rendered as paragraphs, the literal '1. ' survives as text — which " +
        "is what the ordered-list marker pattern catches."
    ).toBeVisible();
  });

  test("a bullet list renders as ONE list, not one list per item (F-13)", async ({ page }) => {
    await driveToResult(page);
    // MESSY_BULLET_LIST: 6 items, seeded into the disagreement section — a
    // block surface that is genuinely VISIBLE here. (The model-card grid
    // measures 0x0 on this view, so an answer body would have gated markup no
    // user ever sees.)
    const body = page
      .locator("#main-content .result-synth-body")
      .filter({ hasText: "instrument retention events before export" })
      .first();
    await expect(body).toBeVisible();
    const shape = await body.evaluate((el) => ({
      // TOP-LEVEL lists only. The defect this guards is "six bullets became six
      // SIBLING single-item lists" — a statement about siblings. Counting every
      // <ul> in the subtree also counts a correctly NESTED sub-list, which is
      // the fix, not the defect. The comment below already said pinning the
      // ITEM count would "block the fix for the defect it half-describes"; the
      // list count had the identical flaw and nobody noticed, because no
      // renderer had ever nested anything. ADR-0014's parser does: it took this
      // number from 1 to 2 while the six bullets stayed in ONE sibling list.
      topLevelLists: el.querySelectorAll(":scope > ul").length,
      nestedLists: el.querySelectorAll("ul ul, ul ol, ol ul, ol ol").length,
      items: el.querySelectorAll("ul li").length,
      emptyParagraphs: [...el.querySelectorAll("p")].filter(
        (p) => !(p.textContent || "").trim()
      ).length,
    }));
    expect(
      shape.topLevelLists,
      `expected exactly ONE top-level <ul> for the six-item list; saw ${shape.topLevelLists}. ` +
        "More than one means each line became its own single-item list."
    ).toBe(1);
    // At LEAST six: the fixture seeds an indented sub-bullet, so the flat count
    // and the nested count differ by how that item is ATTACHED, not by content.
    expect(
      shape.items,
      "the six seeded bullets must all be <li> of that list"
    ).toBeGreaterThanOrEqual(6);
    // Positive partner for `topLevelLists === 1`: that assertion is ALSO
    // satisfied by a renderer that dropped the indented sub-bullet outright.
    // The fixture seeds exactly one, so exactly one nested list must exist.
    expect(
      shape.nestedLists,
      "the fixture's indented sub-bullet must render as a NESTED list — not " +
        "flattened to a sibling item, and not dropped"
    ).toBe(1);
    // No item may carry the stripped indent as literal text.
    const untrimmed = await body.evaluate(() =>
      [...document.querySelectorAll(".result-synth-body li")]
        .map((li) => li.textContent || "")
        .filter((t) => t !== t.trimStart())
    );
    expect(untrimmed, "a list item kept its marker indentation as text").toEqual([]);
    expect(
      shape.emptyParagraphs,
      "empty <p> residue means a <ul> was emitted INSIDE a <p> and the browser " +
        "hoisted it out, splitting the paragraph around it"
    ).toBe(0);
  });

  test("soft-wrapped prose never becomes a bullet (F-13)", async ({ page }) => {
    await driveToResult(page);
    // A single paragraph the provider broke with SINGLE newlines — the shape
    // most real model output arrives in. Its lines are prose, not list items.
    // Positive control FIRST: without it, a fixture reword makes the negative
    // below silently vacuous — it would pass because the text is absent, not
    // because it is correctly rendered.
    await expect(
      page.getByText("The instrumentation is rarely the hard part", { exact: false }).first()
    ).toBeVisible();
    const stray = page
      .locator("#main-content li")
      .filter({ hasText: "The instrumentation is rarely the hard part" });
    await expect(
      stray,
      "a soft-wrapped prose line was rendered as a list item. Ordinary prose " +
        "must never become a bullet — the reader cannot tell the model did not " +
        "write a list."
    ).toHaveCount(0);
  });

  test("a soft wrap onto a number never deletes the number (F-13)", async ({ page }) => {
    // "…first proposed in\n2025. Nobody has revisited…" is ONE paragraph the
    // provider wrapped. Treating "2025. " as an ordered-list marker strips it,
    // so the year vanishes from the answer entirely. CommonMark only lets an
    // ordered list interrupt a paragraph when it starts at 1, precisely to stop
    // this.
    await driveToResult(page);
    const body = page
      .locator("#main-content .result-synth-body")
      .filter({ hasText: "The gate was first proposed in" })
      .first();
    await expect(body).toBeVisible();
    await expect(
      body,
      "the year was deleted from the rendered answer — the marker is stripped, " +
        "so no raw-marker gate can see this happen"
    ).toContainText("2025");
  });

  test("stray asterisks in prose never fabricate emphasis (F-13)", async ({ page }) => {
    // Two unpaired asterisks in ordinary prose (a multiplication, a footnote
    // mark) must not pair up ACROSS words into a bogus <em>. Rendered via the
    // real formatter, not a unit stub.
    await driveToResult(page);
    // Scoped to `.q-prose` — the class setProse puts on rendered PROVIDER
    // prose. App chrome legitimately writes <strong>Provider path: </strong>
    // with a trailing space inside the tag; that is app-authored markup, not
    // something the formatter derived from model text, and it is not what this
    // invariant is about.
    const emphasised = await page.evaluate(() => {
      const scope = document.querySelector("#main-content") || document.body;
      return [...scope.querySelectorAll(".q-prose em, .q-prose strong")].map(
        (e) => e.textContent || ""
      );
    });
    // The signature of a FALSE pair is precise: `a * b and c * d` emphasises
    // " b and c ", so the emphasised run carries leading/trailing whitespace.
    // Real emphasis never does — `*bold*` cannot capture its own bounding
    // spaces. Keying off the signature, not a word-count heuristic, is what
    // makes this assertion able to fail.
    // Without this the filter below is over a possibly-empty set: setProse
    // REMOVES `q-prose` on its placeholder branch, so "the formatter fell back
    // everywhere" would pass as cleanly as a correct render.
    expect(
      emphasised.length,
      "no emphasis found in provider prose at all — the filter below would be " +
        "green over an empty set"
    ).toBeGreaterThan(0);
    // The whitespace-bounded signature below catches the SPACED form. It
    // cannot catch the unspaced one — the regex captures `[^\s*]…[^\s*]`, so
    // emphasis text can never carry bounding spaces, making that predicate
    // unreachable for any variant of the current rule. So assert the unspaced
    // arithmetic directly, against text the fixture seeds for it.
    const arithmetic = page
      .locator("#main-content .q-prose p")
      .filter({ hasText: "Rerunning it costs" })
      .first();
    await expect(arithmetic).toBeVisible();
    await expect(
      arithmetic,
      "unspaced arithmetic must survive literally — emphasis here is invented"
    ).toContainText("3*40");
    expect(
      await arithmetic.locator("em").count(),
      "an <em> in a paragraph whose only asterisks are multiplication signs " +
        "is emphasis the model never wrote"
    ).toBe(0);

    const fabricated = emphasised.filter((t) => t !== t.trim());
    expect(
      fabricated,
      `emphasis whose text is surrounded by whitespace is two stray asterisks ` +
        `paired ACROSS words, not something the model wrote:\n` +
        JSON.stringify(fabricated, null, 2)
    ).toEqual([]);
  });

  test("inline code renders verbatim — no emphasis fires inside a <code> span (#30)", async ({ page }) => {
    // Inline code is verbatim by contract. The underscore/asterisk emphasis
    // rules must NOT fire inside a code span: `__init__` must stay literal, not
    // become `<strong>init</strong>`. Regression guard for the applyOutsideTags
    // code-span skip (adversarial finding 2a).
    await driveToResult(page);
    const codeSpans = await page.evaluate(() => {
      const scope = document.querySelector("#main-content") || document.body;
      return [...scope.querySelectorAll("code")].map((c) => ({
        html: c.innerHTML,
        text: c.textContent || "",
      }));
    });
    const withEmphasis = codeSpans.filter((c) => /<(strong|em)\b/i.test(c.html));
    expect(
      withEmphasis,
      `emphasis leaked INTO a <code> span (code must be verbatim):\n${JSON.stringify(withEmphasis, null, 2)}`
    ).toEqual([]);
    // The seeded dunder must survive literally (proves the fix, not just absence).
    const dunder = codeSpans.find((c) => c.text.includes("__init__"));
    expect(
      dunder,
      `expected a <code> span containing the literal "__init__"; saw ${JSON.stringify(codeSpans.map((c) => c.text))}`
    ).toBeTruthy();
  });

  test("live-run elapsed readout is monotonic across a decreasing poll sequence (#29)", async ({ page }) => {
    // Successive polls report elapsed 12s → 3s → 4s → 5s → 6s. A correct readout
    // never ticks backwards; today it snaps down to ~3s when the lower poll lands.
    await driveDecreasingTimer(page, [12000, 3000, 4000, 5000, 6000]);

    const samples: number[] = [];
    const deadline = Date.now() + 5000;
    // NOTE: real wall-clock sampling is required here (we are observing a live
    // ticker); this is not Date.now()-in-a-workflow-script, it is a browser test.
    while (Date.now() < deadline) {
      const el = page.locator("#live-elapsed");
      if ((await el.count()) === 0 || !(await el.isVisible())) break;
      const ms = parseElapsedMs(await el.textContent());
      if (ms != null) samples.push(ms);
      await page.waitForTimeout(150);
    }

    expect(samples.length, "expected to sample the live elapsed readout while running").toBeGreaterThan(3);
    // Guard against a SPURIOUS PASS: prove the sampler actually witnessed the
    // high value the readout falls FROM. Without this, a slow runner whose first
    // sample lands after the ~1s high-value window would see only the monotonic
    // tail (3.3s→4.5s→6.0s) and pass while the backward-jump bug is still present.
    expect(
      Math.max(...samples),
      `sampler never observed the pre-drop high value (~12s); saw max=${Math.max(...samples)}ms. ` +
        `Cannot certify monotonicity without witnessing the drop's origin. samples=${JSON.stringify(samples)}`
    ).toBeGreaterThan(10000);
    // Allow tiny parse jitter (display granularity is 0.1s), but a real backward
    // jump (seconds) must fail.
    const TOL = 150;
    let worstDrop = 0;
    for (let i = 1; i < samples.length; i++) {
      worstDrop = Math.max(worstDrop, samples[i - 1] - samples[i]);
    }
    expect(
      worstDrop,
      `elapsed readout jumped BACKWARDS by ${worstDrop}ms (non-monotonic timer).\n` +
        `samples(ms)=${JSON.stringify(samples)}`
    ).toBeLessThanOrEqual(TOL);
  });

  test("the page never scrolls horizontally (result + transcript)", async ({ page }) => {
    await driveToResult(page);
    expect(await pageScrollsHorizontally(page), "result view forces horizontal page scroll").toBe(false);

    await driveToTranscript(page);
    expect(await pageScrollsHorizontally(page), "transcript view forces horizontal page scroll").toBe(false);
  });

  // The test above NEVER calls setViewportSize, so for its whole life it has
  // only ever asserted this at Playwright's 1280px default — where the layout is
  // comfortable and nothing overflows. A 77px blowout at 375px sat behind that
  // blind spot: `.result-synth-row` is `grid-template-columns: 132px 1fr` with no
  // mobile breakpoint, and `1fr` resolves to `minmax(auto, 1fr)` whose auto
  // minimum is the content's MIN-CONTENT — so a long unbreakable token in the
  // synthesis body (`retention_flag=true`) pushed the row past the viewport and
  // the session panel painted over the verdict band.
  //
  // Mobile is where a horizontal-scroll bug actually bites, so sweep the real
  // breakpoints. 375 = iPhone SE/mini, 768 = tablet, 1440 = the design comp.
  // Page-level scroll is NOT the whole story. A card that clips its own
  // overflow hides the damage from the document: the transcript's opening cards
  // measured clientWidth 271 with scrollWidth 624 — 353px of provider text
  // silently cut off — while `document.scrollWidth` stayed clean. Content the
  // user cannot read is a defect whether or not the page scrolls.
  //
  // Intentional scroll containers (overflow-x: auto/scroll, e.g. the wide
  // positions table) are exempt: scrolling INSIDE a container that advertises
  // itself as scrollable is the designed behaviour.
  for (const width of [375, 768] as const) {
    test(`no element silently clips its own content @ ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await driveToResult(page);
      await driveToTranscript(page);
      await page.evaluate(() => (document as unknown as { fonts?: { ready: Promise<unknown> } }).fonts?.ready);

      const clipped = await page.evaluate(() => {
        const bad: { tag: string; cls: string; client: number; scroll: number; text: string }[] = [];
        const root = document.getElementById("main-content");
        if (!root) return bad;
        for (const el of Array.from(root.querySelectorAll<HTMLElement>("*"))) {
          if (el.scrollWidth <= el.clientWidth + 1) continue;
          // Exempt this element or any ancestor that opts into scrolling.
          let scrollable = false;
          for (let n: HTMLElement | null = el; n && n !== root.parentElement; n = n.parentElement) {
            const ox = getComputedStyle(n).overflowX;
            if (ox === "auto" || ox === "scroll") { scrollable = true; break; }
          }
          if (scrollable) continue;
          const cs = getComputedStyle(el);
          if (cs.display === "none" || cs.visibility === "hidden") continue;
          bad.push({
            tag: el.tagName,
            cls: (el.className || "").toString().slice(0, 45),
            client: el.clientWidth,
            scroll: el.scrollWidth,
            text: (el.textContent || "").trim().slice(0, 45),
          });
        }
        return bad;
      });

      // Positive partner (#131/#226): "nothing clipped" is trivially true of a
      // page that rendered no elements. Third of the three pre-existing
      // violations in this file that blocked the #120 merge.
      const examined = await page.evaluate(
        () => document.querySelectorAll("#main-content *").length,
      );
      expect(examined, "examined no elements — the check below would be vacuous").toBeGreaterThan(0);
      expect(
        clipped,
        `elements clipping their own content at ${width}px:\n${clipped
          .map((c) => `  ${c.tag}.${c.cls} client=${c.client} scroll=${c.scroll} — "${c.text}"`)
          .join("\n")}`,
      ).toEqual([]);
    });
  }

  for (const width of [375, 768, 1440] as const) {
    test(`the page never scrolls horizontally @ ${width}px (result + transcript)`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await driveToResult(page);
      expect(
        await pageScrollsHorizontally(page),
        `result view forces horizontal page scroll at ${width}px`,
      ).toBe(false);

      await driveToTranscript(page);
      expect(
        await pageScrollsHorizontally(page),
        `transcript view forces horizontal page scroll at ${width}px`,
      ).toBe(false);
    });
  }
});

// The universally-valid layout invariant: the PAGE (document) must not scroll
// horizontally. Keyed on the document scroll width, NOT per-element bounding
// boxes — so it never false-positives on content that legitimately scrolls
// INSIDE its own `overflow-x:auto` container (e.g. the wide positions table).
// Waits for web fonts so late reflow can't flip a borderline result.
async function pageScrollsHorizontally(page: Page) {
  await page.evaluate(() => (document as unknown as { fonts?: { ready: Promise<unknown> } }).fonts?.ready);
  return page.evaluate(() => {
    const el = document.documentElement;
    // 1px slack for sub-pixel rounding.
    return el.scrollWidth > el.clientWidth + 1;
  });
}

/**
 * #120 — BLOCK STRUCTURE ON THE BLOCKQUOTE AND INLINE-PROSE PATHS.
 *
 * Until this landed, `formatAnswerText`'s blockquote branch handed raw lines to
 * `mdInline` and `setInlineProse` called `mdInline` directly, so neither path
 * had list handling. The fixture deliberately seeded no list into either — and
 * `golden-run.ts` said so out loud: "a numbered list in a blockquote would fire
 * this with no fix available. The fixture seeds none — that, and not the
 * pattern, is why this is green there."
 *
 * So the gate was green because nothing exercised it, which is exactly the
 * vacuous-guard shape AGENTS.md rule 7 exists to stop. These four tests seed
 * the shapes and assert STRUCTURE, not substrings.
 *
 * WHAT TURNS EACH RED is stated per test. All four were measured RED on 2ba0519
 * and GREEN after the fix; the before/after numbers are in the ADR.
 */
test.describe("#120 — lists inside blockquotes and inline surfaces", () => {
  test.beforeEach(async ({ page }) => {
    await driveToResult(page, goldenRespWithBlockStructure());
  });

  // RED IF: flushQuote stops re-entering formatAnswerText and goes back to
  // joining mdInline output with <br>. Measured before the fix: ol=0.
  test("an ordered list inside a blockquote renders a real <ol>", async ({ page }) => {
    const quoted = page.locator("#main-content blockquote", { hasText: "Steps to follow" }).first();
    await expect(quoted).toBeVisible();
    await expect(quoted.locator("ol")).toHaveCount(1);
    // The positive partner: the <ol> must carry BOTH steps, not an empty shell.
    await expect(quoted.locator("ol > li")).toHaveCount(2);
    await expect(quoted.locator("ol > li").first()).toHaveText("Instrument the events first.");
  });

  // RED IF: consecutive bullets inside a quote each become their own list
  // again. Measured before the fix: ul=2, li=2 for two bullets — one
  // single-item <ul> per line.
  test("consecutive bullets inside a blockquote form ONE <ul>", async ({ page }) => {
    const quoted = page.locator("#main-content blockquote", { hasText: "Steps to follow" }).first();
    await expect(quoted.locator("ul")).toHaveCount(1);
    await expect(quoted.locator("ul > li")).toHaveCount(2);
  });

  // RED IF: setInlineProse stops pre-rendering markers, so a list reaches
  // mdInline intact AND mdInline can build a list from it. Measured before the
  // fix: exactly one violation, "UL inside <p> (result-source-support)".
  //
  // Review correction: an earlier version of this comment said "mdInline
  // regains a <ul> rule, OR setInlineProse stops pre-rendering". The first
  // disjunct is FALSE and was demonstrated so — re-injecting the deleted <ul>
  // rule into mdInline leaves all four tests green, because inlineListMarkers
  // has already consumed every marker before mdInline runs. Only the
  // conjunction turns this red. The structural guard in
  // tests/unit/test_mdinline_bullets.py is what covers mdInline on its own.
  test("no list element is ever a child of a <span> or <p>", async ({ page }) => {
    const violations = await page.evaluate(() => {
      const main = document.querySelector("#main-content");
      if (!main) return ["#main-content missing"];
      return Array.from(main.querySelectorAll("ul,ol"))
        .filter((el) => el.parentElement && ["SPAN", "P"].includes(el.parentElement.tagName))
        .map(
          (el) =>
            `${el.tagName} inside <${el.parentElement!.tagName.toLowerCase()}>` +
            ` (${el.parentElement!.className})`,
        );
    });
    expect(violations, "list element inside an inline-only container").toEqual([]);
    // Positive partner — without it this passes over a page that rendered no
    // list at all, which is the very failure the assertion above cannot see.
    const lists = await page.locator("#main-content ul, #main-content ol").count();
    expect(lists, "fixture must actually render lists for the check above to mean anything").toBeGreaterThan(0);
  });

  // RED IF: any path stops rendering a marker — this runs the SAME patterns the
  // whole-DOM sweep above uses, but over the seeded payload. Measured before
  // the fix: 4 text nodes matched "ordered-list marker (1. )".
  test("no raw markdown marker survives on the seeded block-structure payload", async ({ page }) => {
    const hits = await page.evaluate(
      (patterns: { name: string; src: string }[]) => {
        const main = document.querySelector("#main-content");
        const walker = document.createTreeWalker(main as Node, NodeFilter.SHOW_TEXT);
        const texts: string[] = [];
        for (let n = walker.nextNode(); n; n = walker.nextNode()) {
          if (n.nodeValue && n.nodeValue.trim()) texts.push(n.nodeValue);
        }
        const found: string[] = [];
        for (const p of patterns) {
          const re = new RegExp(p.src);
          for (const t of texts) {
            if (re.test(t)) found.push(`${p.name} :: ${JSON.stringify(t.slice(0, 60))}`);
          }
        }
        // Returned alongside so an empty `found` cannot mean "walked nothing".
        return { found, textNodeCount: texts.length };
      },
      RAW_MARKDOWN_PATTERNS.map((p) => ({ name: p.name, src: p.re.source })),
    );
    // toBeGreaterThanOrEqual, not toBeGreaterThan: the guard only treats
    // `toBeGreaterThan` as a positive partner when it compares against ZERO
    // (check-negative-assertions.mjs:197), while `toBeGreaterThanOrEqual`
    // counts for any positive number (:198). Same assertion, recognised.
    expect(hits.textNodeCount, "walked no text nodes — the check would be vacuous").toBeGreaterThanOrEqual(20);
    expect(hits.found, "raw markdown survived into a text node").toEqual([]);
  });
});

/**
 * #120, ROUND 2 — the assertions review proved were MISSING.
 *
 * Lens 1 built two implementations the ADR explicitly rejects — "delete every
 * marker" and "keep bullets, delete every ordinal" — and measured that ALL
 * four tests above plus all 13 unit tests stayed green against both. The suite
 * asserted that no RAW marker survives, and nothing anywhere asserted that a
 * RENDERED one appears. A negative check with no positive partner, which is
 * the exact shape AGENTS.md rule 7 names, sitting inside the gate written to
 * close a rendering issue.
 *
 * These three are that partner. Each states what turns it red.
 */
test.describe("#120 round 2 — the rendered marker, and the number the model wrote", () => {
  test.beforeEach(async ({ page }) => {
    await driveToResult(page, goldenRespWithBlockStructure());
  });

  // RED IF: inlineListMarkers deletes a bullet instead of rendering one, or
  // stops emitting <br> so the items collapse onto a single run-on line.
  test("an inline bullet list renders a bullet character, one item per line", async ({ page }) => {
    const support = page.locator("#main-content .result-source-support").first();
    await expect(support).toContainText("• verify the cost figure");
    await expect(support).toContainText("• keep the cap");
    // The <br> is what stacks them; without it white-space:normal collapses the
    // newline and both items share a line. Measured on .result-source-support:
    // 88px stacked before #120, 20px run-on with a bare newline, 61px with <br>.
    expect(await support.locator("br").count(), "items must be separated by <br>").toBeGreaterThan(0);
  });

  // RED IF: an ordinal is DELETED rather than rendered — the ADR's rejected
  // alternative, which passed every other test in this file.
  test("an inline ordered list keeps the model's numbers", async ({ page }) => {
    const caption = page
      .locator("#main-content .result-trust-caption")
      .filter({ hasText: "Open items" })
      .first();
    await expect(caption).toContainText("(1) cohort definition");
    await expect(caption).toContainText("(2) export gate");
  });

  // RED IF: <ol> loses its `start` attribute. Then a quoted procedure that the
  // model opened at "4." is RENUMBERED to 1 on screen — the product stating a
  // fact its input never contained. Invisible to every text-node walk in this
  // file, because the number lives in ::marker; only the attribute and the
  // rendered ::marker text can see it.
  test("a quoted list that opens at 4 is not renumbered to 1", async ({ page }) => {
    const quoted = page
      .locator("#main-content blockquote", { hasText: "Reconcile the ledger" })
      .first();
    await expect(quoted).toBeVisible();
    const ol = quoted.locator("ol").first();
    await expect(ol).toHaveAttribute("start", "4");
    // Both halves of what the browser actually numbers from: the parsed `start`
    // property (not just the attribute string) and a decimal list-style. With
    // start=4 and list-style-type:decimal the first ::marker is "4.".
    //
    // The ::marker TEXT itself is deliberately not asserted. Measured:
    // `getComputedStyle(li, "::marker").content` returns "normal" in Chromium
    // for a browser-generated counter — the string is never exposed to the DOM.
    // That is precisely why this defect is invisible to every text-node walk in
    // this file, and why the attribute is the strongest available proxy. Stated
    // rather than papered over.
    const shape = await ol.evaluate((el) => ({
      start: (el as HTMLOListElement).start,
      listStyle: getComputedStyle(el).listStyleType,
    }));
    expect(shape.start, "the <ol> must be numbered from the model's own 4").toBe(4);
    expect(
      shape.listStyle,
      "a non-decimal list-style would hide the number the start attribute sets",
    ).toBe("decimal");
  });
});

/**
 * #120 ROUND 3 — the two mdInline callers the fix's own prose forgot.
 *
 * The commit body and ADR both claimed "no caller lost anything" and listed
 * FOUR callers. `grep -n "mdInline(" app.js` returns FIVE. The two missed —
 * the heading branch and flushQuote's depth-capped fallback — were left
 * emitting a raw marker once mdInline's <ul> rule was deleted, and BOTH new
 * shapes match the blocking gate's own patterns. Neither is in the golden
 * fixture, so review found them and the gate could not.
 */
test.describe("#120 round 3 — the callers a superlative hid", () => {
  const HEADING_AND_DEEP_QUOTE =
    "### - alpha bravo\n\n" + ">".repeat(6) + " - side note zulu\n";

  test.beforeEach(async ({ page }) => {
    const resp = goldenCompletedResp() as Record<string, unknown>;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (resp as any).result.final_synthesis.recommendation = HEADING_AND_DEEP_QUOTE;
    await driveToResult(page, resp);
  });

  // RED IF: the heading branch stops calling inlineListMarkers. Before #120 it
  // emitted "<h6><ul><li>alpha bravo</li></ul></h6>" — a <ul> inside a heading,
  // illegal. Removing mdInline's rule without adding the call left a raw "- ".
  test("a heading renders its marker and contains no list", async ({ page }) => {
    const heading = page
      .locator("#main-content h4, #main-content h5, #main-content h6")
      .filter({ hasText: "alpha bravo" })
      .first();
    await expect(heading).toBeVisible();
    await expect(heading).toHaveText("• alpha bravo");
    expect(await heading.locator("ul, ol").count(), "a heading may not contain a list").toBe(0);
  });

  // RED IF: the depth-capped fallback stops flattening leftover "> " markers.
  // MEASURED on this 6-deep input: main leaves ">>>>> - side note zulu", which
  // the gate's `(^|\n)>\s` pattern does NOT match; stripping one level per
  // recursion leaves "> - side note zulu", which DOES — 3 hits. Flattening
  // gives 0.
  test("a quote nested past the depth cap leaks no marker", async ({ page }) => {
    const found = await page.evaluate(
      (patterns: { name: string; src: string }[]) => {
        const main = document.querySelector("#main-content");
        const walker = document.createTreeWalker(main as Node, NodeFilter.SHOW_TEXT);
        const texts: string[] = [];
        for (let n = walker.nextNode(); n; n = walker.nextNode()) {
          if ((n.parentElement as Element | null)?.closest("code, pre")) continue;
          if (n.nodeValue && n.nodeValue.trim()) texts.push(n.nodeValue);
        }
        const hits: string[] = [];
        for (const p of patterns) {
          for (const t of texts) {
            if (new RegExp(p.src).test(t)) hits.push(`${p.name} :: ${JSON.stringify(t.slice(0, 50))}`);
          }
        }
        return { hits, zulu: texts.filter((t) => t.includes("zulu")) };
      },
      RAW_MARKDOWN_PATTERNS.map((p) => ({ name: p.name, src: p.re.source })),
    );
    // Positive partner: the deep-quoted content must actually be on the page,
    // or "no markers found" would be true of a page that dropped it entirely.
    expect(found.zulu.length, "the deeply quoted line must still be rendered").toBeGreaterThan(0);
    expect(found.hits, "a marker survived past the depth cap").toEqual([]);
    // The bullet must survive as STRUCTURE, inside the quote. This used to
    // assert the literal text "• side note zulu" — the rendered-marker
    // WORKAROUND the hand-rolled formatter emitted once it hit a recursion cap
    // it needed because it re-entered itself per "> " level. ADR-0014's parser
    // is iterative and has no cap, so it renders the real thing: nested
    // <blockquote>s ending in a genuine <li>. Asserting the workaround's glyph
    // would have failed the strictly better output — so this now asserts the
    // structure, which the old renderer could NOT produce at this depth and the
    // new one must.
    const structure = await page.evaluate(() => {
      const li = [...document.querySelectorAll("#main-content blockquote li")]
        .find((el) => (el.textContent || "").includes("side note zulu"));
      return {
        found: Boolean(li),
        insideList: Boolean(li?.closest("ul, ol")),
        quoteDepth: li ? li.closest("blockquote") ? (() => {
          let n = 0;
          for (let el: Element | null = li; el; el = el.parentElement) {
            if (el.tagName === "BLOCKQUOTE") n++;
          }
          return n;
        })() : 0 : 0,
      };
    });
    expect(structure.found, "the deeply quoted bullet must be a real <li>").toBe(true);
    expect(structure.insideList, "that <li> must sit inside a <ul>/<ol>").toBe(true);
    // Six "> " markers in the source, so six nested quote levels — proof the
    // nesting is parsed rather than flattened at a cap.
    expect(structure.quoteDepth, "all six quote levels must be represented").toBe(6);
  });
});
