# Test Evidence

## Scope

This file records planned and actual evidence for Release 1 MVP tests. VS-002 through VS-013
have local implementation evidence. Local CI-style reports, a deterministic repository security
scan, and browser UI rendering/accessibility-contract evidence now exist. A remote GitHub Actions
run, live-provider, production, load/percentile, and full rubric-backed AI eval evidence are not
claimed yet.

## Evidence Rules

- Do not mark a suite as passed until the command has run and the result is captured.
- Evidence must include command, timestamp, environment, result, and linked AC/test IDs.
- Provider keys, user prompts, raw private content, and raw provider errors must not appear in evidence artifacts.
- CI evidence, Jira evidence, and release evidence remain `Not available` until produced by the approved workflow.

## Planned Evidence Matrix

| Test Suite | Scope | Command | AC Coverage | Last Result | Evidence Link/Path | Owner | Blocking? |
|---|---|---|---|---|---|---|---|
| Unit | Domain rules, cost thresholds, state machine, validation, result projection, redaction helpers, event contract helpers. | `uv run pytest tests/unit` | AC-001 through AC-036 where unit coverage is listed in `docs/54-ac-to-test-map.md` | Not run | Not available | Engineering lead | Yes |
| Integration | Database/repository behavior, orchestration with provider stubs, fallback, terminal states, BYO key metadata, structured events. | `uv run pytest tests/integration` | AC-002, AC-003, AC-004, AC-011, AC-012, AC-014, AC-015, AC-016, AC-017, AC-018, AC-021, AC-022, AC-025, AC-026, AC-027, AC-029, AC-030, AC-036 | Not run | Not available | Engineering lead | Yes |
| Contract | API request/response/error contracts for auth, estimates, query runs, result retrieval, BYO key status/add/remove. | `uv run pytest tests/contract` | AC-001, AC-002, AC-003, AC-005, AC-006, AC-007, AC-008, AC-009, AC-010, AC-015, AC-021, AC-023, AC-024, AC-025, AC-026, AC-027, AC-032 | Not run | Not available | Engineering lead | Yes |
| E2E | Local API workflow for auth boundary, query setup, warning display contract, model defaults, completed result, BYO key settings, active-run release, and browser UI render shell. | `uv run pytest tests/e2e` | AC-001 through AC-028, AC-032 through AC-035 | Passed locally on 2026-06-17 as part of VS-013 report-generating evidence | `build/test-results/pytest.xml`; remote CI run not claimed | Engineering lead | Yes |
| Security | Auth/authorization, IDOR prevention, cost tampering, secret redaction, prompt injection, BYO isolation, high-stakes boundary, and deterministic repository secret scan. | `uv run pytest tests/security`; `make security-scan` | AC-001, AC-003, AC-008, AC-010, AC-015, AC-016, AC-020, AC-023, AC-024, AC-025, AC-026, AC-032, AC-033, AC-034, AC-036 | Passed locally on 2026-06-17 as part of VS-013 evidence; security scan finding count is 0 | `build/security/security-scan.json`; external vendor SAST/DAST not claimed | Engineering lead | Yes |
| Accessibility | API contract checks and browser UI render contract for landmarks, labels, focus styling, minimum control size, warning readability, and result sections. | `uv run pytest tests/accessibility` | AC-005, AC-006, AC-007, AC-008, AC-013, AC-018, AC-020, AC-022, AC-027, AC-028, AC-033, AC-034, AC-035 | Passed locally on 2026-06-17 as part of VS-013 browser UI contract evidence | `build/test-results/pytest.xml`; manual WCAG audit not claimed | Engineering lead | Yes |
| Performance | Health/readiness, estimate, acceptance, full stubbed workflow, fallback, timeout, cost reporting, event completeness. | `uv run pytest tests/performance` | AC-009, AC-010, AC-012, AC-017, AC-021, AC-022, AC-029, AC-030, AC-036 | Passed locally on 2026-06-17 as part of VS-012 local stubbed-workflow timing and event-completeness evidence | Local terminal output; load/CI evidence not available | Engineering lead | Yes |
| Resilience | Provider failures, fallback, retry/timeout budgets, partial-result recovery, terminal state release. | `uv run pytest tests/integration -m resilience` or implementation-selected equivalent | AC-004, AC-012, AC-015, AC-021, AC-022 | Not run | Not available | Engineering lead | Yes |
| AI eval | Citation coverage, false consensus, high-stakes warning coverage, prompt-injection source set, partial-result quality. | `uv run pytest tests/evals` plus future rubric-backed eval batch | AC-005, AC-018, AC-019, AC-020, AC-031, AC-034 | Deterministic VS-010 eval checks passed locally on 2026-06-17; full rubric-backed eval batch not available | Local terminal output for VS-010 deterministic eval checks; CI evidence not available | Product owner and Engineering lead | Yes |
| Privacy/content review | Sensitive-data warning, no contradictory privacy copy, provider-terms dependent claims blocked. | Manual checklist plus automated copy assertions selected during implementation planning | AC-006, AC-033 | Not run | Not available | Product owner | Yes |

