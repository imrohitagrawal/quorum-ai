# W7, Google sign-in with history: how it can fail

Written before the code (AGENTS.md rule 16e). The owner decided W7 on
2026-09-24 (CHG-012 D7, their words): *"the purpose of sig-in is to preserve
the history of the searches from a account. THis can be limited to last 5
searches for example if we face issue in storage."* and *"the whole purpose
will be forfeited if we delete the history on every sign-out! but yes on
account deletion we should remove"*. The session's design, summarised back
and not contested (CHG-012 D7): keep the last 5 runs per account AND drop
runs older than 30 days, both environment settings with pinned defaults; a
summary row per run, not the run; nothing deleted on sign-out; account
deletion as a typed-confirmation action on one authenticated endpoint; the
24-hour spend envelope kept on a one-way hash of the Google subject for 24
hours; "Results are ephemeral" rewritten for signed-in users. Google sign-in
only. The prompt's hard stop: store no provider key, no password, and no
Google token beyond the sign-in exchange.

Today every browser gets an anonymous account id (a uuid4) with a
server-side session (`auth.py`, `session_store.py`): the id keys the
per-account spend rails and the one-active-run rule. Sign-in binds that
session to a Google identity; it does not replace the anonymous path.

| # | Failure | Harm | Design answer |
|---|---|---|---|
| 1 | **Login CSRF / a forged callback.** An attacker completes the OAuth flow with THEIR Google account and lands the victim's browser on the callback, so the victim's searches are saved into the attacker's history. | Private searches leak to an attacker. | A single-use `state` bound to the victim's current session (stored server-side, compared in constant time, deleted on first use, 10-minute expiry) and PKCE (`code_verifier` held server-side, never in the URL). A callback without a matching state is refused. |
| 2 | **Session fixation.** The session id that existed before sign-in keeps working after it, so a planted id becomes a signed-in one. | Account takeover by a pre-planted cookie. | Sign-in mints a NEW session (new id, new CSRF token) and revokes the old one; the cookie is replaced in the callback response. Sign-out revokes the session server-side, not only the cookie. |
| 3 | **A token kept.** The access token, refresh token or ID token is stored or logged. | A stolen database or log gives Google access. | Only the ID token's verified `sub` and, for display, `email` are read; no token is stored, no refresh token is requested (`access_type` omitted, scope `openid email`), and the exchange response is never logged. Sentry scrubbing covers the callback. A test asserts no token string reaches the database or the logs. |
| 4 | **A forged ID token.** An ID token not issued by Google for this app is accepted. | Anyone signs in as anyone. | The code is exchanged server-side at Google's token endpoint over verified TLS, and the ID token is taken only from that response (OpenID Connect Core 3.1.3.7 allows TLS server validation in place of the signature check for a token received this way), then `iss`, `aud` (this client id), `exp`, `iat` and `email_verified` are checked; no ID token from the browser is ever accepted. |
| 5 | **History leaking across accounts.** One account's history is served to another (a wrong key, a shared browser, a cached page). | Private searches exposed. | History rows are keyed by the internal account id bound to the Google `sub`, read only through the authenticated session; the history route sends `Cache-Control: no-store`; a test signs in two accounts and asserts neither sees the other. |
| 6 | **The anonymous account's runs after sign-in.** Runs made before signing in silently join the Google account, or are lost. | Surprise either way. | The session's design: only runs finished while signed in are saved; nothing is merged. Recorded as the session's, for the owner to see. |
| 7 | **Storing the answer.** The history row stores provider prose or the full question. | The store becomes a copy of everything users asked. | A summary row per run: the question truncated to a fixed length, the date, the mode and panel size, the band, the cost; no answers, no sources, no judge text. The question itself is the user's own text in their own history, which is the feature. |
| 8 | **Unbounded storage.** History grows without limit. | Disk fills on the Fly volume. | Keep the last `HISTORY_MAX_RUNS_PER_ACCOUNT` (default 5) and drop rows older than `HISTORY_MAX_AGE_DAYS` (default 30), both pinned; pruned on every write, in the same transaction. |
| 9 | **Deletion that is not.** "Delete my account" leaves history, the session or the Google binding behind; or a single click deletes everything by accident. | Data kept after a deletion request; or loss by mistake. | One authenticated POST with a typed confirmation string removes the account row, its history and its sessions in one transaction, and nulls the account id on operator run rows; a test reads every table afterwards. |
| 10 | **Deletion as a spend-cap reset.** A user deletes the account and signs in again to get a fresh 24-hour spend envelope. | The daily cap is bypassed. | Before deletion, the account's spend in the envelope is carried to a key that is a one-way hash of the Google `sub` (salted with a server secret), kept 24 hours; the new account created at the next sign-in with the same `sub` starts from that spend. |
| 11 | **The mint cap and sign-in.** Sign-in mints a session, and the per-IP daily mint cap (2 in production) refuses it, or sign-in becomes a way around the cap. | Users locked out, or the cap bypassed. | *Corrected after the code (see below).* Sign-in never re-binds a session (row 2 forbids it); it creates one new session and revokes the old. That rotation neither checks nor records a mint: the cap counts ANONYMOUS account ids, sign-in creates none (the id comes from the accounts row, one per Google subject), and the callback only runs for a browser already holding a session the cap let through. Checking it would refuse sign-in to anyone who had already used their two sessions that day. A test pins both halves: sign-in succeeds with the address's cap spent, and the mint count does not move. |
| 12 | **Open redirect.** The post-sign-in redirect target comes from the request. | Phishing through our domain. | The callback always redirects to `/ui`; no `next` parameter. |
| 13 | **Misconfiguration in production.** Sign-in is on without a client id or secret, or with the wrong redirect URI. | A broken button, or a flow that fails after the user consented. | Sign-in is off unless `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` and `GOOGLE_OAUTH_REDIRECT_URI` are all set (validated at startup; reported on `/status`); the button is not rendered otherwise. The operator sets them; this work sets no secret. |
| 14 | **Google down or slow.** | A hanging callback request. | The token exchange has a total time bound (the source fetcher's lesson, ADR-0124: a per-read socket timeout does not bound a server that keeps sending) and a failure returns the user to `/ui` with a plain message; nothing is half-created. *As built:* the exchange runs on a worker thread that the request stops waiting for after 10 s, with the socket timeout as the worker's own backstop; a test holds a stub that sends one byte every 0.2 s. |

## Corrections after the code (2026-09-25, the first pull request)

Two rows were written before the code and did not survive it:

- **Row 11** said the callback "reuses the session-creation path's cap check
  for the one new session it creates". The built design does the opposite and
  says why in the row: the rotation is not an anonymous mint, and checking it
  would lock out the visitors most likely to sign in. Recorded as the
  session's decision in ADR-0130.
- **Row 14** named "the source fetcher's watchdog". The fetcher shuts the
  socket from a timer; the exchange instead stops waiting on a worker thread.
  The lesson carried over (bound the total, not each read); the mechanism did
  not.

Rows 5 to 10 are the second pull request's and are unchanged.

