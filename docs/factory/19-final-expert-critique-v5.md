# Final Expert Critique and V5 Hardening

## Final verdict

The V4.1 factory was good enough to guide Codex, but not yet deterministic enough to control Codex when many skills, Jira/Confluence workflows, optional external skills, and ORBI-specific governance are present.

V5 adds the missing control layer:

- deterministic skill routing;
- explicit driver/reviewer/moderator rules;
- optional ORBI profile isolation;
- Atlassian artifact map and roadmap;
- change-capture from Confluence/Jira/repo docs back into traceable work;
- clearer roadblock handling before implementation;
- no fabricated Jira/Confluence execution claims.

## What was weak before

1. Skill selection was mostly instruction-driven. `make next` suggested phases but did not explain driver skill, reviewer skills, risk triggers, or blockers.
2. ORBI rules were useful but too product-specific to become global defaults for every enterprise product.
3. Jira/Confluence artifacts existed, but the factory needed stronger roadmapping, change capture, and free-tier fallback controls.
4. External skills were recognized, but they needed even clearer isolation from local policy and source-of-truth artifacts.
5. A user could still be unsure what to ask Codex next.

## What V5 fixes

- `configs/skill-router.json` defines phase-driven routing.
- `scripts/skill_router.py` recommends driver skill, reviewer skills, blocking gates, missing evidence, and risk triggers.
- `make skill-route` and `make next` now explain the next action.
- `docs/39-skill-router-and-conflict-rules.md` documents conflict rules.
- `configs/atlassian-artifact-map.json` defines Jira/Confluence source-of-truth behavior.
- `docs/38-atlassian-integration-roadmap.md` defines manual, assisted MCP, and controlled sync stages.
- `custom-skill-packs/orbi-ai-operating-model-pack/` stores the reviewed ORBI pack for reference.
- `profiles/orbi/` makes ORBI activation explicit.
- `make apply-orbi-profile` activates ORBI only when desired.

## Final operating principle

The user should only need to provide an idea. The factory must ask clarifying questions, build the problem statement, route to the correct skill, produce artifacts, suggest next actions, and block unsafe or low-evidence progress.
