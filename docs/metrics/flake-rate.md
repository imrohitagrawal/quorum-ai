# E2E flake rate — measured, not estimated (RB-4)

The blocking e2e lane runs every spec **once**, with `--retries=0`. That makes a
single red honest but ambiguous: a spec that fails one run in ten looks exactly
like bad luck. This page is where that ambiguity is resolved with a number.

**Source of every row below:** `.github/workflows/flake-scan.yml` —
`--repeat-each=10 --retries=0` per spec, one matrix leg each, on a nightly cron
plus `workflow_dispatch`. A row may only be filled in from a **real run id**.
An empty cell means *not yet measured*; it never means *clean*. (A leg that
produces no junit report is `UNMEASURED`, not `0/10` — the summary step says so
explicitly.)

## Policy

| measured | action |
| --- | --- |
| 0 failures | the spec stays in the blocking lane |
| >0 failures | **QUARANTINE**: move behind a `@flaky` tag excluded from the blocking steps, add a row here with an owner and the root cause under investigation |

**Read the denominator literally.** `--repeat-each=10` repeats every test *in*
the spec ten times, so a 53-test spec is measured over 530 executed
repetitions, not 10 — the "N≥10" in the rule is the repeat count, never the
denominator. The summary step prints the denominator it actually computed, and
counts only repetitions that **executed**: a skipped repetition is not a
passing one, so a leg that skipped everything reports `UNMEASURED`, never
`0/N`. Transcribe the printed numbers; do not round them to a tenth.

A retry is never the remedy, and neither is a wider timeout. Both keep the
pipeline green while the intermittency — which is usually a real product race,
not a test artefact — ships to users. The scan job is deliberately
`continue-on-error: true`: it measures, it does not gate, so there is never
pressure to quarantine for convenience.

## KNOWN CONFOUND — read before transcribing the first scan

**The first scan may measure the session rate limiter rather than flakiness.**
Do not record its output as a flake rate, and do not quarantine on it, until
this is resolved.

`/v1/session` is rate limited per IP at 30 requests/minute
(`_InMemoryIpRateLimiter`, `src/product_app/query_runs.py`). Every spec's
`boot()` GETs it once. Measured directly against a locally started app: requests
1–30 return 200, **request 31 onward returns 429**, refilling one token every
two seconds.

The arithmetic that follows is not reassuring:

| spec | tests | boots at `--repeat-each=10` |
| --- | --- | --- |
| `tests/ui-parity/parity-behavior.spec.ts` | 53 | 530 |
| `tests/accessibility/axe-all-views.spec.ts` | 15 | 150 |

All from one IP, serially (CI runs `workers: 1`). The lane only stays under the
limit while each test averages more than the two-second refill interval — so it
sits right on a boundary that CI load moves across.

That is also a **credible root cause of the original intermittent parity
failure** this slice set out to fix, and a better one than the mis-argumented
wait alone: the parity spec's 53 boots already exceed a 30-token bucket in a
single ordinary run. The wait bug explains why the failure was *illegible*
(unbounded wait, killed by the test timeout, no cause reported); the limiter
would explain why it *happened*. Both are now visible rather than one masking
the other — with the wait fixed, a 429 surfaces immediately as
`app bootstrap did not succeed`, naming itself.

**This is stated as a corroborated hypothesis, not a conclusion.** What is
measured is the limiter's behaviour (30 then 429, above) and the test counts.
What is *not* measured is the real per-test pace on a CI runner, which is the
only thing that decides whether the bucket actually drains there.

→ **OPERATOR HAND-OFF.** Resolving it means giving the hermetic lane a
rate-limit seam — a change to a security control, which does not belong in a
CI-infra PR and should not be made by widening a guardrail on an unmeasured
hunch. Options, for a decision: (a) an opt-in, default-off env override set only
in the hermetic workflows; (b) per-worker IP variation; (c) letting specs share
one session. Until then the scan runs and reports, but **its output is not a
flake rate.**

## Measurements

| spec | executed repetitions | failures | rate | date (UTC) | run id |
| --- | --- | --- | --- | --- | --- |
| `tests/invariants/rendering-invariants.spec.ts` | — | — | — | — | — |
| `tests/invariants/real-integration-smoke.spec.ts` | — | — | — | — | — |
| `tests/invariants/trust-score-invariants.spec.ts` | — | — | — | — | — |
| `tests/ui-parity/parity-behavior.spec.ts` | — | — | — | — | — |
| `tests/accessibility/axe-all-views.spec.ts` | — | — | — | — | — |

> **Status: unmeasured.** `flake-scan.yml` lands with this change; the first
> scan populates these rows. Recording a rate here before a scan has run would
> be fabricating the one number the whole mechanism exists to produce.
>
> **And the first scan alone will not be enough to fill them** — see the
> confound above. A leg that comes back dirty must be attributed to the rate
> limiter or exonerated of it *before* a number lands in this table.

## Diagnosed, partly fixed

### The parity/axe `boot()` wait — made DIAGNOSABLE, not yet fixed

**Status, stated precisely: RB-4 fixed why the failure was unreadable. It did
not fix why the failure happens.** The likely cause is the session rate limiter
in the confound section above, which this slice deliberately does not touch.
What follows is the diagnostic half.

Both `tests/ui-parity/parity-behavior.spec.ts` and
`tests/accessibility/axe-all-views.spec.ts` waited for the four model slots to
populate with:

```ts
await page.waitForFunction(fn, { timeout: 15000 });
```

Playwright's signature is `waitForFunction(pageFunction, arg, options)` — so
the options object was passed in the **`arg`** position and the 15s budget was
never applied.

What it fell back to is worse than a longer timeout. `PageWaitForFunctionOptions.timeout`
"Defaults to `0` - no timeout" (`playwright-core/types/types.d.ts`), overridable
only by an `actionTimeout`, which this repo does not set. So the wait was
**unbounded**: it could not fail on its own terms at all, and was simply killed
by the 60s whole-test timeout (`timeout: 60000` in `e2e/playwright.config.ts`).
That is why the failure always surfaced as a generic "test timeout" with no
cause attached, instead of a 15s wait failure naming the condition it was
waiting on.

Why the wait could hang at all: the slots are painted by `refreshDefaults()`,
two network round-trips into `boot()` (`initSession()` first). If `initSession()`
threw, `renderModelInputs` was never reached and the condition could never
become true — indistinguishable, to the waiter, from merely being slow.

What RB-4 changed — no timeout was widened:

1. `boot()` now stamps `data-app-state` on `<html>` on **both** paths
   (`ready` / `error`), giving automation one settled fact to observe.
2. `waitForComposerReady()` (`e2e/fixtures/stabilize.ts`) waits on that signal
   with the options in the correct position, then asserts the outcome — so a
   failed bootstrap fails **fast**, naming the cause, instead of consuming the
   test budget.

**What that does and does not buy.** `initSession()` throwing is the trigger,
and the most likely reason it throws is the 429 documented in the confound
above — which this slice does not fix. So the specs are not proven stable; a
`GET /v1/session` refusal that used to appear as an anonymous 60s timeout now
appears immediately as `app bootstrap did not succeed`. That is a real gain —
the failure names itself, which is what made the cause findable at all — but it
is a diagnostic gain, not a stability one.

Both specs are in the scan matrix above, so the *next* claim about them will be
a measured one rather than an assurance.
