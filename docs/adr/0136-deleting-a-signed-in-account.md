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

Two further owner decisions, both on 2026-09-27, each choosing an option the
session had drafted:

- 12:02:35Z (CHG-024): accept a one-time envelope reset for accounts created
  before this change.
- 15:05:02Z (CHG-025): after review round 2 found blockers the first design
  could not close, re-plan with a separate spend key (Decision 3, and the
  first rejected alternative). The chosen option ended with *"Also ends the
  old-account reset (CHG-024)."*, so that reset no longer happens.

The session's own choices are marked below. Among them: typing the account's
own email as the typed confirmation; the three steps' order and words; one
run at a time per account id rather than per spend key; refusing, not
degrading, a request whose spend key cannot be read.

## Context

Reported on `main` by the read-only map before building (2026-09-26; its
probes are not committed, so these are inherited, not re-measured here):
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
   `CONFIRMATION_MISMATCH`. A request on the local-only `X-Account-Id` path
   (no cookie) is refused as not signed in.
2. Order: the delete is marked as under way
   (`SessionRepository.begin_deletion`; it refuses nothing on its own); the
   account row, its history and its sessions are deleted in one transaction,
   and the account's spend key is kept for 24 hours under the keyed hash of
   its Google subject (the `spend_key_carry` table, same transaction); only
   then is every session of the account refused
   (`SessionRepository.revoke_account`: a deleted mark kept in memory for the
   session lifetime, and the cached sessions dropped), any session row another
   device wrote back just before that deleted again, its carry-over links (to
   or from it) dropped, and its run-history rows given a NULL `account_id`. A session read from disk during the delete is refused as it
   is cached, or dropped by the refusal. If the store refuses the delete (503
   `DELETION_FAILED`), nothing has been changed: other devices stay signed
   in and "try again" is true.
3. **Each account life has a random id; the spend envelope has its own key.**
   A new account row gets a random `account_id` (as ADR-0130 had) and a
   `spend_key`: HMAC-SHA256 of the Google subject under
   `QUORUM_TOKEN_SECRET`, as a UUID. An account created before this change
   keeps its own id as its spend key (a guarded migration adds the column and
   backfills it), so no number moves at deploy. An anonymous session's spend
   key is its account id. The estimate and create routes read the key once
   per request (`auth.spend_key_for`) and the run stores it
   (`QueryRun.spend_key`); the per-account rails (the daily cap, the
   in-memory running total, the charge, its void and its reconciliation, the
   judge's pre-flight) all use that one key. The confirmation token and the
   estimate-time audit events (preview, blocked, confirmation required) stay
   on the account id; the charge step's events (the opening charge, a
   ceiling degrade) carry the spend key. A spend key that cannot be read
   refuses the request (503 `SPEND_KEY_UNAVAILABLE`), for anonymous visitors
   too while the sessions database cannot be read; a request of a deleted
   account is refused (401), and so is one whose lookup returned the id while
   a delete of that id is under way. A lookup that returned a different key
   read the row, so for an account created after this change a delete that
   fails refuses no other device; an account created before it (its key IS
   its id) is refused for the length of that delete's transaction, and works
   again straight after. Deleting and signing in again gets
   a NEW id and the SAME spend key, from the 24-hour pointer, so the day's
   spend still counts, for an account of either age.
4. A run still running when its account is deleted finishes. Its history
   write finds no account row (checked in the write's own transaction) and
   stores nothing; its run-history row is written without the account (the
   deleted mark is checked after the row is written). No later account can
   have its id.
5. One run at a time is per account id (the session's choice): after
   deleting and signing in again, the new life can start a run while an old
   one finishes. The spend rails still bound both, since each charge is
   tested and recorded atomically under the shared spend key.
6. The page: at the foot of the History panel, "Delete my account…", then a
   reminder with the typed email, then "Last check … Delete permanently".
   Closing the panel starts the steps over. After deletion the browser has
   no session and reloads as anonymous.

## Rejected alternatives

- **Deriving the account id itself from the subject** (this pull request's
  first design): the id came back after deletion, so everything keyed on it
  (a run, a session restored from disk, a history write, a carry-over link)
  treated the time before the deletion as the new account's. Two review
  rounds found four such leaks, each a check with a race gap; two were added
  by fixes for the others. Replaced at the owner's choice (CHG-025).
- **A carried-spend row added into the cap check at sign-in:** a second
  number in the money arithmetic; the spend key changes only which key the
  existing arithmetic reads.
- **Deleting the cost ledger's rows:** the owner kept the envelope.
- **Typing "DELETE":** the email is specific to the account and harder to
  type by habit (the session's choice).

## Consequences

- Deleting and signing in again within 24 hours keeps what the person
  already spent that day, through the estimate and the create routes
  (`tests/integration/test_spend_key.py`).
- An account created before this change keeps its own id as its spend key,
  so no number moves at deploy, and deleting and re-creating it keeps its
  day through the pointer. The one-time reset the owner accepted on
  2026-09-27 at 12:02:35Z (CHG-024) therefore no longer happens, as the
  option chosen at 15:05:02Z (CHG-025) said.
- The pointer holds the keyed hash of the Google subject and the spend key
  for 24 hours after a deletion (`SPEND_KEY_CARRY`); after that it is not
  used, and it is removed at the next open, sign-in or deletion.
- The page says "try again" for a store failure or a dropped connection;
  everything else, including a stale token, an expired session, a missing
  cookie and a proxy error with no code, is told to reload first
  (`accountDeleteMessage`, pinned under Node).
- The spend key is stored, never recomputed, so rotating
  `QUORUM_TOKEN_SECRET` leaves live accounts' envelopes intact; only an
  account deleted before a rotation and re-created after it starts fresh
  (the pointer is found by the hash under the current secret).
- Review measured one state, reachable only by a fault, that meters a
  signed-in account as its id: the spend-key column present without its
  migration marker. Sign-in is then off, but a session already signed in
  would be metered as its id.
- Cost-ledger rows keep the spend key after the 24 hours (nothing in `src/`
  deletes cost rows), and a run degraded to simulation at the global
  ceiling sends it to Sentry as `account_id` (the charge step's call to
  `CostEstimationService.record_guardrail_event`).
  How long either may keep it is open for the owner (`docs/48`).
- The in-memory deleted mark is lost on restart; by then the account's
  session rows are gone from disk, and a sign-in racing the delete re-checks
  the account row and revokes its own session. Lapsed marks are dropped at
  the next deletion.
- No automated browser test drives the three steps; no end-to-end suite
  here can sign in. The server check (the typed email) is tested; the
  reminder and last-check steps were checked by hand in Chromium and pinned
  as markup.
