# ADR-0139: A network that has used its anonymous sessions gets a sign-in-only session, never a dead end

## Status

Accepted — 2026-09-30, board row W34. The product owner decided the rule on
2026-09-29 (CHG-026 a; their words, M04: *"When a user is not signed in and he
is trying to access the application, in that case, the 2-a-day limit should be
applicable"*; M05: *"Agree with suggestion on both parts"* to the session's
proposal that the limit never stops sign-in and signed-in users are limited per
account). The shape below — a sign-in-only session held in memory — is the
session's design. Three points the plan raised are taken as assumptions, not
decisions, and are listed under Consequences.

## Context

The per-network daily cap (`SESSION_MINT_CAP_PER_IP = 2`, ADR-0073) counts each
NEW anonymous session. Sign-in rotates a session without counting (ADR-0130);
sign-out clears the cookie (ADR-0130); an idle expiry ends the session
(ADR-0138); "sign out everywhere" ends every session of the account (ADR-0137).
After any of those, the next page load has no cookie and mints a new anonymous
session, which counts. The third in a day rendered the capped page, which had
no sign-in control — and the sign-in start needs a cookie session — so the
person could not sign in at all. The owner hit it on 2026-09-30 after two
sign-ins and a sign-out (M23). ADR-0138 had recorded the expiry case as decided by the owner (CHG-026 a) and
not yet built.

The failure modes were listed before the code:
`docs/analysis/2026-09-30-w34-session-cap-and-sign-in-failure-modes.md`.

## Decision

1. When the daily cap refuses a mint on `/ui` and sign-in is possible on this
   request (`sign_in_enabled()` and `on_sign_in_host(request)`), the server
   mints a **sign-in-only session**: a real session id and CSRF token, bound
   to a fresh random account id, flagged `sign_in_only`. It is **not recorded
   as a mint**. A NEW one is minted only when the per-address per-minute
   session limiter (the one `/v1/session` draws on, 10 a minute) allows it;
   a browser presenting a live sign-in-only cookie reuses it and draws
   nothing; when the limiter refuses, the page is rendered with no session,
   no cookie and no control. Review round 1 measured the unbounded version:
   3,000 capped page loads from one address held 3,000 sessions in memory.
2. The flag lives **in memory only**: `SessionRepository._persist` skips such
   a session, so no schema changes, no migration runs, and a restored session
   can never carry the flag. A restart loses it; the cost is one retry of the
   capped page (failure mode 17).
3. A sign-in-only session may start and complete Google sign-in (the callback
   rotates it away exactly as for any session) and may sign out. It may do
   nothing else: `auth.refuse_sign_in_only` answers 403 `SIGN_IN_REQUIRED`
   from `spend_key_for` (the choke point the estimate and the run creation
   pass through), from the warnings route (it records a durable row) and from
   run cancel; read-only routes (idle status, keep-active, model defaults,
   the active-run query) still answer it;
   `/ui` renders the capped page for it, never the workspace; `/v1/session`
   answers it with the same 429 `SESSION_MINT_CAP_EXCEEDED` as a cookie-less
   request, so the page script and the JSON contract are unchanged.
4. A sign-in-only cookie presented to `/ui` first tries a counted mint, so a
   slot that has aged out of the window is used and the visitor gets the full
   product back.
5. The capped page keeps its 429 status and `Retry-After` header (the anonymous
   allowance IS refused), adds `Cache-Control: no-store` (it now carries a
   token), names the limit with the digit of the effective cap, says that
   signing in is not limited by it, and offers a "Sign in with Google" button
   (a `<button>` with a short inline script; the content-security policy
   forbids forms). The invite-capped page gets the same block.
6. When sign-in is not possible on the request, or the minute limiter
   refuses: no sign-in-only session, no cookie, no control, and no sentence
   about signing in (that sentence is part of the control's block). The digit
   and the wait are the same either way; the page is not byte-identical to
   the one before this change.

## Rejected alternatives

- **Sign-out rotates to a fresh anonymous session, uncounted.** Fixes the
  owner's exact journey in the fewest lines, but every sign-out then yields an
  uncounted session that can spend: a sign-in/sign-out loop mints a fresh daily
  envelope each cycle, bounded only by the sign-in start limiter. That is what
  ADR-0130 rejected. It also does nothing for idle expiry, for "sign out
  everywhere" on another device, or for a colleague arriving on a used-up
  network.
- **Count signed-in sessions per account and remember the account on the
  address** so the post-sign-out mint is not counted. Needs the account id in
  the mint row (an address-to-account link, a new privacy datum), a change to
  a money table, and still dead-ends a new visitor on a used-up network.
- **Persist the flag** with a guarded migration. Adds a write path that must
  degrade on a read-only volume, for a session whose loss costs one retry.
- **A new route for the capped page's sign-in.** No decorated route is free
  under the cap `tests/unit/test_mutation_test_set_integrity.py` enforces, and
  the existing start route already works with any cookie session.
- **Answer 200 from `/v1/session` with `sign_in_only: true`.** The page script
  would need a third state; today it needs none.
- **Count the sign-in-only session as a mint.** It cannot spend, and counting
  it would refuse the very case being fixed.

## Consequences

- No new setting, no constant moves, no schema change, no new route, no change
  to `app.js`, the golden fixtures or the visual baselines. `docs/48` is
  unchanged: nothing new is stored.
- Assumptions taken by the session (the owner may overturn any of them):
  (i) "limited per account only" means today's per-account spend limits; no
  per-account count of sessions or sign-ins is added; (ii) after a sign-out
  the next load still mints a counted anonymous session while the allowance
  lasts (today's behaviour); (iii) the capped page names the session limit but
  prints no money figure.
- The remaining anonymous allowance is not shown before the cap is hit; that
  is bug 4's own pull request (W33).
- The lockout bullets in ADR-0137 and ADR-0138 point here.
