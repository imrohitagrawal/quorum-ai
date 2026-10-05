import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import {
  boot,
  EVAL_CLEAN,
  goldenCompletedResp,
  goldenCreateResp,
  goldenQuickCreateResp,
  goldenQuickResp,
  goldenRunningResp,
  quickEstimateEnvelope,
  withEvaluation,
} from "../../fixtures/golden-run";
import { freeze, waitForComposerReady } from "../../fixtures/stabilize";
import {
  HELP_HINT_IDS,
  HELP_HINT_KEYS,
  helpHintDismissId,
  markHelpSeen,
  TOUR_DIALOG_ID,
  TOUR_HEADING_ID,
  TOUR_OPENER_NAV_ID,
  TOUR_OPENER_PREVIEW_ID,
} from "../../fixtures/help";

/**
 * W48 (ADR-0145) — help for new users: three one-time hints and an optional tour.
 *
 * The owner's words (CHG-027 g): *"contextual help on by default (one short hint
 * per new idea: the cost estimate, the trust score, History; each shown once per
 * device with "Got it"), and an optional 1-minute tour opened only from a "Take
 * the tour" link on the landing page and in "How it works", never automatically,
 * skippable at every step, keyboard and screen-reader accessible, sharing its
 * text with the hints."* Journeys and failure modes:
 * docs/analysis/2026-10-05-w48-help-and-tour-journeys-and-failure-modes.md.
 *
 * THE CONTRACT THIS FILE FIXES (names in e2e/fixtures/help.ts):
 *   - hints: `#help-hint-estimate` (on the cost gate, above `#cost-review-card`),
 *     `#help-hint-trust` (on a panel result, above `#result-trust-score`),
 *     `#help-hint-history` (signed in only; tested in
 *     tests/signed-in/help-history-hint.spec.ts). Each is `role="note"` with an
 *     accessible name, in the page flow (not absolute/fixed), outside the thing
 *     it explains, not a live region, takes no focus, and holds its idea's text
 *     from `helpTextTable().hints` plus a "Got it" button `#<hint id>-dismiss`.
 *   - "Got it" hides the hint and writes `"1"` to `quorum.hintSeen.<idea>`; a
 *     stored "1" keeps it hidden; a failed read shows it; a failed write still
 *     hides it for the life of the page.
 *   - tour openers: `#landing-tour` (landing nav row) and
 *     `#landing-preview-tour` (end of `.landing-preview`), both "Take the tour".
 *   - tour: `#help-tour`, `role="dialog"`, `aria-modal="true"`,
 *     `aria-labelledby="help-tour-heading"`; `#help-tour-heading` names the
 *     step ("Step N of 5") and takes focus on open and on every step;
 *     `#help-tour-text` is the step's text from `helpTextTable().tour`; buttons
 *     "Back" (disabled on step 1), "Next" (steps 1-4), "Done" (step 5) and
 *     "Skip the tour" on every step; Tab stays inside; Escape closes it and
 *     reaches nothing else; focus returns to the opener; reopening starts at
 *     step 1; no animation; never opened by anything but a click on an opener.
 *
 * These tests start WITHOUT the hint keys (fresh browser storage), unlike every
 * other spec, whose boot helpers call `markHelpSeen` (ADR-0145 decision 6).
 *
 * Journey 1 runs against the REAL backend (the estimate is free; one simulated
 * run, $0). Other tests mock run responses with the golden fixture and say so.
 */

const fulfil = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const QUESTION = "What are the key metrics for measuring SaaS customer retention?";
const LANDING_TYPED = "Should we adopt passkeys by 2027?";
const TOUR_STEPS = 5;

const hint = (page: Page, idea: keyof typeof HELP_HINT_IDS) => page.locator(`#${HELP_HINT_IDS[idea]}`);
const gotIt = (page: Page, idea: keyof typeof HELP_HINT_IDS) => page.locator(`#${helpHintDismissId(idea)}`);
const tour = (page: Page) => page.locator(`#${TOUR_DIALOG_ID}`);
const tourHeading = (page: Page) => page.locator(`#${TOUR_HEADING_ID}`);
const tourButton = (page: Page, name: string) => tour(page).getByRole("button", { name, exact: true });

/** Click a "Take the tour" control, failing fast (and by name) when it is missing. */
async function openTour(page: Page, openerId: string = TOUR_OPENER_NAV_ID) {
  const opener = page.locator(`#${openerId}`);
  await expect(opener, `#${openerId} ("Take the tour") is on the landing`).toBeVisible();
  await opener.click();
}

/** Land on the composer as a returning visitor, with NO hint marked seen. */
async function bootWithoutHelpSeen(page: Page) {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem("quorum.workspaceSeen", "1");
    } catch (_) {}
  });
  await page.goto("/ui", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-view="composer"]')).toBeVisible();
  await waitForComposerReady(page);
}

/** On the composer: ask, press "See the estimate", wait for the cost gate (real backend unless routed). */
async function openCostGate(page: Page, question = QUESTION) {
  await page.locator("#query-text").fill(question);
  await page.locator("#estimate-run").click();
  await expect(page.locator('[data-view="cost-gate"]')).toBeVisible({ timeout: 15000 });
  await expect(page.locator("#cost-review-card")).toBeVisible();
}

/** Mock a panel run that completes with a trust score (golden fixture + EVAL_CLEAN). */
async function routePanelRun(page: Page) {
  const created = goldenCreateResp();
  await page.route("**/v1/query-runs/estimate", (r) =>
    r.fulfill(fulfil({ correlation_id: "corr-help-est", cost_estimate: created.cost_estimate, model_slots: created.model_slots, reasons: [] })),
  );
  await page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] })));
  await page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null })));
  await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) =>
    r.fulfill(fulfil(withEvaluation(goldenCompletedResp(), EVAL_CLEAN))),
  );
  await page.route(/\/v1\/query-runs$/, (r) =>
    r.request().method() === "POST" ? r.fulfill(fulfil(goldenCreateResp())) : r.continue(),
  );
}

async function runToPanelResult(page: Page) {
  await page.locator("#query-text").fill(QUESTION);
  await page.locator("#run-now").click();
  await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
  await expect(page.locator("#result-trust-score")).toBeVisible();
}

