/**
 * W4 (ADR-0120, CHG-010) — the panel is two to four models, four by default.
 *
 * The product owner decided (2026-09-22): a visible remove / add control per
 * slot; range 2..4; and at N=2 with both agreeing a green band that reads
 * "Both models agree (2 of 2)" -- never "The panel's verdict".
 *
 * What this spec pins, and what turns each test red:
 *   - the composer boots with four slots, the add control hidden and remove
 *     enabled (red if the default panel changes or the add control shows at four);
 *   - removing a slot sends THREE model ids, in order, in the POST body
 *     (red if the request body is built from anything but the rendered slots);
 *   - the floor: at two the remove control is disabled AND says so to
 *     assistive tech; add restores three, then four hides add again
 *     (red if either bound moves);
 *   - at N=2 the green band's eyebrow is "Both models agree" and the tally
 *     "2 of 2" (red if the eyebrow keeps "The panel's verdict" at two);
 *   - at N=3 the eyebrow keeps "The panel's verdict" -- the positive partner
 *     (red if the N=2 wording leaks upward);
 *   - a failed slot on a panel of two reads "1 of 2" in the degraded banner
 *     (red if a denominator is hard-coded to four);
 *   - the rendering invariants hold on the N=2 and N=3 fixtures;
 *   - the cost gate's meta line says "2 models" after two removals
 *     (red if the "4 models" literal comes back);
 *   - the transcript renders one card per REQUESTED slot, two at N=2
 *     (red if the cards are keyed off the default panel).
 *
 * The trust cap (ADR-0120 decision 3) is NOT observable here: `support_verified`
 * is always false in CI, so it is unit-tested in tests/unit only.
 *
 * Runs against the real workspace with API routes stubbed. No live calls.
 */
import { test, expect, Page } from "@playwright/test";
import {
  SLOTS,
  boot,
  driveToResult,
  driveToTranscript,
  goldenCreateResp,
  goldenRespWithPanelSize,
} from "../../fixtures/golden-run";
import { waitForComposerReady } from "../../fixtures/stabilize";

const fulfil = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const slotInputs = (page: Page) => page.locator("[data-model-slot]");
const removeButtons = (page: Page) => page.locator("[data-slot-remove]");
const addButton = (page: Page) => page.locator("#model-slot-add");

/**
 * A stubbed estimate for whatever panel the composer currently holds. "allow"
 * lets Run now go straight to the run; "require_confirmation" lands on the
 * cost gate, which is what the meta-line test wants to look at.
 */
async function stubEstimate(page: Page, n: number, action = "allow") {
  await page.route("**/v1/query-runs/estimate", (r) =>
    r.fulfill(
      fulfil({
        correlation_id: "corr-panel-size",
        cost_estimate: {
          estimated_cost_usd: "0.0840",
          currency: "USD",
          threshold_action: action,
          confirmation_token: action === "allow" ? null : "tok-panel-size",
          reasons: [],
          breakdown: { by_model: [], by_stage: [] },
        },
        model_slots: SLOTS.slice(0, n),
        reasons: [],
      }),
    ),
  );
  await page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] })));
  await page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null })));
}

