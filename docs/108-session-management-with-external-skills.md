# Session Management With External Skills

Session management should reuse proven external patterns, not reinvent them blindly.

## Recommended pattern

| Need | External pattern to consider | Local factory control |
|---|---|---|
| Break work into a plan | Superpowers `writing-plans`, Addy `planning-and-task-breakdown` | `implementation-planning`, `docs/60-implementation-plan.md` |
| Execute plan safely | Superpowers `executing-plans`, TDD, verification | `vertical-slice-builder`, `test-architecture`, `make validate` |
| Parallel work | Superpowers `using-git-worktrees`, `dispatching-parallel-agents` | one worktree per workstream, no shared file ownership |
| End session | Superpowers branch finishing/handoff-style skills | `session-continuity-manager`, `docs/session-handoff.md` |
| Continue session | context-engineering / repo onboarding skills | read `AGENTS.md`, `docs/00-factory-console.md`, `docs/session-handoff.md` |
| Review before completion | verification-before-completion, code review skills | local blocking gates and release evidence |

## Mandatory handoff rule

Before closing or switching a session, run:

```bash
make next
make skill-route
make handoff
```

Then commit or clearly record uncommitted changes.

## Parallel terminal rule

Use separate git worktrees and branches. Each session must declare:

- workstream;
- files it owns;
- files it must not touch;
- next driver skill;
- reviewer skills;
- validation commands.

## What not to do

- Do not depend on chat history alone.
- Do not let two agents edit the same artifact family.
- Do not let an external session-management skill bypass local validation or source-of-truth updates.
