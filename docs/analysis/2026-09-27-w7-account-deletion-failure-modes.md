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

## Reported on main by the read-only map (2026-09-26; its probes are not committed)

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
4. **The spend cap resets by deleting and re-creating.** *(The answer below
   was replaced by the re-plan at the end of this page.)* A new account's id is
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
6. **A run in flight when the account is deleted.** *(Replaced by the
   re-plan below.)* It finishes; it is
   marked at deletion, so it writes no history and its run-history row is
   written without the account id. (The first draft said its history write
   "finds no account". Review round 1 showed that is false once the same
   person signs in again: the id comes back. See 10.)
7. **Partial deletion.** The account row, its history and its sessions go in
   one transaction in the sessions database; the run-history NULLing is a
   separate database and runs after, best effort, logged on failure.
8. **Deleting an anonymous session.** Refused: there is no account.
9. **The page after deletion.** The browser is signed out (the session is
   gone) and shown the anonymous page.

## Added by review round 1 (2026-09-27)

10. **The id comes back.** *(Closed by construction by the re-plan below.)* Because of 4, the same Google account signing in
    again gets the same id, so anything keyed only on the id treats the time
    before the deletion as the new account's. Review showed three cases,
    each by a forced interleaving or a probe in its own copy: a run from
    before the deletion landing in the new history; a history write that
    checked the account just before the delete landing just after it; the
    2-hour deleted mark refusing the new account's own sessions and run
    rows. Answer: runs are marked at deletion; the history write checks the
    account row inside its own transaction; the mark refuses only sessions
    created before the deletion.
11. **A sign-in finishing during the delete.** The callback reads the
    account, the delete runs, then the session is issued, leaving a session
    row for a deleted account. Answer: after issuing, the callback checks
    the account row again and, if it is gone, revokes the session and
    reports "did not complete".
12. **A failed delete.** *(Replaced by the re-plan below: nothing changes.)* The sessions are refused before the rows are
    deleted, so a 503 leaves the visitor signed out. The message says so.
13. **The local `X-Account-Id` path.** It needs no cookie. Deletion refuses
    it.
14. **Accounts created before this change.** Their id is random, so for
    them the envelope does not carry over, once each. The product owner
    accepted that on 2026-09-27 at 12:02:35Z (CHG-024).

## Re-plan after review round 2 (2026-09-27)

Round 2 found four blockers; two were added by the round-1 fixes. The root
cause is 4 above: the account id was derived from the Google subject, so it
came back after deletion, and every guard against the time before the
deletion was one check with a gap. The product owner chose, on 2026-09-27 at
15:05:02Z, to re-plan with a separate spend key (CHG-025). Written before the
code, from two read-only maps of the tree at 6301fc7.

**The design.** Each account life gets a fresh random id again (as ADR-0130
had). The 24-hour spend envelope is keyed on a separate **spend key**, stored
in a new `accounts.spend_key` column: HMAC-SHA256 of the Google subject for a
new account; the account's own id for an existing one (backfilled), so no
number changes at deploy and CHG-024's one-time reset stays exactly as
accepted. An anonymous session's spend key is its account id.

### How a separate spend key fails

S1. **A money call left on the account id.** It reads 0 for a signed-in
    account and never trips. Answer: the key is resolved once per request in
    the route and stored on the run; each money call site passes it. Test: a
    signed-in account whose key differs from its id, driven through the real
    routes; each call site mutated back to the id must turn a test red.
S2. **A reconcile or void under a different key from the charge.** The
    read-only map measured it: the store accepts the correction, the global
    meter moves, the account's meter keeps the estimate, and a later correct
    write is refused. Answer: charge, void, reconcile and the judge's
    pre-flight all read `QueryRun.spend_key`, never look it up again. Test:
    reconcile with actual ≠ estimate moves `daily_spend_for(spend_key)`.
S3. **Estimate and token disagree.** The confirmation token stays bound to
    the account id (it checks who asked); only the rails take the spend key.
    Test: a signed-in confirm-band run completes its confirmation.
S4. **The lookup fails, or the account is gone mid-request.** Falling back
    to the account id would open a fresh, empty envelope. Answer: a read
    error refuses the request (503); a deleted account's request is refused
    (401). Test: both, and no charge row under the account id.
S5. **The migration on a read-only volume.** Guarded, one transaction, like
    `w7_accounts`; sign-in needs both markers. With the column missing,
    every row's key is its id, which is exactly the backfill value. Test: the
    backfill sets spend key = account id on an existing row (with a partner
    proving the row exists).
S6. **A rolled-back build inserts a row without a spend key.** NULL means
    the account id. Test: a NULL row resolves to its id.
S7. **The secret is rotated.** The key is stored, never recomputed, so a
    live account keeps its day. Only an account deleted and re-created after
    a rotation starts fresh (recorded).
S8. **An anonymous run, then sign-in mid-run.** The run keeps the key it was
    charged under. Test: reconcile after sign-in lands under the anonymous key.
S9. **Two lives of one person at once.** Both charge under the same key
    inside the store's one lock; the atomic check still holds.

### The account side, once ids are random again

- Gone by construction: a run, history row, session or carry-over link from
  before the deletion can never match the new life's id. The round-1
  `account_deleted` run flag is removed.
- Still guarded:
  - a history write racing the delete: the write checks the account row in
    its own transaction (kept; the history-store tests now seed a row);
  - a sign-in or session caught in the delete: deletion drops cached
    sessions and carry-over links BEFORE and AGAIN AFTER the rows are
    deleted, and the callback re-checks the row;
  - a run-history row written just after the NULLing: after writing, the
    run re-checks the deleted mark and NULLs again;
  - a failed delete: the mark is lifted, so nothing changed and "please try
    again" is true (round 2 showed the old order hid a surviving account's
    run and signed it out).
- One run at a time now keys on the account id (the session's choice): a new
  life can run while an old run finishes. Money stays bounded by the atomic
  charge (S9). It removes the dead-end 409 round 2 found.

### Open, for the owner (not blocking this design)

- Cost-ledger rows keep the spend key after the 24 hours; nothing in `src/`
  deletes cost rows. That was already true of the derived id on this branch.

### Added by review round 1 of the re-plan (2026-09-27)

- **An account switch racing the delete** (critical, reproduced by review):
  device 1 signed in as Ada switches to Grace while Ada is deleted on device
  2. Ada's id then had no account row, and carry-over took it for anonymous,
  moving Ada's questions into Grace's history. Answer: carry-over refuses an
  id whose account is being or was just deleted, and deletion drops links to
  or from the id.
- **A failed delete that still changed things**: the refusal was set before
  the store transaction, so another device was signed out and a run
  finishing then NULLed the account's run rows. Answer: before the rows go,
  the delete is only marked as under way (read by the spend-key lookup and
  carry-over, refusing nothing); the refusal comes after the commit.
- **The old-account reset** (CHG-024): the option the owner chose (CHG-025)
  said the re-plan also ends it. Answer: a deleted account's spend key is
  kept 24 hours under the keyed hash of its subject, and the re-created
  account takes it back.