/** Where a hint sits relative to the element it explains, in one read. */
async function placement(page: Page, hintId: string, targetSelector: string) {
  return page.evaluate(
    ([h, t]) => {
      const hintEl = document.getElementById(h) as HTMLElement;
      const target = document.querySelector(t) as HTMLElement;
      const hr = hintEl.getBoundingClientRect();
      const tr = target.getBoundingClientRect();
      let liveAncestor: string | null = null;
      for (let n: HTMLElement | null = hintEl; n; n = n.parentElement) {
        const live = n.getAttribute("aria-live");
        const role = n.getAttribute("role");
        if ((live && live !== "off") || role === "status" || role === "alert" || role === "log") {
          liveAncestor = n.id || n.className || n.tagName;
          break;
        }
      }
      return {
        inside: target.contains(hintEl),
        wraps: hintEl.contains(target),
        above: hr.bottom <= tr.top + 1,
        overlaps: !(hr.right <= tr.left || hr.left >= tr.right || hr.bottom <= tr.top || hr.top >= tr.bottom),
        position: getComputedStyle(hintEl).position,
        role: hintEl.getAttribute("role"),
        liveAncestor,
        focusInside: hintEl.contains(document.activeElement),
      };
    },
    [hintId, targetSelector] as const,
  );
}

/** Assert the hint is a labelled, in-flow note above (not inside, not over) what it explains. */
async function expectHintBeside(page: Page, idea: "estimate" | "trust", targetSelector: string) {
  const note = hint(page, idea);
  await expect(note).toBeVisible();
  await expect(note).toHaveAttribute("role", "note");
  await expect(note).toHaveAccessibleName(/\S/);
  await expect(gotIt(page, idea)).toBeVisible();
  await expect(gotIt(page, idea)).toHaveAccessibleName("Got it");
  // The button belongs to its own hint.
  await expect(note.locator(`#${helpHintDismissId(idea)}`)).toHaveCount(1);
  // Let any deferred focus move land before asking where focus is.
  await page.waitForTimeout(500);
  const where = await placement(page, HELP_HINT_IDS[idea], targetSelector);
  expect(where, `${idea} hint placement`).toMatchObject({
    inside: false, // failure mode 7: never inside the card / the trust score
    wraps: false,
    above: true, // ADR-0145 decision 2: above it
    overlaps: false, // failure mode 6: never over it
    liveAncestor: null, // failure mode 14: a note in the reading order, not a live region
    focusInside: false, // ADR-0145 decision 2: it takes no focus
  });
  expect(["static", "relative"], `${idea} hint must be in the page flow`).toContain(where.position);
}

/** The served `helpTextTable()`, run in Node from the very app.js the page loaded. */
async function servedHelpTable(page: Page): Promise<{
  hints: Record<"estimate" | "trust" | "history", string>;
  tour: { idea: string; title: string; text: string }[];
}> {
  const source = await (await page.request.get("/static/app.js")).text();
  const marker = "function helpTextTable(";
  const start = source.indexOf(marker);
  expect(start, "app.js defines helpTextTable() (ADR-0145 decision 1)").toBeGreaterThanOrEqual(0);
  const open = source.indexOf("{", source.indexOf(")", start));
  let depth = 0;
  let end = open;
  for (; end < source.length; end++) {
    if (source[end] === "{") depth++;
    else if (source[end] === "}" && --depth === 0) break;
  }
  // eslint-disable-next-line no-new-func
  return new Function(`${source.slice(start, end + 1)}\nreturn helpTextTable();`)();
}

/** Record whether a dialog is EVER shown, from before app.js runs (an auto-open-then-close is still an auto-open). */
async function watchForAnyDialog(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __dialogSeen: string[] };
    w.__dialogSeen = [];
    const isDialog = (n: Node) =>
      n instanceof HTMLElement && (n.tagName === "DIALOG" || n.getAttribute("role") === "dialog");
    const check = (records: MutationRecord[]) => {
      // A dialog un-hidden or opened at any moment, even if it is hidden again
      // in the same task (the records keep the transition; a later look would not).
      for (const r of records) {
        const t = r.target as HTMLElement;
        if (r.type === "attributes" && isDialog(t)) {
          if (r.attributeName === "hidden" && r.oldValue !== null && !t.hasAttribute("hidden")) w.__dialogSeen.push(t.id || t.tagName);
          else if (r.attributeName === "hidden" && r.oldValue !== null) w.__dialogSeen.push(`${t.id || t.tagName} (unhidden, then hidden again)`);
          if (r.attributeName === "open" && r.oldValue === null) w.__dialogSeen.push(t.id || t.tagName);
        }
      }
      for (const d of Array.from(document.querySelectorAll('[role="dialog"], dialog'))) {
        const el = d as HTMLElement;
        const shown = !el.hidden && (el.tagName !== "DIALOG" || (el as HTMLDialogElement).open) &&
          getComputedStyle(el).display !== "none" && el.getClientRects().length > 0;
        if (shown) w.__dialogSeen.push(el.id || el.tagName);
      }
    };
    new MutationObserver(check).observe(document, { subtree: true, childList: true, attributes: true, attributeOldValue: true });
  });
}

async function setTheme(page: Page, theme: "light" | "dark") {
  await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await page.waitForTimeout(150);
}

async function scanBothThemes(page: Page, label: string) {
  for (const theme of ["light", "dark"] as const) {
    await setTheme(page, theme);
    await freeze(page);
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    const serious = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
    expect(
      serious,
      `${label} [${theme}] critical/serious axe violations:\n` +
        serious.map((v) => `  ${v.impact} ${v.id} @ ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`).join("\n"),
    ).toEqual([]);
  }
}

/** Press Tab (or Shift+Tab) until `id` has focus; return how many presses, or -1. */
async function tabTo(page: Page, id: string, max = 60, key = "Tab"): Promise<number> {
  for (let i = 1; i <= max; i++) {
    await page.keyboard.press(key);
    if ((await page.evaluate(() => document.activeElement?.id ?? "")) === id) return i;
  }
  return -1;
}

