# W28 bring-your-own-key: research for the owner's six decisions (2026-10-16)

**PROPOSED — AWAITING OWNER. Research only; no decision is recorded here.** Every
recommendation below is the research's, not the owner's. The owner asked for this
research on 2026-10-15 (CHG-051: *"do a thorough research on the 6 decisions for
W28 and let me know the options along with recommendation"*), and on 2026-09-29
asked how other websites secure user keys (CHG-026 (f)); this file answers both.
The six decisions are the ones listed in the plan of draft pull request #525
(branch `w28/byok-pr1-plan`, section "Decisions only the owner can make"). W28
itself waits until W71 to W81 are done (the board's Parked table, CHG-051).

Repository claims are marked **MEASURED** (a command was run on `main` at
`6872e46`; the command is named) or **INHERITED** (read from a document; the
document is named). No paid call was made and no key was sent anywhere. The
OWASP ASVS 5.0 text and the LibreChat code were read raw from GitHub; the other
web quotes came through a text-extracting fetch and were spot-checked against
their pages before this file was committed (see "How the sources were checked"
at the end).

## The six decisions in one line each

| # | Question | Research's recommendation |
|---|---|---|
| 1 | Where does a user's key live? | In the server's memory only, never written to disk |
| 2 | Does a key belong to one browser session or to the account? | One session |
| 3 | May a visitor who has not signed in use their own key? | No: signed-in only |
| 4 | Does a key entered before sign-in carry over after sign-in? | No: drop it at sign-in |
| 5 | The user removes the key mid-run (EDGE-013): stop or finish? | Stop before the next stage; never fall back to the app's key |
| 6 | What should FR-012, AC-025 and AC-026 say? | Optional, two postures (ADR-0121); keep and sharpen AC-026 |
| + | How does the key reach us? | OpenRouter's OAuth sign-in (PKCE) with a credit limit and an expiry, rather than pasting a key |

## What the repository does today (the ground the decisions stand on)

- Every run uses the app's key; the source is hard-coded.
  `credential_source = ProviderCredentialSource.APP_OWNED` at
  `src/product_app/query_run_orchestration.py:1248`. `BYO_OPENROUTER` exists only in
  the enum (`src/product_app/provider_keys.py:7`). MEASURED:
  `grep -rn "credential_source = ProviderCredentialSource\|BYO_OPENROUTER" src/product_app`.
- The key is copied once at run start; clearing it mid-run still sent all 11 calls.
  INHERITED (the draft plan on `origin/w28/byok-pr1-plan`, from an uncommitted probe).
- The session cookie is `__Host-quorum_session`, `HttpOnly`, `Secure` in production,
  with a CSRF token on every change. MEASURED: `grep -n -i "cookie\|csrf" src/product_app/auth.py`.
- Sessions are **durable**: mirrored to SQLite on the Fly volume (ADR-0073). The
  `sessions` table holds only `session_digest, account_id, csrf_token, created_at,
  last_used_at`; the session id itself is stored only as a SHA-256. MEASURED:
  `sed -n 286,300p src/product_app/session_store.py`.
- Anonymous sessions live 2 hours (`auth.py:61`); signed-in ones expire after 120
  idle minutes (`config.py:862`, ADR-0138). MEASURED: grep.
- Google sign-in (ADR-0130) mints a **new** session, revokes the old one, and carries
  anonymous run history over (`account_history.carry_over`, ADR-0135). It already
  does PKCE server-side: "the verifier never leaves the server" (`google_signin.py:15`).
  MEASURED: `sed -n 15,16p` and `sed -n 690,715p` of that file.
- Production stops when idle and runs one machine: `min_machines_running = 0`,
  `auto_stop_machines = "stop"` (`fly.toml:191-192`); "This config assumes a
  single-instance deployment" (`fly.toml:6`). MEASURED: `sed` of `fly.toml`.
- `cryptography==50.0.2` is a pinned dependency, for pypdf's encrypted PDFs
  (`pyproject.toml:41-42`), but **no file under `src/` imports it**. MEASURED:
  `grep -rn "import cryptography\|from cryptography" src/` → no hits.
- The page allows inline scripts: `script-src 'self' 'unsafe-inline'`
  (`main.py:875`). MEASURED: grep. The security review makes fixing this (W75) and
  the key-redaction gaps (W76) prerequisites of W28. INHERITED
  (`docs/analysis/2026-10-13-security-review.md`, S11 and section 2; W76 rests on
  agents' reports not yet re-run).
- New routes cannot be decorated functions: a test caps them at 55
  (`tests/unit/test_mutation_test_set_integrity.py:280`, MEASURED); that the tree is
  at 55 is INHERITED (draft plan).
- FR-012 is "Required" in `docs/10:201` and "Optional" in `docs/17:18`; AC-026 says
  "no user-entered provider-key field is shown"; both test files its traceability
  row cites are missing. MEASURED: `grep -n`, and `ls` → "No such file or directory".

### What the owner has actually said

- 2026-09-29 (M03, point 5), verbatim: *"Do thorough research and analysis of how
  other websites are securing this BYOK feature. We should ensure that we are not
  storing it in any logs, any web sessions, or anywhere the user or an attacker can
  web-inspect and see the keys, and that any other security threats are not there."*
  INHERITED (`docs/analysis/2026-09-29/OWNER-DISCUSSION-LOG.md:111`; CHG-026 (f)).
- The status table of that log says "key in server memory only" (line 23). That
  column is the **session's** summary, not the owner's words. The owner's words do
  not choose between memory and encrypted storage. **"Any web sessions" is
  ambiguous**: it could mean the browser (cookies, local storage) or the server's
  session records. The owner should say which; decision 1 turns on it.
- ADR-0121 (PROPOSED) records the shape the owner accepted on 2026-09-23: the party
  paying chooses the flags; the party at risk sets the rails; $5 user budget window.
  INHERITED.

---

## Decision 1. Where does a user's key live?

**Question.** When a visitor gives us their OpenRouter key, do we keep it only in the
server's memory, or write it to our database, encrypted?

**Example.** Priya pastes `sk-or-v1-…` at 10:00 and runs two questions. At 10:40
nobody is using the site, so Fly stops the machine. At 11:00 she comes back.
- Memory only: her session is still valid (sessions are durable), but the key is
  gone. The page asks her to paste it again.
- Encrypted at rest: the key is read back from the database and decrypted. She runs
  her question without pasting.
- A merge to `main` redeploys (every merge does), with the same two outcomes.

**Options.**
- **A. Server memory only.** A dictionary in the process, keyed by session.
- **B. Database, encrypted** (AES-256-GCM; master key a Fly secret; account id bound
  into each encryption).
- **C. In the browser** (local storage, or a cookie holding the key).

**Risks and build cost.**

| Option | What could go wrong | Build cost here |
|---|---|---|
| A | Nothing on disk or in volume snapshots. But the user re-pastes after every idle stop and deploy, and **each paste crosses the browser**, where an injected script can read it while inline scripts are allowed (W75). Keep the key in its own dictionary, not on `_Session`, so it can never reach the SQLite mirror. | Smallest: an in-process store; three routes via `add_api_route`; the resolver at `query_run_orchestration.py:1248`; the judge key in `evaluation.py`; drop the key on sign-out, sign-out-everywhere, idle expiry, `revoke_account`, account deletion (`auth.py`, `google_signin.py`, `account_deletion.py`); UI in `static/app.js`, `templates/workspace.html`; `openapi.yaml`. W75 and W76 first. |
| B | Whoever gets the database **and** the master key reads every key. Volume snapshots hold the database (security review §4 item 5). A binding bug could let one account decrypt another's key (LibreChat's weakness, below). Fewer pastes. | All of A, plus: a migrated table in `session_store.py`; first use of `cryptography` in `src/` (AES-GCM, random nonce, account id as associated data); a versioned master-key Fly secret; re-encryption on rotation; cross-account decrypt tests. Roughly double A. |
| C | Any script on our origin reads it; OWASP and ASVS forbid it; fails the owner's "web-inspect" words and AC-026. | Small, but ruled out. |

**How established products do it.**
- **Stored at rest, encrypted (server side):**
  - OpenRouter, for the provider keys its own users bring
    (https://openrouter.ai/docs/use-cases/byok): *"Your provider keys are securely
    encrypted and used for all requests routed through the specified provider."*
    No method is named.
  - Cloudflare AI Gateway
    (https://developers.cloudflare.com/ai-gateway/configuration/bring-your-own-keys/):
    *"The keys are stored securely with Secrets Store"*.
  - LibreChat, self-hosted chat app
    (https://www.librechat.ai/docs/configuration/dotenv): *"LibreChat uses `CREDS_KEY`
    and `CREDS_IV` to encrypt supported credentials stored in the database."* Its code,
    read raw (`packages/data-schemas/src/methods/key.ts`): `const encryptedValue = await
    encrypt(value);`, and `encrypt` in `packages/data-schemas/src/crypto/index.ts` is
    the `/** --- Legacy v1/v2 Setup: AES-CBC with fixed key and IV --- */` function.
    So LibreChat's user keys use one fixed IV for every row and no authentication tag.
    That breaks ASVS 11.3.2/11.3.3/11.3.4 (below). **A cautionary example, not a
    model.**
- **Not stored by the service:** Cursor (https://cursor.com/docs/settings/api-keys):
  *"Your API key is not stored on our servers."* and *"It is sent to our backend with
  every request"*. The desktop app holds it.
- **On the user's device:** Zed (https://zed.dev/docs/ai/use-api-access): *"Keys saved
  through Zed are stored in the system keychain, not in `settings.json`."*; GitHub
  Copilot app (https://github.blog/changelog/2026-06-23-github-copilot-app-support-for-byok):
  *"Keys are stored in the local OS keychain and are never read back by the UI."*;
  Simon Willison's `llm` (https://llm.datasette.io/en/stable/setup.html): *"Keys that
  are stored in this way live in a file called `keys.json`."*
- **In the browser (option C):**
  - TypingMind (https://docs.typingmind.com/general-faqs.md): *"Your API key is stored
    locally in your browser's local storage and is never sent to TypingMind's
    servers."*
  - Open WebUI Direct Connections
    (https://docs.openwebui.com/features/chat-conversations/direct-connections): keys
    are used *"without storing them on the Open WebUI server"* and *"keys are stored in
    the browser's local storage."*
  - Both work because those apps call the provider **from the browser**. Ours calls
    OpenRouter from the server, so a browser-held key would still have to travel to us
    on every run.
- **Standards:**
  - OWASP Cryptographic Storage Cheat Sheet
    (https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html):
    *"The best way to protect sensitive information is to not store it in the first
    place."*; *"The most commonly used authenticated modes are GCM and CCM, which should
    be used as a first preference."*; *"Where possible, encryption keys should be stored
    in a separate location from encrypted data."*
  - OWASP Secrets Management Cheat Sheet
    (https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html):
    *"You should not store keys next to the secrets they encrypt"*; *"Rotating certain
    keys, such as encryption keys, might trigger full or partial data re-encryption."*
  - OWASP ASVS 5.0 (raw text, `OWASP/ASVS` repo, `5.0/en`): 11.3.2 *"Verify that only
    approved ciphers and modes such as AES with GCM are used."*; 11.3.4 (no IV reused
    for one key and data pair); 14.3.3 *"Verify that data stored in browser storage
    (such as localStorage, sessionStorage, IndexedDB, or cookies) does not contain
    sensitive data, with the exception of session tokens."*

**Recommendation (research's, not the owner's).** Start with **A, server memory
only**, and revisit B only after the owner has used it. **Deciding reason:** OWASP's
first rule is not to store what you do not need, and our sessions already survive
restarts, so the only cost of A is a re-paste after an idle stop. If the owner picks
OpenRouter's OAuth flow (section at the end), that re-paste becomes one click, and
A's main drawback almost disappears. The security review's contrary
recommendation (B) rested on the re-paste cost (`security-review.md` §5 item 2,
INHERITED); OAuth removes that cost. Option C is ruled out by the owner's own words.

---

## Decision 2. Per browser session or per account?

**Question.** Does a key belong to the one browser that entered it, or to the
signed-in account, shared by every device of that account?

**Example.** Priya, signed in, pastes her key on her laptop, then opens the site on
her phone.
- Per session: the phone has no key; she pastes it again there (or the phone runs on
  the app's key and its limits).
- Per account: the phone has the key at once. When she signs out on the laptop, the
  phone still holds it until she removes it.

**Options.** **A. Per session.** **B. Per account.**

| Option | What could go wrong | Build cost here |
|---|---|---|
| A | Smallest reach: a stolen session cookie spends the key only until that session ends (120 idle minutes signed in, 2 hours anonymous). Fits memory-only storage exactly. | Smallest: the store is keyed by session id; ending a session already exists in several paths, each must drop the key. |
| B | A stolen cookie for **any** of her sessions can spend the key, and it outlives sign-out on one device; "sign out everywhere" (ADR-0137) and account deletion must remove it. | Only useful across devices with storage at rest, so it implies decision 1 = B. Keyed by `account_id`; status owner-scoped. |

**How established products do it.**
- Per account / team (server side): LibreChat stores keys per user (`updateUserKey`
  upserts by `userId` and `name`, read raw from `key.ts`); Vercel AI Gateway
  (*"scoped to be available throughout your Vercel team"*, URL above); GitHub Copilot
  enterprise BYOK (https://docs.github.com/en/copilot/concepts/models/bring-your-own-key):
  *"Enterprise BYOK is handled server-side and affects the models served to users by
  the Copilot API."*
- Per device: GitHub Copilot local BYOK (same page): *"These keys are only handled
  client-side: they are stored locally and the associated models aren't available to
  other users."*; Zed, the Copilot app, TypingMind and Open WebUI (quotes in decision 1).
- Standards: OWASP Secrets Management, *"Secrets must have the minimum privileges
  assigned to them to enable their required use/role."* (URL above). ASVS 13.3.2
  *"Verify that access to secret assets adheres to the principle of least
  privilege."*

**Recommendation (research's).** **A, per session.** **Deciding reason:** it bounds a
stolen cookie to one session's life, and it is the only choice consistent with
memory-only storage; per account only pays off once keys are stored at rest.

---

## Decision 3. May an anonymous (not signed-in) session hold a key?

**Question.** Must a visitor sign in with Google before using their own key?

**Example.** Ravi has never signed in. He pastes his key and asks a question.
- Allowed: the run uses his key. His session lasts 2 hours; no account means no
  "sign out everywhere" and no account deletion to clean up.
- Signed-in only: the page says "Sign in to use your own key" and his run uses the
  app's key and its limits.

**Options.** **A. Signed-in only.** **B. Anonymous allowed.**

| Option | What could go wrong | Build cost here |
|---|---|---|
| A | Ravi must sign in first (one Google step). Abuse with throwaway keys needs a Google account per attempt. | Small: one check on `SessionContext` (anonymous vs signed in) in the submit route; a test that an anonymous session can never hold or use a key (the security review's key-safety agent listed it, INHERITED). |
| B | **Planted-key spying.** If a victim's browser ends up on a session holding the **attacker's** key (a fixation bug, or a shared computer), the victim's questions run on that key, and its owner can read them: *"Navigate to your Observability settings and toggle Input & Output Logging to enable it."*; *"Once enabled, your prompts and completions are accessible from your Logs page."* (https://openrouter.ai/docs/guides/features/input-output-logging). Anonymous sessions are the cheapest to plant. Also, the owner rejected the 2-per-day mint cap for BYOK (ADR-0121), so anonymous BYOK needs the new limits first. | The check, plus the rails work for anonymous mints (ADR-0121 PR 2). |

**How established products do it.**
- LibreChat requires an account; keys are stored per `userId` (raw code above).
- TypingMind and Open WebUI Direct Connections keep the key in the browser with no
  server account, which is the anonymous case, but neither sends the key to their own
  server (quotes in decision 1).
- **Not found:** a hosted service whose **server** holds a key for an anonymous
  visitor. Absence of evidence, not evidence of absence.
- The security review's key-safety agent recommended "signed-in accounts only"
  (`security-review.md` §5 item 3). INHERITED, an agent's view.

**Recommendation (research's).** **A, signed-in only.** **Deciding reason:** a key
spends real money and exposes the questions sent with it to the key's owner; tying it
to a Google identity makes every key traceable to one person and gives the existing
clean-up paths (sign out everywhere, account deletion) something to act on.

---

## Decision 4. Does a key entered before sign-in carry over after sign-in?

**Question.** If a key is entered on an anonymous session and the visitor then signs
in, does the new signed-in session keep that key?

(If decision 3 is "signed-in only", this question mostly disappears: no anonymous
session ever holds a key. It still applies to a key entered on one signed-in session
when the user signs in again as a different Google account on the same browser.)

**Example.** An attacker on a shared library computer opens the site, pastes **his
own** key with prompt logging on, and walks away. Asha sits down and signs in.
- Carry over: Asha's questions run on the attacker's key; he reads them in his
  OpenRouter Logs page.
- Drop: sign-in starts a clean session; Asha sees "no key" and her runs use the app's
  key or her own.

**Options.** **A. Drop the key at sign-in.** **B. Carry it over.** **C. Carry it over
only after the user confirms on a screen that shows the key's last four characters.**

| Option | What could go wrong | Build cost here |
|---|---|---|
| A | A real user re-pastes once. | Smallest: sign-in already makes a new session; do not copy the key. One test, with a positive partner (a key entered after sign-in is present). |
| B | Planted-key spying. The app **already** carries anonymous history over at sign-in (ADR-0135); copying that for keys is easy and wrong, since history is the user's own data and a key may be someone else's. | Small. |
| C | People click through; four characters mean little. | Medium: a screen and a route. |

**How established products do it.**
- **Not found:** any product page that says what happens to a provider key entered
  before sign-in.
- Standard (the nearest rule): OWASP Session Management Cheat Sheet
  (https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html):
  *"The session ID must be renewed or regenerated by the web application after any
  privilege level change"* and *"The session ID regeneration is mandatory to prevent
  session fixation attacks."* ASVS 7.2.4: *"Verify that the application generates a
  new session token on user authentication, including re-authentication, and
  terminates the current session token."* We already do this
  (`issue_signed_in_session`). Carrying the key over would bring back, for the key,
  the very thing the new session token protects against.

**Recommendation (research's).** **A, drop it.** **Deciding reason:** it is the only
option that defeats a planted key, and its cost is one re-paste.

---

## Decision 5. The user removes the key while a run is in progress (EDGE-013)

**Question.** If a user clicks "Remove key" mid-run, do the remaining stages stop, or
does the run finish on the key it started with?

**Example.** Priya starts a four-model run on her key. After the four answers arrive
(4 calls sent), she clicks Remove. The debate, synthesis and judge are still to come.
- Stop at the next stage: no more calls go out on her key. She gets the four answers
  and a notice "Stopped: you removed your key." Calls already sent cannot be recalled.
- Finish on the starting key: the remaining calls go out on her key. The receipt says
  "Finished on the key you removed at 10:42; removal applies to the next run."

**Options.** **A. Stop at the next stage (fail closed).** **B. Finish, and say so on
the receipt.**

| Option | What could go wrong | Build cost here |
|---|---|---|
| A | A partial result she paid for. A bug that falls back to the **app's** key would move her run onto our money (see Vercel below); a test must rule it out. | Medium: each stage re-reads the key's presence, as the live flag already is (INHERITED, draft plan); a test asserting the exact call count (rule 6b). |
| B | Spending continues after she said stop, which fails the usual reason to remove a key: "I think it leaked". | Small: keep copy-at-start; a receipt line and a test. |

Whichever is chosen, the user can also **revoke the key on OpenRouter itself**. Then
the next call fails with 401 whatever we decide, so option B cannot promise to finish.
The run must treat a 401 mid-run as "key revoked", never retry on the app's key.

**How established products do it.**
- **Not found:** any product page that defines what happens to an in-flight request
  when a user removes a key.
- A cautionary example of the fallback risk: Vercel AI Gateway
  (https://vercel.com/docs/ai-gateway/byok): *"If a query using your credentials
  fails, AI Gateway will retry the query with its system credentials to improve
  service availability."* Vercel bills that to the customer's credits; for us a
  fallback would bill the app.
- Standard: OWASP Secrets Management (URL above): *"When secrets are no longer
  required or potentially compromised, you must securely revoke them to restrict
  access."*

**Recommendation (research's).** **A, stop at the next stage.** **Deciding reason:** a
user removes a key most often because they fear it leaked, and stopping is the only
option that honours that; OpenRouter-side revocation forces the same behaviour anyway.

---

## Decision 6. What should FR-012, AC-025 and AC-026 say?

**Question.** The requirement contradicts itself and one acceptance criterion forbids
the feature; what should the requirement say now?

**Example.** A BYOK pull request adds a key field. AC-026 as written ("no
user-entered provider-key field is shown") now fails, while FR-012's title calls the
key "Required" and the registry calls it "Optional".

**Options.**
- **A. Optional, two postures (ADR-0121).** FR-012: a signed-in user may supply a
  key; runs on it follow the user posture. AC-025 unchanged (the app's key). AC-026
  rewritten: with BYOK on, a signed-in user sees a key field; the key is never in
  browser storage, never returned in full (last four characters only), never logged.
  Repair the traceability rows. Risk: none new. Cost: docs only (`docs/10`, `12`,
  `16`, `17`, `18`).
- **B. Required** (the app stops paying). Contradicts ADR-0121 and ends free use.
- **C. Leave it** until BYOK ships; repair only the false traceability rows now
  (possible without any BYOK decision, INHERITED from the draft plan). Keeps a
  contradiction alive.

**How established products do it.** Not applicable to a requirement's wording. The
standards bear on AC-026's content: ASVS 14.3.3 (no sensitive data in browser storage,
quoted in decision 1); ASVS 14.2.6 *"Verify that the application only returns the
minimum required sensitive data for the application's functionality. For example,
only returning some of the digits of a credit card number and not the full
number."*; ASVS 14.2.1 *"…the URL and query string do not contain sensitive
information, such as an API key or session token."* GitHub's Copilot app shows the
practice: *"never read back by the UI"* (URL above).

**Recommendation (research's).** **A.** **Deciding reason:** it is the posture the
owner already accepted in ADR-0121, and AC-026's existing promise ("no provider key is
stored in the browser") is exactly what the standards require, so it should be kept
and sharpened, not deleted.

---

## OpenRouter OAuth PKCE as an alternative to pasting a key

**What it is.** OAuth is a "log in with X and approve this app" flow. PKCE ("proof key
for code exchange") is the variant that stops a stolen one-time code from being
useful to anyone but the app that started the flow.

**What OpenRouter offers.**
- https://openrouter.ai/docs/use-cases/oauth-pkce: *"Users can connect to OpenRouter
  in one click using Proof Key for Code Exchange (PKCE)."*; *"Your user will be
  prompted to log in to OpenRouter and authorize your app."*; the app sends the
  returned code to `https://openrouter.ai/api/v1/auth/keys` to *"exchange the code for
  a user-controlled API key"*; *"Authorization codes expire 10 minutes after
  issuance."*; *"Store the API key securely within the user's browser or in your own
  database"*. That guide page mentions no spending limit, and its examples do the
  exchange in the browser; doing it on our server is our choice.
- **A spending limit is available in the API reference**
  (https://openrouter.ai/docs/api/api-reference/oauth/create-authorization-code.md,
  `POST /auth/keys/code`): `limit`: *"Credit limit for the API key to be created"*;
  `usage_limit_type`: *"Optional credit limit reset interval. When set, the credit
  limit resets on this interval."* (daily, weekly or monthly); `expires_at`:
  *"Optional ISO 8601 UTC expiration timestamp."* The page does not say whether the
  user sees or can change the limit on OpenRouter's approval screen: **UNVERIFIED**.
  The page does not state the unit of `limit`; dollars is likely but **UNVERIFIED**.
  An independent write-up (Kristóf Marussy, https://marussy.com/pkce-authentication/):
  *"it allows generating API keys with inbuilt spending limits."* and *"we can ask the
  user to provide us with an API key with the limit of their choosing."*
- The approval step is free and needs no key, but nobody has run it against this
  app. Before building, one manual run with a throwaway OpenRouter account should
  confirm: the approval screen, whether `limit` and `expires_at` are honoured, and
  that the key appears in the user's OpenRouter key list where they can revoke it.
  **UNVERIFIED** until then (AGENTS rule 8c).

**What it changes for decisions 1 to 5.**
- **The key never passes through the browser** if our server does the code exchange
  (the code passes through the URL; the key does not). That removes the paste, the
  biggest browser exposure, and weakens (but does not remove) the W75 prerequisite: a
  script on our page could still act as the user, but cannot read a key the page
  never holds. We already run this exact pattern for Google sign-in
  (`google_signin.py:15`, MEASURED), so the build reuses known code.
- **Decision 1:** reconnecting after an idle stop is one click, not a re-paste, so
  memory-only (A) loses its main drawback. And because the app can ask for a key with
  a credit `limit` and an `expires_at`, a key stored at rest (B) is worth much less to
  a thief. Either option gets safer; memory-only gets cheaper for the user.
- **Decision 2:** unchanged; per session plus one-click reconnect per device is easy.
- **Decisions 3 and 4:** unchanged. The planted-key risk stays: the planted key would
  simply be one the attacker approved.
- **Decision 5:** unchanged in our app; the `limit` caps the worst case of any choice.
- **It adds** a start and a callback route (via `add_api_route`), a pending-exchange
  store modelled on the Google one, and a "Connect OpenRouter" control. W76 and the
  key-absence tests are still needed.

**Recommendation (research's).** Offer OAuth PKCE as the main way in, with a credit
limit and an expiry requested on every key, and keep "paste a key" out of the first
pull request. **Deciding reason:** it is OpenRouter's own supported flow, it keeps the
key out of the browser (the owner's "web-inspect" concern) and it caps the money at
risk, which no storage choice can do on its own.

---

## Not covered

JetBrains AI Assistant, Continue.dev and Langfuse/LangSmith were not read. Raycast
(https://manual.raycast.com/ai/bring-your-own-key) says only *"The key is stored
securely"*.

## Summary

| Decision | Options | Research's recommendation | The deciding reason |
|---|---|---|---|
| 1. Where the key lives | Server memory / encrypted database / browser | Server memory only | OWASP: do not store what you need not; sessions already survive restarts; OAuth makes reconnecting one click |
| 2. Per session or per account | Session / account | Per session | Bounds a stolen cookie to one session's life; per account only pays off with storage at rest |
| 3. Anonymous sessions | Signed-in only / anonymous allowed | Signed-in only | A key's owner can read the prompts sent with it; a Google identity makes every key traceable and cleanable |
| 4. Carry over at sign-in | Drop / carry / carry after confirm | Drop | Only option that defeats a planted key; cost is one re-paste |
| 5. Removal mid-run (EDGE-013) | Stop at next stage / finish and say so | Stop at next stage | Users remove keys because they fear a leak; OpenRouter-side revocation forces the same result anyway; never fall back to the app's key |
| 6. FR-012, AC-025, AC-026 | Optional two-posture / required / leave until BYOK ships | Optional, two postures; keep and sharpen AC-026's "nothing in the browser" | Matches ADR-0121, which the owner accepted; AC-026's promise is what ASVS 14.3.3 requires |
| Key intake (cross-cutting) | Paste / OpenRouter OAuth PKCE | OAuth PKCE with a credit limit and expiry | Key never in the browser and money at risk is capped; reuses our Google PKCE pattern |

## How the sources were checked

SOURCES_CHECK_PLACEHOLDER
