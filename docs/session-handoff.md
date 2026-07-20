# Session Handoff

## Date/time
2026-07-20T14:06:40+05:30

## Current branch/worktree
feat/r2-s2-evaluation-engine

## Current phase
Operate, learn, and improve

## Current driver skill
`production-feedback-loop`

## Reviewer skills
- `post-release-operations`
- `support-readiness`
- `product-discovery`
- `fanatic-critic`
- `ai-feature-classifier`
- `grounding-contract-builder`
- `prompt-registry-manager`
- `model-risk-register`
- `llm-evaluation`
- `prompt-injection-defense`
- `security-threat-modeling`
- `privacy-compliance`
- `data-governance`
- `owasp-control-mapper`
- `supply-chain-security`
- `external-skill-security-auditor`
- `skill-contract-auditor`
- `jira-confluence-mcp-integration`
- `ux-research-synthesizer`
- `ux-design`
- `content-design`
- `design-system-governance`
- `accessibility-testing`
- `sre-observability`
- `performance-engineering`
- `resilience-testing`
- `incident-drill`
- `mvp-value-outcome-finder`
- `study-artifact-publisher`
- `project-knowledge-base-publisher`
- `diagram-media-standards-governor`
- `faq-wiki-generator`
- `technical-article-writer`
- `linkedin-technical-post-writer`
- `git-confluence-publish-reviewer`
- `python-fastapi-backend-guardrails`
- `api-contract-governance`
- `api-error-model`
- `test-architecture`

## Blocking gates
- `production-readiness-review`

## Missing or incomplete evidence
- None

## Git status
```text
M docs/analysis/R2-plan-review-findings.md
 M docs/session-handoff.md
 M scripts/session_handoff.py
?? MORNING-REPORT.md
?? S2-BUILD-PROMPT.md
?? S2.1-DEBT-011-BUILD-PROMPT.md
?? design_handoff_quorum_ui/
?? docs/analysis/R2-S2-handback.md
```

## Diff stat
```text
docs/analysis/R2-plan-review-findings.md |   4 +-
 docs/session-handoff.md                  | 159 ++++++-------------------------
 scripts/session_handoff.py               |  13 +++
 3 files changed, 46 insertions(+), 130 deletions(-)
```

## Completed in this session
- Update manually before closing the session.

## Decisions made
- Update manually before closing the session.

## Assumptions recorded
- Update `docs/ASSUMPTIONS.md` when needed.

## Open questions
- Update `docs/13-open-questions.md` when needed.

## Durable records (this file is REGENERATED — it cannot hold session state)
Everything below the "Current phase" line is derived from `make skill-route`,
and this whole file is overwritten by `scripts/session_handoff.py`. Anything a
session needs to survive into the next one lives in a tracked doc instead:
- `docs/analysis/R2-plan-review-findings.md` — **PHASE STATUS** is the
  authoritative phase, not the "Current phase" line above (which reports the
  factory router's view, overridden for R2 under AGENTS.md precedence #2).
- The current slice's handback, linked from that PHASE STATUS block.
- `docs/63-technical-debt-register.md` — accepted debt and what blocks what.

## Risks/blockers
- Update manually before closing the session.

## Validation run
```bash
make next
make skill-route
make validate
```

## Validation result
- Update after running checks.

## Next best action
Review production signals, incidents, support feedback, and product metrics. Propose the next iteration with evidence.

## Suggested next Codex prompt
```text
Continue from AGENTS.md, docs/00-factory-console.md, and docs/session-handoff.md.
Read the PHASE STATUS block in docs/analysis/R2-plan-review-findings.md and the
slice handback it links: the phase line in this file is the router's view, not
the authoritative one.
Do not redo completed work.
Use the recommended driver skill and reviewer skills from make skill-route.
Before editing, list the files you intend to modify.
```
