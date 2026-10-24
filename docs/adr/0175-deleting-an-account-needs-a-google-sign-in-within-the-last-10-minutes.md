# ADR-0175: Deleting an account needs a Google sign-in within the last 10 minutes

## Status

Accepted — 2026-10-20, board row W87, the second of its three pull requests (W87-2). W87-1
(ADR-0174) built the maximum session age; W87-3 builds the operator command that ends sessions.
W87 stays open until W87-3 lands. The owner's decisions it builds on are CHG-056 (d), CHG-063 (e)
and (f)(1), CHG-066 (c) and CHG-073 (a) to (e).

The product owner chose: a Google sign-in within the last 10 minutes before an account is deleted
(CHG-056 (d)); the refusal's words, which include "If you are still signed in to Google it takes
one click.", and its "Sign in again" button, after which the visitor comes back to the account
panel and presses Delete again (CHG-063 (f)(1)); that another account coming back from that
sign-in is an ordinary sign-in as that account, with a line saying nothing was deleted
(CHG-066 (c)), in the words that match the button (CHG-073 (d)); a record that sign-in is single-factor plus one line near "Sign in" (CHG-063 (e)),
placed only near "Sign in" and on the capped sign-in page (CHG-073 (e)); keeping the signed-in
account's id beside a late-run saved question, with a notice when another account comes back
(CHG-073 (a)); the no-sign-in text for a signed-in visitor on a page with no sign-in (CHG-073 (b));
and keeping the anonymous visitor's late-run question across sign-in too (CHG-073 (c)).
**Everything else below is the session's design**, and the choices the owner was not asked about
are marked "(the session's choice)".

