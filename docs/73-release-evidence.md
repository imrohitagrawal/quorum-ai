# Release Evidence

## Release Readiness Status

Decision: No-go for production release.

Reason: The repository has approved planning artifacts, clean local validation/quality gates,
the authenticated execution-boundary slice, the in-memory query-run state-machine slice, the
safety/privacy warning acknowledgement slice, the model-slot defaults/replacement validation
slice, the cost guardrails slice, the provider-stub/search-fallback slice, the
per-model answer result-projection slice, the two-round debate orchestration slice, the
final-synthesis/eval-check slice, the BYO OpenRouter key account-scoping slice, local
VS-012 API E2E/accessibility-contract/performance/security/eval evidence, and local VS-013
CI-style report/security-scan/browser-UI evidence.
The full Release 1 production workflow has not been released. A remote CI run, external vendor
security scans, manual WCAG audit, live provider execution, durable persistence, deployment,
full rubric-backed AI eval, and production telemetry evidence are not available yet.

## Evidence Register

| Evidence | Link/Location | Owner | Status |
|---|---|---|---|
| Requirements coverage | `docs/10-functional-requirements.md`, `docs/11-non-functional-requirements.md`, `docs/12-acceptance-criteria.md`, `docs/18-requirement-traceability-matrix.md` | Product owner | Planning evidence complete |
| Architecture evidence | `docs/20-architecture.md`, `docs/21-domain-model.md`, `docs/22-api-contract.md`, `docs/23-data-model.md`, `docs/adr/0001-initial-architecture.md` | Engineering lead | Planning evidence complete |
| UX evidence | `docs/30-ux-design.md`, `docs/31-accessibility-plan.md`, `docs/32-ui-state-matrix.md`, `docs/33-content-design.md` | Product owner and Engineering lead | Planning evidence available |
| Security/privacy evidence | `docs/40-threat-model.md`, `docs/41-security-controls.md`, `docs/43-privacy-data-governance.md`, `docs/45-control-mapping.md`, `docs/48-data-retention.md` | Security and Product owner | Planning evidence available; runtime evidence absent |
| AI safety and grounding evidence | `docs/42-ai-safety-grounding.md`, `docs/44-model-risk-register.md`, `docs/46-prompt-registry.md` | Product owner and Engineering lead | Planning evidence available; eval evidence absent |
| Test strategy evidence | `docs/50-test-strategy.md`, `docs/51-test-data-strategy.md`, `docs/54-ac-to-test-map.md`, `docs/55-performance-baseline.md`, `docs/57-test-evidence.md` | Engineering lead | Planned coverage complete; local VS-002 through VS-012 evidence available |
| Local validation gate | `make validate` | Engineering lead | Passed on 2026-06-17 after VS-013 documentation updates |
| Local quality gate | `make quality`; `make ci-evidence` | Engineering lead | Passed locally on 2026-06-17 with 70 pytest tests, 99 percent coverage, 0 deterministic security-scan findings, and one dependency deprecation warning |
| VS-002 auth boundary | `src/product_app/auth.py`, `src/product_app/query_runs.py`, `tests/unit/test_query_run_auth_boundary.py` | Engineering lead | Implemented locally; blocks anonymous query-run creation and accepts UUID account boundary |
| VS-003 state machine and active-run guard | `src/product_app/query_runs.py`, `tests/unit/test_query_run_state_machine.py`, `tests/integration/test_query_run_active_rule.py`, `docs/29-state-machines.md` | Engineering lead | Implemented locally; blocks duplicate active runs per account and releases the slot on terminal state |
| VS-004 safety/privacy warnings | `src/product_app/safety.py`, `src/product_app/query_runs.py`, `tests/unit/test_safety_warning_policy.py`, `tests/integration/test_query_run_safety_warnings.py` | Engineering lead | Implemented locally; returns required warnings and requires acknowledgements before accepted query creation |
| VS-005 model-slot defaults and replacement validation | `src/product_app/model_slots.py`, `src/product_app/query_runs.py`, `src/product_app/main.py`, `tests/unit/test_model_slots.py`, `tests/integration/test_model_slot_configuration.py`, `openapi.yaml` | Engineering lead | Implemented locally; returns four authenticated defaults, validates exactly four OpenRouter-style replacement IDs, stores selected slots with accepted runs, and records non-secret model-slot selection events |
| VS-006 cost guardrails | `src/product_app/costs.py`, `src/product_app/query_runs.py`, `tests/unit/test_cost_guardrails.py`, `tests/integration/test_query_run_cost_guardrails.py`, `openapi.yaml` | Engineering lead | Implemented locally; estimates cost server-side, accepts normal-cost queries, requires matching confirmation above USD 0.15, blocks estimates above USD 0.25, and records non-secret cost guardrail events |
| VS-007 provider stubs and search fallback | `src/product_app/providers.py`, `src/product_app/query_runs.py`, `tests/unit/test_provider_stubs.py`, `tests/integration/test_query_run_provider_stubs.py`, `openapi.yaml` | Engineering lead | Implemented locally; creates deterministic OpenRouter-first initial answer stubs, falls back to approved search stubs when OpenRouter sources are unusable, exposes visible source links and citation coverage metadata, and records non-secret provider duration/fallback/source-count events |
| VS-008 result projection | `src/product_app/providers.py`, `src/product_app/query_runs.py`, `tests/unit/test_query_run_result_projection.py`, `tests/integration/test_query_run_result_endpoint.py`, `openapi.yaml` | Engineering lead | Implemented locally; captures per-model answer status, source links, latency, error code, and user-safe provider notices, exposes an owner-scoped result projection with cost and elapsed time, keeps model answers separate from future debate/synthesis sections, and asserts result payloads do not expose provider secrets |
| VS-009 debate orchestration | `src/product_app/debate.py`, `src/product_app/query_runs.py`, `tests/unit/test_debate_orchestration.py`, `tests/integration/test_query_run_result_endpoint.py`, `openapi.yaml` | Engineering lead | Implemented locally; runs two deterministic structured critique rounds after initial answers, records non-secret debate events, projects debate outputs separately from synthesis, simulates timeout-budget recovery with `partial` status, exposes failed/missing steps, and releases the active slot on debate timeout |
| VS-010 final synthesis and AI eval checks | `src/product_app/synthesis.py`, `src/product_app/query_runs.py`, `tests/unit/test_synthesis.py`, `tests/evals/test_synthesis_eval_checks.py`, `tests/integration/test_query_run_result_endpoint.py`, `openapi.yaml` | Engineering lead | Implemented locally; completed stubbed runs now produce structured consensus, disagreement, source-support, uncertainty, and recommendation sections, preserve disagreement to avoid false consensus, aggregate citation coverage against the 80 percent target, include decision-support framing and high-stakes notices, emit non-secret synthesis events, and project the typed synthesis in result responses |
| VS-011 BYO OpenRouter key account scoping | `src/product_app/provider_keys.py`, `src/product_app/main.py`, `src/product_app/providers.py`, `src/product_app/query_runs.py`, `tests/unit/test_provider_keys.py`, `tests/integration/test_provider_key_endpoints.py`, `openapi.yaml` | Engineering lead | Implemented locally; authenticated add/status/remove endpoints store account-scoped in-memory secret references, responses and events omit raw keys and secret references, wrong-account status/removal cannot access another account's BYO key, and future stubbed provider events use `byo_openrouter` only for the owning account until removal returns them to `app_owned` |
| VS-012 release hardening evidence | `tests/e2e/test_release_hardening_workflow.py`, `tests/accessibility/test_api_accessibility_contract.py`, `tests/performance/test_query_run_performance_evidence.py`, `tests/security/test_release_security_redaction.py`, `tests/evals/test_synthesis_eval_checks.py`, `docs/57-test-evidence.md` | Engineering lead | Implemented locally; targeted suites prove the local API workflow across BYO key setup/removal, warnings, accepted run creation, completed result retrieval, active-run release, warning/result accessibility contracts, local stubbed-workflow timing, non-secret event completeness, BYO/provider-failure redaction, and deterministic synthesis eval regressions |
| VS-013 CI artifact, security scan, and browser UI evidence | `.github/workflows/ci.yml`, `Makefile`, `scripts/security_scan.py`, `src/product_app/main.py`, `tests/e2e/test_browser_ui_rendering.py`, `tests/accessibility/test_browser_ui_accessibility_contract.py`, `build/test-results/pytest.xml`, `build/coverage/coverage.xml`, `build/security/security-scan.json` | Engineering lead | Implemented locally; report-generating pytest/coverage artifacts, deterministic security scan with 0 findings, CI artifact upload configuration, and server-rendered `/ui` browser shell render/accessibility contracts exist |
| CI evidence | `build/test-results/pytest.xml`, `build/coverage/coverage.xml`, `.github/workflows/ci.yml` | Engineering lead | Local CI-style artifacts available and GitHub Actions upload configured; remote CI run not claimed |
| Security scans | `tests/security/test_release_security_redaction.py`, `scripts/security_scan.py`, `build/security/security-scan.json` | Security owner | Focused local redaction tests and deterministic repository security scan passed with 0 findings; external vendor SAST/DAST and dependency scans not claimed |
| E2E evidence | `tests/e2e/test_release_hardening_workflow.py`, `tests/e2e/test_browser_ui_rendering.py`, `build/test-results/pytest.xml` | Engineering lead | Local API E2E and server-rendered browser UI render evidence available; full browser automation against Playwright or a real browser not claimed |
| Accessibility evidence | `tests/accessibility/test_api_accessibility_contract.py`, `tests/accessibility/test_browser_ui_accessibility_contract.py`, `build/test-results/pytest.xml` | Engineering lead | Local API and browser UI accessibility-contract evidence available; manual WCAG 2.2 AA audit not claimed |
| Performance evidence | `tests/performance/test_query_run_performance_evidence.py`; load artifact location not yet configured | Engineering lead | Local stubbed-workflow timing and event-completeness evidence available; load/percentile/CI artifacts not available |
| AI eval evidence | `tests/evals/test_synthesis_eval_checks.py` | Product owner and Engineering lead | Partially available locally for deterministic VS-010/VS-012 checks; full rubric-backed eval harness and CI artifacts are not available because OQ-012 remains open |
| Observability evidence | `docs/80-observability.md`, `docs/81-slo.md`, `docs/82-alerts.md`, `docs/85-dashboard-spec.md`, `tests/performance/test_query_run_performance_evidence.py` | Engineering lead | Planning evidence and local event-completeness assertions available; dashboard/runtime evidence absent |
| Rollback evidence | `docs/72-rollback-plan.md`, `docs/64-feature-flag-plan.md` | Release owner | Planning evidence available |
| Support evidence | `docs/83-runbook.md`, `docs/84-incident-response.md`, `docs/86-oncall-playbook.md` | Support owner | Planning evidence available |