test.describe("panel size: remove / add a slot, N-relative copy (W4)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  test("the composer boots with four slots, add hidden, remove enabled", async ({ page }) => {
    await boot(page);
    await expect(slotInputs(page)).toHaveCount(4);
    await expect(removeButtons(page)).toHaveCount(4);
    for (let i = 0; i < 4; i++) {
      await expect(removeButtons(page).nth(i)).toBeEnabled();
      await expect(removeButtons(page).nth(i)).toHaveAttribute("aria-disabled", "false");
    }
    await expect(addButton(page)).toBeHidden();
    // The controls carry accessible names (axe-all-views scans them too).
    await expect(removeButtons(page).nth(0)).toHaveAttribute("aria-label", /^Remove slot 1 \(.+\)$/);
  });

  test("removing a slot sends three model ids, in order, in the POST body", async ({ page }) => {
    await boot(page);
    const before = await slotInputs(page).evaluateAll((els) =>
      els.map((e) => (e as HTMLSelectElement).value),
    );
    expect(before).toHaveLength(4);

    await removeButtons(page).nth(3).click();
    await expect(slotInputs(page)).toHaveCount(3);
    await waitForComposerReady(page, 3);
    const after = await slotInputs(page).evaluateAll((els) =>
      els.map((e) => (e as HTMLSelectElement).value),
    );
    expect(after).toEqual(before.slice(0, 3));

    let posted: { model_slots?: string[] } | null = null;
    await stubEstimate(page, 3);
    await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) =>
      r.fulfill(fulfil(goldenRespWithPanelSize(3))),
    );
    await page.route(/\/v1\/query-runs$/, (r) => {
      if (r.request().method() !== "POST") return r.continue();
      posted = r.request().postDataJSON();
      return r.fulfill(fulfil(goldenCreateResp()));
    });
    await page.getByRole("textbox").first().fill("Which three models agree on retention metrics?");
    await page.locator("#run-now").click();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });

    expect(posted, "the create request must have been sent").not.toBeNull();
    expect(posted!.model_slots).toEqual(before.slice(0, 3));
    // Slot numbers are assigned server-side by position; the client sends ids only.
    expect(posted!.model_slots).toHaveLength(3);
    // The result view echoes the requested panel: three, not four.
    await expect(page.locator(".result-verdict-agreement").first()).toContainText("of 3");
  });

  test("the floor is two: remove is disabled and aria-disabled, add restores three then four", async ({
    page,
  }) => {
    await boot(page);
    await removeButtons(page).nth(3).click();
    await expect(slotInputs(page)).toHaveCount(3);
    await expect(addButton(page)).toBeVisible();
    await removeButtons(page).nth(2).click();
    await expect(slotInputs(page)).toHaveCount(2);
    await expect(removeButtons(page)).toHaveCount(2);
    for (let i = 0; i < 2; i++) {
      await expect(removeButtons(page).nth(i)).toBeDisabled();
      await expect(removeButtons(page).nth(i)).toHaveAttribute("aria-disabled", "true");
    }
    // A forced click on the disabled control must not go below two.
    await removeButtons(page).nth(0).dispatchEvent("click");
    await expect(slotInputs(page)).toHaveCount(2);

    await addButton(page).click();
    await expect(slotInputs(page)).toHaveCount(3);
    await expect(removeButtons(page).nth(0)).toBeEnabled();
    await expect(addButton(page)).toBeVisible();
    await addButton(page).click();
    await expect(slotInputs(page)).toHaveCount(4);
    await expect(addButton(page)).toBeHidden();
    // Added slots are populated (the next unused default), never blank.
    const ids = await slotInputs(page).evaluateAll((els) =>
      els.map((e) => (e as HTMLSelectElement).value.trim()),
    );
    expect(ids.every((id) => id.length > 0)).toBe(true);
    expect(new Set(ids).size).toBe(4);
  });

  test("at N=2 with both agreeing the band reads 'Both models agree' and '2 of 2'", async ({
    page,
  }) => {
    await driveToResult(page, goldenRespWithPanelSize(2, { consensus: true }));
    const band = page.locator("#result-verdict");
    await expect(band).toHaveAttribute("data-consensus", "true");
    await expect(band.locator(".result-verdict-eyebrow")).toHaveText("Both models agree");
    await expect(band.locator(".result-verdict-agreement").first()).toContainText("2 of 2");
    const text = (await band.textContent()) || "";
    expect(text).not.toContain("panel's verdict");
    expect(text).not.toContain("of 4");
    // The debate-rounds caption names the requested panel too.
    await expect(page.locator(".result-debate-caption")).toContainText(
      "covering both answers together",
    );
  });

  test("at N=3 with all agreeing the band keeps 'The panel's verdict' and '3 of 3'", async ({
    page,
  }) => {
    await driveToResult(page, goldenRespWithPanelSize(3, { consensus: true }));
    const band = page.locator("#result-verdict");
    await expect(band).toHaveAttribute("data-consensus", "true");
    await expect(band.locator(".result-verdict-eyebrow")).toHaveText("The panel's verdict");
    await expect(band.locator(".result-verdict-agreement").first()).toContainText("3 of 3");
    expect(((await band.textContent()) || "").includes("Both models agree")).toBe(false);
    await expect(page.locator(".result-debate-caption")).toContainText(
      "covering all three answers together",
    );
  });

  test("a failed slot on a panel of two reads '1 of 2' in the degraded banner", async ({ page }) => {
    await driveToResult(page, goldenRespWithPanelSize(2, { failedSlots: 1 }));
    const banner = page.locator("#result-degraded");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText(/1 of 2/);
    await expect(banner).not.toContainText(/of 4/);
  });

  test("rendering invariants hold on the N=2 and N=3 fixtures", async ({ page }) => {
    for (const n of [2, 3] as const) {
      await driveToResult(page, goldenRespWithPanelSize(n, { consensus: n === 2 }));
      const scan = await page.evaluate(() => {
        const scope = document.querySelector("#main-content") || document.body;
        const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
        const raw: string[] = [];
        let node: Node | null;
        let walked = 0;
        while ((node = walker.nextNode())) {
          const parent = node.parentElement;
          if (!parent || parent.closest("code, pre")) continue;
          const text = node.textContent || "";
          if (!text.trim()) continue;
          walked += 1;
          if (/\*\*|^\s*#{1,6}\s|\]\(https?:\/\/|`[^`]+`/.test(text)) raw.push(text.trim().slice(0, 60));
        }
        const overflow = document.documentElement.scrollWidth > document.documentElement.clientWidth;
        return { raw, walked, overflow };
      });
      // Positive partner in the shape check-negative-assertions.mjs recognises
      // (`toBeGreaterThanOrEqual(<positive literal>)`): "no raw Markdown" is
      // trivially true of a page that rendered nothing.
      expect(scan.walked, `N=${n}: the walker must have visited text`).toBeGreaterThanOrEqual(20);
      expect(scan.raw, `N=${n}: raw Markdown survived`).toEqual([]);
      expect(scan.overflow, `N=${n}: horizontal overflow`).toBe(false);
    }
  });

  test("the cost gate's meta line names the requested panel: '2 models'", async ({ page }) => {
    await boot(page);
    await removeButtons(page).nth(3).click();
    await removeButtons(page).nth(2).click();
    await expect(slotInputs(page)).toHaveCount(2);
    await stubEstimate(page, 2, "require_confirmation");
    await page.getByRole("textbox").first().fill("Which two models agree on retention metrics?");
    await page.getByRole("button", { name: /see the estimate|estimate cost/i }).click();
    await expect(page.locator("#gate-confirm")).toBeVisible({ timeout: 15000 });
    const meta = page.locator("#cost-gate-question-meta");
    await expect(meta).toContainText(/^2 models/);
    await expect(meta).not.toContainText("4 models");
  });

  test("the transcript renders one card per requested slot: two at N=2, four by default", async ({
    page,
  }) => {
    await driveToResult(page, goldenRespWithPanelSize(2, { consensus: true }));
    await driveToTranscript(page);
    await expect(page.locator("article.model-card")).toHaveCount(2);
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await driveToResult(page);
    await driveToTranscript(page);
    await expect(page.locator("article.model-card")).toHaveCount(4);
  });
});
