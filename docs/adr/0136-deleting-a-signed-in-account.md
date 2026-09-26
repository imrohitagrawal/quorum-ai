# ADR-0136: Deleting a signed-in account

## Status

Accepted — 2026-09-27, board row W7, part b of the second pull request. The
product owner decided that deleting an account removes its history
(CHG-012 D7, their words): *"but yes on account deletion we should remove"*.
The session's design, summarised back to the owner and not contested
(CHG-012 D7): account deletion as a typed-confirmation action on one
authenticated endpoint that removes the account, its history and its
session, nulls the account id on operator run rows, and keeps the 24-hour
spend envelope keyed on a one-way hash of the Google subject for 24 hours.
On 2026-09-25 at 08:56:57Z (CHG-021 f): *"A reminder and re-confirmation
from User before permanently deleting the account."*

The session's own choices are marked below. Among them: typing the account's
own email as the typed confirmation; the three steps' order and words; the
keyed-hash account id as the way to keep the envelope.

## Context

Measured on `main` by the read-only map before building (2026-09-26):
deleting only the accounts row left another device's session working;
nothing revoked all of an account's sessions; a session read from disk just
before a delete could be cached after it; and deleting and re-creating an
account reset the daily spend cap (a probe spent 0.35 on the old id and
read 0 on the new). Failure modes first:
`docs/analysis/2026-09-27-w7-account-deletion-failure-modes.md`.

## Decision

1. `POST /v1/account/delete` (not in the published API schema; the page
   calls it): the session's own signed-in account only, CSRF-checked, a JSON
   body with the typed email, compared without case or surrounding spaces.
   An anonymous session gets 403 `NOT_SIGNED_IN`; a wrong email 400
   `CONFIRMATION_MISMATCH`.
2. Order: every session of the account is refused first
   (`SessionRepository.revoke_account`: a deleted mark kept in memory for
   the session lifetime, and the cached sessions dropped); then the account
   row, its history and its sessions are deleted in one transaction; then
   the run-history rows have `account_id` set to NULL. A session being read
   from disk during the delete is checked against the mark before it is
   cached, so it cannot come back.
3. A new account's id is `account_id_for(subject)`: HMAC-SHA256 of the
   Google subject under `QUORUM_TOKEN_SECRET`, as a UUID. The same Google
   account gets the same id after deletion, so the 24-hour spend recorded
   under it in the cost ledger still counts; the ledger is not touched. The
   id is not reversible without the secret.
4. A run still running when its account is deleted finishes; it joins no
   history, and its run-history row is written without the account.
5. The page: at the foot of the History panel, "Delete my account…", then a
   reminder with the typed email, then "Last check … Delete permanently".
   After deletion the browser has no session and reloads as anonymous.

## Rejected alternatives

- **A carried-spend row keyed on the hash, added into the cap check at
  sign-in:** it would change the money path (`try_record_cost_charge`); a
  derived id keeps the existing arithmetic unchanged.
- **Deleting the cost ledger's rows:** the owner kept the envelope.
- **Typing "DELETE":** the email is specific to the account and harder to
  type by habit (the session's choice).

## Consequences

- Deleting and signing in again within 24 hours keeps what the account
  already spent that day (pinned by
  `test_signing_in_again_keeps_the_days_spend`).
- Accounts created before this change keep their random id; if one is
  deleted and re-created, the envelope does not carry over (not migrated).
- If `QUORUM_TOKEN_SECRET` is rotated, an existing account keeps its id (it
  is looked up by subject); only a deleted and re-created account gets a new
  one, and with it a fresh envelope.
- The cost ledger keeps rows under the hashed id past the 24 hours; they no
  longer count once they are older than the window.
- The in-memory deleted mark is lost on restart; by then the account's
  session rows are gone from disk, so nothing can be restored.