## Local Slice Evidence

| Slice | Command | Result | Coverage | Evidence |
|---|---|---|---|---|
| VS-002 | `uv run pytest tests/unit/test_query_run_auth_boundary.py` | Passed locally on 2026-06-16 | AC-001, AC-002, AC-032 auth boundary regression | Local terminal output; CI evidence not available |
| VS-003 | `uv run pytest tests/unit/test_query_run_auth_boundary.py tests/unit/test_query_run_state_machine.py tests/integration/test_query_run_active_rule.py` | Passed locally on 2026-06-16 with 12 tests and one upstream Starlette/httpx deprecation warning | AC-003, AC-004, AC-021, AC-022 state-machine and active-run guard coverage | Local terminal output; CI evidence not available |
| VS-004 | `uv run pytest tests/unit/test_safety_warning_policy.py tests/integration/test_query_run_safety_warnings.py` | Passed locally on 2026-06-16 | AC-005, AC-006, AC-033, AC-034 safety/privacy warning and acknowledgement coverage | Local terminal output; CI evidence not available |
| VS-005 | `uv run pytest tests/unit/test_model_slots.py tests/integration/test_model_slot_configuration.py` | Passed locally on 2026-06-16 with one upstream Starlette/httpx deprecation warning | AC-007, AC-008 default model slot and replacement validation coverage | Local terminal output; CI evidence not available |
| VS-006 | `uv run pytest tests/unit/test_cost_guardrails.py tests/integration/test_query_run_cost_guardrails.py`; `make quality` | Passed locally on 2026-06-16. Full `make quality` passed with 37 tests and one upstream Starlette/httpx deprecation warning | AC-009, AC-010, AC-030 cost estimate, confirmation, blocking, and non-secret cost event coverage | Local terminal output; CI evidence not available |
| VS-007 | `uv run pytest tests/unit/test_provider_stubs.py tests/integration/test_query_run_provider_stubs.py tests/integration/test_query_run_active_rule.py`; `make quality`; `make validate` | Passed locally on 2026-06-16. Targeted VS-007 suite passed with 11 tests; full `make quality` passed with 44 tests and one upstream Starlette/httpx deprecation warning; `make validate` passed | AC-011, AC-012, AC-013, AC-031 OpenRouter-first provider stub, fallback search stub, visible source links, citation coverage scoring, and non-secret provider event coverage | Local terminal output; CI evidence not available |
| VS-008 | `uv run pytest tests/unit/test_query_run_result_projection.py tests/unit/test_provider_stubs.py tests/integration/test_query_run_result_endpoint.py tests/integration/test_query_run_provider_stubs.py`; `make quality`; `make validate` | Passed locally on 2026-06-17. Targeted VS-008 suite passed with 12 tests; full `make quality` passed with 49 tests and one upstream Starlette/httpx deprecation warning; `make validate` passed | AC-014, AC-015, AC-027, AC-028 per-model answer capture, owner-scoped result projection, provider failure notices, and non-secret payload assertions | Local terminal output; CI evidence not available |
| VS-009 | `uv run pytest tests/unit/test_debate_orchestration.py tests/unit/test_query_run_result_projection.py tests/unit/test_query_run_state_machine.py tests/unit/test_query_run_auth_boundary.py tests/integration/test_query_run_result_endpoint.py tests/integration/test_query_run_provider_stubs.py tests/integration/test_query_run_active_rule.py`; `make quality`; `make validate` | Targeted VS-009 suite passed locally on 2026-06-17 with 23 tests and one upstream Starlette/httpx deprecation warning. Full `make quality` passed on 2026-06-17 with 52 tests and the same upstream deprecation warning. `make validate` passed all factory gates. | AC-016, AC-017, AC-021, AC-022 two structured critique rounds, debate event recording, timeout-budget partial behavior, missing-step projection, and active-slot release on partial timeout | Local terminal output; CI evidence not available |
| VS-010 | `uv run pytest tests/unit/test_synthesis.py tests/evals/test_synthesis_eval_checks.py tests/integration/test_query_run_result_endpoint.py tests/integration/test_query_run_provider_stubs.py tests/unit/test_query_run_auth_boundary.py`; `make quality`; `make validate` | Targeted VS-010 suite passed locally on 2026-06-17 with 14 tests and one upstream Starlette/httpx deprecation warning. Full `make quality` passed on 2026-06-17 with 56 tests and the same upstream deprecation warning. `make validate` passed all factory gates. | AC-018, AC-019, AC-020, AC-031, AC-034 structured synthesis sections, false-consensus preservation, citation coverage target check, decision-support framing, high-stakes synthesis notice, and non-secret synthesis event coverage | Local terminal output; CI evidence not available |
| VS-011 | `uv run pytest tests/unit/test_provider_keys.py tests/integration/test_provider_key_endpoints.py tests/unit/test_query_run_auth_boundary.py tests/integration/test_query_run_provider_stubs.py`; `make quality`; `make validate` | Targeted VS-011 suite passed locally on 2026-06-17 with 14 tests and one upstream Starlette/httpx deprecation warning. Full `make quality` passed on 2026-06-17 with 64 tests and the same upstream deprecation warning. `make validate` passed all factory gates. | AC-023, AC-024, AC-025, AC-026, AC-032 authenticated BYO add/status/remove endpoints, account-scoped key status, provider credential-source scoping, removal returning future runs to app-owned credentials, and non-secret response/event assertions | Local terminal output; CI evidence not available |
| VS-012 | `uv run pytest tests/e2e tests/accessibility tests/performance tests/security tests/evals`; `make quality`; `make validate` | Targeted VS-012 suite passed locally on 2026-06-17 with 6 tests and one upstream Starlette/httpx deprecation warning. Full `make quality` passed on 2026-06-17 with 68 tests and the same upstream deprecation warning. | AC-029, AC-035, AC-036 plus regression coverage for completed local API workflow, warning/result accessibility contract, local stubbed-workflow timing, non-secret event completeness, BYO/provider-failure redaction, and deterministic eval checks | Local terminal output; CI, browser UI, external scan, load-test, and full rubric eval evidence not available |
| VS-013 | `make ci-evidence`; `uv run ruff format . --check`; `uv run ruff check .`; `uv run mypy src tests` | Passed locally on 2026-06-17 with 70 tests, 99 percent coverage, 0 security-scan findings, and one upstream Starlette/httpx deprecation warning. CI workflow now uploads pytest, coverage, and security-scan artifacts when GitHub Actions runs. | AC-023, AC-027, AC-028, AC-035, AC-036 plus release evidence artifact coverage | `build/test-results/pytest.xml`; `build/coverage/coverage.xml`; `build/security/security-scan.json`; remote CI run not claimed |

