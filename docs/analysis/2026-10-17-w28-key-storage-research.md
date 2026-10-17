# W28: keeping a signed-in user's own OpenRouter key — the research, the decisions, and the one W28 analysis (2026-10-17)

**This file is the one W28 analysis.** It replaces, for W28, the earlier documents listed in
section 17, which now carry a "Superseded by" note. It records research and the owner's answers.
It changes no code: W28 is built later, after W85, W86, W100, W87, W88, W80, W75 and W76 (CHG-061).
The decisions are the CHG rows named in section 15; the design they add up to is ADR-0180.

**How each claim is marked.**
- **[session]**: this session ran the command itself on 2026-10-17; the command is named.
- **[agent]**: one of six read-only research agents read the page or ran the free command on
  2026-10-17. Their full reports, with every quote and command, are outside the repository, in the
  owner's evidence folder `quorum-ai-evidence/2026-10-17/w28-research/` (`r1-fly.md`,
  `r2-openrouter.md`, `r3-products.md`, `r4-standards.md`, `r5-kms.md`, `r6-repo.md`). A vendor's
  documentation is the vendor's claim, not a measurement of the product.
- **UNVERIFIED**: nothing confirmed it; the check that settles it is named.
- Line numbers are on `main` at `a2af06c`.

No paid call was made. No real key was used. Nothing was changed on OpenRouter, Fly or Google.
OWASP texts are quoted briefly under their CC BY-SA 4.0 licence; most are paraphrased.

---

## The answer in short

- **Whoever can deploy code to the app can read a user's key in every design where our server uses
  the key.** That is true of memory-only storage, of an encrypted database, and of a key held by a
  key service. Fly says it of its own secrets: *"People with deploy access can deploy code that
  reads secret values"* [agent, `docs.fly.io/apps/secrets`]. So the designs differ in how far they
  limit the damage, not in whether they prevent it: a spend limit on the key, how quickly it can be
  revoked, and whether misuse leaves a trail.
- **Memory-only storage does not fit this app.** The one machine stops when idle and at every
  deploy (`fly.toml:191-192`), so a memory-held key is lost at every idle stop and every deploy, and
  the user would paste it again each time. The owner asked for no re-paste after a stop or deploy (CHG-059).
- **Every product the research read that stores the key on its server keeps it across restarts and
  deploys** (inferred from where each stores the key; no vendor page says it in words; section 6).
  The decryption key usually sits in an environment variable or a file beside the database, and the
  enterprise tiers move it into a key service (section 6, pattern 2).
- **The decided design** (the owner's answers of 2026-10-17, section 15; ADR-0180):
  - the key arrives only through OpenRouter's own sign-in flow (OAuth with PKCE), exchanged on our
    server, so it never passes through the browser; on OpenRouter's approval screen the user sets
    the key's credit limit [agent, OpenRouter's screenshot; UNVERIFIED that today's screen still
    has it], and a key with no limit gets a warning;
  - it is stored per signed-in account, in its own table, encrypted with AES-256-GCM, the account
    id bound into every encryption; never on a session, a cookie or in the browser;
  - the master key is its own Fly secret (not `QUORUM_TOKEN_SECRET`), versioned so it can be
    replaced; it moves to AWS's key service, reached with Fly's machine identity, if a Fly or GitHub
    token is ever suspected;
  - a run on the user's key follows the user's own budget window and per-run cap, never falls back to
    the app's key, and never spends the app's Tavily key; if the key is removed mid-run, the page asks
    whether to stop, and stops if there is no answer.
- **What no design here stops:** someone holding a Fly token, GitHub write access (the deploy
  workflow), or a breach at Fly or OpenRouter. The real outer bound is the credit limit on the key
  at OpenRouter, and the user's power to revoke it there.

---

## 1. The owner's words that bind this work

Checked word for word against the transcripts' `type: user` records on 2026-10-17 [session: a
script over transcripts `23fee4a3` and `20d36bac` found each quote at the time given].

| When (UTC) | Where | The owner's words |
|---|---|---|
| 2026-09-23 16:11:37Z | transcript `23fee4a3` | *"In the case of bring your own, the live execution should be turned on by default, and the judge should also be turned on by default. It should not need fly secrets settings."* and *"the per-IP limitations, the per-day charges, or per-run-per-day charges should not be enforced from the code side. It should be something that the user should be able to select. For example, we can have a $5 window or a limit"* |
| 2026-09-23 16:17:23Z | `23fee4a3` | *"the quorum-ai judge API key should also be the same as the bring your own key which the user is providing as an open router key"* |
| 2026-09-23 16:21:02Z | `23fee4a3` | *"For the rest, I agree with all your suggestions"* (the rails table ADR-0121 records) |
| 2026-09-29 | `docs/analysis/2026-09-29/OWNER-DISCUSSION-LOG.md:111` (M03 point 5; CHG-026 (f)) | *"We should ensure that we are not storing it in any logs, any web sessions, or anywhere the user or an attacker can web-inspect and see the keys, and that any other security threats are not there."* |
| 2026-10-13 06:18:27Z | `20d36bac` | the key must be stored so that *"it is not leaked, is not in the sessions, and is not being hunted by any attackers or stealers"* |
| 2026-10-17 | CHG-059 | *"I don't think that, in enterprise applications, I need to repaste the key for each and every stop and deploy."*; *"Thorough research needs to be done here."*; decision 3: signed-in only |

**A rule the owner sent but did not write** (found by the repository agent, [agent, `r6-repo.md`
A3]): ADR-0130 (`docs/adr/0130-sign-in-with-google-and-sign-out.md:17-19`), CHG-020 and the accounts
table comment (`src/product_app/session_store.py:314-316`) honour a "hard stop" against *"storing a
provider key, a password, or any Google token beyond the sign-in exchange"*. ADR-0130 records it as
assistant-drafted text in a prompt the owner sent on 2026-09-24, for W7. Any design that stores the
key contradicts it, so the owner was asked to lift or keep it (section 15).

