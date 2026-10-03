import { test, expect, Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { freeze } from "../../fixtures/stabilize";
import {
  boot,
  goldenCreateResp,
  goldenCompletedResp,
  goldenRunningResp,
} from "../../fixtures/golden-run";

/**
 * W33 slice A + W43 — the page journey (ADR-0140).
 *
 * The owner asked that the final feature testing use the REAL system, not
 * mocks (OWNER-DISCUSSION-LOG M18 point 5 and M22). So the first describe below
 * drives the real FastAPI app that Playwright's webServer starts (live
 * execution off: measured 2026-10-03 over three simulated runs, the server
 * reported 15-19 ms elapsed at completion, and the page's poll saw "completed"
 * about 0.76 s after the create), with NO `page.route` — the same
 * guard `real-integration-smoke.spec.ts` uses fails the test if one is added.
 *
 * ANONYMOUS ONLY. No e2e lane can sign in today, so every journey here is an
 * anonymous visitor. The signed-in page shares the same browser code for every
 * behaviour tested here, but that is an inference, not a measurement.
 *
 * Budget: each browser context is a new anonymous session with a $0.40 daily
 * envelope and a simulated run charges about $0.105, so no real test here runs
 * more than two questions.
 *
 * The second describe uses `page.route` ONLY for states the real backend cannot
 * reach within one session's envelope, or at all; each says why.
 *
 * Exact copy comes from ADR-0140 (the hint, the empty-state line). Where the ADR
 * leaves the wording open, a test asserts the element and a key phrase only.
 */

const DESKTOP = { width: 1440, height: 900 };
const PHONE = { width: 390, height: 844 };

// ADR-0140 decision 8, verbatim (the bold marks are <strong>, not asterisks).
const HINT_FOUR =
  "Your four models are picked for you — change any if you like. Then press See the estimate to check the cost first, or Run now to start straight away (it still asks first if the cost needs your approval).";
// ADR-0140 decision 7, verbatim.
const EMPTY_LINE = "Questions you ask in this tab appear here.";

const Q1 = "What are the key metrics for measuring SaaS customer retention?";
const Q2 = "How should a small team choose between Postgres and MySQL?";

/** Fail the test if anything installs a page-level mock (best effort, as in the smoke). */
function forbidRoutes(page: Page): () => boolean {
  let mocked = false;
  const origRoute = page.route.bind(page);
  (page as unknown as { route: typeof page.route }).route = ((...args: Parameters<typeof origRoute>) => {
    mocked = true;
    return origRoute(...args);
  }) as typeof page.route;
  return () => mocked;
}

const verdictVisible = (page: Page) => page.locator('[data-view="result"] #result-verdict[data-consensus]');

/** Wait for a real run started from the composer to reach the result view. */
async function settleRealRun(page: Page) {
  // Against the simulated backend Run now auto-proceeds on an allow-band
  // estimate; if the estimate lands in the confirm band, approve it.
  await expect(
    page.locator('#result-verdict[data-consensus]:visible, #gate-confirm:visible').first(),
  ).toBeVisible({ timeout: 30000 });
  const confirm = page.locator("#gate-confirm");
  if (await confirm.isVisible()) await confirm.click();
  await expect(verdictVisible(page)).toBeVisible({ timeout: 30000 });
}

async function askReal(page: Page, question: string) {
  await page.locator("#query-text").fill(question);
  await page.locator("#run-now").click();
  await settleRealRun(page);
  await expect(page.locator("#result-question")).toHaveText(question);
}

const activeView = (page: Page) =>
  page.evaluate(() => document.getElementById("main-content")?.dataset.activeView ?? null);
const historyLength = (page: Page) => page.evaluate(() => window.history.length);

/** Mark the window so a later check can tell a full page load from an in-page move. */
async function markWindow(page: Page) {
  await page.evaluate(() => {
    (window as unknown as { __w33aNoReload: number }).__w33aNoReload = 1;
  });
}
const windowMark = (page: Page) =>
  page.evaluate(() => (window as unknown as { __w33aNoReload?: number }).__w33aNoReload ?? null);

const resultView = (page: Page) => page.locator('[data-view="result"]');
const newQuestionButton = (page: Page) =>
  resultView(page).getByRole("button", { name: "New question", exact: true });
const resultBrandLink = (page: Page) => resultView(page).getByRole("link", { name: /Quorum/ });
const transcriptBrandLink = (page: Page) =>
  page.locator('[data-view="transcript"]').getByRole("link", { name: /Quorum/ });
const topbarLogoLink = (page: Page) => page.locator("header.topbar").getByRole("link", { name: /Quorum/ });
const trailPanel = (page: Page) => page.locator(".session-trail-panel");
const trailEntries = (page: Page) => page.locator(".session-trail-entry");
const emptyLine = (page: Page) => trailPanel(page).getByText(EMPTY_LINE, { exact: true });
const trailHeading = (page: Page) => trailPanel(page).getByRole("heading", { name: "This session" });
const composerView = (page: Page) => page.locator('[data-view="composer"]');
// The hint is located by the phrase every variant of it keeps ("... picked for
// you"); its exact four-model wording is asserted separately below.
const handoffHint = (page: Page) => composerView(page).getByText(/picked for you/i);

/** First visit: the landing view, then a landing question handed off to the composer. */
async function landingHandoff(page: Page, question: string) {
  await page.goto("/ui", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-view="landing"]')).toBeVisible();
  await page.locator("#landing-query").fill(question);
  await page.locator("#landing-estimate").click();
  await expect(composerView(page)).toBeVisible({ timeout: 8000 });
}

/** Rect facts about the hint, the question box and the model slots, in one read. */
async function hintGeometry(page: Page) {
  return page.evaluate(() => {
    const hint = Array.from(document.querySelectorAll('[data-view="composer"] *')).find(
      (e) => /picked for you/i.test(e.textContent || "") &&
        !Array.from(e.children).some((c) => /picked for you/i.test(c.textContent || "")),
    ) as HTMLElement | undefined;
    if (!hint) return null;
    const r = hint.getBoundingClientRect();
    const q = document.getElementById("query-text")!.getBoundingClientRect();
    const m = document.getElementById("model-inputs")!.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    const active = document.activeElement as HTMLElement | null;
    return {
      top: r.top,
      bottom: r.bottom,
      viewportHeight: window.innerHeight,
      questionBottom: q.bottom,
      modelsTop: m.top,
      hitInsideHint: !!hit && hint.contains(hit),
      hitTag: hit ? `${hit.tagName}.${(hit as HTMLElement).className}` : "null",
      activeText: (active?.textContent || "").replace(/\s+/g, " ").trim(),
      activeTag: active?.tagName ?? "null",
    };
  });
}

/**
 * Hold every estimate RESPONSE until the test releases it. The request still
 * goes to the REAL server (it prices the question and returns a real
 * confirmation token); only its arrival in the page is delayed. This is a
 * fetch wrapper installed by an init script, NOT `page.route`, so the
 * no-mocks guard stays meaningful. `app.js` calls `fetch` for every API call.
 */
async function holdEstimates(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as {
      __estimateAnswered: number;
      __releaseEstimates: () => void;
    };
    const orig = window.fetch.bind(window);
    // Re-armable: a release frees only the estimates already SENT, and the
    // next one is held again.
    let release: () => void = () => {};
    let gate = Promise.resolve();
    const arm = () => {
      gate = new Promise<void>((r) => (release = r));
    };
    arm();
    w.__estimateAnswered = 0;
    w.__releaseEstimates = () => {
      const free = release;
      arm();
      free();
    };
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const pending = orig(input, init);
      if (!/\/v1\/query-runs\/estimate(\?|$)/.test(url)) return pending;
      const myGate = gate;
      return pending.then((res) =>
        myGate.then(() => {
          w.__estimateAnswered += 1;
          return res;
        }),
      );
    };
  });
}

