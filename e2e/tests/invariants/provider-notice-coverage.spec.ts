// Issue #124 (follow-up to #114) — only 1 of the registry's 8 provider
// notices had browser-level coverage: NOTICE_NO_SOURCES_FOUND, seeded in
// golden-run.ts and asserted visible by answer-completeness.spec.ts. The
// other 7 were covered as copy (no-developer-speak, complete-sentence rules
// in test_provider_notice_copy.py) and as emission (reachable from the
// provider layer), but nothing proved each one actually reaches a user's
// screen on a real render.
//
// Parameterised over notice-coverage-cases.ts (the model: the registry walk
// in tests/unit/test_provider_notice_copy.py) rather than eight hand-written
// specs, so a ninth registered notice with no case fails
// tests/unit/test_notice_coverage_spec_sync.py before this spec would ever
// need editing.
import { test, expect } from "@playwright/test";
import { driveToResult, driveToTranscript, goldenCompletedRespWithNotice } from "../../fixtures/golden-run";
import { NOTICE_COVERAGE_CASES } from "../../fixtures/notice-coverage-cases";

test.describe("provider notice coverage (issue #124)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "chromium-only gate");

  for (const { label, text } of NOTICE_COVERAGE_CASES) {
    test(`${label} notice is visible where that model's answer is read`, async ({ page }) => {
      await driveToResult(page, goldenCompletedRespWithNotice(text));
      await driveToTranscript(page);
      const notice = page.locator(".transcript-opening-notice").filter({ hasText: text });
      await expect(
        notice.first(),
        `provider notice ${JSON.stringify(text)} must be visible where the ` +
          "reader of that model's answer would see it, not just present in " +
          "the API response"
      ).toBeVisible();
    });
  }
});
