import http from "node:http";
import type { AddressInfo } from "node:net";
import { test, expect, type Page } from "@playwright/test";
import { recordWire, wireHop, type WireLog } from "../../fixtures/wire-headers";

/**
 * W88 (CHG-063 (b), CHG-067): another site's loads of /ui and /v1/session, in a
 * real browser.
 *
 * The other site is a small loopback server this spec starts, opened as
 * `http://localhost:<port>`. The app is `127.0.0.1:18085`, a different host,
 * so the browser marks the app's requests `cross-site`; the same server opened
 * as `http://127.0.0.1:<port>` is `same-site`. It is a real server, not a
 * `page.route` fulfilment: MEASURED 2026-10-23, Chromium refused an `<img>`
 * and an `<iframe>` of the app from a fulfilled page before sending them
 * (`LocalNetworkAccessPermissionDenied`), so such a case could never reach
 * the app. Every case first checks the
 * header the browser really sent (read from the DevTools protocol, see
 * `fixtures/wire-headers.ts`), so no case passes without the browser having
 * marked the request as another site's.
 *
 * Hidden loads (an image, a frame) must be refused with 403. Opening the page
 * from a link, in the same tab or a new one, and the invite page's "Continue"
 * must still end on a working page. The daily session limit is never
 * asserted here: this lane runs with SESSION_MINT_CAP_OVERRIDE=600 (AGENTS.md
 * rule 13), which hides it.
 */

const APP = "http://127.0.0.1:18085";
const pages = new Map<string, string>();
let server: http.Server;
let port = 0;
const otherSite = () => `http://localhost:${port}`;
const sameSite = () => `http://127.0.0.1:${port}`;

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

/** Put `body` on the other site at `/<name>` and open it. */
async function openOtherPage(page: Page, origin: string, name: string, body: string): Promise<void> {
  pages.set(`/${name}`, body);
  await page.goto(`${origin}/${name}`);
}

/** The app's request whose URL carries `?w88=<mark>`, as sent and answered. */
function appHop(log: WireLog, path: string, mark: string) {
  return wireHop(log, (url) => url.origin === APP && url.pathname === path && url.searchParams.get("w88") === mark);
}

async function expectWorkingPage(page: Page): Promise<void> {
  await expect(page.locator("html")).toHaveAttribute("data-app-state", "ready", { timeout: 20000 });
  await expect(page.locator("#connection-pill-text")).toContainText("Session active");
  await expect(page.locator("#connection-pill-text")).not.toHaveText("Disconnected");
  await expect(page.getByText(/session unavailable/i)).toHaveCount(0);
}