**Four tensions** the prompt named, each settled by an owner answer in section 15:
1. *"not in the sessions"* (2026-10-13) against a key held per browser session (the 2026-10-16
   research's recommendation);
2. *"no re-paste after a stop or deploy"* (2026-10-17) against "memory only" (the 2026-09-29
   conditional agreement);
3. *"should not be enforced from the code side"* (2026-09-23) against ADR-0121 keeping the $0.50
   per-run cap for user keys;
4. *"It should not need fly secrets settings"* against any design whose master key is a Fly secret.

---

## 2. Who the attacker is, and what each holds

| # | Attacker | What they hold |
|---|---|---|
| A1 | Someone on the internet, no account | Nothing but the public pages |
| A2 | A signed-in user after another user's key | Their own session; they change ids in requests |
| A3 | A thief of a user's session cookie | The cookie: can act as the user, so can spend |
| A4 | Script in our page (cross-site scripting) or a hostile browser extension | Everything the page and browser storage hold |
| A5 | A reader of logs | Fly log search (7 days, [agent, Fly logging docs]), GitHub Actions logs, Sentry |
| A6 | A holder of a database copy | A volume snapshot (kept 5 days, [session]), a backup, a laptop copy |
| A7 | A holder of a Fly token, or an organisation member | Deploy, SSH as root, exec, restore a snapshot ([agent, Fly tokens and roles docs]; that a deploy token or a member can SSH and restore is inferred from the capability lists, not run) |
| A8 | Someone with GitHub write access | The deploy workflow, which holds `FLY_API_TOKEN` |
| A9 | A breach at Fly, Sentry, OpenRouter or a key service | That company's systems |

Measured by the session on 2026-10-17 with read-only `fly` commands: the volume `quorum_data`
reports `encrypted: true`, `snapshot_retention: 5` and `auto_backup_enabled: true`
(`fly volumes list -a quorum-ai --json`), and the app has two app-scoped deploy tokens, each
expiring in 2046 (`fly tokens list -a quorum-ai`). Organisation-scoped tokens were not listed: the
session's command to list them was refused by its own permission settings, so that is the owner's
to run (`fly tokens list --scope org`). Fly holds the volume's encryption key (*"We manage the keys
for the drives for you"*, [agent, Fly healthcare page]), so volume encryption protects against a
disk lost at Fly, not against A6 or A7.

---

## 3. The storage patterns compared

"Read" means get the plaintext key. M = memory only; F = database, AES-256-GCM, master key a Fly
secret; K = database, the key encrypted by a key service (AWS KMS, Google Cloud KMS, or Fly's own
`secretkeys`); C = encrypted cookie; B = browser only; P = a tokenising proxy that injects the key
into the outbound call.

| Attacker | M | F | K | C | B | P |
|---|---|---|---|---|---|---|
| A1 | nothing | nothing | nothing | nothing | nothing | nothing |
| A2 | nothing if lookups use the signed-in account | same, and a copied row fails to decrypt (account id bound in) | same | nothing | nothing | depends on the proxy's token scoping |
| A3 | spends, cannot read | spends, cannot read | spends, cannot read | spends; the cookie carries the ciphertext | spends only from that browser | spends |
| A4 | reads at every paste | reads at the one paste (none with OAuth) | same as F | cannot read an `HttpOnly` cookie; can spend | **reads it** | reads at paste |
| A5 | only through a redaction gap | same | same | same | same | same |
| A6 | nothing | ciphertext only: useless without the Fly secret | ciphertext only: useless without the key service | nothing on our disk | nothing | tokens only |
| A7, A8 | deploy code that captures keys as they arrive or sit in memory | read the master key once, then decrypt every copy they hold **offline, for ever**; rotating the master key protects only what is written afterwards | deploy code that asks the key service to decrypt: a **decrypt oracle while access lasts**; no key to copy; each decrypt logged outside Fly (AWS, Google) | same as F with the cookie's key | none of ours, but they can serve script to the page (= A4) | spend through the proxy; with a caller-chosen destination, read ([agent, `r5-kms.md` 8.1]) |
| A9 | Fly | Fly (holds secrets, volumes) | Fly plus the key service: two companies | Fly | none | the proxy company |

For every row:

| Question | M | F | K | C | B | P |
|---|---|---|---|---|---|---|
| Survives an idle stop and a deploy? | **No** (`fly.toml:191-192`) | Yes | Yes | While the cookie lives | On that browser | Yes |
| Works on every device of the account? | No | Yes | Yes | No | No | Yes |
| Passes through the browser? | At each paste | Once at paste; never with OAuth | Same as F | Once, then as ciphertext on every request | Always | Once at paste |
| Does deleting really delete? | Yes | The row goes; snapshots keep the ciphertext up to about 5 days | Same, and deleting the service's key makes every copy unreadable, for all users (the key cannot have been copied out) | The cookie goes | Yes, on that browser | The vault's copy goes |
| Cost per run | none | one local decrypt | one remote decrypt; cache it for the run | one local decrypt | none | a proxy hop on every model call |
| Build and running cost | smallest; $0 | medium; $0 | F plus a cloud account, about 4 to 10 hours, $0.07 to $3 a month ([agent, `r5-kms.md`]) | medium; $0 | small, but the server would have to stop calling OpenRouter itself | $995 to $1,000 a month ([agent, `r5-kms.md` 8]) |
| Fits the owner's words? | fails "no re-paste" | yes; needs one operator secret | yes; needs a one-time cloud setup, no Fly secret | fails "not in the sessions" and "web-inspect" | fails "web-inspect" | sees every prompt |
| Fits ASVS 5.0 14.3.3 (L2: no sensitive data in browser storage or cookies)? | yes | yes | yes | **no** | **no** | yes |

**OpenRouter's sign-in flow (OAuth with PKCE) is not a storage pattern; it is how the key
arrives.** It combines with F or K. It changes three rows: the key never passes through the browser
(A4 cannot read it at paste time); the key is made for this app, so revoking it does not break the
user's other tools; and the user can set a credit limit on it, which bounds what any attacker in
the table can spend.

Three more points the research brief asked about:
- **A vault that stores the key itself** (the brief's row 3.4) is folded into K: the services that
  only store secrets (Doppler, 1Password) hand the app the plaintext, so they are no better than F,
  and HCP Vault is out of scale (section 5).
- **A non-extractable WebCrypto key** in the browser stops the key being exported, not being used by
  script in the page; a `CryptoKey` can be kept in IndexedDB [agent, `r4-standards.md` 2.5]. Pattern
  B stays ruled out by ASVS 14.3.3.
- **This app's session is server-side.** The cookie holds only the session id, and the sessions table
  keeps a SHA-256 of it (`src/product_app/session_store.py:287-297`), so an encrypted-cookie design
  would be a new mechanism, not a change to the existing one.

**Why the limit matters more than the storage.** A thief with the plaintext key calls OpenRouter
directly and never touches our app, so our own budget rails do not bound them. Only the key's
credit limit at OpenRouter does, plus the user revoking the key there.

---

## 4. Fly's own options

| Option | What it is | What the research found |
|---|---|---|
| Fly secrets | Encrypted in Fly's vault, delivered *"as environment variables at boot time"* [agent] | Visible in an SSH session (`fly ssh console -C "printenv"` is Fly's own documented way to view them) [agent, Fly Rails docs]; SSH logs in as root by default [agent, flyctl source]. Setting one restarts the machines; `--stage` defers it [agent] |
| `[[files]]` in `fly.toml` | Writes a secret's value to a file at boot | The value stays an environment variable as well by default; the setting that would stop that (`ignore_app_secrets`) is not settable from `fly.toml` as far as the docs show (UNVERIFIED) [agent]. So it does not remove the environment exposure |
| Machines API `secretkeys` | Encrypt and decrypt with a key Fly holds (types include `xaes256gcm`) | **Not a launched product**: API reference only, the flyctl command is hidden (*"TODO: unhide when we're ready to go public"*), no price, no guide, no SLA, no audit log found [agent, flyctl source and Fly docs]. A Fly employee wrote on 2026-07-04 that the API *"exists"* but the filesystem feature *"is currently not a priority"* [agent, forum thread 21825]. Decrypt works from inside a machine with no token, and is refused from outside [agent]. The app runs as uid 1000 (`Dockerfile:67`), and one user report says a non-root process is refused by the machine socket (UNVERIFIED for this app) [agent] |
| Fly OIDC identity | A machine gets a short-lived signed token naming `org:app:machine`; AWS, Google, Azure and Vault can trust it, so no cloud password is stored | Documented end to end for AWS only [agent, `docs.fly.io/security/openid-connect`]. Same non-root question |
| Volume snapshots | Daily, kept 5 days on `quorum_data` [session] | No snapshot delete command exists; a retention change affects only new snapshots; an organisation member can manage volumes, so can restore one into a new volume (inferred from Fly's role list, not run) [agent]. So a deleted row lives on for up to about 5 days |
| Tokens | Deploy, SSH, exec, org, read-only; 20 years by default | A deploy token can do everything an SSH token can [agent, flyctl source]; `--expiry` sets a shorter life [agent]. Fly documents no GitHub OIDC route, so `FLY_API_TOKEN` stays a stored secret [agent] |
| Logs | Kept 7 days in Fly's log search | No log shipper runs (`docs/adr/0031` rejected one) [agent] |

Found along the way, not W28's to fix: two smoke-test steps in `.github/workflows/deploy.yml`
receive `FLY_API_TOKEN` but run only `curl` [agent, `r1-fly.md` section 8]. Narrowing that is board
row W79's kind of work.

---

## 5. Key services outside Fly

Defined once: a **key management service (KMS)** keeps a master key inside its own hardware and
encrypts or decrypts on request; the app never holds the master key.

| Service | How a Fly machine signs in | Monthly cost at 1,000 to 10,000 decrypts | Audit of each decrypt | Verdict |
|---|---|---|---|---|
| AWS KMS | Fly OIDC token, no stored credential | $1 per key, up to $3 after two rotations; requests inside a free tier of 20,000 a month [agent, AWS price file] | Yes: CloudTrail, on by default, 90 days free, records the account id passed as encryption context [agent] | Realistic. Needs an AWS account on a paid plan and a root login to protect |
| Google Cloud KMS | Workload identity federation with Fly's token | About $0.07 to $0.09 [agent] | Only after turning on Data Access logs [agent] | Realistic, cheapest; Fly gives no setup steps for Google |
| Azure Key Vault | Federated credential, exact match per machine (limit 20) | About $0.003 to $0.03 [agent] | After a diagnostic setting | Fragile: each replacement machine needs a new trust entry |
| HCP Vault Dedicated | Fly OIDC | About $450 [agent] | Yes | Out of scale |
| Self-hosted Vault or OpenBao | Fly OIDC | another always-on machine | Yes, once enabled | Must be unsealed after every restart; out of scale |
| Infisical | OIDC | $0 to $23 per identity; its table marks key management as Enterprise only [agent] | Pro: 30 days | Unclear on the cheaper plans |
| Doppler, 1Password, Cloudflare Secrets Store | — | — | — | Not encryption services a Fly machine can call [agent] |
| Basis Theory, Very Good Security (tokenising proxies) | static key | $995, from $1,000 [agent] | 24 hours (Basis Theory) | Out of scale; they see every prompt; streamed replies, which the app uses (`providers.py:1627`), are undocumented |

Where the key lives and how it rotates [agent, `r5-kms.md`]: AWS KMS keys are generated inside its
hardware security modules and never leave them unencrypted (import is optional); automatic rotation
is yearly by default, and `ReEncrypt` re-wraps a ciphertext inside KMS without exposing the plaintext. Google
Cloud KMS keeps the key-encryption key inside the service; a rotation adds a new version and does
not re-encrypt data; no server-side re-wrap was found. Vault's Transit engine has the best rotation
model (versions, `rewrap`, a minimum decryption version) but must be run by us, or bought as HCP Vault Dedicated at about $450 a month. HCP Vault Secrets is
ended: end of sale 2025-06-30 and end of life by 2026-07-01 at the latest, per IBM's support page.

Every service above is a decrypt oracle for code running as the app (A7, A8). What a key service
adds over F: a stolen database or snapshot decrypts nothing; the master key cannot be copied out,
so the attacker's power to decrypt ends when their access ends (copies they already decrypted stay
read); and each decrypt is logged at a second company,
where a burst of decrypts across many accounts is the signature to alert on. Every design fails
closed if written that way: if the service is down, a run on the user's key does not start, and it
never falls back to the app's key.

---

## 6. How other products keep users' own keys

From [agent, `r3-products.md`], which read vendor pages and, for open-source products, the code.

| Product | Where the key is stored | Cipher | Where the decryption key sits | Paste again after a restart? (inferred from where it is stored) | Shown again? |
|---|---|---|---|---|---|
| OpenRouter (its own BYOK, provider keys) | OpenRouter, per workspace | not stated | not stated | No | No: *"never returned in API responses"* |
| Portkey | Portkey's vault | AES-256; enterprise: envelope encryption with AWS KMS | KMS (enterprise) | No | No |
| Cloudflare AI Gateway | Secrets Store | data keys under a key-encryption key | *"the root key never leaves a secure system"* | No | No |
| Langfuse | Postgres | AES-256-GCM, random IV | environment variable `ENCRYPTION_KEY` | No | last 4 only |
| LobeHub (LobeChat) | Postgres, per user | AES-GCM, random IV | environment variable | No | yes, to the owner |
| LibreChat | MongoDB, per user | AES-CBC with a fixed IV in the latest release (AES-256-CTR, unreleased, since 2026-10-13); no authentication tag | environment variables | Only on a user-chosen expiry (default 12 hours) | No |
| LiteLLM | Postgres | XSalsa20-Poly1305 by default, AES-256-GCM opt-in | environment variable; *"Never change this key"* | No | virtual keys hashed, last 4 |
| n8n | database | AES-256-GCM (new), data keys wrapped, rotation behind a flag | environment variable or a file | No | — |
| Dify | database | RSA-wrapped AES per tenant; optional Azure Key Vault | a private-key file in storage, or Key Vault | No | first 6 and last 2 |
| Cursor | not stored; sent with every request | — | — | once per device | — |
| GitHub Copilot (app) | the device's keychain | — | — | once per device | *"never read back by the UI"* |
| TypingMind | browser local storage | optional AES with a password | the user's password | on every new browser | — |
| Vercel AI Gateway | Vercel, per team | not stated | not stated | No | not stated |
| Open WebUI | the server's user-settings record (and the browser), despite its docs | none found in the code | — | No | yes, to the owner (inferred from the settings round trip, `r3-products.md` 2.7) |
| Retool (self-hosted) | Postgres | AES-192-CBC by default, AES-192-GCM opt-in | environment variable `ENCRYPTION_KEY`; a documented zero-downtime rotation | No | not stated |
| Zapier | its servers | "bank-level encryption" | not stated | only when the upstream credential changes | not stated |
| Make | its servers | AES-256 full-disk encryption (read through a fetch tool) | AWS KMS, for that disk encryption | not stated | No, for its credential requests |

Sources, per row: `r3-products.md` sections 1 and 2 (vendor pages, or the code at a named commit).
OpenRouter's management keys (`/api/v1/keys`) are a different model: they create keys on the **app's**
OpenRouter account, spending the app's credits, so they are not a user's own key [agent,
`r2-openrouter.md` 2].

Patterns:
1. **No server-side product makes the user paste again after a restart or deploy** (inferred from
   where each stores the key; no vendor page says it in words). Re-entry is
   per device for device-held keys, and only LibreChat expires keys on a schedule the user picks.
2. **The decryption key usually sits in an environment variable or a local file beside the
   database**: in 6 of the 9 codebases read (LibreChat, LiteLLM, Langfuse, LobeHub, n8n, Flowise), and
   Retool documents the same. Key services appear in the enterprise tiers (Portkey, Cloudflare,
   Dify's Azure mode).
3. **Of the hosted gateways whose behaviour was read, OpenRouter, Portkey, Cloudflare, LangSmith and
   Langfuse never show a stored key again.** Helicone is the exception: its API returns stored keys
   to an organisation's admins and owners [agent, `r3-products.md` 1.5, read in its code]. Vercel's
   is not stated. Some open-source chat apps show it too.
4. **The recurring failures are not cipher failures.** They are: one tenant reaching another's key
   by id (LibreChat, Flowise, n8n, Helicone advisories); a user-set base URL that makes the server
   send the stored key to an attacker (LobeChat, Langfuse, Flowise, LiteLLM); a master key read out of
   the environment (LibreChat); and tokens in `localStorage` read by page script (Open WebUI).
5. **Rotating the master key is weak almost everywhere.** Formats without a key id cannot hold two
   keys at once.
6. **Binding the ciphertext to its owner is rare** (only Helicone binds the organisation id).
7. **Falling back to the platform's own key is a real design.** Vercel's AI Gateway says: *"If a
   query using your credentials fails, AI Gateway will retry the query with its system credentials"*.
   For this app that would bill the app for a user's run; ADR-0180 forbids it.

Lessons for W28: look keys up only by the signed-in account; send a user's key only to the fixed
OpenRouter host (ASVS 5.0 13.2.4, an outbound allow-list); never read the master key anywhere a
user can steer; store a key id with every row; bind the account id into every encryption; show only
the last 4 characters.

---

## 7. OpenRouter

From [agent, `r2-openrouter.md`] unless marked.

**OAuth with PKCE.** The browser goes to `https://openrouter.ai/auth` with `callback_url`,
`code_challenge` (S256), `state` and optionally `key_label`, `workspace_id`,
`required_workspace_id`. No limit or expiry parameter is documented for that redirect. The server
then posts the returned `code` and its `code_verifier` to `https://openrouter.ai/api/v1/auth/keys`
and receives `{key, user_id}`. Codes expire after 10 minutes.
- **Measured: the exchange works from a server with no key.** A made-up code sent with `curl`
  returned `400 {"error":{"message":"Invalid code","code":400}}` (the docs say 403) [agent].
- **The user sets the credit limit.** OpenRouter's own screenshot of the approval screen shows a
  "Credit limit (optional)" box the user fills in [agent, the image in the OAuth guide]. Whether
  today's screen still has it, and whether there is an expiry field, is UNVERIFIED.
- `POST /api/v1/auth/keys/code` lists `limit`, `usage_limit_type` and `expires_at`, but a keyless or
  fake-key call gets the same 404 as a made-up path, answered by the website rather than the API. It
  looks like the approval page's own backend. Whether an app may call it is UNVERIFIED.
- **No documented call lets the app revoke a key it received** (UNVERIFIED that no undocumented one
  exists). A delete call with the key itself answers 404; deleting keys needs a management key on the
  key owner's account. The documentation implies the user can disable or archive it on OpenRouter's
  Security settings page (U5). Even the user's own management key may not delete it: the
  management-key page excepts keys "provisioned by a Connect client", which may mean OAuth keys
  (UNVERIFIED).
- Each "Authorize" appears to create a new key. Whether reconnecting leaves the old one live is
  UNVERIFIED.

**Key status.** `GET /api/v1/key` costs no tokens and returns `limit`, `limit_remaining`,
`expires_at`, `workspace_id`, `budgets` and `effective_budget`. `limit_remaining` alone can mislead
when a workspace or guardrail budget is tighter. With a fake key it answers `401` *"User not
found."*; with no key, *"No cookie auth credentials found"* [agent]. How it is rate limited is
UNVERIFIED. An intake check must not become a free tester for stolen keys: one message for every
failure, no `limit_remaining` echoed (the 2026-10-13 key-safety report, citing Sysdig's
"LLMjacking" write-up of 2024).

**Limits and errors.** OpenRouter's limits page gives both 402 and 403 for a key at its limit, and a
second page says 403; the reliable field is `error.metadata.limit_source`. Nothing says a request is refused for
what it *would* spend, so one large request may finish above the limit (UNVERIFIED). Search fees are
outside OpenRouter's up-front estimate.

**Calls from a browser.** Measured: preflights to completions, key status and the code exchange all
answer `access-control-allow-origin: *` and allow the `Authorization` header [agent]. So a browser
could call OpenRouter directly, but this app runs the panel, critique, synthesis and judge on its
server; a browser-only design would mean rebuilding that flow in the page or sending the key with
every request.

**The planted-key risk.** Whoever owns or created a key can read every prompt and answer sent with
it, on OpenRouter's Logs page or streamed to their own server by its Broadcast feature, through
settings the app cannot see [agent, OpenRouter's logging and broadcast pages]. So an attacker who
gets their key attached to a victim's account reads the victim's questions. With OAuth, a code the
attacker injects into the victim's callback fails the exchange when the server keeps the verifier
tied to the victim's session and checks `state`.

**The user's account settings reach our calls.** Default plugins with "Prevent overrides", model
allow-lists, privacy settings, a maximum key lifetime and IP allow-lists can make one of the four
models, the judge or web search fail or cost more, for reasons only the user's account shows.

**Leaks and terms.** OpenRouter is a GitHub secret-scanning partner and emails the owner of a leaked
key; automatic disabling is not documented. Its terms make the key's owner responsible for *"all
activity and charges"* on the key, and say nothing about apps holding users' keys (section 3.2 of
the terms; UNVERIFIED whether OpenRouter permits it: a written question to their support settles it).

**Web search.** Under a user's key, OpenRouter's search fees go to the user's account.

---

## 8. Standards: what applies, and whether the decided design meets it

From [agent, `r4-standards.md`]: OWASP ASVS 5.0.0 read raw at tag `v5.0.0`; OWASP cheat sheets at
commit `1a78ae3e`; NIST PDFs. "Meets" is the session's reading for the decided design (F, with
OAuth); "not met" gives the reason it was accepted; "build" means the W28 build must do it and a test in section 13 checks it.

| Item | What it asks, in short | Decided design |
|---|---|---|
| OWASP Cryptographic Storage: minimise storage | Do not store what you need not | Considered: memory-only fails the owner's no-re-paste rule; stored, encrypted, minimal (the key and its last 4) |
| ASVS 14.3.3 (L2) | No sensitive data in browser storage or cookies, except session tokens | Meets: nothing in the browser |
| ASVS 11.3.1, 11.3.2 (L1), 11.3.3 (L2) | Approved authenticated encryption, AES-GCM | Meets: AES-256-GCM (the `cryptography` package already pinned, `pyproject.toml:42`) |
| NIST SP 800-38D §5.2.1.1, §8.3; ASVS 11.3.4 (L3) | 96-bit random nonce; at most 2^32 encryptions per key | Meets: a fresh 12-byte nonce each time; the count is far away at this scale |
| ASVS 8.2.2 (L1) | One user cannot reach another's data by id | Build: look up by the signed-in account only; bind the account id as associated data (measured: a wrong account id raises `InvalidTag`, [agent, `cryptography` 50.0.2]) |
| ASVS 14.2.1 (L1) | No secret in a URL | Build: the key travels only in OpenRouter's exchange response and in the `Authorization` header |
| ASVS 16.2.5, 16.5.1 (L2); Logging cheat sheet | Never log credentials; generic errors | Build: W76 first; tests T2 to T4, T19 |
| ASVS 14.2.3 (L2); OWASP LLM07:2025 | Not sent to third parties; not in any prompt | Build: test T5 |
| ASVS 13.2.4 (L2) | Outbound allow-list | Build: the key goes only to the configured OpenRouter host |
| Cryptographic Storage: keys apart from data | Keep keys in a separate place from the encrypted data | Partly: the Fly secret is not on the volume, so a database copy alone is useless; the same machine holds both while running. The key-service move separates them |
| Cryptographic Storage: encrypting stored keys; Secrets Management §4.2, §7.3 (envelope encryption) | A data key wrapped by a key-encryption key kept elsewhere. Where the two cannot be kept apart, as on one server, wrapping has *"limited value"* but is *"an additional barrier to unskilled attackers"* | Not met: one master key encrypts every user's key directly. On one machine a per-user data key wrapped by the same master key would add little; a key held in a key service would meet it. NIST SP 800-57 §5.5.2 suggests a key per person; the trigger move of CHG-075 brings a key service, and per-user keys there would be the build's choice |
| NIST SP 800-57 §5.5.2 and §9.5.4; Rev. 6 draft items 21 and 22 | A key should protect one person's data, or few; a key protecting many stored keys is the hard case to recover from | Not met, for the same reason: one app-wide master key. Accepted at this scale; recovery is rotation plus users revoking at OpenRouter |
| Key Management cheat sheet: escrow and backup | Data under a lost key is lost; plan a key backup | Not met on purpose (the session's design): no copy of the master key outside Fly's vault, since each copy is one more place to steal it. If it is lost, users reconnect through OpenRouter's sign-in |
| Secrets Management §5.1 | Environment variables *"not recommended unless the other methods are not possible"* | Not met by F, accepted for $0 and no new account (CHG-075); the key-service move meets it (no master key in the environment) |
| Key Management cheat sheet: application code never reads raw keys | | Not met by F, for the same reason; the key-service move meets it |
| ASVS 13.3.1 (L2) | A secrets-management solution such as a key vault, for the whole lifecycle | Partly: Fly's vault holds the master key; a key service holds it without exposing it |
| ASVS 13.3.2 (L2) | Least privilege on secret access | Build: only the run path decrypts; no route, export or admin page does |
| ASVS 13.3.3, 13.3.4, 13.1.4 (L3) | Crypto inside an isolated module; secrets expire and rotate as documented; the critical secrets and their rotation written down | 13.3.3 not met (the app decrypts with a master key it holds), accepted for $0 and no new account (CHG-075); the trigger move meets it. 13.3.4 and 13.1.4: build (the master key yearly and after suspicion; the user's own key not force-rotated) |
| ASVS 14.1.1, 14.1.2, 14.2.4 (L2) | Classify the key as sensitive; write down and apply its protection | Build: `docs/43-privacy-data-governance.md` and `docs/48-data-retention.md` list it; this file is the protection record |
| ASVS 14.2.7 (L3) | Retention, with deletion on a schedule | Partly: kept until the user removes it or deletes the account (CHG-075, CHG-076); no rule yet for a key left unused |
| ASVS 11.2.1, 11.5.1 (L2) | Industry-validated libraries; random values from a CSPRNG, at least 128 bits | Build: the `cryptography` package; nonces, `state` and the PKCE verifier from Python's `secrets` module, as the Google sign-in already does |
| ASVS 11.7.2 (L3); Secrets Management §2.5 | Expose the minimum while processing | Build: decrypt once per run, keep it only for the run |
| ASVS 7.4.2 (L1), 7.5.2 (L2) | Account deletion ends every session; users see and end sessions | 7.4.2: deletion already ends sessions; the build makes it delete the key too. 7.5.2: partly, as today (sign out everywhere exists; no session list) |
| Secrets Management §2.6 (audit), §2.7.4 (expiry), §9 (incident response) | Who used a secret and when; expire where possible; a written response | Build: section 9 items 5 and 10. Expiry: whether an OAuth-issued key can carry one is U1 and U2 |
| Key Management cheat sheet: never stored in plaintext | | Meets |
| OWASP HTML5 Security and Session Management cheat sheets | Nothing secret in browser storage; a new session id at sign-in | Meets: nothing in the browser; sign-in already issues a new session (`auth.py:812`) |
| OWASP Top 10:2025 A04 | Authenticated encryption, no IV reuse, store keys in a hardware or cloud module | Meets except the last, which the trigger move meets |
| NIST SP 800-57 §7 (key states) | Keys move from active to deactivated to destroyed, with a record | Build: each master-key version is active, retired (decrypt only) or destroyed, logged in the audit trail |
| NIST SP 800-57 §5.2 | One key, one purpose | Build: a new master key, not `QUORUM_TOKEN_SECRET` (which already serves three purposes, `docs/analysis/2026-10-17-asvs-5-level-2-check.md`) |
| ASVS 11.1.1, 11.1.2 (L2); NIST SP 800-57 §5.5.2 | A written key policy, an inventory, a compromise-recovery plan | Build: section 9 items 1 and 10, written as a runbook entry |
| ASVS 11.2.2 (L2) | Keys replaceable and data re-encryptable | Build: a key version on every row; test T12 |
| NIST SP 800-57 Table 1 (Rev. 5, final) | A data or key-wrapping key: under 2 years of use; decrypt for up to 3 years after | Build: rotate the master key at least yearly and after any suspicion. A Rev. 6 draft (2025-12-05) would state this as an amount of use instead [agent] |
| ASVS 16.5.3 (L2) | No fail-open | Build: never fall back to the app's key (test T6) |
| OWASP API4:2023; LLM10:2025 | A spending limit on every third-party key, or billing alerts | Partly: the user sets the limit at OpenRouter (OAuth screen, or the key's settings for a pasted key); the app adds the user's own window and per-run cap |
| ASVS 14.2.6 (L3) | Return the minimum | Meets: last 4 characters only |
| ASVS 14.2.2, 14.3.2 (L2), 14.3.1 (L1) | `Cache-Control: no-store`; clear client data at sign-out | Build: on every key route (row W90 covers the rest of the app) |
| ASVS 16.3.2, 16.4.2, 16.4.3 (L2) | Log access, protect logs, ship them elsewhere | Partly: an audit row per key event in the app's database; off-machine only with a key service's log |
| ASVS 10.1.1, 10.1.2, 10.2.1 (L2); RFC 9700 §2.1, §2.1.1; RFC 7636 §4.2 | OAuth client: exchange on the server, PKCE S256 (never `plain`), a one-time `state` bound to the session | Build: copy the Google sign-in pattern (`google_signin.py`), without row W80's flaw |
| ASVS 10.2.2 (L2) | Mix-up defence with two authorization servers | Build: becomes applicable (Google and OpenRouter); a distinct callback path per server |
| Secrets Management §2.7.2 | User credentials are not rotated on a schedule | Meets: the user's own key is never force-rotated |
| NIST SP 800-88 Rev. 2 (final 2025-09-26) | Cryptographic erase works only when every copy of the key is destroyed | Recorded: deleting a row leaves snapshot copies for up to 5 days; destroying an old master-key version makes them unreadable only to someone who never copied that key |
| GDPR Art. 32, 33, 34; India's DPDP Act 2023 s.8 and Rules 2025 (rules 6 and 7 from about May 2027) | Security, breach notice (GDPR: 72 hours; DPDP: users and the Board without delay, detail within 72 hours, no exemption for encrypted data) | Build: the privacy text and the incident runbook. Whether an API key is personal data is UNVERIFIED (a legal question) |

ASVS 7.4.3 and 7.5.1 do not apply literally: an OpenRouter key is not a sign-in factor and does not
affect sign-in [agent]. The ASVS 13.2.1 lead ("an OpenRouter key is an unchanging API key") was
overstated: the item is about the app's own components.

---

## 9. Operations

1. **Rotating the master key.** Each row carries the master-key version. A new version is added as
   a new Fly secret (the old one kept); new writes use it; a re-wrap job moves old rows; when none
   remain, the old version is removed and the app refuses it. A crash halfway leaves every row
   readable under one of the two versions (test T12). Setting the secret restarts the machine; with
   auto-stop, a staged secret also arrives at the next start [agent, Fly secrets docs].
2. **The user replaces their key** (or reconnects by OAuth): the new ciphertext replaces the old
   row in one transaction; a run in progress treats the replaced key as removed: the page asks, stop by
   default (the session's design, following CHG-078; test T26).
3. **Removal and deletion.** "Remove key" deletes the row; account deletion deletes it with the
   account (`session_store.py:964` gains the table). `PRAGMA secure_delete` on that store (board
   row W86) stops deleted bytes lingering in free pages. Snapshots keep the ciphertext for up to
   about 5 days; it is useless without the master key. The real off switch is the user revoking the
   key at OpenRouter, and the page says so.
4. **Backups.** Every copy of the database is a snapshot or a manual download; each holds only
   ciphertext. The master key is in none of them.
5. **An audit trail without the key.** One row per event: account id, a key fingerprint (a SHA-256
   of the key, not a prefix), the action (added, used, replaced, removed, decrypt failed), the run
   id and the time. The user sees the date added and the date last used.
6. **Spend limits.** The user's credit limit at OpenRouter is the outer bound. Inside the app, the
   user's own window and per-run cap (decision on tension 3).
7. **What the user sees.** "Connected: OpenRouter key ending in `ab12`, added 17 Oct, last used
   18 Oct", a Remove button, and a link to revoke or limit it at OpenRouter. Never the full key: not
   in a response, the page, an export, an error or the OpenAPI examples.
8. **Session theft and XSS.** A stolen cookie can spend within the limits, never read the key.
   OAuth keeps the key out of the page. Paste, if ever added, gets its own page with no model
   output, a strict content security policy, `autocomplete="off"`, and `Cache-Control: no-store`.
   W75 (no inline scripts) comes first.
9. **Several devices.** Per-account storage works on every device; signing out on one device ends
   only that session.
10. **If the master key leaks**, the runbook entry the build writes, in this order:
    1. who acts: the owner, the same day;
    2. contain first: revoke the Fly and GitHub tokens that may have leaked, remove anyone who should
       not have access, and stop the machines if they may be running hostile code. A new secret set
       while the leaked access still works would leak too;
    3. then, from a trusted deploy, rotate the master key, re-wrap every row and destroy the old
       version. This protects only what is written afterwards: any copy of the database the
       attacker took stays readable with the old key, for ever;
    4. so tell every user whose key was stored at the time to revoke it at OpenRouter (only they can);
       until they do, treat each such key as stolen;
    5. move the master key to the key service (the trigger, CHG-075);
    6. check the law that applies for the notice deadline (GDPR: 72 hours; DPDP: without delay);
    7. record the event and what was done.
11. **Privacy text.** What is stored, where, how encrypted, who can reach it, how long, how to
    delete it; sub-processors (Fly, Sentry, OpenRouter, and a key service if used); that OpenRouter,
    not this app, bills the user; that OpenRouter lets a key's owner read the prompts sent with it.
12. **Failure posture.** If the master key or key service is unavailable, the run on the user's key
    does not start. It never falls back to the app's key. (An ADR records this: ADR-0180.)
13. **Validation at intake.** With OAuth, the key comes from OpenRouter, so a format check and one
    `GET /api/v1/key` call confirm it works. One message for every failure; nothing echoed.
14. **Python memory.** A decrypted key is a Python string and cannot be wiped (CWE-316). Decrypt
    once per run, pass it only to the provider calls, never keep it beyond the run. The OWASP Secrets
    Management cheat sheet calls stronger in-memory protection usually overkill for this threat
    model. A separate decrypt-and-call service on a second machine would separate duties, but on one
    Fly organisation the same tokens reach both; not worth it at this scale.
15. **If the master key is lost** (deleted, or the Fly app recreated): every stored key becomes
    unreadable. Users reconnect through OpenRouter's sign-in (connect, approve, set a limit) and
    should revoke the old key there, since it may still be live (U6); the page says why. No copy
    of the master key is kept outside Fly's vault (the session's design: a copy is one more thing to
    steal).

---

## 10. Failure modes of this one-machine Fly app

| # | Failure | What the design does |
|---|---|---|
| 1 | Master key and database on the same machine | A database copy alone is useless; live code execution reads both. The key-service move takes the master key off the machine |
| 2 | The master key in an environment variable | Read once at start; never logged; the settings object never printed (W76 covers `model_dump_json`); the sandboxed PDF reader already gets an empty environment (`source_fetcher.py:556`, `env={}`) [agent] |
| 3 | Snapshots keep deleted rows for up to 5 days | Ciphertext only, useless without the master key; said in the privacy text. Rotating the master key and destroying the old version makes old copies unreadable only to someone who never copied the old key |
| 4 | Fly tokens last 20 years by default | Two app deploy tokens expire in 2046 [session]. Shorter expiries would bound A7 for every design, but no board row owns Fly token lifetimes yet (W79 and W95 cover the disclosure route, key replacement and the key list); the build prompt asks for one |
| 5 | Logs kept 7 days | Redaction (W76) and tests T2 to T4 |
| 6 | Sentry | No `before_breadcrumb` hook today. At send time the whole event (exception values, messages, extra data, breadcrumbs, spans) is swept for key-shaped text (`main.py:182-202`, ADR-0163), and request headers are kept only for an allow-list without `Authorization` (`main.py:159-169`). The patterns still miss keys glued to a word, percent-encoded or without their prefix; W76 widens them [agent, `r6-repo.md` Q8]. Whether Sentry's own server-side scrubbing is on is UNVERIFIED (the owner's Sentry project settings) |
| 7 | Python strings stay in memory | Decrypt per run, keep for the run only |
| 8 | One process serves pages and decrypts | Accepted at this scale (section 9 item 14) |
| 9 | A stop or deploy mid-run | The run is lost as today; the stored key survives; nothing falls back |
| 10 | The volume is lost | Keys are lost; users reconnect through OpenRouter's sign-in and revoke the old keys there; the page says so |
| 11 | The app's key and a user's key confused | Associated data binds the account id; tests T6 and T9 in both directions |

---

## 11. The judge, peer critique, web search, and what the page shows

- **The judge.** On a user-key run the judge runs on the user's key (the owner's words of
  2026-09-23 16:17:23Z). Today `judge_configured()` needs both the operator's judge key and
  `QUORUM_EVAL_JUDGE_MODEL_ID` (`evaluation.py:2457-2470`), and the judge also passes the app's money
  rails (`query_run_orchestration.py:2556`). Under a user key the judge needs only the model id, and
  is priced as a `by_stage` row on the user's estimate.
- **Peer critique and live execution.** Three places gate on the app's live flag rather than on "a
  key that may be spent": `providers.py:1005-1006`, `debate.py:1818`, `synthesis.py:1473` [agent].
  With production's flag off (`fly.toml:80`), a user-key run would be simulated unless all three
  change. ADR-0121's rule stands: one predicate decides "this run holds a key that may be spent".
  A fourth place reads the app's posture, for the page's copy: `_peer_critique_in_effect`
  (`main.py:402`) needs the peer flag, the live flag and the app's own key [session: read in the
  code].
- **When the judge runs.** The run's status becomes COMPLETED at `query_run_orchestration.py:1664`.
  Two paths then evaluate the finished run: the worker's terminal save (`_persist_terminal_run`,
  called from the `finally` at `:1146`, which evaluates through `_result_response` at `:1791`) and a
  page read of the result (`_result_response` at `query_runs.py:1114`). Whichever comes first makes
  the first judge call. Both share the evaluation memo (`query_run_orchestration.py:2840-2850`) and
  the judge's verdict memo. A read calls the judge again only when
  both memos miss, as after the verdict memo evicts the run (#216). A restart never leads to a
  repeat call: it empties the in-memory runs too, so a read then answers 404
  (`query_run_orchestration.py:1831-1838`, `query_runs.py:1106-1113`) [session: read in the code].
  The 2026-09-29 raw map said the judge runs when the result is read, and the comment at
  `main.py:1745-1751` says the first call is inside `_persist_terminal_run` and that #216's repeat
  call also follows a restart; all three are out of date (the comment is for a later code pull
  request). So under a user key the judge is a stage of the run, and a removal during the run
  follows the owner's rule (ask, stop by default). The rule (ADR-0180 decision 8, the session's
  design; test T29): for a run on a user's key no repeat call is made, on any key, and a verdict
  already paid for is kept with its cost record.