test.describe("W48 help for new users: one-time hints (ADR-0145 decisions 2 and 3)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "the help lane runs on the reference engine only");

  test("journey 1: the estimate hint shows once on the first cost gate, and Got it keeps it gone (real backend)", async ({ page }) => {
    // RED-IF: no `#help-hint-estimate` on the first cost gate; or it is not a
    // labelled note above (and outside) `#cost-review-card`; or "Got it" does
    // not hide it and write `quorum.hintSeen.estimate`; or it comes back on the
    // next estimate or after a reload (failure mode 4).
    test.setTimeout(90000);
    // A first visit: fresh storage, the landing, a question handed off.
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await page.locator("#landing-query").fill(QUESTION);
    await page.locator("#landing-estimate").click();
    await expect(page.locator('[data-view="composer"]')).toBeVisible({ timeout: 8000 });
    await waitForComposerReady(page);
    await page.locator("#estimate-run").click();
    await expect(page.locator('[data-view="cost-gate"]')).toBeVisible({ timeout: 15000 });
    await expect(page.locator("#cost-review-card")).toBeVisible();

    await expectHintBeside(page, "estimate", "#cost-review-card");
    // The hint is on the cost gate, not somewhere else on the page.
    await expect(page.locator(`[data-view="cost-gate"] #${HELP_HINT_IDS.estimate}`)).toHaveCount(1);
    expect(await page.evaluate((k) => localStorage.getItem(k), HELP_HINT_KEYS.estimate)).toBeNull();

    await gotIt(page, "estimate").click();
    await expect(hint(page, "estimate")).toBeHidden();
    expect(await page.evaluate((k) => localStorage.getItem(k), HELP_HINT_KEYS.estimate)).toBe("1");

    // The next estimate in this page: the card again, no hint.
    await page.locator("#gate-back").click();
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await page.locator("#estimate-run").click();
    await expect(page.locator("#cost-review-card")).toBeVisible({ timeout: 15000 }); // partner: the gate is there
    await expect(hint(page, "estimate")).toBeHidden();

    // After a reload (this device): the card again, no hint.
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await waitForComposerReady(page);
    await openCostGate(page);
    await expect(hint(page, "estimate")).toBeHidden();
  });

  test("journey 1: the trust-score hint shows once on the first panel result, outside the trust score; no History hint for an anonymous visitor (real backend)", async ({ page }) => {
    // RED-IF: no `#help-hint-trust` on the first panel result, or it sits
    // inside / over `#result-trust-score` (failure mode 7), or "Got it" does
    // not persist; or a History hint appears for an anonymous visitor
    // (failure mode 13).
    test.setTimeout(150000);
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await page.locator("#landing-open-workspace").click();
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await waitForComposerReady(page);

    // Anonymous: no History control, so no History hint (failure mode 13).
    await expect(page.locator("#account-history")).toHaveCount(0);
    await expect(hint(page, "history")).toBeHidden();

    // One real simulated run ($0).
    await page.locator("#query-text").fill(QUESTION);
    await page.locator("#run-now").click();
    const gateConfirm = page.locator("#gate-confirm");
    if (await gateConfirm.isVisible({ timeout: 8000 }).catch(() => false)) await gateConfirm.click();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 90000 });
    await expect(page.locator("#result-trust-score")).toBeVisible();

    await expectHintBeside(page, "trust", "#result-trust-score");
    // The D-2 contract of the trust score is untouched: still no digit inside it.
    expect(await page.locator("#result-trust-score").innerText()).not.toMatch(/\d/);
    // The trust hint just shown is the positive partner for the History
    // negative above: hints DO render for this anonymous visitor, and still
    // none for History.
    await expect(hint(page, "history")).toBeHidden();

    await gotIt(page, "trust").click();
    await expect(hint(page, "trust")).toBeHidden();
    expect(await page.evaluate((k) => localStorage.getItem(k), HELP_HINT_KEYS.trust)).toBe("1");

    // A second panel result after a reload (mocked, so no second spend): no hint.
    await routePanelRun(page);
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await waitForComposerReady(page);
    await runToPanelResult(page); // partner: the trust score is shown
    await expect(hint(page, "trust")).toBeHidden();
  });

  test("the trust-score hint is not shown on a quick answer, where there is no trust score (mocked run)", async ({ page }) => {
    // RED-IF: `#help-hint-trust` shows on a quick answer (ADR-0145 decision 2:
    // "when it is shown"). Positive partner: the same visitor, fresh storage,
    // gets the hint on a panel result (asserted at the end).
    await page.addInitScript(() => {
      try {
        window.localStorage.setItem("quorum.workspaceSeen", "1");
      } catch (_) {}
    });
    await page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(quickEstimateEnvelope())));
    await page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] })));
    await page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null })));
    await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => r.fulfill(fulfil(goldenQuickResp())));
    await page.route(/\/v1\/query-runs$/, (r) =>
      r.request().method() === "POST" ? r.fulfill(fulfil(goldenQuickCreateResp())) : r.continue(),
    );
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await waitForComposerReady(page);
    await page.locator("#quick-mode-input").check();
    await page.locator("#query-text").fill(QUESTION);
    await page.locator("#run-now").click();
    await expect(page.locator('#result-quick[data-mode="quick"]')).toBeVisible({ timeout: 20000 });
    await expect(page.locator("#result-trust-score")).toBeHidden();
    await expect(hint(page, "trust")).toBeHidden();

    // Positive partner: a panel result in a fresh page of the same device shows it.
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await routePanelRun(page);
    await page.reload({ waitUntil: "domcontentloaded" });
    await waitForComposerReady(page);
    if (await page.locator("#quick-mode-input").isChecked()) await page.locator("#quick-mode-input").uncheck();
    await runToPanelResult(page);
    await expect(hint(page, "trust")).toBeVisible();
  });

  test("storage blocked: the hint still shows, Got it hides it for the page's life, and nothing throws (failure mode 5)", async ({ page }) => {
    // RED-IF: with localStorage throwing, `#help-hint-estimate` does not show,
    // or "Got it" leaves it up, or it returns on the next estimate in the same
    // page, or any uncaught error reaches the page.
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.addInitScript(() => {
      const blocked = () => {
        throw new DOMException("storage is blocked", "SecurityError");
      };
      Storage.prototype.getItem = blocked;
      Storage.prototype.setItem = blocked;
      Storage.prototype.removeItem = blocked;
    });
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    // A blocked read of the workspace flag already fails toward the workspace.
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await waitForComposerReady(page);
    // Partner: storage really is blocked in this page.
    expect(
      await page.evaluate(() => {
        try {
          localStorage.getItem("x");
          return false;
        } catch (_) {
          return true;
        }
      }),
    ).toBe(true);

    await openCostGate(page);
    await expect(hint(page, "estimate")).toBeVisible();
    await gotIt(page, "estimate").click();
    await expect(hint(page, "estimate")).toBeHidden();
    await page.locator("#gate-back").click();
    await page.locator("#estimate-run").click();
    await expect(page.locator("#cost-review-card")).toBeVisible({ timeout: 15000 });
    await expect(hint(page, "estimate")).toBeHidden();

    expect(errors, "no uncaught error with storage blocked").toEqual([]);
    // Partner for that empty list: the listener does catch an uncaught error.
    await page.evaluate(() => setTimeout(() => { throw new Error("help-probe"); }, 0));
    await expect.poll(() => errors).toEqual(["help-probe"]);
  });

  test("keyboard: each hint's Got it is reachable by Tab, named, and works from the keyboard", async ({ page }) => {
    // RED-IF: `#help-hint-estimate-dismiss` / `#help-hint-trust-dismiss` cannot
    // be reached with Tab, is not named "Got it", or Enter does not dismiss.
    await bootWithoutHelpSeen(page);
    await openCostGate(page);
    await page.locator("#cost-gate-heading").focus();
    const presses = await tabTo(page, helpHintDismissId("estimate"));
    expect(presses, "Tab reaches the estimate hint's Got it").toBeGreaterThan(0);
    await expect(gotIt(page, "estimate")).toHaveAccessibleName("Got it");
    await page.keyboard.press("Enter");
    await expect(hint(page, "estimate")).toBeHidden();

    await page.unrouteAll({ behavior: "ignoreErrors" });
    await routePanelRun(page);
    await page.locator("#gate-back").click();
    await runToPanelResult(page);
    await page.locator("#result-verdict").evaluate((e) => {
      (e as HTMLElement).tabIndex = -1;
      (e as HTMLElement).focus();
    });
    const toTrust = await tabTo(page, helpHintDismissId("trust"), 120);
    expect(toTrust, "Tab reaches the trust-score hint's Got it").toBeGreaterThan(0);
    await expect(gotIt(page, "trust")).toHaveAccessibleName("Got it");
    await page.keyboard.press("Space");
    await expect(hint(page, "trust")).toBeHidden();
  });

  test("axe: no critical/serious violation with the estimate hint and with the trust-score hint shown, both themes", async ({ page }) => {
    // RED-IF: a hint brings a critical/serious WCAG A/AA violation (contrast,
    // name, landmark) in either theme. The visibility asserts first are the
    // positive partners: without a hint on screen the scan proves nothing.
    test.setTimeout(90000);
    await bootWithoutHelpSeen(page);
    await openCostGate(page);
    await expect(hint(page, "estimate")).toBeVisible();
    await scanBothThemes(page, "cost gate with the estimate hint");

    await page.reload({ waitUntil: "domcontentloaded" });
    await routePanelRun(page);
    await waitForComposerReady(page);
    await runToPanelResult(page);
    await expect(hint(page, "trust")).toBeVisible();
    await scanBothThemes(page, "panel result with the trust-score hint");
  });

  test("phone 390x844: with the estimate hint shown, Approve and Back to edit still take the click (failure mode 6)", async ({ page }) => {
    // RED-IF: `#help-hint-estimate` is missing at phone width, overlaps
    // `#gate-confirm` / `#gate-back`, covers them in paint order, or makes the
    // page scroll sideways.
    await page.setViewportSize({ width: 390, height: 844 });
    await bootWithoutHelpSeen(page);
    await openCostGate(page);
    await expect(hint(page, "estimate")).toBeVisible();
    for (const id of ["gate-confirm", "gate-back"]) {
      await page.locator(`#${id}`).scrollIntoViewIfNeeded();
      const hit = await page.evaluate(
        ([control, hintId]) => {
          const el = document.getElementById(control) as HTMLElement;
          const r = el.getBoundingClientRect();
          const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          const h = (document.getElementById(hintId) as HTMLElement).getBoundingClientRect();
          return {
            reaches: Boolean(top && (top === el || el.contains(top))),
            actual: top ? `${top.tagName.toLowerCase()}${top.id ? "#" + top.id : ""}` : "null",
            overlapsHint: !(h.right <= r.left || h.left >= r.right || h.bottom <= r.top || h.top >= r.bottom),
          };
        },
        [id, HELP_HINT_IDS.estimate] as const,
      );
      expect(hit, `a click on #${id} landed on ${hit.actual}`).toMatchObject({ reaches: true, overlapsHint: false });
    }
    const sideways = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    expect(sideways).toBe(false);
    const box = await hint(page, "estimate").boundingBox();
    expect(box && box.x >= 0 && box.x + box.width <= 390).toBe(true);
  });

  test("existing specs keep their pages: the shared boot marks every hint as seen", async ({ page }) => {
    // RED-IF: `boot()` in fixtures/golden-run.ts stops calling markHelpSeen, so
    // after the build the estimate hint would appear in every spec booted
    // there (failure mode 8). Journey 1 above shows the hint when the keys
    // are absent.
    await boot(page);
    for (const key of Object.values(HELP_HINT_KEYS)) {
      expect(await page.evaluate((k) => localStorage.getItem(k), key), key).toBe("1");
    }
    await openCostGate(page);
    // Positive partners (rule 7), in this test so the guard sees them: the
    // cost gate really opened and the hint is in the page, so "hidden" below
    // means "marked seen", not "never reached the gate" or "never rendered".
    // RED-IF: the cost gate does not open, or the hint markup is removed.
    await expect(page.locator("#cost-review-card")).toBeVisible();
    await expect(hint(page, "estimate")).toBeAttached();
    await expect(hint(page, "estimate")).toBeHidden();
  });
});

