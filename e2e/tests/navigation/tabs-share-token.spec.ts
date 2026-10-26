import http from "node:http";
import type { AddressInfo } from "node:net";
import { test, expect, type BrowserContext, type Page } from "@playwright/test";
import {
  ESTIMATE,
  SESSION,
  estimateWrite,
  expectReady,
  indexedDbDump,
  instrument,
  markSeen,
  pageText,
  recordWire,
  recorded,
  settle,
  typeQuestion,
  watchNotices,
  type Wire,
} from "../../fixtures/tabs-share-token";

/**
 * W105 (CHG-071, CHG-089): open tabs share a renewed anti-forgery token.
 * The anonymous cases, two pages in ONE browser context, against the real
 * backend of the main config (127.0.0.1:18085). Nothing is mocked except
 * where a test holds an answer to set an order, and says so.
 *
 * The write each test checks is "See the estimate" (`#estimate-run`): a
 * click-time POST protected by the token, whose refusal reaches the error
 * banner, and which starts no run. What it carried is read from the request
 * (`x-csrf-token`), and the tokens from the real `/v1/session` answers.
 *
 * The owner's decisions (CHG-089): tabs of the same person share (CHG-071);
 * a click already sent with the old token is refused as today, no retry
 * (case 2); a tab that missed the message is refused as today (case 4).
 *
 * The signed-in cases (E2, E6, E7) are in tests/signed-in/tabs-share-token.spec.ts.
 */

const APP = "http://127.0.0.1:18085";
const TOKEN = /^[A-Za-z0-9_-]{16,128}$/;

/** Open `/ui` in `page` (instrumented first) and wait for its boot. */
async function boot(page: Page): Promise<Wire> {
  const wire = recordWire(page);
  await instrument(page);
  await markSeen(page);
  await page.goto("/ui", { waitUntil: "domcontentloaded" });
  await expectReady(page);
  await settle(wire);
  return wire;
}

/** A second page in the same context, booted. */
async function secondTab(context: BrowserContext): Promise<{ page: Page; wire: Wire }> {
  const page = await context.newPage();
  const wire = await boot(page);
  return { page, wire };
}

/** Let a posted message reach the other page (delivery is asynchronous). */
const DELIVERY_MS = 400;

