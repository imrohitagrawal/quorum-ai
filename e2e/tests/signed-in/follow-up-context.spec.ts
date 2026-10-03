import { test, expect, type Page, type Request } from "@playwright/test";

/**
 * W37 — the follow-up journey SIGNED IN (ADR-0143), on the signed-in lane
 * (W33 slice D, ADR-0142).
 *
 * Runs ONLY under `playwright.signed-in.config.ts`, whose test-only launcher
 * (`e2e/servers/signed_in_server.py`) starts the real app with Google sign-in
 * on against a loopback token stub, fresh temporary databases and live
 * execution off ($0). The one thing caught is Google's consent page, exactly as
 * `history-refresh.spec.ts` does; everything after it — sign-in, estimate,
 * warnings probe, the simulated run — is the real backend. The API is never
 * mocked: requests are OBSERVED with `page.on("request")`.
 *
 * Why a signed-in copy of the anonymous journey: a signed-in page has its own
 * session and spend key (ADR-0136), and the anonymous lane cannot sign in.
 */

const Q1 = "Postgres or MySQL for a small team?";
const Q2 = "What about running it on a managed service?";
const Q3 = "How do I back up a small database?";

type Ctx = { prior_question?: string; prior_synthesis?: string } | undefined;
type Body = { query_text?: string; context?: Ctx };
type Sent = { kind: "estimate" | "warnings" | "create"; body: Body; seq: number };

let counter = 0;
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

async function signIn(page: Page, account: { sub: string; email: string }) {
  await routeGoogle(page, account);
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem("quorum.workspaceSeen", "1");
    } catch (_) {}
  });
  await page.goto("/ui", { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-view="composer"]')).toBeVisible();
  await page.locator("#sign-in-google").click();
  await expect(page.locator("#account-email")).toHaveText(account.email);
  await expect(page.locator('[data-view="composer"]')).toBeVisible();
}

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

const countOf = (sent: Sent[], kind: Sent["kind"]) => sent.filter((s) => s.kind === kind).length;
const lastOf = (sent: Sent[], kind: Sent["kind"]) => [...sent].reverse().find((s) => s.kind === kind);
async function nextSent(sent: Sent[], kind: Sent["kind"], before: number): Promise<Sent> {
  await expect.poll(() => countOf(sent, kind), { timeout: 15000 }).toBeGreaterThan(before);
  return lastOf(sent, kind)!;
}

const composerView = (page: Page) => page.locator('[data-view="composer"]');
const nextRegion = (page: Page) => page.getByRole("region", { name: "Ask your next question" });
const followUpButton = (page: Page) => nextRegion(page).getByRole("button", { name: "Follow up on this", exact: true });
const startFreshButton = (page: Page) => nextRegion(page).getByRole("button", { name: "Start fresh", exact: true });
const composerFollowLine = (page: Page) => composerView(page).getByText(/Following up on: /).filter({ visible: true });

async function settleResult(page: Page, question: string) {
  const gateConfirm = page.locator("#gate-confirm");
  await expect(page.locator('#result-verdict[data-consensus]:visible, #gate-confirm:visible').first()).toBeVisible({
    timeout: 30000,
  });
  if (await gateConfirm.isVisible()) await gateConfirm.click();
  await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 60000 });
  await expect(page.locator("#result-question")).toHaveText(question);
}

test.describe("signed-in follow-up context (W37)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "the lane runs on the reference engine only");

  test("signed in: Follow up carries the context on the estimate, the warnings probe and the run; Start fresh carries none", async ({ page }) => {
    // RED-IF: the signed-in page shows no mode buttons, or its estimate, warnings probe or create lacks the context, or Start fresh still sends it (ADR-0143 decisions 4, 5, 7).
    const sent = recordRunRequests(page);
    await signIn(page, freshAccount("w37"));

    await page.locator("#query-text").fill(Q1);
    await page.locator("#run-now").click();
    await settleResult(page, Q1);

    await expect(followUpButton(page)).toBeVisible();
    await expect(followUpButton(page)).toHaveAttribute("aria-pressed", "true");
    await expect(startFreshButton(page)).toBeVisible();
    await expect(page.locator("#result-next-input")).toHaveValue("");

    await page.locator("#result-next-input").fill(Q2);
    await page.locator("#result-next-run").click();
    await expect(composerView(page)).toBeVisible();
    await expect(composerFollowLine(page)).toContainText(Q1);

    const estimatesBefore = countOf(sent, "estimate");
    await page.locator("#estimate-run").click();
    const estimate = (await nextSent(sent, "estimate", estimatesBefore)).body;
    expect(estimate.context?.prior_question).toBe(Q1);
    expect((estimate.context?.prior_synthesis ?? "").length).toBeGreaterThan(0);

    const createsBefore = countOf(sent, "create");
    await expect(page.locator("#gate-confirm")).toBeVisible({ timeout: 15000 });
    await page.locator("#gate-confirm").click();
    const create = await nextSent(sent, "create", createsBefore);
    expect(create.body.context).toEqual(estimate.context);
    const probe = [...sent].reverse().find((s) => s.kind === "warnings" && s.seq < create.seq);
    expect(probe, "a warnings probe was sent before the create").toBeTruthy();
    expect(probe!.body.context).toEqual(estimate.context);
    await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 60000 });
    await expect(page.locator("#result-question")).toHaveText(Q2);

    await startFreshButton(page).click();
    await expect(startFreshButton(page)).toHaveAttribute("aria-pressed", "true");
    await page.locator("#result-next-input").fill(Q3);
    await page.locator("#result-next-run").click();
    await expect(composerView(page)).toBeVisible();
    await expect(composerFollowLine(page)).toHaveCount(0);
    const freshBefore = countOf(sent, "estimate");
    await page.locator("#estimate-run").click();
    const fresh = (await nextSent(sent, "estimate", freshBefore)).body;
    expect(fresh.query_text).toBe(Q3);
    expect(fresh.context, "Start fresh sends no context").toBeUndefined();
  });
});
