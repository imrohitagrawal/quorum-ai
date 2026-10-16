# Session Handoff

## Date/time
2026-10-16T07:13:08+05:30

## Open work
`docs/65-open-work.md` — the source of truth for what is open, what blocks what,
and the evidence for each row. Checked against the tree by
`scripts/check_open_work.py --check` inside `make validate`. The "Current phase"
line further down this file is the factory router's view of the lifecycle, not a
work status.

## Latest narrative handoff
`docs/analysis/2026-10-14-session-handoff-2.md` — read this for full context before editing. **(2 days old** — if a newer session ran since then and its narrative handoff was archived without a replacement being written, this may be stale; check `docs/archive/` for a newer one.)

This file is a mechanical snapshot (branch/git-status/skill-route/live state) —
regenerated fresh every `make handoff`. The narrative above (what happened,
what's next, the traps) lives in the dated doc it points to, not here.

## Current branch/worktree
w70/secret-scan

## Live state (measured fresh by this run, not hand-carried)
Run `make handoff` again for current numbers instead of trusting this file
once it ages -- every value below is read from git/gh/`/status` at
generation time, per #134.

- **`origin/main` tip:** `467ae9f0a079`
- **Last commit touching `src/`:** `ad959d2c1341`
- **Production vs. last `src/` commit:** production build_sha 467ae9f is in sync: it is `origin/main`'s tip, which holds the last src/ commit ad959d2
- **pytest collected (no execution):** 7198
- **e2e lane spec counts:** invariants: 26, ops: 2, degraded: 1
- **Open issues:** 2
- **Changed-lines coverage:** not computed here -- `make diff-cover` shares
  coverage data with every pytest-invoking target and races with them if run
  concurrently (AGENTS.md rule 15), so this file does not run it. Run
  `make quality && make diff-cover DIFF_BASE=origin/main` for a current number.
- **Remote branches not merged into `origin/main`:**
- `w28/byok-pr1-plan`
- `w70/secret-scan`

## Product readiness
`docs/product-readiness.md`, regenerated from production's `/status` and `/ready` by this run (`make readiness`):
product readiness: verdict Not ready, written to docs/product-readiness.md

## Board and GitHub
From `make board-github-check`: DONE rows whose issue is still open, and open issues no row cites.
board vs GitHub: 81 board rows, 2 open issues
  the board and GitHub agree

## Root prompt check
`PASSED` (checked 0, exempt 1; `make prompt-check`)
Prompt write hook: not installed in `.claude/settings.json`; run `.venv/bin/python scripts/prompt_write_hook.py --install .`

## Parked work and branches
From `make parked-check`:
```text
Parked work check: 3 remote branches, 2 open pull requests, 4 Parked lines, 0 branches with no open pull request, 0 Parked items due
Remote branches with no open pull request (merge, park or delete each):
  - none
Parked items whose resume-when has come (resume, re-park or close each):
  - none
Problems:
  - draft pull request #567 (w70/secret-scan) has no line in the ## Parked table
FAILED
```

## Next session
There is no root prompt named `CONTINUE-<AREA>-<ROWS>-PROMPT.md` that passes `make prompt-check`, so there is no line to paste. Write one by copying `.agents/skills/work-item-delivery/prompt-template.md`.

## Leftovers
From `make session-clean`, which reports and never deletes.
```text
Poisoned local state:
- `.data/feedback_events.sqlite3` — poisoned local state -- a stale mint cap makes the UI answer 429 and ~12 specs fail. The same events table also holds locally seeded audit and spend-rail events; production keeps its own database elsewhere

Feature branches and worktrees:
- `worktree ~/Projects/quorum-ai-wt-byok` — remove with 'git worktree remove' once its branch is merged
- `worktree ~/Projects/quorum-ai-wt-w70` — remove with 'git worktree remove' once its branch is merged
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
M  .agents/skills/work-item-delivery/SKILL.md
A  .agents/skills/work-item-delivery/prompt-template.md
M  .github/workflows/deploy.yml
M  AGENTS.md
M  Makefile
M  docs/110-command-reference.md
UU docs/19-change-control-log.md
UU docs/24-adr-index.md
UU docs/65-open-work.md
M  docs/README.md
M  docs/adr/0120-a-panel-is-two-to-four-models-and-a-panel-of-two-is-described-honestly.md
M  docs/adr/0121-a-user-key-changes-who-chooses-the-flags-and-who-sets-the-rails.md
M  docs/adr/0125-the-bound-prices-web-search-context-from-its-own-figure.md
M  docs/adr/0166-ci-actions-are-pinned-to-commits-and-audited.md
A  docs/adr/0168-parked-work-carries-a-reason-an-owner-and-a-resume-when.md
A  docs/adr/0169-the-next-session-prompt-is-a-checked-template.md
M  docs/analysis/2026-09-22-session-handoff.md
M  docs/analysis/2026-09-23-session-handoff.md
M  docs/analysis/2026-09-24-session-handoff.md
A  docs/analysis/2026-10-14-session-handoff-2.md
A  docs/analysis/2026-10-16-w28-decision-research.md
A  docs/archive/2026-10/2026-09-24-rejected-fix-e2e-visual-wait-for-fonts.md
A  docs/archive/2026-10/2026-09-29-w29-judge-wiring-plan.md
A  docs/archive/2026-10/CONTINUE-SECURITY-W69-W70-PROMPT.md
A  docs/archive/2026-10/adr-0119-the-web-search-context-constant-is-measured-low-and-raising-it-blocks-mixes.md
M  docs/product-readiness.md
UU docs/session-handoff.md
A  scripts/check_parked_work.py
M  scripts/check_root_prompts.py
M  scripts/deploy_gate.py
A  scripts/prompt_write_hook.py
A  scripts/proofs/search_context_band_sweep.py
M  scripts/session_handoff.py
M  src/product_app/costs.py
M  tests/unit/test_bound_search_context_is_decoupled.py
A  tests/unit/test_check_parked_work.py
A  tests/unit/test_deploy_job_uses_production_environment.py
M  tests/unit/test_how_we_work_review_round_1.py
M  tests/unit/test_how_we_work_review_round_2.py
A  tests/unit/test_item1_recheck_regressions.py
A  tests/unit/test_item1_round1_regressions.py
A  tests/unit/test_item1_round2_regressions.py
A  tests/unit/test_parked_table_survives_the_board.py
A  tests/unit/test_prompt_template_passes_the_check.py
A  tests/unit/test_prompt_write_hook.py
M  tests/unit/test_root_prompt_check.py
A  tests/unit/test_root_prompt_shape.py
A  tests/unit/test_search_context_band_sweep_refuses_an_unpriced_judge.py
A  tests/unit/test_session_handoff_parked_and_paste_line.py
M  tests/unit/test_session_handoff_prompt_and_leftovers.py
M  tests/unit/test_w69_manual_deploy_main_only.py
```

## Diff stat
```text
docs/19-change-control-log.md | Unmerged
 docs/19-change-control-log.md |  9 ++++++++-
 docs/24-adr-index.md          | Unmerged
 docs/24-adr-index.md          |  2 ++
 docs/65-open-work.md          | Unmerged
 docs/65-open-work.md          | 22 ++++++++++++++++++++--
 docs/session-handoff.md       | Unmerged
 docs/session-handoff.md       | 23 +++++++++++++----------
 4 files changed, 43 insertions(+), 13 deletions(-)
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
