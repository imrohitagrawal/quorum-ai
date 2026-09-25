# ADR-0131: Loading the page does not replace the CSRF token

## Status

Accepted — 2026-09-25. A production fix, decided by the session. The
owner's words that raised it: *"when I click on Sign Out, it is throwing me
an error: "Sign-out did not complete. Please try again."* and *"When I run a
query, I see error: "Security check failed ... Post refresh session also
running query gives this error."*

## Context

Since C10 (commit `f49e990`, 2026-06-20) every resume of a session gave it a
new CSRF token, the value a protected request must carry. `/ui` and
`/v1/session` both resumed, so both replaced it. The page only ever learns
its token from `/v1/session`.

Read in the production logs at about 12:00 UTC on 2026-09-25, from one
browser (the log buffer has since rolled over, so the rows below are this
session's record of what it read, not something a reader can re-run):

| Time (UTC) | Request | Token after it |
|---|---|---|
| 11:55:36 | `GET /v1/auth/google/callback` 303 | new session |
| 11:55:36 | `GET /ui` 200 | A |
| 11:55:36 | `GET /v1/session` 200 | B, which the page keeps |
| 11:55:37 | `GET /ui` 200 | C |
| 11:56:23 | `POST /v1/auth/sign-out` 403 | page sent B |

Each of the four page loads in that window (11:55:16, 11:55:36, 11:56:14,
11:57:53) had a second `GET /ui` with no `/v1/session` after it, so it ran no
page code. Its sender is not identified (a browser prefetch or an extension
would look like this). On the load before sign-in it arrived before
`/v1/session` and did no harm; on the three loads after sign-in it arrived
after, so those reloads did not recover. Which one lands first is a race. A
reviewer reported a later reload (12:02) that did recover, consistent with
that; this session could not re-read it. Nothing here is specific to
sign-in: an anonymous page whose extra fetch lands late fails the same way
(`test_an_extra_page_load_leaves_the_pages_token_valid` signs no one in).

## Decision

`/ui` resumes an existing session WITHOUT a new token
(`issue_or_resume_session(..., rotate_csrf=False)`). It still mints a session
for a browser that has none, under the same per-address cap. `/v1/session`
still replaces the token on every call.

## Why this keeps the protection

The C10 reason for rotating is that a token handed out earlier stops working
once the page asks again. `/ui` never hands a token out, and the page asks
`/v1/session` straight after loading, which still rotates. So an old token
now dies at the next `/v1/session` call rather than at the next `/ui` fetch,
and a real page load makes that call straight after fetching `/ui`. The one
new survival is a token living through a `/ui` fetch that runs no page code,
which is exactly the fetch that caused the fault; the token still has to be
read from a `/v1/session` response to be used, and a cross-site page cannot
read one. A side effect: before this, any site could break a visitor's open
tab by sending the browser to `/ui` (the session cookie travels on a
top-level navigation); that no longer works.
`test_the_session_call_still_retires_the_previous_token` pins that.

## Rejected alternatives

- **Put the token in the page and stop calling `/v1/session`.** Puts the
  token in HTML that caches and extensions can read, and changes the page's
  start-up for a fault that one flag fixes.
- **Retry once on 403 by fetching a new token.** Hides every genuine CSRF
  failure behind an automatic retry.
- **Turn sign-in off.** Does not fix it: anonymous pages fail the same way.

## Consequences

- Two tabs still invalidate each other's token, because each calls
  `/v1/session`. That predates this and is unchanged; "Refresh session"
  recovers from it, since a reload now ends with the reloading tab's own
  token.
- Tests: `tests/integration/test_page_load_keeps_csrf.py` (five) and
  `test_sign_out_works_after_the_page_is_fetched_again`.
