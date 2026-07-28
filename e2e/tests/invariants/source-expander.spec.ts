// WP-F / F-19 — the "+N more" sources affordance.
//
// The synthesis Sources row caps its chip list at 3 and appends a "+N more"
// note for the rest. That note was a plain <span>: it told the user their run
// had cited sources they could not reach, and offered no way to reach them.
// The remaining sources were rendered nowhere at all — not hidden, simply
// never built. This is provenance the product asks users to judge answers on.
//
// It was also untestable until WP-F. The golden fixture deduped to TWO unique
// sources, below the cap, so the branch never executed in any test run — a
// gate cannot catch what the fixture cannot express. The fixture now carries
// five unique sources across the slots (two of them shared, so dedupe is still
// exercised).
import { test, expect } from "@playwright/test";
import { driveToResult } from "../../fixtures/golden-run";

test.describe("F-19 — the rest of the cited sources are reachable", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "chromium-only gate");

  test("the collapsed row shows three chips and an expander for the rest", async ({ page }) => {
    await driveToResult(page);
    const row = page.locator(".result-synth-source-chips");
    await expect(row).toBeVisible();
    await expect(row.locator(".result-source-chip:visible")).toHaveCount(3);
    const more = row.locator("button.result-source-more");
    await expect(
      more,
      "the '+N more' affordance must be a real button. As a <span> it announced " +
        "sources the user had no way to open, and screen-reader and keyboard " +
        "users had nothing to operate at all."
    ).toBeVisible();
    await expect(more).toHaveAttribute("aria-expanded", "false");
  });

  test("expanding reveals every remaining source, and collapsing hides them again", async ({ page }) => {
    await driveToResult(page);
    const row = page.locator(".result-synth-source-chips");
    const more = row.locator("button.result-source-more");
    await more.click();
    await expect(more).toHaveAttribute("aria-expanded", "true");
    // Five unique sources in the fixture, so all five chips are now on screen.
    // `:visible` matters here: the collapsed chips stay ATTACHED and hidden,
    // so a plain count would read 5 in both states and could never fail.
    await expect(row.locator(".result-source-chip:visible")).toHaveCount(5);
    for (const chip of await row.locator(".result-source-chip").all()) {
      await expect(chip).toBeVisible();
    }
    await more.click();
    await expect(more).toHaveAttribute("aria-expanded", "false");
    await expect(row.locator(".result-source-chip:visible")).toHaveCount(3);
  });

  test("the revealed chips keep their real numbering and their links", async ({ page }) => {
    await driveToResult(page);
    const row = page.locator(".result-synth-source-chips");
    await row.locator("button.result-source-more").click();
    const nums = await row.locator(".result-source-chip:visible .result-source-num").allTextContents();
    expect(
      nums,
      "citation numbers must stay stable and continue past the cap — a source " +
        "the prose calls [4] cannot appear as [1] once revealed"
    ).toEqual(["1", "2", "3", "4", "5"]);
    // Every fixture source is a real https URL, so every chip is a safe link.
    await expect(row.locator("a.result-source-chip:visible")).toHaveCount(5);
  });

  test("the expander is operable from the keyboard", async ({ page }) => {
    await driveToResult(page);
    const more = page.locator(".result-synth-source-chips button.result-source-more");
    await more.focus();
    await expect(more).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(more).toHaveAttribute("aria-expanded", "true");
  });
});
