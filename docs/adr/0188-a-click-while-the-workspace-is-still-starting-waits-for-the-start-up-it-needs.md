# ADR-0188: A click while the workspace is still starting waits for the start-up it needs

## Status

Accepted — 2026-10-31, board row W121. The owner put this fix ahead of the dependency updates (CHG-109).

## Context

The workspace wires its buttons before its start-up finishes. Start-up is two requests: `GET /v1/session` (which gives the page its anti-forgery token) and `GET /v1/models/defaults` (which draws the model slots). Until they answer, the model slots are placeholders and the page has no token.

A click in that window acted on the half-built page:

- **Estimate** read the model slots with `getModelIds()`, which calls `.value.trim()` on each; the placeholders have no value, so the click threw "Cannot read properties of undefined (reading 'trim')", showed an error card and never asked for the estimate.
- **Any write** (the sign-in start, the high-stakes warnings check) went out without its `x-csrf-token` header, because `api()` adds the header only when a token is already held. The server refused it (403 `CSRF_INVALID`); for the sign-in start, the visitor stayed signed out.

The window is normally short. On a slow server or connection it is long enough for a person to click into. CI showed it: the signed-in browser lane, many of whose tests click as soon as the composer is visible rather than waiting for `data-app-state="ready"`, failed 12 attempts on 2026-10-29 and 2026-10-30. The one failure that left a trace showed `GET /v1/session` taking 411 ms against 6 ms for the session request before it in the same run, a token-less write refused with 403, and the error card above. The other failures left no trace, so this is the cause of the one that was traced; the rest are consistent with it.

## Decision

1. Start-up has two steps a click may need, each a promise that `boot()` settles when the step ends, on success or failure. The session step comes first, then the model step. A boot that throws before reaching them settles both. A step that has ended never holds a click.
2. `api()` waits for the session step before sending any request that is not `GET` or `HEAD`, and builds the token header after the wait. After a successful start-up the write carries the token the session answer gave; after a failed one it is sent as before and the server refuses it. `GET` and `HEAD` do not wait, so reads go out as before. No read in today's start-up goes through `api()` before the session step ends (the session request itself uses `fetch`), so no test can see this exemption: a mutation that makes reads wait too passes every test in the spec.
3. `estimateRun()`, the one path every estimate and run goes through, waits for the model step after showing its spinner and before reading the question and the slots. If the person left for another question meanwhile, it stops, as it already does when an answer arrives late. It then checks whether the slots are drawn at that moment (`modelSlotsDrawn()`), not what the first start-up reported. If they are not (start-up failed and was not recovered), it shows start-up's own error again (`startUpFailure`, which keeps its way to recover, such as "Start a session"), never a crash on the placeholders. After a successful "Start a session", which draws the slots, an estimate prices normally.
4. A click made after start-up is unchanged: both promises are already settled.

## Measurements

`e2e/tests/signed-in/early-click.spec.ts` holds each start-up request open until after the click, or answers it with a failure.

| Check | Before this change | After |
|---|---|---|
| Estimate clicked while `/v1/session` is held | error card "reading 'trim'", no estimate request | waits; after release one estimate request with the session's token, pricing the panel the slots show; the cost gate opens |
| Estimate clicked while `/v1/models/defaults` is held | the same error card | waits; after release the drawn panel is priced |
| "Sign in with Google" clicked while `/v1/session` is held | the start is sent at once, without a token | the start waits; after release it carries a token and the account is shown |
| `/v1/session` fails while an Estimate click waits | the start-up card ("Start a session to run a query") | the same card; the click finishes |
| Estimate clicked after a start-up has failed | error card "reading 'trim'" | the start-up card again |
| `/v1/models/defaults` fails while an Estimate click waits | — | the click finishes without the crash card |
| `/v1/session` fails while a sign-in click waits | — | the start goes out once, is refused, and the button is usable again |
| "Start a session" recovers a failed start-up, then Estimate | (the estimate is priced) | the same: one estimate request, the cost gate opens |
| start-up throws while wiring the page, then "Sign in with Google" | — | the start goes out once and the button is usable again, never left waiting |

On the code before this change, 5 of the 9 tests fail; the other 4 guard the failure and recovery paths this change must keep working. Six mutations each turn a named test red: no session wait in `api()`; the session step settled only on success; no release when `boot()` throws; no "are the slots drawn" check; no model wait in `estimateRun()`; and reading the first start-up's outcome instead of the slots (the recovery test). A review of an earlier version of this change found exactly that last defect: after "Start a session", every estimate showed the old start-up error again.

## Rejected alternatives

- **Disable the buttons until start-up ends.** A visible change for a window that is normally short, and it still needs a release on failure. A click that waits behind the spinner it already shows does the same job.
- **One wait for the whole start-up, inside `api()`.** The model ids are read before `api()` is called, so an estimate would still price the placeholders (an empty panel). And the sign-in start and sign-out would then wait for the model list, which has no time limit, so a stuck model list would block signing in.
- **Make the tests wait for `data-app-state="ready"`.** It would hide the window from the tests while a person could still hit it.

## Consequences

- A write made in the first moments after load is delayed until the session answers. After a successful start-up it always carries the session's token.
- A start-up request that never answers holds what waits on it: neither `api()` nor the session request has a time limit, so a hung `/v1/session` holds every write, and a hung model list holds an Estimate click (its spinner stays). Before this change those clicks failed at once instead; a time limit on the start-up requests is separate work.
- `getModelIds()` still throws on placeholders; any new caller that can run before the model step must wait for it too.
