// W127 (board rows W127 and W49): one run scope for the workspace.
//
// The workspace is one page, so every view region survives between runs unless
// something clears it, and today no answer is checked against the run it was
// asked for. The contract these tests fix (the work item's plan, revision 2):
//
// * `<html data-run-id>` names the run the visible run view belongs to; it is
//   absent on the composer, the cost confirmation and the landing.
// * every run-scoped region in workspace.html carries `data-run-scope`, and the
//   renderer that fills it sets `data-run-id` to the run it was given.
// * `assertNoForeignRunContent(page)` below checks, after EVERY transition,
//   that every visible run-scoped region with text belongs to that run, that a
//   run view has at least one such region (the positive partner), and that the
//   composer and the landing have none.
//
// Every route is stubbed: these are states the real simulated backend cannot
// reach on demand (it finishes a run in tens of milliseconds, so a Stop, a slow
// poll or an answer arriving late cannot be timed against it). Each case runs
// at 1440 px and at 390 px.
//
// The invariant check is SOFT (`expect.soft`), so a test goes on to its own
// visible symptom and a red run reports both; both still fail the test.
import { test, expect, Page, Route, Request } from "@playwright/test";
import {
  boot,
  goldenCompletedResp,
  goldenCreateResp,
  goldenQuickCreateResp,
  goldenQuickResp,
  goldenQuickRunningResp,
  goldenRespWithPeerDebate,
  goldenRunningResp,
  quickEstimateEnvelope,
  withRunId,
  SLOTS,
} from "../../fixtures/golden-run";

const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
];

const Q1 = "What are the key metrics for measuring SaaS customer retention?";
const Q2 = "What is the capital of Australia and why was it chosen?";
const Q3 = "Which European city has the most museums per person?";

const RUN_A = "aaaaaaaa-0000-4000-8000-00000000000a";
const RUN_B = "bbbbbbbb-0000-4000-8000-00000000000b";
const RUN_C = "cccccccc-0000-4000-8000-00000000000c";

const json = (body: unknown, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify(body) });

const panelEstimate = () => ({
  correlation_id: "corr-scope-est",
  cost_estimate: goldenCreateResp().cost_estimate,
  model_slots: SLOTS,
  reasons: [],
});

const panelCreate = (id: string) => withRunId(goldenCreateResp(), id);
const quickCreate = (id: string) => withRunId(goldenQuickCreateResp(), id);
const panelRunning = (id: string) => withRunId(goldenRunningResp(2000), id);
const panelDone = (id: string) => withRunId(goldenCompletedResp(), id);
const quickRunning = (id: string) => withRunId(goldenQuickRunningResp(), id);
const quickDone = (id: string) => withRunId(goldenQuickResp(), id);
const withStatus = (resp: unknown, status: string) => ({ ...(resp as Record<string, unknown>), status });
const panelFailed = (id: string) => {
  const golden = goldenCompletedResp();
  return withRunId(
    {
      ...golden,
      status: "failed",
      failed_steps: ["initial_answers"],
      missing_steps: ["debate_round_1", "debate_round_2", "synthesis"],
      provider_failure_notices: ["The model provider returned an error."],
      result: { ...golden.result, final_synthesis: null },
    },
    id,
  );
};
const simulatedDone = (id: string) =>
  withRunId({ ...goldenCompletedResp(), demo_mode: true, live_count: 0, local_count: 4 }, id);
const activeRun = (id: string | null) =>
  id
    ? {
        query_run_id: id,
        status: "initial_answers_running",
        correlation_id: `corr-${id.slice(0, 8)}`,
        progress: null,
        model_slots: SLOTS,
        cost_estimate: null,
        initial_answers: [],
        mode: "panel",
      }
    : { query_run_id: null };
const BUSY = { detail: { code: "ACTIVE_QUERY_EXISTS", message: "A query is already running." } };
const BOOM = { error: { code: "INTERNAL_ERROR", message: "boom" } };

// ---- one stubbed server per test ------------------------------------------

type Handler = (route: Route, n: number) => Promise<void> | void;
interface Fake {
  /** The estimate route; the default prices a panel or a quick body. */
  estimate: Handler;
  /** The create route, by how many creates have been sent. */
  create: (n: number) => { status?: number; body: unknown };
  /** GET /v1/query-runs/{id}, by run id and how many GETs that id has had. */
  get: Record<string, Handler>;
  /** DELETE /v1/query-runs/{id}. */
  del: Record<string, Handler>;
  active: () => unknown;
  sent: { method: string; tail: string; body: Record<string, unknown> }[];
  count: (method: string, tail: string) => number;
}

async function installFake(page: Page): Promise<Fake> {
  const counts = new Map<string, number>();
  const next = (key: string) => {
    const n = (counts.get(key) ?? 0) + 1;
    counts.set(key, n);
    return n;
  };
  const fake: Fake = {
    estimate: (route) => {
      const body = JSON.parse(route.request().postData() || "{}");
      return route.fulfill(json(body.mode === "quick" ? quickEstimateEnvelope() : panelEstimate()));
    },
    create: () => ({ body: panelCreate(RUN_A) }),
    get: {},
    del: {},
    active: () => activeRun(null),
    sent: [],
    count: (method, tail) => fake.sent.filter((s) => s.method === method && s.tail === tail).length,
  };
  await page.route(/\/v1\/query-runs(\/[^/?#]+)?(\?[^#]*)?$/, async (route) => {
    const req = route.request();
    const tail = new URL(req.url()).pathname.replace(/^\/v1\/query-runs/, "");
    const method = req.method();
    fake.sent.push({ method, tail, body: JSON.parse(req.postData() || "{}") });
    if (tail === "") {
      if (method !== "POST") return route.continue();
      const answer = fake.create(next("create"));
      return route.fulfill(json(answer.body, answer.status ?? 200));
    }
    if (tail === "/estimate") return fake.estimate(route, next("estimate"));
    if (tail === "/warnings") return route.fulfill(json({ warnings: [] }));
    if (tail === "/active") return route.fulfill(json(fake.active()));
    const id = tail.slice(1);
    if (!/^[0-9a-f-]{36}$/.test(id)) return route.continue();
    const table = method === "GET" ? fake.get : method === "DELETE" ? fake.del : null;
    const handler = table && table[id];
    if (!handler) return route.continue();
    return handler(route, next(`${method} ${id}`));
  });
  return fake;
}

/** A request held open by a route handler, released by the test. */
function holder() {
  let ready!: () => void;
  const isReady = new Promise<void>((resolve) => (ready = resolve));
  const box: { route: Route | null; ready: Promise<void>; take: (route: Route) => void } = {
    route: null,
    ready: isReady,
    take(route) {
      box.route = route;
      ready();
    },
  };
  return box;
}

/** Answer a held request, then give the page time to process the answer. */
async function deliver(page: Page, held: { route: Route | null }, body: unknown, status = 200) {
  const route = held.route as Route;
  const request: Request = route.request();
  const delivered = page.waitForResponse((r) => r.request() === request);
  await route.fulfill(json(body, status));
  await delivered;
  // A negative check over time: the page has the answer, so 600 ms is several
  // event-loop turns for a handler that would render it.
  await page.waitForTimeout(600);
}

async function deliverFailure(page: Page, held: { route: Route | null }) {
  const route = held.route as Route;
  const request: Request = route.request();
  const failed = page.waitForEvent("requestfailed", (r) => r === request);
  await route.abort("failed");
  await failed;
  await page.waitForTimeout(600);
}

// ---- what the page showed ---------------------------------------------------

type Toast = { text: string; classes: string[] };

/** Every toast the page ever raised, in order (they expire after a few seconds). */
async function recordToasts(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __toasts: { text: string; classes: string[] }[] };
    w.__toasts = [];
    new MutationObserver((mutations) => {
      for (const m of mutations) {
        for (const node of Array.from(m.addedNodes)) {
          if (node instanceof HTMLElement && node.classList.contains("toast")) {
            w.__toasts.push({
              text: (node.querySelector(".toast-body")?.textContent || "").trim(),
              classes: Array.from(node.classList),
            });
          }
        }
      }
    }).observe(document, { childList: true, subtree: true });
  });
}
const toastTexts = async (page: Page) =>
  (await page.evaluate(() => (window as unknown as { __toasts: Toast[] }).__toasts)).map((t) => t.text);
