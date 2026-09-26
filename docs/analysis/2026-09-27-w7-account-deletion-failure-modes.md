# W7, 2b — account deletion: failure modes first

Written before the code (AGENTS rule 16e), for board row W7 (part b of the
second pull request; history was part a, ADR-0135).

## What the owner decided

- CHG-012 D7 (2026-09-24), their words: *"but yes on account deletion we
  should remove"*. The session's design, summarised back and not contested:
  account deletion as a typed-confirmation action on one authenticated
  endpoint that removes the account, its history and its session, nulls the
  account id on operator run rows, and keeps the 24-hour spend envelope
  keyed on a one-way hash of the Google subject for 24 hours.
- CHG-021 (f) (2026-09-25, 08:56:57Z): *"A reminder and re-confirmation from
  User before permanently deleting the account."* The session's reading:
  permanent deletion needs a reminder and a re-confirmation on top of the
  typed confirmation.
- The race the session promised to design and test (2026-09-25, 11:30:42Z):
  deleting an account while it is signed in on another device.
- CHG-023: the stored questions are removed with the account.

## Measured on main by the read-only map (2026-09-26)

- Deleting only the accounts row leaves another device's session working,
  still carrying the deleted id (a probe showed it resolving).
- Nothing revokes all of an account's sessions; the `sessions` table has no
  index on `account_id`.
- A session read from disk just before a delete can be put back in the
  in-memory cache after it (a probe showed the restore).
- Deleting and re-creating an account resets the daily spend cap today: a
  new account id, and spend counts by account id (a probe: 0.35 spent on the
  old id, 0 on the new).

## Failure modes, and the design's answer to each

1. **Deleted by accident.** Three steps in the page: a reminder of what is
   deleted (history, sign-in, nothing recoverable), a typed confirmation
   (the visitor types their own email; the session's choice), and a final
   "Delete permanently".
   The server checks the typed text and the CSRF token.
2. **Deleted by someone else.** One authenticated endpoint, the session's own
   signed-in account only, CSRF-protected, JSON body. Nothing takes an
   account id from the request.
3. **Still signed in on another device** (the promised race). Deletion
   removes every session of the account, durable and in memory, and records
   the id as deleted (in memory, for the session lifetime) so a session read
   from disk a moment before cannot be restored after. A test signs in on two
   devices, deletes on one, and the other's next request is anonymous.
4. **The spend cap resets by deleting and re-creating.** A new account's id is
   derived from a keyed one-way hash of the Google subject (HMAC-SHA256 with
   the server's token secret). Deleting and signing in again gets the SAME id,
   so the 24-hour spend already recorded under it still counts. The cost
   ledger's rows are not touched; the hash is not reversible without the
   secret. Accounts created before this change keep their random id; for
   them the envelope does not carry over (recorded, not migrated).
   Measured: a charge of 0.35, deletion, and a new sign-in with the same
   subject read 0.35 again under the same id (the test named in ADR-0136).
5. **Operator rows keep the account.** The run-history table's `account_id`
   is set to NULL for the deleted account's rows; the cost ledger keeps the
   hash-derived id, which is what keeps the 24-hour envelope.
6. **A run in flight when the account is deleted.** It finishes; its history
   write finds no account and writes nothing; its run-history row is written
   without the account id.
7. **Partial deletion.** The account row, its history and its sessions go in
   one transaction in the sessions database; the run-history NULLing is a
   separate database and runs after, best effort, logged on failure.
8. **Deleting an anonymous session.** Refused: there is no account.
9. **The page after deletion.** The browser is signed out (the session is
   gone) and shown the anonymous page.
