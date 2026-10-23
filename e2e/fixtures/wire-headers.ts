import { expect, type Page } from "@playwright/test";

/**
 * W88: the request headers Chromium really put on the wire, and the status
 * that came back, read from the DevTools protocol.
 *
 * Why not `request.allHeaders()` and `page.on("response")`: MEASURED
 * 2026-10-23 on this lane, Playwright's `allHeaders()` returned no
 * `sec-fetch-site` for a link click from a page served by `page.route`, and
 * none for an `<img>` even with no route at all, while the protocol's
 * `Network.requestWillBeSentExtraInfo` showed `cross-site` for both; and an
 * `<img>` whose answer is not an image (the app's HTML or JSON) gives no
 * Playwright response event. A spec that asserts the header first would have
 * failed for the wrong reason, and one that skipped it could pass on a
 * request the browser never marked.
 *
 * Chromium only. One request id covers every hop of a redirect chain, and a
 * hop answered by `route.fulfill` (Google's page in the signed-in lane) is
 * sent to no server, so it may have a URL and no wire headers or status. Such
 * a hop comes first in its chain, so the lists are paired from the END; every pair is
 * then checked against the `Host` header actually sent, and a pair that does
 * not match is dropped rather than reported under the wrong URL.
 */

export type WireHop = { url: string; sent: Record<string, string>; status: number };

export type WireLog = () => WireHop[];

export async function recordWire(page: Page): Promise<WireLog> {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Network.enable");
  const order: string[] = [];
  const urls = new Map<string, string[]>();
  const sent = new Map<string, Record<string, string>[]>();
  const statuses = new Map<string, number[]>();
  const push = <T>(m: Map<string, T[]>, id: string, value: T) => {
    if (!urls.has(id) && !sent.has(id) && !statuses.has(id)) order.push(id);
    const list = m.get(id) ?? [];
    list.push(value);
    m.set(id, list);
  };
  cdp.on("Network.requestWillBeSent", (e) => push(urls, e.requestId, e.request.url));
  cdp.on("Network.requestWillBeSentExtraInfo", (e) => {
    const lower: Record<string, string> = {};
    for (const [k, v] of Object.entries(e.headers)) lower[k.toLowerCase()] = String(v);
    push(sent, e.requestId, lower);
  });
  cdp.on("Network.responseReceivedExtraInfo", (e) => push(statuses, e.requestId, e.statusCode));
  return () => {
    const hops: WireHop[] = [];
    for (const id of order) {
      const u = urls.get(id) ?? [];
      const s = sent.get(id) ?? [];
      const st = statuses.get(id) ?? [];
      const n = Math.min(u.length, s.length, st.length);
      for (let i = 0; i < n; i += 1) {
        const hop = { url: u[u.length - n + i], sent: s[s.length - n + i], status: st[st.length - n + i] };
        if (hop.sent["host"] === new URL(hop.url).host) hops.push(hop);
      }
    }
    return hops;
  };
}

/** The first hop whose URL matches, once its headers and status are both known. */
export async function wireHop(log: WireLog, match: (url: URL) => boolean): Promise<WireHop> {
  let found: WireHop | undefined;
  await expect
    .poll(
      () => {
        found = log().find((hop) => match(new URL(hop.url)));
        return found !== undefined;
      },
      { timeout: 15000, message: "the browser sent the request and got an answer" },
    )
    .toBe(true);
  return found!;
}
