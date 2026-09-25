# Acceptance Criteria

## Account And Quota

## AC-001 Session and provider access required

Given a visitor has not established a valid browser session or the server does not have provider access configured, when they attempt to submit a query for execution, then the system blocks execution and explains the missing prerequisite.

- Requirement: FR-001, NFR-005
- Test: TEST-FR-001

## AC-002 Session-scoped execution allowed

Given a user has a valid browser session, server-configured provider access, and no active running query, when they submit a valid query within cost guardrails, then the system accepts the query and starts orchestration.

- Requirement: FR-001, NFR-005
- Test: TEST-FR-001

## AC-003 Duplicate active query blocked

Given a browser session already has a running query, when another query is submitted from the same session, then the system rejects the second execution and explains that one active query is allowed at a time.

- Requirement: FR-002
- Test: TEST-FR-002

## AC-004 Active query slot released

Given a running query completes, fails with a terminal error, or reaches the hard timeout, when the terminal status is recorded, then the browser session can submit a new query.

- Requirement: FR-002
- Test: TEST-FR-002

## Safety And Privacy

## AC-005 High-stakes warning shown

Given the workflow is used for medical, legal, financial, safety, or regulated topics, when the user prepares to submit or view results, then the system shows decision-support-only language and does not present the output as professional advice or an automated decision.

- Requirement: FR-003, NFR-008
- Test: TEST-FR-003, TEST-NFR-008

## AC-006 Sensitive-data warning shown before submission

Given a user is on the query submission screen, when they prepare to submit a query, then the system warns them not to submit sensitive, private, secret, or confidential data until privacy controls are finalized.

- Requirement: FR-003, NFR-007
- Test: TEST-FR-003, TEST-NFR-007

## AC-007 Default models populated

Given an authenticated user opens the query workflow for the first time, when the model selector loads, then four slots are populated with `openai/gpt-4o-mini`, `anthropic/claude-haiku-4.5`, `google/gemini-2.5-flash`, and `nvidia/nemotron-3-nano-30b-a3b`.

- Requirement: FR-004
- Test: TEST-FR-004

## AC-008 Model slots replaceable

Given an authenticated user selects valid OpenRouter-supported model identifiers for one or more slots, when they save or submit the configuration, then the system uses the selected model identifiers for that query.

- Requirement: FR-004
- Test: TEST-FR-004

## Cost Guardrails

## AC-009 Normal-cost query proceeds

Given an authenticated user submits a valid query with estimated cost at or below USD 0.15, when the estimate is calculated, then the system can proceed without extra cost confirmation.

- Requirement: FR-005, NFR-002
- Test: TEST-FR-005, TEST-NFR-002

## AC-010 High-cost query requires confirmation or block

Given an authenticated user submits a query with estimated cost above USD 0.15, when the estimate is calculated, then the system requires explicit confirmation, and if the estimate is above USD 0.25 the system blocks execution or follows a product-approved override path.

- Requirement: FR-005, NFR-002
- Test: TEST-FR-005, TEST-NFR-002

## Search And Initial Answers

## AC-011 OpenRouter search attempted first

Given an accepted query starts, when the system prepares source-backed answering, then it attempts OpenRouter search before any fallback provider.

- Requirement: FR-006, NFR-003
- Test: TEST-FR-006

## AC-012 Search fallback used on failure

Given OpenRouter search fails or returns no usable source support, when the approved fallback provider is configured, then the system attempts Tavily or the approved free-search fallback and records fallback usage.

- Requirement: FR-006, NFR-004
- Test: TEST-FR-006, TEST-NFR-004

## AC-013 Source links visible for source-backed answers

Given a model answer is produced with source-backed search, when the answer is displayed, then the related source links are visible near that model answer.

- Requirement: FR-006
- Test: TEST-FR-006

## AC-014 Per-model output captured

