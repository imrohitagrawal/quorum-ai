
# Research Basis And External Skill Sources

This skeleton intentionally treats external skills as accelerators, not authority. The following sources influenced the V4 upgrade and should be reviewed periodically before use because the agent-skills ecosystem is fast-moving.

## Skill ecosystem references

| Source | Why it matters | Factory usage |
|---|---|---|
| OpenAI Codex Skills | Defines Codex skills as task-specific packages containing instructions, resources, and optional scripts with progressive disclosure. | Use as the primary compatibility model for internal `.agents/skills/*/SKILL.md`. |
| OpenAI AGENTS.md guidance | Explains how Codex discovers project-specific guidance before work starts. | Use for repo-level operating instructions and command expectations. |
| Vercel Agent Skills documentation | Defines agent skills as packaged capabilities that support structured, production-ready agent behavior. | Use for skill-package pattern and installation awareness only. |
| skills.sh / Vercel skills CLI | Provides discovery and installation of skill packages across several agent clients. | Use as a discovery directory only; security audit required before adoption. |
| Addy Osmani agent-skills | Production-grade engineering skill patterns and phase model. | Use as engineering reviewer input. |
| Atlassian Rovo MCP Server | Provides real-time Jira/Confluence interactions through MCP with OAuth and access controls. | Use for optional Jira/Confluence assisted sync when approved. |
| PM skills by Paweł Huryn and Dean Peters | Product discovery, PRD, prioritization, stakeholder, and PM execution references. | Use as PM reviewer input. |
| Erik Holmberg AI PM Toolkit | AI/ML PM framing, prompting, and product management templates. | Use as AI PM reviewer input. |
| Figma MCP/design skills | Design-to-code and design-system handoff patterns. | Use as UX/design reviewer input where Figma is part of the workflow. |
| OWASP and security skill collections | Security control and risk-mapping patterns. | Use as security reviewer input, never to bypass local security policy. |

## Research caution

Recent research on agent skills suggests curated focused skills can improve agent outcomes, but benefits vary by domain and some skills can cause regressions. Another research direction highlights semantic supply-chain risk in `SKILL.md` metadata and instructions. Therefore, this factory requires provenance, permission, sandboxing, local-policy review, and regression checks before external skill adoption.

## Enterprise rule

Do not run `npx skills add ...` directly inside an enterprise repository unless the external-skill-security-auditor has approved the skill source, permission profile, scripts, and local-policy compatibility.
