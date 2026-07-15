import { test, expect, Page, ConsoleMessage } from "@playwright/test";

/**
 * The app self-hosts Swagger UI (/docs) from same-origin /static/vendor assets
 * specifically so its strict Content-Security-Policy does NOT have to be widened.
 * The unit tests (tests/integration/test_docs_self_hosted.py) prove the rendered
 * HTML references only same-origin assets — but they run under a TestClient and
 * never load the page in a real browser, so the load-bearing claim ("the docs
 * actually FUNCTION under the enforced CSP") was only ever checked by hand.
 *
 * This pins it in a real browser: /docs mounts, renders the operation list, and
 * logs zero CSP violations. If the CSP is ever tightened in a way that breaks the
 * docs (e.g. dropping 'unsafe-inline'), this test goes red instead of shipping a
 * blank /docs behind green unit tests.
 *
 * (ReDoc /redoc is intentionally NOT served — it cannot be CSP-clean: its search
 * builds a blob: Worker that script-src 'self' blocks and it fetches an external
 * cdn.redoc.ly logo. test_docs_self_hosted asserts /redoc 404s.)
 */

const EXTERNAL_HOSTS = ["cdn.jsdelivr.net", "unpkg.com", "fastapi.tiangolo.com", "googleapis.com"];
const isCspError = (s: string) =>
  /content security policy|refused to (load|execute|create|connect)|worker-src|violates the following|securityerror/i.test(s);

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m: ConsoleMessage) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(String(e)));
  return errors;
}

test.describe("self-hosted API docs render + function under the strict CSP", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "chromium-only reference run");

  test("/docs (Swagger UI) renders with no external asset host and no CSP violation", async ({ page }) => {
    const errors = collectErrors(page);
    await page.goto("/docs", { waitUntil: "networkidle" });
    // Swagger UI actually mounted and rendered the operation list from the schema.
    await expect(page.locator(".swagger-ui")).toBeVisible();
    await expect(page.locator(".opblock").first()).toBeVisible();
    const html = await page.content();
    for (const host of EXTERNAL_HOSTS) {
      expect(html, `/docs must not reference ${host}`).not.toContain(host);
    }
    const csp = errors.filter(isCspError);
    expect(csp, `CSP/security console errors on /docs:\n${csp.join("\n")}`).toEqual([]);
  });

  test("/redoc is not served (ReDoc cannot be CSP-clean)", async ({ page }) => {
    const resp = await page.goto("/redoc", { waitUntil: "domcontentloaded" });
    expect(resp?.status(), "/redoc must 404 — only Swagger /docs is self-hosted").toBe(404);
  });
});
