import { expect, type Page, type Request } from "@playwright/test";

/**
 * W105 (CHG-071, CHG-089): helpers shared by the two tab-sharing specs,
 * `tests/navigation/tabs-share-token.spec.ts` (anonymous, main config) and
 * `tests/signed-in/tabs-share-token.spec.ts` (the signed-in lane).
 *
 * Nothing here mocks the app. `recordWire` reads what the page really sent and
 * what the server really answered; `instrument` counts the page's channel
 * posts (their field names, kind, identity and number, NEVER the token) and
 * any toast or banner that appears once `watchNotices` is called.
 */

export const ESTIMATE = "/v1/query-runs/estimate";
export const SESSION = "/v1/session";

/** One write (any non-GET `/v1/` request) as sent and answered. */
export type Write = { path: string; header: string; status: number | null; sentAt: number };

/** One page's `/v1/session` requests and answers, and its writes, in order. */
export type Wire = {
  sessionRequestsAt: number[];
  sessionAnswers: string[];
  writes: Write[];
  settled: Promise<unknown>[];
};

export function recordWire(page: Page): Wire {
  const wire: Wire = { sessionRequestsAt: [], sessionAnswers: [], writes: [], settled: [] };
  const pending = new Map<Request, Write>();
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === SESSION && request.method() === "GET") {
      wire.sessionRequestsAt.push(Date.now());
      return;
    }
    if (url.pathname.startsWith("/v1/") && request.method() !== "GET") {
      const write: Write = { path: url.pathname, header: "", status: null, sentAt: Date.now() };
      wire.writes.push(write);
      pending.set(request, write);
      wire.settled.push(
        request.allHeaders().then((headers) => {
          write.header = headers["x-csrf-token"] ?? "";
        }),
      );
    }
  });
  page.on("response", (response) => {
    const request = response.request();
    const url = new URL(request.url());
    if (url.pathname === SESSION && request.method() === "GET" && response.ok()) {
      wire.settled.push(
        response
          .json()
          .then((body) => wire.sessionAnswers.push(String(body.csrf_token ?? "")))
          .catch(() => undefined),
      );
    }
    const write = pending.get(request);
    if (write) write.status = response.status();
  });
  page.on("requestfailed", (request) => {
    const write = pending.get(request);
    if (write) write.status = 0;
  });
  return wire;
}

/** Wait until every header and answer the wire has seen is read. */
export async function settle(wire: Wire): Promise<void> {
  await Promise.all(wire.settled);
}

