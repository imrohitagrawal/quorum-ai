# ADR-0135: Signed-in history keeps the last 5 questions for 30 days

## Status

Accepted — 2026-09-26, board row W7, the second of W7's pull requests, part
a. The product owner decided W7's purpose on 2026-09-24 (CHG-012 D7, their
words): *"the purpose of sig-in is to preserve the history of the searches
from a account. THis can be limited to last 5 searches for example if we
face issue in storage."* and *"the whole purpose will be forfeited if we
delete the history on every sign-out! but yes on account deletion we should
remove"*. On 2026-09-25 (CHG-021 a): *"do carry them over, but only the runs
from the same browser session, at the moment of sign-in, capped by the same
keep-the-last-5 rule"*. On 2026-09-26 at 15:05:11Z (CHG-023) they approved
storing the question text: *"Yes, store the question"*.

The session's design, summarised back to the owner and not contested
(CHG-012 D7): keep the last 5 AND drop runs older than 30 days, both
settings; a summary row per run, not the run; nothing deleted on sign-out.
The session's own choices below are marked as such. Splitting W7's second
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
   question, status, mode, number of models, estimated cost and completion
   time. No answer, source, judge rationale or verdict (CHG-023).
2. A finished run joins a history only if its account is signed in, or its
   anonymous session has since signed in (`account_history.carry_over`,
   recorded at the callback before the old session is revoked, and kept in
   memory for `QUERY_RUN_ACTIVE_TTL`, as long as a run can still run).
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
6. The cost shown is the estimate the visitor confirmed, for every row,
   including carried ones (the session's choice: a carried run's actual cost
   would need the full result response, which can dispatch the paid judge).

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
- W7's board needle moves to what the next pull request adds
  (`def delete_account(`), so the row does not read done while deletion is
  pending.
