# Session handoff — 2026-10-19

The session of 2026-10-17 to 2026-10-19 (transcript `b12e5f2a`) ran `CONTINUE-SECURITY-W85-W76-PROMPT.md`,
archived by this pull request as `docs/archive/2026-10/CONTINUE-SECURITY-W85-W76-PROMPT.md`. The owner
chose to hand off after W87-1 (CHG-072). The source of truth is `git log` and the ADRs; this note says
where things stand.

## Shipped

| Pull request | Merge commit | What | Decisions it added or rests on |
|---|---|---|---|
| #575 | `a839ba9` | W85: a request body over 1 MB gets 413 before it is read; request models refuse unknown fields with one error, bound their lists, and a 422 lists at most 20 errors | ADR-0171; CHG-063 (a), CHG-064 |
| #578 | `8463a72` | W86: signed-in history older than 30 days, and beyond an account's newest 5, is deleted for every account; the session store deletes securely | ADR-0172; rests on CHG-023 |
| #579 | `19647a9` | W100: a high-stakes acknowledgement is sent only for a ticked box; an unticked run is held; a tick is used by one attempt | ADR-0173; CHG-063 (g), CHG-065, CHG-068; also landed CHG-066 and CHG-067 |
| #580 | `5e8676d` | W87-1: a session ends 12 hours after sign-in, or 24 hours after an anonymous start; the warning, the texts, the late-run refusal | ADR-0174; CHG-056 (c), CHG-063 (f), CHG-066 (a), (b), CHG-069, CHG-070 |

Production checks, run by this session:
- #575: the Deploy job of run 39067406792 succeeded; `/status` `build_sha` was `a839ba9`; one request of
  1,048,577 bytes with no cookie to `/v1/query-runs/estimate` answered `413` with the
  `REQUEST_TOO_LARGE` envelope (curl took over two minutes to finish; why is UNVERIFIED), a small one `401`.
- #578: the Deploy job of run 39092019131 succeeded; `build_sha` `8463a72`. The sweep cannot be seen from
  outside: the last 100 log lines held only health checks.
- #579: the first three Deploy runs were skipped because main's E2E run failed in the signed-in lane on
  its first attempt; after `gh run rerun --failed` it passed, and the Deploy job of run 39155055508
  succeeded; `build_sha` `19647a9`; the served `app.js` contains `safetyAcknowledgementsFor`.
- #580: the E2E run on the merge passed at once; the Deploy job of run 39296617736 succeeded (two earlier
  runs for the same commit were cancelled); `build_sha` `5e8676d`; `/ready` 200; the served `app.js` contains
  `maxAgeReminderText`. The 12-hour end itself cannot be seen from outside without waiting 12 hours.

## What the owner decided this session

CHG-063 (the values and words for W85, W88, W80, W87 and W100), CHG-064 (W85's bounds), CHG-065 and
CHG-068 (W100's acknowledgements), CHG-066, CHG-069 and CHG-070 (W87's warning, late runs, other account,
`--all`, card title, keeping the question, sign-in-off text, countdown), CHG-067 (what W88 refuses, and a
row for page loads that never count, now W106), CHG-071 (tabs share a renewed token, now W105), CHG-072
(hand off after W87-1). Two of the session's own records were corrected by review: CHG-069 no longer
says the session explained itself before its next question (the transcript holds no such text), and
CHG-070 (d) records that its question wrongly said today's idle warning counts down. CHG-072's question
wrongly said W80's plan had been reviewed by Codex; only W80's failure modes exist.

## Left for the next session

`CONTINUE-SECURITY-W87-W76-PROMPT.md`, committed by this pull request: W87-2 (recent sign-in before
deleting an account), W87-3 (the operator command), W88, W105, W80, W75, W76. The plans and evidence are
outside the repository, in `~/Projects/quorum-ai-evidence/2026-10-18/` (`w87/`, `w88/`, `w80/`), because
CHG-060 still holds W87's remaining parts and W88 back.

**Owner questions to ask at the start of the next session:**
- The `docs/48` row for the account id the page keeps beside a saved question (added by W87-1, pending).
- W87-1 shows CHG-070 (c)'s sign-in-off text to a signed-in visitor on a page without sign-in: the
  session's choice.
- After the anonymous "Sign in with Google" from the late-run card, the typed question is not kept
  (CHG-070 (b) covered only "Sign in again").
- W104's three small follow-ups need words.
- W102 (many large bodies at once) needs an owner value.

## Advisory leftovers, recorded in the ADRs

- W85 (ADR-0171): a request that declares a body it never sends waits for it on every route; no counter of
  its own for 413s; no per-string bounds on model ids, versions and tokens; what Fly's proxy shows on an
  early 413 (UNVERIFIED). Sentry's FastAPI integration reads request bodies by default (for W76).
- W86 (ADR-0172): a row can pass 30 days while the machine is stopped; Fly keeps volume snapshots 5 days;
  a rollback to a non-secure writer and back can leave one pruned question in free pages.
- W100 (ADR-0173): stacked toasts cover the top of the box at 375 px on the expired-confirmation path; a
  ticked run continues if the visitor navigates away during the final check; the unknown-type rule is
  caught by a unit test only.
- W87-1 (ADR-0174): a run can end after its session (W103); "Sign in again" pressed seconds before the
  end comes back to `sign_in=failed` (fixed in W87-2); a lost run result cannot be reopened.

## Traps learned

- **CI's e2e lanes share one count of opened sessions on disk.** W100's new tests took the third lane past
  600 and it failed with `locator.fill` timeouts; reproduced locally in CI order (459, then 571, then 600).
  `e2e.yml` now allows 1500. The signed-in lane uses its own temporary data folder.
- **The signed-in lane's first attempt fails in CI now and then.** It failed on main for #579 and on #580
  (once each, sign-in-dependent tests), and passed on re-run; locally the lane passed every time.
- **On a loaded Mac, 58 to 59 `tests/unit/test_w54_*` fail** with `BlockingIOError` in the PDF reader's
  pipe write, identically on clean `main` (now row W107). Count non-w54 failures before blaming a diff.
- **A production check must never request `/ui` or `/v1/session` without a cookie**: each spends one of
  the owner's network's two daily sessions. One such check was stopped before it ran.
- **Text written mid-turn before a question tool call is not in the transcript**, so the owner may not
  have seen it (CHG-069). Put reasoning the owner needs inside the question.
- **Codex sometimes cites rules from its own instructions** ("make intervals configurable"); check the
  repository before acting (`git grep`), and record the rejection.
- **Disk filled twice** from other work on the Mac. The owner chose deleting Codex sessions older than
  30 days (9.1 GB) and pruning unused Docker images and build cache (about 9 GB reclaimed).
- **The stop rule's count mattered.** W85, W86, W100 and W87-1 each reached one failed fix (a fix that
  added a defect or was incomplete); each following fix was narrow and Codex's re-check approved it.