/** Count channel posts and (once `watchNotices` runs) every toast or banner. */
export async function instrument(page: Page): Promise<void> {
  await page.addInitScript(() => {
    type Post = { keys: string[]; kind: unknown; identity: unknown; seq: unknown };
    const record = { posts: [] as Post[], notices: [] as string[], watching: false };
    (window as unknown as { __w105: typeof record }).__w105 = record;
    const Channel = window.BroadcastChannel;
    if (typeof Channel === "function") {
      const post = Channel.prototype.postMessage;
      Channel.prototype.postMessage = function (message: unknown) {
        try {
          const m = (message ?? {}) as Record<string, unknown>;
          record.posts.push({ keys: Object.keys(m).sort(), kind: m.kind, identity: m.identity, seq: m.seq });
        } catch (_) {}
        return post.call(this, message);
      };
    }
    new MutationObserver((mutations) => {
      if (!record.watching) return;
      for (const mutation of mutations) {
        if (mutation.type === "attributes") {
          const target = mutation.target as HTMLElement;
          if (target.id === "error-region" && !target.hidden) {
            record.notices.push(`banner: ${(target.textContent ?? "").trim().slice(0, 120)}`);
          }
          continue;
        }
        for (const node of Array.from(mutation.addedNodes)) {
          if (node instanceof HTMLElement && (node.matches(".toast, [role=alert]") || node.querySelector(".toast"))) {
            record.notices.push(`toast: ${(node.textContent ?? "").trim().slice(0, 120)}`);
          }
        }
      }
    }).observe(document, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden"] });
  });
}

type Recorded = { posts: { keys: string[]; kind: unknown; identity: unknown; seq: unknown }[]; notices: string[] };

export async function recorded(page: Page): Promise<Recorded> {
  return page.evaluate(() => {
    const r = (window as unknown as { __w105: Recorded }).__w105;
    return { posts: r.posts.slice(), notices: r.notices.slice() };
  });
}

export async function watchNotices(page: Page): Promise<void> {
  await page.evaluate(() => {
    (window as unknown as { __w105: { watching: boolean } }).__w105.watching = true;
  });
}

/** Mark the first-visit gate and the one-time hints as seen. */
export async function markSeen(page: Page): Promise<void> {
  await page.addInitScript(() => {
    for (const key of [
      "quorum.workspaceSeen",
      "quorum.hintSeen.estimate",
      "quorum.hintSeen.trust",
      "quorum.hintSeen.history",
    ]) {
      try {
        window.localStorage.setItem(key, "1");
      } catch (_) {}
    }
  });
}

/** The page finished its boot: the session is up and the composer is ready. */
export async function expectReady(page: Page): Promise<void> {
  await expect(page.locator("html")).toHaveAttribute("data-app-state", "ready", { timeout: 20000 });
  await expect(page.locator('[data-view="composer"]')).toBeVisible();
}

/** Type the question once, so the background warnings check has run before the write. */
export async function typeQuestion(page: Page, wire: Wire): Promise<void> {
  const probes = () => wire.writes.filter((w) => w.path === "/v1/query-runs/warnings").length;
  const before = probes();
  await page.locator("#query-text").fill("What are the key metrics for measuring SaaS customer retention?");
  await expect.poll(probes, { timeout: 5000 }).toBeGreaterThan(before);
  await expect.poll(() => wire.writes.filter((w) => w.status === null).length, { timeout: 5000 }).toBe(0);
}

/**
 * The click-time write: "See the estimate" (`#estimate-run`), a protected
 * POST whose refusal reaches the error banner. Returns that one request.
 */
export async function estimateWrite(page: Page, wire: Wire): Promise<Write> {
  const back = page.locator("#gate-back");
  if (await back.isVisible().catch(() => false)) await back.click();
  const count = () => wire.writes.filter((w) => w.path === ESTIMATE).length;
  const before = count();
  const answered = page.waitForResponse(
    (r) => new URL(r.url()).pathname === ESTIMATE && r.request().method() === "POST",
    { timeout: 15000 },
  );
  await page.locator("#estimate-run").click();
  await answered;
  await settle(wire);
  const mine = wire.writes.filter((w) => w.path === ESTIMATE);
  expect(mine.length, "the click sent exactly one estimate request").toBe(before + 1);
  return mine[mine.length - 1];
}

/** Every value in the page's storage, its URL, its cookie and its HTML. */
export async function pageText(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const values: string[] = [];
    for (const store of [window.localStorage, window.sessionStorage]) {
      for (let i = 0; i < store.length; i += 1) {
        const key = store.key(i) ?? "";
        values.push(`${key}=${store.getItem(key) ?? ""}`);
      }
    }
    values.push(window.location.href, document.cookie, document.documentElement.outerHTML);
    return values;
  });
}

/** Every IndexedDB database the page can see: its stores, keys and values. */
export async function indexedDbDump(
  page: Page,
): Promise<{ db: string; store: string; keys: unknown[]; values: unknown[] }[]> {
  return page.evaluate(async () => {
    const out: { db: string; store: string; keys: unknown[]; values: unknown[] }[] = [];
    const list = await indexedDB.databases();
    for (const info of list) {
      if (!info.name) continue;
      const db = await new Promise<IDBDatabase>((resolve, reject) => {
        const req = indexedDB.open(info.name as string);
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      });
      for (const name of Array.from(db.objectStoreNames)) {
        const tx = db.transaction(name, "readonly");
        const store = tx.objectStore(name);
        const keys = await new Promise<unknown[]>((resolve) => {
          const r = store.getAllKeys();
          r.onsuccess = () => resolve(r.result as unknown[]);
        });
        const values = await new Promise<unknown[]>((resolve) => {
          const r = store.getAll();
          r.onsuccess = () => resolve(r.result as unknown[]);
        });
        out.push({ db: info.name, store: name, keys, values });
      }
      db.close();
    }
    return out;
  });
}
