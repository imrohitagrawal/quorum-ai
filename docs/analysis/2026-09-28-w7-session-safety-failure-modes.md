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

C1. **Other devices, including requests in flight** (the owner's required
    test). Answer: a per-account cutoff time, the later of now and the
    newest existing session of the account. The cached sessions of the
    account are dropped (a dropped session is never written again), and a
    session created at or before the cutoff is refused when restored from
    disk (`accounts.sessions_valid_after`, and the in-memory cutoff under the
    lock). The rows go in the same transaction that records the cutoff, then
    are deleted again with the same cutoff (a row written back in between).
    A request already past the session check is re-checked when it asks for
    its spend key, so an estimate or a create whose key is read after the
    sign-out is refused (401); one whose key was read just before still runs
    and is charged (review round 1 measured it; recorded in ADR-0137). Tests: another device's request
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
