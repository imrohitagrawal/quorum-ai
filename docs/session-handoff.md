# Session Handoff

## Date/time
2026-11-13T20:14:41-06:00

## Open work
`docs/65-open-work.md` — the source of truth for what is open, what blocks what,
and the evidence for each row. Checked against the tree by
`scripts/check_open_work.py --check` inside `make validate`. The "Current phase"
line further down this file is the factory router's view of the lifecycle, not a
work status.

## Latest narrative handoff
`docs/analysis/2026-11-13-session-handoff.md` — read this for full context before editing. (today)

This file is a mechanical snapshot (branch/git-status/skill-route/live state) —
regenerated fresh every `make handoff`. The narrative above (what happened,
what's next, the traps) lives in the dated doc it points to, not here.

## Current branch/worktree
docs/handoff-2026-11-13

## Live state (measured fresh by this run, not hand-carried)
Run `make handoff` again for current numbers instead of trusting this file
once it ages -- every value below is read from git/gh/`/status` at
generation time, per #134.

- **`origin/main` tip:** `e2cf4ad361bc`
- **Last commit touching `src/`:** `29135116ef71`
- **Production vs. last `src/` commit:** production build_sha e2cf4ad is in sync: it is `origin/main`'s tip, which holds the last src/ commit 2913511
- **pytest collected (no execution):** 8474
- **e2e lane spec counts:** invariants: 28, ops: 2, degraded: 1
- **Open issues:** 2
- **Changed-lines coverage:** not computed here -- `make diff-cover` shares
  coverage data with every pytest-invoking target and races with them if run
  concurrently (AGENTS.md rule 15), so this file does not run it. Run
  `make quality && make diff-cover DIFF_BASE=origin/main` for a current number.
- **Remote branches not merged into `origin/main`:**
- `dependabot/github_actions/actions/checkout-7.0.1`
- `dependabot/github_actions/actions/setup-node-7.1.0`
- `dependabot/github_actions/actions/setup-python-7.1.0`
- `dependabot/github_actions/actions/upload-artifact-7.0.2`
- `dependabot/github_actions/astral-sh/setup-uv-10.3.2`
- `dependabot/npm_and_yarn/e2e/e2e-7d5c8b5c19`
- `dependabot/uv/python-88b4e5b089`
- `dependabot/uv/python-f4752791c6`
- `dependabot/uv/sentry-sdk-fastapi--gte-2.73.0-and-lt-3.0`
- `dependabot/uv/uvicorn-standard--gte-0.54.0-and-lt-1.0`

## Product readiness
`docs/product-readiness.md`, regenerated from production's `/status` and `/ready` by this run (`make readiness`):
product readiness: verdict Not ready, written to docs/product-readiness.md

## Board and GitHub
From `make board-github-check`: DONE rows whose issue is still open, and open issues no row cites.
board vs GitHub: 143 board rows, 2 open issues
  the board and GitHub agree

## Root prompt check
`PASSED` (checked 1, exempt 1; `make prompt-check`)
Prompt write hook: not installed in `.claude/settings.json`; run `.venv/bin/python scripts/prompt_write_hook.py --install .`

## Parked work and branches
From `make parked-check`:
```text
Parked work check: 7 remote branches, 2 open pull requests, 6 Parked lines, 4 branches with no open pull request, 0 Parked items due
Remote branches with no open pull request (merge, park or delete each):
  - dependabot/github_actions/actions/upload-artifact-7.0.2
  - dependabot/github_actions/astral-sh/setup-uv-10.3.2
  - dependabot/uv/sentry-sdk-fastapi--gte-2.73.0-and-lt-3.0
  - dependabot/uv/uvicorn-standard--gte-0.54.0-and-lt-1.0
Parked items whose resume-when has come (resume, re-park or close each):
  - none
PASSED
```

## Next session
Paste this line to start the next session:
```text
Read CONTINUE-DEPS-REST-W136-W141-W117-PROMPT.md in the repo root and follow it exactly.
```

## Leftovers
From `make session-clean`, which reports and never deletes.
```text
Feature branches and worktrees:
- `worktree ~/Projects/quorum-ai-handoff` — remove with 'git worktree remove' once its branch is merged

Containers and images:
- `image quorum-ai:local` — built by this repo. Remove by name: docker image rm quorum-ai:local
```

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
clean
```

## Diff stat
```text
no unstaged diff
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
