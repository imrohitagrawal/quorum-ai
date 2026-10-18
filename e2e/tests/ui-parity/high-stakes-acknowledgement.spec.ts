import { test, expect, Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { freeze } from "../../fixtures/stabilize";
import { boot, SLOTS, goldenCreateResp, goldenCompletedResp, goldenRunningResp } from "../../fixtures/golden-run";

/**
 * W100 — a high-stakes acknowledgement is sent only for a ticked box, and a
 * run whose final warnings check names the high-stakes topic is HELD until the
 * box is ticked.
 *
 * The owner's decisions: CHG-063 (g) (the line "Tick the box above to run this
 * question." under the buttons when a run is held) and CHG-065 (a) the
 * sensitive-data acknowledgement stays automatic, (b) a fresh tick per run,
 * (c) unknown warning types are never acknowledged, (d) the existing toast
 * stays as well as the line.
 *
 * Mocked routes (no real backend), so each step's answer is fixed. Runs are
 * COUNTED by recording every POST to exactly /v1/query-runs (AGENTS.md rule
 * 6b): a test asserts how many, never only that one happened.
 *
 * The warnings mock answers like the server for the question it is given,
 * except that, when a test asks for it, a check sent BEFORE the first estimate
 * answers as if the background check had not caught up yet. That is how a
 * run reaches its final check with the box never shown.
 *
 * Every test carries a "Red when:" line.
 */

const SD = { warning_type: "sensitive_data", version: "sd-v7" };
const HS = { warning_type: "high_stakes", version: "hs-v3" };
const HIGH_STAKES_WORDS = /\b(contract|lawyer|loan)\b/i;

const HS_Q = "Should I sign this employment contract with a non-compete clause?";
const PLAIN_Q = "Postgres or MySQL for a small team?";
const EDITED_PLAIN_Q = "What should a good employment offer include?";
const FOLLOW_UP_HS_Q = "Do I need a lawyer to review it?";

const LINE = "Tick the box above to run this question.";
const TOAST = "Acknowledge the decision-support notice before running this query.";

type Ack = { warning_type: string; version: string };
type CreateBody = {
  query_text?: string;
  safety_acknowledgements?: Ack[];
  cost_confirmation?: { confirmation_token?: string } | null;
  context?: { prior_question?: string } | null;
};
type Band = "allow" | "require_confirmation";

const breakdown = (total: string) => ({
  by_model: SLOTS.map((s) => ({ model_id: s.model_id, display_name: s.display_label, usd: "0.025", kind: "model" })),
  by_stage: [{ stage: "initial_answers", usd: total }],
  total,
});
const estimateResp = (band: Band) => {
  const total = band === "allow" ? "0.100" : "0.190";
  return {
    correlation_id: "corr-w100-est",
    cost_estimate: {
      estimated_cost_usd: total,
      max_cost_usd: (Number(total) * 1.2).toFixed(4),
      currency: "USD",
      threshold_action: band,
      confirmation_token: "tok-w100",
      reasons: [],
      breakdown: breakdown(total),
    },
    model_slots: SLOTS,
    reasons: [],
  };
};
const fulfil = (body: unknown, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify(body) });

interface Mock {
  creates: CreateBody[];
  estimates: number;
  /** Before the first estimate, answer sensitive-data only (a check that has not caught up). */
  blindUntilEstimate: boolean;
  /** How the warnings checks AFTER the first estimate answer. */
  finalMode: "answer" | "abort" | "empty";
  band: Band;
  /** Set true to hold the first warnings check after the NEXT estimate open. */
  armHold: boolean;
  held: number;
  release: () => void;
  /** While true, the run poll answers "still running", so the page stays on the live run. */
  pollRunning: boolean;
}

