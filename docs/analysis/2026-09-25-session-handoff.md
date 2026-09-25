# Session handoff — 2026-09-25 (eight-package run: seven delivered in part or whole; two production faults found by the owner's live test)

Read `AGENTS.md` first, then this. The procedure for the next session is the
untracked root prompt `CONTINUE-2026-09-25-ULTRACODE-PROMPT.md`; this file is
the record. Figures point at the pull request, commit body or command that
holds them. The session ran from the owner's prompt
`CONTINUE-BACKLOG-2026-09-24-ULTRACODE-PROMPT.md` (untracked, repo root;
assistant-drafted, sent by the owner) from 2026-09-24 to 2026-09-25,
transcript `efe4f2fc`.

**Attribution.** "The owner decided" appears below only where a `type: user`
record exists, with its UTC time. Everything else is the session's wording.

## 0. Preconditions

```bash
cd /Users/rohitagrawal/Projects/quorum-ai
git status --porcelain   # expect only the CONTINUE-*.md prompts (untracked)
git worktree list        # expect quorum-ai (main) and quorum-ai-wt-268 (parked)
curl -s https://quorum.stackclimb.com/status | jq '{build_sha,live_execution,peer_critique_enabled,sign_in_enabled}'
```

At close: `live_execution` false, `peer_critique_enabled` false,
`sign_in_enabled` **true**: the three Google settings were set on 2026-09-25,
not by the session, which ran no `fly secrets` command.

## 1. Merged and running in production

Each row: the Deploy **job** read, exactly one `success` among the runs for
the merge SHA (run id given), `/status.build_sha` matched, `/ready` 200.

| Package / item | PR | merge | Deploy run |
|---|---|---|---|
| 1. #458 peer critique coupled to the live window; CHG-012 (ADR-0122) | #499 | b6213c4 | 35988702649 |
| 2. The confirmation token binds the panel and the critique shape (ADR-0123) | #502 | 4b8f9ce | 36042264957 |
| 4. #459 every watchdog latency reads the measured interval | #503 | f2de08a | 36051196970 |
| 5. #447, 1 of 2: the source fetcher, shipped off (ADR-0124) | #504 | 81eee7a | 36065270279 |
| 6. #268 (b): the bound prices web-search context from its own figure (ADR-0125) | #505 | 498f154 | 36073767803 |
| 3. W5, 1 of 4: `mode: "quick"` (ADR-0126) | #506 | e8c7503 | 36079750033 |
| 3. W5, 2 of 4: the quick verdict, scores, sources (ADR-0127) | #507 | 9b0c9da | 36086718770 |
| 3. W5, 3 of 4: the workspace shows the quick answer (ADR-0128) | #508 | 1fc3b45 | 36095476384 |
| 3. W5, 4 of 4: the quick judge verifies and shows its claims (ADR-0129) | #509 | 2c76efa | 36104719948 |
| 7. W7, 1 of 3: sign in with Google and sign out, shipped off (ADR-0130) | #510 | 099c5d4 | 36129436521 |
| Production fault: loading the page replaced the CSRF token (ADR-0131) | #511 | 709ccfe | 36141095011 |
| This handoff, CHG-021, CHG-022, board rows W30 to W32 | this PR | — | — |

Merges used `Refs`, never a closing keyword; `make close-guard` ran with an
empty `EXPECT_CLOSE` each time. So #458, #459, #268 and #447 are still OPEN
on GitHub although their work merged (#447 only half; see §2). Closing them is
the owner's.

## 2. Not finished — in the order the next session takes them

**The order below is partly the session's.** The owner approved (13:47:58Z,
*"Everything is approved here"*) the session's proposal of 13:42:33Z, whose
order was: the address fix, the allow-list, then W7's second pull request.
That proposal put the invite link "later, only if needed"; the owner's
13:48:26Z message brings it into the plan without placing it. W29 (#447's
second half) was in neither message; the 2026-09-24 order put #447 before W7
(CHG-012 D6). So placing the invite link third and W29 fourth is the
session's reading, put to the owner at the close of this session; the next
session uses the owner's answer if there is one.

1. **W30 — the per-network session limit counts the app's own address.**
   Found 2026-09-25 when the owner could not retest #511 ("This network has
   reached its session limit"). Measured: `fly ips list` shows
   `2a09:8280:1::131:de60:0` (dedicated v6) and `66.241.125.57` (shared v4)
   as quorum-ai's own ingress addresses; production logged the owner's
   browser and the session's `curl` under those, while the session's real
   address was `171.76.82.80` (ipify). So the daily new-session cap (2) and
   the per-minute session limit are one bucket per address family for every
   visitor. **UNVERIFIED and to measure first (AGENTS 8c):** what Fly
   forwards (`Fly-Client-IP`, the `X-Forwarded-For` order). `main.py` keys
   both limits on `request.client.host`; the Dockerfile trusts
   `--forwarded-allow-ips 172.16.0.0/12,fdaa::/16,127.0.0.1,::1` (since #58,
   2026-07-21), and uvicorn then reported the app's own address. CHG-022.
