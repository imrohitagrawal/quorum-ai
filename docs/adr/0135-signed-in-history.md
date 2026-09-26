# ADR-0135: Signed-in history keeps the last 5 questions for 30 days

## Status

Accepted — 2026-09-26, board row W7, part a of the second pull request. The product owner decided W7's purpose on 2026-09-24 (CHG-012 D7, their
words): *"the purpose of sig-in is to preserve the history of the searches
from a account. THis can be limited to last 5 searches for example if we
face issue in storage."* and *"the whole purpose will be forfeited if we
delete the history on every sign-out! but yes on account deletion we should
remove"*. On 2026-09-25 (CHG-021 a): *"do carry them over, but only the runs
from the same browser session, at the moment of sign-in, capped by the same
keep-the-last-5 rule"* (the phrase in double quotes is the session's
suggestion, which the owner agreed to). On 2026-09-26 at 15:05:11Z (CHG-023)
they approved storing the question text, by selecting the session-drafted
option *"Yes, store the question (Recommended)"*.

The session's design, summarised back to the owner and not contested
(CHG-012 D7): keep the last 5 AND drop runs older than 30 days, both
settings; a summary row per run, not the run; nothing deleted on sign-out.
The session's own choices below are marked as such. One of them extends
CHG-021 (a): a run still RUNNING at sign-in joins the history when it
finishes. The owner's words cover the runs of that session "at the moment of
sign-in"; the 2026-09-25 11:30:42Z message promised to design and test for
this race, not a decision that such runs join. Splitting W7's second
pull request into history (this one) and account deletion (the next) is the
session's: they are two concerns.

## Context

Measured on `main` before building (read-only map, 2026-09-26): no store
kept question text durably (the run-history table is metrics-only by
contract, and the in-memory run store forgets a finished run after an hour);
sign-in hands the browser a new account id and keeps nothing of the
anonymous one; a run in flight keeps the id it started with. Failure modes
first: `docs/analysis/2026-09-26-w7-history-failure-modes.md`.

## Decision

1. A `history` table in the sessions database (beside `accounts`, created by
   a guarded migration, `w7_history`): the run id, the account id, the
   question, status, mode, number of models, estimated cost, completion time
   and verdict, the result's own caption, captured when the run finishes
   from the response already built (no extra judge call). No answer, source
   or judge rationale.
2. A finished run joins a history only if its account is signed in, or its
   ANONYMOUS session has since signed in (`account_history.carry_over`,
   recorded at the callback before the old session is revoked). A session
   already signed in as another account carries nothing, and a run already
   in one account's history is never moved to another (review round 1
   found a sign-in switch moving one account's question into another's).
   The link is kept in memory for the longer of `QUERY_RUN_ACTIVE_TTL` and
   the run deadline setting.
3. Every write keeps only the account's newest `HISTORY_KEEP_COUNT` (5) rows
   and none completed more than `HISTORY_KEEP_DAYS` (30) ago, in one
   transaction; reading applies the same rules. A run is keyed by its id, so
   it is never listed twice.
4. The page renders the history, escaped, in a "History" disclosure beside
   Sign out. There is no separate endpoint (the session's choice: the page
   is rendered on the server, and an endpoint would add a surface).
5. A signed-in visitor's composer lede says the last 5 questions are kept for
   30 days and answers are not. The footer and receipt lines about the
   answer stay; the anonymous page is byte-identical.
6. The cost shown is the estimate the visitor confirmed before the run (the
   session's choice: it is the one figure every run has, measured or not).

## Rejected alternatives

- **Rebuild history from the run-history table:** it holds no question, by
  contract.
- **Carry over every run of the anonymous id at any time:** the owner said
  "the same browser session, at the moment of sign-in"; the link lapses when
  no run of it can still be running.
- **A JSON history endpoint:** nothing needs it yet.

## Consequences

- A signed-in account's questions are stored (at most 5, at most 30 days).
  Until account deletion ships in W7's next pull request, the keep rules are
  the only removal. `docs/48` records this for signed-in history only.
- A run still running at sign-in joins the history when it finishes
  (the promised race, pinned by
  `test_a_run_still_running_at_sign_in_joins_when_it_finishes`).
- Signing out deletes nothing; signing in again shows the same history.
- Carry-over takes what the in-memory run store still holds: runs of the
  session that finished more than 1 hour (`QUERY_RUN_TERMINAL_TTL`) before
  sign-in are not carried. A restart between sign-in and a run finishing
  loses the link, and the run with it (the run store is in memory too).
- If the history cannot be read, the page says so rather than showing an
  empty history.
- W7's board needle moves to what the next pull request adds
  (`def delete_account(`), so the row does not read done while deletion is
  pending.
