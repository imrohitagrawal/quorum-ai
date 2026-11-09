import { test, expect } from "@playwright/test";
import {
  answeringWith401AuthRequired,
  answeringWith401Unchecked,
  appState,
  attemptGivenUpAfter,
  atTheCardShown,
  BOTH_WIDTHS,
  bothAttemptsRunOut,
  BY_HAND_MS,
  card,
  CARD_SENTENCE,
  CARD_TITLE,
  cardTitle,
  costGate,
  DESKTOP,
  expectTheCardAndNoRawError,
  expectTheCardShown,
  firstRequestSent,
  focusedId,
  freezeClock,
  MODELS,
  notice,
  NOTICE_MS,
  NOTICE_TEXT,
  ONE_RUN,
  openLanding,
  openWorkspace,
  PHONE,
  pill,
  pressEstimate,
  pressRunNow,
  queryBox,
  QUESTION,
  QUIET_MS,
  RETRY_GAP_MS,
  retrySentAfter,
  scrollTop,
  SEEN_MS,
  SESSION,
  SHORT_PHONES,
  signIn,
  SMOOTH_SCROLL_MS,
  startASession,
  tryAgain,
  WRONG_SESSION,
} from "../../fixtures/start-up-limit";

/**
 * W140: what a person sees while start-up is slow or has run out.
 * "Still connecting…" at 10 s, the line that stands in for the card on a short
 * phone screen, the card "Can't reach the server" and its sentence, and the
 * keyboard: someone typing keeps every character and their focus whichever
 * path shows the card. Decisions: ADR-0189. Shared helpers and how these tests
 * hold time: `e2e/fixtures/start-up-limit.ts`.
 */

test.describe("the page's start-up requests have a time limit (W140)", () => {
  // This group's own helpers (see the table in the fixture).
  const answering = answeringWith401Unchecked;
  const expectTheCard = expectTheCardAndNoRawError;

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
});

test.describe("the start-up limit, review round 1 (W140)", () => {
  // This group's own helpers (see the table in the fixture).
  const answering = answeringWith401AuthRequired;
  const expectTheCard = expectTheCardShown;
  const atTheCard = atTheCardShown;

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
    // it reaches it. The tests above cover typing only at boot's failure.
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
        // Points clear of the rounded corners: a point 4 px in from a corner of
        // radius 14 px lies just outside the shape, so whether it hit the line
        // depended on sub-pixel layout (it failed once in CI with the line
        // visibly on top). Both ends of the middle line, and the top and bottom
        // of the centre, where the edge is straight, so a strip over either
        // half is still seen.
        const middle = box.top + box.height / 2;
        const centre = box.left + box.width / 2;
        const points = [
          [centre, middle],
          [box.left + 16, middle],
          [box.right - 16, middle],
          [centre, box.top + 3],
          [centre, box.bottom - 3],
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
      expect(hits.asShipped, "a click at the line reaches what is under it").toEqual([false, false, false, false, false]);
      expect(hits.switchedOn, "the line is what is on top at each point").toEqual([true, true, true, true, true]);
    });
  }

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
});
