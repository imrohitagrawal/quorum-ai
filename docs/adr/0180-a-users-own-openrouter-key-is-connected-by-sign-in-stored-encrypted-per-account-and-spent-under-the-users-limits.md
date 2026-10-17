# ADR-0180: A user's own OpenRouter key is connected by OpenRouter's sign-in, stored encrypted per account, and spent under the user's own limits

## Status

Accepted — 2026-10-17, for the parts the product owner decided: CHG-075 to CHG-080, and decision 3 of CHG-059.

The section "Not decided" lists what is still open. Nothing here is built: W28 is built after W85,
W86, W100, W87, W88, W80, W75 and W76 (CHG-061). This record replaces ADR-0121 for W28. ADR-0121 is
left as it is, because `tests/unit/test_live_posture_check.py` and `tests/test_planted_false_claims.py`
pin its first status sentence; its two-posture principle and its rails table carry into this record except where the
owner changed them (the per-run cap, CHG-078). The research behind every point, with its sources, is
`docs/analysis/2026-10-17-w28-key-storage-research.md`.

## Context

Every run spends the app's own OpenRouter key today: `credential_source =
ProviderCredentialSource.APP_OWNED` is hard-coded at `src/product_app/query_run_orchestration.py:1248`.
The owner planned a second posture on 2026-09-23, in which a user brings their own key (CHG-011 D8,
ADR-0121), and on 2026-10-17 asked for enterprise practice, with no re-paste of the key after every
stop and deploy (CHG-059).

Three facts shaped the choice:
- The one production machine stops when idle and at every deploy (`fly.toml:191-192`), so a key
  held only in memory is lost many times a day.
- In every design where the server uses the key, whoever can deploy code to the app can read it.
  Fly says so of its own secrets (*"People with deploy access can deploy code that reads secret
  values"*, `docs.fly.io/apps/secrets`). Designs differ in how far they limit the damage.
- Every hosted product the research read keeps users' keys on its server, encrypted, with no re-entry
  after a restart; the decryption key usually sits in an environment variable beside the database,
  and enterprise tiers move it into a key service.

## Decision

Each item names its source: the owner's CHG row, or "session's design" for a part the session
worked out from the research to carry the owner's decision out. The session's design stands with the
owner's decisions it serves (CHG-075 to CHG-080); a later review may change it without an owner
decision.

1. **Who may hold a key.** A signed-in account only (CHG-059, decision 3). The key belongs to the
   account, not to a session (CHG-076). No key can be entered before sign-in, and nothing carries over
   at sign-in.
2. **How the key arrives.** Through OpenRouter's own sign-in flow only (OAuth with PKCE), no paste
   (CHG-077). The server makes the code verifier (S256, never `plain`) and a one-time `state` bound to
   the session, keeps both on the server, checks `state` before it discards the pending entry, and
   exchanges the code at `https://openrouter.ai/api/v1/auth/keys` itself, so the key never reaches the
   browser. The callback has its own path, distinct from Google's, and its query string is redacted
   from logs and Sentry (session's design, from ASVS 5.0 V10 and RFC 9700). The owner runs the free
   trial in section 16 of the research file first.
3. **Where it is stored.** In its own table in the sessions database, added by a guarded
   `schema_migrations` block, never on a session row, a session object, a cookie or in the browser
   (CHG-075, CHG-076), encrypted with AES-256-GCM and bound to the account (CHG-075's chosen option
   said so). The rest of this item is the session's design: the guarded migration; the pinned
   `cryptography` package; a fresh 12-byte random nonce each time; and associated data binding the
   account id, the master-key version and the purpose, so a row copied to another account fails to
   decrypt. The row also holds the
   master-key version, the key's last 4 characters, a SHA-256 fingerprint and the dates. That store
   turns on `PRAGMA secure_delete`.
4. **The master key.** Its own Fly secret (CHG-075, CHG-077). It moves to AWS's key service,
   reached with Fly's machine identity, if a Fly or GitHub token is ever suspected or a security
   review asks for it (CHG-075). The session's design: never `QUORUM_TOKEN_SECRET` (NIST SP 800-57
   §5.2, one key one purpose); versioned, so a new version can be added and old rows re-wrapped, and
   the version on every row makes the move to the key service possible without anyone reconnecting;
   rotated at least yearly and at once after any suspicion; with the feature on, production refuses
   to start without it, and with the feature off it starts without one (the 2026-10-13 key-safety
   test K10, narrowed so a feature-off deploy needs no secret); no copy kept outside Fly's vault, so a
   lost master key means users reconnect through OpenRouter's sign-in.
