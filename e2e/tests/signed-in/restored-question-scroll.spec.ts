import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { markHelpSeen } from "../../fixtures/help";

/**
 * THE SIGNED-IN BROWSER LANE (ADR-0142) — W87-2, the restore-scroll race,
 * review round 1 (ADR-0175's 2026-10-24 amendment, 2026-10-25): what the
 * scroll listener of the watch on a restored question does with a `scroll`
 * event while the boot is still painting.
 *
 * The setup is X4's and X5's (`session-max-age.spec.ts`): signed in at
 * 390x844, the session aged to its last 12 minutes, "Run now" refused,
 * "Sign in again", and the return page's first `/ready` held, so the boot
 * waits in readiness after the question is put back and the watch is still
 * on. Each test acts in that state, then lets the boot finish, and reads the
 * page's own end signal, `html[data-restore-scroll]`.
 *
 * Nothing is mocked but Google's consent page and the held or edited
 * responses named in each test.
 */

const AGE_SESSIONS = "http://127.0.0.1:18097/age-sessions";
const HOUR = 3600;

const SIGNED_IN_LATE_RUN = "Your session ends in less than 12 minutes. Sign in again, then run this question.";
/** CHG-070 (b): long enough that a person would mind retyping it. */
const LONG_QUESTION =
  "My grandmother's recipe for lemon cake uses 250 g of butter, 200 g of sugar, four eggs and the zest of " +
  "two lemons. If I swap half the butter for olive oil, how will the crumb, the rise and the keeping time " +
  "change, and should I lower the oven from 180 °C?";
/** Long enough that the 156 px box scrolls its own text at 390 px. */
const VERY_LONG_QUESTION = Array.from({ length: 8 }, () => LONG_QUESTION).join("\n\n");

let counter = 0;
/** A Google subject and email no other test in the run uses. */
function freshAccount(label: string): { sub: string; email: string } {
  counter += 1;
  const sub = `1089${Date.now()}${counter}`;
  return { sub, email: `${label}.${sub}@example.com` };
}

/** Catch Google's consent page and send the browser to the local callback. */
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

async function signIn(page: Page, account: { sub: string; email: string }) {
  await routeGoogle(page, account);
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem("quorum.workspaceSeen", "1");
    } catch (_) {}
  });
  await markHelpSeen(page);
  await page.goto("/ui", { waitUntil: "domcontentloaded" });
  await expect(page.locator("html")).toHaveAttribute("data-app-state", "ready");
  await page.locator("#sign-in-google").click();
  await expect(page.locator("#account-email")).toHaveText(account.email);
  await expect(page.locator("html")).toHaveAttribute("data-app-state", "ready");
}

/** The page's session now started `ageSeconds` ago, on the server. */
async function ageSession(page: Page, request: APIRequestContext, ageSeconds: number) {
  const cookies = await page.context().cookies();
  const session = cookies.find((c) => c.name === "quorum_session" || c.name === "__Host-quorum_session");
  expect(session, "the page holds a session cookie").toBeTruthy();
  const aged = await request.post(AGE_SESSIONS, {
    data: { session_id: session?.value ?? "", age_seconds: ageSeconds },
  });
  expect(aged.status(), "the lane's test-only handler found the session").toBe(200);
}

/** True once the main frame has committed the page that comes back. */
function watchReturn(page: Page): () => boolean {
  let returned = false;
  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame() && new URL(frame.url()).pathname === "/ui") returned = true;
  });
  return () => returned;
}

const twoFrames = (page: Page) =>
  page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const outcome = (page: Page) => page.evaluate(() => document.documentElement.dataset.restoreScroll ?? "unset");

/**
 * Refused late run, then "Sign in again" with the return page's first
 * `/ready` held. With `drift`, the return page's second
 * `/v1/models/defaults` names every model stale (as X1 does), so a drift
 * banner paints above the box after the release.
 */
