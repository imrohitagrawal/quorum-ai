import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import {
  test,
  expect,
  type APIRequestContext,
  type BrowserContext,
  type Page,
  type Request,
  type Response,
  type Route,
} from "@playwright/test";
import { markHelpSeen } from "./help";

/**
 * W140 (ADR-0189): helpers and constants shared by the start-up time-limit
 * specs in `tests/signed-in/`:
 *
 * - `start-up-limit-retries.spec.ts`: the limits, the one automatic retry,
 *   what an HTTP answer or a stalled body does, held writes, two tabs;
 * - `start-up-limit-notice-and-card.spec.ts`: "Still connecting…", the line,
 *   the card, typing and focus, phone screens, the card's sentence;
 * - `start-up-limit-recovery.spec.ts`: "Try again", "Start a session", a run
 *   or a result on screen, the question kept across sign-in.
 *
 * The page must give up on one attempt at 15 s, retry once about 1 s after an
 * attempt that got NO HTTP answer, and make one attempt of up to 30 s per step
 * on "Try again". Any HTTP answer ends the step as it did before W140.
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
 * TWO GROUPS OF TESTS, TWO SETS OF HELPERS. The tests were written in two
 * groups, which are still the two `describe` blocks in each spec. Three helpers
 * differ between the groups, and each `describe` binds its own at the top so
 * that every test runs exactly the steps it was written with:
 *
 * | Helper                     | "the page's start-up requests have a time limit" | "the start-up limit, review round 1"   |
 * |----------------------------|--------------------------------------------------|----------------------------------------|
 * | `answering` (a 401's body) | `answeringWith401Unchecked`: `SESSION_UNCHECKED` | `answeringWith401AuthRequired`: `AUTH_REQUIRED` |
 * | `expectTheCard`            | `expectTheCardAndNoRawError`: also the primary button and no abort or crash text | `expectTheCardShown`: title, card, button, state |
 * | `atTheCard`                | `atTheCardWithNoRawError`                        | `atTheCardShown`                       |
 *
 * Runs ONLY under `playwright.signed-in.config.ts`: the real app with Google
 * sign-in on against a loopback stub, $0, live execution off. Only the requests
 * a test names are held; everything else reaches the real server.
 */

export const QUESTION = "How should a small team choose between Postgres and MySQL?";
export const CARD_TITLE = "Can't reach the server";
export const CARD_SENTENCE = "The page could not connect to the server. Check your connection and try again.";
export const NOTICE_TEXT = "Still connecting…";
export const SESSION_500_TITLE = "Start a session to run a query";
const CRASH = "reading 'trim'";
export const NOT_STARTED = "Not started";
export const NO_ACTIVE_RUN = "No active run.";

// Literals on purpose: these are the published timings, written here
// independently of the page's own constants.
export const NOTICE_MS = 10000;
export const ATTEMPT_MS = 15000;
export const RETRY_GAP_MS = 1000;
export const BY_HAND_MS = 30000;

export const DESKTOP = { width: 1440, height: 900 };
export const PHONE = { width: 390, height: 844 };
// A phone with its browser bars showing, and with its keyboard up.
export const SHORT_PHONES = [
  { width: 390, height: 660 },
  { width: 390, height: 420 },
];
export const BOTH_WIDTHS = [DESKTOP, PHONE];

export const SESSION = "/v1/session";
export const MODELS = "/v1/models/defaults";
export const READY = "/ready";
export const SIGN_IN_START = "/v1/auth/google/start";
export const ESTIMATE = "/v1/query-runs/estimate";
export const ONE_RUN = /\/v1\/query-runs\/[0-9a-f-]+$/;
export const WRONG_SESSION = {
  status: 404,
  contentType: "application/json",
  body: JSON.stringify({ detail: { code: "QUERY_RUN_NOT_FOUND", message: "Not found." } }),
};

const AGE_SESSIONS = "http://127.0.0.1:18097/age-sessions";
const HOUR = 3600;

/** How long a real-time check waits for something that must NOT happen (a request, a change). */
export const QUIET_MS = 300;
/** A real-time wait long enough for a smooth scroll to have moved the page. */
export const SMOOTH_SCROLL_MS = 700;
/** Long enough for an abort to reach Playwright, short enough to go red fast. */
export const SEEN_MS = 5000;
/** How long a wait for a request or an answer the test has just caused may take. */
export const ANSWER_MS = 15000;

let counter = 0;
/** A Google subject and email no other test in the run uses. */
export function freshAccount(label: string): { sub: string; email: string } {
  counter += 1;
  const sub = `1140${Date.now()}${counter}`;
  return { sub, email: `${label}.${sub}@example.com` };
}

