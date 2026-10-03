# ADR-0142: The History panel asks the server for its list each time it opens

## Status

Accepted — 2026-10-03, board row W33 (slice D). The product owner reported that
History showed their questions only after signing out and back in, and that its
rows could not be clicked (M07 point 8: *"The history is shown when the user
signs out and then signs in"*). The session's probe found why: the panel says
"No questions yet" until the page reloads (root cause in
`docs/analysis/2026-09-29/owner-bugs-root-causes.md`, Item 8a). Clicking a row
is W36. This amends
ADR-0135 decision 4 ("There is no separate endpoint") and its rejected
alternative ("A JSON history endpoint: nothing needs it yet"): bug 8a is the
need. The route's shape is the session's design. Opening a row, the longer keep
and "Continue this conversation" stay with board row W36 (CHG-026 i).

## Context

ADR-0135 renders the signed-in History panel on the server when `/ui` loads,
and nothing refreshes it, so the panel says "No questions yet" until a reload.
The row is written when a run ends, and can be written after the page has seen
the run finish (a design-review probe: written at 511.6 ms against a 2.8 ms
poll, with 0.5 s added to stand in for the judge; the production gap is not
measured); a cancelled run's row was written only when its worker exited. The failure
modes were listed before the code:
`docs/analysis/2026-10-03-w33d-history-refresh-failure-modes.md`.

## Decision

1. **`GET /v1/account/history`**, registered with `app.add_api_route` (no
   decorator; the decorated-function cap is full) and hidden from the OpenAPI
   schema like the other account routes. It answers `{"html": …, "email": …}`:
   the same list markup the page renders, from one server builder split out of
   today's `_history_html`, and the account's email.
2. **Only a signed-in cookie session may read it.** No session → 401; an
   anonymous, sign-in-only (ADR-0139) or legacy-header session → 403
   `NOT_SIGNED_IN`. The account comes only from the session. Every answer the
   route itself gives (200, 401, 403, 503) is `Cache-Control: no-store`; the
   framework's own 405 and 307 answers carry no data. It does not draw on the
   per-account request limiter that estimate, create, warnings and cancel share. Like
   every authenticated request, it resets the idle clock (ADR-0138) — once per
   opening, plus at most one re-ask.
2a. **When the sessions store cannot say who is signed in**, the route answers
   503 `HISTORY_UNAVAILABLE`, not 403, and the page keeps its rows and says the
   history could not be refreshed — never "your sign-in changed".
3. **The panel refreshes each time it is opened**, never on a timer (a timer
   would keep the session alive past ADR-0138's idle expiry). Only the list, or
   its empty or unavailable line, is replaced; the account controls in the
   panel are left alone. A stale answer is ignored.
4. **The narrow window is covered twice.** The cancel route writes the History
   row as well (keyed by run id, so a later write replaces it); and when this
   tab's latest finished question is missing from the answer, the panel asks
   once more after about 2 seconds.
5. **When the answer cannot be trusted, the page says so.** On 401 or 403 the
   rows are removed and one line asks the person to reload (the sign-in changed
   in another tab, window or device); if the email in the answer differs from
   the page's, the same. On a network error the rows stay
   and a line says the history could not be refreshed. The page never reloads
   itself and never calls `/v1/session`.

## Rejected alternatives

- **Return the rows as JSON and draw them in the browser.** Two renderers that
  drift (dates, status words, model counts, the verdict, the cost's trailing
  zeros); W36 can add its button to the server markup.
- **Add the question just asked in the browser, with no route.** The browser
  cannot know what the server kept (the write is best effort; a deleted
  account's run is not stored; other tabs and devices; the 30-day rule), so the
  page would claim a question is kept when it may not be.
- **Fetch `/ui` again and copy its list.** `/ui` mints a new anonymous session
  when the signed-in one has expired, which counts against the network's daily
  allowance and swaps the cookie — the class of defect behind #511.
- **Refresh on a timer.** Defeats idle expiry.
- **Let an environment variable set the Google token endpoint so a browser test
  can sign in.** The ID token's signature is not checked, so whoever sets the
  endpoint chooses the account; a test-only launcher under `e2e/` sets it
  in-process instead and never ships.

## Consequences

- One new route, hidden from the OpenAPI schema, so its own tests carry its
  contract. No server setting, database schema or stored datum changes (the
  page gains one timing constant, the 2-second re-ask);
  `docs/48` is unchanged (same rows, same keep).
- `tests/unit/test_history_markup.py` moves from pinning `_history_html` whole
  to pinning the shared builder, with a test that the page's list and the
  route's list are byte-identical.
- A signed-in browser lane exists for the first time (a test-only launcher with
  the loopback Google stub); the owner's journey through History is tested in a
  real browser.
- Known limit: the panel can only be opened where the top bar shows (the
  composer and the cost confirmation).
