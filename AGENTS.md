# Product Repository Instructions

This repository was generated from Codex Product Factory Enterprise Edition.


## Simplified start

The user may start in either way:

1. Fill `PRODUCT_IDEA.md`; or
2. Tell the idea directly in the Codex prompt.

If the idea is supplied in the prompt, first write it into `PRODUCT_IDEA.md`. Then run the `idea-intake-clarifier` skill. Ask the smallest useful set of clarifying questions before generating requirements, architecture, Jira issues, Confluence pages, tests, or implementation code.

Maintain `docs/00-factory-console.md` after every meaningful step. It must show current phase, next best action, suggested prompt, questions, assumptions, suggestions, and validation status.

## Mandatory lifecycle

Run `.agents/skills/factory-orchestrator/SKILL.md` before implementation.

Do not code until these exist and validate:

- `docs/01-product-brief.md`
- `docs/03-source-of-truth.md`
- `docs/10-functional-requirements.md`
- `docs/11-non-functional-requirements.md`
- `docs/12-acceptance-criteria.md`
- `docs/17-requirement-registry.md`
- `docs/18-requirement-traceability-matrix.md`
- `docs/20-architecture.md`
- `docs/21-domain-model.md`
- `docs/40-threat-model.md`
- `docs/42-ai-safety-grounding.md`
- `docs/50-test-strategy.md`
- `docs/60-implementation-plan.md`
- `docs/70-ci-cd-plan.md`
- `docs/80-observability.md`

## Jira workflow

Use only statuses defined in `configs/jira-statuses.json`:

Backlog → To Do → Ready For Dev → In Development → Code Review → CI Validation → QA Ready → In QA → QA Verified → Closed.

`Cancelled` and `Duplicate` are terminal. `Closed` can be reopened only with explicit human approval and reason.

## Validation

Run:

```bash
make validate
make quality
```

Stop on failed validation gates.


## Review before "done"

Green gates are necessary but not sufficient — they catch known failures, not
new bugs a change introduces. Before declaring any non-trivial change complete:

- **Adversarially review the diff with independent subagents.** At minimum a
  correctness pass; and for anything touching security, secret handling, auth,
  or detection/validation logic, a reviewer whose explicit job is to *break*
  the change and find an evasion. Do this proactively — do not wait to be
  asked, and do not rely on a single self-assessment.
- **A behavioural change ships with a test that would fail without it.** This
  applies to helper scripts too (e.g. `scripts/security_scan.py`), not only
  `src/` — CI coverage (`--cov=src`) does not see them.
- **When you loosen or suppress a check, prove both directions:** the false
  positive is gone AND every genuine case the check must still catch is still
  caught. Never gate a secret/threat check on whole-line substrings; key off
  the matched token or value.


## V5 deterministic skill routing

Before choosing a skill manually, run or simulate:

```bash
make skill-route
make next
```

Use the recommended driver skill as the single writer for the next missing artifact. Use reviewer skills only to critique and request changes. If skills conflict, apply this precedence: safety/security/privacy/compliance, explicit user approval within policy, approved Jira/Confluence source of truth, local factory policies, ADRs, driver skill output, reviewer findings, external skill suggestions.

ORBI-specific rules are not global defaults. Activate them only through `make apply-orbi-profile` or explicit user instruction, then read `AGENTS.ORBI.md`.


## V5.1 study, publishing, and public-artifact backbone

After the MVP, requirements, architecture, tests, and release evidence are clear enough, the factory must also prepare study and communication artifacts:

- `docs/96-study-artifact-publishing.md`
- `docs/study/00-study-index.md`
- `docs/study/M1-problem-and-mvp.md`
- `docs/study/M2-ai-solution-and-work-easing.md`
- `docs/study/M3-security-scalability-enterprise.md`
- `docs/97-faq-wiki-plan.md`
- `docs/98-technical-article-plan.md`
- `docs/99-linkedin-post-plan.md`
- `docs/100-industry-and-integration-practices.md`

The first question is always: what is the MVP and most valued outcome? Public and Confluence artifacts must explain how the product solves a real problem using AI, how it eases work, how it is secure and scalable, and how it meets enterprise standards.

For Git or Confluence publication, draft first, show the exact diff/page payload, require explicit human confirmation, publish only through approved tools, re-read after publish, and update `docs/37-jira-confluence-sync-log.md`.


## V5.2 external-skills-first and skill onboarding

When a new capability is needed, do not immediately invent a local custom skill. First use `external-skill-discovery-advisor` and `skill-research-librarian` to check existing skills from skills.sh, official providers, and reputable GitHub sources.

The adoption flow is:

```text
find existing skill -> audit provenance/security/license -> approve mode -> register -> route -> validate -> optionally wrap locally
```

Default activation mode for external skills is `reviewer-only`. External skills can help with Superpowers-style planning/worktrees/handoff, Addy-style SDLC, PM discovery, AI PM evaluation, UI/UX, testing, database/platform, and publishing. They still cannot override local policies, source-of-truth records, validation gates, or explicit human approval for side effects.

Use these commands:

```bash
make skill-discover
make skill-onboarding-check
python scripts/audit_external_skill.py <skill-folder>
python scripts/onboard_external_skill.py --name <name> --source-url <url>
```

## Session continuity

Before ending or handing off a session:

```bash
make next
make skill-route
make handoff
```

A new session must read `AGENTS.md`, `docs/00-factory-console.md`, and `docs/session-handoff.md` before editing. Use git worktrees for parallel sessions and keep one owner per artifact family.

## User-guided start

If `PRODUCT_IDEA.md` is empty, placeholder-only, or the user gives the idea in chat, ask for the problem in plain language first. Then suggest the next best action. The user should not have to guess which skill or file to use.
