import { test, expect, Page, Request } from "@playwright/test";
import { boot, driveToResult, goldenCompletedResp } from "../../fixtures/golden-run";

/**
 * W37 — a follow-up sends the previous question and final answer (ADR-0143).
 *
 * The first describe drives the REAL FastAPI app Playwright's webServer starts
 * (live execution off, so every run is simulated and costs $0), with NO
 * `page.route`: the same guard page-journey.spec.ts uses fails a test that adds
 * one. Requests are OBSERVED with `page.on("request")`, never answered.
 *
 * Budget: each browser context is a new anonymous session with a $0.40 daily
 * envelope; a simulated run is about $0.105 and a follow-up a little more, so
 * no test here runs more than two questions.
 *
 * Exact copy (the owner's or the ADR's words): "Follow up on this", "Start
 * fresh", "Following up on: ", "Choose models →". Where the ADR leaves wording
 * open (the note's second sentence, the composer line's layout) a test asserts
 * the element and a key phrase only. The quote marks around the previous
 * question may be straight or curly.
 *
 * Selectors are the template's own or roles and names: the "Ask your next
 * question" region and its two mode buttons by name; the composer's line by
 * its text "Following up on: " and its button by the name "Start fresh".
 *
 * Rows are those of docs/analysis/2026-10-04-w37-follow-up-context-failure-modes.md.
 */

// Short on purpose: the note and the composer line may shorten a long
// question for display (row 15), and these must show whole.
const Q1 = "Postgres or MySQL for a small team?";
const Q2 = "What about running it on a managed service?";
const Q3 = "How do I back up a small database?";

type Ctx = { prior_question?: string; prior_synthesis?: string } | undefined;
type Body = { query_text?: string; mode?: string; context?: Ctx };
type Sent = { kind: "estimate" | "warnings" | "create"; body: Body; seq: number };

function forbidRoutes(page: Page): () => boolean {
  let mocked = false;
  const origRoute = page.route.bind(page);
  (page as unknown as { route: typeof page.route }).route = ((...args: Parameters<typeof origRoute>) => {
    mocked = true;
    return origRoute(...args);
  }) as typeof page.route;
  return () => mocked;
}

/** Every estimate, warnings probe and create the page sends, in order. */
function recordRunRequests(page: Page): Sent[] {
  const sent: Sent[] = [];
  let seq = 0;
  page.on("request", (r: Request) => {
    if (r.method() !== "POST") return;
    const path = new URL(r.url()).pathname;
    const kind =
      path === "/v1/query-runs/estimate" ? "estimate"
      : path === "/v1/query-runs/warnings" ? "warnings"
      : path === "/v1/query-runs" ? "create"
      : null;
    if (kind) sent.push({ kind, body: (r.postDataJSON() ?? {}) as Body, seq: seq++ });
  });
  return sent;
}

type RunPayload = {
  query_run_id?: string;
  mode?: string;
  status?: string;
  result?: {
    final_synthesis?: Record<string, string | null> | null;
    model_answers?: { answer_text?: string; status?: string }[];
  };
};

/** The last payload the page received for each run id (GET /v1/query-runs/<id>). */
function recordRunPayloads(page: Page): Map<string, RunPayload> {
  const byId = new Map<string, RunPayload>();
  page.on("response", async (res) => {
    const m = new URL(res.url()).pathname.match(/^\/v1\/query-runs\/([0-9a-f-]{36})$/);
    if (!m || res.request().method() !== "GET" || !res.ok()) return;
    try {
      byId.set(m[1], (await res.json()) as RunPayload);
    } catch (_) {
      /* a body that is not JSON is not a run payload */
    }
  });
  return byId;
}

const lastOf = (sent: Sent[], kind: Sent["kind"]) => [...sent].reverse().find((s) => s.kind === kind);
const countOf = (sent: Sent[], kind: Sent["kind"]) => sent.filter((s) => s.kind === kind).length;

/** Wait until the page has sent one more request of `kind` than `before`. */
async function nextSent(sent: Sent[], kind: Sent["kind"], before: number): Promise<Sent> {
  await expect.poll(() => countOf(sent, kind), { timeout: 15000 }).toBeGreaterThan(before);
  return lastOf(sent, kind)!;
}

/** The warnings probe sent last before the create with sequence number `seq`. */
function probeBefore(sent: Sent[], seq: number): Sent | undefined {
  return [...sent].reverse().find((s) => s.kind === "warnings" && s.seq < seq);
}