5. **What anyone sees.** A key with no limit gets a warning and a link to that key's page at
   OpenRouter; runs still work (CHG-077). Only the last 4 characters are ever shown, never the full key
   (CHG-079's chosen option). The session's design: the date added, the date last used, and the key's
   credit limit at OpenRouter if it has one (ASVS 5.0 14.2.6).
6. **A run on a user's key.** Live answers and the judge are on by default; no operator setting is
   needed (CHG-077, CHG-080). The judge runs on the user's key (CHG-080); that it then needs only its
   model id is the session's design. Peer critique is the user's choice per run (ADR-0121's agreed table, CHG-080). The app's own
   Tavily key is never spent on a user's run; an optional Tavily key of the user's own is a later W28
   pull request, never a prerequisite, stored and protected like the OpenRouter key, so the lift of
   the 2026-09-24 hard stop follows to that key (the option the owner chose in CHG-078 said it is
   stored like the OpenRouter key; CHG-075 records this). The session's
   design: one predicate decides that a run holds a key that may be spent, and the three places that
   read the app's live flag today (`providers.py:1005-1006`, `debate.py:1818`, `synthesis.py:1473`)
   read it.
7. **Limits.** The user sets a budget window (default $5 a day) and a per-run cap (default $0.50) and
   is asked before a run would cross either; one run at a time and the abuse rate limits stay; the
   credit limit at OpenRouter is the outer bound (CHG-078). For a run on a user's key the shared daily
   ceiling, the per-account app allowance and the live-execution window do not apply (ADR-0121's
   rails table, CHG-080). The process-wide concurrency cap stays (session's design).
8. **Failure posture: closed** (session's design, from ASVS 5.0 16.5.3 and the option text the
   owner chose in CHG-078, "the run never moves to our key"). If the key cannot be decrypted, the
   master key is missing, or OpenRouter answers 401, 402 or 403 on the user's key, the run on that key
   stops. It never falls back to the app's key. The judge first runs when the run finishes
   (`_persist_terminal_run`); a verdict already obtained is kept, with its cost record, after the key
   is removed, and a later read never calls the judge again on any key.
9. **Removal.** "Remove key" deletes the row. During a run the page asks whether to stop the run now
   or let it finish on that key and then remove it; no answer means stop; a key removed and added
   again does not restart the stopped run (CHG-078; the remove-then-add rule is the session's design). "Sign out everywhere" offers "Also remove my
   OpenRouter key", ticked by default (CHG-076). Account deletion deletes it. A removed key's
   encrypted copy stays in volume snapshots for up to 5 days; the privacy text says so, and the
   Remove confirmation tells the user to revoke the key at OpenRouter too (CHG-075).
10. **An audit trail without the key** (session's design, from the OWASP Secrets Management cheat
    sheet §2.6). One row per event (added, used, replaced, removed, decrypt
    failed): account id, fingerprint, run id, time.

## Measured

| Fact | Command | Result |
|---|---|---|
| The volume is encrypted and snapshots are kept 5 days | `fly volumes list -a quorum-ai --json` (session, 2026-10-17) | `encrypted: true`, `snapshot_retention: 5`, `auto_backup_enabled: true` |
| Two app deploy tokens, 20-year default | `fly tokens list -a quorum-ai` (session) | both expire in 2046 |
| No room for a new decorated function | an `ast` walk of `src/product_app/*.py` (session) | 55, the cap in `tests/unit/test_mutation_test_set_integrity.py:285` |
| The code exchange works from a server | `curl` POST to `/api/v1/auth/keys` with a made-up code (research agent) | `400 {"error":{"message":"Invalid code","code":400}}` |
| A wrong account id cannot decrypt | AES-GCM with a different associated data, `cryptography` 50.0.2 (research agent) | `InvalidTag` |

## Not decided

- What today's OpenRouter approval screen offers (a credit-limit box, an expiry field), whether
  reconnecting leaves the old key live, and the exact error at a key's limit: the owner's trial.
- The abuse-limit numbers for signed-in users with their own key. ADR-0121's "100 or 200" and "10 in
  1 or 2 minutes" were about anonymous session mints behind office networks; with signed-in only,
  users are limited per account (CHG-026 (a)). The build proposes values for the owner.
- How long audit rows are kept, the privacy text's wording, and which law applies (where the users
  are): for the owner, with the build.
- The page copy.

## Rejected alternatives

| Alternative | Why not |
|---|---|
| Memory only | Lost at every idle stop and deploy; fails the owner's no-re-paste rule (CHG-075) |
| Per browser session | Fails "not in the sessions"; a phone would need its own connection (CHG-076) |
| Paste, alone or with sign-in | The key crosses the browser and may be the user's main key with no limit (CHG-077) |
| AWS key service now | About $1-3 a month and an AWS account; it does not stop a live attacker with deploy access. Kept as the move on a trigger (CHG-075) |
| Fly's own `secretkeys` | API reference only: hidden CLI command, no price, no audit log found |
| Encrypted cookie, or the browser only | ASVS 5.0 14.3.3 and the owner's "web-inspect" words |
| A tokenising proxy | $995 to $1,000 a month, and it sees every prompt |
| A fixed $0.50 per-run cap | The owner wants the user to choose (CHG-078) |
| The app's Tavily key on a user's run | The app's money, uncounted (row W71) |
| Falling back to the app's key | Spends the app's money on a user's run, silently (ASVS 5.0 16.5.3) |
| A data key per user, wrapped by the master key | On one machine the wrapped data key sits beside the master key's reach, so it adds little (OWASP's one-server note); a per-user key held in a key service is part of the trigger move |
| A copy of the master key kept outside Fly | One more place to steal it; losing the key means users reconnect through OpenRouter's sign-in |

## Consequences

- **The limit no design removes.** Anyone with a Fly token, an organisation membership or GitHub
  write access can read users' keys while they hold that access. With the Fly-secret master key they
  can also take the key and database copies away and decrypt those copies for ever: rotating the
  master key protects only what is written afterwards. So every key stored at the time of a
  compromise must be revoked by its owner at OpenRouter, under any design. The damage is bounded by
  the user's credit limit at OpenRouter and by that revocation. Keeping the circle that can deploy
  small is part of this design: 2-step login on GitHub and Fly, and short-lived Fly tokens, which no
  board row owns yet.
- **Build constraints** (research file, section 12): no new decorated function (55 of 55); the
  credential-source enum is pinned; W28's frozen board row and the tests that plant on it must move
  in the first build pull request, to a needle only the last W28 pull request removes; the session
  store changes only through a guarded migration; every new setting goes into `.env.example`;
  `docs/41-security-controls.md` CTRL-006 goes false when the key path lands.
- **Tests.** The build passes T1 to T32 in section 13 of the research file, each written first.
- **Prerequisites.** W85, W86, W100, W87, W88, W80, W75 and W76, in that order (CHG-061).
- **Documents.** FR-012 and AC-026 now describe this design, and AC-025 keeps its meaning, the
  app's key (CHG-079); EDGE-013 records the
  removal posture above.