test.describe("open tabs share a renewed token (W105)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "the lane runs on the reference engine only");

  test("E1: a second tab's renewal reaches the first, whose next write succeeds with it", async ({
    page,
    context,
  }) => {
    // RED-IF: the renewing tab does not post its token, or the first tab
    // does not take it (today: A's write carries A's retired token and gets
    // 403 CSRF_INVALID); or receiving causes a request or a post (FM-7).
    const wireA = await boot(page);
    await typeQuestion(page, wireA);
    const bStartedAt = Date.now();
    const { page: b, wire: wireB } = await secondTab(context);
    expect(wireB.sessionAnswers).toHaveLength(1);
    const tokenB = wireB.sessionAnswers[0];
    expect(tokenB).toMatch(TOKEN);
    expect(tokenB).not.toBe(wireA.sessionAnswers[0]);
    await page.waitForTimeout(DELIVERY_MS);
    const clickAt = Date.now();

    const write = await estimateWrite(page, wireA);
    expect(write.header, "A's write carries the token B's renewal passed on").toBe(tokenB);
    expect(write.status).toBe(200);

    // One /v1/session per boot, one post per renewal, nothing from receiving.
    expect(wireA.sessionRequestsAt).toHaveLength(1);
    expect(wireB.sessionRequestsAt).toHaveLength(1);
    const [a, bRec] = [await recorded(page), await recorded(b)];
    expect(a.posts.map((p) => p.kind)).toEqual(["csrf-token"]);
    expect(bRec.posts.map((p) => p.kind)).toEqual(["csrf-token"]);
    expect(bRec.posts[0].keys).toEqual(["gen", "identity", "kind", "seq", "token"]);
    expect(bRec.posts[0].identity).toBe("anonymous");
    expect(bRec.posts[0].seq).toBe((a.posts[0].seq as number) + 1);
    const whileReceiving = wireA.writes.filter((w) => w.sentAt >= bStartedAt && w.sentAt < clickAt);
    expect(whileReceiving, "receiving made A send nothing").toEqual([]);
    expect(wireA.writes.filter((w) => w.path === ESTIMATE)).toHaveLength(1); // partner: A's writes are seen
  });

  test("E3: while A's renewal is held, B waits for it, and then both tabs can write", async ({ page, context }) => {
    // FM-3, the order. HELD: A's own /v1/session answer is fetched from the
    // server at once (so the server issues A's token first) and handed to
    // the page 1.5 s later. RED-IF: the renewals are not taken in turn (the
    // Web Lock removed): B renews at once instead of after A's answer, and
    // one tab ends with a retired token.
    let fetched!: () => void;
    const aFetched = new Promise<void>((resolve) => (fetched = resolve));
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    let releasedAt = 0;
    await page.route(
      `**${SESSION}`,
      async (route) => {
        const response = await route.fetch();
        fetched();
        await gate;
        releasedAt = Date.now();
        await route.fulfill({ response });
      },
      { times: 1 },
    );
    const wireA = recordWire(page);
    await instrument(page);
    await markSeen(page);
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await aFetched;

    const b = await context.newPage();
    const wireB = recordWire(b);
    await instrument(b);
    await markSeen(b);
    await b.goto("/ui", { waitUntil: "domcontentloaded" });
    await b.waitForTimeout(1500);
    release();
    await expectReady(page);
    await expectReady(b);
    await settle(wireA);
    await settle(wireB);
    await page.waitForTimeout(DELIVERY_MS);

    await typeQuestion(page, wireA);
    const writeA = await estimateWrite(page, wireA);
    await typeQuestion(b, wireB);
    const writeB = await estimateWrite(b, wireB);
    expect(writeA.status, "A can write").toBe(200);
    expect(writeB.status, "B can write").toBe(200);
    expect(writeA.header).toBe(wireB.sessionAnswers[0]);
    expect(writeB.header).toBe(wireB.sessionAnswers[0]);
    expect(wireB.sessionRequestsAt).toHaveLength(1);
    expect(wireB.sessionRequestsAt[0], "B asked for its session only after A's answer").toBeGreaterThanOrEqual(
      releasedAt,
    );
  });

  test("E3b: a tab that waited 10 s renews without the lock, keeps its own token and accepts nothing", async ({
    page,
    context,
  }) => {
    // Item 5. HELD: A's /v1/session answer is held for 11.5 s, past B's 10 s
    // wait for the lock. RED-IF: the lockless tab B takes A's late (older)
    // token, so B's next write is refused. Partner: A did post its late
    // token, so there was something for B to refuse.
    test.setTimeout(90000);
    let fetched!: () => void;
    const aFetched = new Promise<void>((resolve) => (fetched = resolve));
    let releasedAt = 0;
    await page.route(
      `**${SESSION}`,
      async (route) => {
        const response = await route.fetch();
        fetched();
        await new Promise((resolve) => setTimeout(resolve, 11500));
        releasedAt = Date.now();
        await route.fulfill({ response });
      },
      { times: 1 },
    );
    const wireA = recordWire(page);
    await instrument(page);
    await markSeen(page);
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    await aFetched;
    const startedAt = Date.now();

    const b = await context.newPage();
    const wireB = recordWire(b);
    await instrument(b);
    await markSeen(b);
    await b.goto("/ui", { waitUntil: "domcontentloaded" });
    await expectReady(b);
    await expectReady(page);
    await settle(wireA);
    await settle(wireB);
    await b.waitForTimeout(DELIVERY_MS);

    expect(wireB.sessionRequestsAt).toHaveLength(1);
    expect(wireB.sessionRequestsAt[0], "B renewed before A's answer arrived").toBeLessThan(releasedAt);
    await typeQuestion(b, wireB);
    const writeB = await estimateWrite(b, wireB);
    expect(writeB.header, "B kept its own token").toBe(wireB.sessionAnswers[0]);
    expect(writeB.status).toBe(200);
    expect((await recorded(b)).posts, "a tab without the lock posts nothing").toEqual([]);
    expect((await recorded(page)).posts.map((p) => p.kind), "partner: A posted its late token").toEqual([
      "csrf-token",
    ]);
    expect(releasedAt - startedAt).toBeGreaterThan(10000);
  });

  test("E4: a tab that missed the renewal is refused as today, and Refresh session recovers it", async ({
    page,
  }) => {
    // Case 4, "Today's refusal (Recommended)". The token is renewed with
    // page.request, so no page code runs and nothing is posted. RED-IF: the
    // refusal's title or its "Refresh session" action is removed, the
    // refused write is retried, or the reload does not recover the page.
    const wireA = await boot(page);
    await typeQuestion(page, wireA);
    const renewed = await page.request.get(SESSION);
    expect(renewed.status()).toBe(200);
    const elsewhere = String((await renewed.json()).csrf_token ?? "");
    expect(elsewhere).toMatch(TOKEN);

    const refused = await estimateWrite(page, wireA);
    expect(refused.status).toBe(403);
    expect(refused.header).toBe(wireA.sessionAnswers[0]);
    await expect(page.locator("#error-region-title")).toHaveText("Security check failed");
    const refresh = page.locator("#error-region-actions").getByRole("button", { name: "Refresh session", exact: true });
    await expect(refresh).toBeVisible();
    await page.waitForTimeout(1000);
    expect(wireA.writes.filter((w) => w.path === ESTIMATE), "one refused request, no retry").toHaveLength(1);

    const reloaded = page.waitForEvent("load");
    await refresh.click();
    await reloaded;
    await expectReady(page);
    await settle(wireA);
    await typeQuestion(page, wireA);
    const recovered = await estimateWrite(page, wireA);
    expect(recovered.header).toBe(wireA.sessionAnswers[1]);
    expect(recovered.status).toBe(200);
  });

  test("E4b: a write sent with the old token while another tab renews is refused once, not retried", async ({
    page,
    context,
  }) => {
    // Case 2, "Show today's refusal". HELD: A's estimate request is held in
    // page.route until B has renewed, then sent on unchanged (with A's old
    // token). RED-IF: a retry is added (two requests for the one click), the
    // refusal is not shown, or A does not hold B's token afterwards.
    const wireA = await boot(page);
    await typeQuestion(page, wireA);
    let held!: () => void;
    const isHeld = new Promise<void>((resolve) => (held = resolve));
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    await page.route(
      `**${ESTIMATE}`,
      async (route) => {
        held();
        await gate;
        await route.continue();
      },
      { times: 1 },
    );
    const answered = page.waitForResponse((r) => new URL(r.url()).pathname === ESTIMATE, { timeout: 30000 });
    await page.locator("#estimate-run").click();
    await isHeld;
    const { wire: wireB } = await secondTab(context);
    await page.waitForTimeout(DELIVERY_MS);
    release();
    expect((await answered).status()).toBe(403);
    await expect(page.locator("#error-region-title")).toHaveText("Security check failed");
    await page.waitForTimeout(1000);
    await settle(wireA);
    const sent = wireA.writes.filter((w) => w.path === ESTIMATE);
    expect(sent, "one request for the one click").toHaveLength(1);
    expect(sent[0].header).toBe(wireA.sessionAnswers[0]);

    const after = await estimateWrite(page, wireA);
    expect(after.header, "A holds B's token afterwards").toBe(wireB.sessionAnswers[0]);
    expect(after.status).toBe(200);
  });

  test("E8: after sharing, no token is stored, shown or in the URL, and no notice appears", async ({
    page,
    context,
  }) => {
    // FM-8 and FM-14. RED-IF: either token reaches localStorage,
    // sessionStorage, the cookie string, the URL, the page's HTML or
    // IndexedDB; the counter record holds anything but `gen` and `seq`; or
    // a toast or banner appears when the token is taken. Partners: the
    // sharing happened (A's write carries B's token), and the same watcher
    // does see the toast an ordinary estimate shows.
    const wireA = await boot(page);
    await typeQuestion(page, wireA);
    await watchNotices(page);
    const { page: b, wire: wireB } = await secondTab(context);
    await page.waitForTimeout(DELIVERY_MS);
    const tokens = [wireA.sessionAnswers[0], wireB.sessionAnswers[0]];
    for (const token of tokens) expect(token).toMatch(TOKEN);

    for (const p of [page, b]) {
      const texts = await pageText(p);
      expect(texts.length).toBeGreaterThan(2);
      expect(texts.join("").length).toBeGreaterThan(1000);
      for (const token of tokens) expect(texts.filter((t) => t.includes(token))).toEqual([]);
    }
    const dump = await indexedDbDump(page);
    const counter = dump.filter((d) => d.db === "quorum-session-token");
    expect(counter.map((d) => d.store)).toEqual(["counter"]);
    expect(counter[0].keys).toEqual(["counter"]);
    expect(counter[0].values).toHaveLength(1);
    expect(Object.keys(counter[0].values[0] as object).sort()).toEqual(["gen", "seq"]);
    for (const token of tokens) expect(JSON.stringify(dump)).not.toContain(token);
    expect((await recorded(page)).notices, "taking the token showed nothing").toEqual([]);

    const write = await estimateWrite(page, wireA);
    expect(write.header).toBe(tokens[1]);
    expect(write.status).toBe(200);
    await expect
      .poll(async () => (await recorded(page)).notices.join(" | "), { timeout: 5000 })
      .toContain("Cost estimate ready");
  });

  for (const [name, script] of [
    [
      "no BroadcastChannel",
      () => {
        delete (window as unknown as { BroadcastChannel?: unknown }).BroadcastChannel;
      },
    ],
    [
      "a BroadcastChannel whose constructor throws",
      () => {
        (window as unknown as { BroadcastChannel: unknown }).BroadcastChannel = function () {
          throw new Error("W105 test: no channel here");
        };
      },
    ],
    [
      "no navigator.locks",
      () => {
        Object.defineProperty(Navigator.prototype, "locks", { configurable: true, get: () => undefined });
      },
    ],
  ] as const) {
    test(`compatibility: with ${name} the page boots and its own token works`, async ({ page }) => {
      // FM-10. Green today by design (today's page uses none of these).
      // RED-IF: the boot depends on the API (an uncaught error, no session,
      // or a page that never becomes ready).
      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(String(e)));
      await page.addInitScript(script);
      const wire = await boot(page);
      await typeQuestion(page, wire);
      const write = await estimateWrite(page, wire);
      expect(write.header).toBe(wire.sessionAnswers[0]);
      expect(write.status).toBe(200);
      expect(errors).toEqual([]);
    });
  }
});

