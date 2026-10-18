import { test, expect, Page } from "@playwright/test";
import { boot } from "../../fixtures/golden-run";

/**
 * W100 — safety acknowledgements on the REAL backend (no page.route).
 *
 * Drives the FastAPI app Playwright's webServer starts (live execution off, so
 * every run is simulated and costs $0). Requests are OBSERVED with
 * `page.on("request"/"response")`, never answered; the guard below fails a
 * test that installs a route. Where a test needs a slow warnings answer it
 * delays the REAL response with an init-script fetch wrapper, as
 * page-journey.spec.ts does.
 *
 * The owner's decisions (CHG-065): the sensitive-data acknowledgement stays
 * automatic (a); the high-stakes one is sent only for a ticked box, read after
 * the final warnings check.
 *
 * Budget: each test is a new anonymous session ($0.40 a day); a simulated run
 * is about $0.105, and no test here creates more than one run once W100 is in.
 *
 * Every test carries a "Red when:" line.
 */

const PLAIN_Q = "Postgres or MySQL for a small team?";
// "contract" is one of the server's high-stakes words (safety.py).
const HS_Q = "Should I sign this employment contract with a non-compete clause?";

type Ack = { warning_type: string; version: string };
type CreateBody = { query_text?: string; safety_acknowledgements?: Ack[] };
type Warning = { warning_type: string; version: string };

function forbidRoutes(page: Page): () => boolean {
  let mocked = false;
  const origRoute = page.route.bind(page);
  (page as unknown as { route: typeof page.route }).route = ((...args: Parameters<typeof origRoute>) => {
    mocked = true;
    return origRoute(...args);
  }) as typeof page.route;
  return () => mocked;
}

/** Every create (POST to exactly /v1/query-runs) with its body and its HTTP status. */
function recordCreates(page: Page) {
  const creates: { body: CreateBody; status: number | null }[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && new URL(r.url()).pathname === "/v1/query-runs") {
      creates.push({ body: (r.postDataJSON() ?? {}) as CreateBody, status: null });
    }
  });
  page.on("response", (res) => {
    const req = res.request();
    if (req.method() === "POST" && new URL(res.url()).pathname === "/v1/query-runs") {
      const pending = creates.find((c) => c.status === null);
      if (pending) pending.status = res.status();
    }
  });
  return creates;
}

/** Every warnings entry the REAL server answered, so a version can be compared with what was sent. */
function recordWarnings(page: Page): Warning[] {
  const seen: Warning[] = [];
  page.on("response", async (res) => {
    if (new URL(res.url()).pathname !== "/v1/query-runs/warnings" || res.status() !== 200) return;
    try {
      const body = (await res.json()) as { warnings?: Warning[] };
      for (const w of body.warnings ?? []) seen.push(w);
    } catch (_) {
      // A body the page never got (navigation) is not a warning answer.
    }
  });
  return seen;
}

/** Delay every warnings RESPONSE by `ms` (the request still goes to the real server). */
async function delayWarnings(page: Page, ms: number) {
  await page.addInitScript((delay) => {
    const orig = window.fetch.bind(window);
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const pending = orig(input, init);
      if (!/\/v1\/query-runs\/warnings(\?|$)/.test(url)) return pending;
      return pending.then((res) => new Promise<Response>((r) => window.setTimeout(() => r(res), delay)));
    };
  }, ms);
}

/**
 * After a press of Run now: approve the cost gate if the estimate landed in the
 * confirmation band, wait for the create's answer, assert it was accepted, and
 * wait for the result. The status is checked BEFORE the result, so a refused
 * run fails with the status the server gave, not with a timeout.
 */