Given a selected model returns an answer, when the system stores the result, then it records model identifier, answer text, source links, completion status, latency, and non-secret error metadata.

- Requirement: FR-007
- Test: TEST-FR-007

## AC-015 Provider failure visible without secrets

Given a selected model or provider fails, when results are displayed or logged, then the system shows a user-safe failure notice and does not expose provider secrets, raw credentials, or sensitive internal configuration.

- Requirement: FR-007, FR-011, NFR-006
- Test: TEST-FR-007, TEST-FR-011, TEST-NFR-006

## Debate And Synthesis

## AC-016 First critique round runs

Given initial model answers are available or partial results are recoverable, when debate starts, then the system runs a first critique round focused on disagreement, weak support, and missing reasoning.

- Requirement: FR-008
- Test: TEST-FR-008

## AC-017 Second critique round runs

Given the first critique round completes within timeout guardrails, when the workflow continues, then the system runs a second critique round before final synthesis.

- Requirement: FR-008
- Test: TEST-FR-008

## AC-018 Synthesis separates consensus and disagreement

Given debate output is available, when the final answer is generated, then the synthesis has separate sections for consensus, disagreement, source support, uncertainty, and final recommendation.

- Requirement: FR-009, NFR-003
- Test: TEST-FR-009, TEST-NFR-003

## AC-019 Contradictions preserved

Given models materially disagree, when the final synthesis is displayed, then the system includes the disagreement and does not present a false consensus.

- Requirement: FR-009
- Test: TEST-FR-009

## AC-020 Recommendation remains decision support

Given the final synthesis includes a recommendation, when the recommendation is displayed, then it is framed as decision support and includes uncertainty where evidence is incomplete or conflicting.

- Requirement: FR-009
- Test: TEST-FR-009

## Timeout, Partial Results, And Presentation

## AC-021 Hard timeout produces terminal response

Given a query reaches 720 seconds without full completion, when the timeout is reached, then the system returns a completed partial-result response or a terminal failure state with an explanation.

- Requirement: FR-010, NFR-001, NFR-004
- Test: TEST-FR-010, TEST-NFR-001, TEST-NFR-004

## AC-022 Partial results identify missing steps

Given one or more model, search, debate, or synthesis steps fail while other useful results exist, when the user views the result, then the system identifies which steps failed and which outputs were used.

- Requirement: FR-010, NFR-004
- Test: TEST-FR-010, TEST-NFR-004

## AC-023 App-owned keys remain server-side

Given the system uses app-owned OpenRouter, Tavily, or fallback provider keys, when browser payloads, logs, prompts, errors, and analytics events are generated, then those keys are absent.

- Requirement: FR-011, NFR-006
- Test: TEST-FR-011, TEST-NFR-006

## AC-024 Secret redaction verified

Given provider calls fail or raise exceptions, when errors are handled, then the system redacts provider credentials and stores only non-secret diagnostic metadata.

- Requirement: FR-011, NFR-006
- Test: TEST-FR-011, TEST-NFR-006

## AC-025 Provider access sourced from server config

Given the server is configured with provider credentials from environment variables, when a browser session runs queries, then the system uses those credentials only on the server and never exposes them in the browser.

- Requirement: FR-011, NFR-006
- Test: TEST-FR-011, TEST-NFR-006

## AC-026 No user-entered provider key field

Given a user opens the query workflow, when the workspace loads, then no user-entered provider-key field is shown and no provider key is stored in the browser.

- Requirement: FR-011, FR-012, NFR-006
- Test: TEST-FR-011, TEST-FR-012, TEST-NFR-006

## AC-027 Full result components displayed

Given a query reaches completed or partial-result status, when the result page loads, then it displays model answers, source links, debate outputs, final synthesis, cost information, current time context, elapsed time, and provider failure notices where applicable.

- Requirement: FR-013, NFR-010
- Test: TEST-FR-013, TEST-NFR-010

## AC-028 Result structure supports comparison

