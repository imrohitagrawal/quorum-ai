# Session prompt: security fixes, and the board rows W87, W88, W80, W75 and W76

Written by the session of 2026-10-17 to 2026-10-19 (transcript `b12e5f2a`). This file is
the session's wording. The owner's decisions are the CHG rows it names.

**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`. Read it first,
and follow it for roles, review rounds, gates, merging, production checks and cleanup.

## Read first

1. `docs/README.md`, then the newest `docs/analysis/2026-10-19-session-handoff*.md`.
2. `docs/65-open-work.md`: rows W87, W88, W80, W75, W76, W102 to W106, and the Parked table
   (`make parked-check`).
3. `docs/19-change-control-log.md`: CHG-049, CHG-056 (c), (d), CHG-060, CHG-061, CHG-063 to
   CHG-072.
4. `git ls-remote origin 'refs/heads/*'` and `gh pr list --state open`.
5. The private evidence, outside the repository (CHG-060 holds W87's remaining parts and W88 back
   until they ship): `~/Projects/quorum-ai-evidence/2026-10-18/` — `w87/` (the three-part plan
   `w87-plan-v2.md` with Codex's reviews, the failure modes, and the drafted CHG rows), `w88/`
   (`w88-plan.md`, reviewed by Codex, its failure modes and Codex's review), `w80/` (failure modes
   only; the W80 plan is NOT written or reviewed yet). Restore held-back detail hunk by hunk when
   each part ships; never copy a file back whole.

## The items, in order

Each is its own pull request, deployed and checked live before the next starts. Route each
with `make skill-route ITEM=<row>`, and again with `make skill-route DIFF=origin/main` once the
change exists. This is the owner's order (CHG-061); W87 is split into three parts (W87-1 shipped
in PR #580, see the handoff).

1. **W87-2: a recent sign-in before deleting an account.** Ten minutes from the session's own
   start (CHG-056 (d)); the other-account case (CHG-066 (c)); recovery when the session ended
   during the sign-in round trip (W87-1's recorded limit); the visible failure notice on cancel;
   the 2-Step line near "Sign in" (CHG-063 (e)). Plan: section W87-2 of `w87-plan-v2.md`, with
   Codex's open point on revocation in the recovery path.
2. **W87-3: the operator command** `python -m product_app.end_sessions --email … | --all`
   (CHG-063 (d), CHG-066 (d): signed-in sessions only). Plan: section W87-3, with Codex's open
   points on a stalled worker and request ids. Its pull request pins W87's needle (DONE).
3. **W88: refuse another site's session-opening loads** (CHG-063 (b), CHG-067). Plan:
   `w88/w88-plan.md`. Its pull request restores CHG-067's three held-back brackets verbatim.
4. **W105: open tabs share a renewed token** (CHG-071). Page-only; a row to add with W88.
5. **W80**: remove `/feedback/audit` (CHG-063 (c)); stop a cross-site link cancelling a sign-in.
   Write and review the plan first (failure modes in `w80/`).
6. **W75**, with the additions its row names.
7. **W76.** Its parts are agents' reports: reproduce each first. Note from W85: Sentry's FastAPI
   integration reads request bodies by default (`max_request_body_size` unset).

The owner's open questions from this session are listed in the handoff; ask them in one batch at
the start, with examples.

## Approvals

Sending this prompt approves the following for one pull request per item above (W87-2 and W87-3
are one pull request each), and the end-of-session handoff (docs only).
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