- **Only answer slots record which key paid today**; debate, synthesis and judge calls record no
  credential source [agent, `r6-repo.md` C]. The receipt needs it on every stage.
- **Web search.** OpenRouter's search fees land on the user's key. The app's own Tavily key also runs
  inside user runs (a supplement when an answer has no sources, `providers.py:875-876`, and a
  fallback, `:976`) and Tavily spend is counted nowhere [agent]. The owner decided that a user-key run
  never spends the app's Tavily key; a user's own Tavily key is an optional later addition (CHG-078).
- **What `/status` and the page show.** `/status` describes the deployment, never an account; it
  can say whether the feature is on. The readiness banner today says for production *"Live execution
  is turned off. Every model answer and the synthesis will come from Quorum's local simulation
  helpers."* (`static/app.js:1263-1272`) [agent]. That would be false for a user who has connected a
  key. The simulated-result banner must read the run's credential source. The readiness banner is
  shown before any run and reads `/ready`, which takes no session (`main.py:1376`), so it must read
  the signed-in account's key status from the key's own status route. The readiness probe keeps one
  cached key verdict per process (`readiness.py:76`, `_key_auth_state`), so a per-account key needs
  its own state [session: read in the code]. The receipt says "Paid by your OpenRouter key ending
  in `ab12`". The watchdog
  (`scripts/live_posture_check.py`) watches the app's own posture and must not treat a user-key run
  as drift.

