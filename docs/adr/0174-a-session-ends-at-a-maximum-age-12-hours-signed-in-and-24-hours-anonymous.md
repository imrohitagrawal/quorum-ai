# ADR-0174: A session ends at a maximum age: 12 hours signed in, 24 hours anonymous

## Status

Accepted — 2026-10-19, board row W87, the first of its three pull requests (W87-1). Codex split W87
into three: this maximum age, then a recent sign-in before deleting an account (W87-2), then an
operator command to end sessions and the record of why sign-in is single-factor (W87-3). W87 stays
open until W87-3 lands. The values and words this ADR builds on are the owner's (CHG-056 (c),
CHG-063 (f)(2), CHG-066, CHG-069, CHG-070); the rest is the session's design.

The product owner chose the values and the words: 12 hours signed in and 24 hours anonymous
(CHG-056 (c)); the 12-hour note after the end (CHG-063 (f)(2)); a warning 5 minutes before the
12 hours end and a refusal of a run in a signed-in session's last 12 minutes, with their words
(CHG-066 (a), (b)); new words for an anonymous refusal, and no early renewal of an anonymous session
(CHG-069); the card's title, keeping the typed question across "Sign in again", the text with
sign-in off, and the countdown (CHG-070). Everything else below is the session's design.

The failure modes were listed before any code (`docs/analysis/2026-10-19-w87-1-max-age-failure-modes.md`
holds the ones this pull request closes or records). Codex reviewed the plan before any code
(ADR-0168, decision 7): twice for the whole of W87 and twice for W87-1. Its reviews are kept outside
the repository; none has a committed record. W87-1's first review found three open points and one
missing test pin; its second confirmed all four closed and asked that the overshoot below name the
deadline it assumes, which it now does. Codex did not review the code.

## Context

Before W87-1 a session ended only when it had been idle too long: `_Session.is_expired` compared
now with the last use, and the durable read and purge did the same. Every request that passes
`require_session` renews the last use. So a session that kept being used never ended, signed in or
anonymous (ASVS V7.3.2; `docs/analysis/2026-10-17-w82-security-baseline.md`, row W87).

Facts the design rests on, read on `main` at `8463a72` and re-checked where marked:
- Sign-in rotates the session: a new id, a new anti-forgery token and a new `created_at`
  (`issue_signed_in_session`). So a signed-in session's `created_at` is the moment its Google sign-in
  finished, which matches the owner's words "since you signed in".
- `created_at` is written to the durable row and read back on a restart.
- The per-network mint count looks back over a rolling 24 hours and counts a mint at exactly
  24 hours; the mint is recorded before the session is created (MEASURED by the session's probe on
  that tree: counted at t0 + 24 h, not at t0 + 24 h + 1 µs).
- The run deadline is `quorum_run_deadline_seconds`, 720 by default, and may be set from just above
  0 up to 3,600 (`config.py`, `RUN_DEADLINE_MAX_SECONDS`; `tests/integration/test_run_deadline.py`
  accepts 3,600).

## Measured

| What | How | Result |
|---|---|---|
| The new tests fail without the fix | the test designer's red run on `19647a9` with only the test files added (log kept outside the repository) | pytest, the six new files: `9 failed, 7 passed, 37 errors in 10.92s`; the errors are the missing clock `auth._now`. With only that clock added and no behaviour: `40 failed, 10 passed in 10.91s`. The new signed-in spec: `4 failed` |
| The CHG-070 tests fail without the fix | the same, for the tests added after CHG-070 | pytest: `3 failed, 10 deselected, 2 errors in 0.24s`; the signed-in spec: `5 failed`, `1 passed`; the sign-in-off spec on the main lane: `1 failed` |
| The new tests with the fix | the builder's runs on the build commit | the designer's pytest files: `56 passed in 11.16s`; `make quality`: `7631 passed, 37 skipped`; `make api-contract`: `54 passed`, `EXIT=0` |
| The e2e lanes | the four lanes the change touches, run as `.github/workflows/e2e.yml` runs them with the AGENTS.md rule 13 flags | `signed-in: 31 tests executed (floor 31), 0 skipped.` (33 and floor 33 after review round 1); `workspace: 52 tests executed (floor 52), 0 skipped.`; `invariants: 459 tests executed (floor 457), 0 skipped.`; `axe-parity: 133 tests executed (floor 117), 0 skipped.` |
| The visual baselines cannot move | `outerHTML` of the result and transcript views on `goldenCompletedResp()`, before and after | `result: byte-identical (27187 bytes)`, `transcript: byte-identical (17858 bytes)` |

