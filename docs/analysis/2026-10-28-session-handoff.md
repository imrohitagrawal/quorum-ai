# Session handoff, 2026-10-27 to 2026-10-28 (transcript `16de928d`)

Written by the session. The owner's decisions are the CHG rows named here.

## Pull request #591

W114's pull request A was squash-merged as #591 (`e6d5300e955fb25cf1c523b3c967953f31bc04f2`). The
Deploy run 40581470010 for that commit has the job "Deploy to Fly.io" concluded `success`. On
2026-10-28, before this handoff pull request, production `/status` reported `build_sha`
`e6d5300e955fb25cf1c523b3c967953f31bc04f2` and `session_store` `ready`, and `/ready` answered 200.

What #591 changed is in the W114 board row and ADR-0176's amendment of 2026-10-25. Its review,
gates and e2e lanes are in the pull request's description.

## Recorded in this handoff pull request

- **CHG-095**: the owner's *"go ahead with your recommendation is (a) now, then (c)."*. Raise the
  three full-suite CI job limits, the deploy gate's wait and the drift watchdog's grace together
  (W115), then look for the cause of the runner's swing.
- **CHG-096**: W114's pull request B signs out, while the database cannot be read, only a session
  the server holds in memory (*"Refuse when not held"*, not the session's recommendation). The
  W114 row had planned to record this with B; it is recorded now so it does not wait on a session.
- **CHG-097**: the broken mutation check becomes W116, built right after W115; this session hands
  off to a fresh one.
- Extracts `docs/owner-answers/CHG-095.json` to `CHG-097.json`, made and checked with
  `scripts/owner_answers.py` from W113's branch (`check-rows`: 6 extracts, 0 problems; a copy of the
  log with one quote altered gave 1 problem).
- **The board**: new rows W115 and W116; W114's row and Parked line updated (A merged as #591;
  B resumes after W115 and W116); anchor re-stamped to `e6d5300`.
- The session's prompt moved to `docs/archive/2026-10/`; the next prompt is at the root.

## Not finished

- **W115** (CI limits): not started in the repository. The plan, its measurement script and
  output, and three Codex reviews are in the owner's evidence folder,
  `~/Projects/quorum-ai-evidence/2026-10-28/ci-limits/`. Codex's last re-check asked for one change
  (the timing table was labelled measured before it was re-measured); it is applied in `plan.md`
  and needs Codex's confirmation before code. ADR-0182 is reserved for it.
- **W116** (the mutation check): not started. Cause found from the CI logs of #583, #587, #589
  and #591, written in the row.
- **W115's investigation (c)**: not started. Read-only on CI logs; report to the owner before any
  change.
- **W114 pull request B**: not started. Plan revision 3 in `2026-10-24/w873-followup/` in the
  evidence folder; it must now take in CHG-096 and the sign-out/sign-in race (CHG-088 (m)), which
  was reproduced on `main` with probes saved in `2026-10-27/w114a/race-probes/`. The first branch,
  `w87-3/unchecked-cookie` (local only, `bc9dc49`), is still in worktree `quorum-ai-w873f`.
- **W113**: unchanged since the last handoff. Branch `w113/owner-quote-check`, local only, head
  `1e44865`, worktree `quorum-ai-w113`.
- **W80, W75, W76**: not started.

## Left open from #591's review (advisory, not fixed)

- A malformed signed-in cutoff has no runbook step.
- The "briefly unavailable" pages were not checked in Firefox or Safari.
- `docs/48`: the two in-memory id lists were judged not a kept datum (random session ids and
  times, 24 hours, lost at a restart).
- A revoked row whose delete failed and whose kind cannot be read answers "unchecked", not "ended".
- The mutation job's failure, now W116.

## Traps for the next session

- **A Codex job started with `codex-companion.mjs task --background` sends no notification.**
  This session ended a turn "waiting" on one that had finished in 31 seconds, and sat for about
  11 hours until the owner wrote. Check its status in the same turn, or run it so its end wakes
  the session.
- **Never stop processes with `pkill` by a virtual-environment path.** Reviewers' copies share
  the main checkout's `.venv`, so such a pattern killed their test runs. Stop your own task by its
  id, and kill only processes whose command names your worktree.
- **Running e2e lanes back to back spends the local session cap of 600**, and the next lane fails
  with 429s. Delete the worktree's `.data/feedback_events.sqlite3` (gitignored) between lanes.
- **Chain a commit after lint with `&&`, not `;`.** One commit landed after a failed lint and had
  to be amended.
- **Numbering across branches**: CHG-095 to CHG-097 are on `main` now; CHG-090, CHG-091 and
  ADR-0179 are still only on W113's branch. When W113 merges `main`, put both logs back in number
  order. ADR-0182 is W115's.
- **The owner's CHG-095 answer is dated 2026-10-27 in UTC** (19:10:06.838Z). The local clock read
  the next day.

## Not verified

- Any mutation score for code changed since #583 (W116).
- W114 A in Firefox and Safari.