test.describe("W48 help for new users: the optional tour (ADR-0145 decisions 4 and 5)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "the help lane runs on the reference engine only");

  test("journey 3: Take the tour in the nav row opens a labelled modal dialog; Next, Back and Skip on every step, Done on step 5; focus returns", async ({ page }) => {
    // RED-IF: `#landing-tour` is missing from `.landing-nav`; or `#help-tour`
    // is not role=dialog + aria-modal=true labelled by `#help-tour-heading`
    // ("Step N of 5"); or the heading is not focused on open and on each step;
    // or a step lacks Back / Skip the tour / Next (Done on 5); or Back does not
    // go back; or Done leaves focus anywhere but the opener; or the question
    // typed on the landing is lost (journey 3).
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await page.locator("#landing-query").fill(LANDING_TYPED);

    const opener = page.locator(`.landing-nav #${TOUR_OPENER_NAV_ID}`);
    await expect(opener).toBeVisible();
    await expect(opener).toHaveAccessibleName("Take the tour");
    await opener.click();

    await expect(tour(page)).toBeVisible();
    await expect(tour(page)).toHaveAttribute("role", "dialog");
    await expect(tour(page)).toHaveAttribute("aria-modal", "true");
    await expect(tour(page)).toHaveAttribute("aria-labelledby", TOUR_HEADING_ID);
    await expect(page.getByRole("dialog", { name: /Step 1 of 5/ })).toBeVisible();

    for (let step = 1; step <= TOUR_STEPS; step++) {
      await expect(tourHeading(page)).toContainText(`Step ${step} of ${TOUR_STEPS}`);
      await expect(tourHeading(page)).toBeFocused();
      await expect(page.getByRole("dialog", { name: new RegExp(`Step ${step} of ${TOUR_STEPS}`) })).toBeVisible();
      await expect(page.locator("#help-tour-text")).toHaveText(/\S/);
      await expect(tourButton(page, "Skip the tour")).toBeVisible();
      await expect(tourButton(page, "Skip the tour")).toBeEnabled();
      await expect(tourButton(page, "Back")).toBeVisible();
      if (step === 1) await expect(tourButton(page, "Back")).toBeDisabled();
      else await expect(tourButton(page, "Back")).toBeEnabled();
      if (step < TOUR_STEPS) {
        await expect(tourButton(page, "Next")).toBeVisible();
        await expect(tourButton(page, "Done")).toHaveCount(0);
      } else {
        await expect(tourButton(page, "Done")).toBeVisible();
        await expect(tourButton(page, "Next")).toHaveCount(0);
      }
      if (step === 2) {
        await tourButton(page, "Back").click();
        await expect(tourHeading(page)).toContainText(`Step 1 of ${TOUR_STEPS}`);
        await expect(tourHeading(page)).toBeFocused();
        await tourButton(page, "Next").click();
        await expect(tourHeading(page)).toContainText(`Step 2 of ${TOUR_STEPS}`);
      }
      if (step < TOUR_STEPS) await tourButton(page, "Next").click();
    }
    await tourButton(page, "Done").click();
    await expect(tour(page)).toBeHidden();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.locator(`#${TOUR_OPENER_NAV_ID}`)).toBeFocused();
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await expect(page.locator("#landing-query")).toHaveValue(LANDING_TYPED);
  });

  test("journey 5: Tab stays inside the open tour, every control is reached and named; Escape closes it and focus returns", async ({ page }) => {
    // RED-IF: Tab or Shift+Tab moves focus out of `#help-tour` (failure mode
    // 3); a tour control is not reachable or unnamed; Escape does not close
    // it or focus does not return to `#landing-tour`; reopening does not start
    // at step 1.
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await openTour(page);
    await expect(tour(page)).toBeVisible();
    await tourButton(page, "Next").click(); // step 2: Back is enabled
    await expect(tourHeading(page)).toContainText("Step 2 of 5");

    const reached = new Set<string>();
    for (const key of ["Tab", "Shift+Tab"]) {
      for (let i = 0; i < 10; i++) {
        await page.keyboard.press(key);
        const where = await page.evaluate((id) => {
          const a = document.activeElement as HTMLElement | null;
          const d = document.getElementById(id);
          return { inside: Boolean(a && d && d.contains(a)), label: a ? (a.textContent || "").trim() : "" };
        }, TOUR_DIALOG_ID);
        expect(where.inside, `${key} #${i + 1} left the tour (focus on "${where.label}")`).toBe(true);
        reached.add(where.label);
      }
    }
    for (const name of ["Back", "Next", "Skip the tour"]) expect([...reached]).toContain(name);
    for (const name of ["Back", "Next", "Skip the tour"]) await expect(tourButton(page, name)).toHaveAccessibleName(name);

    await page.keyboard.press("Escape");
    await expect(tour(page)).toBeHidden();
    await expect(page.locator(`#${TOUR_OPENER_NAV_ID}`)).toBeFocused();
    await expect(page.locator('[data-view="landing"]')).toBeVisible();

    await openTour(page);
    await expect(tourHeading(page)).toContainText("Step 1 of 5");
  });

  test("journey 4: How it works scrolls to the preview, whose own Take the tour opens the tour; Skip returns focus to it", async ({ page }) => {
    // RED-IF: `#landing-preview-tour` is missing from the end of
    // `.landing-preview`, is not in view after the landing's "How it works",
    // does not open the tour, or Skip does not close it and return focus.
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await page.locator("#landing-query").fill(LANDING_TYPED);
    await page.locator("#landing-howitworks").click();
    const opener = page.locator(`.landing-preview #${TOUR_OPENER_PREVIEW_ID}`);
    await expect(opener).toBeVisible();
    await expect(opener).toBeInViewport();
    await expect(opener).toHaveAccessibleName("Take the tour");
    await opener.click();
    await expect(page.getByRole("dialog", { name: /Step 1 of 5/ })).toBeVisible();
    await tourButton(page, "Next").click();
    await tourButton(page, "Skip the tour").click();
    await expect(tour(page)).toBeHidden();
    await expect(page.locator(`#${TOUR_OPENER_PREVIEW_ID}`)).toBeFocused();
    await expect(page.locator("#landing-query")).toHaveValue(LANDING_TYPED);
  });

  test("journey 4: from the composer, the top bar's How it works opens the landing, where Take the tour works", async ({ page }) => {
    // RED-IF: the landing reached from `#show-landing` has no working
    // `#landing-tour`.
    await boot(page);
    await page.locator("#show-landing").click();
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await openTour(page);
    await expect(page.getByRole("dialog", { name: /Step 1 of 5/ })).toBeVisible();
    await expect(tourHeading(page)).toBeFocused();
  });

  test("failure mode 12: opening the tour during a landing hand-off cancels the hand-off and keeps the question", async ({ page }) => {
    // RED-IF: the pending hand-off still fires under the open tour (the view
    // moves to the composer ~2.8 s after "Choose models"), or the hand-off note
    // and disabled buttons are left behind. Partner: journey 1 above shows the
    // same hand-off DOES move to the composer when nothing cancels it.
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await page.locator("#landing-query").fill(LANDING_TYPED);
    await page.locator("#landing-run").click();
    await expect(page.locator("#landing-handoff-note")).toBeVisible();
    await openTour(page);
    await expect(tour(page)).toBeVisible();
    await expect(page.locator("#landing-handoff-note")).toBeHidden();
    await expect(page.locator("#landing-run")).toBeEnabled();
    await page.waitForTimeout(3500); // past the 2.8 s dwell
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await expect(page.locator('[data-view="composer"]')).toBeHidden();
    await expect(tour(page)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(tour(page)).toBeHidden();
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await expect(page.locator("#landing-query")).toHaveValue(LANDING_TYPED);
  });

  test("failure mode 1: the tour never opens by itself — first visit, reload, the workspace, all hints dismissed", async ({ page }) => {
    // RED-IF: any code path shows a dialog without a click on a "Take the
    // tour" control, even briefly (a MutationObserver records every showing
    // from before app.js runs). Positive partner at the end: a click DOES
    // show one, so the watcher and the locator can see a dialog.
    await watchForAnyDialog(page);
    const seen = () => page.evaluate(() => (window as unknown as { __dialogSeen: string[] }).__dialogSeen);

    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await page.waitForTimeout(3000);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(await seen()).toEqual([]);

    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await page.waitForTimeout(3000);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(await seen()).toEqual([]);

    // Into the workspace, then a returning visit with every hint dismissed.
    await page.locator("#landing-open-workspace").click();
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await page.evaluate((keys) => {
      for (const k of keys) localStorage.setItem(k, "1");
    }, Object.values(HELP_HINT_KEYS));
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await page.waitForTimeout(3000);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(await seen()).toEqual([]);

    // Positive partner.
    await page.locator("#show-landing").click();
    await openTour(page);
    await expect(page.getByRole("dialog")).toHaveCount(1);
    expect((await seen()).length).toBeGreaterThan(0);
  });

  test("failure mode 2: with a run active, Escape in the tour closes only the tour — no cancel request (mocked run)", async ({ page }) => {
    // RED-IF: Escape inside `#help-tour` reaches the page-wide handler, which
    // cancels the active run (a DELETE /v1/query-runs/<id>). Partner, in the
    // same page: once the tour is closed, the same Escape DOES send that
    // DELETE, so the run was active and the recorder works.
    const deletes: string[] = [];
    await page.addInitScript(() => {
      try {
        window.localStorage.setItem("quorum.workspaceSeen", "1");
      } catch (_) {}
    });
    await markHelpSeen(page);
    const created = goldenCreateResp();
    await page.route("**/v1/query-runs/estimate", (r) =>
      r.fulfill(fulfil({ correlation_id: "corr-help-est", cost_estimate: created.cost_estimate, model_slots: created.model_slots, reasons: [] })),
    );
    await page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] })));
    await page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null })));
    let elapsed = 1000;
    await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => {
      if (r.request().method() === "DELETE") {
        deletes.push(r.request().url());
        return r.fulfill(fulfil({ ...goldenRunningResp(elapsed), status: "cancelled" }));
      }
      elapsed += 1000;
      return r.fulfill(fulfil(goldenRunningResp(elapsed)));
    });
    await page.route(/\/v1\/query-runs$/, (r) =>
      r.request().method() === "POST" ? r.fulfill(fulfil(goldenCreateResp())) : r.continue(),
    );
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await waitForComposerReady(page);
    await page.locator("#query-text").fill(QUESTION);
    await page.locator("#run-now").click();
    await expect(page.locator('[data-view="live-run"]')).toBeVisible({ timeout: 15000 });

    // The run is still active; put the landing on screen the way "How it
    // works" does (the button is hidden on the live view, so click it in JS).
    await page.evaluate(() => (document.getElementById("show-landing") as HTMLButtonElement).click());
    await expect(page.locator('[data-view="landing"]')).toBeVisible();

    await openTour(page);
    await expect(tour(page)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(tour(page)).toBeHidden();
    await page.waitForTimeout(1000);
    expect(deletes, "Escape in the tour must not cancel the run").toEqual([]);
    await expect(page.locator('[data-view="landing"]')).toBeVisible();

    // Partner: the tour is closed; the page's own Escape now cancels the run.
    await page.keyboard.press("Escape");
    await expect.poll(() => deletes.length).toBe(1);
  });

  test("failure mode 9 at run time: the tour's estimate, trust and History steps show the same words as the hints, from helpTextTable()", async ({ page }) => {
    // RED-IF: a tour step's text is not the table's text for that step, or the
    // estimate / trust-score hint does not carry its table text — the two read
    // different copies (ADR-0145 decision 1).
    test.setTimeout(90000);
    const table = await servedHelpTable(page);
    // Positive partner: the table has the three hints and five steps.
    expect(Object.keys(table.hints).sort()).toEqual(["estimate", "history", "trust"]);
    expect(table.tour.map((s) => s.idea)).toEqual(["ask", "models", "estimate", "trust", "history"]);

    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await openTour(page);
    for (let step = 1; step <= TOUR_STEPS; step++) {
      await expect(page.locator("#help-tour-text")).toHaveText(table.tour[step - 1].text);
      if (step < TOUR_STEPS) await tourButton(page, "Next").click();
    }
    for (const idea of ["estimate", "trust", "history"] as const) {
      expect(table.tour.find((s) => s.idea === idea)?.text).toBe(table.hints[idea]);
    }
    await tourButton(page, "Done").click();

    await page.locator("#landing-open-workspace").click();
    await waitForComposerReady(page);
    await routePanelRun(page);
    await page.unroute("**/v1/query-runs/estimate");
    await page.route("**/v1/query-runs/estimate", (r) =>
      r.fulfill(fulfil({ correlation_id: "corr-help-est", cost_estimate: goldenCompletedResp().cost_estimate, model_slots: goldenCreateResp().model_slots, reasons: [] })),
    );
    await openCostGate(page);
    await expect(hint(page, "estimate")).toContainText(table.hints.estimate);
    await page.locator("#gate-confirm").click();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
    await expect(hint(page, "trust")).toContainText(table.hints.trust);
  });

  test("axe: no critical/serious violation with the tour open, both themes", async ({ page }) => {
    // RED-IF: the open tour brings a critical/serious WCAG A/AA violation in
    // either theme (contrast, name, aria-modal misuse). The visibility assert
    // is the positive partner: without the dialog the scan proves nothing.
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await openTour(page);
    await expect(tour(page)).toBeVisible();
    await scanBothThemes(page, "landing with the tour open");
  });

  test("phone 390x664 and motion: the tour's controls are on screen, nothing scrolls sideways, and the dialog does not animate (failure mode 16)", async ({ page }) => {
    // RED-IF: at 390x664 Next or Skip the tour is off screen, the page gains a
    // horizontal scroll with the tour open, or the dialog has an animation or
    // a transition.
    await page.setViewportSize({ width: 390, height: 664 });
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await openTour(page);
    await expect(tour(page)).toBeVisible();
    await expect(tourButton(page, "Next")).toBeInViewport();
    await expect(tourButton(page, "Skip the tour")).toBeInViewport();
    const m = await page.evaluate((id) => {
      const d = document.getElementById(id) as HTMLElement;
      const cs = getComputedStyle(d);
      return {
        sideways: document.documentElement.scrollWidth > document.documentElement.clientWidth,
        animation: cs.animationName,
        transitions: cs.transitionDuration.split(",").map((s) => parseFloat(s)),
      };
    }, TOUR_DIALOG_ID);
    expect(m.sideways).toBe(false);
    expect(m.animation).toBe("none");
    expect(m.transitions.every((t) => t === 0)).toBe(true);
  });
});

