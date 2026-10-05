import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { HELP_HINT_IDS, HELP_HINT_KEYS, helpHintDismissId } from "../../fixtures/help";

/**
 * W48 (ADR-0145 decision 2), journey 2 — the History hint, for a signed-in
 * visitor. Runs ONLY under `playwright.signed-in.config.ts` (the test-only
 * launcher of W33 slice D, ADR-0142: real app, Google sign-in against a
 * loopback stub set in-process, live execution off, $0). The one mock is
 * Google's consent page, as in history-refresh.spec.ts.
 *
 * Contract (names in e2e/fixtures/help.ts): `#help-hint-history` is a
 * `role="note"` with an accessible name, on the composer, beside — never
 * inside or over — `#account-history`, in the page flow, not a live region,
 * taking no focus, with a "Got it" button `#help-hint-history-dismiss` that
 * hides it and writes "1" to `quorum.hintSeen.history`. The anonymous half
 * (no History control, no History hint) is in
 * tests/invariants/help-and-tour.spec.ts.
 *
 * These tests do NOT call markHelpSeen: they start with no hint marked seen.
 */

let counter = 0;
function freshAccount(label: string): { sub: string; email: string } {
  counter += 1;
  const sub = `1148${Date.now()}${counter}`;
  return { sub, email: `${label}.${sub}@example.com` };
}

async function routeGoogle(page: Page, account: { sub: string; email: string }) {
  await page.route("https://accounts.google.com/**", async (route) => {
    const asked = new URL(route.request().url());
    const state = asked.searchParams.get("state");
    expect(state, "the app's authorization URL carries a state").toBeTruthy();
    const back = new URL(asked.searchParams.get("redirect_uri") ?? "");
    back.searchParams.set("code", `${account.sub}|${account.email}`);
    back.searchParams.set("state", state ?? "");
    await route.fulfill({ status: 302, headers: { location: back.href } });
  });
}

async function openWorkspace(page: Page) {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem("quorum.workspaceSeen", "1");
    } catch (_) {}
  });
  await page.goto("/ui", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-view="composer"]')).toBeVisible();
}

async function signIn(page: Page, account: { sub: string; email: string }) {
  await routeGoogle(page, account);
  await openWorkspace(page);
  await page.locator("#sign-in-google").click();
  await expect(page.locator("#account-email")).toHaveText(account.email);
  await expect(page.locator('[data-view="composer"]')).toBeVisible();
  await expect(page.locator("#account-history")).toBeVisible();
}

const historyHint = (page: Page) => page.locator(`#${HELP_HINT_IDS.history}`);
const historyGotIt = (page: Page) => page.locator(`#${helpHintDismissId("history")}`);

