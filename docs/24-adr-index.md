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
| [ADR-0036](adr/0036-query-runs-splits-into-api-and-orchestration-modules.md) | `query_runs.py` splits into a thin `query_api` layer and a new `query_run_orchestration` module | Architecture | Accepted — 2026-08-14 (#303) |
| [ADR-0037](adr/0037-debate-usage-prices-by-actual-model-timeout-unchanged.md) | Debate usage prices by the model actually billed; the debate timeout stays 8.0s, unproven either way | Architecture | Accepted — 2026-08-14 |
| [ADR-0038](adr/0038-guard-tests-prove-they-bite-via-artifact-mutation-not-tests-mutation.md) | A guard test proves it bites by mutating the artifact it asserts about, not by mutating `tests/` | Architecture | Accepted — 2026-08-14 (#143, #167) |
| [ADR-0039](adr/0039-constant-and-enum-pin-detectors-close-known-gaps.md) | The constant-pin and enum-pin detectors close their stated gaps, with a deliberately conservative reachability rule | Architecture | Accepted — 2026-08-14 (#145, #160) |
| [ADR-0040](adr/0040-global-log-redaction-filter-over-per-call-site-fixes.md) | A global log-redaction step in `JsonFormatter`, not per-call-site fixes | Architecture | Accepted — 2026-08-14 (issue #313) |
| [ADR-0041](adr/0041-record-factory-redaction-closes-the-sentry-bypass.md) | Redact at the log-record factory, not only in `JsonFormatter` | Architecture | Accepted — 2026-08-14 (issue #313, PR #315 review follow-up) |
| [ADR-0042](adr/0042-module-level-idempotency-flag-for-chained-record-factories.md) | A module-level flag governs `install_redaction_record_factory` idempotency, not a marker on the current factory | Architecture | Accepted — 2026-08-14 (issue #313, PR #315 round-2 review follow-up) |
| [ADR-0043](adr/0043-claude-settings-and-memory-stay-untracked.md) | `.claude/` (agent hooks, permissions, and memory) stays untracked, local-only | Architecture | Accepted — 2026-08-14 (issue #242) |
| [ADR-0044](adr/0044-mutation-scope-dead-glob-detection-stays-pure-ast.md) | Dead-glob detection in the mutation scope stays pure-`ast`, not `mutmut` internals | Architecture | Accepted — 2026-08-14 (#146) |
| [ADR-0045](adr/0045-session-handoff-live-state-degrades-per-value-not-all-or-nothing.md) | `make handoff`'s live state degrades per-value, not all-or-nothing | Architecture | Accepted — 2026-08-14 |
| [ADR-0046](adr/0046-extra-redaction-walks-dict-and-list-values-recursively.md) | `extra={...}` redaction walks dict/list/tuple/set values recursively, bounded by a depth/cycle guard | Architecture | Accepted — 2026-08-14 (issue #313 residual gap) |
| [ADR-0047](adr/0047-gate-detectors-resolve-ambiguity-toward-a-red-gate.md) | Static gate detectors resolve an ambiguous case toward a RED gate, and bound how far they may guess | Architecture | Accepted — 2026-08-15 (#326, #325) |
| [ADR-0048](adr/0048-a-positive-partner-must-survive-the-defect-class-the-file-exists-for.md) | A positive partner must survive the defect class its file exists for | Architecture | Accepted — 2026-08-17 (issue #226) |
| [ADR-0049](adr/0049-annotated-waiver-for-unscoped-event-recorder-reads.md) | Unscoped event-recorder reads are gated by an annotated waiver, not a blanket ban | Architecture | Accepted — 2026-08-15 (#209, follow-up to #104 item 1) |
| [ADR-0050](adr/0050-duplicate-adr-numbers-are-refused-at-both-discovery-points.md) | Duplicate ADR numbers are refused at both discovery points, and a gap is not a defect | Architecture | Accepted — 2026-08-17 (issue #332) |
| [ADR-0051](adr/0051-the-judge-checks-the-spend-rails-instead-of-billing-from-a-read-path.md) | The judge checks the spend rails instead of billing from a read path | Architecture | Accepted — 2026-08-17 |
| [ADR-0054](adr/0054-no-network-intermediary-so-the-403-shape-capture-is-removed.md) | No network intermediary is configured, so the 403 shape-capture is removed | Architecture | Accepted — 2026-08-18 |
| [ADR-0055](adr/0055-a-durable-audit-row-never-asserts-a-verdict-the-run-did-not-get.md) | A durable audit row never asserts a verdict the run did not get | Architecture | Accepted — 2026-08-18 |
| [ADR-0056](adr/0056-extra-redaction-covers-key-object-and-cycle-positions.md) | Extra redaction covers the key, object and cycle positions, and a back-edge becomes a placeholder | Architecture | Accepted — 2026-08-18 |
| [ADR-0057](adr/0057-the-mutation-gate-is-a-regression-detector-and-must-reach-the-real-tree.md) | The mutation gate is kept as a regression detector, and its root resolution must reach the real tree | Architecture | Accepted — 2026-08-19 |
| [ADR-0058](adr/0058-guard-tests-run-in-a-required-pytest-lane.md) | The negative-assertion guard's own tests run in a required pytest lane, and refuse to skip there | Architecture | Accepted — 2026-08-19 (part of issue 226; the classifier half is a separate change) |
| [ADR-0059](adr/0059-guard-resolves-computed-member-properties-and-fails-closed.md) | The negative-assertion guard resolves a member property through both `Identifier.name` and a static literal, and fails closed when it cannot | Architecture | Accepted — 2026-08-19 (issue 226; ADR-0058 was the first half, this is the classifier half) |
| [ADR-0060](adr/0060-live-execution-is-switched-on-only-to-collect-a-sample.md) | Live execution is switched on only to collect a sample, and switched back off | Architecture | Accepted — 2026-08-19 |
| [ADR-0061](adr/0061-apt-dependent-ci-steps-bound-their-own-time.md) | apt bounds each request, and every apt-dependent step bounds its own time | Architecture | Accepted — 2026-08-19 |
| [ADR-0062](adr/0062-the-agreement-tally-is-captioned-as-what-it-measures.md) | The agreement tally is captioned as what it measures, and never inverts on a split panel | Architecture | Accepted — 2026-08-21 |
| [ADR-0063](adr/0063-the-result-view-carries-the-panels-reasoning.md) | The result view carries the panel's reasoning; the inferred position table goes | Architecture | Accepted — 2026-08-22 |
| [ADR-0064](adr/0064-the-displayed-estimate-prices-the-judge.md) | The displayed estimate prices the Layer-B judge | Architecture | Accepted — 2026-08-22 |
| [ADR-0065](adr/0065-the-mutation-scope-names-its-oracle-tests-and-a-truncated-run-is-not-a-score.md) | The mutation scope names its oracle tests, and a truncated run is not a score | Architecture | Accepted — 2026-08-23 |
| [ADR-0066](adr/0066-a-negated-issue-close-is-caught-in-the-two-places-it-can-happen.md) | A negated issue close is caught in the two places it can happen | Architecture | Accepted — 2026-08-24 |
| [ADR-0067](adr/0067-consensus-is-claimed-on-evidence-not-on-a-failure-to-detect-disagreement.md) | Consensus is claimed on evidence, not on a failure to detect disagreement | Architecture | Accepted — 2026-08-24 |
| [ADR-0068](adr/0068-session-residue-is-eight-named-categories-each-with-one-verb.md) | Session residue is eight named categories, each with one verb | Architecture | Accepted — 2026-08-25 |
| [ADR-0069](adr/0069-an-equivalent-mutant-is-removed-not-recorded.md) | An equivalent mutant is removed from the code, not recorded in a list | Architecture | Accepted — 2026-08-25 |
| [ADR-0070](adr/0070-a-money-spending-posture-is-declared-before-it-is-switched-on.md) | A money-spending posture is declared before it is switched on | Architecture | Accepted — 2026-08-25 |
| [ADR-0071](adr/0071-live-execution-is-the-steady-state-so-the-declaration-is-re-affirmed-not-time-boxed.md) | Live execution is the steady state, so the declaration is re-affirmed rather than time-boxed | Architecture | Accepted — 2026-08-25 |
| [ADR-0072](adr/0072-a-child-process-is-denied-the-parents-coverage-environment.md) | A child process is denied the parent's coverage environment, in one place, and a gate keeps it that way | Architecture | Accepted — 2026-08-25 |
| [ADR-0073](adr/0073-sessions-are-as-durable-as-the-cap-that-counts-them.md) | Sessions are as durable as the cap that counts them | Architecture | Accepted — 2026-08-26 |
| [ADR-0074](adr/0074-a-charge-records-whether-the-run-could-spend.md) | A charge records whether the run could spend, and each rail reads the meter that matches what it protects | Architecture | Accepted — 2026-08-26 |
| [ADR-0075](adr/0075-the-moderators-bar-is-a-majority-the-overlap-bar-is-not.md) | The moderator's bar is a strict majority of the panel it read; the overlap bar is not | Architecture | Accepted — 2026-08-26 |
| [ADR-0076](adr/0076-a-reader-gets-its-own-tree-and-an-unread-citation-does-not-set-a-cap.md) | A reader gets its own tree, an unread citation does not set a cap, and a gate's exit status is never read through a pipe | Architecture | Accepted — 2026-08-26 |
| [ADR-0077](adr/0077-the-response-body-decides-the-outcome-and-a-dispatched-call-that-answered-nothing-leaves-evidence.md) | The response body decides the outcome, and a dispatched call that answered nothing leaves evidence | Architecture | Accepted — 2026-08-26 |
| [ADR-0078](adr/0078-a-provider-call-gets-a-total-time-budget-because-a-per-recv-timeout-is-not-one.md) | A provider call gets a total time budget, because a per-`recv` timeout is not one | Architecture | Accepted — 2026-08-26 |
| [ADR-0079](adr/0079-the-open-work-board-is-checked-against-the-tree-not-trusted.md) | The open-work board is checked against the tree, not trusted | Architecture | Accepted — 2026-08-28 |
| [ADR-0080](adr/0080-the-catalog-endpoint-follows-the-configured-base-url.md) | The catalog endpoint follows the configured base URL | Architecture | Accepted — 2026-08-28 |
| [ADR-0081](adr/0081-the-per-call-money-constants-wait-for-a-measured-290.md) | The per-call money constants wait for a measured #290 | Architecture | Accepted — 2026-08-28 |
| [ADR-0082](adr/0082-the-app-keeps-scaling-to-zero.md) | The app keeps scaling to zero | Architecture | Accepted — 2026-08-28 |
| [ADR-0083](adr/0083-consensus-strength-requires-a-genuine-mutual-cluster.md) | Consensus strength requires a genuine mutual cluster, and a panel of one has none | Architecture | Accepted — 2026-08-28 |
| [ADR-0084](adr/0084-the-provider-service-streams-and-a-stream-must-say-it-finished.md) | The provider service streams, and a stream must say it finished | Architecture | Accepted — 2026-08-30 |
| [ADR-0085](adr/0085-a-credential-only-travels-over-https-or-to-loopback.md) | A credential only travels over https, or to loopback | Architecture | Accepted — 2026-09-01 |
| [ADR-0086](adr/0086-the-moderator-grading-its-own-answer-is-reported-not-refused.md) | The moderator grading its own answer is reported, not refused | Architecture | Accepted — 2026-09-01 |
| [ADR-0087](adr/0087-a-panel-of-one-is-not-a-panel-that-agreed.md) | A panel of one is not a panel that agreed | Architecture | Accepted — 2026-09-01 |
| [ADR-0088](adr/0088-spec-docs-name-the-default-slots-a-gate-proves-it.md) | Docs name the shipped default slots, and a gate proves it | Architecture | Accepted — 2026-09-01 (board row W17) |
| [ADR-0089](adr/0089-a-timing-gate-asserts-the-argument-not-the-wall-clock.md) | A timing gate asserts the argument, not the wall clock | Architecture | Accepted — 2026-09-01 (board row W19) |
| [ADR-0090](adr/0090-a-credential-does-not-follow-a-redirect-and-tavily-gets-the-same-scheme-check.md) | A credential does not follow a redirect, and Tavily gets the same scheme check | Architecture | Accepted — 2026-09-01 |

**This index was itself stale** until 2026-07-30: ADR-0002 had existed since
2026-07-19 and was never listed here. A hand-maintained index is a derived fact
living in prose, and derived facts in prose rot — see
`docs/analysis/2026-07-30-session-record.md` §6. It drifted a **second** time on
2026-08-03, when ADR-0004..0007 landed unlisted.

Per that note's own instruction, the fix is no longer manual: this table is
regenerated from `docs/adr/` and **`tests/unit/test_adr_index_matches_directory.py`
fails if it drifts again**. Do not hand-edit rows; add the ADR file and re-run
`python3 scripts/generate_adr_index.py`.
