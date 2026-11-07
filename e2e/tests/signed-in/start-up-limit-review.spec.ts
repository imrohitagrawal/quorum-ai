import { test, expect, type Page, type Request, type Route, type Response } from "@playwright/test";
import { markHelpSeen } from "../../fixtures/help";

/**
 * W140, review round 1: what `start-up-limit.spec.ts` did not hold. Each test
 * here either went red on the code that review read, or goes red on a mutation
 * that spec let through. Timing rules are that spec's: `page.clock` paused
 * before load, advanced in steps, polling for what the page sends.
 *
 * Runs ONLY under `playwright.signed-in.config.ts`: the real app with Google
 * sign-in on against a loopback stub, $0, live execution off. Only the requests
 * a test names are held; everything else reaches the real server.
 */

const QUESTION = "How should a small team choose between Postgres and MySQL?";
const CARD_TITLE = "Can't reach the server";
const CARD_SENTENCE = "The page could not connect to the server. Check your connection and try again.";
const NOTICE_TEXT = "Still connecting…";
const NOT_STARTED = "Not started";
const NO_ACTIVE_RUN = "No active run.";

// Literals on purpose: the published timings, independent of the page's constants.
const NOTICE_MS = 10000;
const ATTEMPT_MS = 15000;
const RETRY_GAP_MS = 1000;
const BY_HAND_MS = 30000;

const DESKTOP = { width: 1440, height: 900 };
const PHONE = { width: 390, height: 844 };
// A phone with its browser bars showing, and with its keyboard up.
const SHORT_PHONES = [
  { width: 390, height: 660 },
  { width: 390, height: 420 },
];
const BOTH_WIDTHS = [DESKTOP, PHONE];

const SESSION = "/v1/session";
const MODELS = "/v1/models/defaults";
const READY = "/ready";
const SIGN_IN_START = "/v1/auth/google/start";
const ESTIMATE = "/v1/query-runs/estimate";
const ONE_RUN = /\/v1\/query-runs\/[0-9a-f-]+$/;
const WRONG_SESSION = {
  status: 404,
  contentType: "application/json",
  body: JSON.stringify({ detail: { code: "QUERY_RUN_NOT_FOUND", message: "Not found." } }),
};

/** How long a real-time check waits for something that must NOT happen. */
const QUIET_MS = 300;
/** A real-time wait long enough for a smooth scroll to have moved the page. */
const SMOOTH_SCROLL_MS = 700;
/** Long enough for an abort to reach Playwright, short enough to go red fast. */
const SEEN_MS = 5000;
/** How long a wait for a request or an answer the test has just caused may take. */
const ANSWER_MS = 15000;

let counter = 0;
function freshAccount(label: string): { sub: string; email: string } {
  counter += 1;
  const sub = `1140${Date.now()}${counter}`;
  return { sub, email: `${label}.${sub}@example.com` };
}

async function freezeClock(page: Page) {
  const now = Date.now();
  await page.clock.install({ time: now });
  await page.clock.pauseAt(now + 1000);
}

type Answer = "hang" | "pass" | "refuse" | number;

const SESSION_REFUSED = JSON.stringify({ detail: { code: "AUTH_REQUIRED", message: "Start a session." } });