async function installMocks(page: Page, opts: Partial<Pick<Mock, "blindUntilEstimate" | "finalMode" | "band">> = {}): Promise<Mock> {
  let releaseGate: () => void = () => {};
  const gate = new Promise<void>((r) => (releaseGate = r));
  let holdNextWarnings = false;
  const mock: Mock = {
    creates: [],
    estimates: 0,
    blindUntilEstimate: opts.blindUntilEstimate ?? false,
    finalMode: opts.finalMode ?? "answer",
    band: opts.band ?? "allow",
    armHold: false,
    held: 0,
    release: () => releaseGate(),
    pollRunning: false,
  };
  await page.route("**/v1/query-runs/estimate", (r) => {
    mock.estimates += 1;
    if (mock.armHold) {
      mock.armHold = false;
      holdNextWarnings = true;
    }
    return r.fulfill(fulfil(estimateResp(mock.band)));
  });
  await page.route("**/v1/query-runs/warnings", async (r) => {
    const body = (r.request().postDataJSON() ?? {}) as { query_text?: string; context?: { prior_question?: string } };
    const afterEstimate = mock.estimates > 0;
    if (afterEstimate && holdNextWarnings) {
      holdNextWarnings = false;
      mock.held += 1;
      await gate;
    }
    if (afterEstimate && mock.finalMode === "abort") return r.abort("failed");
    if (afterEstimate && mock.finalMode === "empty") return r.fulfill(fulfil({}));
    const text = `${body.query_text ?? ""} ${body.context?.prior_question ?? ""}`;
    const highStakes = HIGH_STAKES_WORDS.test(text) && (afterEstimate || !mock.blindUntilEstimate);
    return r.fulfill(fulfil({ warnings: highStakes ? [SD, HS] : [SD] }));
  });
  await page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null })));
  let elapsed = 1000;
  await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => {
    elapsed += 1000;
    return r.fulfill(fulfil(mock.pollRunning ? goldenRunningResp(elapsed) : goldenCompletedResp()));
  });
  await page.route(/\/v1\/query-runs$/, (r) => {
    if (r.request().method() !== "POST") return r.continue();
    mock.creates.push((r.request().postDataJSON() ?? {}) as CreateBody);
    return r.fulfill(fulfil(goldenCreateResp()));
  });
  return mock;
}

const ack = (page: Page) => page.locator("#high-stakes-ack");
const box = (page: Page) => page.locator("#high-stakes-gate");
const line = (page: Page) => page.locator("#high-stakes-held");
const runNow = (page: Page) => page.locator("#run-now");
const seeEstimate = (page: Page) => page.locator("#estimate-run");
const composer = (page: Page) => page.locator('[data-view="composer"]');
const costGate = (page: Page) => page.locator('[data-view="cost-gate"]');
const activeId = (page: Page) => page.evaluate(() => document.activeElement?.id ?? null);
const ackChecked = (page: Page) =>
  page.evaluate(() => (document.getElementById("high-stakes-ack") as HTMLInputElement | null)?.checked ?? null);
const types = (body: CreateBody | undefined) => (body?.safety_acknowledgements ?? []).map((a) => a.warning_type);

/** Wait long enough for a create that is going to happen to be POSTed (mocked answers are immediate). */
const settle = (page: Page) => page.waitForTimeout(1500);

/**
 * THE HELD STATE: no new run, the composer with the box unticked, the line,
 * the toast, focus on the box (and still there a second later), both buttons
 * disabled and not loading, no error card, the question untouched.
 */
async function expectHeld(page: Page, mock: Mock, createsBefore: number, question: string) {
  await settle(page);
  expect(mock.creates, "a held run must create nothing").toHaveLength(createsBefore);
  await expect(composer(page)).toBeVisible();
  await expect(costGate(page)).toBeHidden();
  await expect(box(page)).toBeVisible();
  await expect(ack(page)).not.toBeChecked();
  await expect(line(page)).toBeVisible();
  await expect(line(page)).toHaveText(LINE);
  await expect(page.getByText(LINE, { exact: true })).toHaveCount(1);
  await expect(ack(page)).toHaveAttribute("aria-describedby", /(^|\s)high-stakes-held(\s|$)/);
  await expect(page.locator("#toast-region").getByText(TOAST, { exact: true })).toBeVisible();
  expect(await activeId(page), "focus moves to the tick box on a hold").toBe("high-stakes-ack");
  await page.waitForTimeout(1000);
  expect(await activeId(page), "nothing later in the flow takes focus off the box").toBe("high-stakes-ack");
  for (const button of [runNow(page), seeEstimate(page)]) {
    await expect(button).toBeDisabled();
    await expect(button).not.toHaveAttribute("data-loading", "true");
  }
  await expect(page.locator("#gate-confirm")).not.toHaveAttribute("data-loading", "true");
  await expect(page.locator("#error-region")).toBeHidden();
  await expect(page.locator("#query-text")).toHaveValue(question);
}

