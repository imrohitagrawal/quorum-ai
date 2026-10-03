import { test, expect, type APIResponse, type BrowserContext, type Page, type Request } from "@playwright/test";

/**
 * THE SIGNED-IN BROWSER LANE (W33 slice D, ADR-0142) — the History panel asks
 * the server for its list each time it opens.
 *
 * Runs ONLY under `playwright.signed-in.config.ts`, whose test-only launcher
 * (`e2e/servers/signed_in_server.py`) starts the real app with Google sign-in
 * on and a loopback token stub set in-process. The one thing caught in every
 * test is Google's consent page: `page.route` answers it with a 302 to the
 * local callback carrying the real `state` from the URL the app built, and a
 * `code` that tells the stub which account to sign in (`<sub>|<email>`).
 * Everything else — sign-in, estimate, the simulated run ($0), History — is
 * the real backend. Six tests add ONE more mock each, on
 * `/v1/account/history` only, and say so in the test: rows 10 and 11, row
 * 12's two re-ask tests, row 6 (another account's email) and row 9 / decision
 * 2a (a 503). The two idle-reminder tests (review round 2) mock
 * `/v1/session/idle` and `/v1/session/keep-active` instead, and say so.
 *
 * Rows are those of docs/analysis/2026-10-03-w33d-history-refresh-failure-modes.md.
 *
 * Selectors this lane fixes for the build (ADR-0142 decision 5):
 *   - `#account-history-reload` — the one line asking the person to reload,
 *     shown on 401/403 (or an email that differs), with the rows removed;
 *   - `#account-history-error` — the line saying the history could not be
 *     refreshed, shown on a network error or a 503, with the rows kept.
 * Both inside `#account-history`.
 */

const HISTORY = "/v1/account/history";

let counter = 0;
/** A Google subject and email no other test in the run uses. */
function freshAccount(label: string): { sub: string; email: string } {
  counter += 1;
  const sub = `1093${Date.now()}${counter}`;
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
}

const summary = (page: Page) => page.locator("#account-history > summary");

async function openHistory(page: Page) {
  await expect(page.locator("#account-history")).not.toHaveAttribute("open", "");
  await summary(page).click();
  await expect(page.locator("#account-history")).toHaveAttribute("open", "");
}

async function closeHistory(page: Page) {
  await summary(page).click();
  await expect(page.locator("#account-history")).not.toHaveAttribute("open", "");
}

/** Ask a question through the real composer and wait for the real result. */
async function runQuestion(page: Page, question: string) {
  await page.locator("#query-text").fill(question);
  await page.locator("#run-now").click();
  const gateConfirm = page.locator("#gate-confirm");
  if (await gateConfirm.isVisible({ timeout: 8000 }).catch(() => false)) {
    await gateConfirm.click();
  }
  await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 60000 });
}

function historyResponse(page: Page) {
  return page.waitForResponse(
    (r) => new URL(r.url()).pathname === HISTORY && r.request().method() === "GET",
    { timeout: 8000 },
  );
}

/**
 * Load /ui until the server renders `question` in the History list. The row
 * is written when the run ends, which can trail the result the page shows.
 */
async function loadUntilListed(page: Page, question: string) {
  await expect(async () => {
    await openWorkspace(page);
    await expect(page.locator("#account-history-list .history-question").first()).toHaveText(question, {
      timeout: 1000,
    });
  }).toPass({ timeout: 20000 });
}

const questions = (page: Page) => page.locator("#account-history-list .history-question");

