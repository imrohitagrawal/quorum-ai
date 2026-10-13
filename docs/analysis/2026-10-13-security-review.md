# Security review, 2026-10-13

Written by the session of 2026-10-11 to 2026-10-13 (transcript `20d36bac`). The owner asked, on
2026-10-13: does a security reviewer exist and what does it cover; what an enterprise application
needs; try to break our security as an attacker would; how a stolen key or session is handled; and
how a bring-your-own key would be stored so it is not leaked or hunted. The owner's three decisions
on this review are CHG-042. Everything else here is the session's finding or recommendation, not an
owner decision.

**How to read this.** Section 1 is what the session ran itself, with the command and what it
printed. Section 2 is what agents reported and the session did not re-run. Section 3 is what held.
Each finding carries a class (`AGENTS.md` triage): only `REQUIRED_CONTRACT` and
`CRITICAL_BLOCKER` block. Board rows W68 to W81, and the widened W56, carry the work.

## The answer in short

- **The app's own defences held** against every attack the agents ran: sign-in, sessions, the
  page fetcher and the spend limits (section 3).
- **Three things are live today:** the visitor's address and anti-forgery token reach Sentry
  (finding S1); six known library vulnerabilities, with no check in CI that would notice them
  (S3); and a production build that does not install the versions CI tested (S4).
- **Nothing costs money today**, because live answers are off (`fly.toml:80`,
  `OPENROUTER_LIVE_EXECUTION_ENABLED = "false"`). Several findings must be fixed before they
  are switched back on (S7 to S9).
- **No user key is at risk today**, because bring-your-own key is not built:
  `src/product_app/query_run_orchestration.py:1249` sets
  `credential_source = ProviderCredentialSource.APP_OWNED`, and `BYO_OPENROUTER` appears only
  where it is defined (`src/product_app/provider_keys.py:7`).
- **There was no security reviewer in the process.** `configs/skill-router.json` routes the
  security skills only for sign-in changes (`security-threat-modeling`, `owasp-control-mapper`)
  and AI-output changes (`prompt-injection-defense`). The break-it reviewer is a correctness
  lens, not an attacker. Row W77 adds the role.

## 1. Verified by the session

All on `main` at `9e2de1a`, 2026-10-13, unless a line says otherwise. Each reproduction ran as a
pytest file inside a `git archive HEAD` copy, so the outbound-socket guard in `tests/conftest.py`
was active, and the copy was deleted afterwards.

### S1. Visitor address and anti-forgery token reach Sentry — `REQUIRED_CONTRACT`, live

`docs/48-data-retention.md` (the anonymous spend-key row) and the W56 row record that Sentry
receiving a network's spend key beside the visitor's address lets Sentry pair the two, and CHG-029
(d) put it on the board as W56. The probe below sent one request through the app with production's Sentry
settings (`src/product_app/main.py:222-245`) and captured what would be sent.

```python
import json, sentry_sdk
from sentry_sdk.transport import Transport
from fastapi.testclient import TestClient
CAP = []
class Capture(Transport):
    def capture_envelope(self, envelope):
        for item in envelope.items: CAP.append(item.payload.json or {})
def test_headers():
    from product_app import main
    sentry_sdk.init(dsn="https://abc@o1.ingest.sentry.io/1", transport=Capture,
        traces_sample_rate=1.0, sample_rate=1.0,
        before_send=main._redact_sentry_event, before_send_transaction=main._redact_sentry_transaction,
        include_local_variables=False, send_default_pii=False)
    with TestClient(main.app) as c:
        c.get("/health", headers={"Fly-Client-IP": "203.0.113.88", "X-CSRF-Token": "CSRFSECRET123"})
    sentry_sdk.flush(); blob = json.dumps(CAP)
    print("PROBE1 items", len(CAP), "ip", "203.0.113.88" in blob, "csrf", "CSRFSECRET123" in blob)
```

Printed: `PROBE1 items 1 ip True csrf True`.

