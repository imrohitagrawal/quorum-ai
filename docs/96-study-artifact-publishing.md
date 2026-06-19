# Study Artifact Publishing

Status: Git draft only. Owner: product/documentation. Evidence: `docs/01-product-brief.md`, `docs/20-architecture.md`, `docs/57-test-evidence.md`, `docs/95-production-readiness-review.md`. Risk: public-facing material must not imply the MVP is implemented or released.

## MVP And Most Valued Outcome

Quorum AI's MVP outcome is a single authenticated query workflow that lets a user compare four configurable OpenRouter-backed models, inspect source-backed answers, see two critique rounds, and receive a synthesis that separates consensus, disagreement, uncertainty, source support, and recommendation.

The most valued outcome is hallucination-risk reduction through transparent comparison rather than blind trust in one model.

## Required Study Questions

- How does it solve the problem using AI: by orchestrating four model answers, source-backed evidence, critique rounds, and structured synthesis.
- How is it secure: by requiring authentication, owner authorization, server-side provider keys, redaction, and prompt-injection controls.
- How is it scalable: by starting with one active query per account, provider stubs in CI, async query runs, and measurable latency/cost targets.
- How does it meet enterprise-grade standards: through traceable requirements, ADRs, threat model, AI safety plan, test matrix, release no-go evidence, and local validation gates.

## Git Study Structure

| Artifact | Purpose | Publication Status |
|---|---|---|
| `docs/study/00-study-index.md` | Study entry point and module map. | Draft in Git |
| `docs/study/M0-read-this-first.md` | How to read the study pack safely. | Draft in Git |
| `docs/study/M1-problem-and-mvp.md` | Problem, users, MVP, non-goals, and evidence. | Draft in Git |
| `docs/study/M2-ai-solution-and-work-easing.md` | How AI helps and where humans stay in control. | Draft in Git |
| `docs/study/M3-security-scalability-enterprise.md` | Security, privacy, scalability, testing, and enterprise readiness. | Draft in Git |
| `docs/study/glossary.md` | Plain-English terminology. | Draft in Git |

## Confluence Draft Structure

No Confluence write is authorized in this step. If approved later, mirror the Git pages under the existing Quorum AI Confluence landing page:

- Study Index
- Read This First
- Problem And MVP
- AI Solution And Work Easing
- Security Scalability Enterprise Readiness
- Glossary

## Publication Controls

- Git is the authoring source.
- Confluence publication requires exact page payload review and explicit human approval.
- After any approved publication, re-read the page and update `docs/37-jira-confluence-sync-log.md`.
- Do not publish secrets, provider keys, private prompts, customer data, or unsupported release claims.

## Evidence Rules

- Built evidence is limited to generated FastAPI health/readiness skeleton and clean local gates.
- Planned behavior must be labelled as planned until implemented and tested.
- Release status is no-go per `docs/95-production-readiness-review.md`.
