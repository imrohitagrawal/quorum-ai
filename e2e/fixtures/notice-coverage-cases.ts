/**
 * One case per ``PROVIDER_NOTICES`` entry that
 * ``e2e/tests/invariants/answer-completeness.spec.ts`` does NOT already cover
 * (that spec seeds ``NOTICE_NO_SOURCES_FOUND`` on the zero-source slot via
 * ``golden-run.ts``). Issue #124: the other 7 registered notices had zero
 * browser-level coverage — reachable and copy-guarded, never proven visible
 * on a real screen.
 *
 * Each ``text`` is quoted VERBATIM from ``PROVIDER_NOTICES``
 * (``src/product_app/providers.py``) —
 * ``tests/unit/test_notice_coverage_spec_sync.py`` pins this table to the
 * registry both ways (no stale copy, no missing notice), the same way
 * ``test_golden_fixture_notice_sync.py`` pins golden-run.ts's single seeded
 * notice.
 */
export interface NoticeCoverageCase {
  label: string;
  text: string;
}

export const NOTICE_COVERAGE_CASES: NoticeCoverageCase[] = [
  {
    label: "search disabled",
    text: "Web search was turned off for this model, so its answer comes from what it learned during training.",
  },
  {
    label: "sources from backup search",
    text: "This model did not return any sources of its own. The sources shown here came from a separate web search, so they do not count toward this run's source support.",
  },
  {
    label: "fallback source support",
    text: "The sources shown here did not come from this model, so they do not count toward this run's source support.",
  },
  {
    label: "demo mode",
    text: "Live model calls are not active for this deployment, so the text shown here was produced by Quorum's local simulation. It is not a real model answer.",
  },
  {
    label: "provider unavailable",
    text: "This model's answer is unavailable.",
  },
  {
    label: "cancelled",
    text: "Cancelled before this model was asked for an answer.",
  },
  {
    label: "run deadline",
    text: "The run reached its time limit before this model answered.",
  },
];