## Release Blockers

| Blocker ID | Blocker | Owner | Required Resolution |
|---|---|---|---|
| REL-BLOCK-001 | Release 1 product workflow is only partially implemented. | Engineering lead | Complete remaining vertical slices in `docs/61-vertical-slice-plan.md`. |
| REL-BLOCK-002 | Remote CI release artifacts are not available. | Engineering lead | Push/run GitHub Actions and archive the uploaded non-secret release-hardening evidence artifact. |
| REL-BLOCK-003 | External security scan release evidence is not available. | Security owner | Run approved dependency/SAST/DAST scans and record non-secret evidence. |
| REL-BLOCK-004 | Local API E2E, browser UI render contract, API/browser accessibility contracts, local performance, focused security, deterministic security scan, and deterministic eval evidence are available; load/percentile, resilience, remote CI, manual WCAG, external scans, and full rubric eval artifacts are still missing. | Engineering lead | Implement missing harnesses and publish non-secret CI artifacts. |
| REL-BLOCK-005 | Production deployment target and provider data-processing terms remain unresolved. | Product owner and Engineering lead | Resolve OQ-007 and OQ-014 before release claims. |

## Release Evidence Rules

- Do not mark release evidence as passed until the command, timestamp, environment, and artifact location exist.
- Do not include provider keys, raw user prompts, raw private content, or raw provider error payloads in evidence.
- Do not publish or deploy without explicit human approval and the required release readiness review.

