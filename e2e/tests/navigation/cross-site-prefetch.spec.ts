import http from "node:http";
import type { AddressInfo } from "node:net";
import { test, expect, type Page } from "@playwright/test";
import { recordWire, wireHop, type WireLog } from "../../fixtures/wire-headers";

/**
 * W88 round 1 (B1): another site's speculation-rules prefetch of /ui and
 * /v1/session, in a real browser.
 *
 * MEASURED by round 1: Chromium fetches both addresses in the background,
 * from a page on another site carrying `<script type="speculationrules">`,
 * with `Sec-Fetch-Site: none` (the value of a typed address) and
 * `Sec-Purpose: prefetch`. Before the fix each fetch opened a counted session.
 *
 * As in `cross-site-loads.spec.ts`, the other site is a real loopback server
 * (`http://localhost:<port>`; the app is `127.0.0.1:18085`, so another site),
 * because Chromium refuses a `page.route` page's loads of the app. The headers
 * are read from the DevTools protocol (`fixtures/wire-headers.ts`). Each case
 * first checks the browser really sent `sec-purpose: prefetch`, so it cannot
 * pass on a prefetch that never happened.
 */

const APP = "http://127.0.0.1:18085";
const pages = new Map<string, string>();
let server: http.Server;
let port = 0;
const otherSite = () => `http://localhost:${port}`;

test.beforeAll(async () => {
  server = http.createServer((req, res) => {
    const body = pages.get(new URL(req.url ?? "/", "http://x").pathname);
    res.writeHead(body === undefined ? 404 : 200, { "content-type": "text/html; charset=utf-8" });
    res.end(body === undefined ? "" : `<!doctype html><html><body>${body}</body></html>`);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
  port = (server.address() as AddressInfo).port;
});

test.afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

function speculationRules(urls: string[]): string {
  return `<script type="speculationrules">${JSON.stringify({ prefetch: [{ source: "list", urls }] })}</script>`;
}

async function openOtherPage(page: Page, name: string, body: string): Promise<void> {
  pages.set(`/${name}`, body);
  await page.goto(`${otherSite()}/${name}`);
}

function prefetchHop(log: WireLog, path: string, mark: string) {
  return wireHop(
    log,
    (url) => url.origin === APP && url.pathname === path && url.searchParams.get("w88") === mark,
  );
}

test.describe("another site's prefetch of the app (W88 round 1)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "speculation rules are measured in Chromium");

  test("another site's prefetch of /ui and /v1/session is refused", async ({ page }) => {
    // RED-IF: either route answers a speculation-rules prefetch from another site's page (sent as Sec-Fetch-Site: none with Sec-Purpose: prefetch) with anything but 403 (B1).
    const log = await recordWire(page);
    const ui = `${APP}/ui?w88=prefetch-ui`;
    const session = `${APP}/v1/session?w88=prefetch-session`;
    await openOtherPage(page, "prefetch1", `<p>other site</p>${speculationRules([ui, session])}`);
    for (const hop of [await prefetchHop(log, "/ui", "prefetch-ui"), await prefetchHop(log, "/v1/session", "prefetch-session")]) {
      expect(hop.sent["sec-purpose"] ?? "").toMatch(/^prefetch\b/);
      expect(hop.sent["sec-fetch-site"]).toBe("none");
      expect(hop.status).toBe(403);
    }
    // The visitor never left the other site.
    expect(page.url()).toBe(`${otherSite()}/prefetch1`);
  });

  test("after a refused prefetch, a link from the same page still opens a working page", async ({ page }) => {
    // RED-IF: a refused prefetch of /ui breaks the visit that follows it, so clicking the link the prefetch was for does not reach a ready page.
    const log = await recordWire(page);
    const ui = `${APP}/ui?w88=prefetch-then-link`;
    await openOtherPage(page, "prefetch2", `<a id="go" href="${ui}">Open Quorum-AI</a>${speculationRules([ui])}`);
    const prefetched = await prefetchHop(log, "/ui", "prefetch-then-link");
    expect(prefetched.sent["sec-purpose"] ?? "").toMatch(/^prefetch\b/);
    expect(prefetched.status).toBe(403);

    await page.locator("#go").click();
    const isVisit = (h: { url: string; sent: Record<string, string> }) =>
      h.url === ui && h.sent["sec-purpose"] === undefined;
    await expect
      .poll(() => log().filter(isVisit).length, { timeout: 15000, message: "the click reached the app" })
      .toBe(1);
    const visits = log().filter(isVisit);
    expect(visits[0].sent["sec-fetch-site"]).toBe("cross-site");
    expect(visits[0].sent["sec-fetch-dest"]).toBe("document");
    expect(visits[0].status).toBe(200);
    await expect(page.locator("html")).toHaveAttribute("data-app-state", "ready", { timeout: 20000 });
    await expect(page.locator("#connection-pill-text")).toContainText("Session active");
  });
});
