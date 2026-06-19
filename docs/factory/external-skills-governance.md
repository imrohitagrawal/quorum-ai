# External Skills Governance

External skills are accelerators, not dependencies and not authorities. The factory must be able to operate without Paweł Huryn PM Skills, Dean Peters Product Manager Skills, Erik Holmberg AI PM Toolkit, Obra Superpowers, Addy Osmani Agent Skills, UI/UX Pro Max, or any other external skill.

## Allowed external sources and use

| Source | Use | Stage | Risk level | Notes |
|---|---|---|---|---|
| Obra Superpowers | Agentic workflow patterns, discipline, project setup inspiration | Orchestration, build loops | Medium | Use as process inspiration. Do not let it override local lifecycle order. |
| Addy Osmani Agent Skills | Engineering verification, spec-plan-build-test-review-ship discipline | Planning, build, review, ship | Low/Medium | Excellent for engineering gates. Map into internal skills instead of blindly delegating. |
| Paweł Huryn PM Skills | Product discovery, strategy, market research, launch, growth | Discovery, requirements, GTM | Medium | Strong PM lifecycle coverage. Use for PM inputs, not architecture authority. |
| Dean Peters Product Manager Skills | PM framework clarity, interview/discovery/PRD decomposition | Discovery, requirements | Medium | Strong PM education and framework rigor. Use for PM reasoning. |
| Erik Holmberg AI PM Toolkit | AI/ML PM templates, scripts, evals, cost/ROI, risk/governance | AI product requirements/evals | Medium | Use when product has AI/ML features. |
| Marily Nika AI PM material | AI product framing, eval mindset, builder workflow | AI product framing/evals | Medium | Use as conceptual reference, not executable code. |
| UI/UX Pro Max | UI structure, states, aesthetics, accessibility | UX/UI | Medium | Use for UI exploration and review. Internal UX/accessibility/security policy still wins. |
| Vercel/skills.sh skills | Highly specific operational skills | Only after review | High | Install only after review. |

## Dependency rule

The product factory is **not dependent** on any external skill. External skills may improve quality, but internal skills must provide a complete fallback path.

## Install strategy

Do not auto-install all external skills into every product.

Use a three-zone model:

1. `external/raw/` — cloned or downloaded third-party skills, never directly executed.
2. `external/reviewed/` — security-reviewed external skills.
3. `.agents/skills/` — internal curated skills that Codex may use.

## Promotion checklist

A third-party skill can be promoted only if:

- License is acceptable.
- `SKILL.md` is reviewed.
- Scripts are reviewed.
- No network calls are hidden.
- No secret access is requested.
- No shell-profile modification is performed.
- No destructive filesystem operations exist.
- Scope is narrow and clear.
- It does not override internal policies.
- It has a rollback/removal plan.

## Conflict handling

If an external skill conflicts with an internal skill or policy:

1. Explicit user instruction wins.
2. Approved Jira/Confluence source of truth wins.
3. Local policy wins.
4. Security/privacy/compliance/AI-safety wins.
5. ADR and approved architecture win.
6. Driver skill owns final artifact.
7. External skill becomes reviewer/input only.
8. Record the conflict in `docs/reviews/skill-conflicts.md`.

## Skill collision handling

When multiple skills can perform the same task:

- Use only one skill as **driver**.
- Use others only as **reviewers** or **input sources**.
- `factory-orchestrator` chooses the driver using `docs/skill-routing.md`.
- `skill-conflict-moderator` resolves unresolved disagreement.

Example:

```text
Task: create product discovery artifacts
Driver: internal product-discovery
Reviewers: Paweł PM discovery, Dean Peters PM framework, fanatic-critic
Forbidden: external skill directly overwrites docs without internal validation
```