## Decision

1. **Two new limits, never `SESSION_TTL`.** `SIGNED_IN_MAX_AGE` is 12 hours and `ANONYMOUS_MAX_AGE`
   is 24 hours (`auth.py`). `SESSION_TTL` stays the 2-hour idle lifetime that the restore, the
   purge, the cookie and the deleted-account mark already mean by it (ADR-0138, decision 1).
2. **Where each clock starts.** A signed-in session's 12 hours start at the sign-in rotation; an
   anonymous session's 24 hours start at its mint. An anonymous session that signs in becomes a new
   session with a fresh 12 hours; its anonymous age is not carried over, because the new session
   needed a Google sign-in. Signing in again starts a fresh 12 hours too.
3. **Strict boundaries.** `is_expired` is "idle too long OR `now - created_at > max_age`". A session
   is alive at exactly 12 hours (or 24) and ended 1 microsecond later. The session code reads one
   clock, `auth._now()`, so tests stand it at an exact instant. Sign out everywhere takes its cutoff
   from the same clock.
4. **The mint count, stated narrowly.** CHG-056 (c) records the session's reasoning that an ending
   anonymous session never uses up one of the network's 2 a day. What holds, and is tested, is
   narrower: a session ended by its 24-hour limit has always aged out of the count, because its mint
   came no later than its start and the count looks back exactly 24 hours. An anonymous session
   that ends sooner, by idle time or sign-out, still holds its slot until 24 hours after its mint,
   and its replacement takes a slot (as ADR-0138 and ADR-0139 already record).
5. **No exemption.** Invite-link sessions, sessions of an allow-listed visitor and sign-in-only
   sessions (ADR-0139) end at 24 hours like any anonymous session.
6. **The durable store applies the same bound.** The read refuses a row created more than 24 hours
   ago, and the purge deletes exactly those rows. A row whose `created_at` is in the future is
   refused and purged, as a future `last_used_at` already was, so a stepped clock or an edited file
   cannot make a session that never ends. A restored row gets 12 hours unless one lookup says its
   account is anonymous; a lookup that fails gives 12 hours, the closed side.
7. **The reported end is the nearer one.** Every issue and resume path reports
   `min(idle end, created_at + max_age)`. `/v1/session/idle` answers the smaller time left and
   `ends_because`, `"idle"` or `"max_age"`. The cookie's own `Max-Age` is unchanged; the server
   decides.
8. **A failed touch is refused.** `require_session` uses what the touch returns, so a session that
   passes its lookup and reaches its limit before its touch gets 401. The touch and the CSRF
   rotation check the limits again, under the lock, with the same clock reading they record as the
   last use, and drop a session that has ended (review round 1, Codex: a clock step between the
   lookup and the recorded use served a request one second after the 12 hours).
9. **The 401 says why only when it knows.** It carries `SESSION_MAX_AGE` and the owner's sentence
   (CHG-063 (f)(2)) only when the durable row still exists, its account did not end its sessions
   after the row started and that cutoff could be read, a lookup that worked says the account is
   signed in, the 12 hours have passed, and the idle end did not come first. Every other end (no
   store, no row, a revoked session, an unreadable cutoff, an anonymous row, a failed lookup, an idle
   end) keeps `SESSION_EXPIRED`, so nobody is told "12 hours" when that is not why. The idle end is
   taken from the freshest last use known: the row's, or the one the process held when it dropped
   the ended session, which the 300-second touch throttle can leave newer (review round 1).