/** Catch Google's consent page and send the browser to the local callback. */
export async function routeGoogle(page: Page, account: { sub: string; email: string }) {
  await page.route("https://accounts.google.com/**", async (route) => {
    const asked = new URL(route.request().url());
    const back = new URL(asked.searchParams.get("redirect_uri") ?? "");
    back.searchParams.set("code", `${account.sub}|${account.email}`);
    back.searchParams.set("state", asked.searchParams.get("state") ?? "");
    await route.fulfill({ status: 302, headers: { location: back.href } });
  });
}

/** Install and pause the page clock. Call it before the page loads. */
export async function freezeClock(target: Page | BrowserContext) {
  const now = Date.now();
  await target.clock.install({ time: now });
  await target.clock.pauseAt(now + 1000);
}

/**
 * A server that sends good headers and the first bytes of a body, then never
 * finishes: `route.fulfill` cannot stall after its headers, and a stall has to
 * be a real one for the browser to raise what it really raises on an abort.
 * A spec that answers a request with "stall" calls this once, at its top level.
 */
let stallServer: Server;
let stallUrl = "";
export function useStallServer() {
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
}

/**
 * What a request gets: no answer at all, the real server's answer, a refused
 * connection, good headers and a body that never ends, or this HTTP status.
 * Only `answeringWith401Unchecked` gives "stall".
 */
export type Answer = "hang" | "pass" | "refuse" | "stall" | number;

function httpBody(status: number): string {
  // A 401 with this code is what a session store that cannot be checked sends.
  if (status === 401) {
    return JSON.stringify({ detail: { code: "SESSION_UNCHECKED", message: "We could not check your session." } });
  }
  return "{}";
}

/** A 401 that says the session is gone: the page answers it with "Start a session". */
const SESSION_REFUSED = JSON.stringify({ detail: { code: "AUTH_REQUIRED", message: "Start a session." } });

/** Give an answer; a 401 carries `SESSION_UNCHECKED`. */
async function giveWith401Unchecked(route: Route, answer: Answer) {
  if (answer === "pass") await route.continue();
  else if (answer === "refuse") await route.abort("connectionrefused");
  else if (answer === "stall") await route.continue({ url: stallUrl });
  else if (typeof answer === "number") {
    await route.fulfill({ status: answer, contentType: "application/json", body: httpBody(answer) });
  }
}

/** Give an answer; a 401 carries `AUTH_REQUIRED`. "stall" is not one of its answers. */
async function giveWith401AuthRequired(route: Route, answer: Answer) {
  if (answer === "pass") await route.continue();
  else if (answer === "refuse") await route.abort("connectionrefused");
  else if (typeof answer === "number") {
    await route.fulfill({
      status: answer,
      contentType: "application/json",
      body: answer === 401 ? SESSION_REFUSED : "{}",
    });
  }
}

/**
 * Answer every request to `path`: the first ones from `first`, in order, then
 * `line.then`. Counts what was sent, and what the page gave up on.
 */
function answeringWith(give: (route: Route, answer: Answer) => Promise<void>) {
  return async function answering(page: Page, path: string, first: Answer[] = [], then: Answer = "hang") {
    const queue = [...first];
    const mine = new Set<Request>();
    const hung: Route[] = [];
    let givenUp = 0;
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
  };
}

/** `answering` for the first group: a 401 is a session store that cannot be checked; "stall" works. */
export const answeringWith401Unchecked = answeringWith(giveWith401Unchecked);
/** `answering` for the review group: a 401 says the session is gone. */
export const answeringWith401AuthRequired = answeringWith(giveWith401AuthRequired);
export type Line = Awaited<ReturnType<typeof answeringWith401Unchecked>>;

/** Every write the page sends to `path`. */
export function writesTo(page: Page, path: string): Request[] {
  const writes: Request[] = [];
  page.on("request", (request) => {
    if (request.method() !== "GET" && new URL(request.url()).pathname === path) writes.push(request);
  });
  return writes;
}

/** Every uncaught error on the page; a raw abort would land here. */
export function watchCrashes(page: Page): string[] {
  const crashes: string[] = [];
  page.on("pageerror", (error) => crashes.push(error.message));
  return crashes;
}

export const firstRequestSent = (line: Line) =>
  expect.poll(line.sent, { message: "the page has sent its first attempt", timeout: SEEN_MS }).toBe(1);

/** Advance by `ms`, then wait for the page to give up on one more attempt. */
export async function attemptGivenUpAfter(page: Page, line: Line, ms: number) {
  const before = line.givenUp();
  await page.clock.runFor(ms);
  await expect
    .poll(line.givenUp, { message: `the page gives up on the attempt after ${ms} ms`, timeout: SEEN_MS })
    .toBe(before + 1);
}

