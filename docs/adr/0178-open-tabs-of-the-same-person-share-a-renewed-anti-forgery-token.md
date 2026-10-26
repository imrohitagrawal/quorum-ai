# ADR-0178: Open tabs of the same person share a renewed anti-forgery token

## Status

Accepted — 2026-10-25, board row W105. The owner's decisions it builds on are CHG-071 ("Tabs share
the new token (Recommended)": the renewing tab passes the token on, and no message is shown) and
CHG-089 (case 1: tabs of another person do not share; case 2: a click already sent is refused as
today, with no retry, which was NOT the session's recommendation; case 3: two anonymous sessions
count as the same person; case 4: a tab that missed the message is refused as today; the counter's
10 s limit and per-reset id; the size limit of 3,200 changed lines; and, answered on 2026-10-26, "Keep
10 seconds (Recommended)" for the wait, see Measured; "Fix it in W105 first" for the drawn-account
guard, decision 8, which was NOT the session's recommendation; and "Continue, stop at 5,000
(Recommended)" for the size). **Everything else below is the session's design.** Codex reviewed the
plan five times, and the guard's plan twice, before any code (ADR-0168, decision 7); the
reviews and the plans are kept outside the repository and none has a committed record.

**Supersedes**, without editing them (`docs/README.md`: "superseded never edited"):

- ADR-0131, Consequences, first bullet ("Two tabs still invalidate each other's token"): for open
  tabs of the same person this no longer holds; for the cases in Known limits below it still does.
- ADR-0177, Known limits, "The second-tab token effect" (its lines 224-228): handled here.
- ADR-0175, decision 12 (the late-run card saves under the account the bootstrap names, not the
  markup): for a page drawn as a known identity whose bootstrap names another, see decision 8.

## Context

Every `GET /v1/session` replaces the session's anti-forgery token
(`tests/integration/test_page_load_keeps_csrf.py::test_the_session_call_still_retires_the_previous_token`),
and the page calls it once at boot and from "Start a session" (`retrySession`). So a second tab, or
a tab opened from another site's link (ADR-0177, Known limits, "The second-tab token effect"),
left the first tab holding a retired token: its next protected request got 403 `CSRF_INVALID`,
"Security check failed" and "Refresh session". `api()` is unchanged. The sharing is in `app.js` only; the guard (decision 8) adds one data island to `/ui`.

## Decision

1. **The channel.** `new BroadcastChannel("quorum-session-token")`, opened once as the script
   starts, before the first bootstrap. Without it (no API, or its constructor throws) the page
   neither sends nor receives a token, so its tabs are refused as before W105. Its renewals still
   take the lock and a number, so it can still wait as decision 6 says.
2. **The message.** `{kind: "csrf-token", token, identity, gen, seq}` and nothing else. The token is
   never written to storage, a URL, the DOM or a log.
3. **The sender.** Only `renewSessionToken` posts, once per renewal that held the lock and took a
   number, and only when the identity is known: the account the answer names, or `"anonymous"` only
   for `anonymous: true` (`sharedTokenIdentity`, which `initSession` now uses for `pageIdentity`
   too). The identity is the one answered inside the lock, not the one held before the wait.
4. **The receiver** (`acceptSharedToken`) takes a message only when all hold: the shape and kind; a
   token matching `^[A-Za-z0-9_-]{16,128}$` (the server's are 32 characters); a non-empty identity
   equal to this page load's `pageIdentity`, which has not changed; sharing not off; not in the
   middle of its own renewal; the same `gen`; a safe-integer `seq` above the highest this tab has
   held. Taking it changes the token and `tokenSeq` only: no request, no post, no notice.
5. **The order.** Each renewal runs inside one Web Lock, `quorum-session-token`; inside it the tab
   takes the next number from one IndexedDB record `{gen, seq}` (one `readwrite` transaction,
   resolved on `complete`), then makes its one `/v1/session` fetch. So the numbers follow the order
   in which the server issued the tokens, and a late message carries a lower number. `gen` is a new
   `crypto.randomUUID()` whenever the record is created, so a message from before the browser
   cleared the site's storage is never compared with one from after.
6. **Bounds and fallbacks.** The wait for the lock is bounded at 10 s (`AbortSignal.timeout`), and
   the counter step at 10 s. No lock, a lock refused before its callback, a wait that times out, or
   no number (no IndexedDB, a refused or failed open or transaction, `blocked`, a malformed or
   exhausted record, the limit) all mean: renew once without them and turn sharing off for the rest
   of the page load. From then on the tab behaves as today, but it may first have waited: a lock
   wait that times out has taken 10 s, and a tab that got the lock late can then wait up to 10 s
   more for the counter, so about 20 s before its one fetch in the worst order (the sum is read from
   the code; the 10 s lock wait is measured, see Measured). With no lock API at all it renews at
   once. The owner chose to keep 10 s (CHG-089 (g)). A failure INSIDE the lock is
   thrown out as today; nothing renews twice. The fetch inside the lock is deliberately NOT bounded:
   today it waits as long as the network takes, and a bound would change that.
7. **No retry anywhere** (case 2). A request that left with the old token is refused once, as today.
8. **The drawn-account guard** (CHG-089 (h); round-2 review: a tab drawn signed out, waiting for the
   lock while another tab signed in as Y, was then answered as Y and ran as Y). `/ui` looks the
   account up ONCE and uses that one result for the account controls, `Cache-Control: no-store` and
   a `drawn-identity` JSON data island (every `<` written `\u003c`, like the other islands). The
   island holds the account id, `"anonymous"` only when the store says the id is certainly in no
   accounts row, or `""` (unknown): `/v1/session`'s rule, now one function, `_drawn_identity`.
   That is one account lookup; for a page with no account, when there is a store, one more store
   read (`is_anonymous`) tells `"anonymous"` from `""`. The page reads the island
   (`readDrawnIdentity`), and both renewal paths keep a token only through `keepRenewedToken`.
   When an answer's identity and the drawn one are both known and differ, the tab sets
   `drawnMismatch` for the rest of the page load, and `pageIdentityChanged`, so nothing is saved.
   It then keeps no token on that renewal or any later one, takes none from another tab,
   puts no saved late-run question back (the stored entry is still removed), and "Start a session"
   reloads the page instead of saying "Session started". Its next write gets today's "Security
   check failed" and "Refresh session". A refused LOCKED renewal still posts its token under the
   answer's identity, `gen` and `seq`, because `/v1/session` has retired the old token of that
   identity's tabs; a lockless one posts nothing, like every lockless renewal. An unknown side
   alone refuses nothing; an earlier refusal on the page load still stands. For a page drawn as a
   known identity whose bootstrap names another, this supersedes ADR-0175's rule that the late-run
   card saves under the account the bootstrap names, not the markup (the orchestrator's reading of
   CHG-089 (h), not an owner decision).

## Measured

| What | How | Result |
|---|---|---|
| The test designer's unit tests, before and after | `tests/unit/test_w105_tabs_share_token.py` on `a20e0f4` (the designer) and on the build | `113 failed, 3 passed`; `116 passed` |
| The browser specs, before and after | each spec with CI's settings (`e2e.yml`: rate 600, mint cap 1500, the anonymous spend override), `--workers=1 --retries=0` | navigation `6 failed, 4 passed` (the designer; the 4 pin today's behaviour); signed-in `3 failed`; after the build `10 passed` and `3 passed` |
| The tests bite | the designer's mutations of its own reference copy, kept outside the repository | unit 60 of 60 killed; e2e 9 of 9 killed |
| The e2e lanes, as `e2e.yml` runs them | CI's settings (`e2e.yml`: mint cap 1500), then `scripts/check_e2e_executed.py` (the builder, 2026-10-25) | invariants `459 passed` (floor 457); axe + parity `133 passed` (117); navigation `72 passed` (72); signed-in History `57 passed` (57) |
| Flake count | each new spec with `--repeat-each=10` | navigation `100 passed`; signed-in `30 passed`; 0 failed |
| The guard's tests, before and after | the marker and guard test files, and `tabs-drawn-identity.spec.ts`, on `5574730` (the designer) and on the build | `81 failed, 3 passed`, then `84 passed`; e2e `3 failed`, `3 passed`, then `6 passed` |
| The guard's tests bite | the designer's mutations of its own reference copy, kept outside the repository | unit and server 19 of 19 killed; e2e 2 of 2 |
| The signed-in History lane with the guard | as `e2e.yml` runs it, CI's settings, then `scripts/check_e2e_executed.py`; the logs are kept outside the repository | on `87233ec`: `63 passed`, `63 tests executed (floor 63)`; with review round 3's added test (2026-10-26): `64 passed`, `64 tests executed (floor 64)` |
| The guard's flake count | each spec with `--repeat-each=10` on `87233ec`, CI's settings; the logs are kept outside the repository | `tabs-drawn-identity` `60 passed`; signed-in `tabs-share-token` `30 passed`; navigation `tabs-share-token` `100 passed`; 0 failed |
| The late-run harness still bites | `test_late_run_question_rules.py` with `pageIdentityChanged = true;` removed from `initSession`, restored and checked with `diff -q` | `2 failed, 17 passed`; restored `19 passed` |
| A clock cannot order the tabs | Codex's model of revision 3 (each page sets its own time offset); its two printed lines joined | `{"arrivalA":1000,"arrivalB":1001,"atA":101000,"atB":1001, "server":"T2","B":"T1","todayB":"T2"}` |
| An unbounded counter step stops the boot | Codex's probe of revision 4 | `{"entered":true,"signalAborted":true,"sessionFetches":0,"todaySessionFetches":1}` |
| A catch-all lock fallback renews twice | Codex's probe of revision 2 | `{"entered":true,"renewalCalls":2,"todayRenewalCalls":1}` |

### The wait length (CHG-089 (g))

Measured by the review of `7c2a896` (2026-10-25) in its own copy: a local server and Chromium,
with Playwright holding one tab's `/v1/session` answer for 25 s, or delaying every tab's answer by
the time shown. "Today" is the same page with `navigator.locks` undefined and no
`BroadcastChannel`. "Works" counts the tabs whose next "See the estimate" got 200, not 403. The 2 s
rows set `SESSION_TOKEN_WAIT_MS` to 2000 in that copy and restored it. Each row's "today" is from
the same run. The logs are kept outside the repository.

| Case | Wait | Today | W105 |
|---|---|---|---|
| One tab's answer held, then a second tab opens: its boot | 10 s | 71 ms | 10,073 ms |
| The same | 2 s | 70 ms | 2,067 ms |
| 10 tabs open together, no delay: boots; tabs that work | 10 s | 329-395 ms; 1 of 10 | 262-361 ms; 10 of 10 |
| The same | 2 s | 381-408 ms; 1 of 10 | 228-342 ms; 10 of 10 |
| 10 tabs, each answer 300 ms | 10 s | 670-694 ms; 1 of 10 | 536-3,421 ms; 10 of 10 |
| The same | 2 s | 577-583 ms; 1 of 10 | 538-2,566 ms; 1 of 10 |
| 3 tabs, each answer 1,000 ms | 10 s | 1,207 ms; 1 of 3 | 1,158-3,194 ms; 3 of 3 |
| The same | 2 s | 1,167-1,168 ms; 1 of 3 | 1,156-3,187 ms; 1 of 3 |
| 5 tabs, each answer 3,000 ms | 10 s | 3,197-3,201 ms; 1 of 5 | 3,154-13,173 ms; 1 of 5 |
| The same | 2 s | 3,170-3,184 ms; 1 of 5 | 3,162-5,173 ms; 1 of 5 |

Decision: the wait stays 10 s, for the lock and for the counter. The owner chose "Keep 10 seconds
(Recommended)" on 2026-10-26 (CHG-089 (g)); the option's wording and its "(Recommended)" are the
session's. 5 s was not measured.

## Rejected alternatives

- **Share with every tab** (case 1's other option): a tab still showing asha@ would run, spend and
  save History as Bob, or as the anonymous allowance.
- **Retry once, quietly** (case 2's other option, the session's recommendation): the owner chose
  today's refusal. ADR-0131 had already rejected a broad retry.
- **A server tag, or a server sequence number** (case 3's and the design question's other options):
  the owner chose the page-only options instead (CHG-089 (c), "Keep W105 page-only", and (e)), as
  CHG-071 described. The guard's island (decision 8) came later, under CHG-089 (h) and (i): it tells
  the page which identity it was drawn for, and neither tags nor numbers a token.
- **Ask the other tabs for the token** (case 4's other option): more code, untestable here (the
  test browser never uses the back/forward cache), and no help when no open tab holds the latest
  token.
- **A clock value to order messages**: tabs' clocks disagree (Measured).
- **Bypass the lock after a timeout and keep sharing**: a lock holder whose fetch stalls answers
  late with an older token; Codex's model of revision 1 printed `{"server":"T2","A":"T1","B":"T1","bothRefused":true}`.
- **A catch-all fallback around the lock**: renews twice (Measured).
- **A 2 s wait** (the wait question's other option): a tab loaded at most about 2 s late in every
  measured case (about 4 s in the worst order, by decision 6's sum), but with
  answers of 300 ms and 1 s sharing gave up and the tabs were refused as today (1 of 10 and 1 of 3
  worked, against 10 of 10 and 3 of 3 at 10 s).
- **A 5 s wait** (the third option): a middle point, not measured; the owner did not choose it.
- **A time bound on the fetch**: changes today's behaviour on a slow network; only the other tabs'
  wait is bounded. A Web Lock's signal stops the wait only, not acquired work.
- **Record the wider window and open a board row for the guard** ((h)'s other option, the session's
  recommendation): the owner chose to build the guard here.
- **A shorter wait instead of the guard** ((h)'s third option): it narrows only W105's window; the
  older case (a slow `app.js`) stays, and sharing gives up more often (The wait length).
- **Compare the displayed email**: `/v1/session` names the account id, not the email, and a
  signed-out page shows no email, so anonymous and unknown would look the same.

## Known limits

- **An unknown side is not checked.** The guard (decision 8) refuses only when the drawn identity
  and the answer's are both known. When the server could not tell (`""`: no store, or a failed
  read), for the page or for an answer, the token is kept as before, so the account shown and the
  identity the tab acts as can still differ: for example a page drawn signed out because its lookup
  failed, answered as Y. Older than this change (Codex's plan review, finding 7).
- **Every open workspace tab receives each posted token**, a refused tab's included; only a tab of
  the same identity takes it (decision 4). That is how the channel works, not new with the guard.
- **After the site's stored data is cleared**, a renewal's message carries a new `gen`, so the
  other open tabs refuse it (decision 5) and are refused once, as today, until they reload.
- **A cached anonymous page.** An anonymous `/ui` is not `no-store`, so a copy from the browser's
  cache can boot after a sign-in in another tab; its answer then names the account, and the guard
  refuses it (unit-tested as drawn anonymous, answered Y). The cached boot itself, and whether
  "Refresh session" then gets a fresh page, were not tested (UNVERIFIED).
- **Two anonymous sessions look the same** (case 3, the owner's choice in CHG-089): a tab whose anonymous session ended
  takes the token of the browser's new anonymous session (`e2e/tests/signed-in/tabs-share-token.spec.ts`, E6).
- **A tab that misses the message is refused as today** (case 4): a page restored from the
  back/forward cache (not testable here), a tab closed right after it renewed, a click already sent.
- **A tab without the lock or the counter keeps today's behaviour**, and so can a tab whose own
  token is older than a lockless renewal's when a locked message reaches it: stale, as today.
- **A tab can boot later than today.** It waits for its turn behind another tab's renewal: one
  stalled answer took a second tab's boot from 71 ms to 10,073 ms. With many tabs opening together
  on a slow network the waits add up, and past 10 s the late tabs renew without sharing, so the
  result can be today's refusals, only later (5 tabs at 3 s: 1 of 5 works, as today, and the
  slowest boots at 13,173 ms instead of 3,201 ms). By the code, a tab that gets the lock just before
  10 s and then waits the counter's 10 s starts its fetch about 20 s late; that order was not
  measured. The owner chose to keep 10 s after the question showed the stalled tab, the 10 tabs at
  300 ms and the 3 tabs at 1 s (CHG-089 (g)); the 5-tab row and the 20 s order were not in it.
- **Hidden background tabs**: delivery to a hidden tab was not measured (headless shows every page
  as visible); a frozen Chromium tab kept 2 of 2 messages in the failure-modes probe.

## Consequences

- `app.js`: `sharedTokenIdentity`, `acceptSharedToken`, `takeTokenNumber`, `renewSessionToken`, the
  channel and its handler; `initSession` renews through `renewSessionToken`. Of the templates,
  only `workspace.html` loads `app.js`, so the capped, ops and invite pages never join the channel.
- `tests/unit/test_late_run_question_rules.py` lifts the new functions with `initSession`, and names
  `navigator.locks` and `indexedDB` as undefined, so its bootstraps stay one plain fetch.
- The navigation lane's floor rises from 62 to 72 and the signed-in History lane's from 54 to 57,
  then to 63 with the guard's `tabs-drawn-identity.spec.ts`, and to 64 with review round 3's
  page drawn unknown in `delete-recent-sign-in.spec.ts`.
- The guard: `main.py` draws `/ui` from one account lookup, plus the `is_anonymous` read for a page
  with no account when there is a store (`_account_controls_for`, `_drawn_identity`)
  and `workspace.html` has the `drawn-identity` island; `app.js` adds `readDrawnIdentity`,
  `keepRenewedToken` and `drawnMismatch`.
- ADR-0175's save under the bootstrap's account is superseded for a drawn known identity (decision
  8): `e2e/tests/signed-in/delete-recent-sign-in.spec.ts`, "a page drawn anonymous whose bootstrap
  names another account is refused and saves nothing", replaces "the anonymous card saves under the
  account the bootstrap names, not the markup". The cost: in that rare mismatch, a question typed
  in the refused tab is not kept across the reload (the page never reaches the late-run save;
  whether a browser refills the box on its own was not checked).
- The site's IndexedDB holds one database, `quorum-session-token`, with one record `{gen, seq}`.
