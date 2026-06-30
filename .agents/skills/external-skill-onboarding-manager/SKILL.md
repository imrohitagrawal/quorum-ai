---
name: external-skill-onboarding-manager
description: Onboard new external skills into the factory through provenance, security, compatibility, routing, and evaluation controls.
---

# External Skill Onboarding Manager Skill

## When to use
- a new external skill is installed, copied, vendored, or proposed
- the user asks to support new skill sources in the future
- a local custom skill should be replaced by an existing community/official skill

## When not to use
- Do not use this skill to bypass local factory policy, safety, security, privacy, compliance, Jira/Confluence source-of-truth, ADRs, or validation gates.
- Do not install or execute unreviewed external scripts, packages, MCP servers, browser automations, or shell commands.

## Inputs
- candidate skill folder or source URL
- `configs/skill-onboarding-policy.json`
- `configs/external-skill-registry.json`
- `configs/external-skill-research-index.json`

## Owned outputs
- `configs/external-skill-registry.json`
- `docs/106-skill-onboarding-runbook.md`
- `docs/reviews/external-skill-security-review.md`

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
1. Capture provenance: source URL, owner, repo, path, commit/ref, license, install method, and date.
2. Check format: `SKILL.md`, frontmatter, description specificity, triggers, dependencies, scripts, and examples.
3. Classify permissions: read-only guidance, repo write, shell, network, browser, MCP, secrets, deployment, or external write.
4. Assign activation mode: blocked, reviewer-only, sandbox, workspace-approved, or promoted internal wrapper.
5. Add route mapping only after security review and human approval.
6. Add a local wrapper skill only when the external skill needs enterprise guardrails or source-of-truth controls.
7. Record evaluation: sample task, expected artifact, validation command, and pass/fail result.

## Quality bar
- No skill becomes active without provenance, scope, risk rating, allowed/forbidden operations, owner, and review date.
- Popularity is treated as discovery signal, not trust signal.

## Validation
- Run `python scripts/validate_skill_onboarding.py`.
- Run `python scripts/audit_external_skill.py <skill-folder>` for local skill folders.

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
