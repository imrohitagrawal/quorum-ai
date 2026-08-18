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

    // SELF-CHECK (#226) — in THIS test, on THIS page, AFTER the two clean
    // claims above. Both channels report "zero" via a `?? []` / an empty array,
    // so "no violations happened" and "nothing was ever collected" are the
    // identical value. Measured 2026-08-17 by mutation on this branch: with
    // the `addInitScript` line above replaced by a no-op, the `toEqual([])` on
    // line 103 stayed GREEN and only the poll below went red; with
    // `collectConsoleErrors` replaced by a bare `[]`, the `toEqual([])` on line
    // 105 stayed GREEN and only the second poll went red. The sibling POSITIVE
    // CONTROL test cannot close that — it proves the engine can detect, on a
    // DIFFERENT page, not that this page's collector is live.
    //
    // Deliberately violate script-src and require BOTH channels to notice.
    // Hermetic: CSP blocks the request before it leaves the browser, so no
    // network call is made and nothing is paid for.
    //
    // Side effect worth knowing, NOT separately measured here: if the served
    // CSP were ever loosened to permit an external script host, this trigger
    // would stop being blocked and both polls below would go red.
    await page.evaluate(() => {
      const s = document.createElement("script");
      s.src = "https://cdn.jsdelivr.net/npm/rb6-csp-selfcheck.js";
      document.head.appendChild(s);
    });
    // Partners the DOM-event channel asserted at the top of this test.
    await expect
      .poll(async () => (await cspViolations(page)).length, {
        timeout: 5_000,
        message:
          "the securitypolicyviolation collector never fired for a deliberately " +
          "blocked external script — so the empty `violations` asserted above " +
          "was a dead collector, not a clean page",
      })
      .toBeGreaterThan(0);
    // Partners the CONSOLE channel asserted at the top of this test. Engines
    // word this differently, which is why `isCspError` is a broad matcher.
    // Measured 2026-08-17 on this exact trigger, one probe run per engine:
    //   chromium — "Loading the script '...' violates the following Content
    //              Security Policy directive: \"script-src 'self' ...\""
    //   firefox  — "Content-Security-Policy: The page's settings blocked a
    //              script (script-src-elem) at ... because it violates the
    //              following directive"
    //   webkit   — "Refused to load ... because it does not appear in the
    //              script-src directive of the Content Security Policy."
    // NO single alternative of `isCspError` covers all three (each alternative
    // tested against each captured message): `content security policy` matches
    // chromium and webkit but NOT firefox, which spells the header hyphenated;
    // `violates the following` matches chromium and firefox but NOT webkit. It
    // takes at least two, so narrowing the matcher to one silently blinds this
    // partner on an engine while leaving it green on the other two.
    await expect
      .poll(() => consoleErrors.filter(isCspError).length, {
        timeout: 5_000,
        message:
          "no CSP console error was captured for a deliberately blocked " +
          "external script — so the empty `csp` asserted above proves nothing",
      })
      .toBeGreaterThan(0);
  });
});