## Acceptance Criterion Evidence Register

| AC | Planned Evidence |
|---|---|
| AC-001 | Unit, integration, contract, E2E, and security evidence that anonymous execution is blocked. |
| AC-002 | Unit, integration, contract, E2E, and security evidence that authenticated valid execution is accepted. |
| AC-003 | Unit, integration, contract, E2E, and security evidence that duplicate active query is rejected. |
| AC-004 | Unit, integration, contract, and E2E evidence that terminal states release the active slot. |
| AC-005 | Unit, integration, contract, E2E, accessibility, security, and eval evidence for high-stakes warnings. |
| AC-006 | Unit, integration, contract, E2E, accessibility, security, and privacy evidence for sensitive-data warning. |
| AC-007 | Unit, contract, E2E, and accessibility evidence for default model slots. |
| AC-008 | Unit, integration, contract, E2E, security, and accessibility evidence for replaceable model slots. |
| AC-009 | Unit, integration, contract, E2E, and performance evidence for normal-cost execution. |
| AC-010 | Unit, integration, contract, E2E, performance, and security evidence for confirmation/blocking thresholds. |
| AC-011 | Unit, integration, E2E, and eval evidence that OpenRouter search is attempted first. |
| AC-012 | Unit, integration, E2E, performance, and resilience evidence for search fallback. |
| AC-013 | Unit, integration, E2E, accessibility, and eval evidence that source links are visible. |
| AC-014 | Unit, integration, E2E, and security evidence for per-model output capture. |
| AC-015 | Unit, integration, contract, E2E, and security evidence for user-safe provider failures. |
| AC-016 | Unit, integration, E2E, security, and eval evidence for first critique round. |
| AC-017 | Unit, integration, E2E, performance, and eval evidence for second critique round. |
| AC-018 | Unit, integration, E2E, accessibility, and eval evidence for required synthesis sections. |
| AC-019 | Unit, integration, E2E, and eval evidence for contradiction preservation. |
| AC-020 | Unit, integration, E2E, accessibility, security, and eval evidence for decision-support recommendations. |
| AC-021 | Unit, integration, contract, E2E, and performance evidence for hard timeout terminal response. |
| AC-022 | Unit, integration, E2E, accessibility, performance, and resilience evidence for partial-result missing steps. |
| AC-023 | Unit, integration, contract, E2E, and security evidence that app-owned keys remain server-side. |
| AC-024 | Unit, integration, contract, and security evidence for redacted provider exceptions. |
| AC-025 | Unit, integration, contract, E2E, and security evidence that BYO key is account-scoped. |
| AC-026 | Unit, integration, contract, E2E, and security evidence that BYO key is removable and not reused. |
| AC-027 | Unit, integration, contract, E2E, accessibility, and security evidence for full result component display. |
| AC-028 | Unit, E2E, and accessibility evidence that result structure supports comparison. |
| AC-029 | Unit, integration, and performance evidence for latency metrics. |
| AC-030 | Unit, integration, and performance evidence for cost metrics. |
| AC-031 | Unit and AI eval evidence for citation coverage measurement. |
| AC-032 | Unit, integration, contract, E2E, and security evidence for wrong-account denial. |
| AC-033 | Unit, E2E, accessibility, security, and privacy review evidence that copy does not contradict sensitive-data warnings. |
| AC-034 | Unit, E2E, accessibility, security, and eval evidence for high-stakes coverage. |
| AC-035 | E2E and accessibility evidence for WCAG 2.2 AA baseline. |
| AC-036 | Unit, integration, performance, and security evidence for non-secret structured event emission. |