10. **The warning.** The signed-in reminder carries `data-max-age-seconds-left`, and the page
    schedules its first check from the nearer end. When `ends_because` is `"max_age"` it shows
    CHG-066 (a)'s sentence, with the minutes counted down as the idle reminder rounds them
    (CHG-070 (d)): "about 5 minutes", "about 3 minutes", then "about a minute". It asks the server
    again every minute and is announced politely, as the idle reminder is. "Stay signed in" is
    hidden, because it cannot extend the 12 hours; "Sign out now" stays. After the end the page
    shows the 12-hour sentence and "Reload the page".
11. **The late-run refusal.** The estimate and the run creation refuse with 409 `SESSION_ENDS_SOON`
    when less than `LATE_RUN_REFUSAL_SECONDS` (720) are left before the maximum age: 720 seconds may
    run, 719 may not. The check comes after the anti-forgery check and before anything is recorded
    or charged. The run creation checks again just before the run is created and its spend
    reserved, so time spent validating and estimating cannot carry a run across the boundary, and a
    session that ended meanwhile gets its 401 (review round 1, Codex). The words are the owner's:
    CHG-066 (b) for a signed-in session, CHG-069 for an anonymous one on a page that offers sign-in
    (sign-in on, and this host is the sign-in host), CHG-070 (c) otherwise, including the fly.dev
    host (review round 1); the server picks the text. The card is titled "Your session ends soon"
    (CHG-070 (a)). A signed-in page offers "Sign in again", which keeps the typed question in this tab
    (`sessionStorage`), saved with the page's account id, and puts it back once after the sign-in
    only when the same account comes back; another account gets an empty box (CHG-070 (b); review
    round 1). An anonymous page offers the top bar's "Sign in with Google" only where it offers
    sign-in at all. The 409 is declared in the API description for both routes.
12. **No early renewal of an anonymous session (CHG-069).** `/ui` and `/v1/session` resume a live
    session as before, however little of its 24 hours is left.
13. **How many sessions one account may hold.** There is no count: each Google sign-in makes one
    more session for the account, and each ends 12 hours after that sign-in, or sooner when idle,
    signed out or signed out everywhere. This is the session's design, not an owner decision
    (ASVS V7.1.2). No test would fail if a count were added, so that item is CODE-ONLY.

## Consequences

- A signed-in visitor signs in again every 12 hours, however busy; one click when still signed in to
  Google (CHG-056 (c)).
- When a signed-in session ends at 12 hours and the page reloads, `/ui` mints an anonymous session
  that counts against the network's 2 a day. On a network that has used both, that is the
  sign-in-only page, which still offers sign-in (ADR-0139). This is a cost of the design, not an
  owner decision.
- An anonymous visitor in the last 12 minutes of 24 hours cannot run a question until they sign in
  or the session ends; reaching 24 hours needs a request at least every 2 hours for a day.
- The signed-in e2e lane's floor rises from 25 to 31 and the workspace lane's from 51 to 52, by
  the new tests only.
- **Known limit: a run can still end after its session.** The refusal guarantees 720 seconds of
  session at admission, not that the run ends in time. The run deadline is checked at three points
  in the run, and a stage started before it runs to its own timeout. At today's 720-second deadline
  that is up to about 9 minutes past the deadline, by the session's reading of the code (not run).
  If `quorum_run_deadline_seconds` is set above 720, up to its 3,600 maximum, a run admitted with
  720 seconds left may run for the deadline minus 720 seconds after the session ends, before any
  stage overshoot: 48 minutes at 3,600. That one result is then lost to an anonymous visitor. For a
  signed-in visitor the run belongs to the account, but History keeps no answers and a run has no
  address of its own, so the page offers no way back to it after signing in again (the journey
  tester, by reading; UNVERIFIED by running). The overshoot past the deadline is an NFR-004 concern
  of its own and is not on the board yet.
- **Known limit, to be fixed in W87-2: signing in across the end.** The sign-in callback refuses a return
  whose original session has meanwhile ended (`google_signin.py`, the `no_session` failure), so a
  visitor who presses "Sign in again" seconds before the 12 hours end can come back to
  `sign_in=failed` (Codex, by executing the callback). They then sign in once more from the
  anonymous page. W87-2, the next pull request, adds the recovery path.
