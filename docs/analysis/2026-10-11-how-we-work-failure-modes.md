# How we work, package A: failure modes listed before building (2026-10-11)

Written before any code, as `AGENTS.md` rule 16e asks. Package A adds three things: a process
skill, a router that reads the change, and a check on root prompt files. The plan is
`docs/analysis/2026-10-11-how-we-work-review.md`, section "The plan". Each failure below names the
defence and the test that must first be shown failing.

## The router (`make skill-route ITEM=…` and `DIFF=…`)

| # | Failure | Example | Defence | Test |
|---|---|---|---|---|
| R1 | **Under-routing.** A money change gets no money roles. | `ef4a716` changed one fee default in `src/product_app/config.py`, a file that also holds sign-in and judge settings. Its path alone does not say "money". | A class matches by path **or** by an identifier in the changed lines. Any path whose name says cost, spend, fee, price or quota is money. | A list of literal paths from `ef4a716` and `40249a6` must route the failure-modes role. |
| R2 | **Over-routing.** Every change gets every role, which is the router we have today (one driver and 39 reviewers for every item). | A docs-only change is told to list money failure modes. | Classes add roles only when they match. Docs only is its own class. | A docs-only diff gets no money role, no money skill and no money check. |
| R3 | **A `src/` module in no class.** A new module is added, and nothing routes it. | A new `src/product_app/<name>.py`. | Classes cover `src/` by path. An unclassified path is printed by name. | Every file `git ls-files src` lists falls in a class, counted against the tree, not the config. |
| R4 | **A routed name that is not a skill.** A skill is renamed or deleted, and the router keeps naming it. | `no-placeholder-gate` and `release-evidence-gate` name nothing anywhere in the repo today. | Remove the dead names. A blocking gate is either a skill or a `make` target. | Every routed name has `.agents/skills/<name>/SKILL.md`. Every blocking-gate name is a skill or a `make` target the `Makefile` defines. |
| R5 | **The old route changes.** `scripts/session_handoff.py` and `scripts/factory_next.py` (which writes `docs/00`) call `route()`. `scripts/validate_publishing_backbone.py` reads the phases. | A refactor of `route()` changes `docs/00-factory-console.md`. | A new function. `route()` is not edited. | `make next`, `make skill-route` and `make handoff` are run before and after, and their output is compared. |
| R6 | **A typo routes nothing.** `ITEM=W5S` matches no board row, and the output is an empty checklist that looks like "nothing needed". | Any typo. | An unknown item, or a diff with no changed paths, exits 1 with a message. | A test for each. |
| R7 | **A diff that misses files.** A diff taken only from commits misses uncommitted and untracked files. | A builder's new, not-yet-added module. | Read the committed diff from the merge base, the uncommitted diff, and the untracked files. | One test with an untracked file in a temporary repository. |

## The root prompt check (`make prompt-check`)

| # | Failure | Defence | Test |
|---|---|---|---|
| P1 | **The skill is named only in passing,** for example "do not use work-item-delivery", or inside a code block. A substring check passes (`AGENTS.md` rule 8). | Require one line of a fixed form, outside code blocks: `**Process:** … .agents/skills/work-item-delivery/SKILL.md`. | A prompt that names the path only in prose, or only in a fenced block, is refused. |
| P2 | **Untracked prompts are missed.** `git ls-files` sees only tracked files, and most prompts at the root are untracked. | Read the root directory itself. | An untracked prompt in a temporary root is refused. |
| P3 | **The name pattern is too narrow.** `*-ULTRACODE-PROMPT.md` misses `CONTINUE-W55-W56-PROMPT.md`. | Match any root `.md` whose name contains `PROMPT`, in any case. | A file named `x-prompt.md` is checked. |
| P4 | **An exemption outlives its file.** | An exempt name that no longer exists fails the check. | A test. |
| P5 | **The check passes over nothing.** A broken glob finds no file and reports success. | Report how many files were checked and how many were exempt. Finding no prompt file at all is an error, because `R2-S2-S4-ULTRACODE-PROMPT.md` is pinned at the root. | A temporary root with no prompt file exits 1. |
| P6 | **The handoff stops working offline,** against ADR-0045. | The check is its own target and fails on its own. `make handoff` prints its result as one value and still writes the file. | A failing prompt check leaves `make handoff` writing the file, with the failure shown. |

## The skill

| # | Failure | Defence | Test |
|---|---|---|---|
| S1 | **Nothing loads it.** The Skill tool lists `.claude/skills/`, which is gitignored and empty in a fresh worktree. | `AGENTS.md` names the file in its first section, which loads into every session and every agent. | The `AGENTS.md` line exists, and the file it names exists. |
| S2 | **It names a path that does not exist.** | `tests/unit/test_cited_paths_resolve.py` already reads `.agents/skills/`. | The existing gate. |
| S3 | **It drops a required section** that `make validate` expects of every skill. | `scripts/validate_quality_contracts.py` checks the 13 sections. | The existing gate. |
| S4 | **It contradicts `AGENTS.md`** on rounds, reviewers, merges or workflow size, so the old contradictions return. | The four points are stated once, in the skill. `AGENTS.md` points to the skill and does not restate them. | The prose review in round 1. |
