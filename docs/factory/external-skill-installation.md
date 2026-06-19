# External Skill Installation Playbook

## Principle

Install external skills only into a review sandbox first. Promote only curated behavior into `.agents/skills/`.

## Paweł Huryn PM Skills

Use at discovery, strategy, market research, launch, and growth stages.

Recommended Codex install path from the upstream repo:

```bash
codex plugin marketplace add phuryn/pm-skills
codex plugin add pm-product-discovery@pm-skills
codex plugin add pm-product-strategy@pm-skills
codex plugin add pm-market-research@pm-skills
codex plugin add pm-execution@pm-skills
codex plugin add pm-ai-shipping@pm-skills
```

Factory usage:

- Driver remains internal `product-discovery` or `requirements-engineering`.
- PM Skills act as reviewer/input source.
- Findings go to `docs/reviews/pm-skill-review.md`.

## Dean Peters Product Manager Skills

Use at discovery and requirements stages for PM framework rigor.

Factory usage:

- Do not make it the driver.
- Use it to check whether PRD, stakeholder questions, prioritization, and epic breakdown are complete.

## Erik Holmberg AI PM Toolkit

Use only when product has AI/ML/LLM features.

Factory usage:

- Pull eval, cost, risk, adoption, and governance ideas into requirements and test strategy.
- Do not use generic prompts directly as final requirements.

## Marily Nika AI PM material

Use for AI product framing and evaluation mindset.

Factory usage:

- Capture AI-specific product risks.
- Add AI eval requirements.
- Add user trust, quality, and safety metrics.

## Obra Superpowers

Use at orchestration and build loop stage.

Recommended use:

- Install from Codex plugin marketplace if available through `/plugins`.
- Use it to improve execution discipline.
- Do not allow it to replace factory lifecycle order.

## Addy Osmani agent-skills

Use at implementation planning, verification, review, and ship stages.

Recommended use:

- Use `/spec`, `/plan`, `/build`, `/test`, `/review`, `/ship` patterns as references.
- Internal skills own final gates.

## UI/UX Pro Max

Use at UX design and UI implementation review stages.

Factory usage:

- Use for screen flows, visual structure, UI states, accessibility, responsive behavior.
- Internal UX policy wins on conflict.

## Promotion procedure

1. Clone external skill into `external/raw/<source>`.
2. Review `SKILL.md` and scripts.
3. Record review in `docs/reviews/external-skill-review.md`.
4. Copy only approved instructions into internal skill or use as reviewer.
5. Never give unreviewed skills production credentials.
