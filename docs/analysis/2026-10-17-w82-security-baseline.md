# W82: the security baseline, 2026-10-17

Written by the session of 2026-10-17 (transcript `21387da6`), on `main` at `2f13e22`. The owner asked
that the security session first look at the measures in place, the gaps, and how to close them
(CHG-051). Everything else here is the session's work and the session's proposal, not an owner
decision: the measure list (`docs/41-security-controls.md`), the ASVS check
(`docs/analysis/2026-10-17-asvs-5-level-2-check.md`), the new board rows and the order below.

**How to read this.** Section 1 is what the session ran itself, with the command and what it printed.
Section 2 is what agents reported. The session ran the tests the ASVS agents cited (142) and the
tests `docs/41-security-controls.md` names (216); a reviewer ran the 10 cited tests in neither set (12
cases passed). The session did not re-check every line of code the agents cite. Each new row says
which kind of evidence it rests on.

**Dates.** File names and dates are India dates. The agents ran on 2026-10-16 between 20:34 and 21:04
UTC, and the session read production between 20:35 and 21:00 UTC (2026-10-17 in India). The owner's
answers came at 2026-10-17 04:43 UTC, and GitHub's settings were read again, and changed at the
owner's instruction, between 05:16 and 06:00 UTC (CHG-057).

## The answer in short

- **Measures in place:** 97, listed in the new `docs/41-security-controls.md`, each with the test or
  the command that shows it runs, or "none". 64 are tested, 26 partly, 5 are in the code with no
  test, and 2 were measured. A new test fails if a test named there is renamed or deleted, or if a
  measure's row disappears.
- **OWASP ASVS 5.0.0, Levels 1 and 2:** 253 items, checked one by one. 97 do not apply (no passwords,
  no file uploads, no WebRTC, the app is not an OAuth server). Of the other 156: 44 are in place with
  a test, 2 were measured in production by the session, 24 are in place with no test, 73 are partly in
  place, 12 are not in place, and 1 could not be settled.
- **Another account's runs and history stay private when read:** the cross-account tests pass
  (`docs/41-security-controls.md` SC-26, SC-28 and SC-29). The exception is cancelling: the cancel
  route checks the account in the code, but no test tries another account's run, and it answers with
  the whole run, answers included (SC-27; row W98). Paid live answers are off in production
  (`/status` `live_execution: false`), so nothing found spends money today.
- **The first three rows, all live:**
  1. W85: a request body is read before the session is checked, and nothing limits its size. The
     session measured it in a local copy (details held back until the fix ships (CHG-060)).
  2. W86: signed-in history older than 30 days is deleted only when that same account saves a new
     question, so an account that stops using the site keeps its old questions on disk. The owner
     approved "none completed more than 30 days ago" (`docs/48-data-retention.md`, CHG-023).
  3. W100: the page can tell the server the user acknowledged a high-stakes warning that was never
     shown (details held back until the fix ships (CHG-060)).
- **17 new rows, W85 to W101.** Seven existing rows change (W71, W72, W73, W74, W75, W77, W78). The owner
  answered four questions on 2026-10-17 (CHG-056, section 6): W87 and W78 are no longer waiting, W74
  is priced before any spend, and W94's limits still wait on the owner.

**What this public file holds back.** The repository is public. For the live gaps not yet fixed
(W85, W87, W88, W100), this file says what the gap is and which row fixes it, but not how to
reproduce it; the full evidence is kept outside the repository until each fix ships (CHG-060).

## 1. What the session ran

