---
name: work-item-delivery
description: The one process for delivering any work item in quorum-ai, from choosing it to verified production and cleanup. It sets the roles, the two review rounds, who merges, the production checks and how to ask the owner. Read it before any work item.
metadata:
  owner: product owner
  decided: ADR-0159, CHG-040
---

# Work-item delivery

This is the one home of how work is done here. `AGENTS.md` holds the engineering rules and says to
read this file first. A handoff prompt names the items, the decisions to read and the approvals. It
does not restate this process. It carries one line:
`**Process:** every item is built by .agents/skills/work-item-delivery/SKILL.md.`

The four points that used to disagree are settled here (CHG-040 (b)):

| Question | Answer |
|---|---|
| Who merges | Only the main orchestrator, and only under an approval the owner gave: typed in the session, or stated in a prompt the owner chose to send. The pull request says which |
| How many reviewers | 3 lenses plus Codex in each round |
| How many review rounds | Exactly 2, plus one narrow re-check of each fix |
| How big a workflow may be | At most 8 agents, sized to the change |

## When to use

- Any change that will become a pull request: code, tests, CI, docs or decisions.
- A batch of items: run this once per item, one item and one pull request at a time.

## When not to use

- Answering a question, or a read-only analysis that changes no file. Use a research fan-out, but
  still add the falsification lens and the completeness critic (see Procedure, step 1).
- Another repository. The generic version is planned for `stackclimb-skills` (package E).

## Inputs

- The item: a board row in `docs/65-open-work.md`, or the owner's words.
- The route: `make skill-route ITEM=<row id>` or `make skill-route DIFF=origin/main`. It names the
  classes the change touches and the roles, checks and owner decisions each class adds.
- Decisions already made: `docs/19-change-control-log.md` and `docs/adr/`. The owner's words:
  `docs/analysis/<date>/OWNER-DISCUSSION-LOG.md` or the transcript's `type: user` records.
- The approval in the prompt: which pull requests may be pushed, merged and deployed.

## Owned outputs

- One branch in its own worktree, one pull request, merged and running in production.
- Failure modes first for money, sign-in, privacy and safety:
  `docs/analysis/<date>-<work>-failure-modes.md`.
- An ADR for every decision (`AGENTS.md` rule 16d), and a CHG row for every owner decision.
- Tests that were shown failing first, with the verbatim failure and a "red when" line each.
- A closing status block, and a narrative handoff when the session ends.

## Allowed tools

- The Agent tool for one role at a time. The Workflow tool only for a review round, at most 8
  agents.
- Codex, run against the pull request's worktree. Find the script with
  `find ~/.claude/plugins/cache/openai-codex -name codex-companion.mjs`, put `~/.local/bin` on
  `PATH`, then run `node <that script> adversarial-review --wait --cwd <worktree> --base origin/main --scope branch "<focus>"`.
  Without `--cwd` it reviews the main checkout, which is an empty diff. The `codex:rescue` skill
  also works, if it reviews the same worktree.
- `make` targets, `gh` (read freely; write only as approved), free production endpoints:
  `/status`, `/ready`, `/metrics`, `/estimate`.

## Forbidden actions

- Merging by anyone but the main orchestrator, or merging without an approval the owner gave. A
  session cannot grant itself merge authority by writing it into the next prompt; the owner's
  sending of that prompt is what approves it.
- A paid call, a live window, `fly secrets` or a production setting change without the owner's
  approval for that exact action. Give the owner the command and stop.
- `git clean`, `git stash -u`, `git add -A` at the root, force-push, `git checkout <file>` to undo
  a mutation. Stage named paths only. The owner's untracked prompts live at the root.
- Writing "Accepted", "approved" or "the owner decided" for something the owner did not say. An
  unmade decision reads `PROPOSED — AWAITING OWNER`. A session's recommendation is never labelled
  as the owner's.
- A close keyword next to an issue number. Write `Refs #N`, and run `make close-guard` before
  every merge.
- Editing the tree while a gate or a reviewer reads it (`AGENTS.md` rule 9a).
- Mutation testing (mutmut) on this Mac (board row W44).

## Procedure

