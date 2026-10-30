# ADR-0188: A click while the workspace is still starting waits for the start-up it needs

## Status

Accepted — 2026-10-31, board row W121.

## Context

The workspace wires its buttons before its start-up finishes. Start-up is two requests: `GET /v1/session` (which gives the page its anti-forgery token) and `GET /v1/models/defaults` (which draws the model slots). Until they answer, the model slots are placeholders and the page has no token.

A click in that window acted on the half-built page:

- **Estimate** read the model slots with `getModelIds()`, which calls `.value.trim()` on each; the placeholders have no value, so the click threw "Cannot read properties of undefined (reading 'trim')", showed an error card and never asked for the estimate.
- **Any write** (the sign-in start, the high-stakes warnings check) went out without its `x-csrf-token` header, because `api()` adds the header only when a token is already held. The server refused it (403 `CSRF_INVALID`); for the sign-in start, the visitor stayed signed out.

The window is normally a few milliseconds. On a slow server or connection it is long enough for a person to click into. CI showed it: the signed-in browser lane, whose tests click as soon as the composer is visible, failed 10 attempts on 2026-10-29 and 2026-10-30. The one failure with a trace showed `GET /v1/session` taking 411 ms (about 6 ms normally), a token-less write refused with 403, and the error card above.

## Decision

1. Start-up has two steps a click may need, each a promise that `boot()` settles when the step ends, **on success or on failure**: the session step, then the model step. A boot that fails before reaching them settles both too. Nothing waits on them for good.
2. `api()` waits for the session step before sending any request that is not `GET` or `HEAD`. The token header is built after the wait, so the request carries the token the session answer gave.
3. `estimateRun()`, the one path every estimate and run goes through, waits for the model step after showing its spinner and before reading the question and the slots. If the person left for another question meanwhile, it stops, as it already does when an answer arrives late.
4. A click made after start-up is unchanged: both promises are already settled.

## Measurements

| Check | Before | After |
|---|---|---|
| Estimate clicked while `/v1/session` is held | error card "reading 'trim'", no estimate request | waits; after release one estimate request with the session's token and the full panel; the cost gate opens |
| Estimate clicked while `/v1/models/defaults` is held | the same error card | waits; after release the full panel is priced |
| "Sign in with Google" clicked while `/v1/session` is held | the start is sent at once, without a token | the start waits; after release it carries a token and the account is shown |
| `/v1/session` fails while an Estimate click waits | the click finishes too (it fails on the placeholders) | the click finishes: the error shows and the button is usable |

(`e2e/tests/signed-in/early-click.spec.ts`; the first three fail on the code before this change, and each of three mutations — no session wait, release only on success, no model wait — turns a named test red.)

## Rejected alternatives

- **Disable the buttons until start-up ends.** A visible change for a window that is normally milliseconds, and it still needs a release on failure. A click that waits behind the spinner it already shows does the same job invisibly.
- **One wait for the whole start-up, inside `api()`.** The model ids are read before `api()` is called, so an estimate would still price the placeholders (an empty panel). And the sign-in start and sign-out would then wait for the model list, which has no time limit, so a stuck model list would block signing in.
- **Make the tests wait for `data-app-state="ready"`.** It would hide the window from the tests while a person could still hit it.

## Consequences

- A write made in the first moments after load is delayed until the session answers, never sent without a token.
- If the model list never answers, an Estimate click keeps its spinner; the page cannot price a run then anyway. If the model request fails, the boot's error shows and the click finishes.
- `getModelIds()` still throws on placeholders; any new caller that can run before the model step must wait for it too.