const composerView = (page: Page) => page.locator('[data-view="composer"]');
const resultView = (page: Page) => page.locator('[data-view="result"]');
const nextRegion = (page: Page) => page.getByRole("region", { name: "Ask your next question" });
const followUpButton = (page: Page) => nextRegion(page).getByRole("button", { name: "Follow up on this", exact: true });
const startFreshButton = (page: Page) => nextRegion(page).getByRole("button", { name: "Start fresh", exact: true });
const nextNote = (page: Page) => page.locator(".result-next-note");
const composerFollowLine = (page: Page) => composerView(page).getByText(/Following up on: /).filter({ visible: true });
const composerStartFresh = (page: Page) =>
  composerView(page).getByRole("button", { name: "Start fresh", exact: true });
const trailEntries = (page: Page) => page.locator(".session-trail-entry");
/** `Following up on: "Q"` with straight or curly quotes. */
const followingUpOn = (q: string) =>
  new RegExp(`Following up on: ["“]${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}["”]`);

/** Wait for a real panel run started from the composer to reach the result view. */
async function settleRealRun(page: Page) {
  await expect(
    page.locator('#result-verdict[data-consensus]:visible, #gate-confirm:visible').first(),
  ).toBeVisible({ timeout: 30000 });
  const confirm = page.locator("#gate-confirm");
  if (await confirm.isVisible()) await confirm.click();
  await expect(page.locator('[data-view="result"] #result-verdict[data-consensus]')).toBeVisible({ timeout: 30000 });
}

async function askReal(page: Page, question: string) {
  await page.locator("#query-text").fill(question);
  await page.locator("#run-now").click();
  await settleRealRun(page);
  await expect(page.locator("#result-question")).toHaveText(question);
}

/** See the estimate, and return the estimate body the page sent. */
async function seeTheEstimate(page: Page, sent: Sent[]): Promise<Body> {
  const before = countOf(sent, "estimate");
  await page.locator("#estimate-run").click();
  return (await nextSent(sent, "estimate", before)).body;
}

/** From an open cost gate, approve and run; wait for the result of `question`. */
async function approveAndSettle(page: Page, question: string) {
  await expect(page.locator("#gate-confirm")).toBeVisible({ timeout: 15000 });
  await page.locator("#gate-confirm").click();
  await expect(page.locator('[data-view="result"] #result-verdict[data-consensus]')).toBeVisible({ timeout: 30000 });
  await expect(page.locator("#result-question")).toHaveText(question);
}

/** The five sections as the page shows them, in order, from a run payload. */
function shownSections(payload: RunPayload | undefined): string[] {
  const fs = payload?.result?.final_synthesis ?? null;
  expect(fs, "the run payload carries a final synthesis").not.toBeNull();
  return ["consensus", "disagreement", "uncertainty", "recommendation", "source_support"]
    .map((k) => String(fs![k] ?? "").trim())
    .filter((t) => t !== "");
}

/** `text` holds every section, in display order. */
function expectSectionsInOrder(text: string, sections: string[]) {
  expect(sections.length, "the previous result had at least one non-empty section").toBeGreaterThan(0);
  let from = 0;
  for (const s of sections) {
    const at = text.indexOf(s, from);
    expect(at, `section missing or out of order in prior_synthesis: ${s.slice(0, 60)}`).toBeGreaterThanOrEqual(0);
    from = at + s.length;
  }
}

