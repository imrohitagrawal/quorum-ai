import { test, expect } from "@playwright/test";
import {
  ANSWER_MS,
  answeringWith401AuthRequired,
  answeringWith401Unchecked,
  answerToken,
  appState,
  ATTEMPT_MS,
  attemptGivenUpAfter,
  BOTH_WIDTHS,
  bothAttemptsRunOut,
  card,
  CARD_TITLE,
  cardTitle,
  costGate,
  DESKTOP,
  estimatePrices,
  expectTheCardAndNoRawError,
  firstRequestSent,
  freezeClock,
  freshAccount,
  MODELS,
  nextAnswerFrom,
  nextRequestTo,
  nextStalledAnswer,
  noFurtherRequest,
  notice,
  openWorkspace,
  PHONE,
  pressEstimate,
  queryBox,
  QUESTION,
  QUIET_MS,
  READY,
  RETRY_GAP_MS,
  retrySentAfter,
  routeGoogle,
  SEEN_MS,
  serveWithRetryReachable,
  SESSION,
  SESSION_500_TITLE,
  SIGN_IN_START,
  startASession,
  startRetryNow,
  tryAgain,
  useStallServer,
  watchCrashes,
  writesTo,
} from "../../fixtures/start-up-limit";

/**
 * W140: the time limit on the page's two start-up requests, `GET /v1/session`
 * and `GET /v1/models/defaults`. One attempt is given up at 15 s and retried
 * once about 1 s later; an HTTP answer is never retried; a body that stalls
 * after good headers counts as no answer; a write held on a start-up that runs
 * out is not sent; each operation settles its own start-up steps; two tabs
 * share the retry's token. Decisions: ADR-0189. Shared helpers and how these
 * tests hold time: `e2e/fixtures/start-up-limit.ts`.
 */
useStallServer();

test.describe("the page's start-up requests have a time limit (W140)", () => {
  // This group's own helpers (see the table in the fixture).
  const answering = answeringWith401Unchecked;
  const expectTheCard = expectTheCardAndNoRawError;

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

test.describe("the start-up limit, review round 1 (W140)", () => {
  // This group's own helpers (see the table in the fixture).
  const answering = answeringWith401AuthRequired;

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

  // ---------------------------------------------------------------------------
  // The readiness read's toast
  // ---------------------------------------------------------------------------

  test("start-up fine and the readiness read fails: the operator's toast is still shown", async ({ page }) => {
    // RED-IF the toast is held back for good, not only beside the unreachable
    // card. The positive partner of this file's check that it is absent
    // there. Partner of this one: the readiness read really was refused.
    await page.setViewportSize(DESKTOP);
    const ready = await answering(page, READY, [], "refuse");
    await openWorkspace(page);
    await expect(appState(page)).toHaveAttribute("data-app-state", "ready");
    await expect(page.locator(".toast", { hasText: "Live-readiness" })).toBeVisible();
    expect(ready.givenUp()).toBeGreaterThan(0);
  });
});
