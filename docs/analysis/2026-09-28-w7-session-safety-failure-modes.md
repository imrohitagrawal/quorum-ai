# W7, part 3 — session safety: failure modes first

Written before the code (AGENTS rule 16e), for board row W7, part 3 of 3
(CHG-021 b to e). Two read-only maps of the tree at `a2801da` (2026-09-28)
fed it; their probes ran in private `git archive` copies and are not
committed, so the facts below marked *measured by the map* are inherited.

Part 3 ships as two pull requests, the session's split for size:

- **A** (this page's first half): (c) sign out everywhere, (d) sign-in
  events, (e) a rate limit on starting a sign-in. ADR-0137.
- **B**: (b) idle expiry for signed-in sessions, with a keep-active reminder.
  ADR-0138. Its failure modes are added here before it is built.

## What the owner decided (CHG-021, 2026-09-25, 08:56:57Z)

Their words: *"I agree with Idle expiry for signed-in sessions post a
reminder where User can decide to keep it active or not. I agree with "Sign
out everywhere.", "Record sign-in events", "Rate-limit the sign-in start"."*
The session's reading, recorded in CHG-021 and not re-confirmed word for
word: (c) one action ends every session of the account; (d) sign-in events
record time and outcome, never tokens; (e) starting a sign-in is
rate-limited. *"The idle length and the rate-limit value are NOT the
owner's: the building session proposes them as settings."* So every value
below ships as a setting, **PROPOSED — AWAITING OWNER**.

## Facts that shape the design (measured by the map)

- **Account deletion's refusal cannot be reused.** `revoke_account` marks the
  whole account id refused for the session lifetime, and a returning Google
  account keeps its id: after it, a new sign-in's session did not survive a
  cold cache.
- **Deleting rows on disk alone signs nobody out.** The in-process cache
  decides; another device's request still returned 200.
- **A request already past the session check keeps going.** A create that
  passed `require_session` before a revoke still got its spend key and
  could charge (bounded by one active run per account and the daily cap).
- **Nothing rate-limits `POST /v1/auth/google/start`**; each start allows at
  most one bounded token exchange with Google, and pending sign-ins are
  capped only by a 10,000-entry backstop.

## (c) Sign out everywhere

C1. **Other devices, including requests in flight** (the race promised to
    the owner on 2026-09-25, 11:30:42Z, in reply to their question about
    race conditions). Answer: a per-account cutoff time, the moment of the request (a
    wall clock stepping backwards is recorded in ADR-0137, not handled).
    The cached sessions of the
    account are dropped (a dropped session is never written again), and a
    session created at or before the cutoff is refused when restored from
    disk (`accounts.sessions_valid_after`, and the in-memory cutoff under the
    lock). The rows go in the same transaction that records the cutoff, then
    are deleted again with the same cutoff (a row written back in between).
    A request already past the session check is checked again when it asks
    for its spend key, just before the key is read, so an estimate or a
    create whose second check runs after the sign-out is refused (401); one
    whose second check ran just before still runs and is charged (review
    measured it; recorded in ADR-0137). Tests: another device's request
    racing each step; a session restored from disk after; 10 concurrent
    requests of another device during the sign-out, all 401 after and no
    rows left.
C2. **The next sign-in must work.** Unlike deletion's refusal, the cutoff is
    a time: a session created after it (a new sign-in, even with the same
    account id) is allowed. Test: sign out everywhere, sign in again, clear
    the cache; the new session restores.
C3. **This device.** "Everywhere" includes it (the session's reading): its
    session is refused and its cookie cleared.
C4. **Who may call it.** POST, CSRF, a cookie session of a signed-in
    account; an anonymous session gets 403 `NOT_SIGNED_IN`; the local-only
    header path is refused. Test: nothing is refused on a refusal (positive
    partner: the same account's sessions still resolve).
C5. **What it must not do.** It deletes no history, no account, no spend
    key, no cost row, no run-history link, and sets no deleted mark. Test:
    all unchanged afterwards.
C6. **Runs already running** on other devices finish and are charged as
    usual (their charge was taken when they started); their pages see 401.
    Cancelling them is not in CHG-021 (recorded, not built).
C7. **The store cannot record the cutoff** (an unwritable volume): 503, and
    nothing is refused. Test.

## (d) Sign-in events

D1. **Privacy.** A row holds the account id, the time and an outcome from a
    closed list (`signed_in`, `signed_out`, `signed_out_everywhere`). Never
    the code, `state`, the verifier, a token, the Google subject, the email,
    the session id, an IP address or a user agent. Test: every column of
    every row after a full sign-in holds none of the code, the state, the
    PKCE challenge, the subject, the email, the session id or the client
    address (positive partner: the dump does find them in a planted row);
    the other two outcomes are fixed strings written by the same function.
D2. **Growth and forgery.** Only server code writes rows; no route accepts
    an event. A failed callback has no account to attribute, so failures
    stay what they are today: fixed reason codes in the log, never rows.
    Keep rules like history: the newest `sign_in_events_keep_count` rows,
    none older than `sign_in_events_keep_days` (PROPOSED 10 and 30), applied
    at the account's next event.
    Deleting the account deletes its events (same transaction). A write for
    an account with no row stores nothing.
D3. **Where they are shown.** Nowhere yet; CHG-021 says record. The
    operator reads the table. (Recorded.)

## (e) Rate limit on starting a sign-in

E1. **Key.** The visitor's address as the session limits count it
    (`client_ip_of`, IPv6 by /64). A per-session key alone is bypassed by
    new sessions; those are capped per address per day anyway.
E2. **Exemptions.** None: CHG-022 lifts only the two per-network session
    limits for the allow-list, and an invite lifts only the daily cap.
E3. **Separate from the per-minute session limit**: its own bucket and its
    own code, `SIGN_IN_RATE_LIMITED`, so using one up leaves the other.
E4. **What the page says.** 429 with `Retry-After`; the page says "Too many
    sign-in attempts. Try again in a few minutes." instead of "try again".
E5. **Never blocks a sign-in already started**: only the start is limited,
    not the callback.
E6. **Value**: PROPOSED 5 starts at once, refilling one a minute, per
    address. The session's judgement; no external standard was found.

## (b) Idle expiry for signed-in sessions, with a keep-active reminder

Pull request B, ADR-0138. Written before the code. A read-only map of the
tree after pull request A (#521) fed it; its probes ran in a private
`git archive` copy and are not committed, so facts marked *measured by the
map* are inherited.

### What is already there (measured by the map)

- **Every session already expires after 2 hours idle**: `auth.SESSION_TTL`,
  checked against `last_used_at` in memory and on restore from disk. Signed
  in or not, the same rule; no setting. So (b) is mostly the reminder: the
  expiry exists, the warning does not.
- Each request through `require_session` resets the idle clock; `/v1/session`
  resets it too and **replaces the CSRF token**, which makes every other open
  tab's next protected request fail with 403 `CSRF_INVALID`.
- The session cookie's own lifetime (`Max-Age` = 2 hours) is renewed only by
  `/ui`, `/v1/session` and the sign-in callback, never by an API call.
- The page makes no request on its own while idle (the run poll runs only
  during a run and resets the clock every 750 ms). It learns its deadline
  once, at start, and never reads it.
- After expiry, the next page load mints a new anonymous session that the
  per-address daily cap counts: the second idle expiry in a day gives the
  whole address a 429, and sign-in cannot start. Sign-out and sign out
  everywhere lead to the same place (ADR-0130, ADR-0137).

### Failure modes

B1. **A reminder that lies.** The page's own timer does not know about
    activity in another tab of the same browser (same session), about a
    computer that slept, or about a server clock that differs. Answer: the
    timer only decides when to ASK; before showing the reminder the page
    asks the server how long is left, and shows it only if the server says
    the end is near. Test: activity after the page's last request moves the
    answer; a status request does not.
B2. **The status request keeps the session alive.** If asking "how long is
    left" reset the clock, an open tab would never expire. Answer: a status
    route that reads without touching, and without replacing the CSRF token.
    Test: two status requests; `last_used_at` unchanged.
B3. **Keep-active breaks other tabs.** Reusing `/v1/session` would replace
    the CSRF token. Answer: a keep-active route that touches the session and
    renews the cookie, and keeps the token. Test: a second tab's token still
    works after keep-active.
B4. **The cookie dies before the session.** An active user whose activity
    is only API calls loses the cookie 2 hours after the page loaded. Answer:
    keep-active and the status route renew the cookie for the full 2-hour
    lifetime, never less, and the page asks at least once per idle length,
    so an open page renews its cookie before it runs out. (The first build
    cut the cookie to the time left; review showed that someone working on
    while the reminder showed then lost the cookie and was told they had
    been idle.) Tests: the cookie's `Max-Age` is the lifetime even with
    minutes left; activity while the reminder shows keeps the cookie.
B5. **A reminder for an anonymous session.** The owner's words name signed-in
    sessions. Answer: only a signed-in page runs the timer; the status route
    says whether the session is signed in. Tests: an anonymous page has no
    reminder element (markup), and the status route says `signed_in: false`;
    that the page script starts no timer without the element was checked in
    a browser, not by a test.
B6. **A setting that cannot work.** A signed-in idle length longer than the
    2-hour session lifetime would be silently cut to 2 hours by every other
    rule that uses `SESSION_TTL` (restore, clean-up, the sign-out-everywhere
    cutoff, the deleted-account mark). Answer: the setting is bounded above
    by 120 minutes. A shorter value is the session's own idle limit, set
    when sign-in creates it and, on a restore from disk, from one lookup of
    whether its account row exists (a lookup that fails applies the shorter
    limit, the closed side); no per-request lookup. Test at the boundary, in
    memory and on restore.
B7. **"Or not."** The owner said the user decides. Answer: the reminder
    offers "Stay signed in" and "Sign out now"; ignoring it lets the session
    expire as today. After expiry the page says so plainly and offers to
    reload, instead of the generic "Session expired" banner. Tests: each
    button's action (`idleKeepActive`, `idleSignOutNow`, under Node) and the
    markup; the click listeners that call them were driven in a browser.
B8. **Accessibility.** The reminder appears without a user action. Answer:
    a region announced politely (`aria-live="polite"`), which never moves
    focus while the user is typing, with buttons reachable by keyboard. The
    page has no dialog pattern today (the map found none), so none is added.
B9. **Other devices.** The idle clock belongs to each session, not to the
    account; keep-active on one device does nothing for another. That is
    the session's reading and is recorded, not built.
B10. **Expiry mid-run.** The run poll resets the clock, so a tab showing a
    running query does not expire. Test: none needed beyond the existing
    poll; recorded.
B11. **Restart.** The disk copy of `last_used_at` can lag the memory copy by
    up to 300 seconds (the throttled write). The first build called that
    "early, never late"; review showed a check the page had scheduled from an
    earlier answer then came late, by up to the lag. Answer: the status route
    writes the last use through each time it answers, so a check scheduled
    from its answer finds at least the time it was told; the first check is
    timed from the page load, which already writes it (the CSRF rotation).
    Test: a lagging disk copy, a status answer, a restart: no time lost
    (partner: without the status answer, the restart takes the lag off).
B12. **What this does NOT change**: who the daily new-session cap counts.
    A replacement session after an idle expiry still counts; changing that
    is an owner decision (ADR-0137 lists it as open), raised with the owner
    in this pull request, not built.

### Values — PROPOSED, AWAITING OWNER

`signed_in_idle_minutes` 120 (today's lifetime, so no one is signed out
sooner than today), bounded 15 to 120; `signed_in_idle_warning_minutes` 5.
CHG-021 records: *"The idle length and the rate-limit value are NOT the
owner's: the building session proposes them as settings."*