test.describe("W37 — follow-up context on the real backend (no page.route)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  test("the owner's journey: landing → run → Follow up → estimate, warnings and run carry the context → Start fresh carries none", async ({ page }) => {
    // RED-IF: any of ADR-0143 decisions 4, 5, 6, 7 or 8 regresses — the first broken step names itself.
    const mocked = forbidRoutes(page);
    const sent = recordRunRequests(page);
    const payloads = recordRunPayloads(page);

    // Decision 8: the landing button is renamed. A first visit opens the landing.
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-view="landing"]')).toBeVisible();
    await expect(page.locator("#landing-run")).toHaveText("Choose models →");
    await page.locator("#landing-query").fill(Q1);
    await page.locator("#landing-run").click();
    await expect(composerView(page)).toBeVisible({ timeout: 8000 });
    await expect(page.locator("#query-text")).toHaveValue(Q1);
    await page.locator("#run-now").click();
    await settleRealRun(page);
    await expect(page.locator("#result-question")).toHaveText(Q1);
    const q1Create = lastOf(sent, "create");
    expect(q1Create, "the first run was created").toBeTruthy();
    expect(q1Create!.body.context, "a question asked from the landing carries no context").toBeUndefined();

    // Decision 4: both buttons, Follow up pressed by default, the note names Q1, the box is empty.
    await expect(followUpButton(page)).toBeVisible();
    await expect(startFreshButton(page)).toBeVisible();
    await expect(followUpButton(page)).toHaveAttribute("aria-pressed", "true");
    await expect(startFreshButton(page)).toHaveAttribute("aria-pressed", "false");
    await expect(nextNote(page)).toContainText(followingUpOn(Q1));
    await expect(page.locator("#result-next-input")).toHaveValue("");

    // The prior answer the page must send: Q1's five sections as shown.
    const q1RunId = [...payloads.keys()].find((id) => payloads.get(id)?.result?.final_synthesis);
    const q1Sections = shownSections(q1RunId ? payloads.get(q1RunId) : undefined);

    // Decision 5: Review & run attaches the context; the composer shows the line.
    await page.locator("#result-next-input").fill(Q2);
    await page.locator("#result-next-run").click();
    await expect(composerView(page)).toBeVisible();
    await expect(page.locator("#query-text")).toHaveValue(Q2);
    await expect(composerFollowLine(page)).toBeVisible();
    await expect(composerFollowLine(page)).toContainText(Q1);

    const estimate = await seeTheEstimate(page, sent);
    expect(estimate.query_text).toBe(Q2);
    expect(estimate.context?.prior_question, "the estimate carries the previous question").toBe(Q1);
    const priorAnswer = estimate.context?.prior_synthesis ?? "";
    expect(priorAnswer.length, "the estimate carries a previous answer").toBeGreaterThan(0);
    expect(priorAnswer.length).toBeLessThanOrEqual(60117);
    expectSectionsInOrder(priorAnswer, q1Sections);

    // Run it: the create (and the warnings probe just before it) carry the same context (rows 5, 6).
    const createsBefore = countOf(sent, "create");
    await approveAndSettle(page, Q2);
    const create = await nextSent(sent, "create", createsBefore);
    expect(create.body.context, "the create carries the context the estimate was priced for").toEqual(estimate.context);
    const probe = probeBefore(sent, create.seq);
    expect(probe, "a warnings probe was sent before the create").toBeTruthy();
    expect(probe!.body.context, "the warnings probe carries the same context").toEqual(estimate.context);

    // Decision 4: on Q2's result the note now names Q2 — one step back only (decision 6).
    await expect(nextNote(page)).toContainText(followingUpOn(Q2));

    // Start fresh: the note says on its own; the composer has no line; the estimate no context.
    await startFreshButton(page).click();
    await expect(startFreshButton(page)).toHaveAttribute("aria-pressed", "true");
    await expect(followUpButton(page)).toHaveAttribute("aria-pressed", "false");
    await expect(nextNote(page)).toContainText(/on its own/i);
    await expect(nextNote(page)).not.toContainText(/Following up on/);
    await page.locator("#result-next-input").fill(Q3);
    await page.locator("#result-next-run").click();
    await expect(composerView(page)).toBeVisible();
    await expect(page.locator("#query-text")).toHaveValue(Q3);
    await expect(composerFollowLine(page)).toHaveCount(0);
    const fresh = await seeTheEstimate(page, sent);
    expect(fresh.query_text).toBe(Q3);
    expect(fresh.context, "Start fresh sends no context").toBeUndefined();

    // Decision 7 (ADR-0140 decision 1): Start fresh does not empty the session list.
    await expect(trailEntries(page)).toHaveCount(2);
    expect(mocked(), "this journey must NOT use page.route").toBe(false);
  });

  test("the composer's Start fresh button drops the context", async ({ page }) => {
    // RED-IF: the composer has no Following up line or no Start fresh button, or pressing it leaves the context on the estimate (row 13).
    const mocked = forbidRoutes(page);
    const sent = recordRunRequests(page);
    await boot(page);
    await askReal(page, Q1);
    await page.locator("#result-next-input").fill(Q2);
    await page.locator("#result-next-run").click();
    // Positive partners, BEFORE the button is pressed: exactly one Following up
    // line is on screen (partner of the toHaveCount(0) below), and an estimate
    // sent now DOES carry the context (partner of the toBeUndefined below), so
    // both absence checks examine something that was present.
    await expect(composerFollowLine(page)).toHaveCount(1);
    await expect(composerFollowLine(page)).toContainText(Q1);
    const attached = await seeTheEstimate(page, sent);
    expect(attached.context?.prior_question).toBe(Q1);
    expect((attached.context?.prior_synthesis ?? "").length).toBeGreaterThan(0);
    // "Back to edit" returns to the composer with the context still attached.
    await page.locator("#gate-back").click();
    await expect(composerView(page)).toBeVisible();
    await expect(composerFollowLine(page)).toHaveCount(1);
    await composerStartFresh(page).click();
    await expect(composerFollowLine(page)).toHaveCount(0);
    await expect(page.locator("#query-text"), "dropping the context keeps the typed question").toHaveValue(Q2);
    const body = await seeTheEstimate(page, sent);
    expect(body.query_text).toBe(Q2);
    expect(body.context).toBeUndefined();
    expect(mocked()).toBe(false);
  });

  test("the top-bar brand link clears the context; the typed question stays", async ({ page }) => {
    // RED-IF: going to a new question through a [data-home-link] leaves the context attached (row 13).
    const mocked = forbidRoutes(page);
    const sent = recordRunRequests(page);
    await boot(page);
    await askReal(page, Q1);
    await page.locator("#result-next-input").fill(Q2);
    await page.locator("#result-next-run").click();
    await expect(composerFollowLine(page)).toContainText(Q1);
    await page.locator("header.topbar").getByRole("link", { name: /Quorum/ }).click();
    await expect(composerView(page)).toBeVisible();
    await expect(composerFollowLine(page)).toHaveCount(0);
    const body = await seeTheEstimate(page, sent);
    expect(body.context).toBeUndefined();
    expect(mocked()).toBe(false);
  });

  test("New question clears the context (via the session list back to the result)", async ({ page }) => {
    // RED-IF: the result header's New question leaves an attached context in place (row 13).
    const mocked = forbidRoutes(page);
    const sent = recordRunRequests(page);
    await boot(page);
    await askReal(page, Q1);
    await page.locator("#result-next-input").fill(Q2);
    await page.locator("#result-next-run").click();
    await expect(composerFollowLine(page)).toContainText(Q1);
    // Back to the result through the session list, then New question.
    await trailEntries(page).filter({ hasText: Q1 }).first().click();
    await expect(resultView(page)).toBeVisible();
    await expect(page.locator("#result-question")).toHaveText(Q1);
    await resultView(page).getByRole("button", { name: "New question", exact: true }).click();
    await expect(composerView(page)).toBeVisible();
    await expect(composerFollowLine(page)).toHaveCount(0);
    await page.locator("#query-text").fill(Q3);
    const body = await seeTheEstimate(page, sent);
    expect(body.query_text).toBe(Q3);
    expect(body.context).toBeUndefined();
    expect(mocked()).toBe(false);
  });

  test("an older result re-opened from the session list is the one followed up (row 10)", async ({ page }) => {
    // RED-IF: the context is taken from the latest run rather than the result on screen when Review & run is pressed.
    const mocked = forbidRoutes(page);
    const sent = recordRunRequests(page);
    await boot(page);
    await askReal(page, Q1);
    await resultView(page).getByRole("button", { name: "New question", exact: true }).click();
    await askReal(page, Q2);
    await expect(trailEntries(page)).toHaveCount(2);
    await trailEntries(page).filter({ hasText: Q1 }).first().click();
    await expect(page.locator("#result-question")).toHaveText(Q1);
    await expect(followUpButton(page)).toHaveAttribute("aria-pressed", "true");
    await expect(nextNote(page)).toContainText(followingUpOn(Q1));
    await page.locator("#result-next-input").fill(Q3);
    await page.locator("#result-next-run").click();
    await expect(composerFollowLine(page)).toContainText(Q1);
    await expect(composerFollowLine(page)).not.toContainText(Q2);
    const body = await seeTheEstimate(page, sent);
    expect(body.context?.prior_question).toBe(Q1);
    expect(mocked()).toBe(false);
  });

  test("the previous question is shown as text, never as HTML (row 15)", async ({ page }) => {
    // RED-IF: the note or the composer line sets innerHTML from the question, so <b> becomes an element.
    const mocked = forbidRoutes(page);
    const sent = recordRunRequests(page);
    const hostile = "Is <b>bold</b> faster than <i>plain</i>?";
    await boot(page);
    await askReal(page, hostile);
    // Positive partner: the note does name the question, literally.
    await expect(nextNote(page)).toContainText("Following up on: ");
    await expect(nextNote(page)).toContainText("<b>bold</b>");
    await expect(nextNote(page).locator("b, i")).toHaveCount(0);
    await page.locator("#result-next-input").fill(Q2);
    await page.locator("#result-next-run").click();
    await expect(composerFollowLine(page)).toContainText("<b>bold</b>");
    await expect(composerView(page).locator("b, i")).toHaveCount(0);
    const body = await seeTheEstimate(page, sent);
    expect(body.context?.prior_question).toBe(hostile);
    expect(mocked()).toBe(false);
  });

  test("a quick answer can be followed up: its answer text is the previous answer, and the estimate is a quick one", async ({ page }) => {
    // RED-IF: a quick result shows no mode buttons, or its follow-up sends no context, or not its answer text (rows 11, 12).
    const mocked = forbidRoutes(page);
    const sent = recordRunRequests(page);
    const payloads = recordRunPayloads(page);
    await boot(page);
    await page.locator("#quick-mode-input").check();
    await page.locator("#query-text").fill(Q1);
    await page.locator("#run-now").click();
    const confirm = page.locator("#gate-confirm");
    await expect(page.locator("#result-quick:visible, #gate-confirm:visible").first()).toBeVisible({ timeout: 30000 });
    if (await confirm.isVisible()) await confirm.click();
    await expect(page.locator("#result-quick")).toBeVisible({ timeout: 30000 });
    await expect(page.locator("#result-question")).toHaveText(Q1);

    await expect(followUpButton(page)).toBeVisible();
    await expect(followUpButton(page)).toHaveAttribute("aria-pressed", "true");
    const quickPayload = [...payloads.values()].find((p) => p.mode === "quick" && p.result?.model_answers?.length);
    const answerText = String(quickPayload?.result?.model_answers?.find((a) => a.status === "completed")?.answer_text ?? "").trim();
    expect(answerText.length, "the quick run produced an answer").toBeGreaterThan(0);

    await page.locator("#result-next-input").fill(Q2);
    await page.locator("#result-next-run").click();
    await expect(composerFollowLine(page)).toContainText(Q1);
    const body = await seeTheEstimate(page, sent);
    expect(body.mode).toBe("quick");
    expect(body.context?.prior_question).toBe(Q1);
    expect(body.context?.prior_synthesis ?? "").toContain(answerText.slice(0, 200));
    expect(mocked()).toBe(false);
  });
});