async function heldAfterRestore(
  page: Page,
  request: APIRequestContext,
  label: string,
  { question = LONG_QUESTION, drift = false }: { question?: string; drift?: boolean } = {},
) {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, freshAccount(label));
  await ageSession(page, request, 12 * HOUR - 600);
  await page.locator("#query-text").fill(question);
  await page.locator("#run-now").click();
  await expect(page.locator("#error-region-message")).toHaveText(SIGNED_IN_LATE_RUN);

  const returned = watchReturn(page);
  let release!: () => void;
  const released = new Promise<void>((resolve) => {
    release = resolve;
  });
  const hold = { held: 0 };
  await page.route("**/ready", async (route) => {
    if (returned() && hold.held === 0) {
      hold.held += 1;
      await released;
    }
    await route.continue();
  });
  let defaultsAsked = 0;
  await page.route("**/v1/models/defaults", async (route) => {
    if (!returned()) {
      await route.continue();
      return;
    }
    defaultsAsked += 1;
    if (!drift || defaultsAsked < 2) {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    const body = await response.json();
    body.stale_model_ids = (body.model_slots ?? []).map((slot: { model_id: string }) => slot.model_id);
    await route.fulfill({ response, json: body });
  });
  let defaultsFinished = 0;
  page.on("requestfinished", (finished) => {
    if (returned() && new URL(finished.url()).pathname === "/v1/models/defaults") defaultsFinished += 1;
  });

  const loaded = page.waitForEvent("load");
  await page.locator("#error-region-actions").getByRole("button", { name: "Sign in again", exact: true }).click();
  await loaded;
  await expect.poll(() => hold.held, { message: "the return page's /ready is held" }).toBe(1);
  await expect(page.locator("html")).toHaveAttribute("data-app-state", "ready");
  await expect(page.locator("#query-text")).toHaveValue(question);
  // The 2 s readiness fallback has painted: no paint of the page's own
  // places the box between the test's action and the release.
  await expect(page.locator("#readiness-banner")).toBeVisible();
  await twoFrames(page);
  expect(hold.held, "the /ready is still held").toBe(1);
  expect(await outcome(page), "the watch is still on").toBe("unset");
  return {
    /** Release the /ready, then wait out the boot: the second defaults and two frames. */
    async finish() {
      release();
      await expect.poll(() => defaultsFinished, { message: "both defaults requests finished" }).toBe(2);
      await twoFrames(page);
    },
  };
}