const toastList = (page: Page) => page.evaluate(() => (window as unknown as { __toasts: Toast[] }).__toasts);

const RUN_VIEWS = new Set(["live-run", "result", "transcript"]);

/**
 * The run-scope invariant. Returns the page's `<html data-run-id>` so a test
 * can also say WHICH run that must be.
 */
async function assertNoForeignRunContent(page: Page, step: string): Promise<string | null> {
  const seen = await page.evaluate(() => {
    const htmlRunId = document.documentElement.dataset.runId ?? null;
    // The view on screen: the one `[data-view]` setView has not hidden.
    const open = Array.from(document.querySelectorAll<HTMLElement>("[data-view]")).filter((v) => !v.hidden);
    const view = open.length === 1 ? (open[0].dataset.view ?? null) : null;
    const shown = (node: HTMLElement) =>
      node.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) && node.getClientRects().length > 0;
    const regions = Array.from(document.querySelectorAll<HTMLElement>("[data-run-scope]")).filter(
      (node) => shown(node) && (node.innerText || "").trim() !== "",
    );
    const foreign = regions
      .filter((node) => !htmlRunId || node.dataset.runId !== htmlRunId)
      .map((node) => `${node.id ? `#${node.id}` : `.${node.className}`} data-run-id=${node.dataset.runId ?? "(none)"}`);
    return { htmlRunId, view, regions: regions.length, foreign };
  });
  // Positive partner for the view itself: exactly one view is on screen.
  expect(seen.view, `${step}: exactly one [data-view] is shown`).not.toBeNull();
  if (RUN_VIEWS.has(seen.view as string)) {
    expect.soft(seen.htmlRunId, `${step}: <html data-run-id> on the ${seen.view} view`).not.toBeNull();
    expect.soft(seen.regions, `${step}: visible run-scoped regions with text on the ${seen.view} view`).toBeGreaterThan(0);
    expect.soft(seen.foreign, `${step}: regions from another run (page run ${seen.htmlRunId})`).toEqual([]);
  } else {
    expect.soft(seen.htmlRunId, `${step}: <html data-run-id> on the ${seen.view} view`).toBeNull();
    expect.soft(seen.regions, `${step}: visible run-scoped regions on the ${seen.view} view`).toBe(0);
  }
  return seen.htmlRunId;
}

const view = (page: Page, name: string) => page.locator(`[data-view="${name}"]`);
const total = (page: Page) => page.locator("#composer-total-estimate");
const trailEntry = (page: Page, runId: string) => page.locator(`.session-trail-entry[data-trail-run-id="${runId}"]`);
const errorCardAction = (page: Page, name: string) =>
  page.locator("#error-region").getByRole("button", { name, exact: true });

async function ask(page: Page, question: string, quick = false) {
  const box = page.locator("#quick-mode-input");
  if (quick) await box.check();
  else await box.uncheck();
  await page.locator("#query-text").fill(question);
  await page.locator("#run-now").click();
}

async function onPanelResult(page: Page, question: string) {
  await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
  await expect(page.locator("#result-question")).toHaveText(question);
}

async function newQuestionFromResult(page: Page) {
  await page.locator("#result-new-question").click();
  await expect(view(page, "composer")).toBeVisible();
}