const estimatesAnswered = (page: Page) =>
  page.evaluate(() => (window as unknown as { __estimateAnswered: number }).__estimateAnswered);

/** Release the held estimates and wait until one more has reached the page. */
async function releaseEstimates(page: Page) {
  const before = await estimatesAnswered(page);
  await page.evaluate(() => (window as unknown as { __releaseEstimates: () => void }).__releaseEstimates());
  await expect.poll(() => estimatesAnswered(page)).toBeGreaterThanOrEqual(before + 1);
  // Give a late answer the time it would need to open a gate or create a run
  // (a real create answers in tens of milliseconds here).
  await page.waitForTimeout(1500);
}

/** Every POST that creates a run (path exactly /v1/query-runs), with its body. */
function recordRunCreates(page: Page): { query_text?: string }[] {
  const creates: { query_text?: string }[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && new URL(r.url()).pathname === "/v1/query-runs") {
      creates.push((r.postDataJSON() ?? {}) as { query_text?: string });
    }
  });
  return creates;
}

/** Wait until the page has SENT the (held) estimate request. */
async function estimateSent(page: Page) {
  await page.waitForRequest((r) => new URL(r.url()).pathname === "/v1/query-runs/estimate", { timeout: 10000 });
}

// Contract chosen by the test designer (the ADR names no element): an element
// #composer-steps, shown with the composer, holding three list items in order
// and exactly one item with aria-current="step".
const stepMarker = (page: Page) => page.locator("#composer-steps");
const stepLabels = async (page: Page) =>
  (await stepMarker(page).getByRole("listitem").allTextContents()).map((t) =>
    t.replace(/[→›>]/g, " ").replace(/\s+/g, " ").trim(),
  );

