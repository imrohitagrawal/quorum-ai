// WP-F — an answer the provider cut short says so, and a per-model notice is
// shown to the person reading that model's answer.
//
// Two honesty surfaces, both of which existed only as data before this:
//
//   `shortened` (WP-D/F-07) crosses the API boundary per answer and means the
//   provider stopped at its token ceiling — the text on screen is the middle
//   of a sentence, not the model's complete view. It appeared ZERO times in
//   app.js, so the product presented a truncated answer as a finished one.
//
//   `provider_notice` (WP-E/F-09) had a render path, but only onto the model
//   card — and `.panel.panel-section { display: none }` hides that entire
//   section on EVERY view, by design, as part of the design-comp parity work.
//   So the nine notices rewritten in WP-E reached the DOM and never reached a
//   user. That is the dead-markup class of issues #111 and #115. This gate
//   asserts the notice where the answer is actually read.
//
// Both assert toBeVisible(), never toBeAttached(): a 0x0 element is exactly
// the failure being fixed, so a gate that accepts attachment would pass over
// the defect it exists to catch.
import { test, expect } from "@playwright/test";
import { driveToResult, driveToTranscript } from "../../fixtures/golden-run";

test.describe("per-answer honesty surfaces", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "chromium-only gate");

  test("an answer the provider cut short is marked as shortened", async ({ page }) => {
    await driveToResult(page);
    await driveToTranscript(page);
    const marked = page.locator(".transcript-opening").filter({ hasText: /shortened/i });
    await expect(
      marked,
      "the fixture's slot-1 answer carries shortened: true. Without a marker " +
        "the reader takes a mid-sentence stop for the model's complete view."
    ).toHaveCount(1);
    await expect(marked.first()).toBeVisible();
  });

  test("only the shortened answer is marked", async ({ page }) => {
    await driveToResult(page);
    await driveToTranscript(page);
    // Three of the four fixture answers are complete. A marker on all of them
    // would be as useless as a marker on none, and would pass the test above.
    await expect(
      page.locator(".transcript-opening").filter({ hasText: /shortened/i })
    ).toHaveCount(1);
    await expect(page.locator(".transcript-opening")).toHaveCount(4);
  });

  test("a per-model provider notice is visible where that answer is read", async ({ page }) => {
    await driveToResult(page);
    await driveToTranscript(page);
    // Slot 3 is the zero-source slot; the fixture carries the registry's
    // NOTICE_NO_SOURCES_FOUND for it, verbatim.
    const notice = page.getByText(
      "This model's answer came back without any linked sources",
      { exact: false }
    );
    await expect(
      notice.first(),
      "a provider notice must be VISIBLE to the reader of that answer. It " +
        "previously rendered only onto the permanently display:none model card."
    ).toBeVisible();
  });
});
