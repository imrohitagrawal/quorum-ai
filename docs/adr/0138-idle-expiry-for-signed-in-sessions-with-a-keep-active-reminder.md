# ADR-0138: Idle expiry for signed-in sessions, with a keep-active reminder

## Status

Accepted — 2026-09-28, board row W7, part 3 of 3, second of two pull
requests (the first is ADR-0137). The product owner decided this on
2026-09-25 at 08:56:57Z (CHG-021), their words: *"I agree with Idle expiry
for signed-in sessions post a reminder where User can decide to keep it
active or not."* The session's reading, recorded in CHG-021 and not
re-confirmed word for word: (b) a signed-in session expires after an idle
period, and before it does the page offers to keep it active. CHG-021:
*"The idle length and the rate-limit value are NOT the owner's: the
building session proposes them as settings."* Both values below were
**approved by the product owner on 2026-09-29 (CHG-026 c)**; they were PROPOSED
when this record was written. The reminder's wording and how it works are
the session's choice.
The two values (idle 120 minutes, warning 5 minutes) were approved by the product owner on 2026-09-29 (CHG-026).

## Context

Failure modes first: section (b) of
`docs/analysis/2026-09-28-w7-session-safety-failure-modes.md`. A read-only
map of the tree after ADR-0137 (#521) measured, with probes in a private
copy that are not committed (so inherited here):

| Fact | Measured |
|---|---|
| Every session already ends after 2 hours without a request (`auth.SESSION_TTL`), signed in or not | a row idle 2h00m05s is not restored; a fresh one is |
| `/v1/session` resets the clock AND replaces the CSRF token | a second tab's next protected request: 403 `CSRF_INVALID` |
| API calls reset the clock but never renew the cookie (`Max-Age` 7200) | `set-cookie` absent on an API response, present on `/ui` and `/v1/session` |
| The page makes no request on its own while idle, and never reads its deadline | 0 requests in 30 s idle after boot |
| After an idle expiry, the next page load mints a new anonymous session the per-address daily cap counts | one address: the 2nd idle expiry in a day gets 429, and sign-in cannot start |
| No route or decorator can be added freely | decorated functions under `src/product_app`: 55 of a cap of 55 |

So the expiry exists; what was missing is the warning, and a way to stay.

## Decision

1. **The signed-in idle length is a setting**, `signed_in_idle_minutes`
   (**120**, approved 2026-09-29, CHG-026; bounds 15 to 120). 120 is every session's lifetime
   today, so nobody is signed out sooner than before. It cannot be longer:
   every other rule that ages a session (restore, clean-up, the
   sign-out-everywhere cutoff, the deleted-account mark) uses the lifetime.
   A shorter value is the session's own idle limit (`_Session.idle_limit`),
   set when sign-in creates it and, when a session is restored from disk,
   from one lookup of whether its account row exists; a lookup that fails
   gets the shorter limit. No per-request lookup. Anonymous sessions keep
   the lifetime.
2. **The page asks, the server answers.** `GET /v1/session/idle` (not in the
   published API schema) returns `signed_in` and `idle_seconds_left`
   WITHOUT resetting the clock or replacing the CSRF token, never creates a
   session, renews the cookie for the full session lifetime (never less: API
   calls do not renew it, and a cookie cut to the time left was lost by
   anyone who kept working while the reminder showed, review measured), and
   writes the session's last use through, so its answer survives a restart.
   The page's timer only decides when to ask: one warning (`signed_in_idle_warning_minutes`,
   **5**, approved 2026-09-29, CHG-026; bounds 1 to 10) before the end it last heard of. Activity
   in another tab, a sleeping laptop or a clock that differs are therefore
   the server's to judge.
3. **The reminder** appears only on a signed-in page, on every view (moved
   out of the top bar, which the result and transcript views hide), and
   says, with minutes rounded up: "You will be signed out in about N
   minutes because nothing has happened on this page. Stay signed in?"
   It is announced politely and never moves focus.
   - **Stay signed in**: `POST /v1/session/keep-active` (CSRF, not in the
     published schema) resets the clock like any request, keeps the token,
     and renews the cookie.
   - **Sign out now**: the existing sign-out.
   - **Ignore it** ("or not"): the session ends as it does today; the page
     then says "You were signed out after N minutes with nothing happening
     on this page. Reload the page to sign in again." with a reload button.
4. **Nothing else changes**: no money value, no count, no stored data.

## Rejected alternatives

- **Using `/v1/session` to stay signed in**: it replaces the CSRF token and
  breaks every other open tab (measured).
- **A page-only countdown**: wrong whenever another tab was used, the laptop
  slept or the clocks differ; the page asks instead.
- **A signed-in idle length longer than 2 hours**: every other ageing rule
  would still cut it at 2 hours.
- **A shared idle clock per account**: the clock belongs to each session;
  staying signed in on one device does nothing for another (the session's
  reading, recorded).

## Consequences

- The reminder cannot be driven by any e2e lane (none can sign in); its
  logic is tested as pure functions under Node, its markup is pinned, its
  routes are tested through the real sign-in flow, and it was driven in a
  real browser for this pull request.
- The session's last use is written to disk at most every 300 seconds, so
  after a restart the server can report up to 5 minutes less than before.
  The status route writes it through each time it answers, so a check the
  page scheduled from that answer still finds the time it was told; the
  first check is timed from the page load, which already writes it. (The
  first build said "early, never late" without that write; review measured
  a scheduled check coming late by the lag.)
- Timers in a background tab can fire up to a minute late; the answer then
  comes from the server either way.
- **The lockout after expiry — decided by the owner on 2026-09-29 (CHG-026 a):
  the daily cap counts anonymous use only and must never stop anyone signing
  in; not yet built.** As written on 2026-09-28: a replacement session
  after an idle expiry still counts against the per-address daily cap of 2,
  so on a network that has used it up (the second idle expiry in a day, or
  a sign-out) the next page load is the cap page (429), and sign-in cannot
  start. That is how it works today (ADR-0130, ADR-0137); the reminder
  makes it rarer, not impossible. Changing who the cap counts is the
  owner's decision (ADR-0137 lists the same question for sign out
  everywhere).
- The two values: approved (CHG-026 c). The wording: the session's. One premise:
  idle expiry already applied to every session (2 hours) before this pull
  request, so at the proposed default it adds the reminder and the setting,
  not a shorter expiry; a shorter signed-in length is one setting away.
