# Codex Prompt — Verify ORBI Pack Readiness

Read AGENTS.md, PRODUCT_IDEA.md, PLANS.md, and templates/.

Verify that the repository is ready for Codex-driven end-to-end product delivery.

Check:
- AGENTS.md is loaded from repository root.
- ORBI skill exists under .agents/skills/orbi-ai-operating-model/SKILL.md.
- Codex custom reviewer agent exists under .codex/agents/orbi-governance-reviewer.toml.
- Product idea exists at PRODUCT_IDEA.md.
- Implementation stack, test commands, lint commands, build commands, and dependency manager are defined before coding.
- No secrets or sensitive data are present.

If missing project-specific implementation commands, propose them but do not add dependencies without approval.
