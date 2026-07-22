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

## KNOWN CONFOUND — RESOLVED 2026-07-22 (run `29911231157`)

**RESOLVED.** The seam landed (Stage B, D0, `bba01c78`) and a real post-seam scan
now demonstrates it. Run
[`29911231157`](https://github.com/imrohitagrawal/quorum-ai/actions/runs/29911231157)
ran with `SESSION_RATE_LIMIT_PER_MINUTE=600` (confirmed in the job env) and the
historically-affected legs came back **clean**: `parity-behavior` 0/530 and
`axe-all-views` 0/150 — i.e. all 530 parity boots and 150 axe boots succeeded,
with **zero HTTP 429s** in the run (the only "429" strings in the log are
timestamps, node PIDs, and the `SESSION_RATE_LIMIT_PER_MINUTE` env line). Under
the old 30-token bucket the 53-boots-per-run parity spec could not have passed
530/530. The scan therefore measured the **product**, not the limiter — the
number in Measurements is a real flake rate. The original text is retained below
for the record.

---

**[Original confound — the first scan may measure the session rate limiter rather
than flakiness.** Do not record its output as a flake rate, and do not quarantine
on it, until this is resolved.]

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

### AMENDMENT (Stage B / D0) — the seam landed; not yet demonstrated

Option **(a)** was taken. The operator pre-authorised it as **D0**: a
default-`None`, LOCAL-only override `SESSION_RATE_LIMIT_PER_MINUTE`
(`src/product_app/config.py`), bounded `[1, 10000]`, refused at startup outside
LOCAL, seeding `_InMemoryIpRateLimiter` capacity/refill. `flake-scan.yml` now
sets `RUNTIME_ENVIRONMENT: "local"` and `SESSION_RATE_LIMIT_PER_MINUTE: "600"`
(≈530 parity boots + headroom), so the scan lane's per-IP bucket is 600/min, not
30. The old `QUORUM_RUNTIME_ENVIRONMENT: "ci"` was a **no-op** (no `env_prefix`;
`"ci"` is not a valid enum) — the lane only ran as LOCAL by accident; it is now
explicit.

- **Landed at:** Stage B PR #66, squash `bba01c78` (deployed Fly v28).
- **Status: RESOLVED 2026-07-22.** Demonstrated by run `29911231157` on the
  post-seam SHA `7fbf1a1`: boots did not 429 (parity 0/530, axe 0/150, zero HTTP
  429s in the run), so the Measurements table now carries a real, run-id-bearing
  flake rate (0/960 across the five specs) rather than dashes.

## Measurements

| spec | executed repetitions | failures | rate | date (UTC) | run id |
| --- | --- | --- | --- | --- | --- |
| `tests/invariants/rendering-invariants.spec.ts` | 50 | 0 | 0/50 | 2026-07-22 | 29911231157 |
| `tests/invariants/real-integration-smoke.spec.ts` | 10 | 0 | 0/10 | 2026-07-22 | 29911231157 |
| `tests/invariants/trust-score-invariants.spec.ts` | 220 | 0 | 0/220 | 2026-07-22 | 29911231157 |
| `tests/ui-parity/parity-behavior.spec.ts` | 530 | 0 | 0/530 | 2026-07-22 | 29911231157 |
| `tests/accessibility/axe-all-views.spec.ts` | 150 | 0 | 0/150 | 2026-07-22 | 29911231157 |

> **Status: MEASURED (first scan, 2026-07-22).** Run
> [`29911231157`](https://github.com/imrohitagrawal/quorum-ai/actions/runs/29911231157),
> dispatched on the post-seam SHA `7fbf1a1` (RB-5 merge, which carries Stage B's
> 600/min seam), `RUNTIME_ENVIRONMENT=local` + `SESSION_RATE_LIMIT_PER_MINUTE=600`
> confirmed in the job env. Every leg ran `--repeat-each=10 --retries=0` and came
> back **0 failures** across its executed repetitions (denominators transcribed
> literally from each leg's `[FLAKE]` summary: 50 / 10 / 220 / 530 / 150). No leg
> was UNMEASURED (none all-skipped). **Measured flake rate: 0/960 across the five
> timing-sensitive specs.** Every spec stays in the blocking lane; nothing is
> quarantined.
>
> This does not make "flaky" impossible forever — it is one clean scan, not a
> proof. The mechanism keeps running (nightly + dispatch); a future dirty leg is
> QUARANTINED behind `@flaky`, never retried, and its rate lands here with its
> own run id.

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
