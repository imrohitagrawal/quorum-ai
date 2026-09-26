import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * W32 (ADR-0134): the page an invite link opens.
 *
 * The token rides in the URL fragment. The page must move it into a JSON
 * POST body, strip it from the address bar, and say what happened. The e2e
 * server has no signing key, so the real endpoint answers "not enabled";
 * the accepted and invalid answers are mocked per test.
 */

const TOKEN = "v1.0123456789ab.2098-07-01." + "a".repeat(64);

test.describe("invite link page", () => {
  test("the token leaves the address bar and travels only in the POST body", async ({
    page,
  }) => {
    const posted: string[] = [];
    page.on("request", (req) => {
      if (req.url().endsWith("/v1/invite")) posted.push(req.postData() ?? "");
    });
    await page.goto(`/ui/invite#${TOKEN}`);
    const status = page.locator("#invite-status");
    // The shipped server has no signing key: the real endpoint says so.
    await expect(status).toHaveAttribute("data-state", "disabled");
    await expect(status).toHaveText("Invite links are not enabled here.");
    expect(page.url()).toBe("http://127.0.0.1:18085/ui/invite");
    expect(posted).toEqual([JSON.stringify({ token: TOKEN })]);
  });

  test("an accepted invite says so and links on", async ({ page }) => {
    await page.route("**/v1/invite", (route) => route.fulfill({ status: 204 }));
    await page.goto(`/ui/invite#${TOKEN}`);
    await expect(page.locator("#invite-status")).toHaveAttribute("data-state", "accepted");
    await expect(page.locator("#invite-continue")).toHaveAttribute("href", "/ui");
  });

  test("a refused invite says to ask for a new one", async ({ page }) => {
    await page.route("**/v1/invite", (route) =>
      route.fulfill({ status: 400, contentType: "application/json", body: "{}" }),
    );
    await page.goto(`/ui/invite#${TOKEN}`);
    await expect(page.locator("#invite-status")).toHaveText(
      "This invite link is not valid. Ask for a new one.",
    );
  });

  test("a link with no invite in it sends nothing", async ({ page }) => {
    const posted: string[] = [];
    page.on("request", (req) => {
      if (req.url().endsWith("/v1/invite")) posted.push(req.url());
    });
    await page.goto("/ui/invite");
    await expect(page.locator("#invite-status")).toHaveAttribute("data-state", "missing");
    // Positive partner for the empty list below: the page did run its script.
    await expect(page.locator("#invite-status")).not.toHaveText("Checking your invite…");
    expect(posted).toEqual([]);
  });

  test("has no critical or serious axe violation", async ({ page }) => {
    await page.goto(`/ui/invite#${TOKEN}`);
    await expect(page.locator("#invite-status")).not.toHaveAttribute("data-state", "pending");
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    const bad = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
    expect(bad.map((v) => v.id)).toEqual([]);
    // axe files a 1:1 contrast under "incomplete", not "violations": the
    // first version of this page had an invisible Continue link and passed.
    const unsure = results.incomplete.filter((v) => v.id === "color-contrast");
    expect(unsure.map((v) => v.nodes.map((n) => n.target.join(" ")))).toEqual([]);
    // Positive partner: axe actually checked rules on this page.
    expect(results.passes.length).toBeGreaterThan(0);
  });

  test("the Continue link is readable on its card", async ({ page }) => {
    await page.goto(`/ui/invite#${TOKEN}`);
    const colours = await page.evaluate(() => {
      const link = document.getElementById("invite-continue")!;
      const card = document.querySelector("main")!;
      return [getComputedStyle(link).color, getComputedStyle(card).backgroundColor];
    });
    expect(colours[0]).not.toBe(colours[1]);
    // Positive partner: both colours were actually read.
    expect(colours[0]).toMatch(/^rgb/);
    expect(colours[1]).toMatch(/^rgb/);
  });

  test("follows the system dark theme", async ({ browser }) => {
    const context = await browser.newContext({ colorScheme: "dark" });
    const page = await context.newPage();
    await page.goto("http://127.0.0.1:18085/ui/invite");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await context.close();
  });
});
