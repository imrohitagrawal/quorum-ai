# Module 1 - Problem And MVP

Status: Git draft only. Owner: product. Evidence: `docs/01-product-brief.md`, `docs/10-functional-requirements.md`, `docs/12-acceptance-criteria.md`.

## Problem solved

Users often ask several AI chatbots the same question to reduce hallucination risk, compare reasoning, and check whether answers agree. That manual process is slow, hard to audit, and still leaves users unsure which answer is reliable.

## Target User

The primary user is a public user or knowledge worker who needs more confidence in AI-generated answers for research, strategy, analysis, study, or creative work.

## Painful Workflow Today

The user manually opens multiple AI tools, copies the same prompt, compares outputs, checks sources, tracks contradictions, and writes their own final answer. This wastes time and hides disagreement.

## MVP value outcome

The MVP should let an authenticated user submit one query, run it across four configurable OpenRouter model slots, inspect source-backed model outputs, see two critique/debate rounds, and receive a synthesis that separates consensus, disagreement, source support, uncertainty, and recommendation.

## Why This Is The Smallest Valuable Slice

The MVP focuses on one query workflow instead of saved research spaces, teams, billing, or enterprise administration. That keeps the first release centered on the core value: transparent multi-model cross-validation.

## Success signal

- Hallucination-risk reduction through visible agreement, disagreement, and source support.
- Improved answer confidence without claiming guaranteed correctness.
- Cost-aware execution within the defined thresholds.
- Time saved compared with manual multi-chatbot comparison.
- Citation coverage for material factual claims when search succeeds.

## Not Included Yet

- Anonymous query execution.
- Saved long-term research history.
- Team workspaces, billing, admin, or audit workflows.
- Professional medical, legal, financial, or safety advice.
- Production release approval.

## Evidence

- Product goal and MVP scope: `docs/01-product-brief.md`.
- Requirements: FR-001 through FR-013 in `docs/10-functional-requirements.md`.
- Acceptance criteria: AC-001 through AC-036 in `docs/12-acceptance-criteria.md`.
- Release status: no-go in `docs/95-production-readiness-review.md`.