Given four model answers are available, when the user reviews the result, then the UI keeps model-level outputs distinguishable from debate output and final synthesis.

- Requirement: FR-013
- Test: TEST-FR-013

## NFR Verification Criteria

## AC-029 Latency target measured

Given validation or production telemetry includes completed query workflow durations, when latency is reviewed, then P50, P95, and hard-timeout counts are reported against the targets in NFR-001.

- Requirement: NFR-001
- Test: TEST-NFR-001

## AC-030 Cost target measured

Given query cost telemetry is available, when cost is reviewed, then average, percentile, and over-threshold query costs are reported against NFR-002.

- Requirement: NFR-002
- Test: TEST-NFR-002

## AC-031 Citation coverage measured

Given a sampled set of source-backed completed queries is reviewed, when each answer that came back is checked for a visible primary source, then the count of those answers carrying one is scored against the NFR-003 target, `sourced_answer_count >= max(1, answer_count - 1)` — at least one answer must carry a primary source and at most one may lack one (ADR-0106).

- Requirement: NFR-003
- Test: TEST-NFR-003

## AC-032 Wrong-account access denied

Given an authenticated user requests another account's query result or BYO key management path, when authorization is checked, then access is denied.

- Requirement: NFR-005
- Test: TEST-NFR-005

## AC-033 Sensitive-data copy is not contradicted

Given product copy, warnings, and result pages are reviewed before release, when sensitive/private-data handling is evaluated, then no page claims the MVP is safe for secrets, regulated personal data, or confidential business data.

- Requirement: NFR-007
- Test: TEST-NFR-007

## AC-034 High-stakes coverage tested

Given regression tests include medical, legal, financial, safety, and regulated-topic examples, when the warning behavior is tested, then every example triggers decision-support-only language.

- Requirement: NFR-008
- Test: TEST-NFR-008

## AC-035 Accessibility baseline verified

Given the core query workflow is tested by keyboard, automated accessibility checks, and screen-reader smoke tests, when release readiness is reviewed, then no critical or serious accessibility violation remains on the core workflow.

- Requirement: NFR-009
- Test: TEST-NFR-009

## AC-036 Observability events emitted

Given a query is accepted, when it moves through submission, provider calls, fallback, debate, synthesis, and terminal status, then non-secret structured events are emitted for each stage.

- Requirement: NFR-010
- Test: TEST-NFR-010

## AC-037 Web-search plugin fee is an accepted cost-accounting exclusion

Given OpenRouter charges a flat per-request web-search plugin fee (~$0.02/request) that is separate from token cost, when a query's cost is estimated and later measured, then the system intentionally does NOT account for that fee: `cost_web_search_request_fee_usd` is permanently `0.0` by decision, the fee is never surfaced to the user or on the UI (at `0.0` it folds invisibly into the total estimate — no separate line item), and the cost guardrail remains fail-safe without it because the pre-run estimate already runs at or above the measured token cost (measured live run 2026-07-17: estimate $0.0199 ≥ actual $0.0149). The per-slot plumbing (server + client) is retained only as a dormant repo-tracking hook, not a pending activation.