- The probe samples every request. Production samples performance records at
  `traces_sample_rate=0.1` (`src/product_app/main.py:227`), so about 1 request in 10 sends them.
- `_scrub_user_text` (`src/product_app/main.py:150`) clears `request.data` and the sign-in
  callback's query, and never touches request headers.
- Earlier the same day, `fly secrets list` showed `SENTRY_DSN` set in production. Names only;
  no value was read.
- UNVERIFIED: whether error events raised during a request carry the same headers. The probe
  captured one performance record, not an error.
- Owner decision: CHG-042 (a) widens W56 to cover this.

### S2. A key inside an error message reaches Sentry — `REQUIRED_CONTRACT` for W56 and bring-your-own key

```python
def test_key_in_exception():
    from product_app import main
    sentry_sdk.init(...same settings, traces_sample_rate=0.0...)
    key = "sk-or-v1-" + "0123456789abcdef" * 4
    try: raise RuntimeError(f"upstream rejected {key}")
    except RuntimeError as e: sentry_sdk.capture_exception(e)
    sentry_sdk.flush()
    print("PROBE2 events", len(CAP), "key", key in json.dumps(CAP))
```

Printed: `PROBE2 events 1 key True`.

- The event scrubber does not clean exception message values.
- Today the only key the app holds is its own server key. Nothing found so far puts it into an
  exception message, so this is not shown to be live.
- With bring-your-own key, every user's key passes through the same code, so this becomes a
  blocker for W28.
- CHG-042 (a) puts "keys inside error messages" in W56's widened scope.

### S3. Six known vulnerabilities in the locked runtime libraries — `REQUIRED_CONTRACT`

```bash
uv export --frozen --no-dev --no-hashes -q > req.txt
uvx pip-audit -r req.txt --no-deps --disable-pip
```

`pip-audit` exited 1 and listed:
- `anyio 4.14.0`: PYSEC-2026-4023, PYSEC-2026-4024 and PYSEC-2026-4025, fixed in 4.14.2.
- `urllib3 2.7.0`: PYSEC-2026-4175, PYSEC-2026-4176 and PYSEC-2026-4177, fixed in 2.8.0.

Whether our code reaches the vulnerable paths is UNVERIFIED. Nothing in `.github/workflows/` runs
a vulnerability check: a search for `pip-audit`, `osv`, `codeql`, `trivy`, `gitleaks`, `semgrep`
and `bandit` across the workflow files found none. Row W68.

### S4. The production image ignores the lock file — `REQUIRED_CONTRACT`

- `Dockerfile:16` runs `uv pip install --python /opt/venv/bin/python --no-cache --compile-bytecode .`.
  That resolves from the version ranges in `pyproject.toml`, not from `uv.lock`, so production
  can run library versions CI never tested.
- Row W59 already records one effect: `cffi` and `pycparser` are unpinned.
- Row W68 fixes the cause, by installing from the lock file. It covers W59.

### S5. The secret scan misses keys outside Python files — `REQUIRED_CONTRACT`

The session planted the same fake 64-character `sk-or-v1-` key in a new `.py` file and a new
`.js` file in a copy, then ran `scripts/security_scan.py`. It exited 1 and named the `.py` file
once and the `.js` file zero times. Row W70.

### S6. GitHub Actions are not pinned to commits — `ADVISORY_DEBT`

- 50 `uses:` lines in `.github/workflows/*.yml` name a third-party action, and 1 of them is
  pinned to a full commit id.
- A moved tag would run new code with this repository's secrets.
- Row W69.

### S7. Non-Latin text is priced at 4 characters per token — `REQUIRED_CONTRACT` before live answers return

- `src/product_app/costs.py:311` sets `CHARS_PER_TOKEN = Decimal(4)`.
- The arithmetic that this lets a run of about $0.77 pass the $0.50 per-run and $0.40 daily
  anonymous limits is an agent's (section 2), not re-run.
- It is dormant while live answers are off. Row W71.

