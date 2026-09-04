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

// Read the Blob the export writes, without touching the filesystem — same
// technique as export-and-expanders.spec.ts.
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

  test("a really-retrieved page is a real citation, not a stub (ADR-0098)", async ({
    page,
  }) => {
    // MEASURED DEFECT. With live execution on, a model that answers with NO
    // citations gets real pages attached by web search (the _tavily_search
    // supplement inside produce_initial_answer's live-answer arm).
    // Those arrived as provider "fallback_search" / is_fallback true — byte
    // identical to the example.test placeholder Quorum writes itself — so the
    // chip row badged a real Reuters URL "fallback stub" and refused to link
    // it, and the export wrote "fallback stub, not a real source".
    //
    // RED before the fix: the chip is a SPAN with a stub tag.
    const resp = goldenCompletedResp() as any;
    resp.result.model_answers[0].sources = [
      {
        title: "Reuters investigation",
        url: "https://reuters.example/a1",
        provider: "web_search",
        // Still true, and deliberately so: a retrieved page is not the MODEL's
        // own citation, so it must not raise citation coverage. The badge must
        // no longer key on this flag.
        is_fallback: true,
      },
      {
        // NEGATIVE PARTNER, same run: the Quorum-authored placeholder must
        // STILL be treated as a stub. Without this, a fix that simply stopped
        // badging everything would pass the assertions above.
        title: "Fallback search evidence for slot 1",
        url: "https://example.test/local-demo/fallback/1",
        provider: "fallback_search",
        is_fallback: true,
      },
    ];
    await driveToResult(page, resp);
    const row = page.locator(".result-synth-source-chips");
    await expect(row).toBeVisible();

    const retrieved = row.locator(".result-source-chip", { hasText: "Reuters investigation" });
    await expect(retrieved).toHaveCount(1);
    expect(
      await retrieved.first().evaluate((el) => el.tagName),
      "a page a real web search returned was rendered as a non-link stub — the " +
        "user is denied the evidence the run actually has"
    ).toBe("A");
    await expect(retrieved.first()).toHaveAttribute("href", "https://reuters.example/a1");
    await expect(retrieved.first().locator(".result-source-stub-tag")).toHaveCount(0);
    // ...but MARKED, not left bare. Un-badging without marking would render it
    // identically to a model-cited source, directly beneath a trust card that
    // (by ADR-0098 Decision 2) still reads "0 sources cited" — one
    // contradiction swapped for another.
    await expect(retrieved.first().locator(".result-source-origin-tag")).toHaveText(
      /web search/i
    );

    const placeholder = row.locator(".result-source-chip", {
      hasText: "Fallback search evidence",
    });
    await expect(placeholder).toHaveCount(1);
    expect(
      await placeholder.first().evaluate((el) => el.tagName),
      "the Quorum-authored example.test placeholder must still not be a link"
    ).toBe("SPAN");
    await expect(placeholder.first().locator(".result-source-stub-tag")).toHaveText(
      /fallback stub/i
    );
  });

  // THE EXPORT. A user-visible surface the chip-row assertions do not reach:
  // a reviewer reverted it and 742 tests plus the blocking lane stayed green
  // while a real Reuters page exported as "not a real source". This is the
  // executing gate for it.
  test("the export marks a retrieved page as real, and a stub as a stub (ADR-0098)", async ({
    page,
  }) => {
    const resp = goldenCompletedResp() as any;
    // LIVE-SHAPED: with live execution on, no example.test stub can exist
    // (a live call that yields nothing FAILS the slot), so this run carries
    // only real pages.
    resp.result.model_answers[0].sources = [
      {
        title: "Reuters investigation",
        url: "https://reuters.example/a1",
        provider: "web_search",
        is_fallback: true,
      },
    ];
    await driveToResult(page, resp);
    const md = await exportedMarkdown(page);

    expect(md, "the export must carry the retrieved page as a real citation").toContain(
      "[Reuters investigation](<https://reuters.example/a1>)"
    );
    expect(md, "and must say where it came from, since it is not the model's own citation")
      .toContain("via web search");
    expect(
      md.includes("Reuters investigation — **fallback stub, not a real source**"),
      "a really-retrieved page must never be exported as 'not a real source'"
    ).toBe(false);
  });

  test("the export still refuses to launder a Quorum placeholder (ADR-0098)", async ({
    page,
  }) => {
    // NEGATIVE PARTNER, in its own DEMO-shaped run: a placeholder only exists
    // when live execution is off, so it gets its own fixture rather than being
    // mixed into the live one above, which the server can never emit.
    const resp = goldenCompletedResp() as any;
    resp.result.model_answers[0].sources = [
      {
        title: "Local demo evidence for slot 1",
        url: "https://example.test/local-demo/1",
        provider: "local_simulation",
        is_fallback: true,
      },
    ];
    await driveToResult(page, resp);
    const md = await exportedMarkdown(page);

    expect(md, "a Quorum-authored placeholder must still be marked").toContain(
      "not a real source"
    );
    expect(
      md.includes("(<https://example.test/local-demo/1>)"),
      "a placeholder must never export as a working citation link"
    ).toBe(false);
    expect(md.includes("via web search"), "and must not claim a web search ran").toBe(false);
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
