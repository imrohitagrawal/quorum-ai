# Session prompt: finish the W28 key-storage research pull request, and the board row W28

Written by the session of 2026-10-17 (transcript `8267786b`). This file is
the session's wording. The owner's decisions are the CHG rows it names.

**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`. Read it first,
and follow it for roles, review rounds, gates, merging, production checks and cleanup.

## Read first

1. `docs/README.md`, then the newest `docs/analysis/<date>-session-handoff*.md`.
2. **Why this session exists.** The session of 2026-10-17 ran `CONTINUE-BYOK-RESEARCH-W28-PROMPT.md`
   (still at the root, tracked on `main`). Its work sits on the branch `w28/key-storage-research`,
   **local only, never pushed**, in the worktree `~/Projects/quorum-ai-wt-w28r` (head `afc383c`). In
   review the stop rule fired (CHG-049): three prose items failed two fixes in a row. The owner chose to
   stop and finish in a fresh session (CHG-081, on the branch). The root cause and the fixed list of remaining changes are in
   `~/Projects/quorum-ai-evidence/2026-10-17/w28-research/50-stop-rule-root-cause-and-plan.md`, which
   Codex reviewed (its answer is recorded at the end of the session record named in point 4). Read that
   plan before anything else; do only what it lists.
3. `docs/19-change-control-log.md` on the branch: CHG-075 to CHG-081, the owner's W28 decisions of
   2026-10-17, which every review round confirmed against the transcript; and on `main`: CHG-047,
   CHG-049, CHG-059, CHG-061, CHG-062.
4. The session record: `~/Projects/quorum-ai-evidence/2026-10-17/w28-research/60-session-handoff.md`.
   The evidence it names (research reports `r1-fly.md` to `r6-repo.md`, review reports, the PR body
   draft `30-pr-body-draft.md`) is in the same folder, outside the repository and untracked: the
   owner's to back up. Agents' reports are leads: check each claim before using it.
5. `git ls-remote origin 'refs/heads/*'` and `gh pr list --state open`. Another session builds the
   security rows (from `CONTINUE-SECURITY-W85-W76-PROMPT.md`); it merged W85 (#575) after this branch
   was cut. Start a new branch from `origin/main` and carry the old branch over, as the plan's
   "Rollback" section says; merge `main` again before pushing. Touch
   neither `docs/41-security-controls.md` nor board rows W71 to W101. Take any new CHG number from
   CHG-082 and any new ADR number from ADR-0181. Check production by ancestry: `/status` `build_sha`
   must contain your merge (`git merge-base --is-ancestor <your merge> <build_sha>` exits 0).

## The items, in order

Route with `make skill-route ITEM=W28` and `make skill-route DIFF=origin/main`. Docs only.

1. **Finish the W28 research pull request** on a new branch from `origin/main`, carrying over
   `w28/key-storage-research` as the plan's "Rollback" section says: items 0 to 23 of the plan,
   each replacement checked against its source with a command before it is written; then one narrow
   re-check of every item; if any fix fails again, stop for good and report (no third attempt). Then
   every required gate, one at a time; push; open the pull request with the body the plan's item 21
   describes; merge; check production. Delete the old local branch and its worktree once nothing on
   them is lost. Then, once that pull request's deploy is checked live, close draft
   #525 and delete the branch `w28/byok-pr1-plan` (CHG-047: its one file is archived on the branch as
   `docs/archive/2026-10/2026-09-29-byok-pr1-plan.md`), and in the handoff pull request repoint W28's
   Parked line from #525 to the archived file. No W28 code (CHG-061).
2. **Give the owner, in chat, as plain text with no tool call in the same message:** the session's two
   views recorded in CHG-080 (plan item 3), the two trial steps (plan item 22) and the measured deploy
   circle with its question. Record the owner's answer as a CHG row.

## Approvals

Sending this prompt approves the following for the W28 research pull request and the end-of-session
handoff (docs only).
- Push and open the pull request.
- Squash-merge through `make close-guard`, with `EXPECT_CLOSE=""`.
- Deploy.
- Close draft #525 and delete the branch `w28/byok-pr1-plan`, only once CHG-047's conditions hold.

Each needs every required gate green and every reproduced blocker fixed. Nothing else is allowed:
- no paid call;
- no `fly secrets` change;
- no change to GitHub's repository settings;
- no attack on production;
- no W28 code, and no change to an OpenRouter, Fly or Google account (the trials are the owner's).

## End of session

1. Write the narrative handoff. Every "merged" or "in production" must cite its pull request. Carry
   into it what the session record of 2026-10-17 says.
2. Write the next session's prompt from `.agents/skills/work-item-delivery/prompt-template.md`: for
   W28's build, that is `CONTINUE-BYOK-BUILD-W28-PROMPT.md`, already on the branch.
3. In the handoff pull request, move this file and `CONTINUE-BYOK-RESEARCH-W28-PROMPT.md` into
   `docs/archive/YYYY-MM/` (run `ls` there first; add a date suffix if a name exists) and keep the
   next prompt at the root.
4. Run `make handoff` last. It prints the line for the owner to paste; end the closing status block
   with that line under "Next action".