2. **W31 — the allow-list**, as CHG-022 item (2). ADR in the same PR.
3. **W32 — the invite link**, CHG-022 item (4). Owner, 13:48:26Z: *"Invite
   link should not be later. I expect it should be planned and included."*
   Failure modes first: a leaked link, revocation, whether uses are capped,
   who can mint one, that it never lifts a spend limit.
4. **W29 — #447, 2 of 2: the judge wiring** (page text into the judge's
   evidence, the input reserve, the receipt row, the posture-keyed copy;
   ADR-0124). If the input reserve moves a shipped money value, DRAFT and
   stop.
5. **W7, 2 of 3 — history and deletion.** CHG-012 D7 (keep the last 5 runs
   and 30 days as `HISTORY_KEEP_COUNT` / `HISTORY_KEEP_DAYS`, summary rows
   only, nothing deleted on sign-out, typed-confirmation deletion, the
   24-hour spend envelope on a one-way hash of the Google subject, "Results
   are ephemeral" rewritten for signed-in users) plus CHG-021 (a) carry-over
   of the same browser session's runs at sign-in and (f) a reminder and a
   re-confirmation before deletion. Failure modes first, including two races
   the session promised the owner (11:30:42Z), each with a test: deleting an
   account while it is signed in on another device, and carrying runs over
   while one of them is still running. Already measured on #510's code (chat
   only, not re-run): 200 rounds of 8 simultaneous first sign-ins for one
   Google account gave 1 account row each time; a copy with the database lock
   weakened failed on round 1.
6. **W7, 3 of 3 — session safety.** CHG-021 (b) idle expiry with a
   keep-active reminder, (c) sign out everywhere, (d) sign-in events (time
   and outcome, never tokens), (e) a rate-limited sign-in start. The idle
   length and the rate-limit value are the session's proposals, as settings.
   The third promised race gets a test here: "sign out everywhere" while
   other requests of that account are in flight.
7. **Package 8 — BYOK.** Last (CHG-012 D8). First PR as a DRAFT and stop;
   ADR-0121 stays `PROPOSED — AWAITING OWNER`.

## 3. Owed by the owner

- **Retest #511** (sign-out and a query after sign-in). Blocked by W30 until
  it is live.
- **Google Auth Platform → Audience.** An account not on the test-user list
  signed in (owner, 2026-09-25). The app has no allow-list of accounts;
  Google enforces the test-user list only while the app is in "Testing".
  **Likely cause, the session's own error:** its first setup steps
  (08:58:29Z) said *"click "Publish app" so it is **In production**"*; its
  later steps (§6 below) said to leave it on Testing. If the first were
  followed, any Google account can sign in. UNVERIFIED until the owner reads
  the publishing status. To restrict sign-in, set it back to Testing (only
  listed users) or accept the allowed-emails offer below.
- **Visual-flake tolerance.** `e2e/tests/invariants/trust-score-visual.spec.ts`
  allows `maxDiffPixels: 120`; the trust-score card (dark, 1440) differed by
  589 pixels on #499 (twice, 2026-09-24 morning; that PR changed
  `workspace.html`) and on #504 (2026-09-24 evening; no UI change), where it
  passed on re-run (run 36059793718, attempt 2). The session's advice: measure the flake
  rate and read the failing run's trace before any tolerance change.
- **The peer drift alert.** ADR-0122 decision 5: the watchdog names a true
  `PEER_CRITIQUE_ENABLED` with live execution off as DRIFT but only reports
  it. Escalating it to an alert is `PROPOSED — AWAITING OWNER`. The session's
  advice: yes. A flag set by a Fly secret is invisible to every tracked file
  and pre-merge gate; today only the watchdog's report and a manual `/status`
  read see it, and neither alerts.
- **Close or keep** draft PR #491 (superseded by #505) and draft PR #501
  (W5 parked; W5 has since shipped), and the issues whose work merged under
  `Refs`: #458, #459, #268 (and #447 after W29).
- **Whether the quick answer's app-written reasons and quoted claims** are
  enough (W5, ADR-0127 and ADR-0129).
- **ADR-0121 (BYOK) acceptance.**
- **Two unanswered offers** (`PROPOSED — AWAITING OWNER`; default if
  unanswered: neither is built): (i) build W7's spend limit as a per-account
  lookup that returns today's value, so paid tiers later change only where
  the number comes from (11:34:12Z); (ii) an allowed-emails setting limiting
  who may sign in, independent of Google's test-user list (13:30:33Z).
- **Paid tiers** (the owner's question, 11:33:40Z): no decision. The
  session's advice: a separate package, failure modes first (duplicate and
  out-of-order payment notices, failed renewals, refunds, a wrong
  downgrade), and ADR-0002's single-writer SQLite decision re-measured
  before any payment record is stored.