**SUPERSEDED — 2026-09-15 (issue #105, CHG-007, ADR-0113). THE DECISION ABOVE NO
LONGER HOLDS: the fee is PRICED, at the measured $0.007.** The criterion's text is
kept verbatim because it is the dated record of what was accepted on 2026-07-17;
what follows is what replaced it.

The reversal, in one line: `0.0` is certainly wrong and `0.007` is measured, and
the error sat in the unsafe direction — the daily ceiling is keyed on the estimate,
and the estimate was $0.028 light on every searching run.

Three of the statements above were already refuted on 2026-09-12 (CHG-006,
ADR-0110), and are corrected here rather than silently left standing:

- **"~$0.02/request" is wrong.** The measured charge is **$0.007** flat. Of the 27
  generation rows in the owner's OpenRouter export for 2026-09-10, exactly 8 carry
  a `cost_web_search` and every one is `0.007`. The ~$0.02 figure came from
  OpenRouter's published rate card, never from a bill.
- **The fail-safe rationale is refuted.** Run 5a9c2d63 was approved at an estimate
  of $0.076 while its measured token cost alone was $0.0938 — so the estimate ran
  BELOW the measured token cost, on this criterion's own token-for-token terms
  (including the fee, the true charge was $0.121763).
- **The plumbing is no longer "per-slot, dormant, not a pending activation."**
  ADR-0110 extends it to the MEASURED path, and activation was then an open
  product-owner decision rather than a closed won't-activate. That decision was
  taken on 2026-09-15 (CHG-007, ADR-0113): the fee is priced at $0.007.

The fourth statement — "never surfaced to the user or on the UI" — was true only
AT `0.0`. It is now false by design: the cheapest searching slot's card moves from
`<$0.001` to about `$0.007`, because `perModelEstimateText` renders `<$0.001`
below the display quantum and no searching slot can round that low at $0.007.

**What activation cost**: under the real production posture (peer critique AND the
judge on, live catalog prices, measured 2026-09-15) the per-account daily envelope
on the shipped mix shrinks. The figures live in ONE place —
ADR-0113 §"What it cost", with the command and posture line pasted verbatim — and
are deliberately not repeated here; three transcribed copies were wrong in three
different ways. The envelope drop is the ceiling becoming CORRECT — it had been
admitting runs it could not afford — and `DAILY_CAP_USD` was deliberately NOT
raised to compensate.

- Requirement: NFR-002
- Decision: accepted 2026-07-17 (issue #18); see CHG-005. **Rationale superseded
  2026-09-12 by CHG-006, and the exclusion itself REVERSED 2026-09-15 by CHG-007
  — the fee is now priced at $0.007.** See ADR-0113 (the activation), ADR-0110
  (the measured-path plumbing it depends on) and
  `config.py cost_web_search_request_fee_usd`
- Test: existing #18 mechanism tests, now running at the activated `0.007`.
  `tests/unit/test_cost_search_fee.py` pins the estimate side;
  `tests/unit/test_actual_cost_source.py::test_the_measured_fee_term_reads_the_SETTING_and_scales_with_it`
  pins the measured side. The default itself is pinned with a literal on both
  sides by `tests/unit/test_search_fee_is_activated.py::test_the_shipped_default_is_the_MEASURED_provider_fee`
  and `tests/unit/test_search_fee_field_validation.py::test_the_shipped_default_is_unchanged_by_adding_the_constraint`
  (both `0.007`); `tests/test_doc_gate_consistency.py::test_env_example_values_match_the_real_defaults`
  ties `.env.example` to it

## Release 2: Trust & Evaluation

## AC-038 Terminal run persisted with verbatim cost provenance

Given a query run reaches a terminal status, when its terminal state is committed, then a durable run-history row exists whose `cost_source`, `actual_cost_usd`, and `estimated_cost_usd` are identical to what `GET /v1/query-runs/{id}` returns for that run — an `estimated` run is never persisted as `measured`.

- Requirement: FR-014
- Test: TEST-FR-014 (`tests/integration/test_query_run_history_persist.py::test_completed_run_persisted_with_verbatim_cost_and_survives_eviction`)

## AC-039 Run-history row is PII-minimised

Given a terminal run is persisted, when the row is written, then it contains only metrics and model ids — the query text and provider answer prose appear nowhere in the row.

- Requirement: FR-014
- Test: TEST-FR-014 (asserts the query text is absent from the persisted row)

## AC-040 Persistence is durable, idempotent, and non-blocking

Given a terminal run is persisted, when the in-memory run is later evicted, then the row survives; and re-recording the same run id does not create a duplicate (INSERT OR REPLACE, last write wins); and a persistence failure is swallowed without affecting the run's terminal state or the request.

- Requirement: FR-014, NFR-011
- Test: TEST-FR-014 (`tests/unit/test_run_history_store.py` idempotency + best-effort; integration survives-eviction assertion)

## AC-041 Layer-A evaluation is computed, honest, and persisted for every terminal run

Given a query run reaches a terminal status, when its durable run-history row has been written, then a deterministic Layer-A evaluation and a `TrustScore` are computed with zero I/O and stored on that row; recomputing over the same run yields byte-identical JSON; the stored payload contains metrics only (no query text, no provider prose); and the OC-2 honesty rule holds — because citation count coverage cannot verify that a citation supports its claim, `TrustScore.support_verified` is False unless a real Layer-B judge returned a citation-support verdict, and while it is False the numeric score is suppressed and the served band is `unverified` rather than any confidence figure.

The Layer-A half is unconditional: the `eval_json` column is written for every terminal run, whatever the money rails say, because Layer A is deterministic and needs no judge. The ordinary path writes both columns via `update_evaluation`.

**The `TrustScore` half has one exception (#342, ADR-0055).** When the spend rails refuse the Layer-B judge a dispatch, no verdict exists, so `trust_json` is left empty rather than filled with the suppressed `band="unverified", score=null, support_verified=false` shape — persisting that shape would assert a finding about a run nothing ever examined, and nothing rewrites the row once the rail resets. On that path only `eval_json` is written, via `fill_layer_a_evaluation_if_absent`, and the refusal cause is recorded on the run's `run_evaluated` event as `judge_refusal`. An empty `trust_json` is an absence, never a low score. The served band is unaffected and stays `unverified`, so the OC-2 honesty rule above is unchanged.

- Requirement: FR-015, NFR-011
- Test: TEST-FR-015 (`tests/unit/test_evaluation_layer_a.py` determinism, `citation_marker_grounding`, `detect_refusal`, suppression; `tests/evals/test_output_correctness_gate.py` OC-2 honesty rule; `tests/integration/test_query_run_evaluation_endpoint.py` persistence; `tests/integration/test_persisted_evaluation_never_asserts_a_verdict_the_run_did_not_get.py` the refusal exception, both halves)

## AC-042 Judge OFF is a proven no-op versus the stub judge

Given the LLM-as-judge key `QUORUM_EVAL_JUDGE_API_KEY` is unset, when a run is evaluated, then the judge seam (`providers.call_with_prompt`) is called zero times, no cost or latency is added, and the resulting `TrustScore` is identical to the score produced with `StubEvalJudge` enabled — the stub deliberately does not set `support_verified`, so both configurations serve the `unverified` band and every hermetic CI run stays byte-identical.

- Requirement: FR-015, NFR-012, NFR-011
- Test: TEST-NFR-012 (`tests/unit/test_evaluation_neutrality.py` seam-call spy and score equality; `tests/unit/test_evaluation_judge.py` key gate, strict-JSON contract, malformed response yields no verdict)

## AC-043 Evaluation inherits the run's account boundary and is never anonymous

Given a query run carries an evaluation, when `GET /v1/query-runs/{id}` is called without a session, then the response is 401 and no `evaluation` payload is returned; and when it is called with a valid session belonging to a different account, then the response is 404 `QUERY_RUN_NOT_FOUND` with no `evaluation` payload — judge rationale is derived data and inherits exactly the run's account scoping, so evaluation adds no new read path around the owner check.

- Requirement: FR-015, NFR-005
- Test: TEST-FR-015 (`tests/unit/test_evaluation_auth_boundary.py` unauthenticated 401 and cross-account 404 with no evaluation payload; `tests/integration/test_query_run_evaluation_endpoint.py` owner-only projection)

## AC-044 The trust surface renders no number and no confident label

Given a completed run whose result payload carries an `evaluation` — which in the default judge-OFF deployment always has `trust.support_verified` False, `trust.score` null and `trust.band` `unverified` — when the owner opens the result view, then the trust summary surface renders a standing "Not verified" disclosure, exactly one plain-language state line and at most three "why" lines; and its rendered text contains no digit of any kind, none of the words `faithful`, `partial`, `unfaithful`, `low risk`, `medium risk`, `high risk`, `confidence`, `accuracy`, `trustworthy`, `reliable`, `score` or `grade`, and no raw Layer-A signal identifier; and no descendant carries an ARIA `meter`, `progressbar` or `slider` role or an `aria-valuenow` attribute. And given the payload has no `evaluation`, or a `null` one, or a malformed one, then the surface is hidden and emits zero text.

- Requirement: FR-016, NFR-011
- Test: TEST-FR-016 (`e2e/tests/invariants/trust-score-invariants.spec.ts` no-digits / no-label-words / no-identifiers / disclosure-present / no-ARIA-value-widget / absent-renders-nothing; `e2e/tests/invariants/real-integration-smoke.spec.ts` the same no-digit assertion against the REAL server projection with no mocks)

## AC-045 A run whose citations could not be checked never presents a confident verdict

Given a run carrying at least one unverifiable off-run URL citation marker whose engine labels sit at the confident end — the DEBT-012 laundering shape, one resolving ordinal beside many fabricated links, which the engine still labels `faithful` / `low` — when the result view is rendered, then the API serves `label_confidence: "indeterminate"` and the surface renders the indeterminate state line stating that some citations point to pages never retrieved on this run; and a payload from which `label_confidence` is absent altogether renders the same indeterminate treatment, so the guard fails closed; and a warning-labelled run is never suppressed, so the guard can only ever under-claim. And given `high_stakes_warning_required` is true while `high_stakes_warning_present` is false, then a persistent amber row states that the question needed a safety caveat and the synthesis did not include one, independent of whether the synthesis carries its own notice.

- Requirement: FR-016, NFR-008
- Test: TEST-FR-016 (`e2e/tests/degraded/degraded-banner.spec.ts` misleading-output gate: laundered / refusal / missing-high-stakes / suppressed-disagreement / fully-live-unfaithful, each with its paired negative; `tests/unit/test_evaluation_presentation_confidence.py` the monotone-downward property; `tests/integration/test_query_run_evaluation_endpoint.py` the fail-closed s2-eval-v2 case)

## AC-046 The trust surface is never green, is accessible, and does not clip or overlap

Given every evaluation shape in the golden fixture, when the result view is rendered at 375, 768 and 1440 px in the pinned Linux CI browser in both the light and the dark theme, then no element of the trust-score surface or any of its descendants or pseudo-elements resolves to a green token in `color`, `background-color`, `background-image`, any `border-*-color`, `outline-color`, `box-shadow`, `text-decoration-color`, `caret-color`, `accent-color`, `fill` or `stroke` — where the expected greens are read from the CSS token source at runtime in each theme, never retyped — and no descendant carries `data-consensus` or a consensus/agreement class; a run whose disagreement was suppressed loses the green Agreement treatment; an axe-core scan scoped to the surface reports no critical or serious violation and no `color-contrast` incomplete result; no two elements' bounding boxes intersect inside `#main-content`; the surface and each trust card neither clip nor truncate; and the human-reviewed element-scoped screenshot baselines match in both themes at all three viewports.

- Requirement: FR-016, NFR-009
- Test: TEST-FR-016 (`e2e/tests/invariants/trust-score-invariants.spec.ts` GREEN-RULE / token-source computed style / overlap / clipping, parameterised over 3 viewports × 2 themes; `e2e/tests/accessibility/axe-all-views.spec.ts` scoped scan failing on violations AND on color-contrast incompletes; `e2e/tests/invariants/trust-score-visual.spec.ts` element-scoped `maxDiffPixels` baselines)

## AC-047 The golden set pins the engine's structural verdicts hermetically

Given the hermetic golden set (`tests/evals/golden/cases/`) of hand-authored real-shaped four-model runs, when the deterministic Layer-A engine of FR-015 is run over every case with the judge OFF, then each case's engine-derived STRUCTURAL verdict — faithfulness label, hallucination-risk band, refusal detection, false-consensus preservation, high-stakes-warning presence — equals that case's declared, MEASURED expectation and the gate names any case that drifts; every case is served band `unverified` with score `None`; the set exercises all three faithfulness labels, all three risk bands, and the refusal, false-consensus and high-stakes signals; and the whole gate performs zero I/O and makes zero paid calls. The gate contains no `skip` and no `xfail`, so `make gate-min-executed` passes.

- Requirement: FR-017, NFR-011
- Test: TEST-FR-017 (`tests/evals/test_golden_set_gate.py` structural-verdict parametrised gate + signal-space coverage + judge-OFF suppression; `tests/evals/golden/loader.py` metric derivation reused from the S2 corpus primitives)

## AC-048 Subject-matter labels are deferred, never fabricated

Given the golden cases flagged `needs_human_label` (one per subject-matter domain: clinical, tax/financial, as-of-date, self-harm/safety), when the gate runs, then it asserts ONLY those cases' structural signals and never a subject-matter correctness label; the loader and the gate both reject any fixture that carries a `correctness` field; each such case is surfaced in the operator queue (`docs/metrics/operator-label-queue.md`) by case id with its question verbatim, a panel summary, and a blank fill-in template; a structural case never appears in that queue; and the queue records that the debt is optional, has no deadline, requires a safety case first, and does not affect the live product (trust suppressed, judge OFF).

- Requirement: FR-017, NFR-012
- Test: TEST-FR-017 (`tests/evals/test_golden_set_gate.py::test_human_label_cases_defer_subject_matter_correctness_and_carry_no_label` and `::test_the_operator_queue_names_every_human_label_case`; `tests/evals/golden/loader.py` correctness-field rejection)

## AC-049 The real judge is wired into the request path, unlocks a score only when configured, and is OFF by default

Given `QUORUM_EVAL_JUDGE_API_KEY` and `QUORUM_EVAL_JUDGE_MODEL_ID` are both configured, when a terminal run is evaluated on the request/serving path, then the real `EvalJudgeService` — never any stub, and never any judge whose `verifies_support` is False — is passed to `evaluate_run`; a conforming verdict whose CONTENT does not contradict the claim (#267 — grounding and faithfulness both above zero, hallucination risk not `high`) flips `support_verified` so the served projection carries a numeric `score` (0–100) and a `low`/`moderate`/`high` band, while a conforming verdict that DOES contradict it serves the suppressed `unverified` shape; the persisted trust row agrees byte-for-byte with the served projection; the paid judge call is memoised per run so N reads of one result make at most one judge call (a failed or non-conforming call is memoised too, serves the suppressed `unverified` shape, and never fails the run); and the result view renders the numeric score with a verified disclosure only for the exact verified shape — any tampered near-miss (null/out-of-range/non-integer score, unknown or `unverified` band, non-True `support_verified`, or a non-`reportable` provenance) falls back to the zero-digit unverified treatment. And given either variable is unset — the default in every environment until the operator funds the key — then no judge object is constructed, no evidence is built, zero I/O is performed, and the served evaluation is byte-identical to `evaluate_run(judge=None)`.

- Requirement: FR-015, NFR-011, NFR-012
- Test: TEST-FR-015 (`tests/integration/test_judge_request_path_wiring.py` unlock, memoisation, half-configured/OFF byte-identity, stub-suppression regression; `tests/contract/test_golden_fixture_matches_served_schema.py` engine-recomputed verified fixture; `e2e/tests/invariants/trust-score-invariants.spec.ts` verified render + tamper fail-closed)

## AC-050 The panel can be shrunk to two or grown to four, and a panel of two is described honestly

Given the query workflow shows its four default slots, when the user removes a slot, then the panel has three slots and the run request carries three model slots; when the user removes another, the panel has two and the remove control is disabled; when the user adds a slot, the panel grows by one up to four. A run with two models that both agree shows a green band reading "Both models agree (2 of 2)" — never "The panel's verdict" — and its served trust band is never `high` (capped at `moderate`, `TrustDiagnostics.panel_size_cap` true). A request with one slot or five is refused with the typed `INVALID_MODEL_SLOT` envelope.

- Requirement: FR-004
- Test: TEST-FR-004 (`tests/unit/test_panel_of_n_is_priced_and_bounded.py` for the range, the N-relative estimate and the trust cap; the remove/add control and the N=2 band copy are TEST-FR-004's e2e half, delivered with the workspace change that follows CHG-010)
- Decided by the product owner on 2026-09-22 (CHG-010).

## AC-051 A quick answer is one model with the judge's verdict and no agreement figure

Given the composer, when the user turns on "Quick answer — one model, no debate", then only slot 1 is shown, the add and remove controls and the shape line are hidden, and "four models by default, 2 debates and 1 sourced answer" is shown; turning it off restores the composer exactly. When the user runs a question with it on, the estimate and create requests carry `mode: "quick"`, one model and no `context`; with it off they carry no `mode` and every slot. When the quick answer finishes, the result view shows the answer rendered from Markdown with no raw marker, its sources, the safety notice when present, and "Judge: <level>" with the reasons, the scores and the sources the judge checked as plain text, and the claims the judge checked, each quoted as text that is already in the rendered answer with its support word and source number (a claim whose words are not the answer's is not shown, and the page says how many were not shown); it shows no verdict ring or band, trust cards, trust score, debate, synthesis or transcript link, and no agreement figure on the page, in Copy or in Export. A later panel run in the same session shows every panel surface again.

- Requirement: FR-018
- Test: TEST-FR-018 (`e2e/tests/invariants/quick-answer.spec.ts`, each absence with a positive partner on a panel result; `tests/unit/test_quick_answer_ui.py` for the request bodies, the cost-gate line, the one-model banner copy, the judge heading, the Copy summary and the fixture's served shape; `tests/unit/test_quick_verdict_claims.py` for which claims are served)
- Decided by the product owner on 2026-09-24 (CHG-012 D1 and the evening answers); the layout is the session's (ADR-0128, CHG-018), and so is the per-claim evidence (ADR-0129, CHG-019).

## AC-052 A person can sign in with Google and sign out, and nothing else changes

Given a deployment with the three `GOOGLE_OAUTH_*` settings set, when a visitor chooses "Sign in with Google" and Google returns them with a valid code and this session's unexpired, unused `state`, then the server exchanges the code with PKCE, accepts the ID token only if its issuer, audience, authorised party, expiry, issue time, verified email, subject and email pass, records one account row per Google subject holding no token, replaces the session with a new one (the old id no longer works), and the page shows the email and "Sign out". A callback with a missing, wrong, expired, reused or another session's `state`, a failing claim, an error from Google, or a token endpoint slower than 10 s returns to `/ui?sign_in=failed` with a fixed notice and changes no session and no row. "Sign out" ends the session on the server and keeps the account row. With any of the three settings unset, the page is byte-identical to the page without sign-in, the routes answer 404 and `/status` reports `sign_in_enabled: false`.

- Requirement: FR-019
- Test: TEST-FR-019 (`tests/integration/test_google_sign_in.py`; `tests/unit/test_google_signin_units.py`)
- Decided by the product owner on 2026-09-24 (CHG-012 D7); the flow, bounds and copy are the session's (ADR-0130, CHG-020).