async function give(route: Route, answer: Answer) {
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

/** Answer every request to `path`: the first from `first`, then `line.then`. */
async function answering(page: Page, path: string, first: Answer[] = [], then: Answer = "hang") {
  const queue = [...first];
  const mine = new Set<Request>();
  const hung: Route[] = [];
  let givenUp = 0;
  const line = {
    then,
    sent: () => mine.size,
    givenUp: () => givenUp,
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
}
type Line = Awaited<ReturnType<typeof answering>>;

function writesTo(page: Page, path: string): Request[] {
  const writes: Request[] = [];
  page.on("request", (request) => {
    if (request.method() !== "GET" && new URL(request.url()).pathname === path) writes.push(request);
  });
  return writes;
}

const firstRequestSent = (line: Line) =>
  expect.poll(line.sent, { message: "the page has sent its first attempt", timeout: SEEN_MS }).toBe(1);

async function attemptGivenUpAfter(page: Page, line: Line, ms: number) {
  const before = line.givenUp();
  await page.clock.runFor(ms);
  await expect
    .poll(line.givenUp, { message: `the page gives up on the attempt after ${ms} ms`, timeout: SEEN_MS })
    .toBe(before + 1);
}

async function retrySentAfter(page: Page, line: Line, ms: number) {
  const before = line.sent();
  await page.clock.runFor(ms);
  await expect
    .poll(line.sent, { message: `the page sends its one retry after ${ms} ms`, timeout: SEEN_MS })
    .toBe(before + 1);
}

async function bothAttemptsRunOut(page: Page, line: Line) {
  await attemptGivenUpAfter(page, line, ATTEMPT_MS);
  await retrySentAfter(page, line, RETRY_GAP_MS);
  await attemptGivenUpAfter(page, line, ATTEMPT_MS);
}

const card = (page: Page) => page.locator("#error-region");
const cardTitle = (page: Page) => page.locator("#error-region-title");
const cardActions = (page: Page) => page.locator("#error-region-actions");
const tryAgain = (page: Page) => cardActions(page).getByRole("button", { name: "Try again" });
const startASession = (page: Page) => cardActions(page).getByRole("button", { name: "Start a session", exact: true });
const notice = (page: Page) => page.locator("#start-up-notice");
const appState = (page: Page) => page.locator("html");
const costGate = (page: Page) => page.locator('[data-view="cost-gate"]');
const pill = (page: Page) => page.locator("#connection-pill-text");
const timeCard = (page: Page) => page.locator("#time-meta");
const progressList = (page: Page) => page.locator("#progress-list");
const queryBox = (page: Page) => page.locator("#query-text");
const focusedId = (page: Page) => page.evaluate(() => document.activeElement?.id);
const scrollTop = (page: Page) => page.evaluate(() => window.scrollY);

async function expectTheCard(page: Page) {
  await expect(cardTitle(page)).toHaveText(CARD_TITLE);
  await expect(card(page)).toBeVisible();
  await expect(tryAgain(page)).toBeVisible();
  await expect(appState(page)).toHaveAttribute("data-app-state", "error");
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

async function pressEstimate(page: Page) {
  const button = page.locator("#estimate-run");
  await button.scrollIntoViewIfNeeded();
  await button.click();
}

function handledLater<T>(waiting: Promise<T>): Promise<T> {
  waiting.catch(() => {});
  return waiting;
}

const nextAnswerFrom = (page: Page, path: string) =>
  handledLater(page.waitForResponse((r) => new URL(r.url()).pathname === path, { timeout: ANSWER_MS }));

const nextRequestTo = (page: Page, path: string) =>
  handledLater(page.waitForRequest((r) => new URL(r.url()).pathname === path, { timeout: ANSWER_MS }));

const answerToken = async (answer: Promise<Response>) =>
  ((await (await answer).json()) as { csrf_token: string }).csrf_token;

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

/** A working page whose next estimate is told the session is gone: the "Start a session" card. */
async function midUseCard(page: Page) {
  let first = true;
  await page.route(
    (url) => url.pathname === ESTIMATE,
    async (route) => {
      if (first) {
        first = false;
        await give(route, 401);
      } else await route.continue();
    },
  );
  await queryBox(page).fill(QUESTION);
  await pressEstimate(page);
  await expect(startASession(page)).toBeVisible();
}

/** Open the workspace signed in, as a person who has just come back from Google. */
async function signIn(page: Page, label: string) {
  const account = freshAccount(label);
  await page.route("https://accounts.google.com/**", async (route) => {
    const asked = new URL(route.request().url());
    const back = new URL(asked.searchParams.get("redirect_uri") ?? "");
    back.searchParams.set("code", `${account.sub}|${account.email}`);
    back.searchParams.set("state", asked.searchParams.get("state") ?? "");
    await route.fulfill({ status: 302, headers: { location: back.href } });
  });
  await openWorkspace(page);
  await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
  await page.locator("#sign-in-google").click();
  await expect(page.locator("#account-email")).toHaveText(account.email);
  await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
}

async function pressRunNow(page: Page) {
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
async function aLiveRunAtTheWrongSessionCard(page: Page) {
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
async function serveWithRetryReachable(page: Page) {
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

const startRetryNow = (page: Page) =>
  page.evaluate(() => {
    void (window as unknown as { __startRetrySession: () => Promise<void> }).__startRetrySession();
  });

test.describe("the start-up limit, review round 1 (W140)", () => {
  // ---------------------------------------------------------------------------
  // Each operation settles its own start-up steps
  // ---------------------------------------------------------------------------

  test("a boot that ends during a retry does not release a sign-in waiting on that retry: it waits, then carries the new token", async ({
    page,
  }) => {
    // RED-IF boot settles the step the page holds now rather than its own: the
    // model answer then releases the retry's waiters and the sign-in goes out
    // with the token the renewal is about to retire. Partner: boot's failure
    // did show its card, and the start goes out once the renewal has answered.
    await page.setViewportSize(DESKTOP);
    await serveWithRetryReachable(page);
    await freezeClock(page);
    const starts = writesTo(page, SIGN_IN_START);
    await answering(page, SIGN_IN_START);
    const session = await answering(page, SESSION, ["pass"], "hang");
    const models = await answering(page, MODELS);
    const firstAnswer = nextAnswerFrom(page, SESSION);
    await openWorkspace(page);
    const oldToken = await answerToken(firstAnswer);
    await firstRequestSent(models);

    await startRetryNow(page);
    await expect.poll(session.sent, { message: "the renewal is on its way" }).toBe(2);
    await models.finishHung(401);
    await expect(startASession(page), "boot has ended, with its own card").toBeVisible();

    await page.locator("#sign-in-google").click();
    await page.waitForTimeout(QUIET_MS);
    expect(starts, "the sign-in waits for the renewal").toHaveLength(0);

    const start = nextRequestTo(page, SIGN_IN_START);
    const renewal = nextAnswerFrom(page, SESSION);
    await session.finishHung("pass");
    const newToken = await answerToken(renewal);
    expect(newToken).not.toBe(oldToken);
    expect((await start).headers()["x-csrf-token"]).toBe(newToken);
    expect(starts).toHaveLength(1);
  });

  test("an Estimate held on boot's step before a retry began still ends when boot's step ends", async ({ page }) => {
    // RED-IF boot's step is lost when a retry replaces the page's steps: the
    // click then waits on something nothing ever settles, and its button spins
    // for good. Partner: it was still waiting after the retry had drawn the
    // slots, and it prices the panel once boot's answer arrives.
    await page.setViewportSize(DESKTOP);
    await serveWithRetryReachable(page);
    await freezeClock(page);
    const models = await answering(page, MODELS, ["hang"], "pass");
    await openWorkspace(page);
    await firstRequestSent(models);
    await queryBox(page).fill(QUESTION);
    await pressEstimate(page);
    const button = page.locator("#estimate-run");
    await expect(button).toHaveAttribute("data-loading", "true");

    await startRetryNow(page);
    await expect(page.locator("select[data-model-slot]"), "the retry drew the slots").not.toHaveCount(0);
    await page.waitForTimeout(QUIET_MS);
    await expect(button, "still held on boot's step").toHaveAttribute("data-loading", "true");

    await models.finishHung("pass");
    await page.clock.resume();
    await expect(costGate(page), "the held click finishes").toBeVisible({ timeout: ANSWER_MS });
  });

  // ---------------------------------------------------------------------------
  // Typing protection, whichever path shows the card
  // ---------------------------------------------------------------------------

  for (const size of BOTH_WIDTHS) {
    test(`Estimate held at boot, back to the box and typing when start-up runs out: every character lands, at ${size.width}`, async ({
      page,
    }) => {
      // RED-IF the held click's own path shows the card with focus and scroll
      // (measured: focus on the card, the rest of the sentence lost, the spaces
      // scrolling the page). Partner: the click did finish, on that same card.
      await page.setViewportSize(size);
      await freezeClock(page);
      const session = await answering(page, SESSION);
      await openWorkspace(page);
      await firstRequestSent(session);
      await queryBox(page).fill("first thought");
      await pressEstimate(page);
      const button = page.locator("#estimate-run");
      await expect(button).toHaveAttribute("data-loading", "true");
      const box = queryBox(page);
      await box.click();
      await box.press("End");
      await page.keyboard.type(" and more");
      const before = await scrollTop(page);

      await bothAttemptsRunOut(page, session);
      await expectTheCard(page);
      await expect(button, "the held click has finished").not.toHaveAttribute("data-loading", "true");
      await page.waitForTimeout(SMOOTH_SCROLL_MS);
      await expect(box, "focus stays in the box").toBeFocused();
      expect(await scrollTop(page), "the page was not scrolled up to the card").toBeGreaterThanOrEqual(before);
      await page.keyboard.type(" KEPT");
      await expect(box).toHaveValue("first thought and more KEPT");
    });
  }

  test('Estimate held during "Try again", back to the box and typing when it runs out: every character lands', async ({
    page,
  }) => {
    // RED-IF the held click's own path takes the keyboard during a retry
    // (measured: value "first thought and more", focus on the card). Partner:
    // the attempt did run out, on the card, with the click finished.
    await page.setViewportSize(DESKTOP);
    const session = await atTheCard(page);
    const box = queryBox(page);
    await box.fill("first thought");
    await tryAgain(page).click();
    await expect.poll(session.sent).toBe(3);
    await pressEstimate(page);
    const button = page.locator("#estimate-run");
    await expect(button).toHaveAttribute("data-loading", "true");
    await box.click();
    await box.press("End");
    await page.keyboard.type(" and more");

    await attemptGivenUpAfter(page, session, BY_HAND_MS);
    await expectTheCard(page);
    await expect(button).not.toHaveAttribute("data-loading", "true");
    await page.keyboard.type(" KEPT");
    await page.waitForTimeout(SMOOTH_SCROLL_MS);
    await expect(box, "focus stays in the box").toBeFocused();
    await expect(box).toHaveValue("first thought and more KEPT");
  });

  test('typing while "Try again" runs out: focus stays in the box and every character lands', async ({ page }) => {
    // RED-IF a failed "Try again" shows the card with focus, by whatever route
    // it reaches it. The other spec tests typing only at boot's failure.
    // Partner: the card did arrive, mid-sentence.
    await page.setViewportSize(PHONE);
    const session = await atTheCard(page);
    await tryAgain(page).click();
    await expect.poll(session.sent).toBe(3);
    const box = queryBox(page);
    await box.click();
    await box.pressSequentially("Should I ");
    await attemptGivenUpAfter(page, session, BY_HAND_MS);
    await expectTheCard(page);
    await page.waitForTimeout(SMOOTH_SCROLL_MS);
    await expect(box, "focus stays in the box").toBeFocused();
    await page.keyboard.type("buy a house?");
    await expect(box).toHaveValue("Should I buy a house?");
  });

  test("not typing and scrolled down: the card comes into view and takes focus", async ({ page }) => {
    // RED-IF the card keeps focus off and stays out of view for someone who is
    // not in a text field: the notice goes and they are told nothing. Partner:
    // the page really was scrolled down, so coming into view is a scroll.
    await page.setViewportSize(PHONE);
    await freezeClock(page);
    const session = await answering(page, SESSION);
    await openWorkspace(page);
    await firstRequestSent(session);
    await page.evaluate(() => {
      (document.activeElement as HTMLElement | null)?.blur();
      window.scrollTo({ top: document.body.scrollHeight, behavior: "instant" as ScrollBehavior });
    });
    expect(await scrollTop(page)).toBeGreaterThan(0);
    await bothAttemptsRunOut(page, session);
    await expectTheCard(page);
    await expect(card(page), "the person can see the card").toBeInViewport();
    await expect.poll(() => focusedId(page)).toBe("error-region");
  });

  test("GUARD: a card from an HTTP answer still takes focus from someone typing, with no line", async ({ page }) => {
    // RED-IF the rule for the unreachable card spreads to the page's other
    // cards, which keep today's behaviour (ADR-0189 decision 5 names only this
    // one). Partner: this is the session's own card, and it has focus.
    await page.setViewportSize(DESKTOP);
    await freezeClock(page);
    const session = await answering(page, SESSION);
    await openWorkspace(page);
    await firstRequestSent(session);
    await queryBox(page).click();
    await session.finishHung(401);
    await expect(startASession(page)).toBeVisible();
    await expect.poll(() => focusedId(page)).toBe("error-region");
    await expect(notice(page)).toBeHidden();
    await expect(notice(page)).toHaveText("");
  });

  // ---------------------------------------------------------------------------
  // On a phone, someone typing still has a message on screen
  // ---------------------------------------------------------------------------

  for (const size of SHORT_PHONES) {
    test(`typing on a ${size.width}x${size.height} screen when start-up gives up: the line says so; pressing Estimate brings the card`, async ({
      page,
    }) => {
      // RED-IF "Still connecting…" just clears at the limit: nothing else is on
      // screen, so it reads as "connected". RED-IF the line stays once the card
      // is in view. Partner: the card, its button and the pill are really off
      // screen, and the next press of Estimate shows the card with focus.
      await page.setViewportSize(size);
      await freezeClock(page);
      const session = await answering(page, SESSION);
      await openWorkspace(page);
      await firstRequestSent(session);
      const box = queryBox(page);
      await box.click();
      await page.keyboard.type("half a que");
      await bothAttemptsRunOut(page, session);
      await expectTheCard(page);

      await expect(notice(page), "on screen, with the card out of view").toBeInViewport();
      await expect(notice(page)).toHaveText(CARD_TITLE);
      await expect(notice(page)).toHaveAttribute("role", "status");
      await expect(cardTitle(page), "the card itself is off screen").not.toBeInViewport();
      await expect(tryAgain(page)).not.toBeInViewport();
      await expect(page.locator("#connection-pill")).not.toBeInViewport();
      await expect(box).toBeFocused();

      await pressEstimate(page);
      await expect(notice(page), "the line gives way to the card").toBeHidden();
      await expect(notice(page)).toHaveText("");
      await expect(card(page)).toBeInViewport();
      await expect.poll(() => focusedId(page)).toBe("error-region");
    });

    test(`not typing on a ${size.width}x${size.height} screen when start-up gives up: no line, the card instead`, async ({
      page,
    }) => {
      // RED-IF the line shows for someone who is not in a text field: the card
      // comes to them, and a second message beside it says the same thing.
      // Partner: the card is on screen and has focus.
      await page.setViewportSize(size);
      await freezeClock(page);
      const session = await answering(page, SESSION);
      await openWorkspace(page);
      await firstRequestSent(session);
      await bothAttemptsRunOut(page, session);
      await expectTheCard(page);
      await expect(card(page)).toBeInViewport();
      await expect.poll(() => focusedId(page)).toBe("error-region");
      await expect(notice(page), "the line is in the page, so its being hidden means something").toBeAttached();
      await expect(notice(page)).toBeHidden();
      await expect(notice(page)).toHaveText("");
    });
  }

  test("a held click, with the person back in the box: the line shows after that path too", async ({ page }) => {
    // RED-IF the line depends on which path showed the card. Partner: the held
    // click did end, and its path was the last to show the card.
    await page.setViewportSize(SHORT_PHONES[0]);
    await freezeClock(page);
    const session = await answering(page, SESSION);
    await openWorkspace(page);
    await firstRequestSent(session);
    await queryBox(page).fill("first thought");
    await pressEstimate(page);
    const button = page.locator("#estimate-run");
    await expect(button).toHaveAttribute("data-loading", "true");
    await queryBox(page).click();
    await bothAttemptsRunOut(page, session);
    await expectTheCard(page);
    await expect(button).not.toHaveAttribute("data-loading", "true");
    await page.waitForTimeout(QUIET_MS);
    await expect(notice(page)).toBeInViewport();
    await expect(notice(page)).toHaveText(CARD_TITLE);
    await expect(queryBox(page)).toBeFocused();
  });

  test("the line is un-hidden first and its text written after, so a screen reader announces it", async ({ page }) => {
    // RED-IF the text is written while the line is hidden. A refused connection
    // reaches the card before 10 s, so here the line starts hidden. Partner:
    // both changes were recorded, in this order, and the text is the card's.
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
    const session = await answering(page, SESSION, [], "refuse");
    await openWorkspace(page);
    await queryBox(page).click();
    await expect.poll(session.givenUp, { timeout: SEEN_MS }).toBe(1);
    await retrySentAfter(page, session, RETRY_GAP_MS);
    await expectTheCard(page);
    await expect(notice(page)).toHaveText(CARD_TITLE);
    const changes = await page.evaluate(() => (window as unknown as { __noticeChanges: string[] }).__noticeChanges);
    expect(changes).toEqual(["shown", "text"]);
  });

  test("the card's dismissal clears the line", async ({ page }) => {
    // RED-IF the line outlives its card: "Can't reach the server" over a page
    // with nothing to act on. Partner: the line was up first, and the card did
    // go.
    await page.setViewportSize(DESKTOP);
    await freezeClock(page);
    const session = await answering(page, SESSION);
    await openWorkspace(page);
    await firstRequestSent(session);
    await queryBox(page).click();
    await bothAttemptsRunOut(page, session);
    await expectTheCard(page);
    await expect(notice(page)).toHaveText(CARD_TITLE);
    await expect(card(page)).toBeVisible();
    await expect(notice(page)).toBeVisible();
    await page.locator("#error-region-dismiss").click();
    await expect(card(page)).toBeHidden();
    await expect(notice(page)).toBeHidden();
  });

  test('"Try again" turns the line to "Still connecting…" at once, and a recovery leaves nothing', async ({
    page,
  }) => {
    // RED-IF the line keeps the card's title while a retry runs (it would say
    // the server cannot be reached while the page is trying), or the retry's
    // notice waits 10 s (CHG-113: it shows at once).
    // Partner: the line was up first, and the retry recovers the page.
    await page.setViewportSize(DESKTOP);
    await freezeClock(page);
    const session = await answering(page, SESSION);
    await openWorkspace(page);
    await firstRequestSent(session);
    await queryBox(page).click();
    await bothAttemptsRunOut(page, session);
    await expectTheCard(page);
    await expect(notice(page)).toHaveText(CARD_TITLE);

    await tryAgain(page).click();
    await expect(notice(page), "a retry says it is connecting, at once").toHaveText(NOTICE_TEXT);
    await expect.poll(session.sent).toBe(3);

    await session.finishHung("pass");
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    await expect(notice(page)).toBeHidden();
    await page.clock.runFor(NOTICE_MS);
    await page.waitForTimeout(QUIET_MS);
    await expect(notice(page), "nothing comes back after the recovery").toBeHidden();
  });

  test('a press of Estimate leaves "Still connecting…" up while a retry runs, after the line has gone', async ({
    page,
  }) => {
    // RED-IF clearing the card also takes away the notice of a start-up still
    // running, or the page goes on thinking the line is held once it has gone:
    // Estimate clears the card, and the person would lose the only message that
    // says the page is still trying. Partner: the line was up first, and the
    // click is really waiting on the retry.
    await page.setViewportSize(DESKTOP);
    await freezeClock(page);
    const session = await answering(page, SESSION);
    await openWorkspace(page);
    await firstRequestSent(session);
    await queryBox(page).fill(QUESTION);
    await bothAttemptsRunOut(page, session);
    await expectTheCard(page);
    await expect(notice(page)).toHaveText(CARD_TITLE);

    await tryAgain(page).click();
    await expect.poll(session.sent).toBe(3);
    await page.clock.runFor(NOTICE_MS);
    await expect(notice(page)).toHaveText(NOTICE_TEXT);
    await pressEstimate(page);
    await expect(page.locator("#estimate-run")).toHaveAttribute("data-loading", "true");
    await page.waitForTimeout(QUIET_MS);
    await expect(notice(page), "the page is still trying, and says so").toHaveText(NOTICE_TEXT);
    await expect(notice(page)).toBeVisible();
  });

  test("a later card clears the line, without a clear first", async ({ page }) => {
    // RED-IF only clearError takes the line away: a session-trail click draws
    // its failure with no clear before it, so "Can't reach the server" would
    // sit over a different card. Partner: the line was up, and the later card
    // is really on screen under its own title.
    test.setTimeout(120000);
    await page.setViewportSize(DESKTOP);
    const session = await answering(page, SESSION, [], "pass");
    await signIn(page, "w140-later-card");
    await pressRunNow(page);
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 60000 });
    await page.route(ONE_RUN, (route) => route.fulfill(WRONG_SESSION));
    const entry = page.locator(".session-trail-entry").first();
    await entry.click();
    await expect(startASession(page)).toBeVisible();
    const wrongSessionTitle = await cardTitle(page).textContent();

    await freezeClock(page);
    session.then = "hang";
    const before = session.sent();
    await startASession(page).click();
    await expect.poll(session.sent).toBe(before + 1);
    const box = page.locator("#result-next-input");
    await box.click();
    await page.keyboard.type("and then");
    await attemptGivenUpAfter(page, session, BY_HAND_MS);
    await expectTheCard(page);
    await expect(notice(page)).toHaveText(CARD_TITLE);
    await expect(box).toBeFocused();

    await entry.click();
    await expect(cardTitle(page)).toHaveText(wrongSessionTitle as string);
    await expect(notice(page)).toBeHidden();
  });

  for (const size of BOTH_WIDTHS) {
    test(`the line is on top of the page and takes no clicks, at ${size.width}`, async ({ page }) => {
      // RED-IF it sits behind what is on the page (`toBeInViewport` and
      // `toBeVisible` cannot see that), or catches clicks meant for what is
      // under it. `pointer-events: none` makes `elementFromPoint` skip the
      // line, so: first, as shipped, the point reaches what is under it; then,
      // with pointer events switched on for this one check, the same points hit
      // the line itself, which holds only if nothing is stacked above it.
      // Partner: the line is on screen and has a real box.
      await page.setViewportSize(size);
      await freezeClock(page);
      const session = await answering(page, SESSION);
      await openWorkspace(page);
      await firstRequestSent(session);
      await page.clock.runFor(NOTICE_MS);
      await expect(notice(page)).toBeInViewport();

      const hits = await notice(page).evaluate((node) => {
        const box = node.getBoundingClientRect();
        const points = [
          [box.left + box.width / 2, box.top + box.height / 2],
          [box.left + 4, box.top + 4],
          [box.right - 4, box.bottom - 4],
        ];
        const hitIsLine = () =>
          points.map(([x, y]) => document.elementFromPoint(x, y)?.id === "start-up-notice");
        const asShipped = hitIsLine();
        (node as HTMLElement).style.pointerEvents = "auto";
        const switchedOn = hitIsLine();
        (node as HTMLElement).style.pointerEvents = "";
        return { width: box.width, asShipped, switchedOn };
      });
      expect(hits.width).toBeGreaterThan(0);
      expect(hits.asShipped, "a click at the line reaches what is under it").toEqual([false, false, false]);
      expect(hits.switchedOn, "the line is what is on top at each point").toEqual([true, true, true]);
    });
  }

  // ---------------------------------------------------------------------------
  // "Start a session" with a run on screen
  // ---------------------------------------------------------------------------

  test('"Start a session" from the wrong-session card with a run live leaves that run\'s progress alone', async ({
    page,
  }) => {
    // RED-IF a recovery with no failed start-up behind it runs the end of
    // start-up: the live run's progress then reads "No active run." Partner:
    // the progress was on the page, the session was renewed, and the run is
    // still on screen.
    await page.setViewportSize(DESKTOP);
    const session = await answering(page, SESSION, [], "pass");
    await signIn(page, "w140-live-run");
    const progress = await aLiveRunAtTheWrongSessionCard(page);
    const before = session.sent();
    await startASession(page).click();
    await expect(page.locator(".toast", { hasText: "Session started" })).toBeVisible();
    expect(session.sent(), "the session was renewed").toBe(before + 1);
    await expect(progressList(page)).toHaveText(progress);
    await expect(page.locator('[data-view="live-run"]')).toBeVisible();
  });

  test('the same, when "Start a session" gets no answer and "Try again" then recovers: the progress stays, and the state is ready', async ({
    page,
  }) => {
    // RED-IF the page takes any failed retry as a start-up that never finished:
    // the failure is recorded here, on a page that started long ago, and the
    // recovery would wipe the live run's progress. Partner: the card was up
    // with state `error`, and the recovery brought it back to `ready`.
    await page.setViewportSize(DESKTOP);
    const session = await answering(page, SESSION, [], "pass");
    await signIn(page, "w140-live-run-no-answer");
    const progress = await aLiveRunAtTheWrongSessionCard(page);
    await freezeClock(page);
    session.then = "hang";
    const before = session.sent();
    await startASession(page).click();
    await expect.poll(session.sent).toBe(before + 1);
    await attemptGivenUpAfter(page, session, BY_HAND_MS);
    await expectTheCard(page);

    session.then = "pass";
    await page.clock.resume();
    await tryAgain(page).click();
    await expect(page.locator(".toast", { hasText: "Session started" })).toBeVisible();
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    await expect(progressList(page)).toHaveText(progress);
    await expect(page.locator('[data-view="live-run"]')).toBeVisible();
  });

  test('"Start a session" over a finished result keeps that result\'s time', async ({ page }) => {
    // RED-IF the end of start-up runs on this recovery: the finished run's time
    // goes back to "Not started". Partner: the time was on the page, and the
    // session was renewed.
    test.setTimeout(120000);
    await page.setViewportSize(DESKTOP);
    const session = await answering(page, SESSION, [], "pass");
    await signIn(page, "w140-result-time");
    await pressRunNow(page);
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 60000 });
    await expect(timeCard(page), "the finished run's time is on the page").not.toHaveText(NOT_STARTED);
    const finishedAt = await timeCard(page).textContent();
    await page.route(ONE_RUN, (route) => route.fulfill(WRONG_SESSION));
    await page.locator(".session-trail-entry").first().click();
    await expect(startASession(page)).toBeVisible();
    const before = session.sent();
    await startASession(page).click();
    await expect(page.locator(".toast", { hasText: "Session started" })).toBeVisible();
    expect(session.sent(), "the session was renewed").toBe(before + 1);
    await expect(timeCard(page)).toHaveText(finishedAt as string);
  });

  test('"Start a session" on a working page keeps the models chosen', async ({ page }) => {
    // RED-IF a recovery on a page that has already started redraws the model
    // slots from the defaults. Partner: the choice differed from the default
    // before the card, and the session was renewed.
    await page.setViewportSize(DESKTOP);
    const session = await answering(page, SESSION, [], "pass");
    await signIn(page, "w140-chosen-models");
    const slot = page.locator("select[data-model-slot]").first();
    const defaultModel = await slot.inputValue();
    const other = await slot.locator("option").evaluateAll(
      (options, current) => options.map((o) => (o as HTMLOptionElement).value).find((v) => v && v !== current),
      defaultModel,
    );
    expect(other, "the catalog offers another model").toBeTruthy();
    await slot.selectOption(other as string);
    await midUseCard(page);
    const before = session.sent();
    await startASession(page).click();
    await expect(page.locator(".toast", { hasText: "Session started" })).toBeVisible();
    expect(session.sent(), "the session was renewed").toBe(before + 1);
    await expect(page.locator("select[data-model-slot]").first()).toHaveValue(other as string);
  });

  test('"Start a session" over a transcript keeps its simulated-output notice', async ({ page }) => {
    // RED-IF a recovery on a page that has already started redraws the model
    // panels, which hides the notice that the answers were simulated. Partner:
    // the notice was on screen before the card, and the session was renewed.
    test.setTimeout(120000);
    await page.setViewportSize(DESKTOP);
    const session = await answering(page, SESSION, [], "pass");
    await signIn(page, "w140-transcript-notice");
    await pressRunNow(page);
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 60000 });
    await page.locator("#result-transcript-link").click();
    const banner = page.locator("#demo-mode-banner");
    await expect(banner, "the notice is on screen").toBeVisible();
    await page.route(ONE_RUN, (route) => route.fulfill(WRONG_SESSION));
    await page.locator(".session-trail-entry").first().click();
    await expect(startASession(page)).toBeVisible();
    const before = session.sent();
    await startASession(page).click();
    await expect(page.locator(".toast", { hasText: "Session started" })).toBeVisible();
    expect(session.sent(), "the session was renewed").toBe(before + 1);
    await expect(banner).toBeVisible();
  });

  test("a sign-in does not wait for the model list once the session has answered", async ({ page }) => {
    // RED-IF boot releases a write's wait only when both steps end: this click
    // would then sit behind a hung model list. Partner: the model list is seen
    // to be unanswered, and the start carries the token the session gave.
    await page.setViewportSize(DESKTOP);
    const models = await answering(page, MODELS);
    const starts = writesTo(page, SIGN_IN_START);
    await page.route("https://accounts.google.com/**", (route) => route.abort());
    const answer = nextAnswerFrom(page, SESSION);
    await openWorkspace(page);
    const token = await answerToken(answer);
    await firstRequestSent(models);
    await page.locator("#sign-in-google").click();
    await expect.poll(() => starts.length, { timeout: SEEN_MS }).toBe(1);
    expect(models.givenUp(), "the model list is still unanswered").toBe(0);
    expect(starts[0].headers()["x-csrf-token"]).toBe(token);
  });

  test("typing an email address when start-up runs out: every character lands", async ({ page }) => {
    // RED-IF the check for "someone is typing" leaves out email fields: the card
    // then takes the focus from the account-deletion address. Partner: the
    // field had the focus and the card came.
    await page.setViewportSize(DESKTOP);
    const label = "w140-email-field";
    await signIn(page, label);
    await freezeClock(page);
    const session = await answering(page, SESSION);
    await page.reload({ waitUntil: "domcontentloaded" });
    await firstRequestSent(session);
    await page.locator("#account-history summary").click();
    await page.locator("#account-delete-start").click();
    const field = page.locator("#account-delete-email");
    await field.click();
    await page.keyboard.type("first.part");
    await bothAttemptsRunOut(page, session);
    await expect(card(page), "the card came").toBeVisible();
    await page.keyboard.type("@example.com");
    await expect(field).toHaveValue("first.part@example.com");
    expect(await focusedId(page)).toBe("account-delete-email");
  });

  // ---------------------------------------------------------------------------
  // The card's sentence
  // ---------------------------------------------------------------------------

  test("the card says exactly what is known, and promises nothing about what was typed", async ({ page }) => {
    // RED-IF the sentence changes, or goes back to claiming nothing typed was
    // lost: a "Try again" answered by a 500 reloads and empties the box.
    // Partner: this is the unreachable card, title included.
    await page.setViewportSize(DESKTOP);
    await atTheCard(page);
    await expect(page.locator("#error-region-message")).toHaveText(CARD_SENTENCE);
  });

  // ---------------------------------------------------------------------------
  // "Try again" and "Start a session", the parts the other spec lets through
  // ---------------------------------------------------------------------------

  test('HTTP failure, then "Start a session" gets no answer: a sign-in click ends with the button usable and no write sent', async ({
    page,
  }) => {
    // RED-IF a failed retry leaves the earlier failure on record: the page then
    // thinks an HTTP answer came, and the write goes out on a dead connection.
    // Partner: the first card was the session's own, and the second is the
    // unreachable one.
    await page.setViewportSize(DESKTOP);
    await freezeClock(page);
    const session = await answering(page, SESSION, [500], "hang");
    const start = await answering(page, SIGN_IN_START);
    await openWorkspace(page);
    await firstRequestSent(session);
    await expect(startASession(page)).toBeVisible();
    await startASession(page).click();
    await expect.poll(session.sent).toBe(2);
    await attemptGivenUpAfter(page, session, BY_HAND_MS);
    await expectTheCard(page);
    const button = page.locator("#sign-in-google");
    await button.click();
    await page.waitForTimeout(QUIET_MS);
    expect(start.sent(), "no write was sent").toBe(0);
    await expect(button, "the sign-in button is usable").toBeEnabled();
  });

  test('after a recovery, a session that goes later: "Start a session" still asks for a new one', async ({ page }) => {
    // RED-IF the failure stays on record after the recovery: "Start a session"
    // then skips the session step and reports success with no session. Partner:
    // the recovery itself sent its request, and the later card is the session's.
    await page.setViewportSize(DESKTOP);
    const session = await atTheCard(page);
    session.then = "pass";
    await page.clock.resume();
    await tryAgain(page).click();
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    const before = session.sent();
    expect(before).toBe(3);
    await midUseCard(page);
    await startASession(page).click();
    await expect.poll(session.sent).toBe(before + 1);
  });

  test('"Start a session" gets no answer on a working page, then "Try again": the session is asked for again', async ({
    page,
  }) => {
    // RED-IF the page still remembers the session answered at boot: "Try again"
    // skips the one step that failed. Partner: the page recovers, and the
    // request count is exact.
    await page.setViewportSize(DESKTOP);
    await freezeClock(page);
    const session = await answering(page, SESSION, [], "pass");
    await openWorkspace(page);
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    const before = session.sent();
    await midUseCard(page);
    session.then = "hang";
    await startASession(page).click();
    await expect.poll(session.sent).toBe(before + 1);
    await attemptGivenUpAfter(page, session, BY_HAND_MS);
    await expectTheCard(page);
    session.then = "pass";
    await page.clock.resume();
    await tryAgain(page).click();
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    expect(session.sent(), "the session that got no answer is asked for again").toBe(before + 2);
  });

  test('a "Try again" that re-asks only the model list ends with the pill saying the session is active', async ({
    page,
  }) => {
    // RED-IF the pill is set only by the session step: after a retry of the
    // model list alone, a working page reads "Connecting" for good. Partner:
    // the session was not asked again, so nothing else could have set it.
    await page.setViewportSize(DESKTOP);
    await freezeClock(page);
    await answering(page, READY);
    const session = await answering(page, SESSION, [], "pass");
    const models = await answering(page, MODELS);
    await openWorkspace(page);
    await firstRequestSent(models);
    await bothAttemptsRunOut(page, models);
    await expectTheCard(page);
    models.then = "pass";
    await page.clock.resume();
    await tryAgain(page).click();
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    await expect(pill(page)).toHaveText(/Session active/);
    expect(session.sent(), "no new session request").toBe(1);
  });

  test("start-up fine and the readiness read fails: the operator's toast is still shown", async ({ page }) => {
    // RED-IF the toast is held back for good, not only beside the unreachable
    // card. The positive partner of the other spec's check that it is absent
    // there. Partner of this one: the readiness read really was refused.
    await page.setViewportSize(DESKTOP);
    const ready = await answering(page, READY, [], "refuse");
    await openWorkspace(page);
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    await expect(page.locator(".toast", { hasText: "Live-readiness" })).toBeVisible();
    expect(ready.givenUp()).toBeGreaterThan(0);
  });
});