/** Advance by `ms`, then wait for the page to send one more attempt. */
export async function retrySentAfter(page: Page, line: Line, ms: number) {
  const before = line.sent();
  await page.clock.runFor(ms);
  await expect
    .poll(line.sent, { message: `the page sends its one retry after ${ms} ms`, timeout: SEEN_MS })
    .toBe(before + 1);
}

/** Drive a held first attempt through its limit, the gap and the retry's limit. */
export async function bothAttemptsRunOut(page: Page, line: Line) {
  await attemptGivenUpAfter(page, line, ATTEMPT_MS);
  await retrySentAfter(page, line, RETRY_GAP_MS);
  await attemptGivenUpAfter(page, line, ATTEMPT_MS);
}

/** Run the clock on past where another attempt would start, and count again. */
export async function noFurtherRequest(page: Page, line: Line, expected: number) {
  await page.clock.runFor(RETRY_GAP_MS + 1);
  await page.waitForTimeout(QUIET_MS);
  await page.clock.runFor(ATTEMPT_MS);
  await page.waitForTimeout(QUIET_MS);
  expect(line.sent(), "no further automatic attempt").toBe(expected);
}

export const card = (page: Page) => page.locator("#error-region");
export const cardTitle = (page: Page) => page.locator("#error-region-title");
export const cardActions = (page: Page) => page.locator("#error-region-actions");
export const tryAgain = (page: Page) => cardActions(page).getByRole("button", { name: "Try again" });
export const startASession = (page: Page) =>
  cardActions(page).getByRole("button", { name: "Start a session", exact: true });
export const notice = (page: Page) => page.locator("#start-up-notice");
export const appState = (page: Page) => page.locator("html");
export const costGate = (page: Page) => page.locator('[data-view="cost-gate"]');
export const pill = (page: Page) => page.locator("#connection-pill-text");
export const timeCard = (page: Page) => page.locator("#time-meta");
export const progressList = (page: Page) => page.locator("#progress-list");
export const queryBox = (page: Page) => page.locator("#query-text");
export const focusedId = (page: Page) => page.evaluate(() => document.activeElement?.id);
export const scrollTop = (page: Page) => page.evaluate(() => window.scrollY);

/** The unreachable card, its primary "Try again", and never the browser's own words for an abort. */
export async function expectTheCardAndNoRawError(page: Page) {
  await expect(cardTitle(page)).toHaveText(CARD_TITLE);
  await expect(card(page)).toBeVisible();
  await expect(tryAgain(page)).toBeVisible();
  await expect(tryAgain(page)).toHaveClass(/button-primary/);
  await expect(appState(page)).toHaveAttribute("data-app-state", "error");
  // Never the browser's own words for an abort, on the card or anywhere else.
  await expect(card(page)).not.toContainText(/abort|signal/i);
  await expect(card(page)).not.toContainText(CRASH);
}

/** The unreachable card is up, with "Try again", and the state is `error`. */
export async function expectTheCardShown(page: Page) {
  await expect(cardTitle(page)).toHaveText(CARD_TITLE);
  await expect(card(page)).toBeVisible();
  await expect(tryAgain(page)).toBeVisible();
  await expect(appState(page)).toHaveAttribute("data-app-state", "error");
}

export async function openWorkspace(page: Page) {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem("quorum.workspaceSeen", "1");
    } catch (_) {}
  });
  await markHelpSeen(page);
  await page.goto("/ui", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-view="composer"]')).toBeVisible();
}

export async function openLanding(page: Page) {
  await markHelpSeen(page);
  await page.goto("/ui", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-view="landing"]')).toBeVisible();
  await expect(page.locator("#landing-query")).toBeVisible();
}

