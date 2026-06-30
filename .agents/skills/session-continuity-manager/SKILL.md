---
name: session-continuity-manager
description: Maintain cross-session context using handoff notes, worktrees, routes, validation evidence, commits, and source-of-truth updates.
---

# Session Continuity Manager Skill

## When to use
- continuing work in a new Codex tab/terminal/session
- handing off work from one agent/session to another
- splitting work across git worktrees or parallel subagents
- before compacting/clearing/closing a session

## When not to use
- Do not use this skill to bypass local factory policy, safety, security, privacy, compliance, Jira/Confluence source-of-truth, ADRs, or validation gates.
- Do not install or execute unreviewed external scripts, packages, MCP servers, browser automations, or shell commands.

## Inputs
- `docs/00-factory-console.md`
- `docs/session-handoff.md`
- git status/diff/log
- current skill route

## Owned outputs
- `docs/session-handoff.md`
- `docs/00-factory-console.md`
- branch/worktree notes in `docs/factory-status.md`

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
1. Run or simulate `make next` and `make skill-route`.
2. Record current branch/worktree, owned workstream, changed files, completed work, open questions, risks, assumptions, and validation result.
3. Commit completed atomic work before switching sessions when possible.
4. In the next session, read `AGENTS.md`, `docs/00-factory-console.md`, and `docs/session-handoff.md` before editing.
5. Do not redo completed work; continue from the next missing artifact.
6. If using external workflow skills such as Superpowers worktrees/handoff, apply them through this local handoff format.

## Quality bar
- A new session can understand the state in under five minutes without reading the full chat history.
- Handoff includes next driver skill, reviewers, blockers, files to touch, and validation commands.

## Validation
- Run `make handoff` after major sessions.
- Run `make validate` before branch handoff when feasible.

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