test.describe("W37 — a result with no final answer (mocked, with the reason)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  // The real backend always writes the five sections of a finished panel run,
  // so a result view whose final answer is EMPTY cannot be reached without a
  // mocked payload. The pair below shares one driver: the positive case (a
  // final answer, buttons shown) and the negative one (no final answer, none).
  test("positive partner: a result with a final answer shows both mode buttons", async ({ page }) => {
    // RED-IF: the mode buttons stay hidden on a result that has a final answer (decision 4).
    await driveToResult(page, goldenCompletedResp());
    await expect(followUpButton(page)).toBeVisible();
    await expect(startFreshButton(page)).toBeVisible();
  });

  test("a result whose final answer is empty shows no mode buttons and says the next question is answered on its own", async ({ page }) => {
    // RED-IF: the mode buttons are shown on every result, final answer or not (row 11).
    const resp = goldenCompletedResp() as unknown as {
      result: { final_synthesis: Record<string, unknown> };
    };
    for (const k of ["consensus", "disagreement", "uncertainty", "recommendation", "source_support"]) {
      resp.result.final_synthesis[k] = "";
    }
    resp.result.final_synthesis.status = "failed";
    await driveToResult(page, resp);
    await expect(nextRegion(page)).toBeVisible();
    await expect(page.locator("#result-next-input")).toBeVisible();
    await expect(followUpButton(page)).toBeHidden();
    await expect(startFreshButton(page)).toBeHidden();
    await expect(nextNote(page)).toContainText(/on its own/i);
    await expect(nextNote(page)).not.toContainText(/Following up on/);
  });
});

