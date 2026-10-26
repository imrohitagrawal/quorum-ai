# Session prompt: security fixes, and the board rows W114, W113, W80, W75 and W76

Written by the session of 2026-10-19 to 2026-10-27 (transcript `bda9c799`). This file is
the session's wording. The owner's decisions are the CHG rows it names.

**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`. Read it first,
and follow it for roles, review rounds, gates, merging, production checks and cleanup.

## Read first

1. `docs/README.md`, then the newest `docs/analysis/2026-10-27-session-handoff*.md`.
2. `docs/65-open-work.md`: rows W114, W80, W75, W76, W45 and W112, and the Parked table
   (`make parked-check`). W113's row is on its branch, `w113/owner-quote-check`.
3. `docs/19-change-control-log.md`: CHG-049, CHG-060, CHG-061, CHG-063, CHG-083, CHG-085,
   CHG-086, CHG-089, and CHG-092 to CHG-094.
4. `git ls-remote origin 'refs/heads/*'` and `gh pr list --state open`.
5. The private evidence, outside the repository: `~/Projects/quorum-ai-evidence/` —
   `2026-10-24/w873-followup/` (W114: `50-stop-rule-root-cause-and-plan.md`, revision 3, and the
   bundle) and `2026-10-24/w873-policy/owner-answers.md`; `2026-10-26/w113/` (`STATE.md` first);
   `2026-10-18/w80/` (failure modes only; the W80 plan is not written yet).

## The items, in order

Each is its own pull request, deployed and checked live before the next starts. Route each
with `make skill-route ITEM=<row>`, and again with `make skill-route DIFF=origin/main` once the
change exists. The order follows the owner's answers in W114's Parked line (the next session
restarts W114 and ships pull request A, then builds B), CHG-094 for W113, and CHG-061 for the
rest; putting W114 before W113 is the session's reading of those answers.

1. **W114, pull request A: the core of the W87-3 follow-up.** Start a fresh branch from `main`
   and build from the plan's revision 3, with the one temporary limit the owner accepted. Take
   only what the plan keeps from branch `w87-3/unchecked-cookie` (local, `bc9dc49`). Record the
   owner's answers as CHG-088 in this pull request, and restore held-back detail hunk by hunk
   (CHG-060).
2. **W114, pull request B: the sign-out part.** Ask the owner first whether it may evict, with an
   example; then build it table-first, as the plan says.
3. **W113: rebuild the owner-quote check on a Markdown parser** (CHG-094: limit 2,900 changed
   lines; past it, stop and ask). Continue branch `w113/owner-quote-check` in worktree
   `quorum-ai-w113`, after merging `main` into it. Amend `r2/root-cause-and-plan.md` with
   `r2/codex-plan-review.md`, have Codex review the amended plan, then failing tests first.
   The owner's approval for W113 is CHG-090, on that branch, with CHG-094's new limit.
4. **W80**: remove `/feedback/audit` (CHG-063 (c)); stop a cross-site link cancelling a sign-in.
   Write and review the plan first.
5. **W75**, with the additions its row names.
6. **W76.** Its parts are agents' reports: reproduce each first. Sentry's FastAPI integration
   reads request bodies by default (`max_request_body_size` unset).

A new security warning that fails `make vuln-audit` follows CHG-092 and ADR-0181.

## Approvals

Sending this prompt approves the following for one pull request per item above (W114 is two
pull requests), any update pull request CHG-092 allows, and the end-of-session handoff (docs
only).
- Push and open the pull request.
- Squash-merge through `make close-guard`, with `EXPECT_CLOSE=""` (or the issues it closes).
- Deploy.

Each needs every required gate green and every reproduced blocker fixed. Nothing else is allowed:
- no paid call;
- no `fly secrets` change;
- no change to GitHub's repository settings;
- no attack on production, and no cookie-less request to production `/ui` or `/v1/session` (each
  spends one of the owner's network's two daily sessions);
- no W28 code;
- no work on rows outside the list above; a serious new gap goes on the board for the owner.

## End of session

1. Write the narrative handoff. Every "merged" or "in production" must cite its pull request.
2. Write the next session's prompt from `.agents/skills/work-item-delivery/prompt-template.md`.
3. In the handoff pull request, move this file into `docs/archive/YYYY-MM/` (run `ls` there first;
   add a date suffix if the name exists) and commit the next prompt at the root.
4. Run `make handoff` last. It prints the line for the owner to paste; end the closing status block
   with that line under "Next action".
