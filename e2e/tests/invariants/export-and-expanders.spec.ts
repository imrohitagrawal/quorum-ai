// WP-F / F-12 (triage issue #3) — the export carries the whole run, and long
// sections can be collapsed.
//
// EXPORT. "Export" wrote four lines: the question, the verdict, an agreement
// count and the run id. Everything the run actually produced — the synthesis
// sections, the sources, where each model stood, the debate rounds — was left
// behind, from a button whose file is named `quorum-<run>.md`. A user
// exporting a decision record got a receipt instead.
//
// EXPANDERS. WP-F also stopped discarding billed section text, so a section
// may now be ~12_000 characters where it used to be cut at 4000. That makes a
// long section a wall of text to scroll past. Sections that run long collapse
// to a readable height with a control to open them; SHORT sections must not
// grow a control they do not need.
import { test, expect } from "@playwright/test";
import { driveToResult } from "../../fixtures/golden-run";

// Read the Blob the export writes, without touching the filesystem: stub
// URL.createObjectURL, click, then read back the Blob's text.
async function exportedMarkdown(page: import("@playwright/test").Page): Promise<string> {
  await page.evaluate(() => {
    const w = window as unknown as { __exported?: Promise<string> };
    const real = URL.createObjectURL.bind(URL);
    URL.createObjectURL = (blob: Blob) => {
      w.__exported = blob.text();
      return real(blob);
    };
  });
  await page.locator("#result-export").click();
  return page.evaluate(() => {
    const w = window as unknown as { __exported?: Promise<string> };
    return w.__exported ?? Promise.resolve("");
  });
}

test.describe("F-12 — export completeness and section expanders", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "chromium-only gate");

  test("the export carries every part of the run, not a four-line receipt", async ({ page }) => {
    await driveToResult(page);
    const md = await exportedMarkdown(page);

    // The question and the verdict — what the old export already had.
    expect(md).toContain(
      "What are the key metrics for measuring SaaS customer retention?"
    );
    expect(md).toMatch(/aligned/i);

    // Every synthesis section the view renders.
    for (const heading of ["Consensus", "Disagreement", "Uncertainty", "Recommendation"]) {
      expect(md, `the export is missing the ${heading} section`).toContain(heading);
    }
    // Section BODIES, not just their headings.
    expect(md).toContain("instrument first, export second");
    expect(md).toContain("Ship the retention-instrumentation slice first");

    // Provenance: every cited source, including the ones behind "+N more".
    expect(md).toContain("https://example.com/a");
    expect(md).toContain("https://example.com/e");

    // Where each model stood, and the debate that moved them.
    expect(md, "the export omits the per-model positions").toMatch(/GPT-4o-mini/);
    expect(md, "the export omits the debate rounds").toMatch(/Round 2/);
    expect(md).toContain("residual disagreement on sequencing");

    // The run id, so the record can be traced back.
    expect(md).toContain("corr-golden-0001");
  });

  test("the export is Markdown a reader can actually read", async ({ page }) => {
    await driveToResult(page);
    const md = await exportedMarkdown(page);
    // Real headings, not a run-on block.
    expect(md).toMatch(/^#{1,3} /m);
    // The provider's own Markdown is preserved verbatim — this is a Markdown
    // file, so `**bold**` is correct here and must NOT be flattened the way the
    // DOM renderer flattens it.
    expect(md).toContain("**");
    // No HTML leaked from the DOM into the Markdown.
    expect(md).not.toMatch(/<\/?(p|ul|ol|li|strong|em|div|span)\b/);
  });

  test("a long synthesis section collapses and can be expanded", async ({ page }) => {
    await driveToResult(page);
    // The fixture's disagreement section is the long one.
    const row = page.locator('.result-synth-row[data-section="disagreement"]');
    await expect(row).toBeVisible();
    const toggle = row.locator("button.result-synth-expand");
    await expect(
      toggle,
      "a section long enough to be clipped must offer a way to open it"
    ).toBeVisible();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");

    const body = row.locator(".result-synth-body");
    const collapsed = await body.evaluate((el) => el.getBoundingClientRect().height);
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    const expanded = await body.evaluate((el) => el.getBoundingClientRect().height);
    expect(
      expanded,
      "expanding must actually reveal more of the section"
    ).toBeGreaterThan(collapsed);

    // And nothing is clipped once open.
    const clipped = await body.evaluate(
      (el) => el.scrollHeight > el.clientHeight + 1
    );
    expect(clipped, "the expanded section still clips its own text").toBe(false);
  });

  test("a short section does not grow a pointless control", async ({ page }) => {
    await driveToResult(page);
    // Consensus is two sentences in the fixture — nothing to expand.
    const row = page.locator('.result-synth-row[data-section="consensus"]');
    await expect(row).toBeVisible();
    await expect(
      row.locator("button.result-synth-expand"),
      "a control that reveals nothing is noise, and it would also make the " +
        "test above pass for a reason that has nothing to do with length"
    ).toHaveCount(0);
  });
});