- Answered in chat from existing records, no new decision: duplicate-email
  sign-up and password reset (accounts key on Google's subject; no password
  exists; ADR-0130), and BYOK's $5 ceiling (ADR-0121).

## 4. Traps measured this session

- **A GET that changes session state breaks under a second fetch.** `/ui`
  rotated the CSRF token; a second `GET /ui` that ran no page code arrived
  after the page had its token, on each of the four loads read, so every
  protected request answered 403 (ADR-0131). The logs cannot tell visitors
  apart (W30), so "the owner's browser" is the likely sender, not a
  measured one. Every sign-in test was green because each drove one clean
  page load.
- **`fly logs --no-tail` holds about 100 lines and rolls over within
  minutes** (the evidence for ADR-0131's table was gone by the review).
  Save it to a file the moment a live report arrives.
- **Editing the tree during a backgrounded gate** produced a false 85% from
  `diff-cover` (a comment line added mid-run shifted every line number).
  AGENTS rule 9a; it happened anyway. Re-run on a committed, still tree.
- **The advisory mutation job can measure nothing and go red** — #510:
  `0 killed, 0 survived`, "UNMEASURED: the run was cut short by its own
  wall-clock deadline". Read the log before citing it either way.
- **Every new module-level constant in risk-tier code needs a bucket**:
  `test_every_risk_constant_is_triaged` failed on `_DEFAULT_PORTS`, added in
  a review round.
- **mypy refuses `google_signin.settings`** (not an explicit export); patch
  `product_app.config.settings`.
- **This machine has used its session allowance for the day**
  (`/v1/session` answered 429 from here at 12:00Z, and with W30 that
  allowance is shared with every visitor); production browser checks need the owner
  until W30 is live.
- **Background wait loops outlived their purpose**: at the owner's question
  (09:17:51Z) the session found 8 of its own polling shells, up to 1 day
  1 hour old. Every wait loop needs a wall-clock limit.
- **The `scriptPath` + `script` trap** (memory
  `workflow-scriptpath-wins-over-script`) re-ran an old review; pass `script`
  only for a new round.

## 5. Practices this session followed (pointers, not copies)

The owner asked for an exhaustive handoff (13:49:03Z). This file POINTS to
the practices rather than copying them, and says so here, because a second
copy drifts from the first. Most live in `AGENTS.md` and the owner's global
instructions; the rest were only in the 2026-09-24 prompt, and
`CONTINUE-2026-09-25-ULTRACODE-PROMPT.md` §2, §3, §6 and §7 carry them
forward in full. The ones that decided outcomes today:
rule 1 (execute, including where things are), 6/6a (mutation, verbatim red),
7 (a positive partner), 8c (measure the upstream first — W30), 9/9a/12b
(read-only reviewers in their own `git archive` copies, never move the tree
under a gate), 11a (the prose lens caught the ADR-0131 overstatements), 12
(two rounds), 13f (exit codes read directly), 16d/16e (an ADR per decision,
failure modes first), 17c (explicit squash message, close-guard), 18/18a
(deploy JOB, `build_sha`, `/ready`, then clean up).

## 6. Google sign-in setup — the operator runbook (corrected)

The owner has already done this once. Kept here because chat is not a
record, and because the first version (08:58:29Z) was wrong about step 4.

1. Google Cloud Console → Google Auth Platform (menu names may differ).
2. **Branding:** app name, support email, authorised domain `stackclimb.com`.
3. **Audience:** External. **Leave it on "Testing"** and add each tester's
   Gmail under "Test users"; only they can sign in. "Publish app" lets any
   Google account sign in; do it only when that is wanted.
4. **Data access:** only `openid` and `.../auth/userinfo.email`.
5. **Clients → Create client → Web application;** authorised redirect URI
   exactly `https://quorum.stackclimb.com/v1/auth/google/callback`; no
   JavaScript origins.
6. Set the three secrets without echoing the secret or saving it in history:
   ```bash
   read -rs SECRET
   printf 'GOOGLE_OAUTH_CLIENT_ID=%s\nGOOGLE_OAUTH_CLIENT_SECRET=%s\nGOOGLE_OAUTH_REDIRECT_URI=%s\n' \
     "PASTE_CLIENT_ID" "$SECRET" "https://quorum.stackclimb.com/v1/auth/google/callback" \
     | fly secrets import -a quorum-ai
   unset SECRET
   ```
7. Check: `/status` shows `"sign_in_enabled": true`; `fly logs` shows
   `google sign-in is on` (or `google sign-in is OFF: ...` with the reason).
   Sign-in is offered only on `quorum.stackclimb.com`, not `quorum-ai.fly.dev`.
8. Off again: `fly secrets unset GOOGLE_OAUTH_CLIENT_SECRET -a quorum-ai`.
