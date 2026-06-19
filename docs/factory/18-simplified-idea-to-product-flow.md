# Simplified Idea-to-Product Flow

The product factory should start from a rough idea and guide the user forward.

## Target experience

The user should be able to do this:

```text
I want to build <idea>.
```

The factory should then:

1. capture the idea in `PRODUCT_IDEA.md`;
2. ask only the smallest useful set of clarifying questions;
3. generate the problem statement;
4. suggest the first vertical slice;
5. generate requirements, acceptance criteria, Jira issues, and Confluence guide;
6. design architecture, tests, security, AI safety, observability, and release gates;
7. keep `docs/00-factory-console.md` updated with what to do next.

## Why this was added in V4.1

The V4 skeleton was strong but still expected the user to understand the factory lifecycle. V4.1 adds a product-coach layer so the skeleton guides the user step by step.

## Relationship to Superpowers-style skills

Superpowers-style workflows are useful because they encourage composable skills, planning, checkpoints, reviews, TDD, and controlled execution. This factory uses the same idea, but adds enterprise product-management, Jira/Confluence, learner-spec, security, AI-safety, observability, and release-governance layers.

## Golden rule

The factory should not ask for everything upfront. It should ask for what matters now, suggest a safe default for what can wait, and record assumptions visibly.
