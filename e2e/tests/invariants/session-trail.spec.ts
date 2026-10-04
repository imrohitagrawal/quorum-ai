import { test, expect, Page } from "@playwright/test";
import {
  boot,
  goldenCreateResp,
  goldenCompletedResp,
  goldenRunningResp,
} from "../../fixtures/golden-run";

const fulfil = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const costEstimateEnvelope = () => ({
  correlation_id: "corr-trail-est",
  cost_estimate: goldenCreateResp().cost_estimate,
  model_slots: goldenCreateResp().model_slots,
  reasons: [],
});

async function driveWithCompleted(page: Page, completed: Record<string, unknown>) {
  await boot(page);
  await Promise.all([
    page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(costEstimateEnvelope()))),
    page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
    page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
  ]);
  await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => r.fulfill(fulfil(completed)));
  await page.route(/\/v1\/query-runs$/, (r) =>
    r.request().method() === "POST" ? r.fulfill(fulfil(goldenCreateResp())) : r.continue(),
  );
  await page.getByRole("textbox").first().fill("What are the key metrics for measuring SaaS retention?");
  await page.locator("#run-now").click();
  await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
}

/** Navigate from the result view back to an empty composer with the result
    header's "New question" button (ADR-0140 decision 4). It used "Start
    fresh", which ADR-0140 hides until W37. */
async function goBackToComposer(page: Page) {
  const newQuestion = page.locator('[data-view="result"]').getByRole("button", { name: "New question", exact: true });
  await expect(newQuestion).toBeVisible();
  await newQuestion.click();
  await expect(page.locator("#query-text")).toBeVisible({ timeout: 10000 });
}

/** A distinct, well-formed run id per run index (the GET route matches 36 hex/dash chars). */
const distinctRunId = (i: number) => `${(i + 1).toString(16).padStart(8, "0")}-1111-4111-8111-111111111111`;

/** Answer every create with the next distinct run id, and every GET with a
    completed run under that id. Each run gets its own id so the trail's
    runId de-duplication can never be what keeps a count low. */
async function routeDistinctRuns(page: Page) {
  let created = 0;
  await Promise.all([
    page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(costEstimateEnvelope()))),
    page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
    page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
  ]);
  await page.route(/\/v1\/query-runs$/, (r) => {
    if (r.request().method() !== "POST") return r.continue();
    const id = distinctRunId(created);
    created += 1;
    return r.fulfill(fulfil({ ...goldenCreateResp(), query_run_id: id, correlation_id: `corr-${id}` }));
  });
  await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => {
    const id = r.request().url().split("/").pop() as string;
    return r.fulfill(fulfil({ ...goldenCompletedResp(), query_run_id: id, correlation_id: `corr-${id}` }));
  });
}

/** Run one question from wherever the page is: the composer on the first
    run, the result's next-question box after that (a path that exists both
    before and after ADR-0140). */
async function runQuestion(page: Page, question: string) {
  const onResult = await page.locator('[data-view="result"]').isVisible();
  if (onResult) {
    await page.locator("#result-next-input").fill(question);
    await page.locator("#result-next-run").click();
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
  }
  await page.locator("#query-text").fill(question);
  await page.locator("#run-now").click();
  await expect(page.locator("#result-question")).toHaveText(question, { timeout: 20000 });
  await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
}