for (const viewport of VIEWPORTS) {
  test.describe(`W127 one run scope at ${viewport.width} px`, () => {
    test.skip(({ browserName }) => browserName !== "chromium", "chromium-only gate");
    test.use({ viewport });

    test("(a) a quick run after a debate shows none of the debate's round cards", async ({ page }) => {
      // Red when: `.live-debate[hidden] { display: none; }` is removed from app.css (the display check below), or the debate host is never emptied before a quick run: beginRunScope's emptying, renderLiveDebate's quick-path emptying and that rule all removed (the round-card count).
      const fake = await installFake(page);
      fake.create = (n) => ({ body: n === 1 ? panelCreate(RUN_A) : quickCreate(RUN_B) });
      fake.get[RUN_A] = (route) => route.fulfill(json(panelDone(RUN_A)));
      fake.get[RUN_B] = (route) => route.fulfill(json(quickRunning(RUN_B)));
      await boot(page);
      await assertNoForeignRunContent(page, "composer at boot");
      await ask(page, Q1);
      await onPanelResult(page, Q1);
      expect.soft(await assertNoForeignRunContent(page, "panel result"), "the result is run A's").toBe(RUN_A);
      // Positive partner: the debate run DID leave round cards in the live view.
      expect(await page.locator("#live-debate .live-round-card").count()).toBeGreaterThan(0);

      await newQuestionFromResult(page);
      await assertNoForeignRunContent(page, "composer after New question");
      await ask(page, Q2, true);
      await expect(view(page, "live-run")).toBeVisible({ timeout: 15000 });
      await expect(page.locator("#live-query")).toHaveText(Q2);
      await expect(page.locator("#live-stage-strip .live-stage")).toHaveCount(1);
      expect.soft(await assertNoForeignRunContent(page, "quick live run"), "the live view is run B's").toBe(RUN_B);
      await expect(page.locator("#live-debate .live-round-card").filter({ visible: true })).toHaveCount(0);
      // The quick run hides the debate host, and hidden must mean not displayed:
      // `.live-debate` sets `display: flex`, which the `hidden` attribute alone loses to.
      const debate = await page
        .locator("#live-debate")
        .evaluate((node) => ({ hidden: (node as HTMLElement).hidden, display: getComputedStyle(node).display }));
      expect(debate.hidden, "the quick run hides the debate host").toBe(true);
      expect(debate.display, "a hidden #live-debate is not displayed").toBe("none");
    });

    test("(b) the composer total reads — whenever the question, panel or mode differs from the priced one", async ({ page }) => {
      // Red when: #composer-total-estimate is written once by estimateRun and reset only by holdForHighStakesAck, instead of being derived from the current inputs against the priced ones.
      await installFake(page);
      await boot(page);
      await page.locator("#query-text").fill(Q1);
      await page.locator("#estimate-run").click();
      await expect(view(page, "cost-gate")).toBeVisible({ timeout: 15000 });
      await assertNoForeignRunContent(page, "cost gate");
      await page.locator("#gate-back").click();
      await expect(view(page, "composer")).toBeVisible();
      // Positive partner: for the priced inputs the total is an amount.
      await expect(total(page)).toHaveText(/^\$\d/);
      const priced = (await total(page).textContent()) as string;
      await assertNoForeignRunContent(page, "composer, priced");

      await page.locator("#query-text").fill(`${Q1} And churn?`);
      await expect(total(page), "after editing the question").toHaveText("—");
      await assertNoForeignRunContent(page, "composer, question edited");
      await page.locator("#query-text").fill(Q1);
      await expect(total(page), "the priced question again (the total is derived, not stored)").toHaveText(priced);

      const slot2 = page.locator("#model-2");
      const original = await slot2.inputValue();
      const other = await slot2.evaluate(
        (select, current) => Array.from((select as HTMLSelectElement).options).map((o) => o.value).find((v) => v && v !== current) ?? "",
        original,
      );
      expect(other, "slot 2 offers another model").not.toEqual("");
      await slot2.selectOption(other);
      await expect(total(page), "after swapping a model").toHaveText("—");
      await page.locator("#model-2").selectOption(original);
      await expect(total(page), "the priced panel again").toHaveText(priced);

      await page.locator("#quick-mode-input").check();
      await expect(total(page), "after switching Quick answer on").toHaveText("—");
      await page.locator("#quick-mode-input").uncheck();
      await expect(total(page), "the priced mode again").toHaveText(priced);

      await page.locator("#model-inputs .model-slot-remove").nth(3).click();
      await expect(page.locator("#model-inputs .model-slot")).toHaveCount(3);
      await expect(total(page), "after removing a model").toHaveText("—");
      await assertNoForeignRunContent(page, "composer, three models");
    });

    test("(b) New question from a result shows the total as —", async ({ page }) => {
      // Red when: goToNewQuestion leaves #composer-total-estimate holding the finished run's estimate.
      const fake = await installFake(page);
      fake.get[RUN_A] = (route) => route.fulfill(json(panelDone(RUN_A)));
      await boot(page);
      await ask(page, Q1);
      await onPanelResult(page, Q1);
      await assertNoForeignRunContent(page, "panel result");
      // Positive partner: the run's estimate did write an amount into the total.
      expect(await total(page).textContent()).toMatch(/^\$\d/);
      await newQuestionFromResult(page);
      await assertNoForeignRunContent(page, "composer after New question");
      await expect(page.locator("#query-text")).toHaveValue("");
      await expect(total(page)).toHaveText("—");
    });

    test("(b) dropping the follow-up context shows the total as —", async ({ page }) => {
      // Red when: the follow-up context is not part of the priced inputs, so "Start fresh" leaves the follow-up's price in #composer-total-estimate.
      const fake = await installFake(page);
      fake.get[RUN_A] = (route) => route.fulfill(json(panelDone(RUN_A)));
      await boot(page);
      await ask(page, Q1);
      await onPanelResult(page, Q1);
      await page.locator("#result-next-input").fill(Q2);
      await page.locator("#result-next-run").click();
      await expect(view(page, "composer")).toBeVisible();
      // Positive partner: the context is attached, and priced.
      await expect(page.locator("#follow-up-context")).toBeVisible();
      await page.locator("#estimate-run").click();
      await expect(view(page, "cost-gate")).toBeVisible({ timeout: 15000 });
      const estimate = fake.sent.filter((s) => s.tail === "/estimate").pop();
      expect(estimate?.body.context, "the follow-up was priced with its context").toBeTruthy();
      await page.locator("#gate-back").click();
      await expect(total(page)).toHaveText(/^\$\d/);
      await assertNoForeignRunContent(page, "composer with the context");
      await page.locator("#follow-up-context-drop").click();
      await expect(page.locator("#follow-up-context")).toBeHidden();
      await expect(total(page)).toHaveText("—");
      await assertNoForeignRunContent(page, "composer, context dropped");
    });

    test("(b) a model swapped while the estimate loads never shows the priced panel's per-model rows", async ({ page }) => {
      // Red when: estimateRun maps the late estimate's by_model rows by position onto getModelIds() as it is when the answer arrives, and the per-slot cells are not derived from the priced inputs.
      const fake = await installFake(page);
      const rows = ["0.777", "0.666", "0.555", "0.444"];
      const rowEstimate = () => {
        const ce = goldenCreateResp().cost_estimate as Record<string, any>;
        return {
          ...panelEstimate(),
          cost_estimate: {
            ...ce,
            breakdown: {
              ...ce.breakdown,
              by_model: [
                ...SLOTS.map((s, i) => ({ model_id: s.model_id, display_name: s.display_label, usd: rows[i], kind: "model" })),
                { model_id: "synthesis", display_name: "Synthesis", usd: "0.024", kind: "synthesis" },
              ],
            },
          },
        };
      };
      const held = holder();
      fake.estimate = (route, n) => (n === 1 ? route.fulfill(json(rowEstimate())) : held.take(route));
      await boot(page);
      const cells = page.locator("#model-inputs .model-slot-estimate");
      await page.locator("#query-text").fill(Q1);
      await page.locator("#estimate-run").click();
      await expect(view(page, "cost-gate")).toBeVisible({ timeout: 15000 });
      await page.locator("#gate-back").click();
      // Positive partner: on the priced panel the cells are the server's rows.
      await expect(cells).toHaveText(["~$0.777", "~$0.666", "~$0.555", "~$0.444"]);

      await page.locator("#estimate-run").click();
      await held.ready;
      const slot2 = page.locator("#model-2");
      const original = await slot2.inputValue();
      const other = await slot2.evaluate(
        (select, current) => Array.from((select as HTMLSelectElement).options).map((o) => o.value).find((v) => v && v !== current) ?? "",
        original,
      );
      await slot2.selectOption(other);
      await deliver(page, held, rowEstimate());
      await expect(view(page, "cost-gate")).toBeVisible({ timeout: 15000 });
      await page.locator("#gate-back").click();
      await expect(view(page, "composer")).toBeVisible();
      await expect(page.locator("#model-2")).toHaveValue(other);
      const shown = await cells.allTextContents();
      expect(shown, "no cell shows a row priced for another panel").toEqual(
        shown.map((t) => (["~$0.777", "~$0.666", "~$0.555", "~$0.444"].includes(t) ? "(not a priced row)" : t)),
      );
      await expect(total(page)).toHaveText("—");
      await assertNoForeignRunContent(page, "composer, panel changed while priced");
    });

    test("(c) Stop answered by an already-completed quick run opens its answer, never 'Run cancelled.'", async ({ page }) => {
      // Red when: cancelRun toasts "Run cancelled." whatever the DELETE returned and opens a result only when final_synthesis exists, instead of calling finishRun(result, scope).
      await recordToasts(page);
      const fake = await installFake(page);
      fake.create = () => ({ body: quickCreate(RUN_B) });
      fake.get[RUN_B] = (route) => route.fulfill(json(quickRunning(RUN_B)));
      fake.del[RUN_B] = (route) => route.fulfill(json(quickDone(RUN_B)));
      await boot(page);
      await ask(page, Q2, true);
      await expect(view(page, "live-run")).toBeVisible({ timeout: 15000 });
      await assertNoForeignRunContent(page, "quick live run");
      await page.locator("#live-stop").click();
      await expect.poll(() => fake.count("DELETE", `/${RUN_B}`)).toBe(1);
      await expect(page.locator('#result-quick[data-mode="quick"]')).toBeVisible({ timeout: 10000 });
      expect.soft(await assertNoForeignRunContent(page, "quick result after Stop"), "the result is run B's").toBe(RUN_B);
      await expect.poll(() => toastTexts(page)).toContain("Run completed. See the answer below.");
      expect(await toastTexts(page)).not.toContain("Run cancelled.");
      await expect(trailEntry(page, RUN_B)).toHaveCount(1);
    });

    test("Stop answered 'cancelled' says 'Run cancelled.' once and lists the run", async ({ page }) => {
      // Red when: cancelRun writes no session-list entry (only pollRun's terminal branch calls appendSessionTrailEntry).
      await recordToasts(page);
      const fake = await installFake(page);
      fake.create = () => ({ body: panelCreate(RUN_A) });
      fake.get[RUN_A] = (route) => route.fulfill(json(panelRunning(RUN_A)));
      fake.del[RUN_A] = (route) => route.fulfill(json(withStatus(panelRunning(RUN_A), "cancelled")));
      await boot(page);
      await ask(page, Q1);
      await expect(view(page, "live-run")).toBeVisible({ timeout: 15000 });
      await page.locator("#live-stop").click();
      await expect(page.locator("#live-status-text")).toHaveText("Cancelled");
      await expect(page.locator("#live-stop")).toBeHidden();
      await expect(page.locator("#live-new-question")).toBeVisible();
      expect.soft(await assertNoForeignRunContent(page, "cancelled live run"), "the live view is run A's").toBe(RUN_A);
      await expect.poll(() => toastTexts(page)).toContain("Run cancelled.");
      await page.waitForTimeout(1600); // two poll intervals: a second toast would have come by now
      expect((await toastTexts(page)).filter((t) => t === "Run cancelled.")).toHaveLength(1);
      await expect(trailEntry(page, RUN_A)).toHaveCount(1);
    });

    test("a failed Stop gives Stop back, and a second Stop works", async ({ page }) => {
      // Red when: cancelRun disables only the hidden aside button, so #live-stop stays enabled while the DELETE is in flight (and two clicks send two DELETEs).
      await recordToasts(page);
      const fake = await installFake(page);
      fake.create = () => ({ body: panelCreate(RUN_A) });
      fake.get[RUN_A] = (route) => route.fulfill(json(panelRunning(RUN_A)));
      const held = holder();
      fake.del[RUN_A] = (route, n) =>
        n === 1 ? held.take(route) : route.fulfill(json(withStatus(panelRunning(RUN_A), "cancelled")));
      await boot(page);
      await ask(page, Q1);
      await expect(view(page, "live-run")).toBeVisible({ timeout: 15000 });
      const stop = page.locator("#live-stop");
      await stop.click();
      await held.ready;
      await expect(stop, "Stop while its DELETE is in flight").toBeDisabled();
      await assertNoForeignRunContent(page, "stopping");
      await deliver(page, held, BOOM, 500);
      // Positive partner: the failure is shown.
      await expect(page.locator("#error-region")).toBeVisible();
      await expect(stop).toBeVisible();
      await expect(stop).toBeEnabled();
      await assertNoForeignRunContent(page, "after the failed Stop");
      await stop.click();
      await expect(page.locator("#live-status-text")).toHaveText("Cancelled");
      expect(fake.count("DELETE", `/${RUN_A}`)).toBe(2);
      await expect.poll(() => toastTexts(page)).toContain("Run cancelled.");
    });

    test("a late answer for an earlier run never reaches the run on screen", async ({ page }) => {
      // Red when: pollRun renders and finishes whatever answer arrives, with no check that it belongs to state.runScope's run.
      await recordToasts(page);
      const fake = await installFake(page);
      fake.create = (n) => ({ body: n === 1 ? panelCreate(RUN_A) : quickCreate(RUN_B) });
      const held = holder();
      fake.get[RUN_A] = (route, n) => (n === 2 ? held.take(route) : route.fulfill(json(panelRunning(RUN_A))));
      fake.del[RUN_A] = (route) => route.fulfill(json(withStatus(panelRunning(RUN_A), "cancelled")));
      fake.get[RUN_B] = (route) => route.fulfill(json(quickRunning(RUN_B)));
      await boot(page);
      await ask(page, Q1);
      await expect(view(page, "live-run")).toBeVisible({ timeout: 15000 });
      await held.ready;
      await page.locator("#live-stop").click();
      await expect(page.locator("#live-new-question")).toBeVisible();
      await page.locator("#live-new-question").click();
      await expect(view(page, "composer")).toBeVisible();
      await assertNoForeignRunContent(page, "composer after Stop");
      await ask(page, Q2, true);
      await expect(view(page, "live-run")).toBeVisible({ timeout: 15000 });
      await expect(page.locator("#live-query")).toHaveText(Q2);
      expect.soft(await assertNoForeignRunContent(page, "run B live"), "the live view is run B's").toBe(RUN_B);

      const pollsOfB = fake.count("GET", `/${RUN_B}`);
      await deliver(page, held, panelDone(RUN_A));
      await expect(view(page, "live-run"), "run B's live view stays on screen").toBeVisible();
      await expect(view(page, "result")).toBeHidden();
      await expect(page.locator("#live-query")).toHaveText(Q2);
      // Positive partner: run B is still being watched.
      await expect.poll(() => fake.count("GET", `/${RUN_B}`), { timeout: 5000 }).toBeGreaterThan(pollsOfB + 1);
      expect(await toastTexts(page)).not.toContain("Run completed. See the synthesis below.");
      expect.soft(await assertNoForeignRunContent(page, "run B after A's late answer"), "still run B").toBe(RUN_B);
    });

    test("a poll answered 'running' after Stop does not bring the run back", async ({ page }) => {
      // Red when: pollRun renders an answer that arrives after Stop closed the scope (renderLiveRun shows Stop again and hides New question).
      const fake = await installFake(page);
      fake.create = () => ({ body: panelCreate(RUN_A) });
      const held = holder();
      fake.get[RUN_A] = (route, n) => (n === 2 ? held.take(route) : route.fulfill(json(panelRunning(RUN_A))));
      fake.del[RUN_A] = (route) => route.fulfill(json(withStatus(panelRunning(RUN_A), "cancelled")));
      await boot(page);
      await ask(page, Q1);
      await expect(view(page, "live-run")).toBeVisible({ timeout: 15000 });
      await held.ready;
      await page.locator("#live-stop").click();
      // Positive partner: the cancelled state is on screen before the late answer.
      await expect(page.locator("#live-status-text")).toHaveText("Cancelled");
      await expect(page.locator("#live-new-question")).toBeVisible();
      await deliver(page, held, panelRunning(RUN_A));
      await expect(page.locator("#live-status-text")).toHaveText("Cancelled");
      await expect(page.locator("#live-stop")).toBeHidden();
      await expect(page.locator("#live-new-question")).toBeVisible();
      await assertNoForeignRunContent(page, "after the late running answer");
    });

    test("a poll answered 'cancelled' after Stop does not toast a second time", async ({ page }) => {
      // Red when: cancelRun never marks the scope finished, so a late cancelled poll takes pollRun's terminal branch and toasts "Run cancelled." again.
      await recordToasts(page);
      const fake = await installFake(page);
      fake.create = () => ({ body: panelCreate(RUN_A) });
      const held = holder();
      fake.get[RUN_A] = (route, n) => (n === 2 ? held.take(route) : route.fulfill(json(panelRunning(RUN_A))));
      fake.del[RUN_A] = (route) => route.fulfill(json(withStatus(panelRunning(RUN_A), "cancelled")));
      await boot(page);
      await ask(page, Q1);
      await expect(view(page, "live-run")).toBeVisible({ timeout: 15000 });
      await held.ready;
      await page.locator("#live-stop").click();
      await expect.poll(() => toastTexts(page)).toContain("Run cancelled.");
      await deliver(page, held, withStatus(panelRunning(RUN_A), "cancelled"));
      expect((await toastTexts(page)).filter((t) => t === "Run cancelled.")).toHaveLength(1);
      await assertNoForeignRunContent(page, "after the late cancelled answer");
    });

    test("a poll that fails after Stop raises no connection-lost notice", async ({ page }) => {
      // Red when: a rejected poll is handled (handlePollError) without checking that its scope is still open, so it re-raises "Connection lost — retrying…" after Stop.
      await recordToasts(page);
      const fake = await installFake(page);
      fake.create = () => ({ body: panelCreate(RUN_A) });
      const held = holder();
      fake.get[RUN_A] = (route, n) => {
        if (n === 2) return route.abort("failed");
        if (n === 4) return held.take(route);
        return route.fulfill(json(panelRunning(RUN_A)));
      };
      fake.del[RUN_A] = (route) => route.fulfill(json(withStatus(panelRunning(RUN_A), "cancelled")));
      await boot(page);
      await ask(page, Q1);
      await expect(view(page, "live-run")).toBeVisible({ timeout: 15000 });
      // Positive partner: a failed poll while the run is open does raise the notice.
      await expect
        .poll(async () => (await toastList(page)).filter((t) => t.classes.includes("toast-network")).length)
        .toBe(1);
      await held.ready;
      await page.locator("#live-stop").click();
      await expect(page.locator("#live-status-text")).toHaveText("Cancelled");
      await expect(page.locator("[data-network-indicator]")).toHaveCount(0);
      const before = (await toastList(page)).length;
      await deliverFailure(page, held);
      await expect(page.locator("[data-network-indicator]")).toHaveCount(0);
      expect((await toastList(page)).slice(before), "toasts raised by the late failure").toEqual([]);
      await assertNoForeignRunContent(page, "after the late failed poll");
    });

    test("a 'running' answer after the run has failed changes nothing, and New question still works", async ({ page }) => {
      // Red when: pollRun renders a non-terminal answer that arrives after the scope's terminal answer was handled (Stop reappears, New question disappears).
      const fake = await installFake(page);
      fake.create = () => ({ body: panelCreate(RUN_A) });
      const held = holder();
      fake.get[RUN_A] = (route, n) => {
        if (n === 1) return route.fulfill(json(panelRunning(RUN_A)));
        if (n === 2) return held.take(route);
        return route.fulfill(json(panelFailed(RUN_A)));
      };
      await boot(page);
      await ask(page, Q1);
      await expect(view(page, "live-run")).toBeVisible({ timeout: 15000 });
      await held.ready;
      // Positive partner: the failure is on screen, with New question and no Stop.
      await expect(page.locator("#live-status-text")).toHaveText("Failed", { timeout: 10000 });
      await expect(page.locator("#live-new-question")).toBeVisible();
      await expect(page.locator("#live-stop")).toBeHidden();
      await deliver(page, held, panelRunning(RUN_A));
      await expect(page.locator("#live-status-text")).toHaveText("Failed");
      await expect(page.locator("#live-stop")).toBeHidden();
      await expect(page.locator("#live-new-question")).toBeVisible();
      await assertNoForeignRunContent(page, "after the late running answer");
      await page.locator("#live-new-question").click();
      await expect(view(page, "composer")).toBeVisible();
      await assertNoForeignRunContent(page, "composer");
    });

    test("W49: Go to run after a finished run reaches that run's result, and its question reads —", async ({ page }) => {
      // Red when: goToActiveRun keeps the finished run's terminalHandled and liveQueryText instead of calling beginRunScope(active.query_run_id), so the page stays on the live view with the earlier question.
      const fake = await installFake(page);
      fake.create = (n) => (n === 1 ? { body: panelCreate(RUN_A) } : { status: 409, body: BUSY });
      fake.get[RUN_A] = (route) => route.fulfill(json(panelDone(RUN_A)));
      let finishC = false;
      fake.get[RUN_C] = (route) => route.fulfill(json(finishC ? panelDone(RUN_C) : panelRunning(RUN_C)));
      await boot(page);
      await ask(page, Q1);
      await onPanelResult(page, Q1);
      await assertNoForeignRunContent(page, "run A's result");
      await newQuestionFromResult(page);
      await ask(page, Q2);
      await expect(errorCardAction(page, "Go to run")).toBeVisible({ timeout: 15000 });
      await assertNoForeignRunContent(page, "composer with the busy card");
      fake.active = () => activeRun(RUN_C);
      await errorCardAction(page, "Go to run").click();
      await expect(view(page, "live-run")).toBeVisible({ timeout: 15000 });
      await expect.poll(() => fake.count("GET", `/${RUN_C}`)).toBeGreaterThan(0);
      // The active-run answer carries no question, so the page has none to show.
      await expect.soft(page.locator("#live-query"), "the adopted run's question").toHaveText("—");
      expect.soft(await assertNoForeignRunContent(page, "run C live"), "the live view is run C's").toBe(RUN_C);
      finishC = true;
      await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 10000 });
      await expect(page.locator("#result-question")).toHaveText("—");
      expect.soft(await assertNoForeignRunContent(page, "run C's result"), "the result is run C's").toBe(RUN_C);
    });

    test("opening a run from the session list clears the error card of the run before", async ({ page }) => {
      // Red when: restoreTrailRun renders the restored run without calling clearError.
      const fake = await installFake(page);
      fake.create = (n) => ({ body: n === 1 ? panelCreate(RUN_A) : panelCreate(RUN_B) });
      fake.get[RUN_A] = (route) => route.fulfill(json(panelDone(RUN_A)));
      fake.get[RUN_B] = (route) => route.fulfill(json(panelFailed(RUN_B)));
      await boot(page);
      await ask(page, Q1);
      await onPanelResult(page, Q1);
      await newQuestionFromResult(page);
      await ask(page, Q2);
      // Positive partner: the failed run's error card is on screen.
      await expect(page.locator("#error-region")).toBeVisible({ timeout: 15000 });
      await expect(page.locator("#live-status-text")).toHaveText("Failed");
      await assertNoForeignRunContent(page, "failed run B");
      await trailEntry(page, RUN_A).click();
      await onPanelResult(page, Q1);
      expect.soft(await assertNoForeignRunContent(page, "restored run A"), "the result is run A's").toBe(RUN_A);
      await expect(page.locator("#error-region")).toBeHidden();
    });

    test("of two quick session-list clicks, the second one's run stays on screen", async ({ page }) => {
      // Red when: restoreTrailRun renders whichever GET answers last, with no restore token.
      const fake = await installFake(page);
      fake.create = (n) => ({ body: n === 1 ? panelCreate(RUN_A) : panelCreate(RUN_B) });
      const held = holder();
      let holdA = false;
      fake.get[RUN_A] = (route) => (holdA ? held.take(route) : route.fulfill(json(panelDone(RUN_A))));
      fake.get[RUN_B] = (route) => route.fulfill(json(panelDone(RUN_B)));
      await boot(page);
      await ask(page, Q1);
      await onPanelResult(page, Q1);
      await newQuestionFromResult(page);
      await ask(page, Q2);
      await onPanelResult(page, Q2);
      holdA = true;
      await trailEntry(page, RUN_A).click();
      await held.ready;
      // While A's answer is outstanding the page still shows B, tagged B.
      expect.soft(await assertNoForeignRunContent(page, "restoring A"), "still run B").toBe(RUN_B);
      await trailEntry(page, RUN_B).click();
      await onPanelResult(page, Q2);
      await deliver(page, held, panelDone(RUN_A));
      await expect(page.locator("#result-question")).toHaveText(Q2);
      expect.soft(await assertNoForeignRunContent(page, "after A's late answer"), "the result is run B's").toBe(RUN_B);
    });

    test("a session-list answer that arrives after New question does not leave the composer", async ({ page }) => {
      // Red when: restoreTrailRun's GET has no guard, so its late answer calls setView("result") over the composer.
      const fake = await installFake(page);
      fake.create = (n) => ({ body: n === 1 ? panelCreate(RUN_A) : panelCreate(RUN_B) });
      const held = holder();
      let holdA = false;
      fake.get[RUN_A] = (route) => (holdA ? held.take(route) : route.fulfill(json(panelDone(RUN_A))));
      fake.get[RUN_B] = (route) => route.fulfill(json(panelDone(RUN_B)));
      await boot(page);
      await ask(page, Q1);
      await onPanelResult(page, Q1);
      await newQuestionFromResult(page);
      await ask(page, Q2);
      await onPanelResult(page, Q2);
      holdA = true;
      await trailEntry(page, RUN_A).click();
      await held.ready;
      await newQuestionFromResult(page);
      await assertNoForeignRunContent(page, "composer while A's answer is outstanding");
      await deliver(page, held, panelDone(RUN_A));
      await expect(view(page, "composer")).toBeVisible();
      await expect(view(page, "result")).toBeHidden();
      await assertNoForeignRunContent(page, "composer after A's late answer");
    });

    test("a session-list answer abandoned by New question then Back is not drawn over the result the user came back to", async ({ page }) => {
      // Red when: a view change does not abandon a pending session-list restore (setView no longer moves state.restoreToken on), so an answer that arrives after a round trip back to the same view is drawn over it.
      const fake = await installFake(page);
      fake.create = (n) => ({ body: n === 1 ? panelCreate(RUN_A) : panelCreate(RUN_B) });
      const held = holder();
      let holdA = false;
      fake.get[RUN_A] = (route) => (holdA ? held.take(route) : route.fulfill(json(panelDone(RUN_A))));
      fake.get[RUN_B] = (route) => route.fulfill(json(panelDone(RUN_B)));
      await boot(page);
      await ask(page, Q1);
      await onPanelResult(page, Q1);
      await newQuestionFromResult(page);
      await ask(page, Q2);
      await onPanelResult(page, Q2);
      // Positive partner: the history entry the user will come back to names run B.
      const entryB = await page.evaluate(() => window.history.state);
      expect(entryB).toEqual({ quorumView: "result", runId: RUN_B });
      holdA = true;
      await trailEntry(page, RUN_A).click();
      await held.ready;
      await newQuestionFromResult(page);
      await page.goBack();
      await onPanelResult(page, Q2);
      expect.soft(await assertNoForeignRunContent(page, "Back to run B's result"), "the result is run B's").toBe(RUN_B);
      await deliver(page, held, panelDone(RUN_A));
      await expect(view(page, "result")).toBeVisible();
      await expect(page.locator("#result-question")).toHaveText(Q2);
      expect.soft(await assertNoForeignRunContent(page, "after A's abandoned answer"), "still run B").toBe(RUN_B);
      expect(await page.evaluate(() => window.history.state), "the history entry still names run B").toEqual(entryB);
    });

    test("a session-list answer abandoned by starting a new run never replaces that run", async ({ page }) => {
      // Red when: neither the view change (setView) nor the new run's scope (beginRunScope) moves state.restoreToken on, so a session-list answer that arrives once a new run is on the live-run view replaces that run's scope and takes the page off it. Either move alone keeps it green; each is pinned on its own by the test above (setView) and tests/unit/test_w127_run_scope_round_one.py (beginRunScope).
      const fake = await installFake(page);
      fake.create = (n) => ({ body: panelCreate(n === 1 ? RUN_A : n === 2 ? RUN_B : RUN_C) });
      const held = holder();
      let holdA = false;
      fake.get[RUN_A] = (route) => (holdA ? held.take(route) : route.fulfill(json(panelDone(RUN_A))));
      fake.get[RUN_B] = (route) => route.fulfill(json(panelFailed(RUN_B)));
      fake.get[RUN_C] = (route) => route.fulfill(json(panelRunning(RUN_C)));
      fake.del[RUN_C] = (route) => route.fulfill(json(panelDone(RUN_C)));
      await boot(page);
      await ask(page, Q1);
      await onPanelResult(page, Q1);
      await newQuestionFromResult(page);
      await ask(page, Q2);
      // Positive partner: run B failed, and its live view offers New question.
      await expect(page.locator("#live-status-text")).toHaveText("Failed", { timeout: 15000 });
      await assertNoForeignRunContent(page, "failed run B");
      holdA = true;
      await trailEntry(page, RUN_A).click();
      await held.ready;
      await page.locator("#live-new-question").click();
      await expect(view(page, "composer")).toBeVisible();
      await ask(page, Q3);
      await expect(view(page, "live-run")).toBeVisible({ timeout: 15000 });
      await expect(page.locator("#live-query")).toHaveText(Q3);
      expect.soft(await assertNoForeignRunContent(page, "run C live"), "the live view is run C's").toBe(RUN_C);
      await deliver(page, held, panelDone(RUN_A));
      await expect(view(page, "live-run"), "run C's live view stays on screen").toBeVisible();
      await expect(page.locator("#live-query")).toHaveText(Q3);
      expect.soft(await assertNoForeignRunContent(page, "run C after A's abandoned answer"), "still run C").toBe(RUN_C);
      // Stop still works: the DELETE says run C had finished, and its answer opens.
      await page.locator("#live-stop").click();
      await expect.poll(() => fake.count("DELETE", `/${RUN_C}`)).toBe(1);
      await onPanelResult(page, Q3);
      expect.soft(await assertNoForeignRunContent(page, "run C's result"), "the result is run C's").toBe(RUN_C);
      await newQuestionFromResult(page);
      await assertNoForeignRunContent(page, "composer after run C");
    });

    test("a session-list click made while Go to run waits is still drawn when no run is active", async ({ page }) => {
      // Red when: setView moves state.restoreToken on even when the view does not change, so "no active run" sending the composer back to the composer abandons the click made after Go to run.
      const fake = await installFake(page);
      fake.create = (n) => (n === 1 ? { body: panelCreate(RUN_A) } : { status: 409, body: BUSY });
      const held = holder();
      let holdA = false;
      fake.get[RUN_A] = (route) => (holdA ? held.take(route) : route.fulfill(json(panelDone(RUN_A))));
      await boot(page);
      await ask(page, Q1);
      await onPanelResult(page, Q1);
      await newQuestionFromResult(page);
      await ask(page, Q2);
      await expect(errorCardAction(page, "Go to run")).toBeVisible({ timeout: 15000 });
      await assertNoForeignRunContent(page, "composer with the busy card");
      // Registered after installFake, so this handler answers /active first.
      const activeHeld = holder();
      await page.route(/\/v1\/query-runs\/active$/, (route) => activeHeld.take(route));
      await errorCardAction(page, "Go to run").click();
      await activeHeld.ready;
      // Positive partner: while Go to run waits, the session-list entry can be clicked.
      await expect(trailEntry(page, RUN_A)).toBeEnabled();
      holdA = true;
      await trailEntry(page, RUN_A).click();
      await held.ready;
      await deliver(page, activeHeld, activeRun(null));
      await expect(view(page, "composer")).toBeVisible();
      await assertNoForeignRunContent(page, "composer after no active run");
      await deliver(page, held, panelDone(RUN_A));
      await onPanelResult(page, Q1);
      expect.soft(await assertNoForeignRunContent(page, "restored run A"), "the result is run A's").toBe(RUN_A);
    });

    test("Go to run shows nothing of the finished run while the adopted run's first answer is outstanding", async ({ page }) => {
      // Red when: beginRunScope leaves the finished run's elapsed time, its pill state or its round cards and statuses on the live view, or leaves the question line empty and untagged, until the adopted run's first poll answers.
      const fake = await installFake(page);
      fake.create = (n) => (n === 1 ? { body: panelCreate(RUN_A) } : { status: 409, body: BUSY });
      fake.get[RUN_A] = (route) => route.fulfill(json(panelDone(RUN_A)));
      // Every poll of run C is held (they overlap, one every 750 ms) until the
      // first is released, so nothing of run C is drawn while the checks run.
      const held = holder();
      const parked: Route[] = [];
      let holdC = true;
      fake.get[RUN_C] = (route, n) => {
        if (!holdC) return route.fulfill(json(panelRunning(RUN_C)));
        if (n === 1) return held.take(route);
        parked.push(route);
      };
      await boot(page);
      await ask(page, Q1);
      await onPanelResult(page, Q1);
      // Positive partner: run A left its header and its rounds in the hidden live view.
      const left = await page.evaluate(() => ({
        elapsed: document.getElementById("live-elapsed")?.textContent ?? "",
        pill: document.getElementById("live-status-pill")?.dataset.state ?? "",
        cards: document.querySelectorAll("#live-debate .live-round-card").length,
      }));
      expect(left.elapsed).not.toEqual("0.0s elapsed");
      expect(left.pill).toEqual("completed");
      expect(left.cards).toBeGreaterThan(0);
      await newQuestionFromResult(page);
      await ask(page, Q2);
      await expect(errorCardAction(page, "Go to run")).toBeVisible({ timeout: 15000 });
      fake.active = () => activeRun(RUN_C);
      await errorCardAction(page, "Go to run").click();
      await held.ready;
      await expect(view(page, "live-run")).toBeVisible();
      await expect.soft(page.locator("#live-elapsed"), "the adopted run's elapsed time").toHaveText("0.0s elapsed");
      await expect.soft(page.locator("#live-status-pill"), "the adopted run's pill").toHaveAttribute("data-state", "running");
      await expect.soft(page.locator("#live-query"), "the adopted run's question").toHaveText("—");
      await expect.soft(page.locator("#live-debate .live-round-card").filter({ visible: true }), "run A's round cards").toHaveCount(0);
      expect.soft(await assertNoForeignRunContent(page, "run C before its first answer"), "the live view is run C's").toBe(RUN_C);
      // Nothing of run C has been drawn: its polls are all still held.
      expect(fake.count("GET", `/${RUN_C}`)).toBeGreaterThan(0);
      holdC = false;
      await deliver(page, held, panelRunning(RUN_C));
      for (const route of parked) await route.fulfill(json(panelRunning(RUN_C)));
      await expect(page.locator("#live-status-text")).toHaveText("Running · initial answers");
      expect.soft(await assertNoForeignRunContent(page, "run C after its first answer"), "the live view is run C's").toBe(RUN_C);
    });

    test("Back to the kept result after New question shows it, still tagged with its run", async ({ page }) => {
      // Red when: setView does not derive <html data-run-id> from state.runScope on the result view, or renderResult does not tag the regions it fills (the visible result is unchanged today; only the invariant is red).
      const fake = await installFake(page);
      fake.get[RUN_A] = (route) => route.fulfill(json(panelDone(RUN_A)));
      await boot(page);
      await ask(page, Q1);
      await onPanelResult(page, Q1);
      await assertNoForeignRunContent(page, "run A's result");
      await newQuestionFromResult(page);
      await assertNoForeignRunContent(page, "composer");
      await page.goBack();
      await onPanelResult(page, Q1);
      expect.soft(await assertNoForeignRunContent(page, "Back to run A's result"), "the result is run A's").toBe(RUN_A);
    });

    test("a moderator transcript after a peer one does not keep the peer caption", async ({ page }) => {
      // Red when: renderTranscript writes .transcript-debate-caption only when describePeerCritique returns a sentence, so a moderator run keeps the earlier peer run's sentence.
      const fake = await installFake(page);
      fake.create = (n) => ({ body: n === 1 ? panelCreate(RUN_A) : panelCreate(RUN_B) });
      fake.get[RUN_A] = (route) => route.fulfill(json(withRunId(goldenRespWithPeerDebate(), RUN_A)));
      fake.get[RUN_B] = (route) => route.fulfill(json(panelDone(RUN_B)));
      const caption = page.locator(".transcript-debate-caption");
      await boot(page);
      const shipped = ((await caption.textContent()) || "").trim();
      await ask(page, Q1);
      await onPanelResult(page, Q1);
      await page.locator("#result-transcript-link").click();
      await expect(view(page, "transcript")).toBeVisible();
      // Positive partner: the peer run writes its own sentence over the shipped one.
      await expect(caption).toBeVisible();
      const peer = ((await caption.textContent()) || "").trim();
      expect(peer).not.toEqual("");
      expect(peer).not.toEqual(shipped);
      expect.soft(await assertNoForeignRunContent(page, "run A's transcript"), "the transcript is run A's").toBe(RUN_A);

      await page.locator("#transcript-back").click();
      await expect(view(page, "result")).toBeVisible();
      await newQuestionFromResult(page);
      await ask(page, Q2);
      await onPanelResult(page, Q2);
      await page.locator("#result-transcript-link").click();
      await expect(view(page, "transcript")).toBeVisible();
      const now = await caption.evaluate((node) => ({
        visible: (node as HTMLElement).checkVisibility(),
        text: (node.textContent || "").trim(),
      }));
      expect(now.visible && now.text === peer, `run B's caption still reads run A's peer sentence: ${now.text}`).toBe(false);
      expect.soft(await assertNoForeignRunContent(page, "run B's transcript"), "the transcript is run B's").toBe(RUN_B);
    });

    test("the transcript's demo banner describes the restored run, not the last one polled", async ({ page }) => {
      // Red when: #demo-mode-banner is set only by renderModelPanels from pollRun, so a restored live run's transcript shows the simulated run's banner.
      const fake = await installFake(page);
      fake.create = (n) => ({ body: n === 1 ? panelCreate(RUN_A) : panelCreate(RUN_B) });
      fake.get[RUN_A] = (route) => route.fulfill(json(panelDone(RUN_A)));
      fake.get[RUN_B] = (route) => route.fulfill(json(simulatedDone(RUN_B)));
      const banner = page.locator("#demo-mode-banner");
      await boot(page);
      await ask(page, Q1);
      await onPanelResult(page, Q1);
      await newQuestionFromResult(page);
      await ask(page, Q2);
      await onPanelResult(page, Q2);
      await page.locator("#result-transcript-link").click();
      await expect(view(page, "transcript")).toBeVisible();
      // Positive partner: the simulated run's transcript carries the banner.
      await expect(banner).toBeVisible();
      expect.soft(await assertNoForeignRunContent(page, "run B's transcript"), "the transcript is run B's").toBe(RUN_B);
      await page.locator("#transcript-back").click();
      await expect(view(page, "result")).toBeVisible();
      await trailEntry(page, RUN_A).click();
      await onPanelResult(page, Q1);
      await page.locator("#result-transcript-link").click();
      await expect(view(page, "transcript")).toBeVisible();
      await expect(page.locator("#transcript-heading")).toHaveText(Q1);
      await expect(banner).toBeHidden();
      expect.soft(await assertNoForeignRunContent(page, "restored run A's transcript"), "the transcript is run A's").toBe(RUN_A);
    });

    test("Stop it & start new says 'Previous run stopped.' only when the DELETE answered cancelled", async ({ page }) => {
      // Red when: stopActiveRunAndCompose toasts "Previous run stopped. Start a fresh query." whatever the DELETE returned.
      await recordToasts(page);
      const fake = await installFake(page);
      fake.create = () => ({ status: 409, body: BUSY });
      fake.active = () => activeRun(RUN_C);
      let answer: unknown = panelDone(RUN_C);
      fake.del[RUN_C] = (route) => route.fulfill(json(answer));
      const stopped = "Previous run stopped. Start a fresh query.";
      await boot(page);
      await ask(page, Q1);
      await expect(errorCardAction(page, "Stop it & start new")).toBeVisible({ timeout: 15000 });
      await errorCardAction(page, "Stop it & start new").click();
      await expect.poll(() => fake.count("DELETE", `/${RUN_C}`)).toBe(1);
      await expect(view(page, "composer")).toBeVisible();
      await expect(page.locator("#error-region")).toBeHidden();
      await assertNoForeignRunContent(page, "composer after stopping a finished run");
      await page.waitForTimeout(600);
      const afterCompleted = await toastTexts(page);

      // Positive partner, same test: a DELETE that did cancel the run says so.
      answer = withStatus(panelRunning(RUN_C), "cancelled");
      await page.locator("#run-now").click();
      await expect(errorCardAction(page, "Stop it & start new")).toBeVisible({ timeout: 15000 });
      await errorCardAction(page, "Stop it & start new").click();
      await expect.poll(() => toastTexts(page)).toContain(stopped);
      await assertNoForeignRunContent(page, "composer after stopping a running run");
      expect(afterCompleted, "toasts after stopping a run that had already completed").not.toContain(stopped);
    });
  });
}
