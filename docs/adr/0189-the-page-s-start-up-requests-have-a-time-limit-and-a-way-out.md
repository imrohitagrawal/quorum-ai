# ADR-0189: The page's start-up requests have a time limit and a way out

## Status

Accepted — 2026-11-05, board row W140. The product owner chose to build this ahead of the dependency updates (CHG-111). The limits, the retry rule and everything else below about how it is met are the session's design; Codex reviewed the plan, and then its revision, before any code.

**Supersedes**, without editing it (`docs/README.md`: "superseded never edited"): ADR-0178, decision 6, the clauses "The fetch inside the lock is deliberately NOT bounded" and "nothing renews twice", and its rejected alternative "A time bound on the fetch". The rest of ADR-0178 stands, including decision 7, "No retry anywhere" (case 2, the owner's choice in CHG-089): a write that left with an old token is still refused once and never repeated. What this adds is a repeat of the start-up's own session request, which that decision does not cover.

It also resolves the consequence ADR-0188 recorded: "a time limit on the start-up requests is separate work".

## Context

Start-up is two requests: `GET /v1/session` (the anti-forgery token) and `GET /v1/models/defaults` (the model slots). ADR-0188 made a click wait for them. Neither has a time limit, so a request that gets no answer leaves a button spinning with no message and no way out.

### A premise that did not hold

The proposal the owner chose described both requests as read-only and safe to repeat. That is near enough for the model list, which records a throttled last-use touch (`auth.py`, `require_session`) and neither opens a session nor changes a token. It is not true of `GET /v1/session`:

- every call with a live cookie replaces the anti-forgery token, retiring the one other tabs hold unless the answer reaches this tab and is posted to them;
- a call with no usable cookie opens a session, counted against the network's limit of 2 per 24 hours (`SESSION_MINT_CAP_PER_IP`). If the answer is lost before its headers arrive, its cookie is lost too, so a repeat counts again. A normal page holds the cookie `/ui` set and is not at risk; a page from the browser's cache, an expired session or blocked cookies are;
- each call that reaches the server, for a visitor not on the allow-list, spends the per-network limiter: 10 a minute (`CAPACITY` in `query_runs.py`; only a local test override raises it).

So the retry is kept, and limited to what these facts allow: once, and only when no HTTP answer came.

## Decision

1. Each start-up request is given up at 15 s, headers and body together, and tried again once, about 1 s later, only if it got **no HTTP answer** (the limit, or a connection that failed). Any HTTP answer ends the step exactly as before: 401 `SESSION_UNCHECKED`, 429, 403 and 500 are never repeated, so the session cards and the daily limit behave as they did.
2. The session retry runs inside `fetchSession`, so it stays inside the Web Lock and under one token number, and a successful retry reaches other tabs through the existing post.
3. "Still connecting…" appears 10 s after start-up begins, fixed to the viewport, because at 390 px the Estimate button sits about 1,530 px down the page, so after pressing it the page is scrolled about 1,130 px and the pill and the card are over 900 px above the screen, and the top bar does not exist on the landing. It clears on every way out of start-up, except as decision 5 says.
4. When a step gets no answer, it fails with `START_UP_UNREACHABLE`. The card reads "Can't reach the server", with one button, "Try again". Held clicks finish, as ADR-0188 arranged.
5. That card does not take the keyboard from someone typing. `showError` always moves focus and scrolls; this card can arrive 31 s or more after load, when a person may be mid-sentence. If a text field has focus, the card appears without either, whichever path shows it (the boot, a retry, or a click that was waiting), and `role="alert"` announces it. On a phone that card is off screen, so the fixed line then reads "Can't reach the server" until the card goes or a retry starts.
6. A write is refused in the page, without being sent, when start-up got no answer and no token is held. The server could only refuse it, and on a dead connection it would hang with no limit, leaving the sign-in button disabled for good. A start-up that got an HTTP answer still sends it (ADR-0188).
7. "Try again" (`retrySession`) makes one attempt per step, of up to 30 s, so a person on a link slower than the automatic limit still has a way to succeed. If the session answered and only the model list did not, it sends no session request, so a good token is not replaced for nothing. Clicks made meanwhile wait for it, as they do at boot, and boot and a retry each settle only their own steps, so a boot that ends during a retry cannot release a click waiting for that retry. One guard inside the function stops a second retry, because `showError` rebuilds the card's buttons. If it gets no answer again, the card stays and the page does not reload: a reload on a dead connection replaces the page with the browser's own error page and loses the typed question. Other failures still reload, as before.
8. The first successful start-up on a page, at boot or by a retry, does the same work (`finishStartUp`, one function, once per page): a question kept across sign-in comes back and `data-app-state` reads `ready`. The kept question does not overwrite text already in the box. A retry on a page that has already started only stamps `ready`, so "Start a session" does not reset a live run or a result on screen.
9. The operator-worded readiness toast is not shown beside this card.

The timings are named constants beside `SESSION_TOKEN_WAIT_MS` in `app.js`. They are fixed page behaviour pinned by the spec, and nothing about them varies by environment, so they do not go through server configuration.

## Measurements

| Input | Measured | Used for |
|---|---|---|
| Production request time, server side, all routes (`/metrics`, 2026-11-05) | 1,621 of 1,621 at or under 0.1 s since that machine started | 15 s leaves a wide margin over a working server |
| `curl /ready` from one outside network | 0.62 to 1.12 s to first byte, 10 samples, the highest straight after 40 minutes with no requests from that network | The same, with real network time |
| One traced slow start-up in CI (ADR-0188) | `GET /v1/session` 411 ms | The same |
| `e2e/tests/navigation/tabs-share-token.spec.ts`, E3b | Holds a session answer 11.5 s and requires it to succeed | The limit must be above about 12 s |
| Machine start events (`fly machine list`) | No stop in the 13.5 hours after the last launch, despite `auto_stop_machines` | See below |

**Not measured: a real cold start.** ADR-0082 records that it never has been, and the machine did not stop during this work, so the first request after idle above is not one. A page from the browser's cache can make `/v1/session` the request that wakes a stopped machine. If a cold start takes more than 15 s, the first attempt is abandoned; the retry covers a start of up to about 31 s, and "Try again" allows 30 s more.

### Tests

`e2e/tests/signed-in/start-up-limit.spec.ts` has 42 tests, driven by Playwright's fake clock so none waits for a limit in real time. On the code before this change 35 fail; the other 7 guard behaviour that must not change (an HTTP answer is never repeated, and a held sign-in still goes out after a 500). `start-up-limit-review.spec.ts` adds 29 tests from the first review round: defects the review reproduced, and guards whose mutants the first file let survive. The lane's floor moves from 83 to 154. One of those tests reaches a retry during boot through a line served only in the test, because no page path to that overlap was found.

## Rejected alternatives

- **No automatic retry of `/v1/session`, only the limit and "Try again".** It removes the first two risks below. It departs from what the owner chose, and two reviews found no reproduced reason to drop a retry bounded at one. A person reloading already repeats the same request.
- **Retry on any failure, including 5xx.** It would repeat requests the server answered, spending the limiter and hiding cards that carry real information.
- **Give up at 10 s.** `tabs-share-token.spec.ts` E3b shows a healthy 11.5 s wait for another tab's lock path, and a shorter limit would abandon it.
- **Show the notice in the connection pill.** It is over 900 px from a pressed Estimate at phone width, and hidden on the landing.
- **A time limit on every request.** Wider than the problem. Writes after a healthy start-up still have none (see below).

## Consequences

- Start-up can take about 31 s per step before the card. Under lock contention the session step can take about 51 s (ADR-0178, decision 6: 10 s for the lock, 10 s for the counter), so about 82 s in all in that worst order.
- A repeated session request can spend a second daily session when the page holds no usable cookie. It is bounded at one retry.
- A repeat can overtake a delayed first attempt across two connections. The server then holds the first's token and **every open tab** takes the second's, so each gets "Security check failed / Refresh session" on its next write. This is narrow and recoverable.
- Tab A holds the lock with a hung request; tab B's 10 s lock wait ends and it renews alone, turning its sharing off; A's retry then retires B's token, and B refuses A's post. B's next write is refused once. A late first answer does the same without this change.
- After a first-session timeout, a token another tab posts is refused by the existing identity guards, so this tab needs "Try again". The guards are unchanged.
- A request that would have answered after 15 s is abandoned.
- The put-back of a kept question now yields to any text in the box, at boot as well, including text the browser restored on a reload or Back. The saved copy is consumed either way.
- Writes after a session has answered have no time limit: on a dead connection, a sign-in click after only the model step failed can still hang with its button disabled. True of every write before this change; recorded as W145.
- "Try again" followed by an HTTP failure still reloads the page, which loses a typed question. It is the old recovery path, and `store-unchecked.spec.ts` depends on it; recorded under W145.
- During the model step the pill reads "Session active" beside "Still connecting…". Each is true of what it describes.
- "Could not connect" and "Check your connection" are plain approximations in two cases that reach the card: a body that stalls after a good status, and a server that is itself down.

The failure modes behind this design are in `docs/analysis/2026-11-05-w140-start-up-time-limit-failure-modes.md`.
