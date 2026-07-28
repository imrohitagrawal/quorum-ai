import { test, expect, Page } from "@playwright/test";
import {
  driveToResult,
  driveToTranscript,
  driveDecreasingTimer,
  parseElapsedMs,
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
        return offenders;
      },
      {
        scopeSelector,
        patterns: RAW_MARKDOWN_PATTERNS.map((p) => ({ name: p.name, re: p.re.source, flags: p.re.flags })),
      }
    );
  }

  test("no raw Markdown control syntax survives in the RESULT view (#30)", async ({ page }) => {
    await driveToResult(page);
    const offenders = await collectRawMarkdown(page, "#main-content");
    expect(
      offenders,
      `Raw Markdown leaked into rendered text (a surface bypassed the formatter):\n` +
        offenders.map((o) => `  [${o.pattern}] "${o.snippet}"  @ ${o.where}`).join("\n")
    ).toEqual([]);
  });

  test("no raw Markdown control syntax survives in the TRANSCRIPT view (#30)", async ({ page }) => {
    await driveToResult(page);
    await driveToTranscript(page);
    const offenders = await collectRawMarkdown(page, "#main-content");
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
      lists: el.querySelectorAll("ul").length,
      items: el.querySelectorAll("ul li").length,
      emptyParagraphs: [...el.querySelectorAll("p")].filter(
        (p) => !(p.textContent || "").trim()
      ).length,
    }));
    expect(
      shape.lists,
      `expected exactly ONE <ul> for the six-item list; saw ${shape.lists}. ` +
        "More than one means each line became its own single-item list."
    ).toBe(1);
    expect(shape.items, "the six seeded bullets must all be <li> of that list").toBe(6);
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
