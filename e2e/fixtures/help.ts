import type { Page } from "@playwright/test";

/**
 * W48 (ADR-0145): the names the help-for-new-users build must use. The
 * acceptance specs (`tests/invariants/help-and-tour.spec.ts`,
 * `tests/signed-in/help-history-hint.spec.ts`) and the shared boot helpers
 * read them from here, so a rename happens in one place.
 *
 * ADR-0145 decision 6: every EXISTING spec keeps its page. The boot helpers
 * that already mark the workspace as seen also mark the three hints as seen,
 * through `markHelpSeen`, so no hint appears in a screenshot, a geometry
 * check or an axe scan that is not about help. Only the help specs start
 * without these keys.
 */

/** One `localStorage` key per hint; the value written on "Got it" is "1". */
export const HELP_HINT_KEYS = {
  estimate: "quorum.hintSeen.estimate",
  trust: "quorum.hintSeen.trust",
  history: "quorum.hintSeen.history",
} as const;

/** The hint notes (role="note") and their "Got it" buttons. */
export const HELP_HINT_IDS = {
  estimate: "help-hint-estimate",
  trust: "help-hint-trust",
  history: "help-hint-history",
} as const;
export const helpHintDismissId = (idea: keyof typeof HELP_HINT_IDS) => `${HELP_HINT_IDS[idea]}-dismiss`;

/** The two "Take the tour" controls, and the tour dialog and its heading. */
export const TOUR_OPENER_NAV_ID = "landing-tour";
export const TOUR_OPENER_PREVIEW_ID = "landing-preview-tour";
export const TOUR_DIALOG_ID = "help-tour";
export const TOUR_HEADING_ID = "help-tour-heading";

/**
 * Mark all three hints as seen before any page script runs, on every load of
 * this page. Call it next to the existing `quorum.workspaceSeen` preset.
 */
export async function markHelpSeen(page: Page): Promise<void> {
  await page.addInitScript((keys: string[]) => {
    for (const key of keys) {
      try {
        window.localStorage.setItem(key, "1");
      } catch (_) {
        /* storage blocked: the page then shows the hints, which only the help specs test */
      }
    }
  }, Object.values(HELP_HINT_KEYS));
}