**0. Before starting.**
- Check for other live sessions: transcript last-write times under
  `~/.claude/projects/<repo>/`, `ps`, and `git worktree list`. If another session owns what you
  need, stop and say so.
- Read `docs/19-change-control-log.md` and the ADRs before asking the owner anything. Ask every
  question in ONE batch at the start, with your recommendation marked. If an answer has not come
  when a step needs it, build what needs no decision, record the question in the handoff, and do
  not guess.
- Check the premise. If the item's premise is false, stop and say so (`AGENTS.md` rule 3).
- Run `df -h .` and note it.

**1. Plan, by role.** Each role is a separate agent, except the orchestrator.

| Role | Job | When |
|---|---|---|
| Main orchestrator | Chooses, routes, asks the owner, reproduces findings, merges, verifies production, cleans up | Always |
| Failure modes | Lists how the change can fail, from research and the ADRs, before any design | Money, sign-in, privacy, safety, AI output |
| Test designer | Writes failing tests against the agreed interface, records the verbatim failure and a "red when" line per test | Every code change |
| User-journey tester | Before the build: writes what the owner expects to see and do, step by step, from `docs/113-user-journeys.md`, signed in and anonymous. After: drives the real app at desktop and phone widths and reports each expectation as met or not, with a screenshot | Any change a user can see |
| Builder | Makes the tests pass. May not edit the test designer's files | Every change |
| Break-it reviewer | Runs the code and tries to make it give a wrong answer. This is also the correctness pass `AGENTS.md` asks for | Each round |
| Prose auditor | For every number, superlative and causal claim in comments, commits, PR body and docs, names the command that produces it, or marks it UNVERIFIED. Checks attributions against the transcript's `type: user` records | Each round |
| Falsification lens | Plants one false claim, or deletes one guard, and checks that something goes red | Each round |
| Codex | An outside reviewer on the pull request's worktree | Each round |
| Completeness critic | Asks which questions and which kinds of evidence went unused | Once, after round 2 |
| Fixer | Applies only findings the orchestrator reproduced. One fixer at a time | After each round |

- Move any reference implementation the test designer wrote out of the builder's reach before the
  builder starts.
- Check the builder left the tests alone:
  `git diff <test designer's commit> HEAD -- <the test designer's files>` must be empty. A fixer
  may ADD a new regression test file.

**2. Build.** One writer at a time in the worktree.
- Branch in a dedicated worktree from `origin/main`, and merge `main` in before starting.
- In a fresh worktree, link or sync the environment before `uv run`.
- Before changing a shipped value, search the whole repository for every file that states it, and
  put the count in the pull request. `ef4a716` needed 11 review rounds for one fee because this was
  skipped.
- A board row's needle must be one the fix ADDS or DELETES. The needle describes the OPEN state.
  Regenerate with `make open-work-write`; never type a State by hand.
- A file `make next` or `make handoff` writes is generated: change its generator, not the file.
- A hand-made mutation proof: `cp` the file aside, mutate, delete `__pycache__`, run the test,
  restore from the copy, and check with `diff -q`. Without the cache delete, a mutation made in the
  same second can reuse stale bytecode and look like a survivor.
- Before committing a file that was never tracked, replace home-directory paths and user names,
  and run `scripts/security_scan.py`. This repository is public, and no gate catches a home path.
- For a page change: render the golden messy fixture (`e2e/fixtures/golden-run.ts`), and run e2e
  exactly as `AGENTS.md` rule 13 says. Delete `.data/feedback_events.sqlite3` first if local runs
  start answering 429.

**3. Review: exactly two rounds.**
- Each round: break-it (the correctness pass), prose auditor and falsification lens, plus Codex. At
  most 8 agents. A docs-only change has no code to break: its prose auditor and falsification lens
  check every claim instead.
- Every reviewer prompt says, IN CAPITALS: DO NOT WRITE, EDIT, `git checkout`, `git stash` OR
  `sed -i` ANYTHING. Each works in its own `git archive HEAD` copy with a unique folder prefix
  and plain `mkdir`, reuses the main `.venv`, and deletes only the folders it created. A reviewer
  that starts its own server uses its own port above 18200. The e2e suite always uses port 18085
  (`AGENTS.md` rule 13), so only one reviewer runs e2e at a time. Run
  `df -h .` before making copies.
