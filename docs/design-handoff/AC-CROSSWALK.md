# AC-001…049 Crosswalk (Quorum R1 + R2)

Maps every acceptance criterion in `docs/12-acceptance-criteria.md` to the
slice + element/id (UI) or module/test (backend) that satisfies it, with a
coverage verdict. This is the traceability evidence for the Slice V PR gate
(R1) and, for AC-038 onward, the Release-2 reconciliation that closed a
real staleness gap in this document (see `README.md`'s "Known repo
follow-ups").

**Legend:** ✅ met · ◑ partial (noted) · 🔬 verification/telemetry criterion
(satisfied by evidence & tests, not a UI surface) · N/A (no UI surface exists
for this criterion by design).

Slice SHAs: R1 — Slice 0 `3132548` · B1 `d46cb42` · B2 `5a5b9e8` · Slice 1
`15d4636` · Slice 2 `054669a` · Slice 3 `2aa50b5` · Slice 4a `afbe0ea` ·
Slice 4b `e520824` · Slice 5 `e762a79` · Slice 6 `bcee421` · Slice 7
`a367579`. R2 — S2 (evaluation engine) `a1cf546` · S3 (trust-score UI)
`fe254b4` · S4 (golden-set harness) `6a412f8`.

**AC-037** (`Web-search plugin fee is an accepted cost-accounting
exclusion`) has no row of its own in the table below — but it is not
UI-invisible, and the note below states that precisely rather than
implying zero effect. AC-037's own text: the fee "is never surfaced to
the user or on the UI **(at 0.0 it folds invisibly into the total
estimate — no separate line item)**." That parenthetical means the
decision *does* affect what the user sees: the total cost figure
rendered on the cost-gate/estimate views (AC-009/010/027, already in
this table) is ~$0.02 lower than it would be if the fee were priced in.
There is no dedicated UI element for the fee itself — nothing to point a
crosswalk row at — so it stays excluded from the row count, but the
correct framing is "folded into an existing total, not a separate
surface," not "no UI effect." Verified by the existing #18 mechanism
tests.

Note: only 8 AC ids carry an `AC-0NN` marker in `app.js` (AC-001/003/008/010/
015/019/022/032 — the edge states + the consensus gate). The rest are satisfied
by backend modules, `COPY-0NN`-tagged UI, or verification tests; those anchors
are cited explicitly below rather than by an in-code `AC` marker.

| AC | Title | Verdict | Satisfied by (slice · element/id or module) | Evidence / test |
|----|-------|---------|----------------------------------------------|-----------------|
| 001 | Session & provider access required | ✅ | Slice 6 edge **E1** — `#error-region` `Anonymous · AC-001` on boot bootstrap failure (`AUTH_REQUIRED`); readiness probe discloses simulation before any run | `test_query_run_auth_boundary.py::test_query_run_requires_authentication`; readiness startup probe |
| 002 | Session-scoped execution allowed | ✅ | Slice 1 composer → Slice 2 gate → Slice 3 create/poll (valid session + within guardrails starts orchestration) | `test_query_run_auth_boundary.py::test_query_run_accepts_authenticated_account_boundary`, `test_query_run_state_machine.py::test_query_run_allows_expected_execution_transitions` |
| 003 | Duplicate active query blocked | ✅ | Slice 6 edge **E2** — `#error-region` `Active query exists · AC-003` on 409 `ACTIVE_QUERY_EXISTS`; "Go to run"/"Stop it & start new" | `test_query_run_state_machine`; `test_active_query_endpoint_returns_empty_after_completed_run` |
| 004 | Active query slot released | ✅ | Backend state machine releases the slot at terminal; UI `goToActiveRun`/`stopActiveRunAndCompose` reflect it | `test_completed_query_run_releases_active_slot_for_same_account`, `test_terminal_state_releases_active_slot` |
| 005 | High-stakes warning shown | ✅ | Slice 1 `#high-stakes-gate` + `#high-stakes-ack` (**COPY-002** verbatim, ack required, race-fixed); Slice 4a verdict framed decision-support | `test_high_stakes_query_requires_high_stakes_acknowledgement`, `test_high_stakes_synthesis_includes_decision_support_notice` |
| 006 | Sensitive-data warning before submission | ✅ | Slice 1 `.privacy-notice role="note"` (**COPY-001** verbatim) at composer | `test_query_run_safety_warnings` (warning acknowledgements) |
| 007 | Default models populated | ✅ | Slice 1 model slots pre-fill the four defaults (`openai/gpt-4o-mini`, `anthropic/claude-haiku-4.5`, `google/gemini-2.5-flash`, `nvidia/nemotron-3-nano-30b-a3b`) | `test_model_slots.py::test_default_model_slots_returns_four_numbered_slots` |
| 008 | Model slots replaceable | ✅ | Slice 1 free-choice swap (`[data-model-slot-select]`); Slice 6 edge **E5** `#error-region` `Invalid model slot · AC-008` on 422 `slot_errors[]` | `test_model_slots.py::test_model_slot_validator_accepts_four_openrouter_style_model_ids`; UI E5 |
| 009 | Normal-cost query proceeds | ✅ | Slice 2 cost-gate **allow** sub-state (≤ $0.15 auto-proceeds, no extra confirm) | `test_normal_cost_query_is_allowed` |
| 010 | High-cost confirm / block | ✅ | Slice 2 **confirm** ($0.15–0.25, **COPY-003**, `#gate-confirm`) + **block** (> $0.25, **COPY-004** verbatim block band); edge **E6** | `test_high_cost_query_requires_matching_confirmation`, `test_over_limit_cost_query_is_blocked` |
| 011 | OpenRouter search attempted first | ✅ 🔬 | Backend provider path attempts OpenRouter before fallback | `test_provider_stub_returns_openrouter_path_when_live_response_succeeds` |
| 012 | Search fallback used on failure | ✅ | Backend fallback + records fallback usage; Slice 3 `#live-fallback` / Slice 5 honest provider tag "Fallback search ×N" (no fabricated Tavily) | `test_provider_stub_uses_fallback_when_openrouter_sources_are_unusable` |
| 013 | Source links visible | ◑ | Slice 5 transcript + Slice 4a source card show non-fallback source **count** near each model answer; discrete link list via `renderSourceList` where sources present | `test_completed_query_run_result_returns_visible_initial_answer_sources`. ◑ R1 surfaces counts + available links honestly; per-claim link anchoring is backend-limited. |
| 014 | Per-model output captured | ✅ | Slice 3 `#live-model-status` (id/status/latency/fallback) + Slice 5 transcript opening positions (`model_answers`) | `test_result_endpoint_projects_model_answers_debate_cost_elapsed_and_synthesis` |
| 015 | Provider failure visible w/o secrets | ✅ | Slice 6 edge **E3** `showProviderFailure` → `#error-region` `Provider failure · AC-015`; user-safe, no secrets/slot# | `test_result_endpoint_projects_provider_failure_notice_without_secrets`, `test_provider_failure_metadata_is_user_safe_and_non_secret` |
| 016 | First critique round runs | ✅ 🔬 | Backend debate round 1; Slice 3 5-stage strip (`debate_round_1`) + Slice 5 round-level critique | `test_debate_stub_runs_two_structured_critique_rounds` |
| 017 | Second critique round runs | ✅ 🔬 | Backend debate round 2 (partial-plan aware); Slice 3 stage strip / Slice 5 rounds | `test_debate_stub_runs_two_structured_critique_rounds`, `..._returns_partial_plan_when_second_round_exceeds_budget` |
| 018 | Synthesis separates consensus/disagreement | ✅ | Slice 4a trust triangle + `renderDebateAndSynthesis` surface consensus / disagreement / source support / uncertainty / recommendation sections | `test_synthesis.py::test_synthesis_stub_returns_required_sections_and_quality_checks` |
| 019 | Contradictions preserved (no false consensus) | ✅ | Slice 4a/5 **`isConsensusResult`** gate (single source of truth, `AC-019` marker) — green only on true consensus; divided → amber, disagreement preserved | `test_synthesis` quality_checks; UI gate |
| 020 | Recommendation = decision support | ✅ | Slice 4a verdict = `recommendation` verbatim, framed decision-support; **COPY-002**; high-stakes synthesis notice | `test_high_stakes_synthesis_includes_decision_support_notice` |
| 021 | Hard timeout → terminal response | ✅ 🔬 | Backend 180s → terminal partial/failure; Slice 3 `timed_out` → TIMEOUT banner, elapsed frozen | `test_timed_out_terminal_state_records_missing_steps` |
| 022 | Partial results identify missing steps | ✅ | Slice 3/4 edge **E4** — `status==="partial"` → result view + `#live-notices`/result notices identify failed vs used (`AC-022` marker) | `test_partial_terminal_state_records_missing_steps` |
| 023 | App-owned keys stay server-side | ✅ 🔬 | No key in browser payloads/logs; server-only config | `test_provider_secret_values_do_not_leak_into_responses_or_events` |
| 024 | Secret redaction verified | ✅ 🔬 | Backend redacts credentials on failure, stores only non-secret metadata | `test_release_security_redaction`, `test_provider_failure_metadata_is_user_safe_and_non_secret` |
| 025 | Provider access from server config | ✅ 🔬 | Credentials sourced from env on server; never exposed to browser | `test_query_run_auth_boundary`; readiness probe |
| 026 | No user-entered provider-key field | ✅ | Slice 0/composer — `templates/workspace.html` has **no** key/secret/token input field (verified) | grep of template: `NO key/secret input fields` |
| 027 | Full result components displayed | ✅ | Slice 4a/4b/5 — model answers, sources, debate, synthesis, cost (est→actual), elapsed, provider-failure notices | `test_result_endpoint_projects_model_answers_debate_cost_elapsed_and_synthesis` |
| 028 | Result structure supports comparison | ✅ | Slice 4b positions table + Slice 5 transcript keep model-level output distinct from debate & synthesis | `test_result_endpoint_projects...`; UI distinct panels |
| 029 | Latency target measured | ◑ | NFR verification criterion — **not met by measurement**. Only a **stubbed** in-process smoke test exists (single sequential call, `<2s` wall-clock, no percentiles/load); the P50/P95/hard-timeout targets are not measured at scale (`docs/55-performance-baseline.md` Evidence = "not available"). Honestly disclosed. | `tests/perf/test_query_run_performance_evidence.py::test_stubbed_workflow_meets_local_performance_and_observability_contract` |
| 030 | Cost target measured | 🔬 | Cost telemetry + guardrail thresholds (quantized, output-token band) | `test_cost_estimate_is_quantized_to_four_decimal_places`, `test_cost_estimate_includes_output_tokens_in_band`, daily-cap tests |
| 031 | Citation coverage measured | ✅ 🔬 | B2 `citation_coverage` / material-claim count; Slice 4a source card shows claim-coverage % | `test_result_endpoint_projects_material_claim_count_and_live_counts`, `test_estimate_material_claim_count_with_real_stub_text_returns_2` |
| 032 | Wrong-account access denied | ✅ | Slice 6 edge **E7** — **404 `QUERY_RUN_NOT_FOUND`** non-disclosing (`AC-032` marker); owner-scoped repo | `test_query_run_repository_keeps_model_answers_owner_scoped` |
| 033 | Sensitive-data copy not contradicted | ✅ | Slice 7 landing disclaimers + **COPY-001**; no page claims MVP safe for secrets/regulated data | Content audit; `test_landing_preview_is_labelled_illustrative` |
| 034 | High-stakes coverage tested | ✅ 🔬 | Regression covers medical/legal/financial/safety/regulated → decision-support language | `test_high_stakes_query_requires_high_stakes_acknowledgement`, `test_high_stakes_synthesis_includes_decision_support_notice` |
| 035 | Accessibility baseline verified | ✅ | **Committed axe drive** (`e2e/tests/accessibility/axe-all-views.spec.ts`, `@axe-core/playwright`, every view × light+dark) — 0 critical/serious violations; found+fixed 3 real bugs (dark theming, `aria-valid-attr-value`, dark muted contrast). Reproducible via `webServer`. Static a11y contract also asserts labels/landmarks/skip-link. | `e2e/tests/accessibility/axe-all-views.spec.ts`; `docs/design-handoff/AXE-EVIDENCE.md`; `tests/accessibility/test_browser_ui_accessibility_contract.py` |
| 036 | Observability events emitted | ✅ 🔬 | Non-secret structured events per stage (submission→providers→fallback→debate→synthesis→terminal) | `test_provider_events_are_non_secret_and_record_source_count`, perf/observability contract |
| 038 | Terminal run persisted with verbatim cost provenance | 🔬 | R2 S1 — `run_history_store`; row's cost fields identical to the served projection | `tests/integration/test_query_run_history_persist.py::test_completed_run_persisted_with_verbatim_cost_and_survives_eviction` |
| 039 | Run-history row is PII-minimised | 🔬 | R2 S1 — query text/answer prose never persisted, metrics only | `tests/unit/test_run_history_store.py` |
| 040 | Persistence is durable, idempotent, non-blocking | 🔬 | R2 S1 — `INSERT OR REPLACE`; persistence failure swallowed, run state unaffected | `tests/unit/test_run_history_store.py` (idempotency + best-effort); integration survives-eviction assertion |
| 041 | Layer-A evaluation computed, honest, persisted | 🔬 | R2 S2 `a1cf546` — `evaluation.py`, zero-I/O deterministic scoring, `support_verified` suppression | `tests/unit/test_evaluation_layer_a.py`; `tests/evals/test_output_correctness_gate.py` (OC-2 honesty rule); `tests/integration/test_query_run_evaluation_endpoint.py` |
| 042 | Judge OFF is a proven no-op vs. stub | 🔬 | R2 S2 `a1cf546` — zero seam calls when key unset; score identical judge-off vs. stub-on | `tests/unit/test_evaluation_neutrality.py` (seam spy + score equality); `tests/unit/test_evaluation_judge.py` |
| 043 | Evaluation inherits the run's account boundary | ✅ 🔬 | R2 S2 `a1cf546` — 401 unauthenticated / 404 cross-account, no `evaluation` payload leaked either way | `tests/unit/test_evaluation_auth_boundary.py`; `tests/integration/test_query_run_evaluation_endpoint.py` |
| 044 | Trust surface renders no number, no confident label | ✅ | R2 S3 `fe254b4` — screen **05b** `#result-trust-score`; disclosure + one state line + ≤3 "why" lines, zero digits/label-words, `role="group"` not a value widget, hidden when absent | `e2e/tests/invariants/trust-score-invariants.spec.ts`; `e2e/tests/invariants/real-integration-smoke.spec.ts` |
| 045 | A run whose citations couldn't be checked never presents a confident verdict | ✅ | R2 S3 `fe254b4` — screen **05b** indeterminate state fails closed; missing-caveat amber row independent of the state line | `e2e/tests/degraded/degraded-banner.spec.ts`; `tests/unit/test_evaluation_presentation_confidence.py`; `tests/integration/test_query_run_evaluation_endpoint.py` |
| 046 | Trust surface is never green, is accessible, does not clip/overlap | ✅ | R2 S3 `fe254b4` — screen **05b**, GREEN RULE extended (see `README.md` Design Tokens); token-source-computed style check, no overlap/clip, 3 viewports × 2 themes | `e2e/tests/invariants/trust-score-invariants.spec.ts`; `e2e/tests/accessibility/axe-all-views.spec.ts` (scoped `#result-trust-score` scan, see `AXE-EVIDENCE.md`); `e2e/tests/invariants/trust-score-visual.spec.ts` |
| 047 | Golden set pins the engine's structural verdicts hermetically | 🔬 | R2 S4 `6a412f8` — `tests/evals/golden/cases/`, zero-I/O parametrised gate | `tests/evals/test_golden_set_gate.py`; `tests/evals/golden/loader.py` |
| 048 | Subject-matter labels deferred, never fabricated | 🔬 | R2 S4 `6a412f8` — 4 `needs_human_label` cases, loader/gate reject a `correctness` field in the fixture; operator queue tracks separately | `tests/evals/test_golden_set_gate.py::test_human_label_cases_defer_subject_matter_correctness_and_carry_no_label`, `::test_the_operator_queue_names_every_human_label_case` |
| 049 | Real judge wired in, unlocks a score only when configured, OFF by default | 🔬 | R2 S3/S4 — verified branch in screen **05b** above; memoised per run, fails closed on any tamper/near-miss; byte-identical to judge-off when unconfigured | `tests/integration/test_judge_request_path_wiring.py`; `tests/contract/test_golden_fixture_matches_served_schema.py`; `e2e/tests/invariants/trust-score-invariants.spec.ts` |

## Coverage summary
- **48 / 48 UI-relevant criteria mapped** (AC-001…036 + AC-038…049; AC-037 excluded — no dedicated UI surface, see the note above the table). Re-counted directly against the table rather than carried forward: **37 ✅ fully met** (33 from R1 + 4 from R2: AC-043/044/045/046), **2 ◑ partial** (AC-013, AC-029, both R1), **9 🔬-only** verification/telemetry rows with no dedicated UI surface (AC-030 from R1, plus 8 from R2: AC-038/039/040/041/042/047/048/049) — all noted, none a merge blocker. **This corrects the original crosswalk's own summary**, which said "33 ✅, 3 ◑ partial" (36 total) — AC-030 was always 🔬-only in the table itself (never carried a ✅), so the true original R1 split was 33 ✅ / 2 ◑ / 1 🔬-only, not 33/3/0. `SLICE_STATE.md`'s separate historical note ("34 met, 2 partial") is a different, also-uncorrected count from the same period — left as the frozen historical record it is, not reconciled here.
  - **AC-013** — source *links* are surfaced as honest per-model source **counts** + the available link list; per-material-claim link anchoring is bounded by the R1 backend projection (documented, not fabricated).
  - **AC-029** — the latency NFR target is **not measured at scale**: the only automated evidence is a stubbed `<2s` smoke test (no P50/P95, no load). Honestly disclosed (`docs/55-performance-baseline.md` = "not available"); a load/percentile harness is follow-up work, not a UI-branch blocker.
  - Every other AC is met; 🔬-tagged rows (including AC-030) are verification/telemetry criteria satisfied by tests + evidence rather than a dedicated UI surface.
- **AC-035** was upgraded from an ephemeral manual drive to a **committed, reproducible** `@axe-core/playwright` spec (see `AXE-EVIDENCE.md`) after the PR-review gate flagged the evidence as non-auditable.
- **Honesty invariant held:** no AC is "met" by fabricated UI. Where the backend does not supply a signal (per-model debate transcript, per-stage cost/timing, Tavily provider, correlation_id on some envelopes), the UI drops or degrades honestly rather than inventing it.