- **Known limit: the reason needs the durable row.** With no session store (an unwritable volume),
  or once the purge has deleted the row, the 401 is the generic expiry, never the 12-hour sentence
  (decision 9). That is the chosen side: no guessing.
- A wall-clock jump forward ends sessions early, and one back extends them. A start in the far future
  is refused (decision 6); nothing else is done about clock jumps.

## Rejected alternatives

- **Renew an anonymous session early, in its last 12 minutes (CHG-069).** It would let the
  approved "reload the page" text start a fresh session, but a stolen anonymous cookie could then be
  kept alive past 24 hours by renewing it, and Codex's plan review showed that a renewal changes the
  account, so a run accepted just before it, or a finished result not yet read, is lost. The owner
  chose to refuse with new words instead.
- **Read the adjustable run deadline as the refusal window.** The texts the owner chose (CHG-066 (b),
  CHG-069, CHG-070 (c)) say "less than 12 minutes". With the refusal reading a `quorum_run_deadline_seconds` of 3,600, refusals would
  start with 3,600 seconds left, so the text would be false (raised by Codex; this sentence said
  "1,800 seconds" until review round 1 corrected it). The window is its own constant, 720, pinned by
  literal; the cost is the overshoot recorded above.
- **Reuse `SESSION_TTL` for the maximum age.** The restore, the purge, the cookie and the
  deleted-account mark already use it to mean the 2-hour idle lifetime (decision 1).
- **Count the 12 hours from the account's last sign-in (`accounts.last_sign_in_at`).** It is per
  account, stamped by a sign-in on any device, so one device signing in would restart the clock of
  every other device.
- **Check the age only in `is_expired`.** A restart restores the row through `fetch`, so the read
  must refuse an old row too (decision 6).
- **An inclusive end (`>=`).** It would end the session at the very instant the count still holds
  its mint, which breaks decision 4's argument at that instant.
- **Tell every ended session "12 hours".** An idle end, or an end the server cannot explain, would
  be told something false (decision 9).
- **Keep "Stay signed in" on the 12-hour warning.** Pressing it cannot extend the 12 hours, and the
  warning would come back.
- **No warning before the 12 hours end.** The owner chose a warning (CHG-066 (a)).
- **Cap the cookie's `Max-Age` at the time left.** Optional; the server already refuses. Not built.

## Related

- Code: `src/product_app/auth.py` (`SIGNED_IN_MAX_AGE`, `ANONYMOUS_MAX_AGE`,
  `LATE_RUN_REFUSAL_SECONDS`, `_now`, `_Session.is_expired`, `SessionRepository.end_reason`,
  `refuse_if_session_ends_soon`, `session_ended`), `src/product_app/session_store.py` (`fetch`,
  `purge_expired`), `src/product_app/google_signin.py` (the idle status route),
  `src/product_app/query_runs.py` (`_refuse_late_run`), `src/product_app/main.py` (the reminder
  markup), `src/product_app/static/app.js` (`maxAgeReminderText`, `signInAgainKeepingQuestion`,
  `restoreLateRunQuestion`).
- Tests: `tests/unit/test_session_max_age.py`, `tests/security/test_session_max_age_durable.py`,
  `tests/integration/test_session_max_age_routes.py`, `tests/integration/test_late_run_refusal.py`,
  `tests/unit/test_max_age_reminder_text.py`, `tests/unit/test_age_sessions_is_test_only.py`,
  `e2e/tests/signed-in/session-max-age.spec.ts`, `e2e/tests/api-mocking/late-run-sign-in-off.spec.ts`.
- Amends ADR-0138 (decisions 1 and 3) and ADR-0139. `docs/41-security-controls.md` SC-14 and SC-102.
- CHG-056 (c), CHG-060 (the detail held back until the fix shipped), CHG-063 (f)(2), CHG-066,
  CHG-069, CHG-070.