// ---------------------------------------------------------------------------
// ADR-0143 decision 5 (as reworded after review round 1): which ways back to
// the composer CLEAR the attached context and which KEEP it.
// ---------------------------------------------------------------------------

const errorCard = (page: Page) => page.locator("#error-region");
const cardAction = (page: Page, name: string) => errorCard(page).getByRole("button", { name, exact: true });
const json = (body: unknown, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify(body) });

/** Real Q1 run, then Follow up → Review & run with Q2 typed: the context is attached. */
async function attachFollowUp(page: Page) {
  await boot(page);
  await askReal(page, Q1);
  await page.locator("#result-next-input").fill(Q2);
  await page.locator("#result-next-run").click();
  await expect(composerView(page)).toBeVisible();
  // Positive partner for every "line gone" check below: it is on screen now.
  await expect(composerFollowLine(page)).toHaveCount(1);
  await expect(composerFollowLine(page)).toContainText(Q1);
}

/** After a card action: no Following up line, and the next estimate has no context. */
async function expectContextCleared(page: Page, sent: Sent[]) {
  await expect(composerView(page)).toBeVisible();
  await expect(composerFollowLine(page)).toHaveCount(0);
  await page.locator("#query-text").fill(Q3);
  const body = await seeTheEstimate(page, sent);
  expect(body.query_text).toBe(Q3);
  expect(body.context, "a card action that starts something new sends no context").toBeUndefined();
}

