import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import {
  test,
  expect,
  type APIRequestContext,
  type BrowserContext,
  type Page,
  type Request,
  type Route,
} from "@playwright/test";
import { markHelpSeen } from "../../fixtures/help";

/**
 * W140: a time limit on the page's two start-up requests, `GET /v1/session` and
 * `GET /v1/models/defaults`. A person whose start-up gets no answer is told
 * what is happening ("Still connecting…" at 10 s) and is given a way out (the
 * card "Can't reach the server" with "Try again"), instead of a spinner with no
 * message and no limit. ADR-0188 made a click wait for start-up and recorded
 * that nothing limited that wait.
 *
 * What the page must do: one attempt is given up at 15 s, one automatic retry
 * follows about 1 s after an attempt that got NO HTTP answer, and "Try again"
 * makes one attempt of up to 30 s per step. Any HTTP answer ends the step as it
 * does today.
 *
 * How these tests hold time (measured on this page with Playwright 1.61):
 * - `page.clock` is installed and paused BEFORE the page loads, so no test
 *   waits real time for a limit. Web Locks and IndexedDB still run, in real
 *   time, so a test polls for the request before advancing the clock.
 * - The clock is advanced in STEPS: one `runFor(31000)` crosses the whole chain
 *   but only one request is seen, because the second is aborted before it can
 *   be intercepted. So: run 15 s, wait for the abort, run 1 s, poll for request
 *   2, run 15 s.
 * - A paused clock also stops the page's ordinary timers (the warnings wait,
 *   the readiness fallback), so a test resumes it once the limits are behind
 *   it and it goes on to use the page normally.
 * - The clock is shared by a whole browser context, so in the two-tab test tab
 *   B finishes booting before tab A hangs.
 *
 * Runs ONLY under `playwright.signed-in.config.ts`: the real app with Google
 * sign-in on against a loopback stub, $0, live execution off. Only the requests
 * a test names are held; everything else reaches the real server.
 */

const QUESTION = "How should a small team choose between Postgres and MySQL?";
const CARD_TITLE = "Can't reach the server";
const NOTICE_TEXT = "Still connecting…";
const SESSION_500_TITLE = "Start a session to run a query";
const CRASH = "reading 'trim'";

// Literals on purpose: these are the published timings, written here
// independently of the page's own constants.
const NOTICE_MS = 10000;
const ATTEMPT_MS = 15000;
const RETRY_GAP_MS = 1000;
const BY_HAND_MS = 30000;

const DESKTOP = { width: 1440, height: 900 };
const PHONE = { width: 390, height: 844 };
const BOTH_WIDTHS = [DESKTOP, PHONE];

const SESSION = "/v1/session";
const MODELS = "/v1/models/defaults";
const READY = "/ready";
const SIGN_IN_START = "/v1/auth/google/start";
const ESTIMATE = "/v1/query-runs/estimate";

const AGE_SESSIONS = "http://127.0.0.1:18097/age-sessions";
const HOUR = 3600;

/** How long a real-time check waits for a request that must NOT be sent. */
const QUIET_MS = 300;
/** A real-time wait long enough for a smooth scroll to have moved the page. */
const SMOOTH_SCROLL_MS = 700;
/** Long enough for an abort to reach Playwright, short enough to go red fast. */
const SEEN_MS = 5000;
/** How long a wait for a request or an answer the test has just caused may take. */
const ANSWER_MS = 15000;

let counter = 0;
/** A Google subject and email no other test in the run uses. */
function freshAccount(label: string): { sub: string; email: string } {
  counter += 1;
  const sub = `1140${Date.now()}${counter}`;
  return { sub, email: `${label}.${sub}@example.com` };
}

/** Catch Google's consent page and send the browser to the local callback. */
async function routeGoogle(page: Page, account: { sub: string; email: string }) {
  await page.route("https://accounts.google.com/**", async (route) => {
    const asked = new URL(route.request().url());
    const back = new URL(asked.searchParams.get("redirect_uri") ?? "");
    back.searchParams.set("code", `${account.sub}|${account.email}`);
    back.searchParams.set("state", asked.searchParams.get("state") ?? "");
    await route.fulfill({ status: 302, headers: { location: back.href } });
  });
}

/** Install and pause the page clock. Call it before the page loads. */
async function freezeClock(target: Page | BrowserContext) {
  const now = Date.now();
  await target.clock.install({ time: now });
  await target.clock.pauseAt(now + 1000);
}

/**
 * A server that sends good headers and the first bytes of a body, then never
 * finishes: `route.fulfill` cannot stall after its headers, and a stall has to
 * be a real one for the browser to raise what it really raises on an abort.
 */
let stallServer: Server;
let stallUrl = "";
test.beforeAll(async () => {
  stallServer = createServer((_request, response) => {
    response.writeHead(200, { "content-type": "application/json" });
    response.write('{"csrf_token":"');
  });
  await new Promise<void>((resolve) => stallServer.listen(0, "127.0.0.1", resolve));
  stallUrl = `http://127.0.0.1:${(stallServer.address() as AddressInfo).port}/stalled`;
});
test.afterAll(async () => {
  stallServer.closeAllConnections();
  await new Promise((resolve) => stallServer.close(resolve));
});

/**
 * What a request gets: no answer at all, the real server's answer, a refused
 * connection, good headers and a body that never ends, or this HTTP status.
 */
type Answer = "hang" | "pass" | "refuse" | "stall" | number;

function httpBody(status: number): string {
  // A 401 with this code is what a session store that cannot be checked sends.
  if (status === 401) {
    return JSON.stringify({ detail: { code: "SESSION_UNCHECKED", message: "We could not check your session." } });
  }
  return "{}";
}

async function give(route: Route, answer: Answer) {
  if (answer === "pass") await route.continue();
  else if (answer === "refuse") await route.abort("connectionrefused");
  else if (answer === "stall") await route.continue({ url: stallUrl });
  else if (typeof answer === "number") {
    await route.fulfill({ status: answer, contentType: "application/json", body: httpBody(answer) });
  }
}

/**
 * Answer every request to `path`: the first ones from `first`, in order, then
 * `line.then`. Counts what was sent, and what the page gave up on.
 */
async function answering(page: Page, path: string, first: Answer[] = [], then: Answer = "hang") {
  const queue = [...first];
  const mine = new Set<Request>();
  const hung: Route[] = [];
  const line = {
    then,
    sent: () => mine.size,
    givenUp: () => givenUp,
    /** Answer the request still held (the page has not given up on it). Raises if there is none. */
    finishHung: async (answer: Answer) => {
      const route = hung.shift();
      if (!route) throw new Error(`nothing is held on ${path}`);
      await give(route, answer);
    },
  };
  let givenUp = 0;
  page.on("requestfailed", (request) => {
    if (!mine.has(request)) return;
    givenUp += 1;
    const held = hung.findIndex((route) => route.request() === request);
    if (held >= 0) hung.splice(held, 1);
  });
  await page.route(
    (url) => url.pathname === path,
    async (route) => {
      mine.add(route.request());
      const answer = queue.length ? (queue.shift() as Answer) : line.then;
      if (answer === "hang") hung.push(route);
      else await give(route, answer);
    },
  );
  return line;
}
type Line = Awaited<ReturnType<typeof answering>>;