// --- E5: the owner's own case, the page opened from another site's link -------------

const otherPages = new Map<string, string>();
let otherServer: http.Server;
let otherPort = 0;

test.describe("a tab opened from another site's link (W105, FM-15)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "the lane runs on the reference engine only");

  test.beforeAll(async () => {
    otherServer = http.createServer((req, res) => {
      const body = otherPages.get(new URL(req.url ?? "/", "http://x").pathname);
      res.writeHead(body === undefined ? 404 : 200, { "content-type": "text/html; charset=utf-8" });
      res.end(body === undefined ? "" : `<!doctype html><html><body>${body}</body></html>`);
    });
    await new Promise<void>((resolve) => otherServer.listen(0, "127.0.0.1", () => resolve()));
    otherPort = (otherServer.address() as AddressInfo).port;
  });

  test.afterAll(async () => {
    await new Promise<void>((resolve) => otherServer.close(() => resolve()));
  });

  test("E5: a tab opened from another site's link passes its token to the open tab", async ({ page, context }) => {
    // Asha's case (CHG-071). The other site is `localhost:<port>`, so the
    // app's `/ui` arrives `cross-site` (the partner checks the header the
    // browser sent). RED-IF: the new tab's renewal does not reach the tab
    // already open (today: A's write is refused, ADR-0177's A4 row).
    await context.addInitScript(() => {
      for (const key of ["quorum.workspaceSeen", "quorum.hintSeen.estimate", "quorum.hintSeen.trust", "quorum.hintSeen.history"]) {
        try {
          window.localStorage.setItem(key, "1");
        } catch (_) {}
      }
    });
    const wireA = await boot(page);
    await typeQuestion(page, wireA);

    const answers: { page: Page | null; token: string }[] = [];
    const reads: Promise<unknown>[] = [];
    const arrivals: Promise<Record<string, string>>[] = [];
    context.on("request", (request) => {
      const url = new URL(request.url());
      if (url.origin === APP && url.pathname === "/ui" && url.searchParams.get("w105") === "tab") {
        arrivals.push(request.allHeaders());
      }
    });
    context.on("response", (response) => {
      const url = new URL(response.url());
      if (url.origin === APP && url.pathname === SESSION && response.ok()) {
        reads.push(
          response.json().then((body) => answers.push({ page: response.frame().page(), token: String(body.csrf_token) })),
        );
      }
    });
    otherPages.set("/w105-link", `<a id="go" target="_blank" href="${APP}/ui?w105=tab">Open Quorum</a>`);
    const other = await context.newPage();
    await other.goto(`http://localhost:${otherPort}/w105-link`);
    const [tab] = await Promise.all([context.waitForEvent("page"), other.locator("#go").click()]);
    await tab.waitForLoadState("domcontentloaded");
    await expectReady(tab);
    await Promise.all(reads);
    expect(arrivals).toHaveLength(1);
    expect((await arrivals[0])["sec-fetch-site"]).toBe("cross-site");
    const fromTab = answers.filter((a) => a.page === tab).map((a) => a.token);
    expect(fromTab).toHaveLength(1);
    await page.waitForTimeout(DELIVERY_MS);

    const write = await estimateWrite(page, wireA);
    expect(write.header, "A's write carries the new tab's token").toBe(fromTab[0]);
    expect(write.status).toBe(200);
    await expect(page.locator("#error-region")).toBeHidden();
    await expect(page.locator('[data-view="cost-gate"]')).toBeVisible(); // partner: the estimate opened the gate
  });
});