/** The button names a help text tells the reader to press ("press X", "click X"...). */
function namedButtons(text: string): string[] {
  const names: string[] = [];
  const re = /\b(?:press|click|tap|choose|use)\s+(?:the\s+)?["“]?([A-Z][A-Za-z']*(?:\s+[A-Za-z']+)*?)["”]?(?=\s*[,.;:!?]|\s+(?:to|and|or|for|button|first)\b|\s*$)/g;
  for (let m = re.exec(text); m; m = re.exec(text)) names.push(m[1]);
  return names;
}

/** The visible text of the cost gate, without the estimate hint itself. */
async function costGateTextWithoutHint(page: Page): Promise<string> {
  return page.evaluate((hintId) => {
    const gate = document.querySelector('[data-view="cost-gate"]') as HTMLElement;
    const copy = gate.cloneNode(true) as HTMLElement;
    copy.querySelector(`#${hintId}`)?.remove();
    // innerText of a detached node ignores CSS; read only what is shown.
    const hiddenIds = Array.from(gate.querySelectorAll("[hidden]")).map((e) => e.id).filter(Boolean);
    for (const id of hiddenIds) copy.querySelector(`#${id}`)?.remove();
    return (copy.textContent || "").replace(/\s+/g, " ");
  }, HELP_HINT_IDS.estimate);
}

