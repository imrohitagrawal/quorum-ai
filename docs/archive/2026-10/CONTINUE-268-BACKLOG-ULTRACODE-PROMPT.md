> **Archived 2026-10-11** (CHG-040 (c)). The process now lives in `.agents/skills/work-item-delivery/SKILL.md`; this file is history and is not to be run. Home-directory paths were replaced with `~`, and citations of files that moved or never existed were rewritten so they resolve.

# ULTRACODE — continue the backlog from the 2026-09-19 handoff

ultracode. You may use the Workflow tool for the read-only phases below.

## 0. Read first, in this order
1. `AGENTS.md`. It overrides everything here.
2. `docs/archive/2026-09/2026-09-19-session-handoff.md`. It is the live context and the work order (§2).
3. Run its §0 preconditions and halt on any surprise.
   `CONTINUE-105-BACKLOG-ULTRACODE-PROMPT.md` is stale; ignore it.

Run the commands, not the numbers. If a figure here or in the handoff disagrees with a command, the command wins. Say so out loud.

## 1. HARD STOPS: ask me every time
- Any paid API call or live run. `/status`, `/ready`, `/estimate` and the free OpenRouter docs and models endpoints are fine.
- Opening, closing, extending or re-affirming a live-execution window, or flipping `OPENROUTER_LIVE_EXECUTION_ENABLED` / `PEER_CRITIQUE_ENABLED`. Editing `configs/live-execution-windows.json` counts.
- Changing a shipped money value, including #268's debate estimate. Bring me the proposal; do not merge it.
- Any merge whose `EXPECT_CLOSE` is non-empty, i.e. closing an issue.
- Lowering a threshold, `# pragma: no cover`, or deleting a test to go green.
- Force-push, history rewrite, `git clean`, `git stash`. Anything touching secrets.
- Two fix rounds in a row that add a defect: stop, find the root cause, re-plan, tell me.

## 2. STANDING AUTHORITY: push, PR, merge and deploy without asking, only when ALL hold and you show the output of each
1. Required contexts re-derived (`gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'`), each SUCCESS on the PR head SHA.
2. `make diff-cover DIFF_BASE=origin/main` green on a committed tree, with its floor line read.
3. The e2e lanes' executed-count floors met in CI; raise a floor if you add tests.
4. Review complete: correctness, break-it and rule-11a prose lenses. Every finding reproduced by you and triaged. Zero open CRITICAL_BLOCKER or REQUIRED_CONTRACT.
5. Every behavioural change has a test proven by mutation (`cp` aside, mutate, run, restore, `diff -q`, clear `__pycache__`). Recorded in the commit body.
6. `make close-guard` passes with an explicit, empty `EXPECT_CLOSE`.
7. After merge: every Deploy run for the merge SHA read by its JOB, and `/status.build_sha` equals the merge SHA.

## 3. How to use workflows (ultracode)
- **Use a Workflow ONLY for read-only fan-out:**
  - Understand: re-derive the item's claims against the tree.
  - Review: the three lenses above, plus a whole-repo prose sweep.
- **Never for building.** One writer, in a dedicated `git worktree`.
- Keep each workflow under 10 agents.
- Tell every agent, IN CAPITALS, not to write, edit, `git checkout`, `git stash` or `sed -i`. Also: never read `.env`, and make no authenticated or paid call.
- Any agent that must run or mutate code works in its OWN copy, on its own path: `git clone --no-hardlinks` or `git archive HEAD` plus `mkdir .git`.
- Never move the tree under a running reader or gate (rule 9a).
- Before changing any shipped value or measured figure:
  - Sweep the whole repo, grepping the NUMBERS as well as the phrasings.
  - Fix every hit in one pass.
  - Keep a measured number in ONE place, with its window and command; everywhere else points to it.
- Cap review at two rounds, then stop and report.

## 4. The work, in order (details in the handoff's §2)
1. **#268:** sweep first → re-run the band sweep under production posture → bring me a proposed value with its evidence. Hard stop before changing it.
2. **#458 flag half:** the landing and `/status` say peer critique is in effect only when the flag AND live execution are both on. Code only, no flag flipped. I have approved this approach.
3. **W23**, then **#464**: make schemathesis cases selectable by the mutation gate. Correct the board row's cause, which is false. Do not exempt the tests.
4. **#459 option 2**, before any live window: production refuses live execution once the declared window lapses. Needs my approval and an ADR before building.

One concern per PR, merged and deployed before the next starts. If an item is bigger than it looked, stop and say so.

## 5. Report every time
Lead with the answer, in plain English. End each piece of work with `Done` / `Verified myself` / `Cleanup` / `Pending` / `Next action`. Say whether it is pushed, merged and running in production. Keep what you ran separate from what a subagent reported. Before ending, write a short narrative handoff that points at commands and PR bodies, then run `make handoff`.