test.describe("PR8 — Conversation trail UI", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  test("a completed run adds an entry to the trail panel", async ({ page }) => {
    await driveWithCompleted(page, goldenCompletedResp());

    const list = page.locator("#session-trail-list");
    await expect(list, "trail list must be visible after a completed run").toBeVisible();
    await expect(list).not.toBeHidden();
    const entries = list.locator(".session-trail-entry");
    await expect(entries).toHaveCount(1);
    const q = await entries.first().locator(".session-trail-question").textContent();
    expect(q).toContain("What are the key metrics");
  });

  test("a simulated run gets a muted trail entry", async ({ page }) => {
    await driveWithCompleted(page, {
      ...goldenCompletedResp(),
      demo_mode: true,
      live_count: 0,
      local_count: 4,
    });

    const entry = page.locator(".session-trail-entry");
    await expect(entry).toHaveCount(1);
    await expect(entry).toHaveClass(/session-trail-entry--muted/);
    const status = await entry.locator(".session-trail-status").textContent();
    expect(status?.toLowerCase()).toBe("simulated");
  });

  test("a failed run gets a muted trail entry", async ({ page }) => {
    await driveWithCompleted(page, {
      ...goldenCompletedResp(),
      demo_mode: false,
      live_count: 0,
      local_count: 0,
      status: "failed",
      failed_steps: ["synthesis"],
    });

    const entry = page.locator(".session-trail-entry");
    await expect(entry).toHaveCount(1);
    await expect(entry).toHaveClass(/session-trail-entry--muted/);
  });

  test("clicking a trail entry restores the result view", async ({ page }) => {
    await driveWithCompleted(page, goldenCompletedResp());
    // Click the trail entry and wait for the result to re-render.
    await page.locator(".session-trail-entry").first().click();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 10000 });
    // The trail must still be visible after restore.
    await expect(page.locator("#session-trail-list")).toBeVisible();
    await expect(page.locator(".session-trail-entry")).toHaveCount(1);
  });

  // ADR-0140 decision 1 / failure-mode row 2: the list keeps at most 10
  // entries and, once it reaches the cap, a line says so instead of dropping
  // the oldest silently. MOCKED because 11 runs cost about $1.16 against an
  // anonymous session's $0.40 daily envelope — the real backend cannot reach
  // the cap in one session. Each run has its own id (routeDistinctRuns), so
  // the runId de-duplication cannot be what holds the count at 10.
  // The ADR leaves the line's wording open; the design names "Showing your
  // last 10 questions", so the key phrase "last 10" is asserted, not the sentence.
  test("the list caps at 10 entries and says so once it reaches the cap", async ({ page }) => {
    // RED-IF: renderSessionTrail stops writing the cap line at SESSION_TRAIL_CAP entries, or the cap stops dropping the oldest.
    test.setTimeout(180000);
    await boot(page);
    await routeDistinctRuns(page);
    const q = (i: number) => `Cap test question number ${String(i).padStart(2, "0")}?`;
    const panel = page.locator(".session-trail-panel");
    const capLine = panel.getByText(/last 10/i);

    for (let i = 1; i <= 9; i++) await runQuestion(page, q(i));
    await expect(page.locator(".session-trail-entry")).toHaveCount(9);
    await expect(capLine, "below the cap there is nothing to say").toHaveCount(0);

    await runQuestion(page, q(10));
    await expect(page.locator(".session-trail-entry")).toHaveCount(10);
    await expect(capLine, "the line appears when the list REACHES the cap").toBeVisible();

    await runQuestion(page, q(11));
    await expect(page.locator(".session-trail-entry")).toHaveCount(10);
    await expect(capLine).toBeVisible();
    const questions = await page.locator(".session-trail-question").allTextContents();
    expect(questions.some((t) => t.includes(q(11)))).toBe(true);
    expect(questions.some((t) => t.includes(q(1))), "the oldest entry is the one dropped").toBe(false);
  });

  test("long questions are truncated to 80 characters", async ({ page }) => {
    const longQuestion = "A".repeat(200);
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
    await page.getByRole("textbox").first().fill(longQuestion);
    await page.locator("#run-now").click();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
    const text = await page.locator(".session-trail-question").first().textContent();
    expect(text!.length).toBeLessThanOrEqual(81); // 80 + ellipsis
    expect(text).toContain("…");
  });

  // ADR-0140 decision 1 (bug 1, M07 point 1). These two replace tests that
  // PINNED the bug: "'Start fresh' clears the session trail", and a "Start
  // fresh then a new run REPLACES the trail" test that could not tell a clear
  // from a de-duplication, because both runs reused the golden run id.
  // W37 (ADR-0143 decisions 4 and 7): Start fresh is back, and it only
  // switches the mode — pressing it must not empty the list.
  test("nothing but Clear empties the list: Start fresh and going to a new question keep the entry", async ({ page }) => {
    // RED-IF: #result-startfresh is not shown on a result with a final answer (ADR-0143 decision 4), or pressing it or any way back to the composer calls clearSessionTrail() (decision 7).
    await driveWithCompleted(page, goldenCompletedResp());
    await expect(page.locator(".session-trail-entry")).toHaveCount(1);
    await expect(page.locator("#result-next-run")).toBeVisible();
    await expect(page.locator("#result-startfresh")).toBeVisible();
    await page.locator("#result-startfresh").click();
    await expect(page.locator("#result-startfresh")).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".session-trail-entry"), "Start fresh keeps the list").toHaveCount(1);

    await page.locator("#result-next-run").click();
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await expect(page.locator(".session-trail-entry"), "going to the composer keeps the list").toHaveCount(1);

    // Clear is the one control that empties it.
    await page.locator("#session-trail-clear").click();
    await expect(page.locator(".session-trail-entry")).toHaveCount(0);
  });

  test("a new question after a finished run APPENDS to the list (two distinct run ids)", async ({ page }) => {
    // RED-IF: the result header's New question path clears the trail, or the button is missing (ADR-0140 decisions 1, 4).
    await boot(page);
    await routeDistinctRuns(page);
    await page.getByRole("textbox").first().fill("First question here?");
    await page.locator("#run-now").click();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
    await expect(page.locator(".session-trail-entry")).toHaveCount(1);

    await goBackToComposer(page);
    await expect(page.locator("#query-text")).toHaveValue("");
    await page.getByRole("textbox").first().fill("Second question here?");
    await page.locator("#run-now").click();
    await expect(page.locator("#result-question")).toHaveText("Second question here?", { timeout: 20000 });

    await expect(page.locator(".session-trail-entry")).toHaveCount(2);
    const questions = await page.locator(".session-trail-question").allTextContents();
    expect(questions.some((q) => q.includes("First question here?"))).toBe(true);
    expect(questions.some((q) => q.includes("Second question here?"))).toBe(true);
  });

  // #126: a FOLLOW-UP run (the "Follow up" mode is the default on the result
  // view's next-run panel — distinct from "Start fresh") is explicitly the
  // SAME session thread continuing, not a new one. Before this fix,
  // `clearSessionTrail()` fired unconditionally on every run creation
  // (app.js, inside the submit handler), so a follow-up silently dropped the
  // prior entry exactly like Start fresh did — the trail could never hold
  // more than 1 entry regardless of which button the user clicked.
  //
  // The two prior tests above use the SAME golden `query_run_id` for every
  // run, so `appendSessionTrailEntry`'s runId-dedupe alone would keep the
  // count at 1 even with the clear removed — they cannot distinguish
  // "cleared" from "deduped-and-replaced". This test uses two DISTINCT run
  // ids so only the clear-on-every-run bug can collapse the count.
  test("a follow-up run (not Start fresh) appends to the trail instead of replacing it", async ({ page }) => {
    await boot(page);
    const runIds = [
      "11111111-1111-4111-8111-111111111111",
      "22222222-2222-4222-8222-222222222222",
    ];
    let createCount = 0;
    await Promise.all([
      page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(costEstimateEnvelope()))),
      page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
      page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
    ]);
    await page.route(/\/v1\/query-runs$/, (r) => {
      if (r.request().method() !== "POST") return r.continue();
      const id = runIds[Math.min(createCount, runIds.length - 1)];
      createCount += 1;
      return r.fulfill(fulfil({ ...goldenCreateResp(), query_run_id: id, correlation_id: `corr-${id}` }));
    });
    await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => {
      const url = r.request().url();
      const id = runIds.find((rid) => url.includes(rid)) ?? runIds[0];
      return r.fulfill(fulfil({ ...goldenCompletedResp(), query_run_id: id, correlation_id: `corr-${id}` }));
    });

    await page.getByRole("textbox").first().fill("First question here?");
    await page.locator("#run-now").click();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
    await expect(page.locator(".session-trail-entry")).toHaveCount(1);

    // "Review & run" with an empty box goes back to the composer; since
    // ADR-0140 nothing pre-fills it, so the next line types the question.
    await page.locator("#result-next-run").click();
    await expect(page.locator("#query-text")).toBeVisible({ timeout: 10000 });
    await page.getByRole("textbox").first().fill("Second question here?");
    await page.locator("#run-now").click();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });

    // Both entries must be present — the follow-up continues the same
    // session thread, it does not start a new one.
    await expect(page.locator(".session-trail-entry")).toHaveCount(2);
    const questions = await page.locator(".session-trail-question").allTextContents();
    expect(questions.some((q) => q.includes("First question here?"))).toBe(true);
    expect(questions.some((q) => q.includes("Second question here?"))).toBe(true);
  });

  // ---- restoring an earlier run must restore ITS question -----------------
  //
  // `restoreTrailRun` used to take a bare run id and label the restored run
  // with `state.liveQueryText`, which is set only on SUBMIT. So clicking the
  // FIRST entry re-rendered run 1's answers under run 2's question — the UI
  // said "You asked" above a question the user had not asked of that run. It
  // then wrote the value back, so restoring A and then B labelled B with A's.
  //
  // The two tests below are each other's partner (AGENTS.md rule 7). The first
  // alone would pass a fix that always rendered the OLDEST entry's question;
  // the second alone would pass the original defect unchanged. Neither means
  // anything without the other.
  //
  // TURNS RED IF: restoreTrailRun stops receiving the entry, or falls back to
  // `state.liveQueryText` / the first model's answer text.

  async function driveTwoRunsThenRestore(page: Page, which: "first" | "second") {
    await boot(page);
    const runIds = [
      "11111111-1111-4111-8111-111111111111",
      "22222222-2222-4222-8222-222222222222",
    ];
    let createCount = 0;
    await Promise.all([
      page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(costEstimateEnvelope()))),
      page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
      page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
    ]);
    await page.route(/\/v1\/query-runs$/, (r) => {
      if (r.request().method() !== "POST") return r.continue();
      const id = runIds[Math.min(createCount, runIds.length - 1)];
      createCount += 1;
      return r.fulfill(fulfil({ ...goldenCreateResp(), query_run_id: id, correlation_id: `corr-${id}` }));
    });
    await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => {
      const url = r.request().url();
      const id = runIds.find((rid) => url.includes(rid)) ?? runIds[0];
      return r.fulfill(fulfil({ ...goldenCompletedResp(), query_run_id: id, correlation_id: `corr-${id}` }));
    });

    await page.getByRole("textbox").first().fill("First question here?");
    await page.locator("#run-now").click();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
    await page.locator("#result-next-run").click();
    await expect(page.locator("#query-text")).toBeVisible({ timeout: 10000 });
    await page.getByRole("textbox").first().fill("Second question here?");
    await page.locator("#run-now").click();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
    await expect(page.locator(".session-trail-entry")).toHaveCount(2);

    // Newest first, so index 0 is run 2 and index 1 is run 1.
    const wanted = which === "first" ? "First question here?" : "Second question here?";
    await page
      .locator(".session-trail-entry")
      .filter({ hasText: wanted.slice(0, 20) })
      .first()
      .click();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
    return wanted;
  }

  test("restoring the EARLIER run shows that run's own question", async ({ page }) => {
    const wanted = await driveTwoRunsThenRestore(page, "first");
    // Positive partner FIRST (#131): the equality below means nothing until the
    // question element is proven to hold something at all.
    await expect(page.locator("#result-question")).not.toBeEmpty();
    await expect(page.locator("#result-question")).toHaveText(wanted);
    await expect(
      page.locator("#result-question"),
      "the most recent run's question must not leak onto an earlier run",
    ).not.toHaveText("Second question here?");
  });

  test("restoring the LATER run shows that run's own question", async ({ page }) => {
    // The partner: a fix that always rendered the oldest entry would pass the
    // test above and fail here.
    const wanted = await driveTwoRunsThenRestore(page, "second");
    await expect(page.locator("#result-question")).not.toBeEmpty();
    await expect(page.locator("#result-question")).toHaveText(wanted);
  });

  // Found by adversarial review of the fix above (same PR, same file/
  // mechanism — self-fixed here rather than filed separately). Before this
  // fix, the trail was ALWAYS empty during a live run (every submission
  // cleared it), so a trail entry was never reachable while a run was in
  // flight. Now that a follow-up's prior entry survives, it stays visible —
  // and clickable — on the live-run view too, since the trail panel renders
  // on every view. Clicking it called `restoreTrailRun()`, which
  // unconditionally `stopPolling()`s and reassigns `state.currentRunId`:
  // the server keeps executing (and billing) the abandoned run, but the
  // client never polls it again, so the user silently loses it.
  test("a stale trail entry cannot hijack a run that is still in flight", async ({ page }) => {
    await boot(page);
    const runIds = [
      "11111111-1111-4111-8111-111111111111",
      "22222222-2222-4222-8222-222222222222",
    ];
    let createCount = 0;
    await Promise.all([
      page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(costEstimateEnvelope()))),
      page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
      page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
    ]);
    await page.route(/\/v1\/query-runs$/, (r) => {
      if (r.request().method() !== "POST") return r.continue();
      const id = runIds[Math.min(createCount, runIds.length - 1)];
      createCount += 1;
      return r.fulfill(fulfil({ ...goldenCreateResp(), query_run_id: id, correlation_id: `corr-${id}` }));
    });
    await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => {
      const url = r.request().url();
      // Run 1 completes; run 2 (the one in flight) never reaches a terminal
      // state for the duration of this test, so the UI stays on live-run.
      if (url.includes(runIds[1])) {
        return r.fulfill(fulfil({ ...goldenRunningResp(2000), query_run_id: runIds[1] }));
      }
      return r.fulfill(fulfil({ ...goldenCompletedResp(), query_run_id: runIds[0] }));
    });

    await page.getByRole("textbox").first().fill("First question here?");
    await page.locator("#run-now").click();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
    await expect(page.locator(".session-trail-entry")).toHaveCount(1);

    await page.locator("#result-next-run").click();
    await expect(page.locator("#query-text")).toBeVisible({ timeout: 10000 });
    await page.getByRole("textbox").first().fill("Second question here?");
    await page.locator("#run-now").click();

    // Run 2 is in flight (never completes): confirm we land on live-run,
    // and the prior entry from run 1 is visible but disabled.
    await expect(page.locator("[data-view='live-run']")).toBeVisible({ timeout: 20000 });
    const staleEntry = page.locator(".session-trail-entry");
    await expect(staleEntry).toHaveCount(1);
    await expect(staleEntry).toBeDisabled();

    // A disabled button does not dispatch a click in a real browser even
    // with Playwright's actionability checks bypassed — proving the guard
    // actually prevents the hijack, not just that the test never tried.
    await staleEntry.click({ force: true, timeout: 2000 }).catch(() => {});
    await expect(page.locator("[data-view='live-run']")).toBeVisible();
    await expect(page.locator("#result-verdict[data-consensus]")).toBeHidden();
  });
});
