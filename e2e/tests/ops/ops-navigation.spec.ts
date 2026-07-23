import { test, expect } from "@playwright/test";

/**
 * Jump-bar TOC + "Used by" honesty + glossary + favicon gate (`/ui/ops`).
 *
 * Drives the REAL local server (playwright webServer — no mocks):
 *  - clicking a TOC link scrolls its section into view and scroll-spy marks
 *    the link with aria-current;
 *  - the two families the tiles actually parse show a "feeds" marker and a
 *    non-consumed family shows "informational" — cross-checked against a
 *    direct /metrics fetch, never a hardcoded family list;
 *  - a jargon link in page-authored copy lands on its glossary entry;
 *  - no page-level horizontal overflow at 375px with the sticky bar present;
 *  - the favicon is linked in the page and served same-origin as an SVG.
 */

const CONSUMED_FAMILIES = [
  "http_requests_total",
  "http_request_duration_seconds",
];

async function waitForFirstRefresh(page: import("@playwright/test").Page) {
  await expect(page.locator('[data-current="version"]')).not.toHaveText("—", {
    timeout: 10_000,
  });
}

test.describe("ops jump-bar TOC + glossary + used-by + favicon", () => {
  test("clicking TOC links scrolls the section into view and sets aria-current", async ({
    page,
  }) => {
    await page.goto("/ui/ops");
    await waitForFirstRefresh(page);

    const toc = page.locator("nav.ops-toc");
    await expect(toc).toBeVisible();

    // Jump to the last section (glossary), then back up to the about section
    // — both directions, so the spy is proven to move, not stick.
    for (const targetId of ["explainer-glossary", "explainer-about"]) {
      const link = toc.locator(`a[href="#${targetId}"]`);
      await link.click();
      await expect(page.locator(`#${targetId}`)).toBeInViewport();
      // Scroll-spy marks the clicked link current once scrolling settles.
      await expect(link).toHaveAttribute("aria-current", "location", {
        timeout: 5_000,
      });
      // Exactly one link is current at a time.
      await expect(toc.locator('a[aria-current="location"]')).toHaveCount(1);
    }
  });

  test("scroll-spy tracks a MANUAL scroll, not only TOC clicks", async ({
    page,
  }) => {
    // Cycle-2 regression: stopping a manual scroll with a section heading
    // just under the sticky bar left aria-current stale indefinitely
    // (no intersection event fires for a tall section's top crossing the
    // current-line mid-band). Scroll in small steps — no TOC click — and
    // the spy must settle on the section actually under the bar.
    await page.goto("/ui/ops");
    await waitForFirstRefresh(page);
    const targetY = await page.evaluate(() => {
      const el = document.getElementById("explainer-about")!;
      // Stop with the section top exactly on the current-line (72px).
      return el.getBoundingClientRect().top + window.scrollY - 72;
    });
    await page.evaluate(async (y) => {
      // Fast to 200px short of the final position (crosses band
      // boundaries, so the spy recomputes and settles)…
      window.scrollTo({ top: y - 200, behavior: "instant" });
      await new Promise((r) => setTimeout(r, 400));
      // …then CREEP the section top across the current-line in 10px
      // steps. This stretch crosses no enter/leave band boundary — the
      // exact stale zone: pre-fix, no event fires here and the highlight
      // stays on the previous section forever.
      for (let d = 190; d >= 0; d -= 10) {
        window.scrollTo({ top: y - d, behavior: "instant" });
        await new Promise((r) => setTimeout(r, 40));
      }
    }, targetY);
    await expect(
      page.locator('nav.ops-toc a[href="#explainer-about"]'),
    ).toHaveAttribute("aria-current", "location", { timeout: 3_000 });
  });

  test("used-by markers are truthful to what the page parses", async ({
    page,
    request,
  }) => {
    await page.goto("/ui/ops");
    await expect(page.locator('[data-current="family-count"]')).not.toHaveText(
      "—",
      { timeout: 10_000 },
    );

    // The live family set, from a direct fetch — never a hardcoded list.
    const metricsText = await (await request.get("/metrics")).text();
    const families = metricsText
      .split("\n")
      .filter((l) => l.startsWith("# HELP "))
      .map((l) => l.split(" ")[2]);
    expect(families.length).toBeGreaterThan(0);

    // NOT vacuous (review finding): every consumed family must actually be
    // in the live exposition — if one is renamed/dropped, this gate REDS
    // instead of silently skipping the feeds assertions.
    for (const family of CONSUMED_FAMILIES) {
      expect(families, `consumed family ${family} missing from /metrics`).toContain(
        family,
      );
    }
    await expect(page.locator("td.used-feeds")).not.toHaveCount(0);

    // Every consuming family shows a feeds marker.
    for (const family of CONSUMED_FAMILIES) {
      await expect(page.locator(`[data-family="${family}"] td.used-feeds`)).toContainText(
        "feeds the",
      );
    }
    // Every other family reads informational — all of them, not a sample.
    for (const family of families.filter((f) => !CONSUMED_FAMILIES.includes(f))) {
      await expect(
        page.locator(`[data-family="${family}"] td.used-info`),
        `family ${family} must be marked informational`,
      ).toContainText("informational — not read by any tile");
    }
  });

  test("hostile /metrics content renders verbatim — never as markup or links", async ({
    page,
  }) => {
    // Behavioral guard (review finding: a source-substring check is
    // evadable — insertAdjacentHTML, createElementNS, quote changes all
    // slip past it). Feed the page a HOSTILE exposition and assert the
    // DOM: help text lands verbatim, no anchor/element is created from
    // it, and a family named __proto__ is catalogued as an ordinary
    // (informational) row without polluting Object.prototype.
    const hostileHelp =
      '<a href="https://evil.example/x">**click**</a><img src=x onerror=alert(1)>';
    const hostile = [
      `# HELP evil_family ${hostileHelp}`,
      "# TYPE evil_family counter",
      "evil_family 1",
      "# HELP __proto__ polluted",
      "# TYPE __proto__ counter",
      "__proto__ 1",
      "",
    ].join("\n");
    await page.route("**/metrics", (route) =>
      route.fulfill({ status: 200, contentType: "text/plain", body: hostile }),
    );
    await page.goto("/ui/ops");
    await expect(page.locator('[data-current="family-count"]')).toHaveText("2", {
      timeout: 10_000,
    });

    // The help cell contains the hostile string VERBATIM as text…
    const evilRow = page.locator('[data-family="evil_family"]');
    await expect(evilRow).toContainText(hostileHelp);
    // …and produced no element from it: no anchor or image anywhere in
    // any catalog table (the page's own a.term links live outside them).
    await expect(page.locator(".catalog-table a, .catalog-table img")).toHaveCount(0);

    // __proto__ is an ordinary catalogued family, not a prototype hit —
    // shown (in the "other" group) and Object.prototype stays clean.
    await expect(page.locator('[data-family="__proto__"]')).toBeVisible();
    const polluted = await page.evaluate(
      () => ({} as Record<string, unknown>).help !== undefined,
    );
    expect(polluted, "Object.prototype polluted by a __proto__ family").toBe(false);
  });

  test("a jargon link lands on its glossary entry", async ({ page }) => {
    await page.goto("/ui/ops");
    await waitForFirstRefresh(page);

    const firstTerm = page.locator("a.term").first();
    const href = await firstTerm.getAttribute("href");
    expect(href).toMatch(/^#term-/);
    await firstTerm.click();
    await expect(page.locator(href!)).toBeInViewport();
    // The entry is a real definition, not a stub.
    const dd = page.locator(`${href} dd`);
    expect(((await dd.textContent()) ?? "").trim().length).toBeGreaterThan(40);
  });

  test("no page-level horizontal overflow at 375px with the sticky bar", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto("/ui/ops");
    await waitForFirstRefresh(page);
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow, "horizontal page overflow at 375px").toBeLessThanOrEqual(0);
    // The bar handles its own width: it declares horizontal scrolling.
    const navOverflowX = await page
      .locator("nav.ops-toc")
      .evaluate((el) => getComputedStyle(el).overflowX);
    expect(navOverflowX).toBe("auto");
    // And it stays sticky: scrolled deep into the page it is still on screen.
    await page.locator('a[href="#explainer-slo"]').click();
    await expect(page.locator("nav.ops-toc")).toBeInViewport();
  });

  test("favicon is linked and served same-origin as an SVG", async ({
    page,
    request,
  }) => {
    await page.goto("/ui/ops");
    // Two icon links: the PNG fallback (Safari) FIRST, then the SVG that
    // SVG-capable browsers prefer.
    const hrefs = await page
      .locator('link[rel="icon"]')
      .evaluateAll((links) => links.map((l) => l.getAttribute("href")));
    expect(hrefs).toEqual(["/static/favicon-32.png", "/static/favicon.svg"]);
    const icon = await request.get("/static/favicon.svg");
    expect(icon.status()).toBe(200);
    expect(icon.headers()["content-type"]).toContain("image/svg+xml");
    const png = await request.get("/static/favicon-32.png");
    expect(png.status()).toBe(200);
    expect(png.headers()["content-type"]).toContain("image/png");
  });
});