async function settleRealRun(page: Page, creates: { status: number | null }[], expected: number) {
  const confirm = page.locator("#gate-confirm");
  await expect
    .poll(async () => creates.length >= expected || (await confirm.isVisible()), { timeout: 30000 })
    .toBe(true);
  if (creates.length < expected && (await confirm.isVisible())) await confirm.click();
  await expect.poll(() => creates[expected - 1]?.status ?? null, { timeout: 30000 }).not.toBeNull();
  expect(creates[expected - 1].status, "the server accepts the run").toBe(202);
  await expect(page.locator('[data-view="result"] #result-verdict[data-consensus]')).toBeVisible({ timeout: 30000 });
}

const serverVersion = (seen: Warning[], type: string) => {
  const versions = [...new Set(seen.filter((w) => w.warning_type === type).map((w) => w.version))];
  expect(versions, `the server answered exactly one ${type} version`).toHaveLength(1);
  return versions[0];
};

test.describe("W100 — safety acknowledgements on the real backend (no page.route)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  test("a plain question runs (202) with exactly one sensitive-data acknowledgement", async ({ page }) => {
    // Red when: the sensitive-data acknowledgement stops being sent for the
    // visitor (every run is then refused), an extra key or a second entry is
    // added, or its version is not the one the server's warnings check gave.
    const mocked = forbidRoutes(page);
    const creates = recordCreates(page);
    const warnings = recordWarnings(page);
    await boot(page);
    await page.locator("#query-text").fill(PLAIN_Q);
    await page.locator("#run-now").click();
    await settleRealRun(page, creates, 1);

    expect(mocked(), "this spec must not mock the backend").toBe(false);
    expect(creates, "exactly one create").toHaveLength(1);
    expect(creates[0].status).toBe(202);
    const acks = creates[0].body.safety_acknowledgements ?? [];
    expect(acks).toHaveLength(1);
    expect(Object.keys(acks[0]).sort()).toEqual(["version", "warning_type"]);
    expect(acks[0].warning_type).toBe("sensitive_data");
    expect(acks[0].version).toBe(serverVersion(warnings, "sensitive_data"));
    await expect(page.locator("#high-stakes-held")).toBeHidden();
  });

  test("a high-stakes question run before the box appears is held; after the tick it runs (202) with both acknowledgements", async ({ page }) => {
    // Red when: the page sends the high-stakes acknowledgement although the
    // box was never ticked (the run is created on the first press), or a
    // ticked run is refused or sent without it.
    const mocked = forbidRoutes(page);
    const creates = recordCreates(page);
    const warnings = recordWarnings(page);
    // Slow every warnings answer, so the press lands before the background
    // check can show the box (the request still reaches the real server).
    await delayWarnings(page, 1500);
    await boot(page);
    await page.locator("#query-text").fill(HS_Q);
    await page.locator("#run-now").click();
    await page.waitForTimeout(4000);

    expect(creates, "no run before the box is ticked").toHaveLength(0);
    await expect(page.locator('[data-view="composer"]')).toBeVisible();
    await expect(page.locator("#high-stakes-gate")).toBeVisible();
    await expect(page.locator("#high-stakes-held")).toBeVisible();
    await expect(page.locator("#error-region")).toBeHidden();

    await page.locator("#high-stakes-ack").check();
    await page.locator("#run-now").click();
    await settleRealRun(page, creates, 1);
    expect(mocked(), "this spec must not mock the backend").toBe(false);
    expect(creates, "exactly one run for the whole journey").toHaveLength(1);
    expect(creates[0].status).toBe(202);
    const acks = creates[0].body.safety_acknowledgements ?? [];
    expect(acks.map((a) => a.warning_type).sort()).toEqual(["high_stakes", "sensitive_data"]);
    for (const a of acks) expect(Object.keys(a).sort()).toEqual(["version", "warning_type"]);
    expect(acks.find((a) => a.warning_type === "high_stakes")?.version).toBe(serverVersion(warnings, "high_stakes"));
    expect(acks.find((a) => a.warning_type === "sensitive_data")?.version).toBe(serverVersion(warnings, "sensitive_data"));
  });
});
