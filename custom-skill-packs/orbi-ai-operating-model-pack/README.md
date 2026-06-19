# ORBI AI Operating Model Pack

Reusable governance instructions for building new AI products under **ORBI / Orbisynth-AI**.

This pack gives you three ways to use the same operating model:

1. **Codex-compatible**: use `AGENTS.md` at the repository root.
2. **Claude Skill**: use `.claude/skills/orbi-ai-operating-model/SKILL.md`.
3. **Claude Code sub-agent**: use `.claude/agents/orbi-ai-governance-agent.md`.

## Core rule

ORBI is the operating layer for **new AI product incubation and shared AI product standards**.

Do not use ORBI as a dumping ground.

## Scope exclusions

Do not modify, move, rename, archive, merge, duplicate, or absorb:

- Aegis
- CiteVyn
- Existing Aegis Jira/Confluence assets
- Existing CiteVyn Jira/Confluence assets

Aegis and CiteVyn may be referenced only as external references when explicitly useful.

## Recommended repo usage with Codex

Copy `AGENTS.md` into the root of your project repo. Then start from:

```text
PRODUCT_IDEA.md
```

Codex should then:

1. Ask clarifying questions.
2. Produce a problem statement.
3. Create PRD/SRS/ADR/quality/runbook artifacts.
4. Slice work into small Jira-ready units.
5. Keep traceability from idea → requirement → implementation → test → release.

## Generated files

```text
AGENTS.md
.claude/skills/orbi-ai-operating-model/SKILL.md
.claude/agents/orbi-ai-governance-agent.md
prompts/codex_product_bootstrap_prompt.md
prompts/orbi_atlassian_artifact_prompt.md
templates/PRODUCT_IDEA.md
templates/PRD.md
templates/SRS_SSD.md
templates/ADR.md
templates/JIRA_DESCRIPTION_BLOCK.md
templates/ACCEPTANCE_CRITERIA.md
templates/QUALITY_GATE.md
templates/RELEASE_READINESS.md
templates/RUNBOOK.md
```

## Codex-specific readiness notes

For Codex-only usage, the important files are:

```text
AGENTS.md
.agents/skills/orbi-ai-operating-model/SKILL.md
.codex/agents/orbi-governance-reviewer.toml
PRODUCT_IDEA.md
PLANS.md
templates/
prompts/
```

The `.claude/` files are retained for portability, but Codex will not rely on them directly.

Before implementation starts, define the actual technology stack, package manager, test command, lint command, build command, and repository layout for the product being built.