| What | Command | What it printed |
|---|---|---|
| Every test the ASVS agents cite exists | a short script, not committed: parse each cited `tests/<file>.py::<name>` out of the six reports and find the function in the file with `ast` | `ids 142 ok 142 missing 0` |
| Every test the ASVS agents cite passes | `.venv/bin/python -m pytest <the 142 ids> -q --no-cov -p no:cacheprovider` on a worktree of `2f13e22`, with `SENTRY_DSN=` and `OPENROUTER_LIVE_EXECUTION_ENABLED=false` | `265 passed, 2 warnings in 36.08s`, `EXIT=0` (parameterised tests run several cases) |
| The section-9 agent's cited tests exist | the same check over its report | `ids 30 ok 30 missing 0` |
| The inventory agent's cited tests exist | the same check over its report | `ids 144 ok 144 missing 0` |
| The tests `docs/41-security-controls.md` names exist and pass | the same check over the file (the generator wrote each `::name` shorthand out in full), then `pytest` on those ids in a `git archive` copy of `2f13e22` | `ids 216 ok 216 missing 0`; `1 failed, 387 passed`. The failure is `tests/unit/test_w69_round2_regressions.py::test_the_command_make_runs_fails_on_a_planted_injection`: in the copy, `make` built a new environment without `zizmor` and printed `Failed to spawn: zizmor`. That test passed in the branch's full `make quality` run |
| The page can acknowledge a high-stakes warning the user never ticked | read `src/product_app/static/app.js` | confirmed; details held back until the fix ships (CHG-060); the evidence is kept outside the repository |
| A request body is read before the session is checked, with no size limit | a local probe in a `git archive` copy; nothing was sent to production | confirmed; details held back until the fix ships (CHG-060); the evidence is kept outside the repository |
| An unhandled error page has no security headers | a pytest probe: a route that raises, through `TestClient(raise_server_exceptions=False)` | `500`, body `Internal Server Error`, `content-security-policy` absent, `x-content-type-options` absent, `x-frame-options` absent; on `/health` the policy is present |
| Production's response headers | `curl -s -D - -o /dev/null https://quorum-ai.fly.dev/status` (and `/health`, `/ready`) | `content-security-policy` with `script-src 'self' 'unsafe-inline'`, `strict-transport-security: max-age=31536000; includeSubDomains`, `x-frame-options: DENY`, `x-content-type-options: nosniff`, `referrer-policy: no-referrer`. No `cache-control`, no `permissions-policy` |
| Plain HTTP is redirected | `curl -s -o /dev/null -w "%{http_code} -> %{redirect_url}" http://quorum-ai.fly.dev/health` | `301 -> https://quorum-ai.fly.dev/health` |
| What production says it runs | `curl -s https://quorum-ai.fly.dev/status` | `build_sha` `2f13e22…`, `live_execution: false`, `judge_enabled: true`, `sign_in_enabled: true`, `invite_links.enabled: false`, `error_tracking: "active"`, `session_limit_allow_list.active_entries: 0` |
| TLS versions | `openssl s_client -connect quorum-ai.fly.dev:443 -tls1_2` (and `-tls1_3`; `-tls1` and `-tls1_1` with `-cipher 'DEFAULT:@SECLEVEL=0'`) | TLS 1.2: `ECDHE-ECDSA-AES256-GCM-SHA384`; TLS 1.3: `TLS_AES_256_GCM_SHA384`; TLS 1.0 and 1.1: `Cipher is (NONE)`. Only one cipher per version was seen; the full list was not enumerated |
| Certificates | `openssl s_client … \| openssl x509 -noout -issuer -subject -dates` | `quorum-ai.fly.dev`: `*.fly.dev`, Let's Encrypt, valid to 2026-11-19, `Verify return code: 0 (ok)`; `quorum.stackclimb.com`: its own name, valid to 2026-12-19, `Verify return code: 0 (ok)` |
| GitHub's security settings | `gh api repos/:owner/:repo` (`.security_and_analysis`), `…/vulnerability-alerts`, `…/private-vulnerability-reporting`, `…/branches/main/protection`, `…/actions/permissions` | secret scanning `enabled`, push protection `enabled`, validity checks `disabled`; Dependabot alerts `404` (off); private vulnerability reporting `{"enabled":false}`; 0 required approvals; `sha_pinning_required: true`; default workflow permissions `read`; 0 repository secrets; the `production` environment with a branch rule |
| A session has no maximum age | read `src/product_app/auth.py:308-309` and `:1083`, `src/product_app/session_store.py:862` | confirmed: expiry looks only at the last use (details held back until the fix ships (CHG-060)) |
| A crash inside a run is not logged | read `src/product_app/query_run_orchestration.py:1122-1140` | the `except BaseException` marks the run failed with the error's class name; no log call, no Sentry call |
| Another site can open counted sessions for a visitor | read `src/product_app/main.py` | confirmed by reading; details held back until the fix ships (CHG-060) |
| History is deleted by age only on a write | `grep -n "DELETE FROM history" src/product_app/session_store.py` | three hits: `:702` (by age) and `:706` (by count), both inside `record_history` and only for the account being written; `:979`, account deletion. Reads already leave out rows past 30 days (`tests/unit/test_account_history_store.py::test_rows_older_than_30_days_are_dropped_and_never_shown`), so old rows are kept on disk, not shown |
| Only the cost store deletes securely | `git grep -n "secure_delete" -- src` | every hit is in `src/product_app/feedback_store.py`; the session store, which holds history and accounts, never sets it |
| The token secret only has to be non-empty | read `src/product_app/config.py:1019-1027` | `if not quorum_token_secret: raise RuntimeError(...)` |
| The vulnerability audit has no schedule | `grep -ln "vuln-audit" .github/workflows/*.yml` | `ci.yml` only, which runs on pushes and pull requests |

