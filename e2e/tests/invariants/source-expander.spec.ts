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
import { driveToResult, goldenCompletedResp } from "../../fixtures/golden-run";

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

  test("a Quorum stub source is never a clickable citation", async ({ page }) => {
    // A stub source is Quorum's own placeholder, not evidence: it points at the
    // IANA-reserved example.test domain, which never resolves. `renderStubSource`
    // has refused to make those anchors elsewhere for exactly that reason, but
    // `collectResultSources` used to DROP the `provider` field, so the synthesis
    // chip row could not tell a stub from a real citation and linked it anyway.
    // F-19 made every source reachable, which turned that into a row of dead
    // links dressed as provenance.
    const resp = goldenCompletedResp() as any;
    resp.result.model_answers[0].sources = [
      {
        title: "Local demo evidence for slot 1",
        url: "https://example.test/local-demo/1",
        provider: "local_simulation",
      },
    ];
    await driveToResult(page, resp);
    const row = page.locator(".result-synth-source-chips");
    await expect(row).toBeVisible();

    const stub = row.locator(".result-source-chip", { hasText: "Local demo evidence" });
    await expect(stub).toHaveCount(1);
    expect(
      await stub.first().evaluate((el) => el.tagName),
      "a stub source was rendered as an anchor — clicking it opens a dead tab, " +
        "and it reads as a real citation"
    ).toBe("SPAN");
    expect(await stub.first().evaluate((el) => el.hasAttribute("href"))).toBe(false);
    // And it is LABELLED, not merely un-linked: an unmarked stub still reads as
    // evidence to someone judging the answer by its sources.
    await expect(stub.first().locator(".result-source-stub-tag")).toHaveText(/simulated/i);

    // Positive control, same run: a genuine https source is still a real link.
    // Without this the assertions above would also pass if NOTHING linked.
    const real = row.locator("a.result-source-chip", { hasText: "Jones & Lee" });
    await expect(real).toHaveCount(1);
    await expect(real).toHaveAttribute("href", "https://example.com/b");
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