test.describe("loads of the app from another site (W88)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "the headers are measured on the reference engine");

  test("another site's hidden image of /ui is refused", async ({ page }) => {
    // RED-IF: /ui answers another site's <img> with anything but 403.
    const log = await recordWire(page);
    await openOtherPage(page, otherSite(), "case1", `<img src="${APP}/ui?w88=img-ui" alt="">`);
    const hop = await appHop(log, "/ui", "img-ui");
    expect(hop.sent["sec-fetch-site"]).toBe("cross-site");
    expect(hop.sent["sec-fetch-dest"]).toBe("image");
    expect(hop.status).toBe(403);
  });

  test("another site's frame of /ui is refused", async ({ page }) => {
    // RED-IF: /ui answers another site's <iframe> with anything but 403 (F9).
    const log = await recordWire(page);
    await openOtherPage(page, otherSite(), "case2", `<iframe src="${APP}/ui?w88=frame-ui"></iframe>`);
    const hop = await appHop(log, "/ui", "frame-ui");
    expect(hop.sent["sec-fetch-site"]).toBe("cross-site");
    expect(hop.sent["sec-fetch-mode"]).toBe("navigate");
    expect(hop.sent["sec-fetch-dest"]).toBe("iframe");
    expect(hop.status).toBe(403);
  });

  test("another site's hidden image of /v1/session is refused", async ({ page }) => {
    // RED-IF: /v1/session answers another site's <img> with anything but 403.
    const log = await recordWire(page);
    await openOtherPage(page, otherSite(), "case3", `<img src="${APP}/v1/session?w88=img-session" alt="">`);
    const hop = await appHop(log, "/v1/session", "img-session");
    expect(hop.sent["sec-fetch-site"]).toBe("cross-site");
    expect(hop.sent["sec-fetch-dest"]).toBe("image");
    expect(hop.status).toBe(403);
  });

  test("a link on another site to /v1/session is refused with the plain refusal", async ({ page }) => {
    // RED-IF: /v1/session answers a cross-site link (a top-level navigation) with a session and token instead of the 403 refusal.
    const log = await recordWire(page);
    await openOtherPage(page, otherSite(), "case4", `<a id="go" href="${APP}/v1/session?w88=link-session">open</a>`);
    await page.locator("#go").click();
    const hop = await appHop(log, "/v1/session", "link-session");
    expect(hop.sent["sec-fetch-site"]).toBe("cross-site");
    expect(hop.sent["sec-fetch-mode"]).toBe("navigate");
    expect(hop.status).toBe(403);
    await page.waitForURL(`${APP}/v1/session?w88=link-session`);
    expect(JSON.parse((await page.locator("body").innerText()).trim())).toEqual({
      detail: {
        code: "CROSS_SITE_REFUSED",
        message: "This request came from another site, so it cannot open or renew a session.",
      },
    });
  });

  test("a same-site neighbour's hidden images of /ui and /v1/session are refused", async ({ page }) => {
    // RED-IF: same-site counts as this site, so a neighbour on the same host is served (F10).
    const log = await recordWire(page);
    await openOtherPage(page, sameSite(), "case5", `<img src="${APP}/ui?w88=same-site-ui" alt=""><img src="${APP}/v1/session?w88=same-site-session" alt="">`);
    for (const hop of [await appHop(log, "/ui", "same-site-ui"), await appHop(log, "/v1/session", "same-site-session")]) {
      expect(hop.sent["sec-fetch-site"]).toBe("same-site");
      expect(hop.status).toBe(403);
    }
  });

  test("a link on another site opens a working page in the same tab, and a reload keeps it working", async ({ page }) => {
    // RED-IF: /ui refuses a page opened from another site's link (F1), or the reload of that page (F3).
    const log = await recordWire(page);
    await openOtherPage(page, otherSite(), "case6", `<a id="go" href="${APP}/ui?w88=link-ui">Open Quorum-AI</a>`);
    await page.locator("#go").click();
    const arrival = await appHop(log, "/ui", "link-ui");
    expect(arrival.sent["sec-fetch-site"]).toBe("cross-site");
    expect(arrival.sent["sec-fetch-mode"]).toBe("navigate");
    expect(arrival.sent["sec-fetch-dest"]).toBe("document");
    expect(arrival.status).toBe(200);
    await expectWorkingPage(page);

    const before = log().length;
    await page.reload();
    const isUi = (h: { url: string }) => new URL(h.url).pathname === "/ui";
    await expect.poll(() => log().slice(before).filter(isUi).length, { timeout: 15000 }).toBe(1);
    const reloads = log().slice(before).filter(isUi);
    expect(reloads).toHaveLength(1);
    // The reload's site is not asserted. The W88 failure modes recorded
    // Chromium re-sending `cross-site` here (F3); MEASURED 2026-10-23 with
    // this lane's Chromium it sent `same-origin`. Either is allowed; the
    // server-side test sends `cross-site` on the reload explicitly.
    expect(["cross-site", "same-origin"]).toContain(reloads[0].sent["sec-fetch-site"]);
    expect(reloads[0].status).toBe(200);
    await expectWorkingPage(page);
  });

  test("a link on another site opens a working page in a new tab", async ({ page, context }) => {
    // RED-IF: /ui refuses a page another site's link opens in a new tab (target=_blank).
    const arrivals: Promise<Record<string, string>>[] = [];
    context.on("request", (request) => {
      const url = new URL(request.url());
      if (url.origin === APP && url.pathname === "/ui" && url.searchParams.get("w88") === "tab-ui") {
        arrivals.push(request.allHeaders());
      }
    });
    await openOtherPage(page, otherSite(), "case7", `<a id="go" target="_blank" href="${APP}/ui?w88=tab-ui">Open</a>`);
    const [tab] = await Promise.all([context.waitForEvent("page"), page.locator("#go").click()]);
    await tab.waitForLoadState("domcontentloaded");
    expect(arrivals).toHaveLength(1);
    expect((await arrivals[0])["sec-fetch-site"]).toBe("cross-site");
    await expectWorkingPage(tab);
  });

  test("the invite page opened from another site, then Continue, gives a working page", async ({ page }) => {
    // RED-IF: /ui/invite is gated (F6), or the same-origin "Continue to Quorum-AI" click into /ui is refused.
    // The e2e server has no invite signing key, so the accept call is answered here, as invite-link.spec.ts does.
    const log = await recordWire(page);
    await page.route(`${APP}/v1/invite`, (route) => route.fulfill({ status: 204 }));
    const token = "v1.0123456789ab.2098-07-01." + "a".repeat(64);
    await openOtherPage(page, otherSite(), "case8", `<a id="go" href="${APP}/ui/invite?w88=invite#${token}">Your invite</a>`);
    await page.locator("#go").click();
    const invite = await appHop(log, "/ui/invite", "invite");
    expect(invite.sent["sec-fetch-site"]).toBe("cross-site");
    expect(invite.status).toBe(200);
    await expect(page.locator("#invite-status")).toHaveAttribute("data-state", "accepted");

    await page.locator("#invite-continue").click();
    const continued = await wireHop(log, (url) => url.origin === APP && url.pathname === "/ui");
    expect(continued.sent["sec-fetch-site"]).toBe("same-origin");
    expect(continued.status).toBe(200);
    await expectWorkingPage(page);
  });
});
