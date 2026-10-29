# Session handoff, 2026-10-29

Written by the session. Decisions are the CHG rows named here; each is a plain restatement
(CHG-102).

## Shipped

- **#594, W114 item 1: an exact test clock.** Squash-merged as `e8b5891`. The 60-second window
  test now steps a clock it owns, so its steps cannot sum to just under 60. Deploy run 40721379134
  for `e8b5891` has the job "Deploy to Fly.io" concluded `success`.
- **#595, W115: CI time limits.** Squash-merged as `7f8cf00`. The three jobs that run the whole
  suite get 45 minutes, the deploy gate waits 3000 s and the drift watchdog's grace is 3300 s
  (ADR-0182, CHG-095). Deploy run 40750748257 for `7f8cf00` has the job "Deploy to Fly.io"
  concluded `success`.
- **#597, W116: tests run inside the mutation tool's copy.** Squash-merged as `0b3234f`, so the
  advisory mutation job can print a score again (ADR-0183). Deploy run 40858370125 for `0b3234f`
  has the job "Deploy to Fly.io" concluded `success`, and production `/status` reported
  `build_sha` `0b3234fcbbd28f07336449a0dbf17b56fb79fe07` afterwards: `0b3234f` is in production.

## The two probes for W116

- **The discovery probe #596** ran the whole suite inside the mutation tool's copy and listed 26
  failing tests in five causes, which #597 fixed. It was closed without merging (CHG-100).
- **The confirmation probe #598** ran after #597. Its mutation job, run 40853766761, printed
  `mutation score (killed / (killed+survived)) = 86.7% (threshold 80%)`: 13 killed, 2 survived.
  It was closed without merging. The score is the condition CHG-099 and CHG-100 set for W116; the
  two survivors are row W120.

## Recorded in this handoff pull request

- **CHG-102**: public records here are plain restatements (decision, basis, trade-offs); the
  exact records and the next prompt are kept in the owner's private notes. It overrides the
  exact-words rule in `AGENTS.md` until W117 rewrites the rules.
- **CHG-103**: the order of the next work, and four approved GitHub settings for this
  repository.
- **The board**: new rows W113 and W117 to W121; W62 extended with the cuts found; a Parked line
  for W113. W116 reads DONE because the board derives it from the tree.
- The session's root prompt moved to `docs/archive/2026-10/`. No new prompt is added at the
  root (CHG-102).

## Open, in CHG-103's order

- **W117**: the public-content guard (one shared scanner, a hook before publishing, a CI job, a
  scan of the merge text) and the rules that required quoted answers and session ids.
- **W118** (with W79): enterprise hygiene.
- **W62**: suite time, with the measured cuts in its row.
- **W121**: two flaky tests seen on #597's runs.
- The cleanup of existing public records.
- **W120**: the two surviving mutants of `is_garbled`.
- **W119**: process sized to risk.
- Then W114's pull request B, W80, W75, W76, and W113's redesign. W113's branch,
  `w113/owner-quote-check`, has never been pushed.

## Technical traps

- **zsh does not split an unquoted variable into words.** `cmd $ARGS` passes one argument, not
  several; use an array or write the arguments out.
- **A gate's log is not available until the whole workflow run finishes.** To read one job early,
  download that job's uploaded artifact instead of waiting for the log.
- **A guard that skips paths missing locally behaves differently on CI.** `npm ci` creates
  `e2e/node_modules` on the runner, so a path that is absent on a fresh local copy exists there.
- **`uv run` in a fresh copy of the tree builds an empty environment** unless
  `UV_PROJECT_ENVIRONMENT` points at an existing one, and tests that start a child process then
  fail.
- **Editing a pull request's body re-runs CI**, because the CI workflow fires on `edited`. Settle
  the body before the last push.
