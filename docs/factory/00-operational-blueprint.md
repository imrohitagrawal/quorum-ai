# 0-to-100 Operational Blueprint

This is the step-by-step operating model for building a reusable Codex product skeleton and using it for any product.

## A. One-time setup: build the factory

1. Create or clone `codex-product-factory`.
2. Keep root `AGENTS.md` small and directive-based.
3. Put all lifecycle behavior in `.agents/skills/*/SKILL.md`.
4. Put reusable constraints in `policies/`.
5. Put product templates in `templates/product/`.
6. Put validation gates in `scripts/`.
7. Add external-skill governance in `docs/external-skills-governance.md`.
8. Test the factory using a dummy `PRODUCT_IDEA.md`.
9. Package it as a GitHub template repo.
10. Make teams create products only via `scripts/bootstrap_product.py`.

## B. Per-product usage

1. Run:
   ```bash
   make bootstrap PRODUCT=../my-product
   ```
2. Edit only `PRODUCT_IDEA.md` with the initial idea.
3. Start Codex from the product directory.
4. Ask only:
   ```text
   Run product factory.
   ```
5. Codex runs `factory-orchestrator`.
6. `factory-orchestrator` runs lifecycle skills in order.
7. Validation scripts block premature implementation.
8. Codex builds one vertical slice at a time.
9. CI validates quality and security.
10. Release-readiness skill produces go/no-go evidence.

## C. Lifecycle order

```text
PRODUCT_IDEA.md
  -> product-discovery
  -> requirements-engineering
  -> fanatic-critic
  -> architecture-design
  -> ux-design
  -> security-threat-modeling
  -> test-architecture
  -> implementation-planning
  -> vertical-slice-builder
  -> code-quality-review
  -> performance-engineering
  -> sre-observability
  -> release-readiness
  -> post-release-operations
```

## D. Where external skills are used

| Stage | Primary internal skill | Optional external input | Who wins on conflict |
|---|---|---|---|
| Discovery | product-discovery | Paweł Huryn PM discovery, Dean Peters discovery frameworks | Internal skill |
| Strategy | requirements-engineering | Paweł Huryn strategy, Dean Peters PM methods | Internal skill |
| AI/ML product specifics | requirements-engineering, test-architecture | Erik Holmberg AI PM Toolkit, Marily Nika AI PM concepts | Internal skill |
| Engineering workflow | implementation-planning, vertical-slice-builder | Addy Osmani agent-skills | Internal skill |
| Agentic workflow discipline | factory-orchestrator | Obra Superpowers | Internal skill |
| UX/UI | ux-design | UI/UX Pro Max | Internal skill |
| Release | release-readiness | Addy ship/review patterns, PM launch skills | Internal skill |

## E. Conflict resolution

When two skills produce conflicting guidance:

1. Prefer product-specific requirements over generic skill guidance.
2. Prefer internal policies over external skills.
3. Prefer security over UX convenience.
4. Prefer correctness over speed.
5. Prefer maintainability over cleverness.
6. Prefer measurable acceptance criteria over vague PM frameworks.
7. Prefer ADR decisions over unstated assumptions.
8. If two options are both valid, create an ADR and choose one.
9. If conflict affects business behavior, record it in `docs/07-open-questions.md` and do not invent an answer.
10. If conflict affects security or data loss, block the phase until resolved.

## F. How Codex should know what to do

Codex should not depend on manually pasted prompts. It should discover:

- `AGENTS.md` for global product-factory rules.
- `.agents/skills/factory-orchestrator/SKILL.md` for lifecycle control.
- Stage-specific `SKILL.md` files for execution.
- `policies/*.md` for enterprise constraints.
- `scripts/validate_*.py` for gates.
- `docs/` for product evidence.
