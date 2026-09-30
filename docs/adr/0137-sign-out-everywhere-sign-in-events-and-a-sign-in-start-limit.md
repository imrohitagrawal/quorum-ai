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
building session proposes them as settings."* Every value below was
**approved by the product owner on 2026-09-29 (CHG-026 c)**; it was PROPOSED when
this record was written. Splitting part 3 into two pull requests is
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
   header path 403. The cutoff is the moment of the request. The store
   raises `accounts.sessions_valid_after` to it (never lowers it) and deletes the
   account's session rows created at or before it, in one transaction; the
   cached ones are dropped (a dropped session is never written again), and
   any session of the account created at or before the cutoff is refused
   when restored from disk; then the store deletes the rows again with the
   same cutoff, for a row another device wrote back in between. "Everywhere"
   includes this browser: its cookie is cleared (the session's reading). If
   the store cannot record the cutoff: 503 `SIGN_OUT_EVERYWHERE_FAILED`, and
   nothing is refused; if the account was deleted meanwhile: 403
   `NOT_SIGNED_IN`.
2. **The next sign-in works.** The cutoff is a time, not a refusal of the
   account, so a session made after it, even with the same account id, is
   allowed, including after a restart.
3. **A request already past its session check** is checked again when it
   asks for its spend key (`auth.spend_key_for`), just BEFORE the key is
   read: an estimate or a create whose second check runs after the sign-out
   is refused with 401. This narrows the window, it does not close it: a
   create whose second check ran just before the sign-out still starts its
   run and is charged, even if its key is read after it (both measured by
   review), like a run already running. (Corrected 2026-09-28 by W7 part 3's
   second pull request: this said "whose key is read after the sign-out",
   which put the edge a few lines late.)
4. **It deletes nothing else**: no account, history, spend key, cost row or
   run-history link, and no deleted mark. Runs already running finish and are
   charged as usual; cancelling them is not in CHG-021 (recorded).
5. **Sign-in events** (`sign_in_events`, a guarded migration): the account
   id, the time and one of `signed_in`, `signed_out`,
   `signed_out_everywhere`. Never a code, `state`, verifier, token, Google
   subject, email, session id, address or user agent. Written only for an
   account row that exists, in the same transaction as the keep rules:
   the newest `sign_in_events_keep_count` (**10**, approved 2026-09-29, CHG-026), none older than
   `sign_in_events_keep_days` (**30**, approved 2026-09-29, CHG-026), applied at the account's
   next event, so an account with no later event keeps its rows until it is
   deleted. Deleted with the account.
   A failed callback has no account to attribute; failures stay fixed reason
   codes in the log, never rows. The events are shown nowhere yet (CHG-021
   says record); the operator reads the table.
6. **Starting a sign-in is limited per visitor address** (`client_ip_of`,
   IPv6 by /64), in its own bucket: `sign_in_starts_per_address_burst`
   starts (**5**, approved 2026-09-29, CHG-026), refilling `sign_in_starts_per_address_per_minute`
   a minute (**1**, approved 2026-09-29, CHG-026). The burst should be at most 5 times the rate
   (the limiter forgets a bucket after 5 idle minutes as if it had
   refilled); that rule is documented next to the settings, not enforced at
   startup (a check there would be one more decorated function over the
   mutation tool's recorded cap). 429 `SIGN_IN_RATE_LIMITED` with
   `Retry-After` (60 seconds at the proposed rate);
   the page says "Too many sign-in attempts. Try again in a few minutes."
   No exemption: the allow-list lifts only the two per-network session
   limits (CHG-022). Only the start is limited, never a callback.

## Rejected alternatives

- **Reusing account deletion's `revoke_account`**: it would refuse the next
  sign-in's session on any cache miss in the same process for two hours;
  only a restart lifts it.
- **Deleting the rows only**: the cached sessions keep working.
- **Recording failed callbacks as rows**: nothing attributes them to an
  account, and anyone can send them, so the table could grow without bound.
- **A per-session start limit only**: a new session is one request away on
  an allow-listed network or with an invite (elsewhere, 2 a day per address).

## Consequences

- A session made in the same instant as the cutoff is refused (`<=`). If the
  wall clock steps backwards, the cutoff can be earlier than sessions that
  already exist, and those survive (measured by review round 1); a new
  sign-in made while the clock is behind the cutoff works until its session
  is next restored from disk (a restart), which then refuses that session
  for good (it was made before the cutoff); a sign-in made after the clock
  passes the cutoff works (measured by the final review; this said "until
  the clock passes the cutoff" until W7 part 3's second pull request).
  Round 1 raised the cutoff to the newest existing
  session to close the first case; round 2 showed that raise had no bound
  (one future-dated session row locked the account out for good), and the
  owner approved returning to the simpler rule (2026-09-28, 12:14:14Z).
- Other devices of the account, reloading afterwards, get a fresh anonymous
  session under the daily new-session cap, so on a network that has used it
  up they see the cap page (429), as after a plain sign-out today
  (ADR-0130). Changing how those sessions are counted is its own decision.
- Behind one shared address (an allow-listed office included), sign-ins
  start 5 at once and then 1 a minute: the 30th person waits about 25
  minutes (review's arithmetic at the proposed values).
- The start limit is in memory: a restart resets it (the machine stops when
  idle).
- Decided by the owner on 2026-09-29 (CHG-026): the four values above
  (approved); a run already running when "sign out everywhere" is pressed
  (ask first — "Yes" stops the run and signs out everywhere, "No" signs out
  everywhere except the running session; not yet built); and the daily cap
  (it counts anonymous use only and must never stop sign-in; not yet built).
  Still open for the owner: whether the events should be shown to the
  account; and failed sign-ins, which are not stored as rows (Decision 5),
  where the proposal the owner agreed to said "time and success or failure".
