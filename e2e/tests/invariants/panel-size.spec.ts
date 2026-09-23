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
 * Third pull request (CHG-011, decided 2026-09-23):
 *   - the composer's shape line (D5) reads the served shape off /status and the
 *     rendered count: four, three, two, three again (red if the line stops
 *     following remove/add, names the other shape, or is reworded);
 *   - the transcript's model-card tooltip (D6) reads the run's size and its
 *     rounds' critique_shape (red if "all four" comes back at two, or the
 *     moderator wording is served on a peer run);
 *   - the landing-to-composer message (D6) names the composer's current panel
 *     (red if "your four models" is served after a removal).
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
  goldenRespWithPeerDebate,
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

  // CHG-011 D5. Both shapes' sentences are pinned WHOLE so a reworded line is
  // red, and the served shape is read off /status (`peer_critique_in_effect`,
  // the same server-side predicate that fills the readiness island) rather
  // than assumed: CI serves the moderator shape, production does today too.
  const SHAPE_LINE = {
    moderator: {
      4:
        "This run: a moderator model critiques all four answers, in two rounds, then one sourced synthesis. " +
        "Peer critique, where each model critiques the others, is available and off on this deployment.",
      3:
        "This run: a moderator model critiques all three answers, in two rounds, then one sourced synthesis. " +
        "Peer critique, where each model critiques the others, is available and off on this deployment.",
      2:
        "This run: a moderator model critiques both answers, in two rounds, then one sourced synthesis. " +
        "Peer critique, where each model critiques the others, is available and off on this deployment.",
    },
    peer: {
      4: "This run: each of the four models critiques the others, in two rounds, then one sourced synthesis.",
      3: "This run: each of the three models critiques the others, in two rounds, then one sourced synthesis.",
      2: "This run: both models critique each other, in two rounds, then one sourced synthesis.",
    },
  } as const;

  test("the composer's shape line reads the served shape and the count: four, three, two, three", async ({
    page,
  }) => {
    const status = await (await page.request.get("/status")).json();
    // RED IF: /status stops reporting the predicate; defaulting would let the
    // spec assert the wrong shape silently.
    expect(typeof status.peer_critique_in_effect).toBe("boolean");
    const shape: "peer" | "moderator" = status.peer_critique_in_effect ? "peer" : "moderator";

    await boot(page);
    const line = page.locator("#panel-shape-line");
    await expect(line).toBeVisible();
    await expect(line).toHaveAttribute("data-shape", shape);
    await expect(line).toHaveAttribute("data-panel-size", "4");
    await expect(line).toHaveText(SHAPE_LINE[shape][4]);

    await removeButtons(page).nth(3).click();
    await expect(slotInputs(page)).toHaveCount(3);
    await expect(line).toHaveAttribute("data-panel-size", "3");
    await expect(line).toHaveText(SHAPE_LINE[shape][3]);

    await removeButtons(page).nth(2).click();
    await expect(slotInputs(page)).toHaveCount(2);
    await expect(line).toHaveAttribute("data-panel-size", "2");
    await expect(line).toHaveText(SHAPE_LINE[shape][2]);

    await addButton(page).click();
    await expect(slotInputs(page)).toHaveCount(3);
    await expect(line).toHaveText(SHAPE_LINE[shape][3]);

    // The static honesty rule: under the moderator shape the first sentence
    // never claims the models critique each other; the availability sentence
    // is the only place that mechanism is named, and it says "off".
    const text = (await line.textContent()) ?? "";
    expect(text.length).toBeGreaterThan(80);
    if (shape === "moderator") {
      expect(text.split(". ")[0]).not.toContain("critique each other");
      expect(text).toContain("off on this deployment");
    } else {
      expect(text).not.toContain("moderator");
    }
  });

  test("the transcript's model-card tooltip reads the run's size and its shape", async ({ page }) => {
    // A moderator run of two: "both", never "all four".
    await driveToResult(page, goldenRespWithPanelSize(2, { consensus: true }));
    await driveToTranscript(page);
    const info = page.locator("article.model-card [data-info-icon]");
    await expect(info).toHaveCount(2);
    for (let i = 0; i < 2; i++) {
      await expect(info.nth(i)).toHaveAttribute(
        "data-info-text",
        "This shows one model's answer. It is the model's only answer — it is not revised. " +
          "Once both respond, a separate moderator model reads both and writes the debate critique.",
      );
    }
    // A peer run of four: each model reads the others; no moderator is named.
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await driveToResult(page, goldenRespWithPeerDebate());
    await driveToTranscript(page);
    const peerInfo = page.locator("article.model-card [data-info-icon]");
    await expect(peerInfo).toHaveCount(4);
    await expect(peerInfo.first()).toHaveAttribute(
      "data-info-text",
      "This shows one model's answer. It is the model's only answer — it is not revised. " +
        "Once all four respond, each model reads the others and writes its own critique.",
    );
    const peerText = (await peerInfo.first().getAttribute("data-info-text")) ?? "";
    expect(peerText.length).toBeGreaterThan(80);
    expect(peerText).not.toContain("moderator");
  });

  test("the landing-to-composer message names the composer's current panel", async ({ page }) => {
    await boot(page);
    await removeButtons(page).nth(3).click();
    await expect(slotInputs(page)).toHaveCount(3);
    // Back to the landing (the "How it works" link) with three slots held.
    await page.locator("#show-landing").click();
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await page.locator("#landing-query").fill("Which three models agree on retention metrics?");
    await page.locator("#landing-estimate").click();
    const note = page.locator("#landing-handoff-note-text");
    // The note dwells 2.8 s on the landing before the view changes.
    await expect(note).toHaveText(
      "Got your question. Taking you to review your three models and see the itemized cost before anything runs…",
    );
    await expect(note).not.toContainText("four models");
  });

  test("the landing CTA still hands off when clicked before the slot grid has rendered", async ({
    page,
  }) => {
    // Review of the third pull request found this: the hand-off message read
    // the composer's count through getModelIds(), which throws on the
    // template's placeholder labels until /v1/models/defaults has answered.
    // The throw left the hand-off latch set, so the landing CTA was dead until
    // reload. Hold the defaults until after the click and prove the hand-off
    // still happens, with the default count.
    let releaseDefaults: () => void = () => {};
    const held = new Promise<void>((resolve) => {
      releaseDefaults = resolve;
    });
    await page.route("**/v1/models/defaults", async (route) => {
      await held;
      await route.continue();
    });
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await expect(page.locator("#landing-query")).toBeVisible();
    // Positive partner: the grid really is un-rendered at this point.
    expect(await page.locator("select[data-model-slot]").count()).toBe(0);
    await page.locator("#landing-query").fill("Should we adopt passkeys?");
    await page.locator("#landing-estimate").click();
    await expect(page.locator("#landing-handoff-note-text")).toHaveText(
      "Got your question. Taking you to review your four models and see the itemized cost before anything runs…",
    );
    releaseDefaults();
    await expect(page.locator('[data-view="composer"]')).toBeVisible({ timeout: 15000 });
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