/** Every write the page sends to `path`. */
function writesTo(page: Page, path: string): Request[] {
  const writes: Request[] = [];
  page.on("request", (request) => {
    if (request.method() !== "GET" && new URL(request.url()).pathname === path) writes.push(request);
  });
  return writes;
}

/** Every uncaught error on the page; a raw abort would land here. */
function watchCrashes(page: Page): string[] {
  const crashes: string[] = [];
  page.on("pageerror", (error) => crashes.push(error.message));
  return crashes;
}

const firstRequestSent = (line: Line) =>
  expect.poll(line.sent, { message: "the page has sent its first attempt", timeout: SEEN_MS }).toBe(1);

/** Advance by `ms`, then wait for the page to give up on one more attempt. */
async function attemptGivenUpAfter(page: Page, line: Line, ms: number) {
  const before = line.givenUp();
  await page.clock.runFor(ms);
  await expect
    .poll(line.givenUp, { message: `the page gives up on the attempt after ${ms} ms`, timeout: SEEN_MS })
    .toBe(before + 1);
}

/** Advance by `ms`, then wait for the page to send one more attempt. */
async function retrySentAfter(page: Page, line: Line, ms: number) {
  const before = line.sent();
  await page.clock.runFor(ms);
  await expect
    .poll(line.sent, { message: `the page sends its one retry after ${ms} ms`, timeout: SEEN_MS })
    .toBe(before + 1);
}

/** Drive a held first attempt through its limit, the gap and the retry's limit. */
async function bothAttemptsRunOut(page: Page, line: Line) {
  await attemptGivenUpAfter(page, line, ATTEMPT_MS);
  await retrySentAfter(page, line, RETRY_GAP_MS);
  await attemptGivenUpAfter(page, line, ATTEMPT_MS);
}

/** Run the clock on past where another attempt would start, and count again. */
async function noFurtherRequest(page: Page, line: Line, expected: number) {
  await page.clock.runFor(RETRY_GAP_MS + 1);
  await page.waitForTimeout(QUIET_MS);
  await page.clock.runFor(ATTEMPT_MS);
  await page.waitForTimeout(QUIET_MS);
  expect(line.sent(), "no further automatic attempt").toBe(expected);
}

const card = (page: Page) => page.locator("#error-region");
const cardTitle = (page: Page) => page.locator("#error-region-title");
const tryAgain = (page: Page) => page.locator("#error-region-actions").getByRole("button", { name: "Try again" });
const notice = (page: Page) => page.locator("#start-up-notice");
const appState = (page: Page) => page.locator("html");
const costGate = (page: Page) => page.locator('[data-view="cost-gate"]');

async function expectTheCard(page: Page) {
  await expect(cardTitle(page)).toHaveText(CARD_TITLE);
  await expect(card(page)).toBeVisible();
  await expect(tryAgain(page)).toBeVisible();
  await expect(tryAgain(page)).toHaveClass(/button-primary/);
  await expect(appState(page)).toHaveAttribute("data-app-state", "error");
  // Never the browser's own words for an abort, on the card or anywhere else.
  await expect(card(page)).not.toContainText(/abort|signal/i);
  await expect(card(page)).not.toContainText(CRASH);
}

async function openWorkspace(page: Page) {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem("quorum.workspaceSeen", "1");
    } catch (_) {}
  });
  await markHelpSeen(page);
  await page.goto("/ui", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-view="composer"]')).toBeVisible();
}

async function openLanding(page: Page) {
  await markHelpSeen(page);
  await page.goto("/ui", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-view="landing"]')).toBeVisible();
  await expect(page.locator("#landing-query")).toBeVisible();
}

async function pressEstimate(page: Page) {
  const button = page.locator("#estimate-run");
  await button.scrollIntoViewIfNeeded();
  await button.click();
}

/** The model ids the panel's drawn slots hold, in order. */
async function drawnPanel(page: Page): Promise<string[]> {
  const slots = page.locator("select[data-model-slot]");
  await expect(slots).not.toHaveCount(0);
  return slots.evaluateAll((nodes) => nodes.map((n) => (n as HTMLSelectElement).value));
}

/** Press Estimate on a working page: it prices the drawn panel, with `token` if given. */
async function estimatePrices(page: Page, token?: string) {
  const writes = writesTo(page, ESTIMATE);
  await page.locator("#query-text").fill(QUESTION);
  const estimate = nextRequestTo(page, ESTIMATE);
  await pressEstimate(page);
  const sent = await estimate;
  if (token !== undefined) expect(sent.headers()["x-csrf-token"], "the estimate carries the token").toBe(token);
  expect((sent.postDataJSON() as { model_slots: string[] }).model_slots).toEqual(await drawnPanel(page));
  expect((await sent.response())?.status(), "the server takes the estimate").toBe(200);
  await expect(costGate(page)).toBeVisible({ timeout: 15000 });
  await expect(card(page)).toBeHidden();
  expect(writes, "exactly one estimate").toHaveLength(1);
}

const answerToken = async (answer: Promise<import("@playwright/test").Response>) =>
  ((await (await answer).json()) as { csrf_token: string }).csrf_token;

/**
 * Started before the action that causes it and awaited after. Marked handled
 * at once: if an earlier check fails first, the wait must not reject into the
 * next test.
 */
function handledLater<T>(waiting: Promise<T>): Promise<T> {
  waiting.catch(() => {});
  return waiting;
}

const nextAnswerFrom = (page: Page, path: string) =>
  handledLater(page.waitForResponse((r) => new URL(r.url()).pathname === path, { timeout: ANSWER_MS }));

/** A stalled answer comes from the stall server, so that is the address it carries. */
const nextStalledAnswer = (page: Page) =>
  handledLater(page.waitForResponse((r) => r.url() === stallUrl, { timeout: ANSWER_MS }));

const nextRequestTo = (page: Page, path: string) =>
  handledLater(page.waitForRequest((r) => new URL(r.url()).pathname === path, { timeout: ANSWER_MS }));