/** Hold the real estimate response until `release()`; record when it is asked for. */
async function holdEstimate(page: Page) {
  let release!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  const state = { asked: false };
  // route.fetch() sends the request to the REAL backend once released, so the
  // page gets a real estimate (and a real confirmation token: a create sent
  // afterwards is a real, simulated $0 run). The hold is what lets the
  // estimate land AFTER the tour has been opened on the landing, which is the
  // race review round 1 reproduced.
  await page.route("**/v1/query-runs/estimate", async (route) => {
    state.asked = true;
    await held;
    const response = await route.fetch();
    await route.fulfill({ response });
  });
  return { state, release: () => release() };
}

/** Record every run create the page sends, with whether the tour was open at that moment. */
async function recordCreates(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __creates: { tourOpen: boolean }[] };
    w.__creates = [];
    const orig = window.fetch.bind(window);
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const method = (init?.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
      if (method === "POST" && /\/v1\/query-runs$/.test(new URL(url, location.href).pathname)) {
        const layer = document.getElementById("help-tour-layer");
        w.__creates.push({ tourOpen: Boolean(layer && !layer.hidden) });
      }
      return orig(input, init);
    };
  });
  return () => page.evaluate(() => (window as unknown as { __creates: { tourOpen: boolean }[] }).__creates);
}

