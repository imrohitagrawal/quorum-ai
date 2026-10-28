# Session prompt: CI limits, the mutation check, then security fixes: the board rows W115, W116, W114, W113, W80, W75 and W76

Written by the session of 2026-10-27 to 2026-10-28 (transcript `16de928d`). This file is
the session's wording. The owner's decisions are the CHG rows it names.

**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`. Read it first,
and follow it for roles, review rounds, gates, merging, production checks and cleanup.

## Read first

1. `docs/README.md`, then the newest `docs/analysis/2026-10-28-session-handoff*.md`.
2. `docs/65-open-work.md`: rows W115, W116, W114, W80, W75, W76, W45 and W112, and the Parked
   table (`make parked-check`). W113's row is on its branch, `w113/owner-quote-check`.
3. `docs/19-change-control-log.md`: CHG-049, CHG-060, CHG-061, CHG-063, CHG-083, CHG-085,
   CHG-086, CHG-088, CHG-089, and CHG-092 to CHG-097.
4. `git ls-remote origin 'refs/heads/*'` and `gh pr list --state open`.
5. The private evidence, outside the repository: `~/Projects/quorum-ai-evidence/` —
   `2026-10-28/ci-limits/` (W115: `plan.md` and its three Codex reviews, `measure.py` and its
   output); `2026-10-27/w114a/` (W114 A's reviews, triage and `race-probes/`);
   `2026-10-24/w873-followup/` (W114 B: `50-stop-rule-root-cause-and-plan.md`, revision 3) and
   `2026-10-24/w873-policy/owner-answers.md`; `2026-10-26/w113/` (`STATE.md` first);
   `2026-10-18/w80/` (failure modes only; the W80 plan is not written yet).

## The items, in order

Each is its own pull request, deployed and checked live before the next starts. Route each
with `make skill-route ITEM=<row>`, and again with `make skill-route DIFF=origin/main` once the
change exists. Item 1 comes first because it can fail any pull request's required `pytest` job. The order
of W115 and W116 is CHG-095 and CHG-097; putting (c) after W116 is the session's reading of
them; the rest keep the previous prompt's order (CHG-061, CHG-094).

1. **W114: the clock-rounding test** (the W114 row; #591 shipped it). Make
   `test_t31_the_window_is_60_monotonic_seconds_from_the_last_line` set the clock to exact
   values instead of adding steps, and make every other test in that file that adds steps safe
   the same way. Show it red first for a start value where the sum falls under 60. The
   handoff has the measurement.
2. **W115: raise the CI time limits together** (CHG-095). Have Codex confirm the one change
   applied after its last re-check of `plan.md`, then build from it: tests red first, ADR-0182,
   ADR-0157 superseded in part. The pull request's own CI shows the new limits apply.
3. **W116: the mutation check measures again** (CHG-097). Two causes are in the row; the run
   stops at the first failing test, so more may sit behind them. Write the plan and have Codex
   review it first. Other test files also change folder
   (`grep -rln "monkeypatch.chdir\|os.chdir" tests`): find which of them the mutation run
   reaches before writing the guard. Done when the pull request's own mutation job prints a
   score; read the number in its log.
4. **W115's investigation (c): the roughly 7-minute swing between runs of the same suite.**
   Read-only on CI logs (runner image, CPU count, the slowest test files per run). Report to the
   owner before any change; no pull request unless the owner asks for one.
5. **W114, pull request B: the sign-out part.** Build it table-first from plan revision 3, with
   CHG-096 ("Refuse when not held") and the sign-out/sign-in race of CHG-088 (m). Have Codex
   review the amended plan before code.
6. **W113: rebuild the owner-quote check on a Markdown parser** (CHG-094: limit 2,900 changed
   lines; past it, stop and ask). Continue branch `w113/owner-quote-check` in worktree
   `quorum-ai-w113`, after merging `main` into it. Amend `r2/root-cause-and-plan.md` with
   `r2/codex-plan-review.md`, have Codex review the amended plan, then failing tests first.
   The owner's approval for W113 is CHG-090, on that branch, with CHG-094's new limit.
7. **W80**: remove `/feedback/audit` (CHG-063 (c)); stop a cross-site link cancelling a sign-in.
   Write and review the plan first.
8. **W75**, with the additions its row names.
9. **W76.** Its parts are agents' reports: reproduce each first. Sentry's FastAPI integration
   reads request bodies by default (`max_request_body_size` unset).

A new security warning that fails `make vuln-audit` follows CHG-092 and ADR-0181.

## Approvals

Sending this prompt approves the following for one pull request per item above (none for item
4 unless the owner asks), any update pull request CHG-092 allows, and the end-of-session handoff
(docs only).
- Push and open the pull request.
- Squash-merge through `make close-guard`, with `EXPECT_CLOSE=""` (or the issues it closes).
- Deploy.

Each needs every required gate green and every reproduced blocker fixed. Nothing else is allowed:
- no paid call;
- no `fly secrets` change;
- no change to GitHub's repository settings, and the mutation job stays advisory;
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