### S8. A link the model writes is fetched by the server — `ADVISORY_DEBT`, by reading the code

- When the provider returns no citations, `src/product_app/providers.py:4452-4466` turns every
  Markdown link in the model's answer into a source.
- `src/product_app/evaluation.py:2104-2114` then fetches every source, keeping the query string.
- So a poisoned web page could make a model write a link carrying the user's question to an
  attacker's server, and our server would fetch it with no click.
- Not run end to end. Dormant while live answers are off. Row W72.

### S9. Smaller AI-input gaps — `ADVISORY_DEBT`

- `_LOOK_ALIKES` (`src/product_app/untrusted_text.py:120`) has no Cyrillic `У`/`у`. A Python
  check of the table printed `cyrillic U present: False`.
- `_SOURCE_URL_HOST_DENYLIST` (`src/product_app/providers.py:4289`) is checked by exact host
  equality at `:4379`, so hosts it does not list pass.
- Row W73.

### S10. Smaller sign-in gaps — `ADVISORY_DEBT`, by reading the code

- `/feedback/audit` (`src/product_app/main.py:2061-2063`) requires only `require_session`. By
  reading, any visitor's anonymous session satisfies that; not run.
- The sign-in callback removes the pending sign-in (`src/product_app/google_signin.py:675`)
  before it compares the `state` (`:678-680`). By reading, a cross-site link with a wrong state
  cancels the visitor's sign-in in progress.
- Row W80.

### S11. The page's security policy allows inline scripts — `ADVISORY_DEBT`, a prerequisite for bring-your-own key

- `src/product_app/main.py:742` sets `script-src 'self' 'unsafe-inline'`.
- The comment at `:733-738` records why, and that a nonce would remove it.
- With a user key in play, an injected script that can run can read it. Row W75.

### S12. Process and documents

- The local Claude settings files (`~/.claude/settings.json`, `.claude/settings.json` and
  `.claude/settings.local.json`, none of them tracked) have no `deny` rule, so nothing stops an
  agent reading `.env`. Rule: `AGENTS.md` and the owner's standing instruction. Row W81.
- `docs/83-runbook.md` and `docs/84-incident-response.md` each contain the word "rotat" 0 times
  (`grep -ci`), so neither says how to replace a leaked key. Row W79.
- The board's I3 limit: `tests/test_planted_false_claims.py:455` reads
  `("I3", plant_i3, OPEN_WORK, 0)`. The plant flips W28's needle word from `PRESENT` to
  `ABSENT` and types its State as DONE. That false "done" is caught 0 times, as
  `docs/65-open-work.md` "What this cannot see" says. Row W78.
- History: earlier on 2026-10-13, `gitleaks git --redact` over all commits returned 20 hits. The
  session inspected each one's file and shape: all were fake test keys or benign. No real secret
  is in git history.

## 2. Reported by agents, not re-run by the session

Seven agents ran: two online-research agents, four attack agents (money, sign-in, AI input, CI and
supply chain), each in its own `git archive` copy, and one key-safety designer. Treat their numbers
as leads until re-run.

