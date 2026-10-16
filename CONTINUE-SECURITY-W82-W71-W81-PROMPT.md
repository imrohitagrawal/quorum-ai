# Session prompt: security, and the board rows W82, W71 to W81

Written by the session of 2026-10-16 (transcript `6a12f59d`). This file is
the session's wording. The owner's decisions are the CHG rows it names.

**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`. Read it first,
and follow it for roles, review rounds, gates, merging, production checks and cleanup.

## Read first

1. `docs/README.md`, then the newest `docs/analysis/2026-10-16-session-handoff*.md`.
2. `docs/65-open-work.md`: rows W82, W71 to W81, W83 and W84, and the Parked table
   (`make parked-check`).
3. `docs/19-change-control-log.md`: CHG-042, CHG-046, CHG-049, CHG-050 and CHG-051.
4. `docs/analysis/2026-10-13-security-review.md`, the findings the rows cite.
5. `git ls-remote origin 'refs/heads/*'` and `gh pr list --state open`.

## The items, in order

Each is its own pull request, deployed and checked live before the next starts. Route each
with `make skill-route ITEM=<row>`.

1. **W82: the security baseline, first (the owner's direction, CHG-051).** As the board row says,
   the rest is the session's proposal, not the owner's decision: its output is the ranking of W71
   to W81 and any new rows it adds, and Codex reviews that ranking before any code (CHG-049).
   New rows W82 adds are not approved by this prompt: put them on the board, ranked, and leave
   them for a later prompt.
2. **W71 to W81, in the order W82 ranks them.** W74 and W78 are parked on the owner (the Parked
   table): ask the owner once W82 has ranked them. This prompt does not approve W74's spend.
3. **W83 and W84**, the secret-scan rows W70 moved out (#567), if the session has room after
   W71 to W81.

The session that finishes W71 to W81 writes the W28 prompt, for a fresh session (CHG-051), from
`.agents/skills/work-item-delivery/prompt-template.md`. W28's six decisions stay the owner's; the
research is `docs/analysis/2026-10-16-w28-decision-research.md`.

## Approvals

Sending this prompt approves the following for one pull request per item above, and the
end-of-session handoff (docs only).
- Push and open the pull request.
- Squash-merge through `make close-guard`, with `EXPECT_CLOSE=""` (or the issues it closes).
- Deploy.

Each needs every required gate green and every reproduced blocker fixed. Nothing else is allowed:
- no paid call (so W74's attack suite does not run without the owner's approval of its spend);
- no `fly secrets` change;
- no change to GitHub's repository settings;
- no attack on production;
- no W28 decision recorded and no W28 code;
- no W78 decision taken by the session.

## End of session

1. Write the narrative handoff. Every "merged" or "in production" must cite its pull request.
2. Write the next session's prompt from `.agents/skills/work-item-delivery/prompt-template.md`.
3. In the handoff pull request, move this file into `docs/archive/YYYY-MM/` (run `ls` there first;
   add a date suffix if the name exists) and commit the next prompt at the root.
4. Run `make handoff` last. It prints the line for the owner to paste; end the closing status block
   with that line under "Next action".