## 2. What agents reported

Eight read-only agents ran on 2026-10-17, each told not to run the app, not to touch the network and
not to contact production:
- six split ASVS 5.0.0's 253 Level 1 and 2 items by chapter; their verdicts are in the ASVS file;
- one listed every measure in place for `docs/41-security-controls.md`;
- one answered section 9 of `docs/analysis/2026-10-13-security-review.md` (below).

The session checked their test citations (section 1) and the claims behind the new rows marked
"read by the session" below. The rest is the agents' reading of the code at `2f13e22`.

## 3. Section 9 of the 2026-10-13 review, answered

**A stolen session.** By the agents' reading, confirmed by the session where marked.
- A session has no maximum age, and deleting an account needs no recent sign-in (row W87; details held back until the fix ships (CHG-060)).
  A thief holding a signed-in cookie can read the account's email and last 5 questions.
- Nothing ties a session to an address or a browser, nothing shows a user their sessions, and using
  a stolen cookie writes no event.
- What stops a thief: the victim's sign-out (it revokes the shared session id), sign out everywhere
  (ADR-0137), deletion, and 2 hours idle.
- Row W87: a maximum age, a fresh sign-in before deletion, and an operator command to end sessions.
- A record of where a session was used from is the owner's decision: sign-in events may never hold
  an address under their approved keep rule (`docs/48-data-retention.md`). W89 adds no identifier.

**The app's own OpenRouter key.**
- Inside the app, spend stops at the $5.00 site ceiling a day (`costs.py:239`), plus what runs
  already going spend beyond their estimates.
- Outside the app, nothing in the repository bounds a stolen key. Only a credit limit set in
  OpenRouter's dashboard would. No CHG row records one (`grep -c -i credit docs/19-change-control-log.md`
  prints `0`).
- Nothing would notice a theft. The key check reads only the status code, and while live answers are
  off it makes no call at all (`readiness.py:301-302`). Nothing compares the app's records with
  OpenRouter's usage.
- Row W91, and an owner action (section 6).

**Bring-your-own key and one stolen machine.** `docs/analysis/2026-10-16-w28-decision-research.md`
says that whoever gets the database and the master key reads every key (its line 129). It does not
say that on Fly both are on the one machine: Fly secrets are environment variables of the same
machine that holds `/data`. So one machine compromise, or one Fly token, gives both, and encryption
would protect only snapshots and backups. This is for the W28 session to weigh; no W28 decision is
made here. It is recorded in W28's Parked line.

