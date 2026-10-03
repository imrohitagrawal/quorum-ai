# W33 slice D — History shows the current list without a reload: failure modes before the code

Written 2026-10-03 before the change (AGENTS.md rule 16e: signed-in data and privacy).
Slice D of board row W33 fixes bug 8a. The owner reported (M07 point 8: *"The history is
shown when the user signs out and then signs in"*) that History appeared only after
signing out and back in; the session's probe traced it to the panel being built on the
server once, when `/ui` loads, so it says "No questions yet" right after a question is
asked. Root cause: `docs/analysis/2026-09-29/owner-bugs-root-causes.md`, Item
8a. Opening a row (8b), the 20-conversation keep and "Continue this conversation" are
board row W36 (CHG-026 i), not this slice. Design: ADR-0142.

Measured on `290d8c5` by a read-only design reviewer (a real sign-in through the loopback
Google stub, real estimate and create in simulation, $0; its probes were not kept in the
repository):

- The History row is written when a run ends, never at create (`record_finished_run` is
  called only from `_persist_terminal_run`).
- The page can see "completed" before the row exists: with 0.5 s added inside
  `_result_response` (standing in for the judge), the first terminal poll answered at
  2.8 ms and the row was written at 511.6 ms.
- The cancel route does not write the row; it is written when the worker thread exits
  (903.1 ms with a pipeline stub sleeping 1 s).
- The History button sits in the top bar, which is hidden on the landing, result,
  live-run and transcript views, so the panel is opened from the composer or the cost
  confirmation, after a run.

| # | Failure mode | Consequence | Design answer |
|---|---|---|---|
| 1 | The route reads the account from a parameter or header. | Any account's questions can be read. | The account comes only from the cookie session; the route takes no parameters. |
| 2 | The legacy `X-Account-Id` path (off in production, allowed elsewhere when enabled) reaches the route. | In development or CI, a header naming an account id reads its history. | A legacy session is refused with 403, as account deletion does. |
| 3 | An anonymous session asks. | It has no rows, but would get "No questions yet" while not signed in. | 403 `NOT_SIGNED_IN` when the session has no account; 401 with no session. |
| 4 | A sign-in-only session (ADR-0139) asks. | A session that should do nothing reads something. | The same refusal: its random id has no account row. |
| 5 | The person signed out in another tab. | This tab keeps showing rows; a refresh gets 401 or 403. | On 401 or 403 the rows are removed and one line says to reload; the page never reloads itself and never calls `/v1/session` (which would mint a counted anonymous session). |
| 6 | Another tab signed in as a different account. | One account's email over another's questions. | The answer carries the account's email; if it differs from the one on the page, no rows and the reload line. |
| 7 | The account was deleted (ADR-0136), or "sign out everywhere" ran (ADR-0137), on another device. | Rows served after the account is gone. | Already refused: those sessions answer 401, and deletion removes the rows. |
| 8 | A refresh on a timer keeps the session alive. | Idle expiry (ADR-0138) never fires. | The refresh runs only when the person opens the panel. |
| 9 | The history store is unavailable. | "No questions yet" would be untrue (ADR-0135 says so instead). | A failed history read: the same server builder returns the "unavailable" line. A sessions store that cannot say who is signed in: 503 `HISTORY_UNAVAILABLE`, and the page keeps its rows and says it could not refresh (found by review round 1: it answered 403 and the page said the sign-in had changed). |
| 10 | The request fails on the network. | The list is wiped for no reason. | The rows stay; a line says the history could not be refreshed. |
| 11 | Answers arrive out of order (open, close, open). | An older list replaces a newer one. | Each refresh is numbered; a stale answer is ignored. |
| 12 | The panel opens in the window before the row is written (measured above). | Bug 8a again, in a narrower window. | The cancel route writes the row too (a second write replaces it, keyed by run id); and when this tab's latest finished question is missing from the answer, the panel asks once more after about 2 seconds. |
| 13 | The whole panel is replaced. | "Sign out everywhere" and the three-step delete lose their listeners and their step. | Only the list (or its empty or unavailable line) is replaced. |
| 14 | Two renderers drift (server on load, browser on refresh). | Different markup for the same rows; existing ids lost. | One server builder for both; a test pins the page's list and the route's list byte-identical for the same rows. |
| 15 | The answer is cached. | The next person at a shared computer, or a proxy, sees the questions. | `Cache-Control: no-store` on every answer the route gives (200, 401, 403, 503); the framework's 405 and 307 carry no data. |
| 16 | The route draws on the 30-a-minute account limiter that estimate, create, warnings and cancel share. | Opening History blocks running a question. | The route does not draw on it. |
| 17 | Question text reaches the page as HTML. | Script injection. | The server escapes, as today; the browser only parses server markup. |
| 18 | The anonymous page changes. | Breaks ADR-0135 decision 5 (byte-identical). | No new markup; the browser code runs only when the History panel exists. |
| 19 | The route is hidden from the OpenAPI contract (`include_in_schema=False`, as other account routes are), so the Schemathesis gate never calls it. | Its 200, 401 and 403 shapes could drift unseen. | Its own integration tests pin each status, code and header. |
| 20 | Scope creeps into W36. | Mixed concerns. | Rows stay text only; no run id in the answer. |

## Testing

No e2e lane can sign in today. The design reviewer showed that a test-only launcher can
start the real app with the loopback Google token stub set in-process (the token
endpoint is a module constant read at call time) and that a browser test can catch the
Google consent page and fulfil a redirect to the local callback (measured with Python
Playwright 1.60; the Node lane later passed 9 of 9 with the same method). The launcher lives
under `e2e/` and never ships (the Dockerfile copies `src`, `pyproject.toml` and `uv.lock`, nothing under `e2e/`).

**Rejected, critical risk:** letting an environment variable set the Google token
endpoint. The ID token's signature is not checked — trust rests on TLS to Google — so
whoever sets the endpoint chooses the account; and the runtime defaults to local, so a
deployment that forgot the setting would accept the override.

What this list cannot see: how long the production gap between "completed" and the
History write is with the judge on (a local simulation with the judge stub delayed to a
production latency would settle it).
