# Session prompt: parked work, W28 research, W70

Written by the session of 2026-10-14 to 2026-10-16 (transcript `42608a52`). This file is the
session's wording. The owner's decisions are the CHG rows it names, and the owner's messages of
2026-10-15 and 2026-10-16 in that transcript (`type: user` records), which item 1 records as CHG
rows in the owner's exact words.

**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`. Read it first,
and follow it for roles, review rounds, gates, merging, production checks and cleanup.

## Read first

1. `docs/README.md`, then the newest `docs/analysis/<date>-session-handoff*.md`.
2. `docs/analysis/2026-10-14-session-handoff-2.md`: W70's state and its bounded plan.
3. `docs/65-open-work.md`, rows W13, W28, W70 and W71 to W81.
4. `docs/19-change-control-log.md`: CHG-012 D5, CHG-026 (f), CHG-042 and CHG-046.
5. `git ls-remote origin 'refs/heads/*'` and `gh pr list --state open`.

## The items, in order

Each is its own pull request, merged and running in production before the next starts. Route each
with `make skill-route ITEM=<row>`.

1. **Parked work and the stop rule (docs and one check).**
   - Record the owner's messages of 2026-10-15 and 2026-10-16 as CHG rows: parked work is
     reviewed first; the stop rule; branches are not deleted blindly; Codex reviews each plan
     before code; W28 is taken up after W71 to W81; the security baseline; the W28 research.
   - The three closed branches (`fix/e2e-visual-wait-for-fonts`, `proposal/268-web-search-context-tokens`,
     `w29/judge-wiring-plan`): for each, list every file not in `main` and everything that needs
     it (open issues, board rows, ADRs, CHG rows), as a table in the pull request. Delete a
     branch only when every file is in `main` or archived there, every citation points at the
     new place, and this pull request is merged and deployed. Issue #268 is OPEN, and its branch
     holds the script that measures the open decision; the session recommends moving the script
     and its test into `main` under `scripts/proofs/`.
   - Every open draft and parked board row states a reason, an owner and a resume-when. `make
     handoff` lists every remote branch with no open pull request and every parked item whose
     resume-when has passed, reports its count, and fails on an empty input.
   - Add a board row for the security baseline, ranked first among the security rows: every
     measure in place with the command that proves it (replacing `docs/41-security-controls.md`),
     ASVS 5.0 Level 2 item by item, and the gaps in section 9 of
     `docs/analysis/2026-10-13-security-review.md`.
   - In the skill and `AGENTS.md` rule 12: Codex reviews each item's plan before any code. Each
     branch ends merged and deleted, or recorded with its fate, and is deleted only by the rule
     above. The stop rule: after two failed fixes in a row, revert to the last commit that passed
     review, write the root cause and a smaller plan, have Codex review it, and restart in a
     fresh session.
   - The next-session prompt becomes a rule, not a habit (owner, 2026-10-16). On 2026-10-16 a
     prompt with the process line but another shape and name passed `make prompt-check`.
     - A template beside the skill, `prompt-template.md`, in this file's shape; the skill's
       handoff contract says to copy it.
     - `make prompt-check` also refuses a root prompt without the four sections "Read first",
       "The items, in order", "Approvals" and "End of session", or not named
       `CONTINUE-<AREA>-<ROWS>-PROMPT.md` (capitals, digits and dashes).
     - A project hook in `.claude/settings.json` runs `make prompt-check` whenever a root
       `*PROMPT*.md` is written or edited, and shows the agent any failure. Today `make handoff`
       only shows the result (ADR-0045), so nothing stops a session ignoring it. W81 also adds
       to that file; keep the two parts separate.
     - The handoff pull request commits the next prompt at the root, so CI's existing check of
       tracked prompts (ADR-0160, decision 4) refuses a bad one whatever agent wrote it, Codex
       included. The session that runs it archives it, as now.
     - `make handoff` prints the exact line for the owner to paste, `Read <file> in the repo
       root and follow it exactly.`, and the skill's closing status block ends with it under
       "Next action".
2. **W28: research the six decisions (docs only).** The six are in draft #525's plan, section
   "Decisions only the owner can make". For each: the question in one sentence, one concrete
   example, the options, each option's security risk and build cost, how established products do
   it (cite what was read), and a recommendation. This is also the BYOK security research the
   owner asked for on 2026-09-29. Codex reviews it. Write `docs/analysis/<date>-w28-decision-research.md`
   and give the owner one line per decision in chat. Record no decision.
3. **W70: the secret scan.** Follow the bounded plan in the handoff of 2026-10-14 (read first,
   item 2), with one change from the owner: a miss that has a fix is fixed, test first; only a
   miss with no fix is written down, with the reason. The scan ends at 0 findings over the whole
   tree. Production cannot show this; name the tests that prove it.

## Approvals

Sending this prompt approves the following for four pull requests: items 1, 2 and 3, and the
end-of-session handoff (docs only).
- Push and open the pull request.
- Squash-merge through `make close-guard`, with `EXPECT_CLOSE=""`.
- Deploy.
- For item 1: delete a closed remote branch only under the rule in item 1.

Each needs every required gate green and every reproduced blocker fixed. Nothing else is approved:
- no paid call;
- no `fly secrets` change;
- no change to GitHub's repository settings;
- no attack on production;
- no recorded W28 decision.

## End of session

1. Run `make handoff`.
2. Write the narrative handoff. Every "merged" or "in production" must cite its pull request, or
   `make validate` refuses it.
3. Write the next session's prompt for the security baseline row and the rows after it, in this
   file's shape. The session that finishes W71 to W81 writes the W28 prompt for a fresh session.
4. In the handoff pull request, archive this file into `docs/archive/<month>/`. Run `ls` there
   first; if a file of the same name exists, add a date suffix.
5. After the merge, delete the root copy by name.