| Finding | Agent's evidence | Class | Row |
|---|---|---|---|
| The `X-Account-Id` header also reaches Sentry | header probe | `REQUIRED_CONTRACT` | W56 |
| Earlier breadcrumbs carry a key into later Sentry events; a key in a URL is kept in http breadcrumbs | SDK probe | `REQUIRED_CONTRACT` for W28 | W76 |
| The key pattern `\bsk-…` misses a key glued to a word, percent-encoded, or without its prefix | regex probe | `REQUIRED_CONTRACT` for W28 | W76 |
| The 422 handler returns validator messages, which can echo an input key | request probe | `REQUIRED_CONTRACT` for W28 | W76 |
| `model_dump_json()` on the settings prints the app key (`repr=False` hides it only from `repr`) | Python probe | `ADVISORY_DEBT` | W76 |
| Chinese or Japanese text: a run of about $0.77 passes the $0.40 and $0.50 limits; worst case about $12 a day against the $5 site ceiling | arithmetic | `REQUIRED_CONTRACT` before live | W71 |
| 31 catalog models charge internal-reasoning fees we do not price | catalog read | `ADVISORY_DEBT` | W73 |
| A fallback-list model is priced at the floor price | code read | `ADVISORY_DEBT` | W73 |
| Variation selectors survive the text cleaning | probe | `ADVISORY_DEBT` | W73 |
| Building today resolves 24 of 32 packages to versions different from the lock | resolver run | `REQUIRED_CONTRACT` | W68 |
| `zizmor` reports 106 findings on the workflows | tool run | `ADVISORY_DEBT` | W69 |
| `FLY_API_TOKEN` is a repository secret with no environment rules; a manual deploy from any branch skips the gates; the `flyctl` version is "latest" | workflow read | `ADVISORY_DEBT` | W69 |
| The secret scan also misses `.ts`, `.sh` and `.example` files, split or joined keys, and names such as `FLY_API_TOKEN`, `GOOGLE_CLIENT_SECRET` and `SENTRY_DSN` | probes | `REQUIRED_CONTRACT` | W70 |
| Dependabot alerts and private vulnerability reporting are off; no `SECURITY.md`; 0 required approvals | `gh api` | owner settings | W79 |
| `docs/41-security-controls.md` CTRL-012 claims scanning that does not exist; `docs/45-control-mapping.md` says "Evidence: Not available" | doc read | `ADVISORY_DEBT` | W77 |

The money agent also tested a "per-request fee" attack. The session refuted it: a read of
OpenRouter's public model list on 2026-10-13 found 0 models with a per-request fee.

## 3. What held

Each of these was attacked by an agent and held. The session re-ran none of them.

- **Page fetcher:** IPv4-mapped and NAT64 addresses, Fly's private network, redirects, byte and
  time bounds, and the PDF sandbox all held.
- **Answer rendering:** HTML is off, images are off, and link schemes are allow-listed. No script
  ran.
- **Untrusted-text fence:** held, apart from S9.
- **Spend limits:**
  - 16 concurrent runs against one allowance gave 3 accepted and 13 refused (402).
  - A spoofed address header was ignored.
  - Rotating through one /64 network was counted as one network.
  - Loops minting new sessions were refused.
  - Negative prices were refused.
  - 129 money tests passed.
- **Sign-in:**
  - Another account's records answer 404.
  - The anti-forgery token is header-only and per session.
  - The session id changes at sign-in.
  - The cookie is `__Host-`, Secure and HttpOnly.
  - Staging refuses the legacy header.
  - `/status`, `/ready` and `/metrics` leak no planted secret.
  - Invite signing and revoking work.
- **Supply chain:**
  - No workflow uses `pull_request_target`.
  - A fork's pull request cannot deploy.
  - The container runs as a non-root user.
  - Telemetry is allow-listed.

## 4. What the owner must do: account settings no agent can check

Each is free, takes minutes and needs no code.

1. Turn on 2-step login for GitHub, Fly, Google Cloud, OpenRouter and Sentry.
2. Put a credit limit on the OpenRouter key, in OpenRouter's dashboard.
3. Replace `FLY_API_TOKEN` with a deploy token limited to this one app.
4. In GitHub's settings, turn on: Dependabot alerts, private vulnerability reporting, secret
   scanning's validity checks, and "require actions pinned to a full commit".
5. Check how long Fly keeps volume snapshots, because they hold the database.

## 5. Bring-your-own key: the session's recommendation

**PROPOSED — AWAITING OWNER.** ADR-0121 is still PROPOSED. The six decisions listed in the
unmerged plan on branch `w28/byok-pr1-plan` (commit `7bdfa87`) are still open. That plan's line
"no encryption exists" is out of date: `cryptography==50.0.2` is a dependency (`pyproject.toml:42`).

