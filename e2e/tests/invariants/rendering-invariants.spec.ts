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
