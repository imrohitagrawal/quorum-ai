# ADR-0007: Suppress the readiness banner's first paint, with a time bound

## Status

Accepted — 2026-08-03 (major-issues batch, issue #117)

## Context

The workspace rendered readiness twice on load: from the server-rendered
`window.LIVE_READINESS` seed, then from `GET /ready`. The credential probe runs
on a background thread at startup (#112), so a page served inside that window
carries a seed that can disagree with the verdict landing moments later.

Measured: a healthy deployment with a stale seed flashed "Live execution is
unavailable" and then reflowed **137 px** on desktop, **319 px** on mobile.

This banner is the one surface telling a user that every answer on screen is
**simulated**, so suppressing it wrongly is far worse than the flash.

## Decision

Do not paint from the seed alone. Wait for `/ready` to settle — and bound that
wait three ways, because a suppression that outlives the page is a hidden
safety disclosure:

1. a `finally`, so a throw inside the fetch's own error handler cannot skip it;
2. `boot()`'s outer `.catch`, because `boot()`'s `try` opens ~180 lines after
   the first paint and the region between is unguarded;
3. a **2000 ms** timer that paints the seed regardless.

## Measurements

Both suppression failures were reproduced before being fixed:

- A throw in `boot()`'s unguarded wiring region (injected by renaming an
  element id in the served HTML — the "renamed id / template change" the file's
  own comment calls realistic): pre-change the seed paint showed the
  disclosure; the suppression alone **hid it entirely**.
- `api()` uses a bare `fetch` with **no timeout** (zero `AbortController` /
  `AbortSignal` uses in the file), so a hung request never resolves and never
  rejects — a `finally` waiting on it never runs either. A hung `/ready` on an
  offline deployment stayed hidden indefinitely.

**2000 ms is a judgement call, not a derived value.** Long enough that a healthy
probe (~12 ms on loopback) never reaches it; short enough to bound the window in
which the run button is enabled with nothing on screen saying answers will be
simulated (review measured ~4 s of that window with `/ready` delayed 4 s).

## Consequences

- On a slow or hung probe the original flash returns — after 2 s, and only
  then. A brief flash on a degraded network is a better failure than a
  permanently invisible "every answer here is simulated".
- `toBeHidden()` cannot test this: it auto-retries and structurally cannot
  observe a ~100 ms transient. The gate is a `MutationObserver` installed via
  `addInitScript` before `app.js` runs, counting OFF→ON edges.
- The drift banner is deliberately **not** suppressed — different surface,
  different data source, no measured flash.

## Rejected alternatives

- **Reserve space for the banner** so a late change does not reflow. Rejected
  per the issue's own reasoning: showing a warning that is then retracted is
  its own small dishonesty. Suppression removes the false claim; reservation
  only removes the jump.
- **No timer, rely on `finally` + `boot().catch`.** Rejected: measured, a hung
  fetch defeats both.
- **Give `api()` a global timeout instead.** Correct and larger — it would fix
  this and other hangs. Deferred as a separate change; the timer bounds this
  disclosure now without touching every call site.

## Related

- Issues #112, #116, #117; `src/product_app/static/app.js`
- Tests: `e2e/tests/invariants/readiness-no-flash.spec.ts`
