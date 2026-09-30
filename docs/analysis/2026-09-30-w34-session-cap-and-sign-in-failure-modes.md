# W34 — the daily session cap must never stop anyone signing in: failure modes before the code

Written 2026-09-30 before the change (AGENTS.md rule 16e), from the design and test-design
lenses of that day. Decision: CHG-026 (a), the product owner on 2026-09-29 (M04, M05):
the per-network 2-a-day limit applies to anonymous use only; signed-in users are limited
per account only. The bug it fixes (owner, 2026-09-30, M23): *"I did 2 logins and then at
logout got the 'This network has reached its session limit' message."* Design: ADR-0139.

Mechanism today: `auth.issue_session` records one mint per NEW anonymous session against
`SESSION_MINT_CAP_PER_IP = 2` per rolling 24 hours per visitor address; sign-in rotates the
session without counting (ADR-0130); sign-out clears the cookie; the next `/ui` load mints
a fresh anonymous session, which counts; the third in a day renders the capped page, which
offers no sign-in, and the sign-in start itself needs a cookie session. The same happens
after an idle expiry (ADR-0138) and after "sign out everywhere" on another device (ADR-0137).

| # | Failure mode | Consequence | Design answer |
|---|---|---|---|
| 1 | Session fixation: a presented id is adopted as the sign-in-only session, or the sign-in-only id survives sign-in. | A planted cookie becomes a signed-in session. | The sign-in-only session is minted by the server (`session_repository.create`), never adopted; the callback still runs `issue_signed_in_session`, which revokes it. Test: the id before the callback resolves to nothing after it. |
| 2 | A sign-in-only session is used to run, estimate, read history or keep-active. | Free anonymous runs past the cap — the drain the cap exists for. | `SessionContext.sign_in_only`; `spend_key_for` refuses with 403 `SIGN_IN_REQUIRED` before any key is read (the choke point both money routes pass through). `/ui` never serves the workspace to it. Tests: estimate 403, create 403, zero cost rows, zero runs (cardinality). |
| 3 | Farming: sign-in then sign-out in a loop, each sign-out yielding a fresh uncounted session. | Unlimited anonymous spend envelopes (what ADR-0130 rejected). | Sign-out still clears the cookie; the next load mints a COUNTED anonymous session while the allowance lasts and a sign-in-only session (cannot spend) after. Nothing uncounted can spend. Test: four sign-in/sign-out cycles → exactly 2 mint rows; the third and fourth post-sign-out sessions refuse the estimate. |
| 4 | Sign-out during a run. | Unchanged: the run finishes and is charged (ADR-0137); the page shows 401. | Out of scope; W35 ("ask first") is the owner's separate decision. |
| 5 | Multi-tab: tab A signs out; tab B still shows the workspace. | Tab B's next call gets 401 → its reload lands on the capped page, which now offers sign-in. | Correct by construction on the server. The workspace copy for that edge state is not changed in this pull request. |
| 6 | Idle expiry, then reload on a network that has used its allowance. | Today: the capped page with no sign-in. | Same path as sign-out: `/ui` cannot resume → a counted mint if a slot is free, else a sign-in-only session with a working sign-in control. Test: expire a signed-in session by the clock, reload with the cap spent, sign in again. |
| 7 | Invite link (W32) and allow-list (W31). | Allow-listed: never capped, no change. Invite: the link's own cap can also dead-end a visitor. | The same fallback from either key; `invite-capped.html` gets the same sign-in block. Test: an invite-capped browser can sign in. |
| 8 | Store unavailable. | Feedback store down: the cap is skipped and everyone gets a full session (fail open, ADR-0004, ADR-0073, unchanged). Session store down: the sign-in-only session lives in memory anyway; sign-in fails at the callback as today. | No new posture. |
| 9 | The per-minute session limiter (10 a minute per address on `/v1/session`). | Unchanged; the capped page's sign-in control never calls `/v1/session`. | The sign-in start has its own limiter (5, then 1 a minute); the page shows that refusal's message. |
| 10 | The 429 page now sets a cookie and carries a CSRF token. | A cached copy would hand the token to the next reader. | Keep 429 and `Retry-After` (the anonymous allowance IS refused); add `Cache-Control: no-store`. Test pins status, both headers. |
| 11 | The page script boots `/v1/session` with a sign-in-only cookie. | If it answered 200, the workspace would offer Run and get 403s. | `/v1/session` answers 429 `SESSION_MINT_CAP_EXCEEDED` for a sign-in-only session exactly as for no session; the JSON contract and `app.js` are untouched. |
| 12 | Mint cardinality (rule 6b): a count that happens to work. | A build that counts sign-in, counts the sign-in-only session, or double-counts, passes an outcome-only test. | The owner's journey records exactly 2 rows; each sign-in 0; each sign-in-only session 0. A sign-in-only cookie presented to `/ui` first tries a counted mint, so a freed slot is used. Tests assert row counts at every step. |
| 13 | "Limited per account only" for signed-in users. | Nothing new is needed for the sentence to hold. | Today per account: the daily spend envelope on the spend key (ADR-0136), the per-run hard cap, one run at a time. No per-account session count exists and none is added (assumption, stated in ADR-0139). |
| 14 | Production runs simulated (live execution off). | Simulated runs still charge the envelope (ADR-0074). | No special path: a sign-in-only session is refused at the estimate in either mode. |
| 15 | Legacy `X-Account-Id` header (production-disabled). | Creates no server session; cannot sign in (403). | `sign_in_only` is False on the legacy branch; unchanged. |
| 16 | Account deletion mid-flow. | Deletion clears the cookie → the next load is a counted mint or sign-in-only; a callback for an account deleted meanwhile is already refused. | The sign-in-only session's random id is in no accounts row. Unchanged. |
| 17 | A restart between the capped page and the callback. | The in-memory sign-in-only session is lost. | Callback → no session → `/ui?sign_in=failed` → the capped page again, with the control. One retry, the same class as ADR-0130's lost pending state. |
| 18 | Sign-in disabled, or the wrong host. | No sign-in can finish there. | The page is the same as today's (the control renders only when `sign_in_enabled()` and `on_sign_in_host(request)`); no sign-in-only session is minted. The existing capped-page tests stay green. |
| 19 | The message names the wrong limit (owner bugs 3 and 4). | "Session limit" with no number, no time, no way forward. | The page and the JSON name the limit hit (the digit from the effective cap), the wait, and say that signing in is not limited by it. No money figure on the page. |

What this list cannot see: whether the owner wants the remaining anonymous allowance shown
before the cap is hit (bug 4's second half); that stays with bug 3/4's own pull request.
