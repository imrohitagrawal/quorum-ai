# Study Index

Status: Git draft only. Owner: documentation. Evidence: `docs/01-product-brief.md`, `docs/96-study-artifact-publishing.md`.

## Purpose

This study pack explains Quorum AI from zero: the user problem, the MVP outcome, the AI workflow, the safety model, and the engineering evidence needed before release.

## Modules

| Module | What It Explains | Evidence |
|---|---|---|
| `M0-read-this-first.md` | How to read the study pack and avoid confusing planned work with built work. | `docs/95-production-readiness-review.md` |
| `M1-problem-and-mvp.md` | The problem, target users, MVP, success signals, and non-goals. | `docs/01-product-brief.md`, `docs/10-functional-requirements.md` |
| `M2-ai-solution-and-work-easing.md` | How multi-model AI comparison, search grounding, debate, and synthesis reduce manual effort. | `docs/42-ai-safety-grounding.md`, `docs/20-architecture.md` |
| `M3-security-scalability-enterprise.md` | Security, privacy, scalability, testing, observability, and release readiness. | `docs/40-threat-model.md`, `docs/57-test-evidence.md` |
| `glossary.md` | Plain-English terms used across the project. | Repository docs |

## Current Build Status

- Built: FastAPI health/readiness skeleton, first authenticated query-run boundary, and clean local validation/quality gates.
- Planned: the full Quorum AI query workflow.
- Release decision: no-go until implementation and evidence exist.

## Safe Sharing Rule

These pages may be reviewed in Git. External or Confluence publication requires explicit approval of the exact content payload.