/** After a way BACK to the question: the line is still there and the estimate carries Q1's context. */
async function expectContextKept(page: Page, sent: Sent[]) {
  await expect(composerView(page)).toBeVisible();
  await expect(composerFollowLine(page)).toHaveCount(1);
  await expect(composerFollowLine(page)).toContainText(Q1);
  const body = await seeTheEstimate(page, sent);
  expect(body.context?.prior_question).toBe(Q1);
  expect((body.context?.prior_synthesis ?? "").length).toBeGreaterThan(0);
}

test.describe("W37 — card actions clear the context; ways back keep it (decision 5)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  test("a failed follow-up run: Start a new run clears the context (mocked failed poll)", async ({ page }) => {
    // RED-IF: the provider-failure card's "Start a new run" (returnToComposer) leaves the follow-up context attached.
    // Mocked poll only: the real LOCAL failure phrase ("force provider failure")
    // ends the run "partial", never "failed" (measured on b67922a: "4 stages
    // failed · 3 missing", list entry "partial"), and only a "failed" run gets
    // this card. The create is real, so its body is the page's own.
    const sent = recordRunRequests(page);
    await attachFollowUp(page);
    await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => {
      if (r.request().method() !== "GET") return r.continue();
      const id = new URL(r.request().url()).pathname.split("/").pop();
      const golden = goldenCompletedResp();
      return r.fulfill(
        json({
          ...golden,
          query_run_id: id,
          status: "failed",
          failed_steps: ["initial_answers"],
          missing_steps: ["debate_round_1", "debate_round_2", "synthesis"],
          provider_failure_notices: ["The model provider returned an error."],
          result: { ...golden.result, final_synthesis: null },
        }),
      );
    });
    await page.locator("#estimate-run").click();
    await expect(page.locator("#gate-confirm")).toBeVisible({ timeout: 15000 });
    await page.locator("#gate-confirm").click();
    await expect(cardAction(page, "Start a new run")).toBeVisible({ timeout: 30000 });
    const create = lastOf(sent, "create");
    expect(create?.body.context?.prior_question, "the failed run was a follow-up").toBe(Q1);
    await cardAction(page, "Start a new run").click();
    await expectContextCleared(page, sent);
  });

  test("one run at a time: Stop it & start new clears the context (mocked 409)", async ({ page }) => {
    // RED-IF: the busy card's "Stop it & start new" (stopActiveRunAndCompose → returnToComposer) leaves the context attached.
    // Mocked: a simulated run finishes in tens of milliseconds, so the real
    // backend never has a run still active when the next create arrives.
    const sent = recordRunRequests(page);
    await attachFollowUp(page);
    await page.route(/\/v1\/query-runs$/, (r) =>
      r.request().method() === "POST"
        ? r.fulfill(json({ detail: { code: "ACTIVE_QUERY_EXISTS", message: "A query is already running." } }, 409))
        : r.continue(),
    );
    await page.locator("#run-now").click();
    await expect(cardAction(page, "Stop it & start new")).toBeVisible({ timeout: 15000 });
    await cardAction(page, "Stop it & start new").click();
    await expectContextCleared(page, sent);
  });

  test("a run this session cannot open: Start your own query clears the context (mocked 404)", async ({ page }) => {
    // RED-IF: the wrong-session card's "Start your own query" (returnToComposer) leaves the context attached.
    // Mocked: the real backend answers QUERY_RUN_NOT_FOUND only for a run of
    // another session (or one gone from memory); here the session list's own
    // entry is answered 404 so the page shows that card.
    const sent = recordRunRequests(page);
    await attachFollowUp(page);
    await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) =>
      r.request().method() === "GET"
        ? r.fulfill(json({ detail: { code: "QUERY_RUN_NOT_FOUND", message: "Query run not found." } }, 404))
        : r.continue(),
    );
    await trailEntries(page).filter({ hasText: Q1 }).first().click();
    await expect(cardAction(page, "Start your own query")).toBeVisible({ timeout: 15000 });
    await cardAction(page, "Start your own query").click();
    await expectContextCleared(page, sent);
  });

  test("a create refused for the daily allowance: Back to the question KEEPS the context (mocked 402)", async ({ page }) => {
    // RED-IF: "Back to the question" clears the context it should keep (decision 5: a way back to the question being worked on).
    // Mocked: reaching the allowance for real takes about four simulated runs,
    // and the estimate would then block before the create is ever sent.
    const sent = recordRunRequests(page);
    await attachFollowUp(page);
    await page.route(/\/v1\/query-runs$/, (r) =>
      r.request().method() === "POST"
        ? r.fulfill(
            json(
              {
                detail: {
                  code: "COST_LIMIT_EXCEEDED",
                  message: "Daily allowance used.",
                  block_reason: "daily_cap",
                  daily_allowance: { cap_usd: "0.40", spent_usd: "0.40", remaining_usd: "0.00" },
                },
              },
              402,
            ),
          )
        : r.continue(),
    );
    await page.locator("#estimate-run").click();
    await expect(page.locator("#gate-confirm")).toBeVisible({ timeout: 15000 });
    await page.locator("#gate-confirm").click();
    await expect(cardAction(page, "Back to the question")).toBeVisible({ timeout: 15000 });
    await cardAction(page, "Back to the question").click();
    await expectContextKept(page, sent);
  });

  test("the cost confirmation's Back, then browser Back and Forward, KEEP the context", async ({ page }) => {
    // RED-IF: gateBackToComposer or the popstate handler clears the context (decision 5: ways back keep it).
    const mocked = forbidRoutes(page);
    const sent = recordRunRequests(page);
    await attachFollowUp(page);
    await page.locator("#estimate-run").click();
    await expect(page.locator("#gate-back")).toBeVisible({ timeout: 15000 });
    await page.locator("#gate-back").click();
    await expectContextKept(page, sent);
    await page.locator("#gate-back").click();
    // Browser Back to the result, then Forward to the composer.
    await page.goBack();
    await expect(resultView(page)).toBeVisible();
    await expect(page.locator("#result-question")).toHaveText(Q1);
    await page.goForward();
    await expectContextKept(page, sent);
    expect(mocked()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Product review of 83a1d62 (items 6-9 of the review-round-1 test job).
// ---------------------------------------------------------------------------

const costGateView = (page: Page) => page.locator('[data-view="cost-gate"]');
const gateFollowLine = (page: Page) => costGateView(page).getByText(/Following up on: /).filter({ visible: true });
const OWNER_FOOTER =
  "See the estimate to check the cost first, or Run now to start straight away. If a run costs more than usual, it asks you first.";

test.describe("W37 — product review: re-opened results, the cost confirmation, the footer, one model", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  test("re-opening an older result from the session list empties the box and offers to follow up THAT result", async ({ page }) => {
    // RED-IF: restoreTrailRun leaves text typed for another result in #result-next-input, so Review & run sends Q1 as context with a question typed to be fresh.
    const mocked = forbidRoutes(page);
    const sent = recordRunRequests(page);
    const typedFresh = "A fresh question about caching layers?";
    await boot(page);
    await askReal(page, Q1);
    await resultView(page).getByRole("button", { name: "New question", exact: true }).click();
    await askReal(page, Q2);
    await startFreshButton(page).click();
    await page.locator("#result-next-input").fill(typedFresh);
    await page.locator("#result-next-run").click();
    await expect(page.locator("#query-text")).toHaveValue(typedFresh);
    await seeTheEstimate(page, sent);
    await page.locator("#gate-back").click();
    await expect(composerView(page)).toBeVisible();
    // Open Q1 from the session list.
    await trailEntries(page).filter({ hasText: Q1 }).first().click();
    await expect(page.locator("#result-question")).toHaveText(Q1);
    // Positive partners: the box and the offer are on screen, for Q1.
    await expect(page.locator("#result-next-input")).toBeVisible();
    await expect(followUpButton(page)).toHaveAttribute("aria-pressed", "true");
    await expect(nextNote(page)).toContainText(followingUpOn(Q1));
    await expect(page.locator("#result-next-input"), "the box must open empty on a re-opened result").toHaveValue("");
    expect(mocked()).toBe(false);
  });

  test("the cost confirmation says the question is a follow-up, and only when it is", async ({ page }) => {
    // RED-IF: the estimate review screen shows no "Following up on: " line (with the previous question, as text) while context is attached, or shows one when none is.
    const mocked = forbidRoutes(page);
    const sent = recordRunRequests(page);
    const hostile = "Is <b>bold</b> faster than plain?";
    await boot(page);
    await askReal(page, hostile);
    await page.locator("#result-next-input").fill(Q2);
    await page.locator("#result-next-run").click();
    const attached = await seeTheEstimate(page, sent);
    expect(attached.context?.prior_question).toBe(hostile);
    await expect(costGateView(page)).toBeVisible();
    await expect(page.locator("#cost-gate-question")).toHaveText(Q2);
    await expect(gateFollowLine(page)).toHaveCount(1);
    await expect(gateFollowLine(page)).toContainText("<b>bold</b>");
    await expect(costGateView(page).locator("b")).toHaveCount(0);
    // Without context: no such line.
    await page.locator("#gate-back").click();
    await composerStartFresh(page).click();
    const fresh = await seeTheEstimate(page, sent);
    expect(fresh.context).toBeUndefined();
    await expect(costGateView(page)).toBeVisible();
    await expect(page.locator("#cost-gate-question")).toHaveText(Q2);
    await expect(gateFollowLine(page)).toHaveCount(0);
    expect(mocked()).toBe(false);
  });

  test("the composer footer uses the owner's wording for the two buttons (CHG-027 d)", async ({ page }) => {
    // RED-IF: .composer-footer-notice still reads "…to review the itemized cost first, or Run now to start low-cost runs immediately — anything needing confirmation still pauses…".
    await boot(page);
    const footer = composerView(page).locator(".composer-footer-notice");
    await expect(footer).toBeVisible();
    await expect(footer).toContainText(OWNER_FOOTER);
    await expect(footer).not.toContainText("start low-cost runs immediately");
    await expect(footer).not.toContainText("still pauses for your approval");
  });

  test("with one model (quick) the note and the composer line say the model, singular; a panel says the models", async ({ page }) => {
    // RED-IF: the follow-up note or the composer line says "the models will see…" for a quick answer's one model (or loses the plural on a panel).
    const mocked = forbidRoutes(page);
    await boot(page);
    // Panel: plural (positive partner for the singular checks below).
    await askReal(page, Q1);
    await expect(nextNote(page)).toContainText(/\bthe models\b/);
    // Quick: singular.
    await resultView(page).getByRole("button", { name: "New question", exact: true }).click();
    await page.locator("#quick-mode-input").check();
    await page.locator("#query-text").fill(Q2);
    await page.locator("#run-now").click();
    await expect(page.locator("#result-quick:visible, #gate-confirm:visible").first()).toBeVisible({ timeout: 30000 });
    if (await page.locator("#gate-confirm").isVisible()) await page.locator("#gate-confirm").click();
    await expect(page.locator("#result-quick")).toBeVisible({ timeout: 30000 });
    await expect(nextNote(page)).toContainText(followingUpOn(Q2));
    await expect(nextNote(page)).toContainText(/\bthe model\b/);
    await expect(nextNote(page)).not.toContainText(/\bthe models\b/);
    await page.locator("#result-next-input").fill(Q3);
    await page.locator("#result-next-run").click();
    await expect(composerFollowLine(page)).toContainText(Q2);
    await expect(composerFollowLine(page)).toContainText(/\bthe model\b/);
    await expect(composerFollowLine(page)).not.toContainText(/\bthe models\b/);
    expect(mocked()).toBe(false);
  });
});
