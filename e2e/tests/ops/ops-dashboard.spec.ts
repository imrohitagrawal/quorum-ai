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
        Array.from(document.querySelectorAll(".tile, .tile *"))
          .filter((el) => el.scrollWidth > el.clientWidth + 1)
          .map(
            (el) =>
              `${el.tagName}.${el.className} ${el.scrollWidth}>${el.clientWidth}`,
          ),
      );
      expect(clipped, `clipped tile content at ${width}px`).toEqual([]);
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