---

## 12. Constraints the build must respect

All measured on `main` [agent, `r6-repo.md`] unless marked.

1. **No decorator room.** Every decorated function in top-level `src/product_app/*.py` counts toward
   a cap of 55, and the count is 55 [session: an `ast` walk with the test's glob printed 55;
   `tests/unit/test_mutation_test_set_integrity.py:285`]. Routes, validators, properties and
   static methods all count. A new route uses `add_api_route`; a new validator uses `Annotated`
   constraints or a check inside the handler, or the cap is raised in a reviewed change.
2. **The credential-source enum is pinned** to `{app_owned, not_configured, byo_openrouter}`
   (`tests/unit/test_enum_membership_pins.py:183-185`).
3. **W28's board row is frozen.** `tests/unit/test_one_status_review_round_1.py:247-285` asserts
   the row equals its text at `b66b107`, reads PENDING, and has the needle `credential_source =
   ProviderCredentialSource.APP_OWNED`. `tests/test_planted_false_claims.py` I1 and I3 plant on W28.
   W28 is the only PENDING row on the board, so those tests cannot simply move to another real row.
   If the build keeps that line, W28 can never read DONE (app-key runs remain for anonymous users);
   if it removes it, W28 reads DONE after the first pull request while later ones remain. So the
   first build pull request rewrites the row's needle (a `PRESENT@<sha>` or `ABSENT` form,
   `scripts/check_open_work.py:717-760`) to one only the LAST W28 pull request removes, and moves
   the three tests to a synthetic row, in the same pull request, with a reason.
