import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * OD-2 ops dashboard gate (`/ui/ops`).
 *
 * Asserts against the REAL local server (playwright webServer — no mocks):
 *  - the SLO tiles render values CONSISTENT with a simultaneous direct fetch
 *    of /metrics and /status (cross-checked, not just "some text appeared");
 *  - no horizontal overflow at 1440px and at a narrow width;
 *  - no critical/serious axe violation;
 *  - the page stays CSP-clean (no console CSP violations).
 */

const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

function parseTotals(metricsText: string): { all: number; err5xx: number } {
  let all = 0;
  let err5xx = 0;
  for (const line of metricsText.split("\n")) {
    if (!line || line.startsWith("#")) continue;
    const sp = line.lastIndexOf(" ");
    if (sp < 0) continue;
    const name = line.slice(0, sp);
    const value = parseFloat(line.slice(sp + 1));
    if (Number.isNaN(value)) continue;
    if (name.startsWith("http_requests_total{")) {
      all += value;
      if (name.includes('status="5xx"')) err5xx += value;
    }
  }
  return { all, err5xx };
}

test.describe("ops dashboard", () => {
  test("tiles render live values consistent with direct fetches", async ({
    page,
    request,
  }) => {
    const cspViolations: string[] = [];
    page.on("console", (msg) => {
      if (msg.text().includes("Content Security Policy")) {
        cspViolations.push(msg.text());
      }
    });

    await page.goto("/ui/ops");
    // First refresh populates the fetched tiles.
    await expect(page.locator('[data-current="version"]')).not.toHaveText("—", {
      timeout: 10_000,
    });

    // Cross-check version + environment against a direct /status fetch.
    const statusJson = await (await request.get("/status")).json();
    await expect(page.locator('[data-current="version"]')).toHaveText(
      String(statusJson.version),
    );
    await expect(page.locator('[data-current="environment"]')).toContainText(
      String(statusJson.environment),
    );

    // Readiness tile must match a direct /ready fetch.
    const readyJson = await (await request.get("/ready")).json();
    await expect(page.locator('[data-current="ready"]')).toHaveText(
      String(readyJson.live_readiness.state),
    );

    // Error-rate tile: recompute from a direct /metrics fetch and compare
    // within tolerance (the page's scrape happened moments earlier, so allow
    // a small delta from traffic in between).
    const metricsText = await (await request.get("/metrics")).text();
    const totals = parseTotals(metricsText);
    const errText = await page
      .locator('[data-current="err"]')
      .textContent();
    if (totals.all > 0) {
      const expectedPct = (totals.err5xx / totals.all) * 100;
      const shownPct = parseFloat(errText ?? "NaN");
      expect(Number.isNaN(shownPct)).toBe(false);
      expect(Math.abs(shownPct - expectedPct)).toBeLessThanOrEqual(1.0);
    }

    // SLO verdicts rendered (PASS/FAIL/no data — never empty) for slo tiles.
    for (const key of ["p95", "err", "ready"]) {
      const verdict = await page
        .locator(`[data-verdict="${key}"]`)
        .textContent();
      expect(verdict === "PASS" || verdict === "FAIL" || verdict === "no data yet").toBe(
        true,
      );
    }

    expect(cspViolations).toEqual([]);
  });

  test("no horizontal overflow at 1440px and narrow width", async ({ page }) => {
    await page.goto("/ui/ops");
    await expect(page.locator('[data-current="version"]')).not.toHaveText("—", {
      timeout: 10_000,
    });
    // OD-2 review finding: a long unbroken token (an env-var name in the
    // readiness reasons) clipped INSIDE its tile while the document-level
    // scrollWidth stayed clean. Inject a worst-case token so the check
    // exercises the wrap behaviour deterministically, then measure BOTH the
    // document and every element inside the tiles.
    await page.evaluate(() => {
      const note = document.querySelector('[data-current="ready-reasons"]');
      if (note)
        note.textContent =
          "reasons: OPENROUTER_LIVE_EXECUTION_ENABLED_EXTREMELY_LONG_UNBROKEN_TOKEN_FOR_OVERFLOW_CHECK is not set";
    });
    for (const width of [1440, 375]) {
      await page.setViewportSize({ width, height: 900 });
      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(overflow, `horizontal overflow at ${width}px`).toBeLessThanOrEqual(0);
      const clipped = await page.evaluate(() =>
        Array.from(
          document.querySelectorAll(
            ".tile, .tile *, #metrics-explained, #metrics-explained *",
          ),
        )
          .filter((el) => {
            const style = getComputedStyle(el);
            // A container that DECLARES horizontal scrolling (overflow-x:
            // auto/scroll) is the sanctioned home for wide content (the
            // catalog table) — scrolling inside it is not clipping. Anything
            // else that overflows its box is a real defect.
            if (style.overflowX === "auto" || style.overflowX === "scroll")
              return false;
            // Inline boxes have clientWidth 0 BY SPEC, so the comparison is
            // meaningless for them (they wrap, they cannot clip). Chromium
            // also reports scrollWidth 0 for inline elements so the check
            // never fired there; Firefox reports the content width, turning
            // every inline span into a false positive. Measure block-level
            // boxes only — the elements that can actually clip content.
            if (style.display === "inline") return false;
            return el.scrollWidth > el.clientWidth + 1;
          })
          .map(
            (el) =>
              `${el.tagName}.${el.className} ${el.scrollWidth}>${el.clientWidth}`,
          ),
      );
      expect(clipped, `clipped tile content at ${width}px`).toEqual([]);
    }
  });

  test("metric catalog renders live families consistent with a direct /metrics fetch", async ({
    page,
    request,
  }) => {
    await page.goto("/ui/ops");
    await expect(page.locator('[data-current="family-count"]')).not.toHaveText(
      "—",
      { timeout: 10_000 },
    );

    // Direct fetch AFTER the page has scraped: the family set is stable
    // within a running process (families register at import/first-request
    // time), so the counts must match exactly.
    const metricsText = await (await request.get("/metrics")).text();
    const directFamilies = metricsText
      .split("\n")
      .filter((l) => l.startsWith("# HELP "))
      .map((l) => l.split(" ")[2]);
    expect(directFamilies.length).toBeGreaterThan(0);

    await expect(page.locator('[data-current="family-count"]')).toHaveText(
      String(directFamilies.length),
    );

    // Every group container renders one row per family in that group,
    // with the family name and its TYPE visible.
    for (const group of ["http", "process", "python"] as const) {
      const expected = directFamilies.filter((f) => f.startsWith(`${group}_`));
      const rows = page.locator(`[data-group="${group}"] [data-family]`);
      await expect(rows).toHaveCount(expected.length);
      for (const family of expected) {
        const row = page.locator(`[data-family="${family}"]`);
        await expect(row).toBeVisible();
        await expect(row).toContainText(family);
      }
      // Empty-group honesty: a known group with no families (process_* is
      // Linux-only) must show the empty-state note instead of bare table
      // headers — and never both states at once.
      const emptyNote = page.locator(`[data-group-empty="${group}"]`);
      const scroll = page.locator(`[data-group="${group}"] .catalog-scroll`);
      if (expected.length === 0) {
        await expect(emptyNote).toBeVisible();
        await expect(scroll).toBeHidden();
      } else {
        await expect(emptyNote).toBeHidden();
        await expect(scroll).toBeVisible();
      }
    }

    // Row content is real: a known histogram family shows its type.
    await expect(
      page.locator('[data-family="http_request_duration_seconds"]'),
    ).toContainText("histogram");
  });

  test("explainer sections state purpose, read-path and SLO source of truth", async ({
    page,
  }) => {
    await page.goto("/ui/ops");
    await expect(page.locator("#explainer-about")).toContainText(/prometheus/i);
    await expect(page.locator("#explainer-about")).toContainText(
      /public|unauthenticated/i,
    );
    await expect(page.locator("#explainer-howto")).toContainText("curl");
    await expect(page.locator("#explainer-slo")).toContainText(
      "docs/80-observability.md",
    );
    // Same-origin links to the raw surfaces the page explains.
    for (const href of ["/metrics", "/status", "/ready"]) {
      await expect(
        page.locator(`#metrics-explained a[href="${href}"]`),
      ).toHaveCount(1);
    }
  });

  test("axe: no critical/serious violations", async ({ page }) => {
    await page.goto("/ui/ops");
    await expect(page.locator('[data-current="version"]')).not.toHaveText("—", {
      timeout: 10_000,
    });
    const results = await new AxeBuilder({ page })
      .withTags(AXE_TAGS)
      .analyze();
    const serious = results.violations.filter(
      (v) => v.impact === "critical" || v.impact === "serious",
    );
    expect(serious).toEqual([]);
  });
});