export async function pressEstimate(page: Page) {
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
export async function estimatePrices(page: Page, token?: string) {
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

export const answerToken = async (answer: Promise<Response>) =>
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

export const nextAnswerFrom = (page: Page, path: string) =>
  handledLater(page.waitForResponse((r) => new URL(r.url()).pathname === path, { timeout: ANSWER_MS }));

/** A stalled answer comes from the stall server, so that is the address it carries. */
export const nextStalledAnswer = (page: Page) =>
  handledLater(page.waitForResponse((r) => r.url() === stallUrl, { timeout: ANSWER_MS }));

export const nextRequestTo = (page: Page, path: string) =>
  handledLater(page.waitForRequest((r) => new URL(r.url()).pathname === path, { timeout: ANSWER_MS }));

/** Open the workspace and run a hung session out to the card. The clock stays paused. */
export async function atTheCardWithNoRawError(page: Page) {
  await freezeClock(page);
  const session = await answeringWith401Unchecked(page, SESSION);
  await openWorkspace(page);
  await firstRequestSent(session);
  await bothAttemptsRunOut(page, session);
  await expectTheCardAndNoRawError(page);
  return session;
}

/** Open the workspace and run a hung session out to the card. The clock stays paused. */
export async function atTheCardShown(page: Page) {
  await freezeClock(page);
  const session = await answeringWith401AuthRequired(page, SESSION);
  await openWorkspace(page);
  await firstRequestSent(session);
  await bothAttemptsRunOut(page, session);
  await expectTheCardShown(page);
  return session;
}

// A question kept across sign-in. The real path: signed in, the session aged
// to its last minutes, "Run now" refused, "Sign in again", and the page that
// comes back gets no answer to its session request.

export const KEPT_QUESTION = "Which is older, the Great Wall or the pyramids at Giza?";
export const LATE_RUN_KEY = "quorum.lateRunQuestion";

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
export async function backFromSignInAtTheCard(page: Page, request: APIRequestContext, label: string) {
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

  const session = await answeringWith401Unchecked(page, SESSION);
  await freezeClock(page);
  const loaded = page.waitForEvent("load");
  await again.click();
  await loaded;
  await expect(page.locator("#account-email")).toHaveText(account.email);
  await firstRequestSent(session);
  await bothAttemptsRunOut(page, session);
  await expectTheCardAndNoRawError(page);
  expect(
    await page.evaluate((key) => window.sessionStorage.getItem(key), LATE_RUN_KEY),
    "the kept question is waiting in this tab's storage",
  ).toContain(KEPT_QUESTION);
  return session;
}

/** A working page whose next estimate is told the session is gone: the "Start a session" card. */
export async function midUseCard(page: Page) {
  let first = true;
  await page.route(
    (url) => url.pathname === ESTIMATE,
    async (route) => {
      if (first) {
        first = false;
        await giveWith401AuthRequired(route, 401);
      } else await route.continue();
    },
  );
  await queryBox(page).fill(QUESTION);
  await pressEstimate(page);
  await expect(startASession(page)).toBeVisible();
}

/** Open the workspace signed in, as a person who has just come back from Google. */
export async function signIn(page: Page, label: string) {
  const account = freshAccount(label);
  await routeGoogle(page, account);
  await openWorkspace(page);
  await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
  await page.locator("#sign-in-google").click();
  await expect(page.locator("#account-email")).toHaveText(account.email);
  await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
}

export async function pressRunNow(page: Page) {
  await queryBox(page).fill(QUESTION);
  await page.locator("#run-now").click();
  const confirm = page.locator("#gate-confirm");
  if (await confirm.isVisible({ timeout: 8000 }).catch(() => false)) await confirm.click();
}

/**
 * A run on screen that stays live, whose Stop is answered "this run is not
 * yours": the card that offers "Start a session" while a run is going. Returns
 * the progress on the page, and from here on the page's polls get no answer, so
 * nothing redraws it behind the test's back.
 */
export async function aLiveRunAtTheWrongSessionCard(page: Page) {
  let holdPolls = false;
  await page.route(ONE_RUN, async (route) => {
    if (route.request().method() === "DELETE") {
      await route.fulfill(WRONG_SESSION);
      return;
    }
    if (holdPolls) return;
    const response = await route.fetch();
    const run = await response.json();
    run.status = "debate_round_1_running";
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(run) });
  });
  await pressRunNow(page);
  await expect(page.locator('[data-view="live-run"]')).toBeVisible({ timeout: 20000 });
  await expect(progressList(page).locator("> *")).not.toHaveCount(0);
  await page.locator("#live-stop").click();
  await expect(startASession(page)).toBeVisible();
  holdPolls = true;
  await page.waitForTimeout(QUIET_MS);
  const progress = await progressList(page).textContent();
  expect(progress, "the run's progress is on the page").not.toContain(NO_ACTIVE_RUN);
  return progress as string;
}

/**
 * The page's own `retrySession`, reachable from a test. No click was found that
 * starts a retry while boot is in its session or model step: an Estimate waits
 * for the model list, the session trail is empty and a failed sign-in shows a
 * toast. These tests hold that order anyway, because the steps must not depend
 * on it: the file as served gets this one added line and nothing else.
 */
export async function serveWithRetryReachable(page: Page) {
  await page.route(
    (url) => url.pathname === "/static/app.js",
    async (route) => {
      const response = await route.fetch();
      const source = await response.text();
      const place = "boot().catch((error) => {";
      if (source.split(place).length !== 2) throw new Error("the place for the added line was not found once");
      await route.fulfill({
        response,
        body: source.replace(place, `window.__startRetrySession = retrySession;\n  ${place}`),
      });
    },
  );
}

export const startRetryNow = (page: Page) =>
  page.evaluate(() => {
    void (window as unknown as { __startRetrySession: () => Promise<void> }).__startRetrySession();
  });
