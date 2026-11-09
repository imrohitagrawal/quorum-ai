# W140: how a start-up time limit with a retry can fail

Listed before the design (`.agents/skills/work-item-delivery/SKILL.md`: sign-in and session work). The decision is ADR-0189.

"Design" means the design handles it, with a test in `e2e/tests/signed-in/start-up-limit-retries.spec.ts`, `start-up-limit-notice-and-card.spec.ts` or `start-up-limit-recovery.spec.ts`. "Accepted" means it is a stated risk in ADR-0189. "Unchanged" means the behaviour was already so.

| # | Area | How it fails | What the person sees | Outcome |
|---|---|---|---|---|
| 1 | Typing | The card always takes focus and scrolls (`showError`). At 31 s or later it can arrive mid-sentence: the rest of the text is lost and the spaces scroll the page | Half a question | Design: no focus or scroll while a text field has focus, on every path that shows the card; the fixed line carries the title on a phone |
| 2 | Phone | The pill and the card region are above the screen once Estimate is in view at 390 px, and the top bar is hidden on the landing | A spinner with no message | Design: the notice is fixed to the viewport |
| 3 | Sign-in | Start-up fails, the held sign-in write goes out on the dead connection and never ends | The button stays disabled for good | Design: refused in the page when no answer came and no token is held |
| 4 | Try again | `showError` rebuilds buttons, so a click during a retry can draw a second, live "Try again"; a second retry queues behind the lock and can turn sharing off | A second retry, or a write with no token | Design: guard inside the function; both steps re-armed |
| 5 | Recovery | The first-run work after a good boot was skipped by a retry | "Session started" with an empty box; the state stays `error` | Design: one shared function |
| 6 | Kept question | The shared function overwrites a question typed since load | The newer text is lost | Design: text in the box stays |
| 7 | Recovery failing | `retrySession` reloads on failure; on a dead connection that replaces the page | The browser's error page; the question is gone | Design: the card stays, no reload, for no answer only |
| 8 | Body stall | Headers arrive, then silence. An abort during the body read is a raw `AbortError` | "signal is aborted without reason" on a card | Design: the limit covers the body, and the error is mapped |
| 9 | HTTP answers | Retrying a 401, 429 or 500 would spend the limiter and hide the session cards | Wrong card, slower | Design: any HTTP answer ends the step |
| 10 | Slow but working link | An answer takes 16 s. Both automatic attempts are abandoned | The card | Design: "Try again" allows 30 s; the abandonment is accepted |
| 11 | Token, overtaking | A delayed first attempt reaches the server after the retry on a new connection. The server holds the first token; every tab takes the second | "Security check failed" on the next write in every tab; "Refresh session" recovers | Accepted |
| 12 | Token, both lost | The server replaced the token and both answers were lost; other tabs hold a retired token | Their next write is refused once | Unchanged |
| 13 | Token, two tabs | B's lock wait ends and it renews alone, then A's retry retires B's token, and B refuses A's post | B's next write is refused once | Accepted |
| 14 | Daily limit | A lost answer loses its cookie, so a repeat can count a second session | One allowance spent early, only without a usable cookie | Accepted; bounded at one retry |
| 15 | Limiter | Each retry that reaches the server spends one of 10 a minute. Several restored tabs on a slow link could reach a 429 | The session card | Accepted |
| 16 | Lock | The first attempt hangs inside the lock | Other tabs wait 10 s, then go alone, as before; the lock is now freed within about 41 s (the counter also runs inside it) | Design |
| 17 | Timers | A forgotten exit leaves the notice over the card | Two messages | Design: cleared on every exit, `boot().catch` included |
| 18 | Screen reader | Writing the text before revealing the line may go unannounced | Silence | Design: reveal first, as `showLandingHandoffNote` does |
| 19 | Duplicate message | A dead connection also fails `/ready`, whose toast is worded for operators | Two alerts, one in jargon | Design: no toast beside this card |
| 20 | Background or sleeping tab | Timers are throttled, so the limit fires late; on wake it may fire at once | The card on return; "Try again" works | No change needed (general browser behaviour, not measured here) |
| 21 | Cold start | A cached page can make `/v1/session` the request that wakes a stopped machine | The retry covers a start of up to about 31 s; "Try again" allows 30 s more | Accepted; the time is not measured (ADR-0189) |
| 22 | Overlap | A boot that ends during a retry could release a click waiting for that retry. No page path to this overlap was found; it was reached through a line served only in a test | A write with an old token | Design: each operation settles its own steps. A late boot can still show its card and hide the retry's line (advisory) |
| 23 | Live run or result | "Start a session" over a live run or a result reset its run details, dropped the models chosen and hid a simulated-output notice (the last two before this change too) | State reset behind the view; a missing disclosure | Design: the end of start-up and the redraw run only on a page that has not started |
| 24 | After start-up | A write with a token on a dead connection has no limit | A spinner with no end | Unchanged; W145 |
