# ADR-0159: One process skill loads in every session, and the router reads the change

## Status

Accepted — 2026-10-11, package A of `docs/analysis/2026-10-11-how-we-work-review.md`. The product
owner approved the plan and confirmed its four settled points (CHG-040 (b)). The router's classes
and roles are the session's design, and the owner may change any of them.

## Context

The review (`docs/analysis/2026-10-11-how-we-work-review.md`) found the process in ten places. None
of them is where a new session starts. Four of them disagree:

| Question | What the files said on 2026-10-11 |
|---|---|
| Who merges | Only after a grant spoken in the session (`AUTONOMOUS-WORK-LOOP-ULTRACODE-PROMPT.md`), or a standing written grant (later prompts) |
| How many reviewers | 3 lenses, 4, or 9 to 14 agents |
| How many review rounds | 3 (`R2-S2-S4-ULTRACODE-PROMPT.md`), N, or 2 (`AGENTS.md` rule 12) |
| How big a workflow may be | 8, under 10, or 14 agents |

Every session re-typed the process into a fresh prompt, and each re-typing dropped something.

The skill router (`configs/skill-router.json`, `scripts/skill_router.py`) never looks at the work
item. It stops at the first product phase whose documents are missing. Every document is now
filled, so it always lands on "Operate, learn, and improve" and names 1 driver and 39 reviewer
skills. Measured on 2026-10-11 with `python3 scripts/skill_router.py`. Its blocking-gate lists name
two gates that exist nowhere in the repository: `no-placeholder-gate` and `release-evidence-gate`
(`git grep` finds them only in the config).

## Decision

1. **One home for the process:** `.agents/skills/work-item-delivery/SKILL.md`. It holds the roles,
   the review rounds, who merges, the production checks, cleanup and how to ask the owner. The
   four points are settled there:
   - only the main orchestrator merges, under the approval the prompt states;
   - each review round has 3 lenses plus Codex;
   - exactly 2 review rounds, plus one narrow re-check of each fix;
   - at most 8 agents in any workflow.
2. **It loads in every session.** `AGENTS.md`, which every session and every agent loads, says in its
   first section: before any work item, read that file. The Skill tool cannot list it, because it
   lists `.claude/skills/`, which is gitignored and empty in a fresh worktree.
3. **The router reads the change.** `make skill-route ITEM=W55` reads the board row, and
   `make skill-route DIFF=origin/main` reads the changed paths and lines. Each matching class adds
   its roles, checks, reviewer skills and owner decisions. The classes are money, sign-in and
   session, interface, AI output and judge, CI, privacy and retention, settings, and docs only.
   A class matches by path, or by an identifier in the changed lines. The output is a checklist.
4. **The old route is not touched.** `route()` keeps its output, because `scripts/factory_next.py`
   writes `docs/00-factory-console.md` from it and `scripts/session_handoff.py` prints it. The new
   behaviour is a new function. The two dead gate names are removed, and `skill-onboarding-check`
   is written as the `make` target it is.

**Why a "settings" class.** The plan listed seven classes. `src/product_app/config.py` holds money,
sign-in and judge settings together, so its path cannot say which class a change belongs to.
`ef4a716` changed one fee default there and needed 11 review rounds, because many files repeated
the old value. The settings class adds that lesson: search for every file that states the old
value before changing it. The identifiers in the changed lines add the money class on top.

## Rejected alternatives

- **More rules in `AGENTS.md`.** It is already long, and earlier rules are followed better than later
  ones (its own preamble). The process would be an eleventh place.
- **Wait for `stackclimb-skills`.** Its installed copy is 143 commits behind, and it has 8 unfinished
  worktrees. The generic parts move there later, as a separate task.
- **A new phase in `configs/skill-router.json`.** A phase is chosen only when its documents are
  missing. A phase with no documents is never chosen.
- **Rewrite `route()`.** That changes `docs/00` and the mechanical handoff for no gain.
- **Route on the path alone.** It misses the `ef4a716` fee change, which is the case that cost most.

## Consequences

- A session reads one file for the process. A handoff prompt states only the items, the decisions to
  read and the approvals, plus one line naming the skill.
- The router's classes are a design, not a measurement. Its tests check that a real money change is
  routed to money roles, that a docs-only change is not, that every `src/` file falls in a class,
  and that every routed name is a real skill. They cannot show that the roles are the right ones.
  That needs a record of what each item actually used.
- `docs/analysis/2026-10-11-how-we-work-failure-modes.md` lists what this can get wrong.