**ASVS Level 2.** The ASVS file has every item.

**Evidence the 2026-10-13 review did not use.**
- `docs/40-threat-model.md` states that anonymous visitors cannot run queries (they can), lists
  bring-your-own key as if it were built, and has no entry for anonymous spend abuse, supply chain,
  Sentry, CI secrets, or theft of a session, or of the app's key from the host or from CI. Row W99.
- ADR-0130 to ADR-0139: by the agents' reading, ten statements no longer hold, each changed by a later
  ADR (0142, 0144, 0163, 0165) or later code. Only ADR-0134 and ADR-0136 carry amendment notes
  (`grep -n "Amended by" docs/adr/013*.md`). Row W99.
- Response headers and cookie flags: section 1.
- Read-only settings: GitHub's in section 1. Fly's and OpenRouter's need the owner's accounts
  (section 6).

## 4. New rows

"Measured" means the session ran it; "read by the session" means the session read the cited code;
"agents' report" means neither. Codex reviewed a first version of this list before any code and
asked for three splits, a narrower W89 and corrected wording; those changes are in.

| Row | What | ASVS items and other sources | How bad | Evidence |
|---|---|---|---|---|
| W85 | Refuse a request body over a size limit before it is read, and refuse unknown fields and over-long lists in the request models | V2.4.1, V15.2.2, V2.2.1, V15.3.3, V5.2.1 | live: production is one machine with 512 MB (`fly.toml:195-197`); details held back until the fix ships (CHG-060) | measured |
| W86 | Delete signed-in history older than 30 days for every account, not only the one saving a question, and turn on `secure_delete` in the session store | V14.2.4; section-9 agent | live: old questions stay on disk, though they are not shown, against the approved keep rule (`docs/48-data-retention.md`, CHG-023). Whether production's SQLite build (Debian, `python:3.12-slim`) already deletes securely by default is UNVERIFIED; `PRAGMA secure_delete` inside the image would settle it | read by the session; that deleted text stays in the file is an agent's probe, not re-run |
| W87 | A session ends at a maximum age; deleting an account needs a recent sign-in; an operator can end one account's or every session; record why sign-in is single-factor | V7.1.1 to V7.1.3, V7.3.2, V7.6.1, V7.4.5, V7.5.2, V6.3.3, V6.8.4 | live; details held back until the fix ships (CHG-060). The owner set the values on 2026-10-17: 12 hours signed in, 24 hours anonymous, and a sign-in within 10 minutes before deletion (CHG-056 (c), (d)) | read by the session |
| W88 | Check where a request comes from before opening a counted session or replacing a visitor's anti-forgery token | V3.5.3 | live: another site can affect a visitor's sessions; details held back until the fix ships (CHG-060) | read by the session |
| W89 | A crash inside a run is logged and reaches Sentry; refusals (401, 403, anti-forgery, 429, 422) are counted apart in `/metrics`; uvicorn logs in the app's JSON format. No new identifier is recorded: adding an address or a network to sign-in events would change their approved keep rule (`docs/48-data-retention.md`, which says "never … an address"), so that is the owner's decision | V15.3.4, V16.2.1, V16.2.2, V16.2.4, V16.3.1 to V16.3.4, V16.4.1 | live: today a crash marks the run failed with the error's class name and nothing more, and refusals are counted only as `4xx`. Sign-in, sign-out and sign-out everywhere already write events | crash: read by the session; the rest agents' report |
| W90 | The browser keeps no private data: `Cache-Control: no-store` on every `/v1/` answer, `Clear-Site-Data` at sign-out and deletion, the page cleared at idle expiry or a failed sign-out, and "Sign out" visible on every view | V14.2.2, V14.3.1, V14.3.2, V7.4.4 | live, on a shared computer | missing header measured on `/status`; the rest agents' report |
| W91 | Notice a stolen OpenRouter key: compare the key's usage, from OpenRouter's free key endpoint, with the app's own records, and alert | section-9 agent | live: the key is a production secret whether or not live answers are on | agents' report |
| W92 | The supply chain on a schedule: a daily vulnerability audit, base images pinned by digest, the image's system packages audited, deploy the image CI checked (Fly builds its own today), ruff's security rules, a list of what the image contains | V15.1.1, V15.1.2, V15.2.1, V1.2.4, V1.5.2, V11.4.1; inventory SC-84 | live: a vulnerability published after a merge waits for the next merge | audit schedule: read by the session; the rest agents' report |
| W93 | Serve the fonts from this site, so Google no longer receives every visitor's address | V14.2.3 | live, privacy | agents' report |
| W94 | Limits at scale: a site-wide cap on sign-in-only sessions, a daily session limit per IPv6 /48, concurrent runs per network, the trust given to Fly's private range `fdaa::/16`, a per-minute limit for allow-listed networks, a limit on history reads, old per-account limiter entries never swept | section-9 agent; inventory | live and dormant parts; **every value is the owner's**, and the session has no measured basis to propose them yet | agents' report |
| W95 | Keys: one list of every key with its use and owner; `QUORUM_TOKEN_SECRET` refused under 32 bytes, and one key per purpose; `DEPLOY.md` says everything that secret keys (rotating it also restarts every network's daily allowance, ADR-0144), and its doc check reads more than `auth.py`. The replacement steps themselves are W79's, in `docs/84-incident-response.md` | V11.1.1, V11.1.2, V11.2.2, V11.2.3, V13.3.2 | process. Whether production's secret is short is UNVERIFIED; only its presence is checked | length check: read by the session; the rest agents' report |
| W96 | The model-catalog fetch, which runs at every start (`main.py:756`), refuses redirects and plain http, as the key-carrying calls do | V15.3.2, V12.3.1 (b) | live but low: it sends no key, and the default address is https; its prices feed the cost estimate | read by the session (`catalog_fetcher.py:94`, `:571`) |
| W97 | Google sign-in token checks: send and check a `nonce`, refuse a future `nbf`, and either check the ID token's signature against Google's keys or record the exception to ASVS in ADR-0130 | V6.8.2, V9.1.1, V9.1.2, V9.2.1, V10.5.1 | low: the token comes only from the server's own call to Google over verified TLS, which ADR-0130 decision 4 says OpenID Connect allows (the ADR notes the specification text was not re-read); no bypass is shown | ADR-0130 read by the session; the rest agents' report |
| W98 | Give a test to each measure in place that no test would miss | V1.2.3, V3.3.4, V3.4.2, V3.5.1, V3.5.2, V3.7.2, V4.1.1, V6.3.2, V6.3.4, V7.2.2, V7.2.3, V8.2.2, V8.2.3, V12.2.1, V12.3.2, V13.2.2, V13.2.3, V13.4.1, V13.4.3, V13.4.4, V14.3.3, V15.2.3, V16.5.1; the "no test" list in `docs/41-security-controls.md` | a later change could remove the measure unnoticed | agents' report |
| W99 | Make the security documents match the code: rewrite `docs/40-threat-model.md` and `docs/45-control-mapping.md`; one table each for routes and who may call them, stored data and its keep time, outbound connections, logs, sign-in pathways, and request rules and limits; amendment lines on the session ADRs; test files `docs/18-requirement-traceability-matrix.md` names that never existed; stale numbers and comments; the placeholder `.github/CODEOWNERS` | V2.1.1 to V2.1.3, V14.2.4, V6.1.1, V6.1.3, V8.1.1, V8.1.2, V13.1.1, V14.1.1, V14.1.2, V15.1.3, V16.1.1, V16.2.3; section-9 and inventory agents | process. Takes `docs/45` over from W77 | agents' report |
| W100 | The page sends a high-stakes acknowledgement only when the user ticked the box, and checks the warnings again before it creates the run | inventory SC-68 | live: the server records an acknowledgement the user never gave; details held back until the fix ships (CHG-060) | read by the session (section 1) |
| W101 | Invite links, off in production: the cookie gets the `__Host-` prefix, the key must be 32 random bytes, the host is part of what is signed, and revoking a link ends the sessions it opened | V3.3.1, V3.3.3, V9.1.3, V9.2.3; section-9 agent | low while invite links are off (`/status` `invite_links.enabled: false`) | agents' report |

**Existing rows that change** (same concern, same code, so they share the pull request):
- **W71** also counts the web-search provider's calls (Tavily), which no limit counts today
  (`costs.py` names Tavily only in a comment). Agents' report.
- **W72** also limits the page fetcher to ports 80 and 443 and prefers https (V1.3.6, V12.3.1 (a)).
  Dormant while live answers are off. Agents' report.
- **W73** also records, as a threat, that panel models asked with `:online` (`providers.py:1470`)
  receive web results that OpenRouter adds and the app never sees, so the app's fence cannot cover
  them; W74's attack suite should measure it. Agents' report; the call site read by the session.
- **W75** also adds `object-src 'none'`, puts the security headers on unhandled-error responses
  (measured, section 1), and fills the page template in one pass, so a model-catalog label naming a
  placeholder cannot break the page's data (V1.3.7, agents' report).
