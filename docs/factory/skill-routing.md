# Skill Routing

## Principle

One skill drives. Others review. The factory orchestrator decides routing and calls `skill-conflict-moderator` when skills disagree or when multiple skills can perform the same task.

## Routing map

| Work item | Driver skill | Reviewer/input skills |
|---|---|---|
| Jira/Confluence intake | source-of-truth-sync | jira-issue-authoring, change-control, traceability-management |
| Jira issue creation/update | jira-issue-authoring | requirements-engineering, test-architecture, security-threat-modeling |
| Stakeholder/user discovery | stakeholder-discovery | product-discovery, Paweł PM Skills, Dean Peters PM Skills, fanatic-critic |
| Prioritization and roadmap | product-prioritization | Paweł PM Skills, Dean Peters PM Skills, fanatic-critic, release-readiness |
| Functional/NFR requirements | requirements-engineering | living-spec-builder, Erik Holmberg AI PM Toolkit when AI product, security-threat-modeling, test-architecture |
| Learner/living spec | living-spec-builder | traceability-management, documentation-engineering, fanatic-critic |
| Problem decomposition | problem-decomposition | product-prioritization, implementation-planning, Addy Osmani Agent Skills, Obra Superpowers |
| Business rules/state machines | domain-modeling | business-rules-modeling, test-architecture |
| Product naming after requirements freeze | product-naming | product-discovery, stakeholder-discovery, fanatic-critic |
| Architecture | architecture-design | security-threat-modeling, sre-observability, platform-engineering, Addy Osmani Agent Skills |
| API contracts | api-contract-governance | contract-testing, security-threat-modeling |
| Data model | data-governance | privacy-compliance, security-threat-modeling |
| UX | ux-design | UI/UX Pro Max, accessibility-testing, fanatic-critic |
| Visual storytelling after architecture approval | architecture-visual-storytelling | architecture-design, ux-design, documentation-engineering, fanatic-critic |
| Security | security-threat-modeling | devsecops, supply-chain-security |
| AI safety | ai-safety-grounding | prompt-injection-defense, llm-evaluation, Erik Holmberg AI PM Toolkit |
| Test strategy | test-architecture | contract-testing, resilience-testing, test-data-engineering |
| Implementation plan | implementation-planning | problem-decomposition, platform-engineering, ci-cd-engineering |
| Code slice | vertical-slice-builder | code-quality-review, devsecops, sre-observability |
| Confluence operational guide | confluence-operational-guide-subagent | jira-issue-authoring, documentation-engineering, educational-awareness-writer |
| Educational content | educational-awareness-writer | architecture-design, documentation-engineering, ai-safety-grounding |
| Release | release-readiness | release-notes-generation, support-readiness |
| Operations | post-release-operations | production-feedback-loop, support-readiness |

## Conflict resolution

- Local policies beat external skills.
- Security/privacy/compliance/safety beats speed and UX convenience.
- Source-backed requirement beats generated assumption.
- ADR beats generic framework preference.
- Driver skill owns final artifact.
- Reviewer skills can block only by evidence-backed finding.
- Fanatic critic can block when evidence is insufficient.
- External skills are never allowed to directly overwrite source-of-truth artifacts.
