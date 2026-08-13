# ADR Index

Architecture and method decisions. **Records are superseded, never edited** — when
a decision changes, add a new ADR and mark the old one superseded with links both
ways, so the record shows what was believed on a date and what replaced it.

| ADR | Title | Kind | Status |
|---|---|---|---|
| [ADR-0001](adr/0001-initial-architecture.md) | Initial Architecture | Architecture | Superseded (in part) — implemented and refined piece-by-piece by later ADRs |
| [ADR-0002](adr/0002-sqlite-single-writer-ceiling.md) | SQLite stores stay single-writer (one connection, one lock, no WAL) | Architecture | Accepted — 2026-07-19 (R2 Phase 0, ledger RB-3) |
| [ADR-0003](adr/0003-measure-review-yield-before-setting-a-review-budget.md) | Measure review yield before setting a review budget | Method | Accepted — 2026-07-30 |
| [ADR-0004](adr/0004-spend-cap-fails-open-on-an-untrustworthy-ledger.md) | The per-account spend cap fails OPEN on an untrustworthy ledger | Architecture | Accepted — 2026-08-03 (major-issues batch, issues #101 / #109 / #122 / #123) |
| [ADR-0005](adr/0005-background-reconnect-for-the-durable-stores.md) | Reconnect the durable SQLite stores in the background, not at boot only | Architecture | Accepted — 2026-08-03 (major-issues batch, issue #123) |
| [ADR-0006](adr/0006-high-stakes-scan-excludes-only-our-own-caveat.md) | The high-stakes scan strips our own caveat by token, never by wildcard | Architecture | Accepted — 2026-08-03 (major-issues batch, issue #155) |
| [ADR-0007](adr/0007-suppress-the-readiness-first-paint-time-bounded.md) | Suppress the readiness banner's first paint, with a time bound | Architecture | Accepted — 2026-08-03 (major-issues batch, issue #117) |
| [ADR-0008](adr/0008-the-source-support-denominator-goes-in-the-caption.md) | the Source support denominator goes in the caption, and states no exclusion count | Architecture | Accepted — 2026-08-04 (issue #193) |
| [ADR-0009](adr/0009-mandated-boilerplate-is-not-evidence-of-agreement.md) | sentences the system dictates are stripped before consensus scoring | Architecture | Accepted — 2026-08-04 (issue #180, part 1 of 2) |
| [ADR-0010](adr/0010-an-answer-nobody-asked-for-is-not-evidence.md) | an answer produced without invoking a model is not evidence of agreement | Architecture | Accepted — 2026-08-04 (issue #247, part 2 of 2; part 1 is ADR-0009) |
| [ADR-0011](adr/0011-block-structure-belongs-to-the-block-renderer.md) | block structure belongs to the block renderer, and an inline surface renders the marker instead | Architecture | Accepted — 2026-08-04 (issue #120) |
| [ADR-0012](adr/0012-record-the-billing-evidence-before-reclassifying-a-5xx.md) | record the billing evidence for a provider error, and do not reclassify a 5xx yet | Architecture | Accepted — 2026-08-05 (issue #105) |
| [ADR-0013](adr/0013-a-paid-subsystem-may-not-be-enabled-invisibly.md) | A paid subsystem may not be enabled invisibly | Architecture | Accepted — 2026-08-05 (config-discoverability work package; issues #216, #110) |
| [ADR-0014](adr/0014-vendor-a-markdown-parser-instead-of-hand-rolling-one.md) | Vendor `markdown-it` instead of hand-rolling the renderer | Architecture | Proposed — 2026-08-05 (live-validation session; issue #257) |
| [ADR-0015](adr/0015-how-the-vendored-markdown-parser-is-configured.md) | How the vendored Markdown parser is configured | Architecture | Accepted — 2026-08-05 (issue #257, implementing ADR-0014) |
| [ADR-0016](adr/0016-the-spend-rails-meter-actuals-and-degrade-rather-than-fail-open.md) | The spend rails meter actuals, and degrade rather than fail open | Architecture | Accepted — 2026-08-06 (issues #255 / #256, operator decision the same day) |
| [ADR-0017](adr/0017-the-spend-cap-prices-every-billable-call.md) | The spend cap prices every billable call, including the judge | Architecture | Accepted — 2026-08-06 (issue #265; operator decision the same day that the |
| [ADR-0018](adr/0018-a-judge-that-produced-nothing-must-say-so-and-must-not-be-charged-for.md) | A judge that produced nothing must say so, and must not be charged for | Architecture | Accepted — 2026-08-06 (issue #258; operator decision 2026-08-06 that the |
| [ADR-0019](adr/0019-the-judge-does-not-spend-on-a-run-that-spent-nothing.md) | The judge does not spend on a run that spent nothing | Architecture | Accepted — 2026-08-06 |
| [ADR-0020](adr/0020-a-verified-badge-must-not-contradict-the-verdict-behind-it.md) | A "verified" badge must not contradict the verdict behind it | Architecture | Accepted — 2026-08-06 (issue #267) |
| [ADR-0021](adr/0021-the-judge-must-ask-for-output-it-can-parse.md) | The judge must ask for output it can parse | Architecture | Accepted — 2026-08-07 |
| [ADR-0022](adr/0022-a-credential-is-removed-from-the-test-process-not-hidden-at-the-print-site.md) | A credential is removed from the test process, not hidden at the print site | Architecture | Accepted — 2026-08-07 |
| [ADR-0023](adr/0023-sentry-payloads-are-scrubbed-on-every-path-and-frame-locals-are-not-collected.md) | Sentry payloads are scrubbed on every path, and frame locals are not collected | Architecture | Accepted — 2026-08-07 |
| [ADR-0024](adr/0024-the-deploy-gate-decides-in-python-not-in-a-yaml-condition.md) | The deploy gate decides in Python, not in a YAML condition | Architecture | Accepted — 2026-08-07 |
| [ADR-0025](adr/0025-workflow-run-trigger-names-are-filter-patterns-and-must-be-escaped.md) | `on.workflow_run.workflows` entries are filter patterns, and must be escaped | Architecture | Accepted — 2026-08-07 |
| [ADR-0026](adr/0026-production-is-proven-to-run-mains-tip-not-assumed-to.md) | Production is proven to run `main`'s tip, not assumed to | Architecture | Accepted — 2026-08-08 |
| [ADR-0027](adr/0027-the-judges-evidence-is-a-bounded-and-priced-input.md) | The judge's evidence is a bounded and priced input | Architecture | Accepted — 2026-08-07 (issue #268, the half the issue body does not name) |
| [ADR-0028](adr/0028-spend-belongs-on-the-stage-the-user-reads.md) | Spend belongs on the stage the user reads | Architecture | Accepted — 2026-08-09 (operator decision) |
| [ADR-0029](adr/0029-code-is-consumed-before-the-citation-scan-not-parsed-by-it.md) | The grounding score counts the citations the reader can see | Architecture | Accepted — 2026-08-09 |
| [ADR-0030](adr/0030-a-citation-marker-is-compared-in-the-shape-the-source-store-keeps.md) | A citation marker is compared in the shape the source store keeps, and a terminal run is evaluated once | Architecture | Accepted — 2026-08-10 (issues #285 then #284, in that order) |
| [ADR-0031](adr/0031-three-blocked-issues-get-durable-telemetry-not-a-guessed-fix.md) | Three blocked issues get durable telemetry, not a guessed fix | Architecture | Accepted — 2026-08-10 |
| [ADR-0032](adr/0032-the-copy-describes-the-moderator-the-requirement-keeps-peer-critique.md) | The copy describes the moderator; the requirement keeps peer critique | Architecture | Accepted — 2026-08-11 |
| [ADR-0033](adr/0033-docs-factory-mirror-drops-its-8-duplicate-numbered-files.md) | `docs/factory/` drops its 8 duplicate-numbered files; `docs/` root is canonical | Architecture | Accepted — 2026-08-11 (repo-housekeeping PR 3) |
| [ADR-0034](adr/0034-docs-numbering-scheme-and-ranges.md) | `docs/NN-*.md` numbering ranges are documented and gated | Architecture | Accepted — 2026-08-11 (repo-housekeeping PR 6) |
| [ADR-0035](adr/0035-vendor-project-faq-for-targeted-gap-closing-not-full-regeneration.md) | Vendor `project-faq` for targeted gap-closing, not full-page regeneration | Architecture | Accepted |
| [ADR-0036](adr/0036-global-log-redaction-filter-over-per-call-site-fixes.md) | A global log-redaction step in `JsonFormatter`, not per-call-site fixes | Architecture | Accepted — 2026-08-14 (issue #313) |

**This index was itself stale** until 2026-07-30: ADR-0002 had existed since
2026-07-19 and was never listed here. A hand-maintained index is a derived fact
living in prose, and derived facts in prose rot — see
`docs/analysis/2026-07-30-session-record.md` §6. It drifted a **second** time on
2026-08-03, when ADR-0004..0007 landed unlisted.

Per that note's own instruction, the fix is no longer manual: this table is
regenerated from `docs/adr/` and **`tests/unit/test_adr_index_matches_directory.py`
fails if it drifts again**. Do not hand-edit rows; add the ADR file and re-run
`python3 scripts/generate_adr_index.py`.
