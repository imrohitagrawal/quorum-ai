import { test, expect } from "@playwright/test";
import {
  aLiveRunAtTheWrongSessionCard,
  answeringWith401AuthRequired,
  answeringWith401Unchecked,
  answerToken,
  appState,
  attemptGivenUpAfter,
  atTheCardShown,
  atTheCardWithNoRawError,
  backFromSignInAtTheCard,
  bothAttemptsRunOut,
  BY_HAND_MS,
  card,
  costGate,
  DESKTOP,
  ESTIMATE,
  estimatePrices,
  expectTheCardAndNoRawError,
  expectTheCardShown,
  firstRequestSent,
  freezeClock,
  freshAccount,
  KEPT_QUESTION,
  LATE_RUN_KEY,
  midUseCard,
  MODELS,
  nextAnswerFrom,
  nextRequestTo,
  noFurtherRequest,
  NOT_STARTED,
  notice,
  ONE_RUN,
  openWorkspace,
  pill,
  pressEstimate,
  pressRunNow,
  progressList,
  QUESTION,
  QUIET_MS,
  READY,
  routeGoogle,
  SESSION,
  SIGN_IN_START,
  signIn,
  startASession,
  timeCard,
  tryAgain,
  writesTo,
  WRONG_SESSION,
} from "../../fixtures/start-up-limit";

/**
 * W140: the ways out of a failed start-up. "Try again" (one attempt of up to
 * 30 s, clicks held until it answers, no reload), "Start a session" with a run
 * or a result on screen, and the question kept across sign-in coming back
 * after the recovery. Decisions: ADR-0189. Shared helpers and how these tests
 * hold time: `e2e/fixtures/start-up-limit.ts`.
 */

test.describe("the page's start-up requests have a time limit (W140)", () => {
  // This group's own helpers (see the table in the fixture).
  const answering = answeringWith401Unchecked;
  const expectTheCard = expectTheCardAndNoRawError;
  const atTheCard = atTheCardWithNoRawError;

  // ---------------------------------------------------------------------------
  // "Try again"
  // ---------------------------------------------------------------------------

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
});

test.describe("the start-up limit, review round 1 (W140)", () => {
  // This group's own helpers (see the table in the fixture).
  const answering = answeringWith401AuthRequired;
  const expectTheCard = expectTheCardShown;
  const atTheCard = atTheCardShown;

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

  // ---------------------------------------------------------------------------
  // "Try again" and "Start a session" after a failure
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
});
