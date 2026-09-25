# ADR-0130: Sign in with Google, and sign out

## Status

Accepted — 2026-09-25, W7's first pull request of two. The product owner
decided W7 on 2026-09-24 (CHG-012 D7, their words): *"the purpose of sig-in is
to preserve the history of the searches from a account. THis can be limited to
last 5 searches for example if we face issue in storage."* and *"the whole
purpose will be forfeited if we delete the history on every sign-out! but yes
on account deletion we should remove"*. The session's design was summarised
back to the owner and not contested (CHG-012 D7): keep the last 5 runs per
account and drop runs older than 30 days; a summary row per run; nothing
deleted on sign-out; account deletion as a typed-confirmation action; the
24-hour spend envelope kept on a one-way hash of the Google subject; "Results
are ephemeral" rewritten for signed-in users; Google sign-in only; store no
provider key, no password and no Google token beyond the sign-in exchange.

Those words and that summary are the owner's. **Everything else below is the
session's design**, listed under "Decisions the owner did not make".

This pull request is sign-in and sign-out only. The history, its retention
settings, the history view, account deletion and the hashed spend key are the
second pull request. The "Results are ephemeral" copy is unchanged here: with
no history yet, it is still true for every user; the second pull request
rewrites it for signed-in users when history exists.

## Context

Every browser has an anonymous account id (a uuid4) held by a server-side
session (`auth.py`, `session_store.py`, ADR-0073); the id keys the per-account
spend rails and the one-active-run rule. Nothing ties that id to a person, so
nothing can outlive the browser, which is what the owner's purpose needs.

Failure modes were listed before the code:
`docs/analysis/2026-09-25-w7-google-sign-in-failure-modes.md` (14 rows; rows
1-4 and 11-14 are this pull request's, and rows 11 and 14 were corrected after
the code, see that page).

## Decision

1. **OpenID Connect authorization code flow with PKCE.**
   `POST /v1/auth/google/start` (session cookie and CSRF header, like every
   other mutating route) makes a `state` and a PKCE `code_verifier`
   (`secrets.token_urlsafe`, 32 and 64 bytes), keeps both in process memory
   bound to the caller's session id, and returns Google's authorization URL
   with the `S256` challenge. Scope `openid email`; no `access_type`, so no
   refresh token; no `prompt`. The browser navigates there (`app.js`), but
   only if the URL's origin is `https://accounts.google.com`.
2. **The callback is protected by `state`, not CSRF.** `GET
   /v1/auth/google/callback` takes the pending entry for the CURRENT session
   (removed on first use, whatever follows), refuses it after 10 minutes, and
   compares `state` with `secrets.compare_digest`. A missing code (Google's
   `error=access_denied`) is refused before any call to Google. Every failure
   redirects to the fixed `/ui?sign_in=failed`; success to the fixed `/ui`.
   There is no `next` parameter.
3. **The exchange is server-side, bounded, and takes the ID token from its
   own response.** The code, verifier, client id, secret and redirect URI are
   POSTed to Google's token endpoint through `CREDENTIAL_OPENER` (no redirect
   is followed, so the secret is never re-sent elsewhere; the endpoint must
   pass `is_credential_safe`). The call runs on a worker thread and the
   request stops waiting after `TOKEN_EXCHANGE_TIMEOUT_S` (10 s); the socket
   timeout is the worker's own backstop. The body is read up to 64 KiB. A
   non-200 is refused without reading the error body.
4. **The ID token's claims are checked; its signature is not.** OpenID
   Connect Core 1.0, section 3.1.3.7, lets a client that receives the ID
   token directly from the token endpoint over TLS use TLS server validation
   in place of the signature check; no ID token from the browser is ever
   accepted. Checked, each with its own refusal: `iss` is one of Google's two
   spellings; `aud` is exactly this client id (a string, not a list); `azp`,
   when present, is this client id; `exp` is an integer later than now;
   `iat` is an integer no more than 300 s ahead of now and not after `exp`;
   `email_verified` is exactly `true`; `sub` and `email` are non-empty
   strings.