1. **How the key arrives.**
   - Recommended: OpenRouter's own sign-in flow (OAuth with PKCE). The user approves on
     OpenRouter, and our server swaps the one-time code for a key server-side, so the key never
     sits in the browser.
   - Alternative: the user pastes a key. It then crosses the browser, so S11 must be fixed
     first.
2. **Where the key lives.**
   - Recommended: in the database, encrypted with AES-256-GCM.
     - The master key is a new Fly secret, with a version number so it can be replaced.
     - The account id is bound into each encryption, so a copied row cannot be read as another
       account's key.
   - Keeping keys in memory only fits badly: production stops when idle
     (`fly.toml:191-192`, `min_machines_running = 0` and `auto_stop_machines = "stop"`), so
     users would paste the key again after every stop, and every paste is a chance to steal it.
3. **Who may use it:** signed-in accounts only.
4. **What anyone sees:** only the last 4 characters, everywhere: page, logs, Sentry, exports.
5. **Before any of it:** W56 widened (S1, S2), W75 (S11) and W76 (the key-safety findings in
   section 2).

The key-safety agent listed 21 required tests for the build. Their subjects:
- the key never appears in any log line, Sentry event, breadcrumb, error response or export;
- a stored key is unreadable without the master key, and unreadable under another account;
- replacing the master key re-encrypts every key;
- revoking deletes the key;
- an anonymous session can never hold or use one.

W28's pull request should turn these into tests written first.

## 6. The board's I3 limit: proposed fix

**PROPOSED — AWAITING OWNER**, its own pull request and ADR.

- When a row turns DONE, the check also re-reads the row's FIRST committed evidence cell, from
  git history, against today's tree.
- If that original needle still says the work is open, the check refuses, unless the row cites
  an owner CHG row that approves the rewrite.
- The test row at `tests/test_planted_false_claims.py:455` moves from 0 to 1.
- A partner test proves an honest rewrite, one cited to a CHG row, is still accepted.
- Row W78.

## 7. Tools and standards the research found

- **For CI, all free:**
  - `osv-scanner` or `pip-audit` for libraries;
  - `zizmor` for workflow files;
  - CodeQL;
  - OpenSSF Scorecard;
  - a ZAP baseline scan against the local server only.
- **For review:**
  - Trail of Bits' security skills, installed as a plugin rather than copied (CC-BY-SA);
  - Semgrep's LLM-security rules;
  - Claude Code's `/security-review`. Its GitHub Action skips flooding and rate-limit
    findings by default, so give it instructions that include cost and flooding.
- **For live model attacks** (`garak`, `promptfoo` or `PyRIT`): these make paid model calls and
  need the owner's approval. Row W74.
- **Not adopted:** LLM Guard, which is archived.
- **Standards checked against:**
  - OWASP Top 10:2025, which adds software supply chain;
  - OWASP API Top 10 2023;
  - OWASP's LLM Top 10 and its agentic list;
  - ASVS 5.0, where Level 2 fits this app;
  - NIST SSDF 800-218;
  - SLSA 1.2;
  - RFC 9700 for OAuth;
  - NIST 800-61r3 for incidents;
  - MITRE ATLAS.

## 8. Rule breaks during this review

Disclosed so they are not repeated.

- Two agents each imported the app outside pytest. On import it pre-fetches OpenRouter's
  public model list, so each may have sent one free request, with no key, to openrouter.ai.
- One research agent loaded production's `/ui` page once. That minted one anonymous session and
  used one of the owner network's two new sessions for that day. The session's prompt had not
  forbidden production; that was the session's oversight.
- The session made free reads of production: `/status`, and the names (not values) of its
  secrets.

## 9. Order

From CHG-042 (b):
1. W56, widened.
2. W68, the library supply chain.
3. W55.
4. W69, CI hardening.
5. W70, secret scan.

The session recommends this for the rest:
- W71 to W73 before live answers are switched back on.
- W74 when the owner approves its spend.
- W75 and W76 before W28.
- W77 to W81 in any order, one pull request each.