test.describe("the page's start-up requests have a time limit (W140)", () => {
  // ---------------------------------------------------------------------------
  // "Still connecting…"
  // ---------------------------------------------------------------------------

  for (const size of BOTH_WIDTHS) {
    test(`the notice appears at 10 s, in view after Estimate on the composer, and clears on the answer, at ${size.width}`, async ({
      page,
    }) => {
      // RED-IF the notice is missing, comes before or after 10 s, sits in the
      // page's flow so a person scrolled down to Estimate cannot see it, is not
      // a status line, or stays after start-up answers. Partner: at 390 the
      // page really is scrolled, and the click then completes (cost gate).
      await page.setViewportSize(size);
      await freezeClock(page);
      const session = await answering(page, SESSION);
      await openWorkspace(page);
      await firstRequestSent(session);
      await page.locator("#query-text").fill(QUESTION);
      await pressEstimate(page);

      await page.clock.runFor(NOTICE_MS - 1);
      await expect(notice(page), "no notice before 10 s").toBeHidden();
      await page.clock.runFor(1);
      await expect(notice(page)).toBeVisible();
      await expect(notice(page), "the notice is on screen, wherever the person has scrolled").toBeInViewport();
      await expect(notice(page)).toHaveText(NOTICE_TEXT);
      await expect(notice(page)).toHaveAttribute("role", "status");
      if (size === PHONE) {
        expect(await page.evaluate(() => window.scrollY), "Estimate is below the fold at 390").toBeGreaterThan(0);
      }

      await session.finishHung("pass");
      await expect(notice(page), "the notice clears when start-up answers").toBeHidden();
      await page.clock.resume();
      await expect(costGate(page), "the waiting click completes").toBeVisible({ timeout: 15000 });
    });

    test(`the notice appears at 10 s, in view after Estimate on the landing, and clears on the answer, at ${size.width}`, async ({
      page,
    }) => {
      // RED-IF the notice is drawn only for the composer, or is off screen
      // from the landing's Estimate (the top bar is hidden there, so nothing
      // else on the page speaks). Estimate is pressed at 8 s so the landing is
      // still showing at 10 s: its hand-off to the composer takes 2.8 s.
      // Partner: the landing is the view on screen, and start-up then finishes.
      await page.setViewportSize(size);
      await freezeClock(page);
      const session = await answering(page, SESSION);
      await openLanding(page);
      await firstRequestSent(session);
      await page.locator("#landing-query").fill(QUESTION);
      await page.clock.runFor(8000);
      const estimate = page.locator("#landing-estimate");
      await estimate.scrollIntoViewIfNeeded();
      await estimate.click();

      await page.clock.runFor(NOTICE_MS - 8000 - 1);
      await expect(notice(page), "no notice before 10 s").toBeHidden();
      await page.clock.runFor(1);
      await expect(page.locator('[data-view="landing"]'), "still on the landing").toBeVisible();
      await expect(notice(page)).toBeVisible();
      await expect(notice(page)).toBeInViewport();
      await expect(notice(page)).toHaveText(NOTICE_TEXT);

      await session.finishHung("pass");
      await expect(notice(page), "the notice clears when start-up answers").toBeHidden();
      await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    });
  }

  test("the notice is timed from the start of start-up, across both steps", async ({ page }) => {
    // RED-IF the 10 s restarts for each step, or the notice looks only at the
    // session step: here the session answers at 6 s and the model list hangs,
    // so the notice is due at 10 s in all, 4 s into the model step. Partner:
    // it clears when the model list answers, and the state is `ready`.
    await page.setViewportSize(DESKTOP);
    await freezeClock(page);
    const session = await answering(page, SESSION);
    const models = await answering(page, MODELS);
    await openWorkspace(page);
    await firstRequestSent(session);
    await page.clock.runFor(6000);
    await session.finishHung("pass");
    await firstRequestSent(models);
    await page.clock.runFor(4000 - 1);
    await expect(notice(page)).toBeHidden();
    await page.clock.runFor(1);
    await expect(notice(page)).toBeInViewport();
    await models.finishHung("pass");
    await expect(notice(page)).toBeHidden();
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
  });

  test("the notice is un-hidden first and its text written after, so a screen reader announces it", async ({
    page,
  }) => {
    // RED-IF the text sits in the template or is written before the line is
    // un-hidden: a status line that changes while hidden may not be announced
    // (the page's own rule for its other status lines). Partner: both changes
    // were recorded, in this order.
    await page.setViewportSize(DESKTOP);
    await page.addInitScript(() => {
      const changes: string[] = [];
      (window as unknown as { __noticeChanges: string[] }).__noticeChanges = changes;
      new MutationObserver((records) => {
        for (const record of records) {
          const target = record.target as Element;
          if (record.type === "attributes" && target.id === "start-up-notice") {
            changes.push(target.hasAttribute("hidden") ? "hidden" : "shown");
          } else if (record.type !== "attributes") {
            const holder = target.nodeType === Node.TEXT_NODE ? target.parentElement : target;
            if (holder && holder.id === "start-up-notice") changes.push("text");
          }
        }
      }).observe(document, {
        subtree: true,
        attributes: true,
        attributeFilter: ["hidden"],
        childList: true,
        characterData: true,
      });
    });
    await freezeClock(page);
    const session = await answering(page, SESSION);
    await openWorkspace(page);
    await firstRequestSent(session);
    await expect(notice(page), "the line is in the page before it is needed").toBeAttached();
    await expect(notice(page), "and holds no text while hidden").toHaveText("");
    await page.clock.runFor(NOTICE_MS);
    await expect(notice(page)).toHaveText(NOTICE_TEXT);
    const changes = await page.evaluate(() => (window as unknown as { __noticeChanges: string[] }).__noticeChanges);
    expect(changes.slice(0, 2)).toEqual(["shown", "text"]);
  });

  test("a healthy start-up never shows the notice", async ({ page }) => {
    // RED-IF the timer is not cleared when start-up succeeds, so the notice
    // appears over a working page at 10 s. Partner: the line exists in the
    // page, so its being hidden means something.
    await page.setViewportSize(DESKTOP);
    await freezeClock(page);
    await openWorkspace(page);
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    await expect(notice(page)).toBeAttached();
    await page.clock.runFor(NOTICE_MS);
    await page.waitForTimeout(QUIET_MS);
    await expect(notice(page)).toBeHidden();
  });

  test("a boot that fails in its own wiring shows no notice at 10 s", async ({ page }) => {
    // RED-IF the notice's timer is armed early and the `boot().catch` path
    // does not clear it: a spinner message over a page that has already
    // failed. The throw is the one early-click.spec.ts uses. Partner: the line
    // exists, and the page did reach the failed state.
    await page.setViewportSize(DESKTOP);
    await page.addInitScript(() => {
      const original = Document.prototype.querySelectorAll;
      Document.prototype.querySelectorAll = function (this: Document, selector: string) {
        if (typeof selector === "string" && selector.includes("data-info-icon")) {
          throw new Error("wiring broken on purpose (W140 test)");
        }
        return original.call(this, selector);
      } as typeof original;
    });
    await freezeClock(page);
    await openWorkspace(page);
    await expect(appState(page)).toHaveAttribute("data-app-state", "error");
    await expect(notice(page)).toBeAttached();
    await page.clock.runFor(NOTICE_MS);
    await page.waitForTimeout(QUIET_MS);
    await expect(notice(page)).toBeHidden();
  });

  test("a boot that rejects after the notice is up clears it", async ({ page }) => {
    // RED-IF the notice is cleared only after a failure has been shown, so
    // that a failure while showing it (here the card's own scroll throws, and
    // `boot()` rejects into `boot().catch`) leaves "Still connecting…" up for
    // good. Partner: the notice was on screen first, the throw did fire, and
    // the page reached the failed state.
    await page.setViewportSize(DESKTOP);
    await page.addInitScript(() => {
      const original = Element.prototype.scrollIntoView;
      Element.prototype.scrollIntoView = function (this: Element, ...args: []) {
        if (this.id === "error-region") {
          (window as unknown as { __scrollThrew: boolean }).__scrollThrew = true;
          throw new Error("the card's scroll broken on purpose (W140 test)");
        }
        return original.apply(this, args);
      } as typeof original;
    });
    await freezeClock(page);
    const session = await answering(page, SESSION);
    await openWorkspace(page);
    await firstRequestSent(session);
    await page.clock.runFor(NOTICE_MS);
    await expect(notice(page)).toBeVisible();
    await session.finishHung(500);
    await expect(appState(page)).toHaveAttribute("data-app-state", "error");
    await expect
      .poll(() => page.evaluate(() => (window as unknown as { __scrollThrew?: boolean }).__scrollThrew))
      .toBe(true);
    await expect(notice(page)).toBeHidden();
  });

  // ---------------------------------------------------------------------------
  // The session step
  // ---------------------------------------------------------------------------

  for (const size of BOTH_WIDTHS) {
    test(`a session request that never answers: exactly 2 requests, then the card; a held Estimate ends there; "Try again" recovers and Estimate prices, at ${size.width}`, async ({
      page,
    }) => {
      // RED-IF there is no limit (today: a spinner for good, 1 request), the
      // limit is not 15 s, the retry comes at once or not at all, there is a
      // second retry, the notice stays over the card, the held click stays
      // busy or crashes on the placeholder slots, or the card does not take
      // focus and come into view for that click. Partner: the same page then
      // recovers and prices the panel, so the card's way out is a real one.
      await page.setViewportSize(size);
      const crashes = watchCrashes(page);
      await freezeClock(page);
      const session = await answering(page, SESSION);
      await openWorkspace(page);
      await firstRequestSent(session);
      await page.locator("#query-text").fill(QUESTION);
      await pressEstimate(page);
      const button = page.locator("#estimate-run");

      await page.clock.runFor(ATTEMPT_MS - 1);
      await page.waitForTimeout(QUIET_MS);
      expect(session.givenUp(), "the attempt is still running 1 ms before 15 s").toBe(0);
      await attemptGivenUpAfter(page, session, 1);
      await page.clock.runFor(RETRY_GAP_MS - 1);
      await page.waitForTimeout(QUIET_MS);
      expect(session.sent(), "the retry waits about 1 s").toBe(1);
      await retrySentAfter(page, session, 1);
      await expect(notice(page), "the notice stays up until the end").toBeVisible();
      await attemptGivenUpAfter(page, session, ATTEMPT_MS);

      await expectTheCard(page);
      await expect(notice(page), "the card replaces the notice").toBeHidden();
      await expect(button, "the held click has finished").not.toHaveAttribute("data-loading", "true");
      await expect(button).toBeEnabled();
      await expect(card(page), "the person who pressed Estimate is shown the card").toBeInViewport();
      await expect
        .poll(() => page.evaluate(() => document.activeElement?.id), { message: "a waiting click: the card takes focus" })
        .toBe("error-region");
      await noFurtherRequest(page, session, 2);
      expect(crashes, "no uncaught error").toEqual([]);

      session.then = "pass";
      await page.clock.resume();
      await tryAgain(page).click();
      await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
      await expect(card(page)).toBeHidden();
      expect(session.sent(), "Try again sent one request").toBe(3);
      await estimatePrices(page);
      expect(crashes, "no uncaught error").toEqual([]);
    });
  }

  test("a refused connection is retried once about 1 s later, then the card, and one message rather than two", async ({
    page,
  }) => {
    // RED-IF a connection that fails at once is not retried, or the readiness
    // read's toast ("Live-readiness probe failed", wording for an operator)
    // appears beside the card. Partner: the readiness read really was tried
    // and failed, so the toast's absence means it was held back.
    await page.setViewportSize(PHONE);
    await freezeClock(page);
    const session = await answering(page, SESSION, [], "refuse");
    const ready = await answering(page, READY, [], "refuse");
    await openWorkspace(page);
    await firstRequestSent(session);
    await expect.poll(session.givenUp).toBe(1);
    await page.waitForTimeout(QUIET_MS);
    expect(session.sent(), "the retry waits about 1 s").toBe(1);
    await retrySentAfter(page, session, RETRY_GAP_MS);
    await expectTheCard(page);
    await expect.poll(ready.givenUp, { message: "the readiness read was tried and failed" }).toBeGreaterThan(0);
    await page.waitForTimeout(QUIET_MS);
    await expect(page.locator(".toast", { hasText: "Live-readiness" })).toHaveCount(0);
    await noFurtherRequest(page, session, 2);
  });

  test("first attempt lost, second answered: no card, and a write carries the second answer's token", async ({
    page,
  }) => {
    // RED-IF there is no retry, the retry shows a card anyway, the page keeps
    // no token or the wrong one (the server takes only the token it last
    // issued, so the write's 200 proves it), or the notice stays. Partner:
    // the notice was up at 15 s, and exactly 2 session requests were sent.
    await page.setViewportSize(DESKTOP);
    await freezeClock(page);
    const session = await answering(page, SESSION, ["hang"], "pass");
    await openWorkspace(page);
    await firstRequestSent(session);
    await attemptGivenUpAfter(page, session, ATTEMPT_MS);
    await expect(notice(page)).toBeVisible();
    const answer = nextAnswerFrom(page, SESSION);
    await retrySentAfter(page, session, RETRY_GAP_MS);
    const token = await answerToken(answer);

    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    await expect(card(page)).toBeHidden();
    await expect(notice(page)).toBeHidden();
    await page.clock.resume();
    await estimatePrices(page, token);
    expect(session.sent()).toBe(2);
  });

  test("a session answer whose body stalls after good headers: the same card, never a raw abort", async ({ page }) => {
    // RED-IF the limit covers only the headers (the read then hangs for good)
    // or the abort during the body read reaches the card or the console as the
    // browser's own abort error. Partner: the first answer really did arrive
    // with status 200 before the body stalled.
    await page.setViewportSize(DESKTOP);
    const crashes = watchCrashes(page);
    await freezeClock(page);
    const session = await answering(page, SESSION, [], "stall");
    const firstAnswer = nextStalledAnswer(page);
    await openWorkspace(page);
    await firstRequestSent(session);
    expect((await firstAnswer).status(), "the headers arrived").toBe(200);
    await bothAttemptsRunOut(page, session);
    await expectTheCard(page);
    await expect(notice(page)).toBeHidden();
    expect(session.sent()).toBe(2);
    expect(crashes, "no uncaught error").toEqual([]);
  });

  // ---------------------------------------------------------------------------
  // The model-list step. `/ready` is hung in every test that counts the list:
  // the readiness read also asks for it (a normal start-up sends 2, measured),
  // and a hung `/ready` keeps that read from being reached, so the count is
  // the start-up step's alone.
  // ---------------------------------------------------------------------------

  for (const size of BOTH_WIDTHS) {
    test(`a model list that never answers: exactly 2 requests, then the card; a held Estimate ends there; "Try again" recovers and Estimate prices, at ${size.width}`, async ({
      page,
    }) => {
      // RED-IF the model step has no limit (today: Estimate spins for good),
      // no retry, a second retry, or the held click crashes on the placeholder
      // slots. `/ready` is hung so the readiness read's own request for the
      // list is not counted. Partner: the same page then recovers, with one
      // more list request, and prices the panel.
      await page.setViewportSize(size);
      const crashes = watchCrashes(page);
      await freezeClock(page);
      await answering(page, READY);
      const models = await answering(page, MODELS);
      await openWorkspace(page);
      await firstRequestSent(models);
      await page.locator("#query-text").fill(QUESTION);
      await pressEstimate(page);
      const button = page.locator("#estimate-run");

      await page.clock.runFor(ATTEMPT_MS - 1);
      await page.waitForTimeout(QUIET_MS);
      expect(models.givenUp(), "the attempt is still running 1 ms before 15 s").toBe(0);
      await attemptGivenUpAfter(page, models, 1);
      await retrySentAfter(page, models, RETRY_GAP_MS);
      await attemptGivenUpAfter(page, models, ATTEMPT_MS);

      await expectTheCard(page);
      await expect(notice(page)).toBeHidden();
      await expect(button).not.toHaveAttribute("data-loading", "true");
      await expect(button).toBeEnabled();
      await expect(card(page)).toBeInViewport();
      await noFurtherRequest(page, models, 2);

      models.then = "pass";
      await page.clock.resume();
      await tryAgain(page).click();
      await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
      await expect(card(page)).toBeHidden();
      expect(models.sent(), "Try again sent one list request").toBe(3);
      await estimatePrices(page);
      expect(crashes, "no uncaught error").toEqual([]);
    });
  }

  test("model list: first attempt lost, second answered: no card, and the panel is drawn and priced", async ({
    page,
  }) => {
    // RED-IF the model step has no retry, or a retry that worked still shows a
    // card. `/ready` is hung so the readiness read's own request for the list
    // is not counted. Partner: exactly 2 list requests, and Estimate prices
    // the panel the second answer drew.
    await page.setViewportSize(DESKTOP);
    await freezeClock(page);
    await answering(page, READY);
    const models = await answering(page, MODELS, ["hang"], "pass");
    await openWorkspace(page);
    await firstRequestSent(models);
    await attemptGivenUpAfter(page, models, ATTEMPT_MS);
    await retrySentAfter(page, models, RETRY_GAP_MS);
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    await expect(card(page)).toBeHidden();
    await expect(notice(page)).toBeHidden();
    await page.clock.resume();
    await estimatePrices(page);
    expect(models.sent()).toBe(2);
  });

  test("a model list whose body stalls after good headers: the same card, never a raw abort", async ({ page }) => {
    // RED-IF `api()`'s last line reads the body with no limit, or lets the
    // abort out unmapped: the card would read the browser's abort message.
    // `/ready` is hung so the readiness read's own request is not counted.
    // Partner: the first answer really did arrive with status 200.
    await page.setViewportSize(DESKTOP);
    const crashes = watchCrashes(page);
    await freezeClock(page);
    await answering(page, READY);
    const models = await answering(page, MODELS, [], "stall");
    const firstAnswer = nextStalledAnswer(page);
    await openWorkspace(page);
    await firstRequestSent(models);
    expect((await firstAnswer).status(), "the headers arrived").toBe(200);
    await bothAttemptsRunOut(page, models);
    await expectTheCard(page);
    expect(models.sent()).toBe(2);
    expect(crashes, "no uncaught error").toEqual([]);
  });

  // ---------------------------------------------------------------------------
  // An HTTP answer ends the step as it does today. These pass on the app before
  // W140: they guard behaviour the limit must not change.
  // ---------------------------------------------------------------------------

  for (const status of [500, 401, 429]) {
    test(`GUARD: a session that answers ${status} is not retried: exactly 1 request and today's card`, async ({
      page,
    }) => {
      // RED-IF the retry fires on an HTTP answer as well as on no answer: each
      // repeat rotates the token and spends the network's limiter. Partner: a
      // card is up, the session's own, not the unreachable one.
      await page.setViewportSize(DESKTOP);
      await freezeClock(page);
      const session = await answering(page, SESSION, [], status);
      await openWorkspace(page);
      await firstRequestSent(session);
      await expect(appState(page)).toHaveAttribute("data-app-state", "error");
      await expect(cardTitle(page)).toHaveText(SESSION_500_TITLE);
      await noFurtherRequest(page, session, 1);
    });

    test(`GUARD: a model list that answers ${status} is not retried: exactly 1 request and not the unreachable card`, async ({
      page,
    }) => {
      // RED-IF the retry fires on an HTTP answer. `/ready` is hung so the
      // readiness read's own request for the list is not counted (it would
      // make this 2 on a correct build). Partner: a card is up, and it is not
      // the unreachable one.
      await page.setViewportSize(DESKTOP);
      await freezeClock(page);
      await answering(page, READY);
      const models = await answering(page, MODELS, [], status);
      await openWorkspace(page);
      await firstRequestSent(models);
      await expect(appState(page)).toHaveAttribute("data-app-state", "error");
      await expect(card(page)).toBeVisible();
      await expect(cardTitle(page)).not.toHaveText(CARD_TITLE);
      await noFurtherRequest(page, models, 1);
    });
  }

  test("a session lost once and then answered 500 ends there: 2 requests and the session's card", async ({ page }) => {
    // RED-IF an HTTP answer to the retry is treated as no answer (a third
    // request, or the unreachable card for a server that did answer). Partner:
    // the first attempt was given up, so this is the retry's answer.
    await page.setViewportSize(DESKTOP);
    await freezeClock(page);
    const session = await answering(page, SESSION, ["hang"], 500);
    await openWorkspace(page);
    await firstRequestSent(session);
    await attemptGivenUpAfter(page, session, ATTEMPT_MS);
    await retrySentAfter(page, session, RETRY_GAP_MS);
    await expect(cardTitle(page)).toHaveText(SESSION_500_TITLE);
    await noFurtherRequest(page, session, 2);
  });

  test("a model list lost once and then answered 500 ends there: 2 requests and not the unreachable card", async ({
    page,
  }) => {
    // RED-IF an HTTP answer to the retry is treated as no answer. `/ready` is
    // hung so the readiness read's own request for the list is not counted.
    // Partner: the first attempt was given up, so this is the retry's answer.
    await page.setViewportSize(DESKTOP);
    await freezeClock(page);
    await answering(page, READY);
    const models = await answering(page, MODELS, ["hang"], 500);
    await openWorkspace(page);
    await firstRequestSent(models);
    await attemptGivenUpAfter(page, models, ATTEMPT_MS);
    await retrySentAfter(page, models, RETRY_GAP_MS);
    await expect(card(page)).toBeVisible();
    await expect(cardTitle(page)).not.toHaveText(CARD_TITLE);
    await noFurtherRequest(page, models, 2);
  });

  // ---------------------------------------------------------------------------
  // A person typing when the card arrives
  // ---------------------------------------------------------------------------

  for (const size of BOTH_WIDTHS) {
    for (const surface of [
      { box: "#query-text", open: openWorkspace, name: "the composer" },
      { box: "#landing-query", open: openLanding, name: "the landing" },
    ]) {
      test(`typing through the card on ${surface.name} keeps every character, focus and the view, at ${size.width}`, async ({
        page,
      }) => {
        // RED-IF the card takes focus or scrolls the page while someone types
        // (measured before W140: the box stopped at "Should I ", the rest was
        // lost and the spaces scrolled the page). Partner: the card did
        // appear, mid-sentence, as an alert.
        await page.setViewportSize(size);
        await freezeClock(page);
        const session = await answering(page, SESSION);
        await surface.open(page);
        await firstRequestSent(session);
        const box = page.locator(surface.box);
        await box.click();
        await box.evaluate((node) => node.scrollIntoView({ block: "start" }));
        await box.pressSequentially("Should I ");
        const before = await page.evaluate(() => window.scrollY);
        expect(before, "the person has scrolled down, so a scroll to the card would show").toBeGreaterThan(0);

        await bothAttemptsRunOut(page, session);
        await expectTheCard(page);
        await expect(card(page)).toHaveAttribute("role", "alert");
        await page.waitForTimeout(SMOOTH_SCROLL_MS);
        await expect(box, "focus stays in the box").toBeFocused();
        await expect(box).toBeInViewport();
        // The card opens above the box, and the browser keeps the box still by
        // moving the scroll position DOWN the page. A scroll to the card can
        // only move it UP.
        const after = await page.evaluate(() => window.scrollY);
        expect(after, "the page was not scrolled up to the card").toBeGreaterThanOrEqual(before);

        await page.keyboard.type("buy a house this year?");
        await expect(box).toHaveValue("Should I buy a house this year?");
        await expect(box).toBeFocused();
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Writes during and after a failed start-up
  // ---------------------------------------------------------------------------

  test("a hung session and a hung write together: a held sign-in ends with the button usable and no write sent", async ({
    page,
  }) => {
    // RED-IF the write goes out after the failed start-up: it could only be
    // refused, and on a dead connection it hangs with no limit, leaving the
    // button disabled for good (the start route here never answers). Partner:
    // the same route sees the start once the session has recovered, and the
    // sign-in then completes.
    await page.setViewportSize(DESKTOP);
    const account = freshAccount("w140-hung-write");
    await routeGoogle(page, account);
    await freezeClock(page);
    const session = await answering(page, SESSION);
    const start = await answering(page, SIGN_IN_START);
    await openWorkspace(page);
    await firstRequestSent(session);
    const button = page.locator("#sign-in-google");
    await button.click();

    await bothAttemptsRunOut(page, session);
    await expectTheCard(page);
    await expect(button, "the sign-in button is usable again").toBeEnabled();
    expect(start.sent(), "no write was sent").toBe(0);

    session.then = "pass";
    start.then = "pass";
    await page.clock.resume();
    await tryAgain(page).click();
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    await button.click();
    await expect(page.locator("#account-email")).toHaveText(account.email, { timeout: 15000 });
    expect(start.sent(), "the start went out once, after the recovery").toBe(1);
  });

  test('GUARD: a session that answers 500 after 12 s still sends the held "Sign in with Google" once (ADR-0188)', async ({
    page,
  }) => {
    // RED-IF the local refusal of a write spreads from "no answer" to an HTTP
    // answer: ADR-0188 has the start go out and be refused by the server, and
    // the button come back. Passes before W140: a guard. Partner: the server's
    // own refusal is what ended the click.
    await page.setViewportSize(DESKTOP);
    await freezeClock(page);
    const session = await answering(page, SESSION);
    const start = await answering(page, SIGN_IN_START, [], "pass");
    await openWorkspace(page);
    await firstRequestSent(session);
    const button = page.locator("#sign-in-google");
    await button.click();
    await page.clock.runFor(12000);
    expect(start.sent(), "the start waits for the session").toBe(0);
    const sent = nextRequestTo(page, SIGN_IN_START);
    await session.finishHung(500);
    expect([401, 403], "the server refuses a start sent without a session").toContain(
      (await (await sent).response())?.status(),
    );
    await expect(button).toBeEnabled({ timeout: 15000 });
    expect(start.sent()).toBe(1);
  });

  // ---------------------------------------------------------------------------
  // "Try again"
  // ---------------------------------------------------------------------------

  /** Open the workspace and run a hung session out to the card. The clock stays paused. */
  async function atTheCard(page: Page) {
    await freezeClock(page);
    const session = await answering(page, SESSION);
    await openWorkspace(page);
    await firstRequestSent(session);
    await bothAttemptsRunOut(page, session);
    await expectTheCard(page);
    return session;
  }

  test('during "Try again", Estimate waits, then prices with the new token', async ({ page }) => {
    // RED-IF the steps are not re-armed for the retry: the click then redraws
    // the card with a new live "Try again" (measured) and reads placeholder
    // slots. Partner: once the retry answers, the one waiting estimate goes
    // out, carrying that answer's token. Session requests are counted: 2 at
    // the card and 1 for the retry.
    await page.setViewportSize(DESKTOP);
    const estimates = writesTo(page, ESTIMATE);
    const session = await atTheCard(page);
    await page.clock.resume();
    await tryAgain(page).click();
    await expect.poll(session.sent).toBe(3);
    await page.locator("#query-text").fill(QUESTION);
    await pressEstimate(page);
    await page.waitForTimeout(QUIET_MS);
    expect(estimates, "the estimate waits for the retry").toHaveLength(0);
    await expect(card(page), "no card is redrawn while the retry runs").toBeHidden();

    const estimate = nextRequestTo(page, ESTIMATE);
    const answer = nextAnswerFrom(page, SESSION);
    await session.finishHung("pass");
    const token = await answerToken(answer);
    const sent = await estimate;
    expect(sent.headers()["x-csrf-token"]).toBe(token);
    expect((await sent.response())?.status()).toBe(200);
    await expect(costGate(page)).toBeVisible({ timeout: 15000 });
    expect(estimates).toHaveLength(1);
    expect(session.sent(), "no second retry").toBe(3);
  });

  test('during "Try again", sign-in waits, then goes out once with the new token', async ({ page }) => {
    // RED-IF the session step is not re-armed: the start goes out at once,
    // with no token, and is refused (or is refused locally by the rule for a
    // failed start-up, though a retry is running). Partner: once the retry
    // answers, the start goes out once with that token and the account shows.
    await page.setViewportSize(DESKTOP);
    const account = freshAccount("w140-try-again-sign-in");
    await routeGoogle(page, account);
    const starts = writesTo(page, SIGN_IN_START);
    const session = await atTheCard(page);
    await page.clock.resume();
    await tryAgain(page).click();
    await expect.poll(session.sent).toBe(3);
    await page.locator("#sign-in-google").click();
    await page.waitForTimeout(QUIET_MS);
    expect(starts, "the start waits for the retry").toHaveLength(0);

    const start = nextRequestTo(page, SIGN_IN_START);
    const answer = nextAnswerFrom(page, SESSION);
    await session.finishHung("pass");
    const token = await answerToken(answer);
    expect((await start).headers()["x-csrf-token"]).toBe(token);
    // Read here: the page that comes back from Google sends a session request of its own.
    expect(session.sent(), "no second retry").toBe(3);
    session.then = "pass";
    await expect(page.locator("#account-email")).toHaveText(account.email, { timeout: 15000 });
    expect(starts).toHaveLength(1);
  });

  test('"Try again" pressed twice sends one request', async ({ page }) => {
    // RED-IF there is no guard inside the function: the card's buttons are
    // rebuilt, so guarding the button cannot do it, and a second press queues
    // a second renewal behind the lock. Partner: the first press did send its
    // request, and the page recovers. Counted after the recovery too, because
    // a queued second renewal sends only once the first has finished.
    await page.setViewportSize(DESKTOP);
    const session = await atTheCard(page);
    await page.clock.resume();
    await tryAgain(page).evaluate((node) => {
      (node as HTMLButtonElement).click();
      (node as HTMLButtonElement).click();
    });
    await expect.poll(session.sent).toBe(3);
    await page.waitForTimeout(QUIET_MS);
    expect(session.sent()).toBe(3);
    session.then = "pass";
    await session.finishHung("pass");
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    await page.waitForTimeout(QUIET_MS);
    expect(session.sent(), "still one request after the recovery").toBe(3);
  });

  test('a "Try again" that also gets no answer: one attempt of 30 s, the card again, no reload, the question kept, "Disconnected"', async ({
    page,
  }) => {
    // RED-IF the page reloads on this failure (a reload on a dead connection
    // replaces the page with the browser's error page and loses the question),
    // the limit by hand is not 30 s, "Try again" retries by itself, the notice
    // does not run or does not clear, or the pill is left wrong. Partner: a
    // second "Try again" with the network back works, so the first left no
    // guard stuck.
    await page.setViewportSize(DESKTOP);
    await freezeClock(page);
    const session = await answering(page, SESSION);
    await openWorkspace(page);
    await firstRequestSent(session);
    await page.locator("#query-text").fill(QUESTION);
    await bothAttemptsRunOut(page, session);
    await expectTheCard(page);
    await page.evaluate(() => {
      (window as unknown as { __sameDocument: boolean }).__sameDocument = true;
    });

    await tryAgain(page).click();
    await expect.poll(session.sent).toBe(3);
    // The owner chose (CHG-113) that the notice shows as soon as "Try again"
    // is pressed: the person has just asked for a connection.
    await expect(notice(page), "the retry shows the notice at once").toBeInViewport();
    await expect(notice(page)).toHaveText("Still connecting…");
    await page.clock.runFor(BY_HAND_MS - 1);
    await page.waitForTimeout(QUIET_MS);
    expect(session.givenUp(), "the attempt is still running 1 ms before 30 s").toBe(2);
    await attemptGivenUpAfter(page, session, 1);

    await expectTheCard(page);
    await expect(notice(page)).toBeHidden();
    await expect(page.locator("#query-text"), "the typed question survives").toHaveValue(QUESTION);
    await expect(page.locator("#connection-pill-text")).toHaveText("Disconnected");
    expect(
      await page.evaluate(() => (window as unknown as { __sameDocument?: boolean }).__sameDocument),
      "the page did not reload",
    ).toBe(true);
    await noFurtherRequest(page, session, 3);

    session.then = "pass";
    await page.clock.resume();
    await tryAgain(page).click();
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    await expect(card(page)).toBeHidden();
    await expect(page.locator("#query-text")).toHaveValue(QUESTION);
    expect(session.sent()).toBe(4);
  });

  test('a "Try again" whose answer takes 20 s succeeds', async ({ page }) => {
    // RED-IF "Try again" uses the 15 s limit: a person on a link slower than
    // that could then never start. Partner: the attempt is still running at
    // 20 s, and it is that same answer that recovers the page.
    await page.setViewportSize(DESKTOP);
    const session = await atTheCard(page);
    await tryAgain(page).click();
    await expect.poll(session.sent).toBe(3);
    await page.clock.runFor(10000);
    await page.waitForTimeout(QUIET_MS);
    await page.clock.runFor(10000);
    await page.waitForTimeout(QUIET_MS);
    expect(session.givenUp(), "still waiting at 20 s").toBe(2);
    await session.finishHung("pass");
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    await expect(card(page)).toBeHidden();
    await expect(notice(page)).toBeHidden();
    await page.clock.resume();
    await estimatePrices(page);
    expect(session.sent()).toBe(3);
  });

  test('session answered, model list unreachable, "Try again": no new session request, and the same token still works', async ({
    page,
  }) => {
    // RED-IF "Try again" re-runs the session step when only the model step
    // failed: a pointless token rotation (this test then sees a third session
    // request, and the old token would be refused). `/ready` is hung so the
    // readiness read's own request for the list is not counted. RED-IF a
    // retry that fails at the model step leaves the pill on "Session active".
    // Partner: the model list IS asked again, and Estimate prices with the
    // first answer's token.
    await page.setViewportSize(DESKTOP);
    await freezeClock(page);
    await answering(page, READY);
    const session = await answering(page, SESSION, [], "pass");
    const models = await answering(page, MODELS);
    const answer = nextAnswerFrom(page, SESSION);
    await openWorkspace(page);
    const token = await answerToken(answer);
    await firstRequestSent(models);
    await bothAttemptsRunOut(page, models);
    await expectTheCard(page);

    await tryAgain(page).click();
    await expect.poll(models.sent).toBe(3);
    await attemptGivenUpAfter(page, models, BY_HAND_MS);
    await expectTheCard(page);
    await expect(page.locator("#connection-pill-text")).toHaveText("Disconnected");
    expect(session.sent(), "no new session request").toBe(1);

    models.then = "pass";
    await page.clock.resume();
    await tryAgain(page).click();
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    await expect(card(page)).toBeHidden();
    expect(models.sent()).toBe(4);
    expect(session.sent(), "no new session request").toBe(1);
    await estimatePrices(page, token);
  });

  test('a "Try again" whose session answers and whose model list does not: "Disconnected" with the card, and the next one asks only for the list', async ({
    page,
  }) => {
    // RED-IF the failure path of "Try again" leaves the pill as the session's
    // answer set it ("Session active" beside "Can't reach the server"), or the
    // page still remembers the first failure as the session's and renews again
    // on the next press. `/ready` is hung so the readiness read's own request
    // for the list is not counted. Partner: the session did answer that retry,
    // and the next press recovers with one more list request.
    await page.setViewportSize(DESKTOP);
    await answering(page, READY);
    const models = await answering(page, MODELS);
    const session = await atTheCard(page);
    expect(models.sent(), "the failed session skipped the model step").toBe(0);

    session.then = "pass";
    await tryAgain(page).click();
    await firstRequestSent(models);
    expect(session.sent()).toBe(3);
    await attemptGivenUpAfter(page, models, BY_HAND_MS);
    await expectTheCard(page);
    await expect(page.locator("#connection-pill-text")).toHaveText("Disconnected");

    models.then = "pass";
    await page.clock.resume();
    await tryAgain(page).click();
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    await expect(card(page)).toBeHidden();
    expect(models.sent()).toBe(2);
    expect(session.sent(), "no new session request").toBe(3);
  });

  // ---------------------------------------------------------------------------
  // A question kept across sign-in. The real path: signed in, the session aged
  // to its last minutes, "Run now" refused, "Sign in again", and the page that
  // comes back gets no answer to its session request.
  // ---------------------------------------------------------------------------

  const KEPT_QUESTION = "Which is older, the Great Wall or the pyramids at Giza?";
  const LATE_RUN_KEY = "quorum.lateRunQuestion";

  async function ageSession(page: Page, request: APIRequestContext, ageSeconds: number) {
    const cookies = await page.context().cookies();
    const cookie = cookies.find((c) => c.name === "quorum_session" || c.name === "__Host-quorum_session");
    expect(cookie, "the page holds a session cookie").toBeTruthy();
    const aged = await request.post(AGE_SESSIONS, {
      data: { session_id: cookie?.value ?? "", age_seconds: ageSeconds },
    });
    expect(aged.status(), "the lane's test-only handler found the session").toBe(200);
  }

  /** Back from "Sign in again" on a page whose start-up has run out, at the card. */
  async function backFromSignInAtTheCard(page: Page, request: APIRequestContext, label: string) {
    const account = freshAccount(label);
    await routeGoogle(page, account);
    await openWorkspace(page);
    await page.locator("#sign-in-google").click();
    await expect(page.locator("#account-email")).toHaveText(account.email);
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    await ageSession(page, request, 12 * HOUR - 600);
    await page.locator("#query-text").fill(KEPT_QUESTION);
    await page.locator("#run-now").click();
    const again = page.locator("#error-region-actions").getByRole("button", { name: "Sign in again", exact: true });
    await expect(again).toBeVisible();

    const session = await answering(page, SESSION);
    await freezeClock(page);
    const loaded = page.waitForEvent("load");
    await again.click();
    await loaded;
    await expect(page.locator("#account-email")).toHaveText(account.email);
    await firstRequestSent(session);
    await bothAttemptsRunOut(page, session);
    await expectTheCard(page);
    expect(
      await page.evaluate((key) => window.sessionStorage.getItem(key), LATE_RUN_KEY),
      "the kept question is waiting in this tab's storage",
    ).toContain(KEPT_QUESTION);
    return session;
  }

  test('a question kept across sign-in comes back after "Try again", and the state is ready', async ({
    page,
    request,
  }) => {
    // RED-IF the recovery skips what a good boot does (measured before W140:
    // an empty box, the question left in storage, and `data-app-state` stuck
    // at `error`). Partner: the question was in storage at the card, and is
    // gone from it now, so it is put back once.
    test.setTimeout(120000);
    const session = await backFromSignInAtTheCard(page, request, "w140-kept");
    await expect(page.locator("#query-text")).toHaveValue("");

    session.then = "pass";
    await page.clock.resume();
    await tryAgain(page).click();
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    await expect(page.locator("#query-text")).toHaveValue(KEPT_QUESTION);
    await expect(card(page)).toBeHidden();
    expect(await page.evaluate((key) => window.sessionStorage.getItem(key), LATE_RUN_KEY)).toBeNull();
  });

  test('a question kept across sign-in, then a different one typed at the card: "Try again" keeps what was typed and drops the saved one', async ({
    page,
    request,
  }) => {
    // RED-IF the put-back overwrites the box (it replaces the box without
    // looking), so the person loses what they typed since the page loaded; or
    // the saved copy stays, to fill the box at a later load. Partner: the
    // saved copy was there at the card, and this recovery is a full one.
    test.setTimeout(120000);
    const session = await backFromSignInAtTheCard(page, request, "w140-edited");
    const typed = "What should I read about the Silk Road?";
    await page.locator("#query-text").fill(typed);

    session.then = "pass";
    await page.clock.resume();
    await tryAgain(page).click();
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    await expect(page.locator("#query-text")).toHaveValue(typed);
    expect(await page.evaluate((key) => window.sessionStorage.getItem(key), LATE_RUN_KEY)).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // Two tabs
  // ---------------------------------------------------------------------------

  test("two tabs: a retry inside the lock posts its token, and the other tab's write succeeds", async ({ context }) => {
    // RED-IF the retry runs outside the lock or does not post what it got:
    // the server has retired B's token, so B's next write would be refused
    // with a 403. B boots first: the clock is shared by the context, and a
    // 15 s advance would also trip a waiting tab's 10 s lock wait. Partner:
    // B's own first token differs from the one its write carries, and the
    // write's 200 is the server's own check of it.
    await freezeClock(context);
    const tabB = await context.newPage();
    await tabB.setViewportSize(DESKTOP);
    const answerB = nextAnswerFrom(tabB, SESSION);
    await openWorkspace(tabB);
    const tokenB = await answerToken(answerB);
    await expect(appState(tabB)).toHaveAttribute("data-app-state", "ready");

    const tabA = await context.newPage();
    await tabA.setViewportSize(DESKTOP);
    const session = await answering(tabA, SESSION, ["hang"], "pass");
    await openWorkspace(tabA);
    await firstRequestSent(session);
    await attemptGivenUpAfter(tabA, session, ATTEMPT_MS);
    const answerA = nextAnswerFrom(tabA, SESSION);
    await retrySentAfter(tabA, session, RETRY_GAP_MS);
    const tokenA = await answerToken(answerA);
    await expect(appState(tabA)).toHaveAttribute("data-app-state", "ready");
    await expect(card(tabA)).toBeHidden();
    expect(tokenA, "the retry's token is a new one").not.toBe(tokenB);

    await tabA.clock.resume();
    await tabB.bringToFront();
    await expect.poll(session.sent).toBe(2);
    await tabB.waitForTimeout(QUIET_MS);
    await estimatePrices(tabB, tokenA);
  });
});