The failure modes were listed before any code (W87's private list of 2026-10-18, sections 2 and 5),
and the ones this pull request closes or records are published with it in
`docs/analysis/2026-10-20-w87-2-recent-sign-in-failure-modes.md`. Codex reviewed the plan four
times before any code (ADR-0168, decision 7); its reviews are kept outside the repository and none
has a committed record. Its findings and what was done with each are summarised under Decision and
Known limits. Codex reviewed the branch's code twice. Round 1 found that a refused recovery wrote
the deleted account's row back, and round 2 that a deletion landing between the new check and the
row step still could; both are fixed (decision 5). One finding is recorded (Known limits, "Check to
issue").

## Context

Before W87-2, deleting an account asked for the typed email and the anti-forgery token, and the
same cookie could read both, so a stolen signed-in cookie could delete the account
(`docs/analysis/2026-10-17-w82-security-baseline.md`, section 3; ASVS V7.6.1).

Facts the design rests on, read on `main` at `0f06765` unless marked:
- Every Google sign-in makes a new session: `issue_signed_in_session` revokes the old id and
  creates one with a new `created_at` (ADR-0174, decision 2). So a session's own start is the
  moment its Google sign-in finished, and `SessionContext.session_created_at` carries it.
- `accounts.last_sign_in_at` is per account and stamped by a sign-in from any browser.
- The callback refused an ended session before it took the pending sign-in, so the pending entry
  stayed in memory (measured by the planner: one entry left after the refusal).
- `/v1/session` sent `account_id` for a signed-in account and nothing otherwise, so a failed account
  read looked the same as an anonymous session (Codex, re-check 2).
- The decorated-function cap of `tests/unit/test_mutation_test_set_integrity.py` was full, 55 of
  55 (measured by the planner).

## Measured

| What | How | Result |
|---|---|---|
| The new tests fail without the fix | the eight test files of the test designer's commit `74979f1`, run before any source change | `62 failed, 194 passed, 1 warning in 44.25s` (the designer's own run: `62 failed, 194 passed, 1 warning in 44.21s`) |
| The new tests with the fix | the same eight files on the build | `256 passed, 1 warning in 45.11s` |
| The suites beside them | `test_google_sign_in.py`, `test_account_deletion.py`, `test_account_history_route.py`, `test_session_safety.py`, `test_session_cap_sign_in.py`, `test_session_cap_page.py`, `test_durable_sessions.py`, `test_google_signin_units.py`, `test_account_delete_message.py`, `test_capped_page_sign_in_block.py`, `test_session_max_age.py`, with the eight above, on the code commit | `1 failed, 522 passed` before `docs/41` gained SC-103 (the one failure was that check) |
| `make quality` | the builder's run on the build | `2 failed, 7681 passed, 78 skipped` in 12 min 36 s: two pins this change moves (`test_browser_ui_advanced_contract.py` lists the new step's two ids as sign-in-only hooks; `test_idle_reminder_page.py` stubs `_history_html` with its new keywords). Moved, they give `24 passed`; the moved hooks pin goes red when the button's id is renamed in `main.py` (mutation, restored from a copy). The run on the head after that and a wording fix to this file: `7683 passed, 78 skipped` in 12 min 31 s, exit 0 |
| `make quality` on head `52e7807` (review round 3's code) | the fixer's run | `7743 passed, 37 skipped` in 13 min 1 s, total coverage 97.46%, exit 0 |
| The OpenAPI document does not move | `make openapi-check` | `openapi contract validation passed (openapi.yaml == app.openapi())`, exit 0 |

## Decision

1. **The proof is the session's own start.** `delete_signed_in_account` refuses with 403
   `RECENT_SIGN_IN_REQUIRED` and CHG-063 (f)(1)'s sentence when `auth._now() -
   session.session_created_at` is more than `RECENT_SIGN_IN_FOR_DELETION`, 10 minutes. Strict, as
   ADR-0174's limits are: allowed at exactly 600 seconds, refused 1 microsecond later. It comes
   straight after the `NOT_SIGNED_IN` refusal and before the email comparison, so a stale session
   is told what would help. It never reads `accounts.last_sign_in_at` (FM-11).
2. **What that proves, and what it does not.** A session younger than 10 minutes came from a
   callback that held a fresh Google code for a `state` and a PKCE verifier this server made at
   most 10 minutes before, for this browser's session. That needs the browser that holds the
   victim's Google session; a stolen Quorum cookie alone cannot get one. It does not prove that
   Google asked for a password or a second factor: Google decides that, and the app cannot see it.
3. **Google is asked for nothing new.** No `max_age` and no `prompt` (FM-18). UNVERIFIED (never
   tried against Google): with `max_age=600`, Google would ask for the password whenever its own
   sign-in is older than 10 minutes, which would contradict the owner-approved words "If you are
   still signed in to Google it takes one click." (CHG-063 (f)(1)). Google's discovery document,
   fetched 2026-10-20 (`https://accounts.google.com/.well-known/openid-configuration`), lists
   `claims_supported` as aud, email, email_verified, exp, family_name, given_name, iat, iss, name,
   picture and sub, with no `auth_time`. The document cannot settle how Google treats `max_age`:
   OpenID Connect Discovery 1.0 defines no metadata for it. `auth_time` is not read. The Quorum session is independent of Google's: signing out of Google leaves Quorum
   signed in, and signing out of Quorum calls nothing at Google. Google is asked again at each
   sign-in, after the 12 hours (ADR-0174), and before a deletion more than 10 minutes after the
   sign-in that made the session; no ending of a session is passed between the two.
4. **A separate start route** (the session's choice). `POST /v1/auth/google/start-for-deletion`,
   hidden from the schema like `/v1/account/delete`, with no body. One inner function holds the
   plain start's checks in the plain start's order (on, cookie session and anti-forgery token, the
   redirect URI's host), then, for a deletion only, a signed-in account (else 403 `NOT_SIGNED_IN`,
   "Sign in to delete your account."), then the same per-address limiter. The pending entry carries
   `purpose` (`"sign_in"` or `"delete_account"`) and, for a deletion, the account that started it.
   It is registered with `add_api_route`, so the decorated count stays 55.
5. **The callback, in order.** No cookie fails. The pending entry is taken first, on every attempt,
   so a `state` is good for one attempt even when the session has ended. A session that no longer
   resolves goes on only when it ended by the signed-in 12 hours (decision 7). Then the state,
   the code and the Google exchange. Then the account row: on the live path as before; for a
   recovered session, `SessionRepository.upsert_if_recoverable` checks the recovery condition again
   and writes the row while holding the session repository's lock, the lock a deletion takes
   (`begin_deletion`) before it removes any row. So a deletion either comes first, and the sign-in
   is refused with nothing written, or waits until the row is written and then removes it (review
   rounds 1 and 2: Codex measured a deleted account's row written back, 0 rows then 1, both times;
   `tests/integration/test_sign_in_recovery_no_account_write.py`,
   `tests/integration/test_sign_in_recovery_lock.py`). With the lock the callback can still
   redirect to `/ui`; the deletion that follows still leaves no account row and no session (the
   lock test asserts both). The lock holds only within one process. Production runs one
   (`Dockerfile:92`, `"--workers", "1"`); a second worker process or a second machine would reopen
   the race. For a recovered session the recovery condition is checked once more after the row;
   the new session is issued (the old id revoked, FM-12); the deleted-while-signing-in check as
   before. Taking the pending entry first is kept for every sign-in, the deletion one included, so
   the sign-in gap that board row W80 records (a cross-site link can cancel a sign-in) is not
   changed by W87-2.
6. **Four fixed return paths.** `/ui` (a plain sign-in), `/ui?sign_in=failed` (every failure, any
   purpose, a cancel included), `/ui?account=delete` (a deletion sign-in, the same account back) and
   `/ui?account=switched` (a deletion sign-in, another account back). All four are module constants
   pinned by literal; nothing from the request reaches a `Location`. A forged `?account=delete`
   only opens the visitor's own panel; a forged `?account=switched` shows the visitor their own
   email and true words.
7. **Recovery across the signed-in 12 hours only** (the session's choice). The new
   `SessionRepository.max_age_account(session_id)` names the ended session's account when its
   durable row shows it ended by the 12 hours and nothing else (every check `end_reason` already
   made: the row exists, no sign-out-everywhere cutoff on disk or in memory at or after its start,
   a lookup that worked says signed in, past 12 hours, the 12 hours before the idle end), and no
   deletion of the account is under way or done (`account_is_going`). `end_reason` now answers from
   it, so the two cannot disagree. The callback asks it before the exchange, again after the
   exchange together with the account row write under one lock (decision 5), and again after the
   account row, right before issuing, so a session revoked,
   signed out everywhere or deleted during the exchange is refused (Codex measured all three signed
   in without the last check). A change in the few statements after the last check is not seen
   (Known limits, "Check to issue"). Not
   recovered: an idle end (the start request touches the session and the shortest signed-in idle
   length, 15 minutes, outlasts the 10-minute pending entry), a sign-out, sign-out everywhere and
   deletion (the visitor or the owner chose them), and the anonymous 24 hours (Known limits).
8. **Another account coming back** (CHG-066 (c), CHG-073 (d)). It is an ordinary sign-in as that
   account: this browser's session for the first account is rotated away, the first account's other
   sessions keep working, the other account's row is created if new, and nothing is deleted. The
   panel then says, in a `role="status"` line, "You are now signed in as <email>. Nothing was
   deleted. To delete this account, press "Delete my account" again." with the session's own email,
   escaped. The other account may delete at once with its own email, because its sign-in is fresh.
9. **The page.** `#account-delete` carries `data-recent-sign-in-seconds-left`, the whole seconds left
   before the session is 10 minutes old (never below 0). "Delete my account…" shows the reminder
   while that time lasts and otherwise the step with CHG-063 (f)(1)'s sentence and one button,
   "Sign in again", which gets the focus. A 403 `RECENT_SIGN_IN_REQUIRED` from "Delete permanently"
   shows the same step, because the server is the control and the page's deadline is only for the
   visitor (FM-14, FM-52). "Sign in again" uses the start for deletion; if the start fails, the
   existing start-failure line shows below the step and the button stays enabled. Back on
   `?account=delete` or `?account=switched` the page opens the panel, moves focus to "Delete my
   account…" and removes the marker with `history.replaceState`. The same account gets no new words
   (CHG-063 (f)(1)).
10. **A cancel at Google shows the notice signed in too.** The signed-in top bar renders "Sign-in
    did not complete. Please try again." on `?sign_in=failed`, as the anonymous one did (FM-48).
11. **`/v1/session` states anonymity positively.** `account_id` when the account is found;
    `"anonymous": true` only when the store answers that the session's id is certainly in no
    accounts row (`is_anonymous(...) is True`); neither field when the read fails or there is no
    store (Codex, re-check 2). The response is described as `schema: {}`, so the OpenAPI document
    does not change.
12. **The late-run question, saved by the bootstrap's identity.** Both late-run cards' buttons
    ("Sign in again" signed in, "Sign in with Google" anonymous, CHG-073 (c)) call one save. It
    classifies the entry by what `/v1/session` said, never by the markup (Codex, finding 2):
    `{account, question}` for an account, `{anonymous: true, saved_at, question}` for
    `anonymous: true`, and nothing when the server could not tell. The page records the first
    identity its bootstrap gave; a later bootstrap (`retrySession`) that names another or an unknown
    identity marks the page load as changed, and nothing is saved on it again (Codex, re-checks 3
    and 4; the session's choice).
13. **Putting it back.** A signed-in entry goes back only for the same account; another signed-in
    account gets an empty box and, above it, "You are now signed in as <email>. Your question was not
    kept because it was typed while signed in as another account." (CHG-073 (a)). That email comes
    from `GET /v1/account/history`, which answers for the cookie's own session, never from the
    HTML; it is inserted as text; if the route fails there is no line. An anonymous entry goes back
    once for whichever session the tab now has, signed in as any account or anonymous again after a
    cancel (the session's choice), within 900 seconds of `saved_at` (the session's choice). An
    anonymous entry with no `saved_at` is not put back. The entry is removed at the first read.
    A question put back is kept in view (review rounds 1 to 3; the owner approved the third round,
    past the stop rule, in CHG-074; the design is the session's): a
    watch starts first thing in `boot()`, before any wait; the restore and every readiness paint
    after it (`confirmReadiness`, which also paints the drift banner) scroll the box with
    `block: "nearest"` when it is not fully visible, and never focus it. The sign-in failure notice
    (`#sign-in-notice`) and focus placed elsewhere (the deletion return) win. The watch ends once,
    "cancelled" at the person's first wheel, touch, pointer or key, a scroll the page did not make,
    a typed change or an error box, or "settled" after the boot's last paint; the outcome is
    written to `html[data-restore-scroll]`, which changes no pixels.
14. **Why 900 seconds** (the session's choice). `saved_at` is taken before the start request. The
    callback accepts a pending entry up to 600 seconds after it began, and checks that before the
    exchange, which can then take up to 10 seconds (`TOKEN_EXCHANGE_TIMEOUT_S`). After it come the
    account row, the redirect, the page load, `/v1/session` and the model list, and only then the
    restore. 610 seconds are bounded by the code; the page's own requests have no time limit. So
    900 is 610 plus 290 seconds of margin. It is a choice, not a proof: a slower round trip loses
    the question (an empty box); it never shows it to anyone else. Codex found that the plan's
    first figure, 600 seconds, could drop a question after a successful sign-in.
15. **The single-factor record** (CHG-063 (e)). Sign-in is Google only and, as far as the app can
    tell, single-factor: no `acr_values` is asked for and no claim about the factor is read. Google
    may ask for its own second step, but the app cannot see or require it. The mitigations are this
    ADR's 10-minute sign-in before deletion, ADR-0174's 12-hour maximum age, sign-out everywhere
    (ADR-0137) and idle expiry (ADR-0138). The page says "We sign you in with Google. Turn on 2-Step
    Verification in your Google account to protect it." beside the top bar's "Sign in with Google"
    on the anonymous page and below the capped sign-in page's button (CHG-073 (e)). The session
    reads "near Sign in" as those two buttons, not the cost card's "Sign in" nor the late-run card's
    buttons (the session's reading of CHG-063 (e) and CHG-073 (e)). With sign-in off the anonymous
    top bar is still the empty string, so the visual lane's page does not change.

## Consequences

- A signed-in visitor who wants to delete their account more than 10 minutes after signing in signs
  in again first; one click when still signed in to Google.
- Every sign-in for deletion rotates the session, so other tabs' anti-forgery tokens go stale (FM-16)
  and the 12 hours start again (FM-17, intended: it is a fresh Google sign-in).
- A visitor who presses "Sign in again" seconds before the 12 hours end now comes back signed in,
  with the question they typed (ADR-0174's known limit, fixed).
- The signed-in e2e lane's floor rises from 35 to 46: the new spec's 8 tests and 3 in
  `session-max-age.spec.ts` for the restored question box (review round 3).
- `docs/48-data-retention.md` lists the anonymous saved question; the signed-in id row is approved
  (CHG-073 (a)).

## Known limits

- **The anonymous 24 hours are not recovered.** The purge deletes an anonymous row older than 24
  hours at its next tick (every 60 seconds), so recovery would race it and work only sometimes, and
  it would need the anonymous history carried over from an ended session, a new path. The visitor
  sees "Sign-in did not complete", and the anonymous question is still put back within 900
  seconds.
- **A stale read** (Codex, re-check 1). `max_age_account` can read a row a moment before a revoke
  deletes it and still name the account.
- **Check to issue** (Codex, re-check 1 and review rounds 1 and 2). A revocation or a sign-out everywhere
  that lands between the last recovery check and `issue_signed_in_session` (a few statements, no
  network call) is not seen: the person who has just signed in with Google as that account gets a
  working new session. The result is the same as an ordinary sign-in, and recovery does not refuse
  it. The live path has no check after the exchange at all (measured by the planner: a live session revoked during a stubbed exchange still gets `303 /ui` and a new cookie;
  `tests/integration/test_sign_in_recovery.py::test_the_live_path_is_unchanged_by_a_revoke_during_the_exchange`
  pins it). The same check on the live path is advisory, not built: the live path is W7's
  (ADR-0130), and it is left for the owner's backlog.
- **Deletion during the live path's exchange** can let the account row step create a new account for
  the same Google identity (Codex). For a recovered session the locked check and write refuses it,
  or the deletion waits for the write and then removes the row (decision 5). On the live path it is
  today's behaviour, unchanged.
- **A scroll of 8 px or less that the page did not make is treated as layout noise** (review round
  3, amended 2026-10-24). The watch on a restored question cancels on such a scroll only when the
  window's `scrollY` moved more than 8 px from where the page last placed the box; a move of the
  box with the view still is the layout's, and the page places the box again (see the amendment
  below). Two scrolls with no input were measured: 2 px (review round 3, scrollY 90 to 92) and 1 px right
  after a 44 px font-swap reflow on Linux (2026-10-24); what makes either is not known. 8 px is
  chosen, not derived: above those and below the one wheel scroll measured (120 px). A script, a
  scrollbar drag or assistive
  technology can scroll with no wheel, touch, pointer or key event, so a scroll of 8 px or less
  from them does not cancel; a wheel, touch, pointer or key event cancels at any distance.
- **The anonymous question can be lost.** After 900 seconds (decision 14); when the bootstrap could
  not tell the session's kind (decision 12); and after any identity change in the page load, even
  for a draft typed after the change, until a reload (the cost is a retyped question, never a
  disclosure).
- **The classification is as fresh as this tab's bootstrap.** Another tab signing in after the
  bootstrap and before the save leaves an anonymous label on a question this same browser typed.
- **Typing for more than 10 minutes after the new sign-in** is refused again (FM-15); the visitor
  signs in again.
- **A restart during the sign-in** loses the pending entry, which is in memory only (FM-20); the
  visitor sees "Sign-in did not complete".
- **The switched line is server-rendered** inside the panel the page opens at load, so a screen
  reader may not announce it as it would a live change; focus moves to "Delete my account…" beside
  it. Not measured with a screen reader.

## Rejected alternatives

- **A body `{"purpose": ...}` on the existing start route.** It needs a request model, W85's
  unknown-key rule, an OpenAPI change and a new Schemathesis surface, and it moves the plain start's
  contract and tests. The separate route needs none of them.
- **`accounts.last_sign_in_at` as the proof.** Another browser's sign-in stamps it, so an old stolen
  cookie could delete within 10 minutes of the victim signing in elsewhere (FM-11).
- **Sending `max_age` or `prompt=login`, or reading `auth_time`.** Google would ask for a password
  (UNVERIFIED for `max_age`; decision 3),
  against CHG-063 (f)(1)'s "If you are still signed in to Google it takes one click."; and that
  Google returns `auth_time` without `max_age` was not verified.
- **Refusing the other account at the new sign-in.** The owner chose an ordinary sign-in with a line
  (CHG-066 (c)).
- **A `/ui?account=delete-failed` path.** Every failure already has `/ui?sign_in=failed`, now shown on
  signed-in pages too.
- **Restoring an anonymous question for 600 seconds.** It could drop a question after a successful
  sign-in (decision 14).
- **Reading the stored identity from the markup (`#account-email`).** The HTML can be stale (another
  tab), so the save could label account B's question anonymous (Codex, finding 2).
- **Treating a missing `account_id` as anonymous.** A failed read gives no `account_id` too (Codex,
  re-check 2).

## Related

- Code: `src/product_app/account_deletion.py` (`RECENT_SIGN_IN_FOR_DELETION`,
  `recent_sign_in_seconds_left`, `delete_signed_in_account`), `src/product_app/google_signin.py`
  (`ACCOUNT_DELETE_PATH`, `ACCOUNT_SWITCHED_PATH`, `PendingSignIn`, `_start`,
  `start_google_sign_in_for_deletion`, `google_sign_in_callback`), `src/product_app/auth.py`
  (`SessionRepository.max_age_account`, `end_reason`), `src/product_app/main.py`
  (`_account_controls_html`, `_history_html`, `_account_delete_html`, `browser_session`, `/ui`),
  `src/product_app/templates/capped-sign-in.html`, `src/product_app/static/app.js`
  (`lateRunQuestionEntry`, `lateRunQuestionToRestore`, `signInAgainKeepingQuestion`,
  `restoreLateRunQuestion`, `showQuestionNotKeptNotice`, `openAccountPanelAfterReturn`,
  `recentSignInFresh`, `accountDeleteMessage`, the delete steps), `src/product_app/static/app.css`.
- Tests: `tests/integration/test_recent_sign_in_for_deletion.py`,
  `tests/integration/test_sign_in_recovery.py`, `tests/integration/test_session_max_age_routes.py`,
  `tests/unit/test_recent_sign_in_markup.py`, `tests/unit/test_late_run_question_rules.py`,
  `tests/unit/test_history_markup.py`, `tests/unit/test_risk_constant_pins.py`,
  `e2e/tests/signed-in/delete-recent-sign-in.spec.ts`, `e2e/tests/signed-in/session-max-age.spec.ts`.
- Amends ADR-0130 (the callback's return paths, recovery across the 12 hours) and ADR-0136
  (deletion's checks). ADR-0174's known limit on signing in across the end is fixed here.
  `docs/41-security-controls.md` SC-03, SC-30 and SC-103.
- CHG-056 (d), CHG-060 (the detail held back until the fix shipped), CHG-063 (e), (f)(1), CHG-066
  (c), CHG-073 (a) to (e).

## Amendment: a layout move no longer cancels the restore (2026-10-24)

**What failed.** The test X1 (`e2e/tests/signed-in/session-max-age.spec.ts`) failed 2 of 11
executions of the signed-in e2e lane in CI since #582, each time with `data-restore-scroll`
"cancelled" instead of "settled". Reproduced on Linux Chromium with DejaVu Sans as the fallback
font: when the Geist web font arrives just after the question is put back, the text above the box
shrinks and the box moves 44 px up, while the window's `scrollY` moves 1 px. The next `scroll`
event saw the box more than 8 px from where the page left it and cancelled, though nobody did
anything. A real visitor with a slow font load could see the question left out of view. On a Mac
the fallback font wraps the same lines as Geist (the heights above the box are the same), so the
font swap moves nothing there: 0 cancelled in 62 runs.

**The new rule** (`watchRestoredQuestionScroll` and `bringRestoredQuestionIntoView` in `app.js`).
The page records `window.scrollY` with the box's top each time it places the box. On a `scroll`
event, in this order:
1. the event's target is an element that holds the box: an inner panel scrolled, so cancel;
2. `window.scrollY` moved more than 8 px from the recorded value: the view moved, so cancel, even
   if the layout moved too;
3. otherwise the view did not move: if the box's top moved more than 8 px, the layout moved it,
   so the page places it again (which records the new top and `scrollY`).

A wheel, touch, pointer or key event, a typed change and an error box cancel as before. The first
rule tried (the box moved in the document, so place it again) was rejected in Codex's plan review:
it swallowed a real scroll made together with a reflow, and an inner panel's scroll.

**Measured** (a Linux Chromium container, `mcr.microsoft.com/playwright:v1.61.1-noble`, fallback
`DejaVu Sans`, the lane's settings; and the signed-in lane on a Mac):

| Case | Before (main `c40159e`) | After (this rule) |
|---|---|---|
| Linux: Geist arrives just after the restore | 28 of 28 cancelled | 30 of 30 settled, the box fully in view |
| Linux: a window scroll of 100 px with a 44 px reflow | (the first rule tried: 10 of 10 settled, the scroll swallowed) | 10 of 10 cancelled |
| Linux: a wheel of 120 px | | 10 of 10 cancelled |
| Mac: X1, X2, X3 | | 15 of 15 green |
| Mac: X4, a 44 px layout shift above the box, then a `scroll`, the view still | 10 of 10 red, "cancelled" | 10 of 10 green |
| Mac: X5, a 44 px shift with a 100 px view scroll | 10 of 10 green | 10 of 10 green (the first rule tried: 10 of 10 red) |

**UNVERIFIED.** Which fallback font the CI runner uses (`fc-match sans-serif` in a CI step would
settle it). What makes the 1 px scroll after the reflow (under 8 px, so the rule does not depend on
it). The inner-panel branch cannot be reached in today's layout: the box has no scrollable ancestor
at 390x844, so it was not measured.

**The delete test.** The other intermittent failure in the lane, "another account at the new
sign-in" in `e2e/tests/signed-in/delete-recent-sign-in.spec.ts` (1 of 11 executions in CI), was a
test defect: it swapped its Google route (`unroute`, then `route`) while the next page loaded, and
clicked "Sign in with Google" before that page had booted. It is fixed in the same pull request:
one Google route whose account can be changed, and a wait for the page's load and
`data-app-state="ready"` before each click. With a 300 ms hold of `app.js` on the page after the
deletion, the old test was red 10 of 10 and the fixed one green 10 of 10. The signed-in lane's
floor rises from 48 to 50 for X4 and X5.