/** After a tick on a held run, the line and its description go, and both buttons come back. */
async function expectReleasedByTick(page: Page) {
  await ack(page).check();
  await expect(line(page)).toBeHidden();
  await expect
    .poll(() => ack(page).getAttribute("aria-describedby").then((v) => v ?? ""), { message: "the description goes with the line" })
    .not.toMatch(/(^|\s)high-stakes-held(\s|$)/);
  await expect(runNow(page)).toBeEnabled();
  await expect(seeEstimate(page)).toBeEnabled();
}

test.describe("W100 — a high-stakes acknowledgement only for a ticked box (mocked)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "chromium-only reference run");

  test("Run now with an unticked high-stakes final check holds the run; a tick then creates exactly one", async ({ page }) => {
    // Red when: the create is sent while the box is unticked (the final check's
    // high-stakes warning acknowledged for the visitor), or the hold lacks the
    // line, the toast or the focus, or the line is not in the page hidden on load.
    const mock = await installMocks(page, { blindUntilEstimate: true });
    await boot(page);
    await page.locator("#query-text").fill(HS_Q);
    await runNow(page).click();
    await expectHeld(page, mock, 0, HS_Q);
    const estimatesAtHold = mock.estimates;

    await expectReleasedByTick(page);
    await runNow(page).click();
    await expect.poll(() => mock.creates.length).toBe(1);
    await settle(page);
    expect(mock.creates, "exactly one run for the whole journey").toHaveLength(1);
    expect(mock.creates[0].safety_acknowledgements).toEqual([SD, HS]);
    expect(mock.estimates, "the held run's estimate is dropped, so the next run asks again").toBe(estimatesAtHold + 1);
  });

  test("the held line is in the composer, hidden, before anything is held", async ({ page }) => {
    // Red when: the line is missing from the page, is shown on load, or sits
    // outside the composer view (where the result and transcript views live).
    await installMocks(page);
    await boot(page);
    await expect(line(page)).toHaveCount(1);
    await expect(line(page)).toBeHidden();
    expect(
      await page.evaluate(() => !!document.querySelector('[data-view="composer"] #high-stakes-held')),
      "the line lives inside the composer view",
    ).toBe(true);
  });

  test("the cost gate's confirm button holds an unticked high-stakes run and returns to the composer", async ({ page }) => {
    // Red when: confirming on the cost gate creates a run with the box never
    // ticked, or the hold stays on the gate (where the box does not exist).
    const mock = await installMocks(page, { blindUntilEstimate: true, band: "require_confirmation" });
    await boot(page);
    await page.locator("#query-text").fill(HS_Q);
    await seeEstimate(page).click();
    await expect(page.locator("#gate-confirm")).toBeVisible();
    await page.locator("#gate-confirm").click();
    await expectHeld(page, mock, 0, HS_Q);

    await expectReleasedByTick(page);
    const before = mock.estimates;
    await seeEstimate(page).click();
    await expect(page.locator("#gate-confirm")).toBeVisible();
    expect(mock.estimates, "a fresh estimate (and confirmation) after the hold").toBe(before + 1);
    await page.locator("#gate-confirm").click();
    await settle(page);
    expect(mock.creates, "exactly one run for the whole journey").toHaveLength(1);
    expect(mock.creates[0].safety_acknowledgements).toEqual([SD, HS]);
    expect(mock.creates[0].cost_confirmation?.confirmation_token).toBe("tok-w100");
  });

  test("Ctrl/Cmd+Enter on the cost gate holds an unticked high-stakes run", async ({ page }) => {
    // Red when: the keyboard confirm on the cost gate creates a run with the
    // box never ticked.
    const mock = await installMocks(page, { blindUntilEstimate: true, band: "allow" });
    await boot(page);
    await page.locator("#query-text").fill(HS_Q);
    await seeEstimate(page).click();
    await expect(page.locator("#gate-confirm")).toBeVisible();
    await page.keyboard.press("ControlOrMeta+Enter");
    await expectHeld(page, mock, 0, HS_Q);

    await expectReleasedByTick(page);
    await seeEstimate(page).click();
    await expect(page.locator("#gate-confirm")).toBeVisible();
    await page.keyboard.press("ControlOrMeta+Enter");
    await settle(page);
    expect(mock.creates, "exactly one run for the whole journey").toHaveLength(1);
    expect(mock.creates[0].safety_acknowledgements).toEqual([SD, HS]);
  });

  for (const how of ["the confirm button", "Ctrl/Cmd+Enter"] as const) {
    test(`a tick made before the cost gate still counts there: ${how} creates exactly one run with both acknowledgements`, async ({ page }) => {
      // Red when: the hold also fires for a ticked box once the composer (and
      // the box with it) is hidden behind the cost gate, so a confirmed run can
      // never start (the Codex plan-review case). True today; it guards the fix.
      const mock = await installMocks(page, { band: "require_confirmation" });
      await boot(page);
      await page.locator("#query-text").fill(HS_Q);
      await expect(box(page)).toBeVisible();
      await expect(line(page)).toBeHidden();
      await ack(page).check();
      await seeEstimate(page).click();
      await expect(page.locator("#gate-confirm")).toBeVisible();
      if (how === "the confirm button") await page.locator("#gate-confirm").click();
      else await page.keyboard.press("ControlOrMeta+Enter");
      await expect.poll(() => mock.creates.length).toBe(1);
      await settle(page);
      expect(mock.creates).toHaveLength(1);
      expect(mock.creates[0].safety_acknowledgements).toEqual([SD, HS]);
      await expect(page.locator("#toast-region").getByText(TOAST, { exact: true })).toHaveCount(0);
      await expect(page.locator("#error-region")).toBeHidden();
    });
  }

  test("unticking while the final check is still answering sends no high-stakes acknowledgement", async ({ page }) => {
    // Red when: the tick is read before the final check answers (a consent
    // withdrawn during the wait is still sent), or the run is created anyway.
    const mock = await installMocks(page);
    await boot(page);
    await page.locator("#query-text").fill(HS_Q);
    await expect(box(page)).toBeVisible();
    await ack(page).check();
    mock.armHold = true;
    await runNow(page).click();
    await expect.poll(() => mock.held, { message: "the final check is being held open" }).toBe(1);
    await ack(page).uncheck();
    mock.release();
    await expectHeld(page, mock, 0, HS_Q);
  });

  for (const mode of ["abort", "empty"] as const) {
    test(`a final check that ${mode === "abort" ? "fails" : "answers {}"} creates nothing and shows the error`, async ({ page }) => {
      // Red when: a failed or malformed final check is treated as "no
      // warnings" and a run is created (fail open). True today; it guards the fix.
      const mock = await installMocks(page, { finalMode: mode });
      await boot(page);
      await page.locator("#query-text").fill(PLAIN_Q);
      await runNow(page).click();
      await expect(page.locator("#error-region")).toBeVisible();
      await settle(page);
      expect(mock.creates).toHaveLength(0);
      expect(mock.estimates, "the flow did reach its final check").toBe(1);
    });
  }

  test("the tick clears once a run starts, so a second high-stakes question needs a fresh tick", async ({ page }) => {
    // Red when: the tick from the first run stays on and is reused for the
    // next high-stakes question (CHG-065 (b)).
    const mock = await installMocks(page);
    // Keep the first run on the live view: a finished run empties the question
    // box, and the empty-box check unticks the box anyway, which would let this
    // test pass without the fresh-tick rule.
    mock.pollRunning = true;
    await boot(page);
    await page.locator("#query-text").fill(HS_Q);
    await expect(box(page)).toBeVisible();
    await ack(page).check();
    await runNow(page).click();
    await expect.poll(() => mock.creates.length).toBe(1);
    expect(mock.creates[0].safety_acknowledgements).toEqual([SD, HS]);
    await expect(page.locator('[data-view="live-run"]')).toBeVisible();
    await expect
      .poll(() => ackChecked(page), { timeout: 1000, message: "the box is unticked once the run is created" })
      .toBe(false);
    await page.waitForTimeout(1000);
    await expect(page.locator('[data-view="live-run"]')).toBeVisible();
    expect(await ackChecked(page), "and stays unticked during the run").toBe(false);

    mock.pollRunning = false;
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
    await page.locator("#result-next-input").fill(FOLLOW_UP_HS_Q);
    await page.locator("#result-next-run").click();
    await expect(composer(page)).toBeVisible();
    await expect(box(page)).toBeVisible();
    await expect(ack(page)).not.toBeChecked();
    await expect(runNow(page)).toBeDisabled();
    await expect(seeEstimate(page)).toBeDisabled();
    expect(mock.creates).toHaveLength(1);

    await ack(page).check();
    await runNow(page).click();
    await expect.poll(() => mock.creates.length).toBe(2);
    await settle(page);
    expect(mock.creates, "two runs in total, one per tick").toHaveLength(2);
    expect(mock.creates[1].safety_acknowledgements).toEqual([SD, HS]);
    expect(mock.creates[1].query_text).toBe(FOLLOW_UP_HS_Q);
    expect(mock.creates[1].context?.prior_question).toBe(HS_Q);
  });

  test("after a hold, editing to a question with no high-stakes words hides the box and the line together", async ({ page }) => {
    // Red when: the line outlives the box ("Tick the box above" over no box),
    // its description stays on the tick box, or the held question is the one
    // that runs instead of the edited one.
    const mock = await installMocks(page, { blindUntilEstimate: true });
    await boot(page);
    await page.locator("#query-text").fill(HS_Q);
    await runNow(page).click();
    await expectHeld(page, mock, 0, HS_Q);

    await page.locator("#query-text").fill(EDITED_PLAIN_Q);
    await expect(box(page)).toBeHidden({ timeout: 5000 });
    await expect(line(page)).toBeHidden();
    await expect(line(page)).toHaveCount(1);
    await expect
      .poll(() => ack(page).getAttribute("aria-describedby").then((v) => v ?? ""))
      .not.toMatch(/(^|\s)high-stakes-held(\s|$)/);
    await expect(runNow(page)).toBeEnabled();
    await runNow(page).click();
    await expect.poll(() => mock.creates.length).toBe(1);
    await settle(page);
    expect(mock.creates).toHaveLength(1);
    expect(mock.creates[0].query_text).toBe(EDITED_PLAIN_Q);
    expect(types(mock.creates[0])).toEqual(["sensitive_data"]);
  });

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 375, height: 812 },
  ]) {
    test(`at ${viewport.width} px the held line sits below both buttons with no sideways scroll`, async ({ page }) => {
      // Red when: the line is placed beside or above "Run now" (inside the
      // button row, or above the footer), or the held state widens the page.
      await page.setViewportSize(viewport);
      const mock = await installMocks(page, { blindUntilEstimate: true });
      await boot(page);
      await page.locator("#query-text").fill(HS_Q);
      await runNow(page).click();
      await settle(page);
      expect(mock.creates).toHaveLength(0);
      await expect(line(page)).toBeVisible();
      const geometry = await page.evaluate(() => {
        const rect = (id: string) => document.getElementById(id)!.getBoundingClientRect();
        return {
          lineTop: rect("high-stakes-held").top,
          runNowBottom: rect("run-now").bottom,
          estimateBottom: rect("estimate-run").bottom,
          overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        };
      });
      expect(geometry.lineTop, "the line starts below Run now").toBeGreaterThanOrEqual(geometry.runNowBottom);
      expect(geometry.lineTop, "the line starts below See the estimate").toBeGreaterThanOrEqual(geometry.estimateBottom);
      expect(geometry.overflow, "no horizontal page scroll").toBeLessThanOrEqual(0);
    });
  }

  test("the held state has no serious or critical axe violations in either theme", async ({ page }) => {
    // Red when: the held state adds an accessibility violation (for example a
    // description pointing at a missing id), or the held state is never reached.
    const mock = await installMocks(page, { blindUntilEstimate: true });
    await boot(page);
    await page.locator("#query-text").fill(HS_Q);
    await runNow(page).click();
    await settle(page);
    expect(mock.creates).toHaveLength(0);
    await expect(line(page)).toBeVisible();
    for (const theme of ["light", "dark"] as const) {
      await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await page.waitForTimeout(150);
      await freeze(page);
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      const serious = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
      expect(serious, `held state [${theme}] critical/serious axe violations:\n` +
        serious.map((v) => `  ${v.impact} ${v.id} @ ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`).join("\n"),
      ).toEqual([]);
    }
  });
});
