# Session prompt: AREA, and the board rows ROWS

<!--
How to use this template (ADR-0169):
- Copy this file to the repository root as CONTINUE-AREA-ROWS-PROMPT.md, in capitals, digits
  and dashes, with at least one board row: for example CONTINUE-SECURITY-W82-W71-W81-PROMPT.md.
- Keep the four level-2 headings below exactly as written. `make prompt-check` refuses a root prompt
  without them, without the Process line, or with another name.
- Name the items, the decisions to read and the approvals. Do not restate the process: it lives in
  the skill the Process line names. Scope belongs on the board (docs/65-open-work.md), not here.
- Commit the prompt in the handoff pull request, so CI checks it too.
- Words such as merged, approved or in production need a cited pull request, commit or CHG row
  in the same paragraph, or `make validate` refuses the committed prompt (ADR-0162).
- Delete this comment block when you fill the template in.
-->

Written by the session of DATE (transcript `SESSION-ID-8`). This file is
the session's wording. The owner's decisions are the CHG rows it names.

**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`. Read it first,
and follow it for roles, review rounds, gates, merging, production checks and cleanup.

## Read first

1. `docs/README.md`, then the newest `docs/analysis/DATE-session-handoff*.md`.
2. `docs/65-open-work.md`: the rows named below, and the Parked table (`make parked-check`).
3. `docs/19-change-control-log.md`: the CHG rows this work rests on.
4. `git ls-remote origin 'refs/heads/*'` and `gh pr list --state open`.

## The items, in order

Each is its own pull request, deployed and checked live before the next starts. Route each
with `make skill-route ITEM=ROW`.

1. **ROW: what, in one line.** Only what is not already on the board row or in a named file.
2. ...

## Approvals

Sending this prompt approves the following for N pull requests: the items, and the
end-of-session handoff (docs only).
- Push and open the pull request.
- Squash-merge through `make close-guard`, with `EXPECT_CLOSE=""` (or the issues it closes).
- Deploy.

Each needs every required gate green and every reproduced blocker fixed. Nothing else is allowed:
- no paid call;
- no `fly secrets` change;
- no change to GitHub's repository settings;
- no attack on production;
- anything else this session must not do.

## End of session

1. Write the narrative handoff. Every "merged" or "in production" must cite its pull request.
2. Write the next session's prompt from `.agents/skills/work-item-delivery/prompt-template.md`.
3. In the handoff pull request, move this file into `docs/archive/YYYY-MM/` (run `ls` there first;
   add a date suffix if the name exists) and commit the next prompt at the root.
4. Run `make handoff` last. It prints the line for the owner to paste; end the closing status block
   with that line under "Next action".