4. **ADR-0121 is pinned PROPOSED.** `tests/unit/test_live_posture_check.py:3119` lists exactly
   ADR-0001, 0014, 0060 and 0121 as not in force, and I7a/I7b need ADR-0121's status text. So
   ADR-0121 is not edited; ADR-0180 supersedes it in its own text.
5. **The session store's schema** may change only through a guarded `schema_migrations` block
   (`session_store.py:282-286`); `_migrate_spend_key` (`:447-489`) is the pattern. No `PRAGMA` runs in
   that store today; `secure_delete` is W86.
6. **Every new setting goes into `.env.example`** (`tests/test_doc_gate_consistency.py:1615`).
7. **Risk constants.** `tests/unit/test_risk_constant_pins.py` covers `auth.py`, `config.py`,
   `main.py`, `costs.py`, `session_store.py`, `google_signin.py` and others; a new constant there needs
   a triage entry, and a new key-holding module should be added to its list.
8. **The security-measures list** (`docs/41-security-controls.md`) uses every id the two-digit rule
   allows: since W85 (#575) it holds SC-01 to SC-99, written out in
   `tests/unit/test_security_controls_cite_real_tests.py`, whose pattern is `SC-[0-9][0-9]` [session:
   read on `main` after #575]. A new measure for W28 needs a reviewed change to that rule first. Its
   CTRL-006 line cites W28's needle as proof that BYOK is not built and goes false when the build
   lands.
9. **The 422 handler returns a validator's message text** (`main.py:925-974`): a key validator must
   never put the value in its message.
10. **Settings hold keys as plain `str`**, hidden from `repr` but printed by `model_dump_json`
    (`config.py:91, 155, 172`). The master-key setting must not repeat that (W76).
11. **The OAuth callback** must check `state` before it discards the pending sign-in: the Google
    callback takes the pending entry at `google_signin.py:675`, before the `state` comparison at
    `:679` (row W80).
12. **New routes and the API contract.** A route included in the OpenAPI schema must appear in
    `openapi.yaml` (`make openapi-check`) and is driven by the Schemathesis tests (`make
    api-contract`); of the Google sign-in routes, the callback, sign-out-everywhere and the two idle-session routes use
    `include_in_schema=False` (`google_signin.py:849-869`), while the start and sign-out routes are in
    the schema; a connect route copied from the start route needs `openapi.yaml`.
13. **Signatures that carry the credential source.** 14 test files (29 lines) pass
    `credential_source=ProviderCredentialSource.APP_OWNED`, and 16 files (34 lines) mention
    `credential_source` [session: `git grep -l` and `git grep -n` over `tests`]; changing that signature touches all of
    them. `tests/e2e/test_release_hardening_workflow.py:190` asserts the set is exactly `{"app_owned"}`,
    which a truthful `NOT_CONFIGURED` for simulated runs (T16) changes.
14. **The cited-paths check reads only added lines** (`tests/unit/test_cited_paths_resolve.py`), so a
    moved file can leave old citations dead without failing.
15. **Prerequisites, in CHG-061's order:** W85, W86, W100, W87, W88, W80, W75, W76.

---

## 13. The tests the build must pass

One list, merging the 11 failure-mode tests of the 2026-09-29 map (M1 to M11, in the raw map outside
the repository) and the 21 key-safety tests of 2026-10-13 (K1 to K21, in the key-safety report
outside the repository). Every test uses a canary key of the real shape (`sk-or-v1-` and 64 hex
characters) and a positive partner proving the thing checked exists. T24 to T32 were added by this
research: T24, T26 to T28 and T30 to T32 for the owner's decisions; T25 and T29 for the session's design.

| # | Test | From | Red when |
|---|---|---|---|
| T1 | Every response body and header over every route, after intake, during a run and after removal, is free of the canary and its 64-hex body. Partner: the status route shows exactly the last 4 | K1, M1 | any route echoes the key |
| T2 | Stdout logs and captured log records across intake, run and removal hold no canary. Partner: a log call site was handed the key and printed it redacted | K2, M2 | a log line interpolates the key |
| T3 | Sentry events, transactions and breadcrumbs (real client, production hooks), including an exception whose message holds the key and a later unrelated error, hold no canary. Partner: the events exist | K3, M2 | the secret sweep is removed |
| T4 | Redaction table: glued to a letter, digit or underscore; percent-encoded; no prefix; upper case; behind a label the patterns do not list; plus exact-value redaction of a live key. Partner: the plain shape was already redacted | K17, M2 | the old word-boundary pattern returns |
| T5 | No prompt body holds the canary across every call of a run. Partner: the question is in the prompt and the `Authorization` header carries the user key once per call; the call count is exact | K4, M3 | the key enters a prompt |
| T6 | Each stage (answers, debate, synthesis, judge) carries the user key on a user-key run and the app key otherwise, with an exact count per stage; a 401, 402 or 403 on the user key is never retried on the app key | K5 | a stage uses the wrong key or falls back |
| T7 | The SQLite main file and its WAL hold no canary. Partner: the ciphertext row exists with a 12-byte nonce and a key version | K6, M4 | plaintext storage |
| T8 | No canary in the sessions table, the session objects' printouts, run history, the feedback store, telemetry or any export. Partner: each store was written | K7, M4, M5 | the key is put on a session or record |
| T9 | A row copied from account A to account B fails to decrypt, with zero provider calls. Partner: A's row decrypts | K8 | the account id leaves the associated data |
| T10 | A ciphertext with one byte flipped is refused, with zero calls. Partner: the untouched row decrypts | K9 | an unauthenticated mode |
| T11 | With the feature on, production refuses to start without the master key; with the feature off it starts without one. Partner: on, it starts with one | K10 | a per-process fallback key, or a refusal that blocks a feature-off deploy |
| T12 | Rotation: v1 rows decrypt after v2 is added; re-wrap moves them; removing v1 fails closed for any row left on it; a crash halfway leaves every row readable | K11 | the version column is ignored |
| T13 | Session B cannot see, use or remove A's key; two sessions of the same account both see it. Partner: A sees and uses it | K12, M6 | lookup by session or by a request field |
| T14 | Remove, sign-out, sign-out-everywhere, account deletion, idle expiry, a new session at sign-in, restart and deploy each do exactly what decision 2 says. Partner: the key survives CSRF rotation and a restart | K13, M7 | a path deletes when it should not, or forgets to |
| T15 | Removal mid-run, "stop" chosen or no answer: remove after the answer calls; exactly 4 answer calls and 0 debate, synthesis and judge calls; the recorded status says why. Remove-then-add also stops the run. Partner: the control run makes every call | K13, M8 | a stage uses the copy made at run start |
| T16 | The resolver's table: feature setting by app key by user key by global ceiling by live flag; the resolved key and recorded source for each (`NOT_CONFIGURED` for a simulated or blanked run); no app key plus a user key is not "misconfigured" | M10 | a hard-coded source, or the check reading the app key |
| T17 | The feature off gives exactly today's calls, key and events; the key routes answer 404. Partner: on gives 200 | K21, M9 | the resolver changes the default path |
| T18 | Missing CSRF: 403; legacy test path: 403; an anonymous session: 403 and can never hold or use a key; the connect start route called with a `key` query parameter: 400, the value never logged; intake and status carry `Cache-Control: no-store`. Partner: a signed-in cookie with CSRF gives 200 | K15, M11 | a check is removed |
| T19 | An invalid key's 422 holds no canary, with a validator that quotes its input. Partner: the 422 is returned | K16, M11 | the handler forwards the validator's message |
| T20 | Intake attempt N+1 in the window: 429 with exactly N outbound checks; one message for invalid and revoked keys; no `limit_remaining` in the response | K14 | the limiter is removed |
| T21 | OAuth: a `state` mismatch is refused; the verifier never reaches the browser; the callback query is redacted from logs and Sentry; exactly one exchange call; the pending entry is checked before it is discarded | K18 | no `state` check |
| T22 | Browser: after intake the canary is absent from localStorage, sessionStorage, IndexedDB, cookies and the DOM | K19 | the page keeps the key |
| T23 | No `'unsafe-inline'` in `script-src` on any HTML route | K20 | it is reverted |
| T24 | A user-key run makes zero calls on the app's Tavily key. Partner: an app-key run whose answer has no sources still calls it | CHG-078 | a user run spends app money unseen |
| T25 | The result banner reads the run's credential source, and the readiness banner reads the signed-in account's key status from the key's own route (`/ready` has no session): a user-key run, and a signed-in user with a connected key, are never told the answers will be simulated. Partner: an app-key simulated run, and a user with no key, still are | new | a banner reads only the app flag |
| T26 | Removal or replacement mid-run, the question: pressing Remove, or connecting a new key, during a run asks whether to stop or finish; "finish" makes exactly the remaining debate, synthesis and judge calls on the key the run started with, and that key is gone (removed, or replaced by the new one) once the finished run is saved; never the app's key. Partner: "stop" gives T15's counts | CHG-078 | the question is skipped, finish uses the app's key, or the old key outlives the run |
| T27 | The user's limits: with a $5 window and a $0.50 cap, a run estimated at $0.62 is held for exactly one question and makes zero calls before the answer; "yes" runs it, "no" makes zero calls; a run of $0.40 with $4.70 already spent (under the cap, past the window) is also held for exactly one question; the number of runs the window allows is exact. Partner: a run under both limits starts with no question | CHG-078; failure mode 4 of the 2026-09-23 page | a limit is skipped, or the count is wrong |
| T28 | Sign out everywhere: the tick box "Also remove my OpenRouter key" is ticked by default; ticked deletes the key and ends every session, unticked ends the sessions and keeps the key. Partner: both ways end every session | CHG-076 | the default flips, or the tick is ignored |
| T29 | The judge's repeat call: on a user-key run, a verdict obtained when the run finished stays, with its cost record, after the key is removed; with the run still in memory and both the evaluation memo and the verdict memo missed (evicted the way `tests/integration/test_judge_preflight_respects_the_spend_rails.py:210-216` does), a read makes zero judge calls on any key. Partner: the same eviction on an app-key run makes exactly one repeat call, on the app's key; and the user-key run's first judge call is exactly one, on the user's key | ADR-0180 decision 8 (the session's design) | a user-key run's judge is called again, falls back to the app's key, or a paid verdict is dropped |
| T30 | The no-limit warning: when `GET /api/v1/key` reports no limit, the Connected panel shows the warning and the link; with a limit it shows the limit and no warning; runs work in both. Partner: the limit shown equals the one reported | CHG-077 | the warning is missing, or it blocks runs |
| T31 | No route accepts a pasted OpenRouter key: a key reaches the store only through OpenRouter's code exchange. Partner: the connect flow does store a key | CHG-077 | a paste route appears |
| T32 | A second run on a user's key while one is running gets the same 409 as today, and the abuse rate limits still apply. Partner: one run starts | CHG-078 | a user-key run skips the one-at-a-time rule or the abuse limits |

---

## 14. The decisions as asked

Each was asked with the session's recommendation marked, except the four transcript-only
statements, which had none; each came with an example except tension 4 and the four statements, which
quoted the owner's own words, and D6, which listed the conflicts. The option texts were the session's. The owner's answers are in section 15.

| # | Question | Example | Session's recommendation |
|---|---|---|---|
| D1 | Where a key lives (settles tension 2 and the 2026-09-24 hard stop) | Priya connects her key at 10:00; Fly stops the idle machine at 10:40; a deploy restarts it at 11:00; at 11:05 she asks a question | Database, encrypted, master key a Fly secret |
| D2 | Per account or per browser session (settles tension 1) | Priya connects on her laptop, then opens the site on her phone | Per account, in its own table; sessions only prove who is asking |
| T4 | What *"It should not need fly secrets settings"* means | (the owner's sentence, with the one before it) | It means the per-run flags: a user-key run needs no operator setting; one master key set once is acceptable |
| Intake | How the key arrives | Priya clicks "Connect OpenRouter", approves on openrouter.ai, types a credit limit such as $5, and is back in seconds; or she pastes a key copied from OpenRouter | OpenRouter's sign-in (OAuth with PKCE) only, after the owner's free trial |
| T3 | Limits on a user-key run | Priya's run is estimated at $0.62 | The user sets a budget window ($5 default) and a per-run cap ($0.50 default), and is asked before crossing either |
| Tavily | The app's web-search key on a user-key run | Two of Priya's four answers return no sources | A user-key run does not use the app's Tavily key; then, after the owner's question, a user's own Tavily key as an optional later addition |
| D5 | Removal mid-run (EDGE-013) | Priya removes the key after the 4 answers came back | Stop at the next step; then, after the owner's question, ask her, with stop as the default |
| D4 | A key entered before sign-in | On a shared library computer someone connects their own key and walks away; Asha signs in as herself | Not possible: the key controls appear only after sign-in, so nothing carries over |
| D6 | FR-012, AC-025, AC-026 | The conflicts listed in section 18 | Optional, two postures; AC-026 keeps "no key in the browser" |
| Quotes | Whether the four transcript-only statements still hold | | — |
| Snapshots | A removed key's ciphertext in snapshots for up to 5 days | Priya removes her key on Monday | Accept and say so in the privacy text |
| No-limit key, lost device, key-service trigger | Improvements the session offered after the owner asked for them | Priya leaves the limit box empty; she loses her phone; a token is suspected | Warn and link; offer to remove the key, ticked; move on a trigger |
| Correction | Decision 1's option text understated a theft: copies taken stay readable after rotation | An attacker takes a snapshot and the master key on Monday; we rotate on Tuesday | Keep the Fly secret |

---

## 15. The owner's answers

Given in the question tool on 2026-10-17 between 17:02Z and 19:32Z UTC (transcript `8267786b`). The
option texts were the session's; the choices, and the questions the owner typed, are the owner's.
The CHG rows quote them in full.

| Question | The owner's answer | CHG |
|---|---|---|
| D1, where a key lives (settles tension 2, lifts the 2026-09-24 hard stop for this one case) | "Database, Fly secret (Recommended)" | CHG-075 |
| When the master key moves to a key service | "On a trigger (Recommended)": if a Fly or GitHub token is ever suspected, or a security review asks | CHG-075 |
| A removed key's copy in snapshots for up to 5 days | "Accept, say so (Recommended)" | CHG-075 |
| D2, per account or per session (settles tension 1) | "Per account (Recommended)" | CHG-076 |
| D4, a key entered before sign-in | "Nothing carries (Recommended)" | CHG-076 |
| A lost device | "Offer to remove key (Recommended)": a tick box on sign-out-everywhere, ticked by default | CHG-076 |
| Tension 4, "should not need fly secrets settings" | "Flags only (Recommended)" | CHG-077 |
| How the key arrives | "OpenRouter sign-in only (Recommended)" | CHG-077 |
| A connected key with no spending limit | "Warn, link to fix (Recommended)" | CHG-077 |
| Tension 3, limits | "User sets both (Recommended)": a budget window ($5 default) and a per-run cap ($0.50 default) | CHG-078 |
| Tavily on a user-key run | first a typed question (*"can we ask the user to provide the Tavily key? Should this Tavily key be a prerequisite along with the OpenRouter key, or what is your expert suggestion here?"*); then "Optional, added later (Recommended)" | CHG-078 |
| D5, removal mid-run | first a typed question (*"Can we give this option to the user as to what the user wants: whether the user wants it to be stopped or whether the user wants the run to use that key?"*); then "Ask her, default stop (Recommended)" | CHG-078 |
| D6, FR-012, AC-025, AC-026 | "Optional, two postures (Recommended)" | CHG-079 |
| The four transcript-only statements | all four still hold | CHG-080 |
| The correction to decision 1's option text (19:31:21Z) | "Keep the Fly secret (Recommended)" | CHG-075 |

The owner also asked whether the session agreed with these decisions or had better suggestions,
and, about a note that whoever can deploy can read a stored key, what the most correct approach is.
The session's view on both, which is not a decision: it agrees with the decisions, and it offered
the improvements above, which the owner then chose; and no design that runs the panel on the server
prevents a deploy-access reader, so the decided design limits the damage (a dedicated key with a
credit limit the user sets, revocation at OpenRouter, a record of every use) and the circle able to
deploy should stay small (2-step login on GitHub and Fly; short-lived Fly tokens, which no board row
owns yet). This view reached the owner in chat in the session's closing message, at 20:53:10Z UTC; it
is recorded here and in CHG-080.

**A correction the owner was shown.** Review round 1 (Codex) found that decision 1's option text
understated a theft: it said a stolen master key works offline "until we rotate it", but database
copies an attacker already took stay readable with the old key for ever. Rotation protects only what
is written afterwards; the remedy for keys stored at the time is that their owners revoke them at
OpenRouter, under every design. Told this (asked at 18:47:22Z, answered at 19:31:21Z UTC), the
owner kept the Fly secret (CHG-075).

---

## 16. Still UNVERIFIED, and the owner's trials

**The owner's trials** (the session did not run them; full steps with undo are in `r2-openrouter.md`
and `r1-fly.md` in the evidence folder):
1. **OpenRouter OAuth, about 20 minutes, a throwaway account, free except an optional step that
   costs cents:** screenshot today's approval screen (is the credit-limit box there? an expiry
   field?); try `limit` and `expires_at` on the redirect; watch the browser's network tab while
   clicking Authorize; exchange the code from a terminal; check the key appears in the account's key
   list and can be disabled; reconnect and see whether the first key stays live; disable it and see
   the error. Settles U1 to U8 below.
2. **Fly `secretkeys`** (only if the owner wants Fly's own key service considered): a one-hour trial
   token; generate a throwaway key; encrypt and decrypt over SSH; check the associated data is
   enforced and whether the app's own user can reach the socket; delete the key; revoke the token.

**Still UNVERIFIED:**
- U1 today's OpenRouter approval screen still has the credit-limit box; whether it has expiry;
- U2 whether `limit` or `expires_at` on the redirect is honoured;
- U3 who may call `POST /api/v1/auth/keys/code`;
- U4 callback codes are single-use (stated only for headless codes);
- U5 OAuth keys appear in the user's key list and can be disabled there;
- U6 reconnecting leaves the old key live;
- U7 a key at its limit gets 402 or 403; one request can overrun;
- U8 how `GET /api/v1/key` is rate limited;
- U9 whether OpenRouter disables leaked keys automatically, and whether its terms allow an app to
  store users' keys (written questions to OpenRouter support);
- U10 whether the app's non-root user can reach Fly's machine socket (matters for a key service);
- U11 Fly `secretkeys`: price, limits, audit, whether associated data is enforced;
- U12 whether organisation-scoped Fly tokens exist (`fly tokens list --scope org`, the owner's);
- U13 whether an API key is personal data under GDPR or DPDP (counsel);
- U14 decrypt latency from Fly's `iad` region for each key service;
- U15 whether AWS KMS needs a paid AWS plan from day one.

---

## 17. Where the earlier W28 documents went

| Earlier document | What it held | Where it is now |
|---|---|---|
| `docs/analysis/2026-09-23-byok-failure-modes.md` (keeps its path: the frozen W28 row, ADR-0121 and ADR-0123 cite it) | 8 failure modes | Modes 1 to 3 → tests T1 to T15; mode 4 → tension 3 and T27; mode 5 → T6 and section 11; mode 6 → T20; mode 7 → closed by ADR-0123; mode 8 → section 11 and T25. A superseded note at its top |
| `docs/analysis/2026-10-16-w28-decision-research.md` | The six decisions, product quotes, OAuth | Sections 3, 6, 7, 14, 15. Its memory-only recommendation is overtaken by the owner's words of 2026-10-17. A superseded note at its top |
| The plan on branch `w28/byok-pr1-plan` (draft #525) | The tree's key path, the six decisions, the smallest first pull request, two repairs | Now `docs/archive/2026-10/2026-09-29-byok-pr1-plan.md`, with a note. Its live points are in sections 11 and 12; "no encryption exists" is false (`cryptography` since #551) |
| The raw map of 2026-09-29 (outside the repository; it stays there) | Key-path probes, the contract lens, the storage lens, the 11 tests | The needle problem → section 12 item 3; the misconfiguration check → T16; only answer slots record the source → section 11; `.env.example` → section 12 item 6; the 11 tests → section 13; the Tavily question → section 11; the judge's timing (corrected: it first runs when the run finishes) → section 11 and T29; the `{"app_owned"}` assertion → section 12 item 13 |
| Section 5 of `docs/analysis/2026-10-13-security-review.md` | The recommendation (OAuth, AES-256-GCM, Fly-secret master key, signed-in only) and the 21 tests' subjects | Sections 3, 14, 15; the 21 tests → section 13. A note at that section |
| Section 3 of `docs/analysis/2026-10-17-w82-security-baseline.md` | Master key and database on one machine | Sections 2, 3 and 10 |
| ADR-0121 (PROPOSED, not edited) | Two postures, the rails table, three pull requests | Superseded by ADR-0180 |
| `docs/analysis/2026-09-29/OWNER-DISCUSSION-LOG.md` M03 point 5 | The owner's words of 2026-09-29 | Section 1; the record itself is unchanged |
| June 2026 documents describing a built BYO key slice | — | Corrected or marked in the same pull request as this file (section 18) |

## 18. The requirement conflicts, resolved by decision 6

All in the pull request that adds this file (CHG-079).

| Conflict | Resolution |
|---|---|
| FR-012 "Required" in `docs/10`, "Optional" in `docs/17` | `docs/10` FR-012 is now "Optional bring-your-own OpenRouter key": a signed-in user, two postures, not built (W28) |
| AC-025 mapped to FR-011, FR-012 and NFR-005 in different files; AC-025 and AC-026 defined differently in `docs/54` | AC-025 keeps its `docs/12` meaning (the app's key stays on the server) and maps to FR-011 and NFR-006 everywhere: `docs/11`, `docs/17`, `docs/18`, `docs/54`. AC-026 is rewritten in `docs/12` as "a user's own key never reaches the browser" and maps to FR-012 and NFR-006; `docs/54` follows |
| AC-026 forbade any key field | It now forbids the key in any page, response, export, log or browser storage, and allows only the last 4 characters |
| `docs/01` "not through a user-entered key field" against `docs/115` "Optional BYO OpenRouter key" in release 1 | Both now say: not in release 1; planned as W28 (ADR-0180) |
| `docs/18` cites two test files that never existed in any commit (a provider-keys unit test and a provider-key endpoints integration test) | Removed from the FR-012, NFR-005 and NFR-006 rows, with the false June "passed" claims they carried; the FR-012 row says no test exists yet |
| EDGE-013 "recorded by implementation design before coding" against `docs/48` "must stop future use immediately" | Both now state the decided rule: ask, default stop, never the app's key |
| `docs/48` own-key retention "Pending approval" | Decided: kept encrypted until removed or the account is deleted; up to 5 days in snapshots |
| OQ-010 open | Answered in part: the user sets their own limits; the abuse-limit numbers are not decided |
| NFR-005's target named "BYO key management endpoints", which do not exist | Now names the own-key routes once W28 builds them |
| The June documents describing a built BYO slice | Marked "not built" or corrected (the list below) |

No check pins the FR-012 and AC-025 repairs: `make fr-completeness` compares no titles and no AC ids
[session: in a `git archive` copy, FR-012's title in `docs/10` was changed and AC-025 swapped for
AC-026 in `docs/17`'s FR-011 row; `scripts/validate_fr_completeness.py --min-requirements 25` still
printed OK].

The June 2026 documents marked or corrected in the same pull request: `README.md`, `docs/104-next-iteration-backlog.md`, `docs/118-qa-test-charter-jira.md`, `docs/20-architecture.md`, `docs/21-domain-model.md`, `docs/34-jira-issue-authoring.md`, `docs/35-confluence-operational-guide.md`, `docs/40-threat-model.md`, `docs/43-privacy-data-governance.md`, `docs/45-control-mapping.md`, `docs/50-test-strategy.md`, `docs/51-test-data-strategy.md`, `docs/57-test-evidence.md`, `docs/60-implementation-plan.md`, `docs/61-vertical-slice-plan.md`, `docs/62-delivery-decomposition.md`, `docs/64-feature-flag-plan.md`, `docs/73-release-evidence.md`, `docs/REVIEW.md`, `docs/architecture/40-decisions.md`, `docs/atlassian-publication-payloads.md`, `docs/faq/index.html`, `docs/reviews/implementation-plan-critic-review.md`, `docs/study/glossary.md`, `docs/design-handoff/README.md` and the two `design_handoff_quorum_ui/` notes. Row W99 still owns rewriting `docs/40` and `docs/45`; they are only marked here. `docs/41-security-controls.md` is left alone: the parallel security session owns it, and its CTRL-006 line stays true until the build lands.

---

## 19. Free checks run, and the brief's open points

No check cost money or used a real key. Fuller output is in the evidence reports named at the top.

| Who | Command (in short) | What it printed |
|---|---|---|
| session | `fly volumes list -a quorum-ai --json` | `quorum_data`: `encrypted: true`, `snapshot_retention: 5`, `auto_backup_enabled: true` |
| session | `fly tokens list -a quorum-ai` | two app-scoped deploy tokens, each expiring in 2046 |
| session | an `ast` walk of `src/product_app/*.py` with the cap test's glob | 55 decorated functions |
| session | a script over transcripts `23fee4a3` and `20d36bac` | each owner quote in section 1, at its time |
| agent | `curl` POST to `https://openrouter.ai/api/v1/auth/keys` with a made-up code | `400 {"error":{"message":"Invalid code","code":400}}` |
| agent | `curl https://openrouter.ai/api/v1/key` with no key, then a fake key | `401` "No cookie auth credentials found"; `401` "User not found." |
| agent | `curl -X OPTIONS` preflights to completions, `/key`, `/auth/keys` | `204`, `access-control-allow-origin: *` |
| agent | `curl -X POST https://openrouter.ai/api/v1/auth/keys/code`, keyless and with a fake key | `404` from the website, as for a made-up path |
| agent | `curl -X DELETE https://openrouter.ai/api/v1/key` with a fake key | `404` |
| agent | `curl https://docs.fly.io/api/machines/openapi.json`, paths read with Python | 9 `secretkeys` operations; no audit field |
| agent | a keyless POST to a `secretkeys` decrypt path (one deviation from "GETs only", stated by the agent) | `401` "token validation error" |
| agent | AWS's KMS price file; Azure's retail price API; Google's KMS pricing page | the prices in section 5 |
| agent | `curl https://oidc.fly.io/personal/.well-known/openid-configuration` | `200`, RS256, claims including `app_name` and `image_digest` |
| agent | AES-GCM with a wrong associated data, `cryptography` 50.0.2 | `InvalidTag` |

The research brief's own list of open points (its section 10), and where each stands:
- Settled: the volume's encryption and snapshot retention (above); Google Cloud KMS's price
  (section 5); HCP Vault Secrets' end (section 5); Doppler has no encrypt service; LiteLLM's virtual
  keys are hashed; LibreChat's cipher (section 6); NIST SP 800-57's cryptoperiods and SP 800-88
  Rev. 2's date (section 8); a `CryptoKey` can be kept in IndexedDB (section 3); CloudTrail logs
  every KMS decrypt (section 5); HCP Vault Dedicated's price (about $450 a month, section 5);
  Infisical's algorithms (AES-256-GCM among others, [agent, `r5-kms.md` 7.1]); Portkey's and
  Retool's storage, section 6.
- OpenRouter's open points (a limit or expiry on an OAuth-issued key, revocation, automatic
  disabling of leaked keys, whether its terms allow an app to store users' keys) are U1, U2, U5 and
  U9 in section 16.
- Still UNVERIFIED, with the check: Fly `secretkeys` price, limits and audit, and whether its key
  import weakens "never leaves" (the owner's Fly trial, section 16); whether `fly ssh console` sees
  secrets on this machine (names only: `printenv | cut -d= -f1`, the owner's); what the Machines API's
  `show_secrets` returns (a question to Fly); Infisical's key service on its cheaper plans (a trial
  account); the cipher behind Zapier, Make and GitHub Copilot's enterprise keys (each vendor's
  security page); India's DPDP section 8 start date (the Gazette notice); whether Google Cloud's free
  Autokey keys can be used (Google's docs).

## How the sources were checked

Six read-only agents wrote the reports named at the top, each told to quote exactly and to mark
anything not confirmed as UNVERIFIED. The session itself ran: the transcript search for the owner's
words; `fly volumes list -a quorum-ai --json` and `fly tokens list -a quorum-ai`; an `ast` walk
counting decorated functions (55); and reads of the plan on `origin/w28/byok-pr1-plan`, the raw map,
the key-safety report and the earlier W28 documents. The pull request lists the review rounds
and what each found.
