# ADR Index

Architecture and method decisions. **Records are superseded, never edited** — when
a decision changes, add a new ADR and mark the old one superseded with links both
ways, so the record shows what was believed on a date and what replaced it.

| ADR | Title | Kind | Status |
|---|---|---|---|
| [ADR-0001](adr/0001-initial-architecture.md) | Initial Architecture | Architecture | Draft |
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

**This index was itself stale** until 2026-07-30: ADR-0002 had existed since
2026-07-19 and was never listed here. A hand-maintained index is a derived fact
living in prose, and derived facts in prose rot — see
`docs/analysis/2026-07-30-session-record.md` §6. It drifted a **second** time on
2026-08-03, when ADR-0004..0007 landed unlisted.

Per that note's own instruction, the fix is no longer manual: this table is
regenerated from `docs/adr/` and **`tests/unit/test_adr_index_matches_directory.py`
fails if it drifts again**. Do not hand-edit rows; add the ADR file and re-run
`python3 scripts/generate_adr_index.py`.