test.describe("W48 the History hint, signed in (ADR-0145 decision 2)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "the lane runs on the reference engine only");

  test("journey 2: the History hint shows beside History on the composer, once; Got it keeps it gone after a reload", async ({ page }) => {
    // RED-IF: a signed-in composer has no `#help-hint-history`; or it is not a
    // labelled note; or it sits inside / over `#account-history` or covers its
    // summary; or it is a live region or takes focus; or "Got it" does not hide
    // it and write `quorum.hintSeen.history`; or it returns after a reload.
    await signIn(page, freshAccount("hint"));

    const note = historyHint(page);
    await expect(note).toBeVisible();
    await expect(note).toHaveAttribute("role", "note");
    await expect(note).toHaveAccessibleName(/\S/);
    await expect(historyGotIt(page)).toBeVisible();
    await expect(historyGotIt(page)).toHaveAccessibleName("Got it");
    await expect(note.locator(`#${helpHintDismissId("history")}`)).toHaveCount(1);

    const where = await page.evaluate((hintId) => {
      const hintEl = document.getElementById(hintId) as HTMLElement;
      const history = document.getElementById("account-history") as HTMLElement;
      const summary = history.querySelector("summary") as HTMLElement;
      const hr = hintEl.getBoundingClientRect();
      const sr = summary.getBoundingClientRect();
      const top = document.elementFromPoint(sr.left + sr.width / 2, sr.top + sr.height / 2);
      let live: string | null = null;
      for (let n: HTMLElement | null = hintEl; n; n = n.parentElement) {
        const v = n.getAttribute("aria-live");
        const role = n.getAttribute("role");
        if ((v && v !== "off") || role === "status" || role === "alert" || role === "log") {
          live = n.id || n.className || n.tagName;
          break;
        }
      }
      return {
        inside: history.contains(hintEl),
        wraps: hintEl.contains(history),
        overlapsSummary: !(hr.right <= sr.left || hr.left >= sr.right || hr.bottom <= sr.top || hr.top >= sr.bottom),
        summaryTakesClick: Boolean(top && (top === summary || summary.contains(top))),
        position: getComputedStyle(hintEl).position,
        live,
        focusInside: hintEl.contains(document.activeElement),
        onComposerView: document.getElementById("main-content")?.dataset.activeView === "composer",
      };
    }, HELP_HINT_IDS.history);
    expect(where).toMatchObject({
      inside: false,
      wraps: false,
      overlapsSummary: false,
      summaryTakesClick: true,
      live: null,
      focusInside: false,
      onComposerView: true,
    });
    expect(["static", "relative"]).toContain(where.position);

    expect(await page.evaluate((k) => localStorage.getItem(k), HELP_HINT_KEYS.history)).toBeNull();
    await historyGotIt(page).click();
    await expect(note).toBeHidden();
    expect(await page.evaluate((k) => localStorage.getItem(k), HELP_HINT_KEYS.history)).toBe("1");

    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await expect(page.locator("#account-history")).toBeVisible(); // partner: History is still there
    await expect(historyHint(page)).toBeHidden();
  });

  test("journey 2: the estimate hint shows for a signed-in visitor too, and Got it on History leaves it alone", async ({ page }) => {
    // RED-IF: the estimate hint is anonymous-only, or one "Got it" dismisses
    // another idea's hint (one key per hint, ADR-0145 decision 2).
    await signIn(page, freshAccount("hint2"));
    await expect(historyHint(page)).toBeVisible();
    await historyGotIt(page).click();
    await expect(historyHint(page)).toBeHidden();
    expect(await page.evaluate((k) => localStorage.getItem(k), HELP_HINT_KEYS.estimate)).toBeNull();

    await page.locator("#query-text").fill("What are the key metrics for measuring SaaS customer retention?");
    await page.locator("#estimate-run").click();
    await expect(page.locator("#cost-review-card")).toBeVisible({ timeout: 15000 });
    await expect(page.locator(`#${HELP_HINT_IDS.estimate}`)).toBeVisible();
  });

  test("keyboard and axe: History's Got it is reachable by Tab and named; no critical/serious violation with the hint shown, both themes", async ({ page }) => {
    // RED-IF: `#help-hint-history-dismiss` cannot be reached with Tab, or the
    // hint brings a critical/serious WCAG A/AA violation in either theme. The
    // visibility assert is the positive partner for the scan.
    await signIn(page, freshAccount("hint3"));
    await expect(historyHint(page)).toBeVisible();

    for (const theme of ["light", "dark"] as const) {
      await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await page.waitForTimeout(150);
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      const serious = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
      expect(
        serious,
        `History hint [${theme}] critical/serious axe violations:\n` +
          serious.map((v) => `  ${v.impact} ${v.id} @ ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`).join("\n"),
      ).toEqual([]);
    }

    await page.locator("#account-history > summary").focus();
    let reached = false;
    for (let i = 0; i < 80 && !reached; i++) {
      await page.keyboard.press("Tab");
      reached = (await page.evaluate(() => document.activeElement?.id ?? "")) === helpHintDismissId("history");
    }
    expect(reached, "Tab from History reaches the History hint's Got it").toBe(true);
    await page.keyboard.press("Enter");
    await expect(historyHint(page)).toBeHidden();
  });
});