5. **An accounts table, one row per Google subject.** In the sessions
   database, created by a guarded, once-only `schema_migrations` block
   (`w7_accounts`), never in `SessionStore._SCHEMA`: an existing read-only
   database still opens, serves sessions, and only sign-in is unavailable.
   Columns: `account_id` (a new uuid4, minted once per subject), `google_sub`
   (unique), `email` (display only), `created_at`, `last_sign_in_at`. Nothing
   else: no token, no name, no picture. A returning subject gets its old id
   and an updated email.
6. **Sign-in mints a new session and revokes the old one.** A new id and a
   new CSRF token, bound to the account's id; the pre-sign-in id is revoked
   from the cache and the durable store (session fixation). This rotation
   neither checks nor records a per-IP mint (see "Decisions").
7. **Sign-out revokes the session server-side and clears the cookie.**
   Nothing else is deleted: the account row stays (the owner: history must
   survive sign-out). `POST /v1/auth/sign-out`, session and CSRF.
8. **Off unless all three settings are set.** `GOOGLE_OAUTH_CLIENT_ID`,
   `GOOGLE_OAUTH_CLIENT_SECRET` and `GOOGLE_OAUTH_REDIRECT_URI`, and the
   redirect URI must be `https` (or `http` to loopback), end in the callback
   path, and carry no query, fragment or userinfo. Off: the three routes
   answer 404, the page renders no account markup (the whole `/ui` page is
   byte-identical to the one before this change), and `/status` reports
   `sign_in_enabled: false`. Half set: the app still starts, sign-in stays off, and an ERROR at
   startup names the missing settings (never a value). This pull request sets
   no secret anywhere; `fly.toml` is unchanged.
9. **Nothing from the exchange is written or logged.** The token response is
   parsed in memory and dropped; failures log a fixed reason code. The
   callback's query (the code and `state`) is redacted from every log line
   by a path-keyed pattern in `logging_config` (uvicorn's access log writes
   the query), and from Sentry events by `main._scrub_user_text`.
10. **The page.** Enabled and anonymous: "Sign in with Google" in the top bar.
    Signed in: the email (escaped) and "Sign out". After a failed sign-in:
    "Sign-in did not complete. Please try again." (fixed text, nothing
    reflected).

## Measurements

On `wp/w7-signin`, based on `2c76efa`; no network except localhost, no paid
call, no call to Google (the token endpoint is a loopback stub,
`tests/google_token_stub.py`).

| what | result |
|---|---|
| RED before the change | the new test file against `origin/main`'s code: collection fails, `ImportError: cannot import name 'google_signin' from 'product_app'` (the routes, module and table do not exist). Not a per-check proof; the mutation table below is that |
| mutation proofs | 34 mutations, each run against the test named for it (cp aside, mutate, `__pycache__` cleared, run, restore, `cmp`), on a `git archive` copy; baseline of the same files green. First pass: 32 killed, 2 survived. `exp <= now` weakened to `exp < now` survived (no test at the expiry instant), and removing the worker join's timeout survived (the stalled stub was stopped by the socket timeout anyway). Two tests were added (a token expiring at this very second; a stub sending one byte every 0.2 s), and both mutations were then killed |
| the time bound | with the bound lowered to 0.5 s: a stub that stalls 5 s, and a stub that sends 25 bytes at 0.2 s each, both return the user in under 2 s (the slow case measured 0.51 s) |
| the page with sign-in off | `GET /ui` rendered on `origin/main`'s code and on this branch with the three settings blank: `cmp` exits 0 (byte-identical). A first draft left one blank line where the placeholder sat; the placeholder was moved onto the preceding line to remove it |
| full suite and gates | recorded in the pull request |

**Not measured, and stated as such:**

- **Google itself.** No request reached Google. The endpoints
  (`https://accounts.google.com/o/oauth2/v2/auth`,
  `https://oauth2.googleapis.com/token`), the two issuer spellings and the
  claim shapes are written from Google's published OpenID Connect
  documentation and its discovery document as the session knows them; they
  were not re-fetched in this session (no network). The first real sign-in,
  after the operator creates the OAuth client, is the check.
- **OpenID Connect Core 3.1.3.7** is cited from the specification as the
  session knows it; the text was not re-read in this session.

## Decisions the owner did not make (the session's)