## Current Evidence Status

| Evidence Area | Status | Reason |
|---|---|---|
| Unit evidence | Partially available locally | VS-002 auth-boundary, VS-003 state-machine, VS-004 warning-policy, VS-005 model-slot, VS-006 cost-guardrail, VS-007 provider-stub, VS-008 result-projection, VS-009 debate-orchestration, VS-010 synthesis, and VS-011 provider-key tests pass locally. Full future-slice unit matrix is incomplete. |
| Integration evidence | Partially available locally | VS-003 active-query, VS-004 acknowledgement, VS-005 model-slot configuration, VS-006 cost-guardrail, VS-007 provider-stub, VS-008 owner-scoped result endpoint, VS-009 debate result/timeout, VS-010 completed synthesis projection, and VS-011 provider-key endpoint integration tests pass locally. Durable database/provider integration tests are not implemented. |
| Contract evidence | Partially available locally | OpenAPI includes VS-002 through VS-011 endpoints/error contracts, provider-key status/add/remove schemas, initial-answer source schemas, structured debate-output schemas, structured final-synthesis schemas, result projection schemas, and partial missing-step fields; full standalone contract suite is not implemented. |
| E2E evidence | Partially available locally | VS-012 adds a local API E2E workflow across defaults, warnings, BYO key status/add/remove, accepted query creation, completed result retrieval, active-run release, and observability event assertions. VS-013 adds browser UI render evidence for the server-rendered `/ui` shell. Full browser automation against a running browser is not claimed. |
| Security evidence | Partially available locally | VS-012 adds focused BYO/provider-failure response and event redaction assertions. VS-013 adds deterministic repository secret/security scan evidence with 0 findings. External vendor SAST/DAST and dependency-vulnerability scans are not claimed. |
| Accessibility evidence | Partially available locally | VS-012 adds API accessibility contract assertions for warning readability and required result sections. VS-013 adds browser UI contract assertions for landmarks, labels, focus styling, minimum control size, warning copy, and result sections. Manual WCAG 2.2 AA audit evidence is not claimed. |
| Performance evidence | Partially available locally | VS-012 adds a local stubbed-workflow timing check under 500 ms plus event completeness assertions. Load, percentile, and CI performance artifacts are not available. |
| AI eval evidence | Partially available locally | Deterministic VS-010/VS-012 eval checks cover false-consensus preservation, citation target calculation, and high-stakes decision-support language. Full rubric-backed sampled eval evidence is not available because OQ-012 remains open. |
| CI evidence | Configured locally; remote run not available | VS-013 adds `make ci-evidence`, report artifacts under `build/`, and GitHub Actions upload configuration. A remote CI run has not been executed in this workspace. |

## Known Blockers Before Release Evidence Can Pass

- OQ-012 must define the citation rubric for AC-031.
- OQ-013 must define eval retention and sampling rules.
- A remote CI run must publish non-secret test artifacts before remote CI evidence can be claimed.
- `make quality` passed after script formatting/lint cleanup and pytest source-path configuration.