test.describe("the restored question box: what a scroll event means (W87-2 restore race, round 1)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "the lane runs on the reference engine only");

  test("R1: scroll anchoring after content grows above the view does not stop the page placing the box", async ({
    page,
    request,
  }) => {
    // RED-IF: the scroll listener cancels when the window's scrollY moved
    // but the box stayed where it was on screen (af774b2's rule: "cancelled"
    // at the anchoring scroll, then the drift banner leaves the box off
    // screen; this test red 2 of 2 on af774b2; see ADR-0175). Partners: the
    // browser's scroll anchoring really moved scrollY by the bar's 40 px while
    // the box stayed put, and the drift banner really painted after it.
    test.setTimeout(120000);
    const held = await heldAfterRestore(page, request, "restore-r1", { drift: true });
    const before = await page.evaluate(() => ({
      scrollY: window.scrollY,
      top: (document.getElementById("query-text") as HTMLElement).getBoundingClientRect().top,
    }));
    expect(before.scrollY, "the view is scrolled, so anchoring has something to keep").toBeGreaterThan(40);
    // A 40 px bar prepended to the page, as a browser extension's bar would be.
    await page.evaluate(() => {
      const bar = document.createElement("div");
      bar.style.height = "40px";
      document.body.prepend(bar);
    });
    await twoFrames(page);
    const after = await page.evaluate(() => ({
      scrollY: window.scrollY,
      top: (document.getElementById("query-text") as HTMLElement).getBoundingClientRect().top,
    }));
    expect(Math.abs(after.scrollY - before.scrollY - 40), `scrollY ${before.scrollY} -> ${after.scrollY}`).toBeLessThan(
      1,
    );
    expect(Math.abs(after.top - before.top), `the box's top ${before.top} -> ${after.top}`).toBeLessThan(1);
    expect(await outcome(page), "the anchoring scroll did not end the watch").toBe("unset");
    await held.finish();
    await expect(page.locator("#drift-region")).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-restore-scroll", "settled");
    await expect(page.locator("#query-text")).toHaveValue(LONG_QUESTION);
    await expect(page.locator("#query-text")).toBeInViewport({ ratio: 1 });
  });

  test("R2: a window scroll of 8 px is tolerated, and 1 px more (9 px in all) cancels", async ({
    page,
    request,
  }) => {
    // RED-IF: the tolerance is raised above 8 px (9 px no longer cancels),
    // or a scroll under the tolerance resets the baseline (the two scrolls
    // never add up). Partners: both scrolls really moved the view, and the
    // 8 px one left the watch on.
    test.setTimeout(120000);
    const held = await heldAfterRestore(page, request, "restore-r2");
    const start = await page.evaluate(() => window.scrollY);
    await page.evaluate(() => window.scrollBy(0, 8));
    await twoFrames(page);
    expect(await page.evaluate(() => window.scrollY), "the view moved 8 px").toBe(start + 8);
    expect(await outcome(page), "8 px is under the tolerance").toBe("unset");
    await page.evaluate(() => window.scrollBy(0, 1));
    await twoFrames(page);
    expect(await page.evaluate(() => window.scrollY), "the view moved 9 px in all").toBe(start + 9);
    expect(await outcome(page), "9 px is over the tolerance").toBe("cancelled");
    await held.finish();
    await expect(page.locator("html")).toHaveAttribute("data-restore-scroll", "cancelled");
    expect(await page.evaluate(() => window.scrollY), "the page did not move the view back").toBe(start + 9);
  });

  test("R3: a layout move of the box places it again at once, before the boot's next paint", async ({
    page,
    request,
  }) => {
    // RED-IF: the listener does nothing when the layout alone moved the box
    // (a review mutation that made this step do nothing: the box 82% in view
    // until the readiness paint after the release). Partners: the box really
    // moved 44 px in the document with the view still, and the watch is still
    // on.
    test.setTimeout(120000);
    const held = await heldAfterRestore(page, request, "restore-r3");
    const shift = await page.evaluate(() => {
      const box = document.getElementById("query-text") as HTMLElement;
      const notice = document.querySelector(".privacy-notice") as HTMLElement;
      const before = { top: box.getBoundingClientRect().top, scrollY: window.scrollY };
      notice.style.paddingBottom = `${parseFloat(getComputedStyle(notice).paddingBottom) + 44}px`;
      const after = { top: box.getBoundingClientRect().top, scrollY: window.scrollY };
      return {
        movedInDocument: after.top + after.scrollY - (before.top + before.scrollY),
        viewMoved: after.scrollY - before.scrollY,
      };
    });
    expect(Math.abs(shift.movedInDocument - 44), `the box moved ${shift.movedInDocument} px`).toBeLessThan(1);
    expect(shift.viewMoved, "the view did not move").toBe(0);
    // A scroll event with the view where it was, as after the Linux font swap.
    await page.evaluate(() => document.dispatchEvent(new Event("scroll", { bubbles: true })));
    await twoFrames(page);
    // Still held: only the scroll listener can have placed the box.
    await expect(page.locator("#query-text")).toBeInViewport({ ratio: 1 });
    expect(await outcome(page), "placing the box does not end the watch").toBe("unset");
    await held.finish();
    await expect(page.locator("html")).toHaveAttribute("data-restore-scroll", "settled");
    await expect(page.locator("#query-text")).toBeInViewport({ ratio: 1 });
  });

  test("R4: the box scrolling its own text does not stop the page placing it", async ({ page, request }) => {
    // RED-IF: the inner-panel check counts the box itself as a panel that
    // holds it (`contains` is true for the node itself; af774b2: "cancelled").
    // Partners: the long question was put back, the box really scrolled its
    // text, and the box ends in view.
    test.setTimeout(120000);
    const held = await heldAfterRestore(page, request, "restore-r4", { question: VERY_LONG_QUESTION });
    const scrolled = await page.evaluate(() => {
      const box = document.getElementById("query-text") as HTMLTextAreaElement;
      const overflow = box.scrollHeight - box.clientHeight;
      box.scrollTop = 200;
      return { overflow, scrollTop: box.scrollTop };
    });
    expect(scrolled.overflow, "the box's text overflows it").toBeGreaterThan(200);
    expect(scrolled.scrollTop, "the box scrolled its own text").toBe(200);
    await twoFrames(page);
    expect(await outcome(page), "the box's own scroll did not end the watch").toBe("unset");
    await held.finish();
    await expect(page.locator("html")).toHaveAttribute("data-restore-scroll", "settled");
    await expect(page.locator("#query-text")).toHaveValue(VERY_LONG_QUESTION);
    await expect(page.locator("#query-text")).toBeInViewport({ ratio: 1 });
  });
});