- The flow's details: PKCE `S256`; the state and verifier sizes; 10 minutes;
  one pending sign-in per session, replaced when started again; a wrong
  `state` spends the entry.
- Keeping the pending state in process memory, not on disk. A restart
  mid-sign-in loses it and the user is told to try again; `fly.toml` runs one
  machine, so no second process can receive the callback.
- The sign-in rotation does not touch the per-IP mint cap. The cap bounds
  ANONYMOUS account ids per address; sign-in creates none (the id is one per
  Google subject), and the callback only runs for a browser holding a session
  the cap already let through. Checking it would refuse sign-in to anyone who
  had used their two sessions that day. Residual: each new Google account a
  person controls is a new account id, and so a new per-account spend
  envelope; the global daily ceiling still binds all of them.
- Sign-out ends the session and leaves the browser with none; the next page
  load mints a new anonymous session under the normal cap. On an address that
  has used its two sessions for the day, that load shows the existing 429
  page. Not minting a replacement inside sign-out is deliberate: a sign-in
  and sign-out loop would otherwise mint anonymous ids past the cap.
- A signed-in account's id is shared by every browser it signs in on, so the
  per-account spend rails and the one-active-run rule now span those
  browsers. That is the stricter direction.
- A new account id per Google subject rather than adopting the browser's
  anonymous id: nothing done before signing in joins the account (failure
  mode 6 records the same choice for history).
- A half-set configuration starts with sign-in off and an ERROR, rather than
  refusing to start.
- The redirect URI rule (`https` or loopback `http`, exact callback path, no
  query, fragment or userinfo).
- `aud` accepted only as a string equal to the client id; `azp` checked when
  present; 300 s of clock skew on `iat`; `email_verified` must be the boolean
  `true`.
- The table in the sessions database, not a new file; its columns; the email
  kept for display and updated on each sign-in.
- The callback is left out of the OpenAPI schema (it is a browser redirect
  target, not an API); the start and sign-out routes are in it, with their
  401, 403 and 404 shapes.
- The legacy `X-Account-Id` test header cannot start a sign-in or sign out
  (403): it has no server-side session to bind or revoke.
- The copy: "Sign in with Google", "Sign out", "Sign-in did not complete.
  Please try again.", and the two toasts in `app.js`.
- The board needle for W7 (`ABSENT src/product_app/config.py ::
  history_max_runs_per_account`): the setting failure mode 8 names as
  `HISTORY_MAX_RUNS_PER_ACCOUNT`, which the second pull request adds. If it
  lands under another name, the row stays PENDING while stale, and the
  second pull request must move the needle.

## Rejected alternatives

- **Verifying the ID token's signature against Google's keys.** It needs a
  key fetch and cache (a second outbound call, and either a dependency or a
  hand-written RS256 check) and buys nothing for a token received directly
  from the token endpoint over verified TLS, which is what 3.1.3.7 says.
- **A Google or OAuth library.** A new dependency for one POST and one JSON
  decode; the repository's outbound calls already share a guarded opener.
- **Re-binding the existing session to the account.** It is exactly the
  fixation hazard (failure mode 2).
- **Storing the pending state in SQLite.** It would survive a restart, at the
  cost of writing a live PKCE verifier to the volume; a lost sign-in costs
  one retry.
- **A `next` parameter.** An open redirect for a convenience nobody asked for.
- **Counting the sign-in rotation against the mint cap.** See "Decisions".
- **A socket-closing watchdog like the source fetcher's.** It would need its
  own connection classes to reach the socket; a worker thread gives the
  request the same total bound with the standard opener.

## Consequences

- With the three settings unset, which is the shipped state, nothing a user
  sees changes: the page, the API behaviour and the spend rails are as
  before, and `/status` gains `sign_in_enabled: false`.
- **The owner must create the Google OAuth client** (type "Web
  application", authorised redirect URI
  `https://quorum.stackclimb.com/v1/auth/google/callback`) and set the three
  secrets with `fly secrets set`. Until then sign-in is off in production.
- The second pull request builds on the account id: history rows keyed by
  it, retention, deletion of the row with its history and sessions, and the
  hashed spend key. Its failure modes are rows 5-10 of the page.
- Board row W7 is pinned and reads PENDING until the second pull request.
