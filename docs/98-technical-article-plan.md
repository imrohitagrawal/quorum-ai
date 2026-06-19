# Technical Article Plan

Status: Git draft only. Owner: technical writing. Evidence: `docs/20-architecture.md`, `docs/42-ai-safety-grounding.md`, `docs/95-production-readiness-review.md`.

## Article Thesis

Working title: "Designing Multi-Model AI Answers Without Hiding Disagreement"

Core idea: A multi-model AI product should not collapse every answer into a polished response. For decision support, the system should preserve model-level outputs, source support, disagreement, uncertainty, and cost/failure context.

The article must stay engineering-first: practical architecture, safety controls, testing evidence, and release honesty matter more than AI hype.

## Article Shape

1. The manual problem: users copy one question across several chatbots.
2. The engineering tension: synthesis is useful, but false consensus is dangerous.
3. The Quorum AI MVP: one authenticated query, four model slots, search grounding, two critique rounds, final synthesis.
4. Architecture pattern: modular FastAPI monolith, provider adapters, query-run state machine, server-side secrets.
5. Safety pattern: decision-support warnings, source references, prompt-injection boundaries, disagreement preservation.
6. Test pattern: map every acceptance criterion to unit, contract, E2E, security, accessibility, performance, resilience, and AI eval evidence.
7. Release honesty: local gates pass, but production release is a no-go until implementation evidence exists.
8. Practical checklist for teams building AI comparison workflows.

## Visual Brief

Create an original diagram showing:

- User query.
- Four model slots.
- Search/source layer.
- Debate round one and round two.
- Synthesis sections: consensus, disagreement, source support, uncertainty, recommendation.
- Guardrails: auth, cost, secrets, observability, AI safety.

## Grounding Sources

- Product brief: `docs/01-product-brief.md`.
- Architecture: `docs/20-architecture.md`.
- AI safety: `docs/42-ai-safety-grounding.md`.
- Test evidence plan: `docs/57-test-evidence.md`.
- Release no-go: `docs/95-production-readiness-review.md`.

## Sources used

Use only the repository evidence listed above plus approved external sources when research is explicitly requested.

## Do not invent

Do not invent production usage, user quotes, benchmark results, release approval, security scan results, provider behavior, or public launch metrics.

## Publication Rule

Do not publish until the full article draft, visual, source list, and safety review are approved by the user.