test.describe("signed-in History refresh (W33 slice D)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "the lane runs on the reference engine only");

  test("sign-in through the caught consent page reaches a signed-in workspace", async ({ page }) => {
    // RED-IF: the launcher, the in-process token stub or the consent-page
    // redirect stops working — every other test here then proves nothing.
    // Green on today's code: it is the lane's infrastructure partner.
    const account = freshAccount("infra");
    await signIn(page, account);
    await expect(page.locator("#sign-out")).toBeVisible();
    await expect(page.locator("#account-history")).toHaveCount(1);
    expect(new URL(page.url()).pathname).toBe("/ui");
  });

  test("bug 8a's journey: a question just asked is in History without a reload", async ({ page }) => {
    // Row 12 / bug 8a. RED-IF: opening History after a run, without a
    // reload, still shows "No questions yet." — the panel is not refreshed
    // from the server when it opens. Positive partner (green today): before
    // the run, opening History shows the empty line.
    test.setTimeout(120000);
    const account = freshAccount("journey");
    await signIn(page, account);

    await openHistory(page);
    await expect(page.locator("#account-history-empty")).toBeVisible();
    await expect(page.locator("#account-history-list")).toHaveCount(0);
    await closeHistory(page);

    // A marker that a reload would wipe.
    await page.evaluate(() => {
      (window as unknown as { __noReload: boolean }).__noReload = true;
    });
    const question = `What does the history keep? ${account.sub}`;
    await runQuestion(page, question);
    await page.locator("#result-new-question").click();
    await expect(page.locator('[data-view="composer"]')).toBeVisible();

    await openHistory(page);
    await expect(questions(page).first()).toHaveText(question);
    await expect(page.locator("#account-history-empty")).toHaveCount(0);
    expect(
      await page.evaluate(() => (window as unknown as { __noReload?: boolean }).__noReload),
      "the page must not have reloaded",
    ).toBe(true);
  });

  test("the delete steps still work after History is refreshed", async ({ page }) => {
    // Row 13. RED-IF: reopening History does not ask the server (no GET of
    // the history route), or the refresh replaces the whole panel, so the
    // account controls lose their listeners or are new elements. The
    // deletion is never completed.
    const account = freshAccount("delete-steps");
    await signIn(page, account);
    await openHistory(page);
    await page.locator("#account-delete-start").click();
    await expect(page.locator("#account-delete-reminder")).toBeVisible();
    // Mark the controls: only the list may be replaced, never these.
    await page.evaluate(() => {
      for (const id of ["account-delete", "sign-out-everywhere", "account-delete-start"]) {
        (document.getElementById(id) as unknown as { __kept: boolean }).__kept = true;
      }
    });
    await closeHistory(page);

    const refreshed = historyResponse(page);
    await openHistory(page);
    expect((await refreshed).status()).toBe(200);
    expect(
      await page.evaluate(() =>
        ["account-delete", "sign-out-everywhere", "account-delete-start"].map(
          (id) => (document.getElementById(id) as unknown as { __kept?: boolean } | null)?.__kept === true,
        ),
      ),
      "the account controls must be the same elements after a refresh",
    ).toEqual([true, true, true]);
    // Closing started the steps over; they still run.
    await expect(page.locator("#account-delete-start")).toBeVisible();
    await page.locator("#account-delete-start").click();
    await expect(page.locator("#account-delete-reminder")).toBeVisible();
    await page.locator("#account-delete-email").fill(account.email);
    await page.locator("#account-delete-continue").click();
    await expect(page.locator("#account-delete-final")).toBeVisible();
    await expect(page.locator("#account-delete-confirm")).toBeFocused();
    await page.locator("#account-delete-back").click();
    await expect(page.locator("#account-delete-start")).toBeVisible();
  });

  test("signed out in another tab: no rows, a reload line, and no new session asked for", async ({
    context,
  }) => {
    // Row 5. RED-IF: after signing out in one tab, opening History in the
    // other still shows the rows, shows no reload line, or the page reloads
    // itself or calls /v1/session (which mints an anonymous session).
    // The mint COUNT is not read here (the lane has no route to it); the
    // request check below is the browser-side form of "the count did not
    // change": no /v1/session call and no navigation from this tab.
    //
    // The tab that signs out is the one that booted LAST. Measured on
    // 10c4fd0: every GET /v1/session rotates the session's CSRF token, so a
    // tab that booted earlier gets 403 CSRF_INVALID on "Sign out" (a
    // pre-existing two-tab limit, not this slice's).
    test.setTimeout(120000);
    const account = freshAccount("two-tabs");
    const kept = await context.newPage();
    await signIn(kept, account);
    const question = `Signed out elsewhere ${account.sub}`;
    await runQuestion(kept, question);
    await kept.locator("#result-new-question").click();
    await expect(kept.locator('[data-view="composer"]')).toBeVisible();

    const leaving: Page = await context.newPage();
    await loadUntilListed(leaving, question);
    await expect(leaving.locator("#account-email")).toHaveText(account.email);
    await leaving.locator("#sign-out").click();
    await expect(leaving.locator("#sign-in-google")).toBeVisible();

    const asked: string[] = [];
    const onRequest = (r: Request) => {
      const path = new URL(r.url()).pathname;
      if (path === "/v1/session" || (r.isNavigationRequest() && path === "/ui")) asked.push(path);
    };
    kept.on("request", onRequest);
    const refused = historyResponse(kept);
    await openHistory(kept);
    expect([401, 403]).toContain((await refused).status());
    await expect(kept.locator("#account-history #account-history-reload")).toBeVisible();
    await expect(kept.locator("#account-history-reload")).toContainText(/reload/i);
    await expect(kept.locator("#account-history-list")).toHaveCount(0);
    await expect(kept.locator("#account-history").getByText(question)).toHaveCount(0);
    kept.off("request", onRequest);
    expect(asked, "the page must not reload itself or ask for a new session").toEqual([]);
  });

  test("a failed refresh keeps the rows and says it could not refresh", async ({ page }) => {
    // Row 10. RED-IF: a network error on the refresh wipes the rows, or no
    // line says the history could not be refreshed; or no refresh is tried.
    // The ONE extra mock: `/v1/account/history` is aborted once.
    test.setTimeout(120000);
    const account = freshAccount("net-error");
    await signIn(page, account);
    const question = `Kept through a network error ${account.sub}`;
    await runQuestion(page, question);
    // The server renders the row on a fresh load; that is the "earlier" list.
    await loadUntilListed(page, question);

    let aborted = 0;
    await page.route(
      (url) => url.pathname === HISTORY,
      async (route) => {
        if (aborted === 0) {
          aborted += 1;
          await route.abort("failed");
        } else {
          await route.continue();
        }
      },
    );
    const failed = page.waitForEvent("requestfailed", {
      predicate: (r) => new URL(r.url()).pathname === HISTORY,
      timeout: 8000,
    });
    await openHistory(page);
    await failed;
    expect(aborted).toBe(1);
    await expect(page.locator("#account-history #account-history-error")).toBeVisible();
    await expect(page.locator("#account-history-error")).toContainText(/could not be refreshed/i);
    await expect(questions(page).first()).toHaveText(question);
  });

  test("an older answer that arrives last does not replace a newer one", async ({ page }) => {
    // Row 11. RED-IF: answers are applied in arrival order, so the FIRST
    // open's answer (no questions), held back until after the second open's
    // answer (one question), replaces the newer list. The ONE extra mock:
    // the first `/v1/account/history` answer is fetched for real and held.
    test.setTimeout(120000);
    const account = freshAccount("stale");
    await signIn(page, account);

    let release: () => void = () => {};
    const released = new Promise<void>((resolve) => {
      release = resolve;
    });
    let seen = 0;
    let firstDone: Promise<void> = Promise.resolve();
    await page.route(
      (url) => url.pathname === HISTORY,
      async (route) => {
        seen += 1;
        if (seen === 1) {
          const real = await route.fetch(); // the list as it is NOW: empty
          firstDone = (async () => {
            await released;
            await route.fulfill({ response: real }).catch(() => {}); // the page may have dropped it
          })();
          return firstDone;
        }
        await route.continue();
      },
    );

    const firstAsked = page.waitForRequest((r) => new URL(r.url()).pathname === HISTORY, { timeout: 8000 });
    await openHistory(page);
    await firstAsked;
    await closeHistory(page);

    const question = `Newest answer wins ${account.sub}`;
    await runQuestion(page, question);
    await page.locator("#result-new-question").click();
    await openHistory(page);
    await expect(questions(page).first()).toHaveText(question);

    release();
    await firstDone;
    // Sampled, never auto-retried: an auto-waiting expect would let a later
    // re-ask (the 2-second backstop) repair the list and hide the defect.
    // Measured on a scratch reference build: with the stale check removed,
    // an auto-waiting form of this assertion still passed.
    for (let sample = 0; sample < 15; sample += 1) {
      expect(await questions(page).allTextContents(), "an older answer replaced the newer list").toEqual([
        question,
      ]);
      expect(await page.locator("#account-history-empty").count()).toBe(0);
      await page.waitForTimeout(100);
    }
    expect(seen).toBeGreaterThanOrEqual(2);
  });

  test("an answer missing this tab's latest question is asked for once more", async ({ page }) => {
    // Row 12's backstop (ADR-0142 decision 4). The window it covers (the
    // row written after the result shows: 511.6 ms with a 0.5 s judge
    // stand-in, a design-review probe) does not open locally, so the ONE extra mock stands in for it: the first open
    // after the run is answered with the list as it was BEFORE the run
    // (fetched for real earlier). RED-IF: the panel does not ask once more
    // when this tab's latest finished question is missing, asks at once
    // (under 1 s: a hot loop), or keeps asking (more than one re-ask).
    test.setTimeout(120000);
    const account = freshAccount("backstop");
    await signIn(page, account);

    let before: APIResponse | null = null;
    let stale = false;
    const asks: number[] = [];
    await page.route(
      (url) => url.pathname === HISTORY,
      async (route) => {
        if (before === null) {
          before = await route.fetch(); // the real list before any run: empty
          await route.fulfill({ response: before });
          return;
        }
        asks.push(Date.now());
        if (!stale) {
          stale = true;
          await route.fulfill({ response: before });
          return;
        }
        await route.continue();
      },
    );
    const firstAsked = page.waitForRequest((r) => new URL(r.url()).pathname === HISTORY, { timeout: 8000 });
    await openHistory(page);
    await firstAsked;
    await expect(page.locator("#account-history-empty")).toBeVisible();
    await closeHistory(page);

    const question = `Asked for once more ${account.sub}`;
    await runQuestion(page, question);
    await page.locator("#result-new-question").click();
    await openHistory(page);
    await expect(questions(page).first()).toHaveText(question, { timeout: 8000 });
    await page.waitForTimeout(3000); // room for a second re-ask, which must not come
    expect(asks.length, "one stale answer, then exactly one re-ask").toBe(2);
    const gap = asks[1] - asks[0];
    expect(gap, "the re-ask comes after about 2 seconds").toBeGreaterThanOrEqual(1000);
    expect(gap).toBeLessThan(5000);
  });

  test("the re-ask happens once, never on a loop", async ({ page }) => {
    // Row 12's backstop, its bound (row 8: nothing may keep asking on a
    // timer). The ONE extra mock: the first TWO asks after the run are
    // answered with the list as it was before the run. RED-IF: the panel
    // asks a third time without being reopened (a re-ask loop), or does
    // not ask again when it is reopened. Measured on a scratch reference
    // build: a re-ask that re-arms itself survives the previous test (its
    // second answer is complete) and is caught only here.
    test.setTimeout(120000);
    const account = freshAccount("bound");
    await signIn(page, account);

    let before: APIResponse | null = null;
    const asks: number[] = [];
    await page.route(
      (url) => url.pathname === HISTORY,
      async (route) => {
        if (before === null) {
          before = await route.fetch(); // the real list before any run: empty
          await route.fulfill({ response: before });
          return;
        }
        asks.push(Date.now());
        if (asks.length <= 2) {
          await route.fulfill({ response: before });
          return;
        }
        await route.continue();
      },
    );
    const firstAsked = page.waitForRequest((r) => new URL(r.url()).pathname === HISTORY, { timeout: 8000 });
    await openHistory(page);
    await firstAsked;
    await closeHistory(page);

    const question = `Asked for once, not forever ${account.sub}`;
    await runQuestion(page, question);
    await page.locator("#result-new-question").click();
    await openHistory(page);
    await expect.poll(() => asks.length, { timeout: 8000 }).toBe(2);
    await page.waitForTimeout(5000); // two more re-ask periods: none may come
    expect(asks.length, "the panel kept asking while open").toBe(2);
    await expect(page.locator("#account-history-empty")).toBeVisible(); // what the server said

    await closeHistory(page);
    await openHistory(page);
    await expect(questions(page).first()).toHaveText(question);
    expect(asks.length).toBe(3);
  });

  test("an answer for another account's email removes the rows and asks for a reload", async ({ page }) => {
    // Row 6 (review round 1: mutating the email check to `false` left the
    // lane green). RED-IF: an answer whose email is not the one on the page
    // is drawn anyway (its rows shown), or no reload line appears. The ONE
    // extra mock: the real answer is fetched and only its `email` is
    // replaced with another account's.
    test.setTimeout(120000);
    const account = freshAccount("email");
    const other = freshAccount("someone-else");
    await signIn(page, account);
    const question = `Not shown under another email ${account.sub}`;
    await runQuestion(page, question);
    await loadUntilListed(page, question);

    let answered = 0;
    await page.route(
      (url) => url.pathname === HISTORY,
      async (route) => {
        const real = await route.fetch();
        const body = await real.json();
        expect(body.html, "the real answer lists the question").toContain(question);
        answered += 1;
        await route.fulfill({ response: real, json: { ...body, email: other.email } });
      },
    );
    await openHistory(page);
    await expect(page.locator("#account-history #account-history-reload")).toBeVisible();
    await expect(page.locator("#account-history-reload")).toContainText(/reload/i);
    await expect(page.locator("#account-history-list")).toHaveCount(0);
    await expect(page.locator("#account-history").getByText(question)).toHaveCount(0);
    expect(answered).toBe(1);
  });

  test("a 503 from the route keeps the rows and says it could not refresh", async ({ page }) => {
    // Row 9 / ADR-0142 decision 2a: the sessions store cannot say who is
    // signed in. RED-IF: a 503 removes the rows, shows the reload line
    // ("your sign-in changed"), or shows no error line. The ONE extra mock:
    // the route answers 503 HISTORY_UNAVAILABLE in the server's own shape
    // (pinned by the integration test of the same row).
    test.setTimeout(120000);
    const account = freshAccount("store-down");
    await signIn(page, account);
    const question = `Kept through a 503 ${account.sub}`;
    await runQuestion(page, question);
    await loadUntilListed(page, question);

    let answered = 0;
    await page.route(
      (url) => url.pathname === HISTORY,
      async (route) => {
        answered += 1;
        await route.fulfill({
          status: 503,
          headers: { "Cache-Control": "no-store" },
          json: {
            detail: { code: "HISTORY_UNAVAILABLE", message: "Your history could not be read just now." },
          },
        });
      },
    );
    await openHistory(page);
    await expect(page.locator("#account-history #account-history-error")).toBeVisible();
    await expect(page.locator("#account-history-error")).toContainText(/could not be refreshed/i);
    await expect(questions(page).first()).toHaveText(question);
    await expect(page.locator("#account-history-reload")).toHaveCount(0);
    expect(answered).toBe(1);
  });

  test("right after a run, the toasts do not block History or Sign out at 1440 px", async ({ page }) => {
    // Review round 1 (product): the "Run started" / "Run completed" toasts
    // sat over the top bar's History and Sign out and took their clicks; a
    // click on History landed after 5.02 s. Real backend, no extra mock.
    // RED-IF: right after a run, a click on History does not land within
    // 1 s, or the point at the centre of Sign out is covered by something
    // else. Partner: the toast is still showing then, and its own dismiss
    // control still removes it.
    test.setTimeout(120000);
    await page.setViewportSize({ width: 1440, height: 900 });
    const account = freshAccount("toasts");
    await signIn(page, account);
    await runQuestion(page, `Toasts over the top bar ${account.sub}`);
    await page.locator("#result-new-question").click();
    await expect(page.locator('[data-view="composer"]')).toBeVisible();

    const toastNow = page.locator(".toast", { hasText: "Run completed" });
    await expect(toastNow).toBeVisible();
    const signOutHit = await page.locator("#sign-out").evaluate((button) => {
      const box = button.getBoundingClientRect();
      const top = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
      return top === button || button.contains(top);
    });
    // Soft, so a red run reports the History click below as well.
    expect.soft(signOutHit, "something covers the centre of Sign out").toBe(true);
    const started = Date.now();
    await summary(page).click({ timeout: 1000 });
    expect(Date.now() - started).toBeLessThan(1000);
    await expect(page.locator("#account-history")).toHaveAttribute("open", "");

    await expect(toastNow).toBeVisible();
    await toastNow.locator(".toast-close").click({ timeout: 1000 });
    await expect(toastNow).toHaveCount(0);
  });

  for (const width of [1440, 700]) {
    test(`at ${width} px the idle reminder does not hide the toast its own failure shows`, async ({ page }) => {
      // Review round 2: round 1 moved the toasts to the bottom right, where
      // the idle reminder (ADR-0138) also sits; the break-it reviewer
      // measured the "Could not keep you signed in" toast 96% covered at
      // 1440 and 700 px. RED-IF: with the reminder showing, the toast's
      // centre or any corner is covered by something else, or its close
      // control cannot be clicked. Partner: the reminder's own "Stay signed
      // in" and "Sign out now" stay clickable.
      //
      // How the reminder is reached, stated: the page's real timer and its
      // real showReminder. A fake clock (installed, then the page reloaded,
      // so the idle timer is scheduled on it) is jumped past the first idle
      // check, and that check's answer is the real `/v1/session/idle` body
      // with `idle_seconds_left` set to 240 (MOCK 1). "Stay signed in" then
      // gets a 500 from `/v1/session/keep-active` (MOCK 2), which is what
      // shows the toast.
      test.setTimeout(120000);
      await page.setViewportSize({ width, height: 900 });
      const account = freshAccount(`idle-${width}`);
      await signIn(page, account);

      await page.route(
        (url) => url.pathname === "/v1/session/idle",
        async (route) => {
          const real = await route.fetch();
          const body = await real.json();
          expect(body.signed_in, "the real idle answer is for a signed-in session").toBe(true);
          await route.fulfill({ response: real, json: { ...body, idle_seconds_left: 240 } });
        },
      );
      let keepActive = 0;
      await page.route(
        (url) => url.pathname === "/v1/session/keep-active",
        async (route) => {
          keepActive += 1;
          await route.fulfill({
            status: 500,
            json: { detail: { code: "INTERNAL_ERROR", message: "Internal error." } },
          });
        },
      );
      await page.clock.install();
      await page.reload({ waitUntil: "domcontentloaded" });
      await expect(page.locator("#account-email")).toHaveText(account.email);
      const reminder = page.locator("#idle-reminder");
      await expect(reminder).toBeHidden();
      await page.clock.fastForward("02:00:00");
      await expect(reminder).toBeVisible();
      await expect(page.locator("#idle-reminder-text")).toHaveText(
        "You will be signed out in about 4 minutes because nothing has happened on this page. Stay signed in?",
      );

      await page.locator("#idle-stay").click();
      const failed = page.locator(".toast", { hasText: "Could not keep you signed in. Please try again." });
      await expect(failed).toBeVisible();
      await failed.evaluate((el) => Promise.all(el.getAnimations().map((a) => a.finished)));
      expect(keepActive).toBe(1);

      const uncovered = await failed.evaluate((toastEl) => {
        const box = toastEl.getBoundingClientRect();
        // Past the rounded corner: hit-testing follows border-radius, so a
        // point closer than ~0.3 r to a corner is outside the toast itself.
        const radius = parseFloat(getComputedStyle(toastEl).borderTopLeftRadius) || 0;
        const inset = Math.ceil(radius * 0.3) + 2;
        const points: Array<[string, number, number]> = [
          ["centre", box.left + box.width / 2, box.top + box.height / 2],
          ["top-left", box.left + inset, box.top + inset],
          ["top-right", box.right - inset, box.top + inset],
          ["bottom-left", box.left + inset, box.bottom - inset],
          ["bottom-right", box.right - inset, box.bottom - inset],
        ];
        return points.map(([name, x, y]) => {
          const top = document.elementFromPoint(x, y);
          return `${name}: ${top && toastEl.contains(top) ? "toast" : top ? top.id || top.className : "nothing"}`;
        });
      });
      expect(uncovered, "every point of the toast must be the toast").toEqual([
        "centre: toast",
        "top-left: toast",
        "top-right: toast",
        "bottom-left: toast",
        "bottom-right: toast",
      ]);

      // Partner: the reminder is still up and its own buttons take clicks.
      await expect(reminder).toBeVisible();
      await page.locator("#idle-stay").click({ trial: true, timeout: 1000 });
      await page.locator("#idle-sign-out").click({ trial: true, timeout: 1000 });

      await failed.locator(".toast-close").click({ timeout: 1000 });
      await expect(failed).toHaveCount(0);
    });
  }

  test("the anonymous page has no History panel and never asks for one", async ({ browser }) => {
    // Row 18. RED-IF: the anonymous page gains a History panel, or the
    // refresh code runs there (any GET of the history route). Green on
    // today's code by design: today nothing asks. The partner proving the
    // request check can see a request is the delete-steps test above, which
    // waits for exactly this route on a signed-in page.
    const context: BrowserContext = await browser.newContext();
    const page = await context.newPage();
    const asked: string[] = [];
    page.on("request", (r) => {
      if (new URL(r.url()).pathname === HISTORY) asked.push(r.url());
    });
    await openWorkspace(page);
    await expect(page.locator("#sign-in-google")).toBeVisible(); // anonymous, sign-in offered
    await expect(page.locator("#account-history")).toHaveCount(0);
    await page.locator("#query-text").fill("an anonymous visitor types");
    await page.locator("#show-landing").click();
    await page.waitForTimeout(500);
    expect(asked).toEqual([]);
    await context.close();
  });
});