- **W77** keeps the security reviewer in every round and the replacement of the generic security
  skills. Its `docs/41` part is done by W82, and its `docs/45` part moves to W99.

**Not made rows** (advisory, recorded in the ASVS file or here): two `escapeHtml` functions in
`app.js` (V1.2.1); optional strict request types and a lint rule for loose comparisons (V15.3.5,
V15.3.6); whether Fly's proxy refuses an ambiguous request length (V4.2.1, needs a test against Fly
that the session may not run); the PDF child keeps network access and has no file-count limit,
which ADR-0153 accepted; a visitor's `sentry-trace` header can force Sentry to sample, which costs
Sentry quota only; the test suite's network guard does not block name lookups.

## 5. The order

**The owner set the front of this order on 2026-10-17 (CHG-061, which replaces CHG-059's order):
the small live rows W85, W86, W100, W87, W88 and W80 first, then W75 and W76, then W28
(bring-your-own key, in a fresh session whose research for decisions 1, 2 and 4 starts at once, in
parallel), then the rest in the order given below.** W28's decision 3 is decided (signed-in only);
decisions 1, 2 and 4 wait on research into enterprise practice.

**The rest is PROPOSED by the session, reviewed by Codex; not an owner decision.** The owner's decisions are that
the baseline comes first (CHG-051) and that new rows join the same queue, a serious one first if
need be (CHG-055). The order follows four rules:
1. Live in production now: first, most harmful first.
2. Live but waiting on an owner value: built as soon as the owner answers.
3. Before bring-your-own key (W28 follows W71 to W81, CHG-051): W75, W76.
4. Before paid live answers are switched back on (they are off): W71, W72, W73.
Process, documents and low-risk rows come last; rows waiting on the owner are parked. Five rows break
these rules on purpose: W81 and W78 are not live in production but come early because they guard
the work itself (agent sessions reading `.env`, and the board's record of what is done), and both are
small; W79 with W95 (process) comes before the live W76 and W75 because a way to report a flaw and
steps to replace a key help with every later incident, and both are small; W93 is live but comes late
because it moves the screenshot baselines (ADR-0149).

| # | Row | Why here |
|---|---|---|
| 1 | W85 | Live, measured; a size limit is a small change |
| 2 | W86 | Live; keeps question text past the 30 days the owner approved |
| 3 | W100 | Live; the server records a consent the user did not give |
| 4 | W87 | Live; sessions have no maximum age. The owner set its values on 2026-10-17 (CHG-056 (c), (d)) |
| 5 | W88 | Live; another site can affect a visitor's sessions |
| 6 | W80 | Live: a cross-site link cancels a sign-in in progress. `/feedback/audit` answers any session, though production has no report to serve (`/status` `latest_audit: null`) |
| 7 | W90 | Live on shared computers |
| 8 | W89 | Live; crashes and refusals leave too little trace to look into an incident |
| 9 | W81 | Protects the owner's local secrets from agent sessions; small |
| 10 | W78 | A false "done" on the board passes every check; the owner chose to build the re-check (CHG-056 (b)) |
| 11 | W91 | The app's key is a live secret and its theft would go unnoticed |
| 12 | W79 with W95 | A route to report a flaw, steps to replace a key, and the key list |
| 13 | W92 with W96 | The supply chain on a schedule, and the catalog fetch that runs at every start |
| 14 | W76 | Key-safety gaps to close before W28; moved ahead of W28 by the owner (CHG-061) |
| 15 | W75 | The script nonce and the header fixes, before W28; moved ahead of W28 by the owner (CHG-061) |
| 16 | W71 | Before live answers |
| 17 | W72 | Before live answers |
| 18 | W73 | Before live answers |
| 19 | W74, priced | The owner chose to price the attack suite first (CHG-056 (a)); pricing is free, the run waits for the owner's amount |
| 20 | W77 with W99 | A security reviewer in every round, and documents that match the code |
| 21 | W98 | Tests for the measures no test would miss |
| 22 | W93 | Privacy; it touches the screenshot baselines (ADR-0149) |
| 23 | W97 | Low: no bypass shown |
| 24 | W101 | Low while invite links are off |

**Waiting on the owner (the Parked table):** W74's spend, once it is priced, and W94 (limits at
scale; the session will propose measured values before asking). **After the queue, if there is
room:** W83 and W84 (the session prompt).

## 6. For the owner

**Asked on 2026-10-17, and answered (CHG-056).** The session asked four questions in one batch,
after Codex had reviewed the order. The owner chose the session's recommendation each time:
- W74: price the attack suite first, from public prices, then ask for one exact amount; no paid call
  before that.
- W78: build the re-check of a row's first committed evidence.
- W87: a signed-in session ends 12 hours after it started, an anonymous one 24 hours after.
- W87: deleting an account needs a Google sign-in within the last 10 minutes.

**Account settings the session could not read.** Each is free and needs the owner's login:
- a credit limit on the app's OpenRouter key and on the judge's key (OpenRouter's dashboard);
- whether `FLY_API_TOKEN` is a deploy token for this one app (`fly tokens list`);
- how long Fly keeps volume snapshots, which hold the databases;
- 2-step login on Fly, Google Cloud, OpenRouter and Sentry (GitHub's is on: read on 2026-10-17, CHG-057);
- who Sentry alerts, and whether a log drain is wanted (it is not free, ADR-0031);
- in GitHub: when section 1 was read, Dependabot alerts, private vulnerability reporting and secret
  scanning's validity checks were off. On 2026-10-17 the owner told the session to switch some of
  them on (CHG-057). Read back afterwards: Dependabot alerts and the dependency graph are on in all
  17 repositories; private vulnerability reporting, secret scanning and push protection are on in
  all 10 public ones. In the private ones, private vulnerability reporting answers `404` (GitHub
  documents it for public repositories only) and the other security settings read `null`; whether
  the plan offers those there is UNVERIFIED; validity checks stay off, because GitHub
  accepts the change through the API and does not apply it.

## 7. What this baseline did not cover

- No attack on production. The request-size probe and the error-page probe ran on a local copy.
- Whether Fly's proxy limits request size or refuses ambiguous request lengths.
- The full list of TLS ciphers production accepts.
- Live model attacks (W74, which needs the owner's approval of its spend).
- The agents' file and line citations were read at `2f13e22`; later changes move them.