## VS-011 Local Evidence

- Scope: BYO OpenRouter key add/remove/status and account scoping for FR-012, NFR-005, and NFR-006.
- Command: `uv run pytest tests/unit/test_provider_keys.py tests/integration/test_provider_key_endpoints.py tests/unit/test_query_run_auth_boundary.py tests/integration/test_query_run_provider_stubs.py`.
- Result: Passed locally on 2026-06-17 with 14 tests and one upstream Starlette/httpx deprecation warning.
- Security evidence: focused assertions verify unauthenticated access is rejected, account B cannot see or remove account A's BYO status, status/remove responses omit raw keys and secret references, provider-key events omit secrets, and future stubbed provider events use `byo_openrouter` only for the owning account.
- Limitations: local in-memory secret-reference implementation only; durable secret store, production deployment evidence, CI security scans, and live provider execution remain unavailable.

## VS-012 Local Evidence

- Scope: E2E, accessibility-contract, local performance, observability event completeness, focused security redaction, and deterministic eval evidence for release hardening.
- Command: `uv run pytest tests/e2e tests/accessibility tests/performance tests/security tests/evals`.
- Result: Passed locally on 2026-06-17 with 6 tests and one upstream Starlette/httpx deprecation warning.
- Full gate: `make quality` passed locally on 2026-06-17 with Ruff format/check, mypy, 68 pytest tests, and the same upstream Starlette/httpx deprecation warning.
- Evidence: local API workflow covers defaults, warnings, BYO key status/add/remove, accepted query creation, completed result retrieval, active-run release, high-stakes synthesis notice, non-secret provider/debate/synthesis/warning events, local stubbed-workflow timing under 500 ms, provider-failure redaction, and deterministic synthesis eval checks.
- Limitations at VS-012 completion: browser UI, external security scans, load/percentile reports, CI artifacts, full rubric-backed eval batches, live provider execution, durable persistence, deployment, and production telemetry were unavailable. VS-013 later added local browser UI and CI-style artifact evidence; remote CI, external scans, load/percentile reports, full eval batches, live providers, persistence, deployment, and production telemetry remain unavailable.