/** Composer → See the estimate (held) → top-bar How it works → Take the tour → release. */
async function estimateLandsUnderTheTour(page: Page) {
  await boot(page);
  const hold = await holdEstimate(page);
  await page.locator("#query-text").fill(QUESTION);
  await page.locator("#estimate-run").click();
  await expect.poll(() => hold.state.asked).toBe(true);
  await page.locator("#show-landing").click();
  await expect(page.locator('[data-view="landing"]')).toBeVisible();
  await openTour(page);
  await expect(tour(page)).toBeVisible();
  hold.release();
  // Positive partner for everything after: the view really did leave the landing.
  await expect(page.locator('[data-view="cost-gate"]')).toBeVisible({ timeout: 15000 });
}

test.describe("W48 review round 1 (ADR-0145): the tour and the page, the help text, phone layout", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "the help lane runs on the reference engine only");

  test("A: an estimate that lands while the tour is open closes the tour and puts focus on the cost gate's heading", async ({ page }) => {
    // RED-IF: setView("cost-gate") runs under the open tour and leaves it open
    // (a90fec3: the dialog stays up over the cost gate, the page behind it
    // inert), or focus ends anywhere but #cost-gate-heading (the opener on the
    // hidden landing, or <body>).
    test.setTimeout(60000);
    await estimateLandsUnderTheTour(page);
    await expect(tour(page)).toBeHidden();
    await expect(page.locator("#cost-gate-heading")).toBeVisible();
    await expect(page.locator("#cost-gate-heading")).toBeFocused();
  });

  for (const key of ["Control+Enter", "Meta+Enter"]) {
    test(`A: ${key} never sends a run create while the tour is open; once it has closed, ${key} on the focused cost gate runs as before`, async ({ page }) => {
      // RED-IF: the page-wide Ctrl/Cmd+Enter handler acts while the tour is
      // open (a90fec3: it confirms the estimate under the dialog and POSTs
      // /v1/query-runs). Partner, same test: with the tour closed and the cost
      // gate visible and focused, the same key sends exactly one create, as it
      // did before W48 — so the recorder sees creates and the key still works.
      test.setTimeout(90000);
      const creates = await recordCreates(page);
      await estimateLandsUnderTheTour(page);
      await page.keyboard.press(key);
      await page.waitForTimeout(1500);
      expect((await creates()).filter((c) => c.tourOpen), "creates sent while the tour was open").toEqual([]);

      // The partner: make sure the tour is closed and the gate has focus, then press again.
      if (await tour(page).isVisible()) await page.keyboard.press("Escape");
      await expect(tour(page)).toBeHidden();
      if ((await creates()).length === 0) {
        await expect(page.locator('[data-view="cost-gate"]')).toBeVisible();
        await page.locator("#cost-gate-heading").focus();
        await page.keyboard.press(key);
      }
      await expect.poll(async () => (await creates()).filter((c) => !c.tourOpen).length).toBe(1);
    });
  }

  test("A: Browser Back while the tour is open closes the tour and puts focus on the result's heading (mocked run)", async ({ page }) => {
    // RED-IF: a popstate that changes the view leaves the tour open over the
    // result (a90fec3), or focus ends on <body>, the hidden opener or anywhere
    // but #result-heading.
    await boot(page);
    await routePanelRun(page);
    await runToPanelResult(page); // history: composer, result
    await page.locator("#result-new-question").click(); // history: composer, result, composer
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await page.locator("#show-landing").click();
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await openTour(page);
    await expect(tour(page)).toBeVisible();
    await page.goBack();
    // Positive partner: Back really moved the page to the result view.
    await expect(page.locator('[data-view="result"]')).toBeVisible();
    await expect(tour(page)).toBeHidden();
    await expect(page.locator("#result-heading")).toBeVisible();
    await expect(page.locator("#result-heading")).toBeFocused();
  });

  test("B: the estimate hint uses only figure words the cost gate itself shows (no 'typical')", async ({ page }) => {
    // RED-IF: the estimate hint names a kind of figure the gate does not show
    // (a90fec3: "typically costs"; the gate shows "estimated", "Planning
    // estimate", "estimated range" and "up to", and ADR-0016 marks the
    // estimate's accuracy UNVERIFIED). Read from the gate the visitor is on.
    await bootWithoutHelpSeen(page);
    await openCostGate(page);
    await expect(hint(page, "estimate")).toBeVisible();
    const hintText = ((await hint(page, "estimate").textContent()) || "").replace(/\s+/g, " ").toLowerCase();
    const gateText = (await costGateTextWithoutHint(page)).toLowerCase();
    const FIGURE_WORDS = ["typical", "typically", "usually", "average", "up to", "worst case", "estimated", "range", "at most", "maximum", "minimum", "exact"];
    const used = FIGURE_WORDS.filter((w) => new RegExp(`\\b${w}\\b`).test(hintText));
    // Partners: the hint does describe the figures, and the gate text was read.
    expect(used.length, `figure words in the hint: ${hintText}`).toBeGreaterThan(0);
    expect(gateText).toContain("estimate");
    const notOnGate = used.filter((w) => !new RegExp(`\\b${w}\\b`).test(gateText));
    expect(notOnGate, `hint figure words the cost gate does not show (gate: ${gateText.slice(0, 400)})`).toEqual([]);
  });

  test("B: read on the landing, the tour names only buttons the visitor can see there", async ({ page }) => {
    // RED-IF: a tour step tells the reader to press a button that is not on
    // the landing (a90fec3, the estimate step: "press See the estimate"; the
    // landing's button is "Estimate").
    // Partners: the extractor finds a named button in a known sentence, and
    // the visibility check finds the landing's own "Estimate" button.
    expect(namedButtons("When you press See the estimate, nothing runs.")).toEqual(["See the estimate"]);
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    const visibleLandingButton = (name: string) =>
      page.evaluate((n) => {
        const view = document.querySelector('[data-view="landing"]') as HTMLElement;
        return Array.from(view.querySelectorAll("button")).some(
          (b) => (b.textContent || "").replace(/\s+/g, " ").trim().replace(/\s*→$/, "").toLowerCase() === n.toLowerCase() &&
            b.getClientRects().length > 0 && getComputedStyle(b).visibility !== "hidden",
        );
      }, name);
    expect(await visibleLandingButton("Estimate")).toBe(true);

    await openTour(page);
    const missing: string[] = [];
    for (let step = 1; step <= TOUR_STEPS; step++) {
      const text = ((await page.locator("#help-tour-text").textContent()) || "").replace(/\s+/g, " ");
      for (const name of namedButtons(text)) {
        if (!(await visibleLandingButton(name))) missing.push(`step ${step}: "${name}"`);
      }
      if (step < TOUR_STEPS) await tourButton(page, "Next").click();
    }
    expect(missing, "buttons the tour names that the landing does not show").toEqual([]);
  });

  for (const size of [
    { width: 390, height: 844 },
    { width: 320, height: 640 },
  ]) {
    test(`D: ${size.width}x${size.height}: on the first cost gate the estimate hint is on screen, and Approve and Back to edit still take the click`, async ({ page }) => {
      // RED-IF: when the cost gate first opens, the estimate hint lies outside
      // the viewport (above or below it) at this size, or #gate-confirm /
      // #gate-back no longer receive a click at their centre.
      await page.setViewportSize(size);
      await bootWithoutHelpSeen(page);
      await openCostGate(page);
      await expect(hint(page, "estimate")).toBeVisible();
      const box = await page.evaluate((id) => {
        const r = (document.getElementById(id) as HTMLElement).getBoundingClientRect();
        return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, vh: window.innerHeight, vw: window.innerWidth };
      }, HELP_HINT_IDS.estimate);
      expect(box.top, `hint box ${JSON.stringify(box)}`).toBeGreaterThanOrEqual(0);
      expect(box.bottom, `hint box ${JSON.stringify(box)}`).toBeLessThanOrEqual(box.vh);
      expect(box.left).toBeGreaterThanOrEqual(0);
      expect(box.right).toBeLessThanOrEqual(box.vw);
      for (const id of ["gate-confirm", "gate-back"]) {
        await page.locator(`#${id}`).scrollIntoViewIfNeeded();
        const hit = await page.evaluate((control) => {
          const el = document.getElementById(control) as HTMLElement;
          const r = el.getBoundingClientRect();
          const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          return { reaches: Boolean(top && (top === el || el.contains(top))), actual: top ? top.tagName + (top.id ? "#" + top.id : "") : "null" };
        }, id);
        expect(hit, `a click on #${id} landed on ${hit.actual}`).toMatchObject({ reaches: true });
      }
    });
  }

  for (const width of [500, 620]) {
    test(`E: at ${width}px the landing header stays one line: the nav buttons share the brand's row`, async ({ page }) => {
      // RED-IF: between 451 and 625px the header wraps to a second line
      // (a90fec3: the below-600px rule forces a break after "Take the tour"
      // even where the whole header fits on one line).
      await page.setViewportSize({ width, height: 800 });
      await page.goto("/ui", { waitUntil: "domcontentloaded" });
      await expect(page.locator('[data-view="landing"]')).toBeVisible();
      const rows = await page.evaluate(() => {
        const ids = ["landing-howitworks", "landing-tour", "landing-open-workspace"];
        const mid = (e: Element) => {
          const r = e.getBoundingClientRect();
          return Math.round(r.top + r.height / 2);
        };
        const brand = document.querySelector(".landing-brand") as HTMLElement;
        return { brand: mid(brand), buttons: ids.map((id) => ({ id, mid: mid(document.getElementById(id) as HTMLElement) })) };
      });
      // Partner: all four are on the page (a missing one would read as mid 0).
      expect(rows.brand).toBeGreaterThan(0);
      for (const b of rows.buttons) {
        expect(b.mid, `${b.id} sits on another line than the brand (${JSON.stringify(rows)})`).toBeGreaterThan(0);
        expect(Math.abs(b.mid - rows.brand), `${b.id} vs the brand line (${JSON.stringify(rows)})`).toBeLessThanOrEqual(6);
      }
    });
  }

  test("E: at 390px the header's Tab order matches its visual order (WCAG 2.4.3)", async ({ page }) => {
    // RED-IF: Tab visits the header buttons in a different order from how they
    // read top-to-bottom, then left-to-right (a90fec3 moves "Take the tour"
    // up to the brand line with CSS order, but Tab still meets "How it works"
    // first).
    await page.setViewportSize({ width: 390, height: 664 });
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    const ids = ["landing-howitworks", "landing-tour", "landing-open-workspace"];
    const visual = await page.evaluate((list) => {
      const boxes = list.map((id) => ({ id, r: (document.getElementById(id) as HTMLElement).getBoundingClientRect() }));
      boxes.sort((a, b) => (Math.abs(a.r.top - b.r.top) > 6 ? a.r.top - b.r.top : a.r.left - b.r.left));
      return boxes.map((b) => b.id);
    }, ids);
    const tabbed: string[] = [];
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    for (let i = 0; i < 25 && tabbed.length < ids.length; i++) {
      await page.keyboard.press("Tab");
      const id = await page.evaluate(() => document.activeElement?.id ?? "");
      if (ids.includes(id) && !tabbed.includes(id)) tabbed.push(id);
    }
    // Partner: Tab reached all three header buttons.
    expect([...tabbed].sort()).toEqual([...ids].sort());
    expect(tabbed, `Tab order vs visual order ${JSON.stringify(visual)}`).toEqual(visual);
  });
});
