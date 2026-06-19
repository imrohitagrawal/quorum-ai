# Quality Gate Contracts

The factory uses two validation layers.

## Layer 1: Skeleton validation

```bash
make validate
```

This proves that the product factory structure, required files, scripts, schemas, and skill packages exist.

## Layer 2: Strict enterprise validation

```bash
FACTORY_STRICT=1 make validate-strict
```

This proves product-specific artifacts are filled with real evidence and are not placeholder-only documents.

## Gate contracts

| Gate | Must prove |
|---|---|
| G0 Intake | Product intent, users, sources, non-goals, assumptions |
| G1 Discovery | customer/job evidence, success metrics, opportunity map |
| G2 Living Spec | FR/NFR/AC/edge cases/learner spec/traceability |
| G2A Jira | issue quality, status validity, test/security mapping |
| G3 Architecture | ADRs, domain model, API/data contracts, diagrams |
| G4 Security/AI | threat model, controls, AI grounding, prompt injection defense, model risk |
| G5 Quality | unit/integration/contract/e2e/performance/security/accessibility/eval plans |
| G6 Implementation | vertical slices, feature flags, migration/rollback, code ownership |
| G7 Release | CI evidence, test evidence, security scans, performance baseline, rollback proof |
| G8 Operations | SLO, alerts, dashboard, runbook, incident drill, support readiness |
| G9 Feedback | support, telemetry, incidents, next-iteration backlog |

## Placeholder policy

Template placeholders are allowed only before the product is filled. Strict validation blocks placeholder language such as `TBD`, `Placeholder`, `Replace with`, and unresolved mandatory sections.