## VS-013 Local Evidence

- Scope: CI artifact configuration, local report generation, deterministic security scan, and browser UI rendering/accessibility-contract evidence.
- Command: `make ci-evidence`; `uv run ruff format . --check`; `uv run ruff check .`; `uv run mypy src tests`.
- Result: Passed locally on 2026-06-17. `make ci-evidence` ran 70 tests with 99 percent coverage and one upstream Starlette/httpx deprecation warning, wrote `build/test-results/pytest.xml` and `build/coverage/coverage.xml`, and wrote `build/security/security-scan.json` with 0 findings.
- CI configuration: `.github/workflows/ci.yml` now runs `make test-report`, `make security-scan`, and uploads pytest, coverage, and security-scan artifacts as `release-hardening-evidence`.
- Browser UI evidence: `/ui` renders a server-side HTML shell with account ID, query text, model defaults, warning copy, model answer, debate, synthesis, and release signal sections; tests assert labels, landmarks, focus styling, minimum control size, and absence of provider key material.
- Limitations: remote GitHub Actions artifact evidence, external vendor security/dependency/SAST/DAST scans, Playwright/real-browser automation, manual WCAG 2.2 AA audit, load/percentile reports, full rubric-backed eval batches, live provider execution, durable persistence, deployment, and production telemetry remain unavailable.
