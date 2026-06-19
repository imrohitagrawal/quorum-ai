# Module 0 - Read This First

Status: Git draft only. Last reviewed: 2026-06-16. Evidence: `docs/95-production-readiness-review.md`.

## What This Study Pack Is

This pack is a learning companion for Quorum AI. It helps a newcomer understand the product without reading every source document first.

## How To Read It

1. Start with `M1-problem-and-mvp.md` to understand the user pain and smallest valuable outcome.
2. Read `M2-ai-solution-and-work-easing.md` to see how AI comparison, grounding, critique, and synthesis are intended to help.
3. Read `M3-security-scalability-enterprise.md` to understand the controls needed before public release.
4. Use `glossary.md` whenever a term is unfamiliar.

## Built Versus Planned

- Built now: generated FastAPI skeleton with health/readiness endpoints, a first authenticated query-run boundary, and clean local gates.
- Planned next: implementation slices in `docs/61-vertical-slice-plan.md`.
- Not claimed: production readiness, live provider integration, full UI, CI release evidence, security scan evidence, accessibility evidence, performance evidence, or AI eval evidence.

## Safety Rules

- Do not treat study pages as release approval.
- Do not paste provider keys, secrets, private prompts, or customer data into study artifacts.
- Do not publish externally without human approval of the exact draft.