test.describe("W33 slice A — the page journey on the real backend (no page.route)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  // ---------------------------------------------------------------------------
  // The owner's journey, end to end (M07 points 1, 2, 6, 9).
  // ---------------------------------------------------------------------------
  test("the owner's journey: ask, New question keeps the list, ask again, Back, then Clear", async ({ page }) => {
    // RED-IF: any step of ADR-0140 decisions 1, 2, 4, 6 or 7 regresses — the first broken step names itself.
    const mocked = forbidRoutes(page);
    await page.setViewportSize(DESKTOP);
    await boot(page);

    await askReal(page, Q1);
    await expect(trailEntries(page)).toHaveCount(1);
    // Positive partner for the empty-box check below: the box is there.
    await expect(page.locator("#result-next-input")).toBeVisible();
    await expect(page.locator("#result-next-input")).toHaveValue("");

    // Decision 4: a way to a new question from the result.
    await expect(newQuestionButton(page)).toBeVisible();
    await newQuestionButton(page).click();
    await expect(composerView(page)).toBeVisible();
    await expect(page.locator("#query-text")).toHaveValue("");
    await expect(trailEntries(page), "a new question must keep the session list").toHaveCount(1);

    await askReal(page, Q2);
    await expect(trailEntries(page)).toHaveCount(2);
    const questions = await page.locator(".session-trail-question").allTextContents();
    expect(questions.some((q) => q.includes(Q1.slice(0, 40)))).toBe(true);
    expect(questions.some((q) => q.includes(Q2.slice(0, 40)))).toBe(true);

    // Decision 6: browser Back from the result stays in the page.
    await page.goBack();
    await expect(composerView(page)).toBeVisible();
    expect(new URL(page.url()).pathname).toBe("/ui");
    await expect(trailEntries(page)).toHaveCount(2);

    // Decision 7: Clear empties the list and the panel explains itself.
    await page.locator("#session-trail-clear").click();
    await expect(trailEntries(page)).toHaveCount(0);
    await expect(emptyLine(page)).toBeVisible();
    await expect(page.locator("#session-trail-clear")).toBeHidden();
    await expect(trailHeading(page)).toBeFocused();

    expect(mocked(), "this journey must NOT use page.route — it exercises the real backend").toBe(false);
  });

  // ---------------------------------------------------------------------------
  // Decision 2 — every finished run empties the next-question box; no pre-fill.
  // ---------------------------------------------------------------------------
  test("a finished follow-up run empties the next-question box (bug 2)", async ({ page }) => {
    // RED-IF: the run-end path stops clearing #result-next-input (failure-mode row 4).
    const mocked = forbidRoutes(page);
    await boot(page);
    await askReal(page, Q1);

    const next = page.locator("#result-next-input");
    await next.fill(Q2);
    await page.locator("#result-next-run").click();
    await expect(composerView(page)).toBeVisible();
    // Positive partner: a TYPED next question does carry into the composer.
    await expect(page.locator("#query-text")).toHaveValue(Q2);
    await page.locator("#run-now").click();
    await settleRealRun(page);
    await expect(page.locator("#result-question")).toHaveText(Q2);

    await expect(next).toBeVisible();
    await expect(next, "the box must open empty after a finished run, not hold the last follow-up").toHaveValue("");
    expect(mocked()).toBe(false);
  });

  test("Review & run with an empty box opens an EMPTY composer — nothing pre-fills (bug 2)", async ({ page }) => {
    // RED-IF: the empty-box branch of the #result-next-run handler copies state.liveQueryText again (row 5).
    const mocked = forbidRoutes(page);
    await boot(page);
    await askReal(page, Q1);
    await expect(page.locator("#result-next-input")).toHaveValue("");
    await page.locator("#result-next-run").click();
    await expect(composerView(page)).toBeVisible();
    await expect(page.locator("#query-text")).toBeVisible();
    await expect(page.locator("#query-text"), "no pre-fill of the previous question").toHaveValue("");
    expect(mocked()).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // Decision 3 — the follow-up mode buttons are hidden until W37.
  // ---------------------------------------------------------------------------
  test("Follow up / Start fresh are hidden until W37 and the note says each question is answered on its own", async ({ page }) => {
    // RED-IF: #result-followup or #result-startfresh is visible again, or the note keeps promising a pre-fill (row 6).
    const mocked = forbidRoutes(page);
    await boot(page);
    await askReal(page, Q1);
    // Positive partners: the block itself is on screen.
    await expect(page.locator("#result-next-input")).toBeVisible();
    await expect(page.locator("#result-next-run")).toBeVisible();
    await expect(page.locator("#result-followup")).toBeHidden();
    await expect(page.locator("#result-startfresh")).toBeHidden();
    const note = page.locator(".result-next-note");
    await expect(note).toBeVisible();
    // Wording left open by the ADR: key phrase only.
    await expect(note).toContainText(/on its own/i);
    await expect(note).not.toContainText(/pre-filled/i);
    // No "Following up on: …" line may claim context the page does not send.
    await expect(page.getByText(/Following up on/i).filter({ visible: true })).toHaveCount(0);
    expect(mocked()).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // Decision 4 — a way to a new question from the result and transcript views.
  // ---------------------------------------------------------------------------
  for (const control of ["the New question button", "the Quorum brand link"] as const) {
    test(`result view: ${control} goes to an empty composer without reloading, list kept (bug 6)`, async ({ page }) => {
      // RED-IF: the result header has no New question button / the brand is not a link, or the move reloads the page.
      const mocked = forbidRoutes(page);
      await boot(page);
      await askReal(page, Q1);
      await expect(trailEntries(page)).toHaveCount(1);
      await markWindow(page);

      const target = control === "the New question button" ? newQuestionButton(page) : resultBrandLink(page);
      await expect(target).toBeVisible();
      if (control === "the Quorum brand link") {
        await expect(target).toHaveAttribute("href", /\/ui$/);
      }
      await target.click();

      await expect(composerView(page)).toBeVisible();
      await expect(resultView(page)).toBeHidden();
      await expect(page.locator("#query-text")).toHaveValue("");
      await expect(trailEntries(page), "the session list survives going home").toHaveCount(1);
      expect(await windowMark(page), "going home must not reload the page").toBe(1);
      expect(new URL(page.url()).pathname).toBe("/ui");
      expect(mocked()).toBe(false);
    });
  }

  test("transcript view: the Quorum brand link goes to an empty composer, list kept (bug 6)", async ({ page }) => {
    // RED-IF: the transcript header has no brand link to /ui, or following it reloads or empties the list.
    const mocked = forbidRoutes(page);
    await boot(page);
    await askReal(page, Q1);
    await page.locator("#result-transcript-link").click();
    await expect(page.locator('[data-view="transcript"]')).toBeVisible();
    await markWindow(page);

    const link = transcriptBrandLink(page);
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", /\/ui$/);
    await link.click();
    await expect(composerView(page)).toBeVisible();
    await expect(page.locator("#query-text")).toHaveValue("");
    await expect(trailEntries(page)).toHaveCount(1);
    expect(await windowMark(page)).toBe(1);
    expect(mocked()).toBe(false);
  });

  test("the top-bar logo is a link to /ui; from the cost gate it closes the estimate and KEEPS the question (rows 10, 28)", async ({ page }) => {
    // RED-IF: the top-bar brand is not a link, going home leaves the cost gate open, or the logo deletes a question that has not run (decision 4).
    // This test asserted an EMPTY composer in round 0; ADR-0140 decision 4 now keeps an un-run question.
    const mocked = forbidRoutes(page);
    await boot(page);
    await page.locator("#query-text").fill(Q1);
    await page.locator("#estimate-run").click();
    // Positive partner: the real estimate opened the cost gate.
    await expect(page.locator('[data-view="cost-gate"]')).toBeVisible({ timeout: 15000 });
    await markWindow(page);

    const logo = topbarLogoLink(page);
    await expect(logo).toBeVisible();
    await expect(logo).toHaveAttribute("href", /\/ui$/);
    await logo.click();
    await expect(composerView(page)).toBeVisible();
    await expect(page.locator('[data-view="cost-gate"]')).toBeHidden();
    await expect(page.locator("#cost-confirmation")).toBeHidden();
    await expect(page.locator("#query-text"), "the logo keeps a question that has not run").toHaveValue(Q1);
    expect(await windowMark(page)).toBe(1);
    expect(mocked()).toBe(false);
  });

  test("on the composer the top-bar logo keeps a typed question (row 28)", async ({ page }) => {
    // RED-IF: the logo's click handler empties #query-text on the composer (a 1,079-character question to 0 in one click).
    const mocked = forbidRoutes(page);
    await boot(page);
    const long = `${Q1} ${"Please weigh cost, latency and team skills. ".repeat(24)}`.trim();
    await page.locator("#query-text").fill(long);
    await expect(page.locator("#query-text")).toHaveValue(long);
    await markWindow(page);
    await topbarLogoLink(page).click();
    await expect(composerView(page)).toBeVisible();
    await expect(page.locator("#query-text"), "a typed, un-run question survives the logo").toHaveValue(long);
    expect(await windowMark(page)).toBe(1);
    expect(mocked()).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // Decision 5 — going home drops anything still in flight (row 26).
  // The estimate is delayed by holdEstimates (an init-script fetch wrapper that
  // holds the REAL server's answer), not by page.route.
  // ---------------------------------------------------------------------------
  test("See the estimate, then the top-bar logo before it answers: the late answer opens nothing, runs nothing, shows no error", async ({ page }) => {
    // RED-IF: the estimate's .then still opens the cost confirmation / gate after the user has gone home.
    const mocked = forbidRoutes(page);
    await holdEstimates(page);
    const creates = recordRunCreates(page);
    await boot(page);
    await page.locator("#query-text").fill(Q1);
    const sent = estimateSent(page);
    await page.locator("#estimate-run").click();
    await sent;
    await topbarLogoLink(page).click();
    await expect(composerView(page)).toBeVisible();

    await releaseEstimates(page);
    await expect(page.locator('[data-view="cost-gate"]'), "a late estimate must not open the gate").toBeHidden();
    await expect(page.locator("#cost-confirmation")).toBeHidden();
    await expect(page.locator("#error-region")).toBeHidden();
    expect(creates.length, "no run may be created").toBe(0);
    await expect(composerView(page)).toBeVisible();
    expect(mocked()).toBe(false);
  });

  test("See the estimate, then a result's brand link before it answers: the late answer opens nothing, runs nothing, shows no error", async ({ page }) => {
    // RED-IF: going home from a result does not cancel the estimate the composer started.
    const mocked = forbidRoutes(page);
    await holdEstimates(page);
    const creates = recordRunCreates(page);
    await boot(page);
    // Run 1 passes its held estimate straight through.
    await page.locator("#query-text").fill(Q1);
    let sent = estimateSent(page);
    await page.locator("#run-now").click();
    await sent;
    await page.evaluate(() => (window as unknown as { __releaseEstimates: () => void }).__releaseEstimates());
    await settleRealRun(page);
    expect(creates.length, "precondition: run 1 was created").toBe(1);
    await newQuestionButton(page).click();
    await expect(composerView(page)).toBeVisible();

    await page.locator("#query-text").fill(Q2);
    sent = estimateSent(page);
    await page.locator("#estimate-run").click();
    await sent;
    // While that estimate is held: open the earlier result, then go home by its brand link.
    await page.locator(".session-trail-entry").first().click();
    await expect(verdictVisible(page)).toBeVisible();
    await resultBrandLink(page).click();
    await expect(composerView(page)).toBeVisible();

    await releaseEstimates(page);
    await expect(page.locator('[data-view="cost-gate"]'), "a late estimate must not open the gate").toBeHidden();
    await expect(page.locator("#error-region")).toBeHidden();
    expect(creates.length, "only run 1 was ever created").toBe(1);
    expect(mocked()).toBe(false);
  });

  test("Run now, go home and type a new question before the estimate answers: no run is created", async ({ page }) => {
    // RED-IF: the Run-now estimate's continuation calls proceedWithRun after the user has gone home.
    const mocked = forbidRoutes(page);
    await holdEstimates(page);
    const creates = recordRunCreates(page);
    await boot(page);
    await page.locator("#query-text").fill(Q1);
    const sent = estimateSent(page);
    await page.locator("#run-now").click();
    await sent;
    await topbarLogoLink(page).click();
    await expect(composerView(page)).toBeVisible();
    await page.locator("#query-text").fill(Q2);

    await releaseEstimates(page);
    expect(creates.length, "a late estimate must not start a run").toBe(0);
    await expect(page.locator('[data-view="live-run"]')).toBeHidden();
    await expect(page.locator("#error-region")).toBeHidden();
    await expect(composerView(page)).toBeVisible();
    await expect(page.locator("#query-text"), "the new question is still in the box").toHaveValue(Q2);
    expect(mocked()).toBe(false);
  });

  test("positive partner: without going home, a delayed See the estimate still opens the gate", async ({ page }) => {
    // RED-IF: the in-flight guard drops EVERY late estimate, not only one the user has left.
    const mocked = forbidRoutes(page);
    await holdEstimates(page);
    const creates = recordRunCreates(page);
    await boot(page);
    await page.locator("#query-text").fill(Q1);
    const sent = estimateSent(page);
    await page.locator("#estimate-run").click();
    await sent;
    await releaseEstimates(page);
    await expect(page.locator('[data-view="cost-gate"]')).toBeVisible();
    await expect(page.locator("#gate-confirm")).toBeVisible();
    expect(creates.length, "See the estimate creates nothing until approved").toBe(0);
    expect(mocked()).toBe(false);
  });

  test("positive partner: without going home, a delayed Run now still starts exactly one run", async ({ page }) => {
    // RED-IF: the in-flight guard drops a Run-now estimate the user never left.
    const mocked = forbidRoutes(page);
    await holdEstimates(page);
    const creates = recordRunCreates(page);
    await boot(page);
    await page.locator("#query-text").fill(Q1);
    const sent = estimateSent(page);
    await page.locator("#run-now").click();
    await sent;
    await releaseEstimates(page);
    await settleRealRun(page);
    expect(creates.length, "exactly one run").toBe(1);
    expect(creates[0].query_text).toBe(Q1);
    expect(mocked()).toBe(false);
  });

  test("Run now, then edit the box before the estimate answers: the run submits the question that was priced", async ({ page }) => {
    // RED-IF: proceedWithRun reads #query-text at create time instead of the text the estimate priced.
    const mocked = forbidRoutes(page);
    await holdEstimates(page);
    const creates = recordRunCreates(page);
    await boot(page);
    await page.locator("#query-text").fill(Q1);
    const sent = estimateSent(page);
    await page.locator("#run-now").click();
    await sent;
    await page.locator("#query-text").fill(Q2);
    await releaseEstimates(page);
    await expect.poll(() => creates.length, { timeout: 15000 }).toBe(1);
    expect(creates[0].query_text, "the run must submit the priced question, not the edit").toBe(Q1);
    expect(mocked()).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // Decision 6 / row 27 — going home from a result or transcript is a history
  // entry of its own, so Back returns to where the user was.
  // ---------------------------------------------------------------------------
  test("result → New question → Back returns to the same result, list intact (row 27)", async ({ page }) => {
    // RED-IF: New question steps history back (history.go(-1)) instead of pushing an entry, so the next Back leaves the site.
    const mocked = forbidRoutes(page);
    await boot(page);
    await askReal(page, Q1);
    await newQuestionButton(page).click();
    await expect(composerView(page)).toBeVisible();

    await page.goBack();
    await expect(verdictVisible(page), "Back returns to the result the user came from").toBeVisible();
    await expect(page.locator("#result-question")).toHaveText(Q1);
    await expect(trailEntries(page)).toHaveCount(1);
    expect(new URL(page.url()).pathname).toBe("/ui");
    expect(mocked()).toBe(false);
  });

  test("transcript → brand link → Back returns to the transcript, list intact (row 27)", async ({ page }) => {
    // RED-IF: going home from the transcript does not push its own entry, so Back skips the transcript or leaves the site.
    const mocked = forbidRoutes(page);
    await boot(page);
    await askReal(page, Q1);
    await page.locator("#result-transcript-link").click();
    await expect(page.locator('[data-view="transcript"]')).toBeVisible();
    await transcriptBrandLink(page).click();
    await expect(composerView(page)).toBeVisible();

    await page.goBack();
    await expect(page.locator('[data-view="transcript"]'), "Back returns to the transcript the user left").toBeVisible();
    await expect(trailEntries(page)).toHaveCount(1);
    expect(new URL(page.url()).pathname).toBe("/ui");
    expect(mocked()).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // Decision 8 / row 30 — the hint recounts; the step marker.
  // ---------------------------------------------------------------------------
  test("after the hand-off, turning quick mode on recounts the hint to one model (row 30)", async ({ page }) => {
    // RED-IF: renderHandoffHint is not re-run when quick mode changes.
    const mocked = forbidRoutes(page);
    await landingHandoff(page, "Compare two database options for a small team");
    const hint = handoffHint(page);
    // Positive partner: before the change it said four.
    await expect(hint).toHaveText(HINT_FOUR);
    await page.locator("#quick-mode-input").check();
    await expect(hint).toContainText(/\bone\b|\byour model\b/i);
    await expect(hint).not.toContainText(/\bfour\b/i);
    expect(mocked()).toBe(false);
  });

  test("after the hand-off, removing a slot recounts the hint to three (row 30)", async ({ page }) => {
    // RED-IF: renderHandoffHint is not re-run when the panel size changes.
    const mocked = forbidRoutes(page);
    await landingHandoff(page, "Compare two database options for a small team");
    const hint = handoffHint(page);
    await expect(hint).toHaveText(HINT_FOUR);
    await page.locator("[data-slot-remove]").first().click();
    await expect(page.locator("select[data-model-slot]")).toHaveCount(3);
    await expect(hint).toContainText(/Your three models are picked for you/);
    expect(mocked()).toBe(false);
  });

  test("the composer's step marker reads Question → Models → Estimate and run, with Question current on a plain load (row 32)", async ({ page }) => {
    // RED-IF: #composer-steps is missing, its three labels change or reorder, or not exactly one step carries aria-current="step".
    const mocked = forbidRoutes(page);
    await boot(page);
    await expect(stepMarker(page)).toBeVisible();
    expect(await stepLabels(page)).toEqual(["Question", "Models", "Estimate and run"]);
    const current = stepMarker(page).locator('[aria-current="step"]');
    await expect(current).toHaveCount(1);
    await expect(current).toHaveText(/Question/);
    expect(mocked()).toBe(false);
  });

  test("after the landing hand-off the step marker's current step is Models (row 32)", async ({ page }) => {
    // RED-IF: the hand-off does not move aria-current="step" to Models.
    const mocked = forbidRoutes(page);
    await landingHandoff(page, "Compare two database options for a small team");
    await expect(stepMarker(page)).toBeVisible();
    const current = stepMarker(page).locator('[aria-current="step"]');
    await expect(current).toHaveCount(1);
    await expect(current).toHaveText(/Models/);
    expect(mocked()).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // Decision 7 / row 31 — the list's small text meets WCAG AA in both themes.
  // ---------------------------------------------------------------------------
  test("the session list with entries passes axe color-contrast (WCAG 2 AA) in both themes on the result view (row 31)", async ({ page }) => {
    // RED-IF: .session-trail-status / .session-trail-time go back to tokens under 4.5:1 (measured 3.2:1 light, 3.41:1 dark).
    const mocked = forbidRoutes(page);
    await page.setViewportSize(DESKTOP);
    await boot(page);
    await askReal(page, Q1);
    // Positive partners: the small text axe must judge is on screen.
    await expect(trailEntries(page)).toHaveCount(1);
    await expect(page.locator(".session-trail-time").first()).toBeVisible();
    await expect(page.locator(".session-trail-status").first()).toBeVisible();
    const violations: Record<string, string[]> = {};
    const incomplete: Record<string, number> = {};
    for (const theme of ["light", "dark"] as const) {
      await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await page.waitForTimeout(150);
      await freeze(page);
      const results = await new AxeBuilder({ page })
        .include(".session-trail-panel")
        .withRules(["color-contrast"])
        .analyze();
      const judged = [...results.passes, ...results.violations].reduce((n, r) => n + r.nodes.length, 0);
      expect(judged, `[${theme}] axe must have judged some text in the panel`).toBeGreaterThan(0);
      violations[theme] = results.violations
        .map((v) => v.nodes.map((n) => `${n.target.join(" ")}: ${n.any.map((c) => c.message).join(" ")}`))
        .flat();
      incomplete[theme] = results.incomplete.filter((r) => r.id === "color-contrast").length;
    }
    // Both themes are reported together, so one red run shows every failing pair.
    expect(violations, "color-contrast violations in the session list, by theme").toEqual({ light: [], dark: [] });
    expect(incomplete, '"axe could not tell" is not a pass').toEqual({ light: 0, dark: 0 });
    expect(mocked()).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // Decision 6 — browser Back and Forward stay inside the page.
  // ---------------------------------------------------------------------------
  test("entering the result adds exactly one history entry (the cost gate and live run add none); Back → composer, Forward → result", async ({ page }) => {
    // RED-IF: setView("result") stops pushing a history entry, or the cost gate / live run push one too (row 11).
    const mocked = forbidRoutes(page);
    await boot(page);
    const h0 = await historyLength(page);

    await page.locator("#query-text").fill(Q1);
    await page.locator("#estimate-run").click();
    await expect(page.locator('[data-view="cost-gate"]')).toBeVisible({ timeout: 15000 });
    expect(await historyLength(page), "the cost confirmation is never a history entry").toBe(h0);
    await page.locator("#gate-confirm").click();
    await expect(verdictVisible(page)).toBeVisible({ timeout: 30000 });
    expect(await historyLength(page), "the result adds ONE entry; the live run adds none").toBe(h0 + 1);

    await page.goBack();
    await expect(composerView(page)).toBeVisible();
    expect(new URL(page.url()).pathname).toBe("/ui");
    await expect(trailEntries(page)).toHaveCount(1);
    // Back never reopens a spent estimate.
    await expect(page.locator('[data-view="cost-gate"]')).toBeHidden();

    // The result is still in memory, so Forward shows it again.
    await page.goForward();
    await expect(verdictVisible(page)).toBeVisible();
    await expect(page.locator("#result-question")).toHaveText(Q1);
    expect(mocked()).toBe(false);
  });

  test("the transcript adds one more history entry: Back goes transcript → result → composer", async ({ page }) => {
    // RED-IF: entering the transcript view stops pushing its own history entry.
    const mocked = forbidRoutes(page);
    await boot(page);
    const h0 = await historyLength(page);
    await askReal(page, Q1);
    await page.locator("#result-transcript-link").click();
    await expect(page.locator('[data-view="transcript"]')).toBeVisible();
    expect(await historyLength(page)).toBe(h0 + 2);

    await page.goBack();
    await expect(verdictVisible(page)).toBeVisible();
    await page.goBack();
    await expect(composerView(page)).toBeVisible();
    await expect(trailEntries(page)).toHaveCount(1);
    expect(mocked()).toBe(false);
  });

  test("a Forward to a result no longer in memory (after a reload) shows the composer (row 11)", async ({ page }) => {
    // RED-IF: no history entry is pushed for the result, or a popped result entry with no result in memory renders an empty result view.
    const mocked = forbidRoutes(page);
    await boot(page);
    const h0 = await historyLength(page);
    await askReal(page, Q1);
    expect(await historyLength(page), "precondition: the result is a history entry").toBe(h0 + 1);
    await page.goBack();
    await expect(composerView(page)).toBeVisible();

    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(composerView(page)).toBeVisible();
    await page.goForward();
    await expect(composerView(page)).toBeVisible();
    await expect(page.locator("#query-text")).toBeVisible();
    await expect(resultView(page)).toBeHidden();
    await expect(page.locator("#error-region")).toBeHidden();
    expect(mocked()).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // Decision 7 — the empty list explains itself.
  // ---------------------------------------------------------------------------
  for (const [label, viewport] of [["1440", DESKTOP], ["390", PHONE]] as const) {
    test(`an empty session list explains itself, hides Clear, and is named by its title (${label} px, bug 9)`, async ({ page }) => {
      // RED-IF: renderSessionTrail's empty branch stops writing the line, Clear shows over nothing, or the region keeps the name "Conversation trail" (row 13, 16).
      const mocked = forbidRoutes(page);
      await page.setViewportSize(viewport);
      await boot(page);
      await expect(trailPanel(page)).toBeVisible();
      await expect(emptyLine(page)).toBeVisible();
      await expect(page.locator("#session-trail-clear")).toBeHidden();
      await expect(page.getByRole("region", { name: "This session", exact: true })).toBeVisible();
      expect(mocked()).toBe(false);
    });
  }

  test("Clear empties the list, hides itself, moves focus to the heading and says so (row 15)", async ({ page }) => {
    // RED-IF: Clear stays visible after clearing, focus drops to <body>, or nothing announces the clear.
    const mocked = forbidRoutes(page);
    await boot(page);
    await askReal(page, Q1);
    const clear = page.locator("#session-trail-clear");
    await expect(clear).toBeVisible();
    await expect(trailEntries(page)).toHaveCount(1);
    await expect(emptyLine(page)).toBeHidden();

    await clear.click();
    await expect(trailEntries(page)).toHaveCount(0);
    await expect(clear, "Clear must hide once there is nothing to clear").toBeHidden();
    await expect(trailHeading(page)).toBeFocused();
    // Wording left open by the design: a polite message with the key word.
    await expect(
      page.locator('[role="status"], [aria-live="polite"]').filter({ hasText: /cleared/i }).first(),
    ).toBeAttached();
    await expect(emptyLine(page)).toBeVisible();
    expect(mocked()).toBe(false);
  });

  test("at phone width an empty panel is not pinned over the page; a panel with entries still is", async ({ page }) => {
    // RED-IF: the 600 px media query pins .session-trail-panel with position: fixed whatever the list holds (row 13).
    const mocked = forbidRoutes(page);
    const position = () =>
      page.evaluate(() => getComputedStyle(document.querySelector(".session-trail-panel")!).position);
    await page.setViewportSize(PHONE);
    await boot(page);
    // Kept property (landing-cta-reachable.spec.ts): the panel still shows on the composer.
    await expect(trailPanel(page)).toBeVisible();
    const emptyPosition = await position();
    expect(
      emptyPosition === "fixed" || emptyPosition === "sticky",
      `an empty panel must not be pinned over the page (position: ${emptyPosition})`,
    ).toBe(false);

    // Run at desktop width so the click is not under any bar, then look again at 390.
    await page.setViewportSize(DESKTOP);
    await askReal(page, Q1);
    await page.setViewportSize(PHONE);
    await expect(trailEntries(page)).toHaveCount(1);
    // Positive partner: a list WITH entries keeps the existing bottom bar (ADR-0140 known limit).
    expect(await position()).toBe("fixed");
    expect(mocked()).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // Decision 8 — after a landing question the page lands on the models.
  // ---------------------------------------------------------------------------
  for (const [label, viewport] of [["1440", DESKTOP], ["390", PHONE]] as const) {
    test(`after a landing question the hint above the models takes focus and is in view (${label} px, bug 10)`, async ({ page }) => {
      // RED-IF: the landing hand-off focuses #query-text again, or the hint is missing, off-screen, covered, or not directly above the slots (rows 14, 17, 20).
      const mocked = forbidRoutes(page);
      await page.setViewportSize(viewport);
      await landingHandoff(page, "Compare two database options for a small team");
      const hint = handoffHint(page);
      await expect(hint).toBeVisible();
      await expect(hint).toHaveText(HINT_FOUR);
      await expect.poll(async () => (await hintGeometry(page))?.activeText ?? null).toBe(HINT_FOUR);
      const g = await hintGeometry(page);
      expect(g, "the hint must be in the composer").not.toBeNull();
      expect(g!.top, "hint top inside the viewport").toBeGreaterThanOrEqual(0);
      expect(g!.bottom, "hint bottom inside the viewport").toBeLessThanOrEqual(g!.viewportHeight);
      expect(g!.hitInsideHint, `a click at the hint's centre lands on ${g!.hitTag}`).toBe(true);
      expect(g!.top, "the hint sits below the question box").toBeGreaterThanOrEqual(g!.questionBottom);
      expect(g!.bottom, "the hint sits above the model slots").toBeLessThanOrEqual(g!.modelsTop);
      // Positive partner: the question did arrive in the composer.
      await expect(page.locator("#query-text")).toHaveValue("Compare two database options for a small team");
      expect(mocked()).toBe(false);
    });
  }

  test("quick mode: the hint and the hand-off note count the one model shown (row 19)", async ({ page }) => {
    // RED-IF: the hint or landingHandoffSlotCount counts rendered selects instead of the models actually shown.
    const mocked = forbidRoutes(page);
    await boot(page);
    await page.locator("#quick-mode-input").check();
    await page.locator("#show-landing").click();
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await page.locator("#landing-query").fill("Compare two database options for a small team");
    await page.locator("#landing-estimate").click();
    const note = page.locator("#landing-handoff-note-text");
    await expect(note).toContainText(/Got your question/);
    // Wording left open: "one" (or "your model"), never "four".
    await expect(note).not.toContainText(/\bfour\b/i);
    await expect(composerView(page)).toBeVisible({ timeout: 8000 });
    const hint = handoffHint(page);
    await expect(hint).toBeVisible();
    await expect(hint).toContainText(/\bone\b|\byour model\b/i);
    await expect(hint).not.toContainText(/\bfour\b/i);
    expect(mocked()).toBe(false);
  });

  test("a three-model panel: the hint says three (row 19)", async ({ page }) => {
    // RED-IF: the hint hard-codes "four" instead of counting the slots shown.
    const mocked = forbidRoutes(page);
    await boot(page);
    await page.locator("[data-slot-remove]").first().click();
    await expect(page.locator("select[data-model-slot]")).toHaveCount(3);
    await page.locator("#show-landing").click();
    await page.locator("#landing-query").fill("Compare two database options for a small team");
    await page.locator("#landing-estimate").click();
    await expect(composerView(page)).toBeVisible({ timeout: 8000 });
    const hint = handoffHint(page);
    await expect(hint).toBeVisible();
    await expect(hint).toContainText(/Your three models are picked for you/);
    expect(mocked()).toBe(false);
  });

  test("a high-stakes question: the hint says to tick the acknowledgement first and focus goes there (row 18)", async ({ page }) => {
    // RED-IF: the hint names See the estimate / Run now while the gate has disabled them, or focus does not go to #high-stakes-ack.
    const mocked = forbidRoutes(page);
    await landingHandoff(page, "Should I see a doctor about recurring headaches?");
    // Positive partner: the real warnings probe did show the gate.
    await expect(page.locator("#high-stakes-gate")).toBeVisible();
    const hint = handoffHint(page);
    await expect(hint).toBeVisible();
    // Wording left open: key word only.
    await expect(hint).toContainText(/tick/i);
    await expect(page.locator("#high-stakes-ack")).toBeFocused();
    expect(mocked()).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // Decision 9 (W43) — the empty box is not an error until a submit attempt.
  // ---------------------------------------------------------------------------
  test("a plain load does not mark the empty box invalid; an empty submit does (W43)", async ({ page }) => {
    // RED-IF: boot runs the validator and marks length 0 aria-invalid again (row 22).
    const mocked = forbidRoutes(page);
    await boot(page);
    const box = page.locator("#query-text");
    await expect(box).toHaveValue("");
    await expect(box).not.toHaveAttribute("aria-invalid", "true");
    await expect(page.locator("#query-validation-hint")).not.toHaveText("Question is required.");

    // Positive partner: the same empty box IS marked once the user tries to submit.
    await page.locator("#run-now").click();
    await expect(box).toHaveAttribute("aria-invalid", "true");
    await expect(
      page.locator("#error-region:visible, #query-error:visible").filter({ hasText: /question is required|enter a question/i }).first(),
    ).toBeVisible();
    expect(mocked()).toBe(false);
  });

  test("1–11 characters is advice, never an error state (W43)", async ({ page }) => {
    // RED-IF: updateQueryValidation sets aria-invalid="true" for a short-but-not-empty question.
    const mocked = forbidRoutes(page);
    await boot(page);
    const box = page.locator("#query-text");
    await box.fill("Short one");
    // Positive partner: the advice is shown.
    await expect(page.locator("#query-validation-hint")).toHaveText(/A few more characters/);
    await expect(box).not.toHaveAttribute("aria-invalid", "true");
    await expect(page.locator("#query-error")).toBeHidden();
    expect(mocked()).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // Failure-mode row 7 — Ctrl+Enter inside the next-question box.
  // ---------------------------------------------------------------------------
  test("Ctrl+Enter in the next-question box does what Review & run does (row 7)", async ({ page }) => {
    // RED-IF: the global Ctrl+Enter handler runs the hidden composer from the result view (a false "Question is required").
    const mocked = forbidRoutes(page);
    await boot(page);
    await askReal(page, Q1);
    let estimates = 0;
    page.on("request", (r) => {
      if (r.url().includes("/v1/query-runs/estimate")) estimates += 1;
    });
    const next = page.locator("#result-next-input");
    await next.fill(Q2);
    await next.press("Control+Enter");
    await expect(composerView(page)).toBeVisible();
    await expect(page.locator("#query-text")).toHaveValue(Q2);
    await expect(page.locator("#error-region")).toBeHidden();
    await page.waitForTimeout(300);
    expect(estimates, "Review & run does not start an estimate; neither may Ctrl+Enter").toBe(0);
    expect(mocked()).toBe(false);
  });
});

// =============================================================================
// Mocked: only states the real backend cannot reach within one session.
// =============================================================================

const fulfil = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});
const costEstimateEnvelope = () => ({
  correlation_id: "corr-journey-est",
  cost_estimate: goldenCreateResp().cost_estimate,
  model_slots: goldenCreateResp().model_slots,
  reasons: [],
});

test.describe("W33 slice A — states the real backend cannot reach (mocked, with the reason)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  test("the live-run view has no home control; the result it finishes into has both (row 9)", async ({ page }) => {
    // MOCKED because a real simulated run completes in 15-19 ms server-side
    // and the live-run view shows for one poll (about 0.76 s, measured
    // 2026-10-03), so it cannot be held open long enough to inspect it.
    // RED-IF: a brand link / New question appears on the live-run view, or the result view lacks them.
    let finished = false;
    await boot(page);
    await Promise.all([
      page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(costEstimateEnvelope()))),
      page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
      page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
    ]);
    await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) =>
      r.fulfill(fulfil(finished ? goldenCompletedResp() : goldenRunningResp(2000))),
    );
    await page.route(/\/v1\/query-runs$/, (r) =>
      r.request().method() === "POST" ? r.fulfill(fulfil(goldenCreateResp())) : r.continue(),
    );
    await page.locator("#query-text").fill(Q1);
    await page.locator("#run-now").click();

    const live = page.locator('[data-view="live-run"]');
    await expect(live).toBeVisible({ timeout: 20000 });
    // Positive partner: the live run keeps its Stop control.
    await expect(page.locator("#live-stop")).toBeVisible();
    await expect(page.locator('a[href$="/ui"]').filter({ visible: true })).toHaveCount(0);
    await expect(live.getByRole("button", { name: "New question", exact: true })).toHaveCount(0);

    finished = true;
    await expect(verdictVisible(page)).toBeVisible({ timeout: 20000 });
    await expect(newQuestionButton(page)).toBeVisible();
    await expect(resultBrandLink(page)).toBeVisible();
  });

  test("a stopped run shows New question on the live-run view, and it goes home (row 29)", async ({ page }) => {
    // MOCKED because a real simulated run completes in 15-19 ms server-side,
    // so Stop cannot reach it while it is still running. The poll answers
    // "running" until the DELETE (what Stop sends) answers "cancelled".
    // RED-IF: the live-run view keeps no way home once the run is no longer in progress.
    let cancelled = false;
    await boot(page);
    await Promise.all([
      page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(costEstimateEnvelope()))),
      page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
      page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
    ]);
    await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => {
      if (r.request().method() === "DELETE") cancelled = true;
      const body = goldenRunningResp(2000);
      return r.fulfill(fulfil(cancelled ? { ...body, status: "cancelled" } : body));
    });
    await page.route(/\/v1\/query-runs$/, (r) =>
      r.request().method() === "POST" ? r.fulfill(fulfil(goldenCreateResp())) : r.continue(),
    );
    await page.locator("#query-text").fill(Q1);
    await page.locator("#run-now").click();

    const live = page.locator('[data-view="live-run"]');
    await expect(live).toBeVisible({ timeout: 20000 });
    const liveNewQuestion = live.getByRole("button", { name: "New question", exact: true });
    // While it runs: Stop alone (row 9).
    await expect(page.locator("#live-stop")).toBeVisible();
    await expect(liveNewQuestion).toHaveCount(0);

    await page.locator("#live-stop").click();
    await expect.poll(() => cancelled).toBe(true);
    await expect(live, "a cancelled run stays on the live-run view").toBeVisible();
    await expect(liveNewQuestion).toBeVisible();
    await liveNewQuestion.click();
    await expect(composerView(page)).toBeVisible();
    await expect(live).toBeHidden();
  });

  test("going home from the result clears an error card (row 10)", async ({ page }) => {
    // MOCKED because the real backend cannot make a GET of your own finished
    // run fail; the failed re-fetch is how an error card reaches the result view.
    // RED-IF: the New question path leaves #error-region showing over the empty composer.
    await boot(page);
    await Promise.all([
      page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(costEstimateEnvelope()))),
      page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
      page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
    ]);
    await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => r.fulfill(fulfil(goldenCompletedResp())));
    await page.route(/\/v1\/query-runs$/, (r) =>
      r.request().method() === "POST" ? r.fulfill(fulfil(goldenCreateResp())) : r.continue(),
    );
    await page.locator("#query-text").fill(Q1);
    await page.locator("#run-now").click();
    await expect(verdictVisible(page)).toBeVisible({ timeout: 20000 });

    // Later routes win: the re-fetch behind a trail click now fails.
    await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) =>
      r.fulfill(fulfil({ error: { code: "INTERNAL_ERROR", message: "boom" } }, 500)),
    );
    await page.locator(".session-trail-entry").first().click();
    // Positive partner: the error card is really showing.
    await expect(page.locator("#error-region")).toBeVisible();

    await expect(newQuestionButton(page)).toBeVisible();
    await newQuestionButton(page).click();
    await expect(composerView(page)).toBeVisible();
    await expect(page.locator("#error-region")).toBeHidden();
  });
});
