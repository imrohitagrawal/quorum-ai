# ADR-0137: Sign out everywhere, sign-in events, and a limit on starting a sign-in

## Status

Accepted — 2026-09-28, board row W7, part 3 of 3, first of two pull requests
(the second is idle expiry, ADR-0138). The product owner decided these on
2026-09-25 at 08:56:57Z (CHG-021), their words: *"I agree with "Sign out
everywhere.", "Record sign-in events", "Rate-limit the sign-in start"."* The
session's reading, recorded in CHG-021 and not re-confirmed word for word:
(c) one action ends every session of the account; (d) sign-in events record
time and outcome, never tokens; (e) starting a sign-in is rate-limited.
CHG-021: *"The idle length and the rate-limit value are NOT the owner's: the
building session proposes them as settings."* Every value below is
**PROPOSED — AWAITING OWNER**. Splitting part 3 into two pull requests is
the session's choice, for size.

## Context

Failure modes first: `docs/analysis/2026-09-28-w7-session-safety-failure-modes.md`.
Two read-only maps of the tree at `a2801da` found (their probes are not
committed, so this is inherited): account deletion's refusal
(`revoke_account`) cannot be reused, because it refuses the account id for
two hours and a returning Google account keeps its id; deleting session rows
on disk alone signs nobody out, because the in-process cache decides; a
request already past its session check could still be estimated and
charged; and nothing limited `POST /v1/auth/google/start`.

## Decision

1. **Sign out everywhere is a cutoff time per account.** `POST
   /v1/auth/sign-out-everywhere` (not in the published API schema; the
   History panel calls it): a cookie session of a signed-in account, with its
   CSRF token; an anonymous session gets 403 `NOT_SIGNED_IN`, the local-only
   header path 403. It records `accounts.sessions_valid_after` and deletes
   the account's session rows created at or before it, in one transaction;
   drops the cached ones and refuses, from then on, any session of the
   account created at or before the cutoff (checked on every cache read and
   on every restore from disk); then deletes the rows again, for a row
   another device wrote back in between. "Everywhere" includes this browser:
   its cookie is cleared (the session's reading). If the store cannot record
   the cutoff: 503 `SIGN_OUT_EVERYWHERE_FAILED`, and nothing is refused.
2. **The next sign-in works.** The cutoff is a time, not a refusal of the
   account, so a session made after it, even with the same account id, is
   allowed, including after a restart.
3. **A request already past its session check** is re-checked when it asks
   for its spend key (`auth.spend_key_for`), so an estimate or a create after
   the sign-out is refused with 401 before it can be charged.
4. **It deletes nothing else**: no account, history, spend key, cost row or
   run-history link, and no deleted mark. Runs already running finish and are
   charged as usual; cancelling them is not in CHG-021 (recorded).
5. **Sign-in events** (`sign_in_events`, a guarded migration): the account
   id, the time and one of `signed_in`, `signed_out`,
   `signed_out_everywhere`. Never a code, `state`, verifier, token, Google
   subject, email, session id, address or user agent. Written only for an
   account row that exists, in the same transaction as the keep rules:
   the newest `sign_in_events_keep_count` (**PROPOSED 10**), none older than
   `sign_in_events_keep_days` (**PROPOSED 30**). Deleted with the account.
   A failed callback has no account to attribute; failures stay fixed reason
   codes in the log, never rows. The events are shown nowhere yet (CHG-021
   says record); the operator reads the table.
6. **Starting a sign-in is limited per visitor address** (`client_ip_of`,
   IPv6 by /64), in its own bucket: `sign_in_starts_per_address_burst`
   starts (**PROPOSED 5**), refilling `sign_in_starts_per_address_per_minute`
   a minute (**PROPOSED 1**). 429 `SIGN_IN_RATE_LIMITED` with `Retry-After`;
   the page says "Too many sign-in attempts. Try again in a few minutes."
   No exemption: the allow-list lifts only the two per-network session
   limits (CHG-022). Only the start is limited, never a callback.

## Rejected alternatives

- **Reusing account deletion's `revoke_account`**: it would refuse the next
  sign-in for two hours after a restart.
- **Deleting the rows only**: the cached sessions keep working.
- **Recording failed callbacks as rows**: nothing attributes them to an
  account, and anyone can send them, so the table could grow without bound.
- **A per-session start limit only**: a new session is one request away.

## Consequences

- A session made in the same instant as the cutoff is refused (`<=`); a
  wall clock stepping backwards between the cutoff and a new sign-in could
  refuse that sign-in's session once (the person signs in again).
- The start limit is in memory: a restart resets it (the machine stops when
  idle).
- Open for the owner: the four values above; whether runs already running
  should be cancelled; whether the events should be shown to the account.
