import { test, expect, Page, ConsoleMessage } from "@playwright/test";
import { waitForComposerReady } from "../../fixtures/stabilize";

/**
 * RB-6 — CROSS-ENGINE CSP SMOKE (advisory; own workflow `csp-smoke.yml`).
 *
 * The blocking `docs-under-csp.spec.ts` runs chromium-only. This smoke checks
 * the primary workspace page (`/ui`) under the enforced Content-Security-Policy
 * on chromium, firefox AND webkit, so a CSP that breaks the app on a non-Blink
 * engine is caught rather than shipped.
 *
 * ANTI-VACUITY (this stage's characteristic failure). A bare
 * `expect(violations).toEqual([])` passes just as emptily on an engine where
 * the page never loaded, or where CSP violations never reach the harness. Two
 * things defend against that:
 *   1. The smoke asserts the app FUNCTIONS (`waitForComposerReady` → the four
 *      model slots populate), not merely that a document arrived.
 *   2. A POSITIVE CONTROL test deliberately triggers a CSP violation and
 *      asserts the harness DETECTS it — if detection does not work on this
 *      engine the control goes RED (not skipped), so the clean result is never
 *      vacuous.
 *
 * The detector is the standardised `securitypolicyviolation` DOM event
 * (`SecurityPolicyViolationEvent`), which fires on `document` in Chromium,
 * Firefox and WebKit alike — unlike console text, which each engine words
 * differently. The console `isCspError` matcher (shared shape with
 * `docs-under-csp.spec.ts`) is kept as a second, belt-and-braces signal.
 */

const isCspError = (s: string) =>
  /content security policy|refused to (load|execute|create|connect)|worker-src|violates the following|securityerror/i.test(
    s,
  );

// Installed via addInitScript so it is registered BEFORE the page's own
// scripts run — it must be listening on the very first navigation.
const INSTALL_CSP_LISTENER = `
  window.__cspViolations = [];
  document.addEventListener('securitypolicyviolation', function (e) {
    window.__cspViolations.push({ directive: e.violatedDirective, blockedURI: e.blockedURI });
  });
`;

type Violation = { directive: string; blockedURI: string };

async function cspViolations(page: Page): Promise<Violation[]> {
  return page.evaluate(
    () => (window as unknown as { __cspViolations?: Violation[] }).__cspViolations ?? [],
  );
}

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m: ConsoleMessage) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(String(e)));
  return errors;
}

test.describe("workspace renders + functions under the strict CSP, cross-engine", () => {
  test("POSITIVE CONTROL: this engine actually detects a CSP violation", async ({ page }) => {
    // If this fails, the CSP detector is broken on this engine and the clean
    // assertion below would be a vacuous green — so this MUST fail, not skip.
    await page.addInitScript(INSTALL_CSP_LISTENER);
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    // Deliberately violate `script-src 'self'` by loading an external script host.
    await page.evaluate(() => {
      const s = document.createElement("script");
      s.src = "https://cdn.jsdelivr.net/npm/rb6-csp-positive-control.js";
      document.head.appendChild(s);
    });
    await expect
      .poll(async () => (await cspViolations(page)).length, {
        timeout: 5_000,
        message:
          "securitypolicyviolation never fired for a blocked external script — " +
          "the CSP detector does not work on this engine, so a clean smoke would be vacuous",
      })
      .toBeGreaterThan(0);
    const violations = await cspViolations(page);
    expect(
      violations.some((v) => /script-src/.test(v.directive)),
      `expected a script-src violation; got: ${JSON.stringify(violations)}`,
    ).toBe(true);
  });

  test("/ui renders, boots, and logs ZERO CSP violations", async ({ page }) => {
    await page.addInitScript(INSTALL_CSP_LISTENER);
    const consoleErrors = collectConsoleErrors(page);
    await page.goto("/ui", { waitUntil: "domcontentloaded" });
    // The app must actually FUNCTION under the CSP — the four model slots
    // populate — not merely deliver a document.
    await waitForComposerReady(page);
    // Let any resource loads that boot() kicked off settle before snapshotting:
    // securitypolicyviolation is dispatched asynchronously, so a violation from
    // a late load would otherwise be missed and the smoke would stay green.
    await page.waitForLoadState("networkidle");
    const violations = await cspViolations(page);
    expect(
      violations,
      `securitypolicyviolation events on /ui:\n${JSON.stringify(violations, null, 2)}`,
    ).toEqual([]);
    const csp = consoleErrors.filter(isCspError);
    expect(csp, `CSP/security console errors on /ui:\n${csp.join("\n")}`).toEqual([]);
  });
});
