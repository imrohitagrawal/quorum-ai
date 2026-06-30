---
name: skill-research-librarian
description: Maintain the factory skill research index so new skills can be discovered, evaluated, and adopted without hardcoding one fixed list forever.
---

# Skill Research Librarian Skill

## When to use
- updating the external skill research snapshot
- comparing skills from skills.sh, GitHub, official vendors, or community repositories
- deciding whether to build, wrap, or reuse a skill

## When not to use
- Do not use this skill to bypass local factory policy, safety, security, privacy, compliance, Jira/Confluence source-of-truth, ADRs, or validation gates.
- Do not install or execute unreviewed external scripts, packages, MCP servers, browser automations, or shell commands.

## Inputs
- `configs/external-skill-research-index.json`
- `docs/107-skills-sh-research-snapshot.md`
- official docs and marketplace pages when browsing is available

## Owned outputs
- `configs/external-skill-research-index.json`
- `docs/107-skills-sh-research-snapshot.md`

## Allowed tools
- Read repository files relevant to the skill decision.
- Write only the owned outputs listed above.
- Use skills.sh, GitHub, and official project docs as discovery sources when online access is available.
- Use installed external skills only after provenance, license, security, and scope review.

## Forbidden actions
- Do not fabricate skill install success, audit results, source URLs, versions, licenses, Jira IDs, Confluence page IDs, CI evidence, or production metrics.
- Do not promote a third-party skill to authority without explicit human approval and an entry in `configs/external-skill-registry.json`.
- Do not allow an external skill to edit files outside its approved scope.

## Procedure
1. Refresh the index by domain: workflow, PM, AI PM, engineering, testing, design, database, cloud, content, publishing, browser automation, and security.
2. Record source quality: official, reputable community, individual expert, marketplace listing, or unverified.
3. Record install method, supported agents, license, audit status, and known risks when available.
4. Mark whether the skill should be default-advisor, optional-advisor, tool-specific, sandbox-only, or reject.
5. Never treat marketplace rank as proof of correctness or security.

## Quality bar
- The index helps the factory find existing skills first while still protecting enterprise quality.
- Every entry has purpose, trigger, trust tier, activation mode, and review requirement.

## Validation
- Run `make skill-onboarding-check`.
- JSON must parse and required docs must exist.

## Handoff contract
- Update owned outputs.
- Record decisions, assumptions, risks, blockers, and next action.
- Add links to source artifacts, reviews, and validation evidence.

## Stop conditions
- Missing provenance, unclear license, unsafe permissions, network/secrets/shell risk, or policy conflict.
- Skill conflicts with local architecture, security, testing, privacy, or source-of-truth rules.
- Validation failure.

## Examples
- Good: a reviewed external skill is approved as reviewer-only for one phase, with source URL, commit/ref, license, allowed files, denied operations, validation evidence, and owner.

## Anti-examples
- Bad: install a trending skill because it is popular, without reading `SKILL.md`, scripts, package files, permissions, and known audit status.

---

## Enterprise Skill Contract

## When to use
- Use this skill only for the phase described in its frontmatter and procedure.

## When not to use
- Do not use this skill to bypass a more specific skill, local policy, or source-of-truth requirement.

## Owned outputs
- The outputs listed above plus any review notes explicitly assigned by the factory orchestrator.

## Allowed tools
- Repository read/write for owned artifacts.
- Approved MCP/API tools only when access is configured and authorized.
- External skills only as reviewer/reference inputs after governance approval.

## Forbidden actions
- Do not fabricate facts, approvals, Jira IDs, Confluence IDs, CI evidence, security results, or production metrics.
- Do not proceed past a blocking gate with unresolved source-of-truth, security, privacy, AI-safety, or validation issues.

## Procedure
- Follow the phase-specific steps above.
- Mark assumptions explicitly.
- Add traceability to requirements, Jira, tests, evidence, and reviews.
- Escalate conflicts to `skill-conflict-moderator`.

## Quality bar
- Output is specific, testable, owned, sourced, traceable, and evidence-backed.
- Generic advice is not acceptable as a final artifact.

## Validation
- Run `make validate` after structural updates.
- Run `FACTORY_STRICT=1 make validate-strict` before release readiness.

## Handoff contract
- Update owned artifacts.
- Record open questions, risks, and evidence.
- Identify the next required skill or blocker.

## Stop conditions
- Missing source evidence.
- Contradictory requirements.
- Missing owner for a blocking decision.
- Validation failure.

## Examples
- Good: documented decision with owner, source, metric, test, and evidence.

## Anti-examples
- Bad: placeholder-only output, unverified claim, or implementation without traceability.