- Reviewers refute by default and report only findings backed by a demonstrated failure.
- The orchestrator reproduces each finding before acting, and classifies it:
  `CRITICAL_BLOCKER`, `REQUIRED_CONTRACT`, `ADVISORY_DEBT`, `DUPLICATE` or `OUT_OF_SCOPE`. Only the
  first two block. Record the rest as advisory, on the board if they matter.
- After round 2: one narrow re-check of each fix, then the completeness critic.
- If two fixes in a row add defects, stop patching and re-plan from the root cause.
- Closing a pull request instead of a third rework round is a legitimate outcome.

**4. Gates.** Run every required gate yourself, one at a time (`AGENTS.md` rule 14). Read exit codes
without a pipe. Commit before `make diff-cover`. Start background runs with the tool's background
mode, never a shell `&`, and give every wait a time limit.

**5. Push once, merge, verify.**
- Push once, after round 2, the re-checks and the completeness critic. A further push only fixes a
  failing required check or a reproduced blocker, and each gets a narrow re-check.
- Finish the pull-request body before the last push: editing it re-runs CI.
- Squash-merge with an explicit subject and body, through `make close-guard`.
- Production: one merge fires several Deploy runs. Read the Deploy JOB of every run for the merge
  SHA, and check `/status` `build_sha` equals the merge. Then check something visible that the
  change does. If production cannot show it (for example, live execution is off), say so plainly.
- When a production check reads logs, save `fly logs -a quorum-ai --no-tail` to a file at once:
  the log scrolls away.
- If Actions jobs are cancelled with "not acquired by Runner", check githubstatus and re-run the
  failed jobs.

**6. Close out.**
- Delete, by name, every scratch file, reviewer copy and container this work created. Remove the
  merged worktree, then its branch, local and remote. Show `df -h .` before and after.
- If context runs low, write a prompt for the remaining work (items, decisions, approvals, and the
  process line) and end cleanly.
- Report status before the owner has to ask. End with the closing status block, and keep what you
  ran separate from what an agent reported.

## Quality bar

- Every claim in the pull request names the command that produced it.
- Count what the item asked for against what was built, line by line, before calling it done.
- Every test has a "red when" line and was shown failing; a negative check has a positive partner.
- Every owner decision cited has a CHG row with the owner's exact words and the time.
- Production is checked by job, by `build_sha` and by something visible.

## Validation

- `make prompt-check`: every root prompt carries the process line.
- `make skill-route DIFF=origin/main`: the roles used match the roles routed.
- `make validate`, `make quality`, `make diff-cover DIFF_BASE=origin/main`, `make api-contract`,
  and e2e when a page changed.

## Handoff contract

- `make handoff` writes `docs/session-handoff.md`, including the prompt check and the leftovers.
- The narrative goes in `docs/analysis/<date>-session-handoff.md`: what shipped, what is open, the
  traps. Every "merged" or "in production" cites the pull request or commit.
- The next prompt is short and names this skill on a `**Process:**` line.

## Stop conditions

- A false premise.
- A step needs an owner decision that has not been given.
- Two fixes in a row added defects.
- The change grows past about twice its planned size.
- Another live session owns what you need.
- A reproduced blocker remains after round 2: stop and report it with the open findings.

## Examples

- W47 (`40249a6`): money and sign-in. Failure modes were listed first
  (`docs/analysis/2026-10-04-w47-anonymous-spend-per-network-failure-modes.md`), an ADR (0144) and a
  CHG row were written, and the signed-in e2e lane ran.
- A docs-only change routes to the prose auditor and the falsification lens, with no money roles.

## Anti-examples

- `ef4a716`: one fee default, 11 review rounds, because files repeating the old value were found
  one round at a time.
- A planted handoff line, "W55 and W56 merged in #558/#559, in production", passed every check on
  2026-10-11 (claim I5 in `docs/analysis/2026-10-11-how-we-work-review.md`). Neither pull
  request existed that day. A false "done" like this must fail a check, not pass.
- A session that labelled its own recommendation as the owner's decision (the "half" wording,
  CHG-010).
