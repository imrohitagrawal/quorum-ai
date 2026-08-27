# Session Handoff

## Date/time
2026-08-28T00:58:16+05:30

## Open work
`docs/65-open-work.md` — the source of truth for what is open, what blocks what,
and the evidence for each row. Checked against the tree by
`scripts/check_open_work.py --check` inside `make validate`. The "Current phase"
line further down this file is the factory router's view of the lifecycle, not a
work status.

## Latest narrative handoff
`docs/analysis/2026-08-27-session-handoff.md` — read this for full context before editing. **(1 day old** — if a newer session ran since then and its narrative handoff was archived without a replacement being written, this may be stale; check `docs/archive/` for a newer one.)

This file is a mechanical snapshot (branch/git-status/skill-route/live state) —
regenerated fresh every `make handoff`. The narrative above (what happened,
what's next, the traps) lives in the dated doc it points to, not here.

## Current branch/worktree
docs/w0-open-work-board

## Live state (measured fresh by this run, not hand-carried)
Run `make handoff` again for current numbers instead of trusting this file
once it ages -- every value below is read from git/gh/`/status` at
generation time, per #134.

- **`origin/main` tip:** `e115d92ac070`
- **Last commit touching `src/`:** `8b2ffdac8e6b`
- **Production vs. last `src/` commit:** unavailable: could not reach https://quorum-ai.fly.dev/status (last src/ commit is 8b2ffda)
- **pytest collected (no execution):** 3816
- **e2e lane spec counts:** invariants: 18, ops: 2, degraded: 1
- **Open issues:** 7
- **Changed-lines coverage:** not computed here -- `make diff-cover` shares
  coverage data with every pytest-invoking target and races with them if run
  concurrently (AGENTS.md rule 15), so this file does not run it. Run
  `make quality && make diff-cover DIFF_BASE=origin/main` for a current number.
- **Remote branches not merged into `origin/main`:**
- None (every remote branch merges into `main`)

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
M Makefile
 M docs/00-factory-console.md
 M docs/analysis/R2-plan-review-findings.md
 M docs/session-handoff.md
 M scripts/factory_next.py
 M scripts/session_handoff.py
 M tests/unit/test_gates_carry_a_charter.py
?? docs/65-open-work.md
?? scripts/check_open_work.py
?? tests/unit/test_open_work_matches_reality.py
```

## Diff stat
```text
Makefile                                 | 13 ++++-
 docs/00-factory-console.md               | 97 +++-----------------------------
 docs/analysis/R2-plan-review-findings.md |  9 ++-
 docs/session-handoff.md                  | 39 +++++++++----
 scripts/factory_next.py                  |  7 +++
 scripts/session_handoff.py               | 22 +++++---
 tests/unit/test_gates_carry_a_charter.py |  1 +
 7 files changed, 79 insertions(+), 109 deletions(-)
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
- The narrative handoff linked above — what happened, what's next, the traps.
- `docs/65-open-work.md` — the open-work board: what is open, what blocks
  what, and the evidence for each row, checked against the tree by
  `scripts/check_open_work.py`. The "Current phase" line above is the factory
  router's view of the lifecycle, not a work status.
- `docs/analysis/R2-plan-review-findings.md` — the R2 planning round, historical.
  Its PHASE STATUS block claimed authority until 2026-08-28 and no longer does.
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
Read the narrative handoff linked at the top of this file first -- it has the
real "what happened, what's next" context this mechanical file cannot hold.
Read docs/65-open-work.md for what is open and what blocks what: the phase
line in this file is the router's view of the lifecycle, not a work status.
Do not redo completed work.
Use the recommended driver skill and reviewer skills from make skill-route.
Before editing, list the files you intend to modify.
```
