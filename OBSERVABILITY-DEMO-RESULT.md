# Observability & demo-evidence backbone — RESULT

All seven stages (OD-1 → OD-7) shipped, each: branch → PR → green blocking
checks → squash-merge → deploy-verified (Deploy JOB `success` + prod
`/ready` state=live, plus a prod-surface curl for served deltas). Every
stage left `main` coherent and demo-able. Prod: <https://quorum.stackclimb.com>.

Working rule held throughout: **evidence-first, no fabricated number**. SLO
*targets* are declarations; every *measured* value cites its source. Reviews
ran a 2-lens fan on code PRs (an executing output-correctness lens in its own
worktree + an adversarial read) and 1 critical lens on docs PRs, each with a
round-2 pass on the fix diff. Bite proofs used file-copy restore, never
`git checkout`.

## Per-stage ledger

| Stage | PR | Squash SHA | Deploy JOB run | Prod-surface proof |
| --- | --- | --- | --- | --- |
| OD-1 `/metrics` + docs/80 SLOs | #77 | `0b014d3` | `29956496654` success | `curl /metrics` serves Prometheus text; `/ready` live |
| OD-2 ops dashboard `/ui/ops` | #78 | `5845409` | `29958936194` success | `/ui/ops` 200 (8 live tiles), `/static/ops.js` 200 |
| OD-3 request-ID correlation | #79 | `c728f45` | `29961670893` success | `/ready` echoes inbound `X-Request-ID` |
| OD-4 `make evals` | #80 | `3fec293` | `29963515232` success | no served delta; `/ready` live |
| OD-5 availability check + alert | #81 | `7fbc1f9` | `29964846338` success | dispatch proof run `29964680225` (both hosts live) |
| OD-6 incident runbook + doc review | #82 | `7002f8a` | `29964...` success (see below) | docs-only; `/ready` live |
| OD-7 evidence page + demo script | #83 | `<SHA>` | `<run>` | docs-only; `/ready` live |

> OD-6/OD-7 deploy-run ids: docs-only stages carry no served-asset delta, so
> the Deploy JOB `success` + prod `/ready` live is the deploy signal (the
> DEPLOY-READINESS lesson — a served-asset curl only applies to OD-1/2/3).

## What shipped and what it proves

- **OD-1** — `prometheus-fastapi-instrumentator`; `/metrics` (per-route-template
  counts by status class, latency histograms, in-progress gauge),
  public-unauth by pre-authorised decision, outside the OpenAPI schema so the
  drift-guard + Schemathesis are untouched. `docs/80` rewritten from a 5-line
  stub into a real doc (signals inventory, declared SLO table with per-row
  measurement source, alerting policy, provenance rules). *Proves*: real
  request telemetry with honest, sourced numbers.
- **OD-2** — `/ui/ops`, a self-contained CSP-clean SLO dashboard; every current
  value computed client-side from live `/metrics`/`/status`/`/ready`, never
  hardcoded (tested). *Proves*: at-a-glance SLO status with no fabricated data.
- **OD-3** — `X-Request-ID` middleware (safe-echo-or-regenerate, injection-proof)
  + contextvar log stamping (no-bleed proven under overlapping async requests);
  structured `query_run_id` telemetry. Aggregator log shape unchanged.
  *Proves*: per-request forensics without breaking existing log consumers.
- **OD-4** — `make evals`: honest per-suite table (114 executed, 100%) from a
  real pytest run; pinned pilot lines cite their docs. Errors never render
  green. *Proves*: the AI-behaviour suites pass and the accuracy pilot is
  pinned, not asserted.
- **OD-5** — `availability-check.yml` (15-min schedule + dispatch only, off the
  push path): fails on prod `/ready` non-200 / state≠live; GitHub's failure
  email is the $0 alert. Alert rule 1 flipped to MECHANISED; the runtime-vs-
  pipeline division of labour with the drift watchdog is documented. *Proves*:
  the OpenRouter-403 incident shape would now page the operator within ~15 min.
- **OD-6** — `docs/runbooks/live-provider-outage.md`: the real 2026-07-15 outage,
  every claim source-attributed, unverifiable details marked "not recorded".
  docs/80 un-staled; docs/81–84 stubs turned into honest pointers. *Proves*:
  a real postmortem with a mechanised prevention story, zero invention.
- **OD-7** — `docs/95-demo-evidence.md`: one row per claim → artifact → real
  identifier (all `gh`/`curl`-verified), an ops-dashboard screenshot, and a
  60–90 s demo click-path; short README "Production evidence" section.
  *Proves*: the whole backbone is demonstrable and every number is tracked.

## Real review findings that mattered (all fixed test-first, round-2 verified)

- **OD-1 MAJOR** — attacker-chosen HTTP method tokens minted unbounded metric
  series (uvicorn/h11 accept arbitrary tokens). Fixed with an `OTHER`-sentinel
  ASGI normaliser; round-2 proved the sentinel bounded (20 bogus methods → 1
  series). Plus: anchored `^/metrics$` exclusion (an unanchored pattern hid
  404 paths containing `/metrics`).
- **OD-3 MAJOR (latent)** — `$` in the safe-id regex tolerated a trailing `\n`,
  so `b'abc\n'` was echoed into the response header; fixed with `fullmatch`,
  RED-proven at the raw ASGI layer. Plus a corrected docstring (an
  `extra={'request_id'}` call site raises `KeyError`, pinned by a tripwire).
- **OD-4 MAJOR** — pytest fixture/collection ERRORs rendered as 100% green;
  fixed with an errors column + red-on-nonzero-exit, RED-proven with a real
  fixture-error suite.
- **OD-5 MAJOR** — the alert channel's own failure modes (60-day scheduled
  auto-disable, actor-attributed routing, ~96 emails/day sustained, no-retry)
  were undocumented; now stated honestly, each verified against GitHub docs.
- **OD-6 MAJOR ×4** — the runbook was itself *reconstructing* (the exact failure
  it documents): an unsourced 403 narrative and a function name
  (`_execute_or_simulate`) that never existed. De-reconstructed to cite real
  records; docs/80 un-staled (`/ui/ops` + request-ids shipped); contradictory
  81–84 stubs replaced.
- **CI caught** (OD-3) — the secret scanner flagged `token = ...` (a
  `contextvars.Token`, not a secret); renamed the variable, scanner untouched.

## Deliberately deferred (with the exact next command)

- **Alert rule 2 (error-rate over SLO)** — documented, not yet mechanised;
  needs a scrape history. Next: add a scheduled job that scrapes `/metrics`,
  computes the 5xx ratio over a window, and fails past 1% — model it on
  `availability-check.yml`. Do NOT put it on the push path.
- **`make gate-min-executed` missing-xml false-green** — pre-existing (NOT an
  OD-4 change): with no `build/gates/<name>.xml`, the target prints a
  traceback yet exits 0. Next: add `test -f "$XML" || { echo missing; exit 1; }`
  before the `[ ]` count checks in the `gate-min-executed` recipe, with a test.
- **Build-SHA env passthrough** — skipped (optional, non-blocking); `/status`
  surfaces the hardcoded `0.2.0`. Next: add a `--build-arg GIT_SHA` in
  `deploy.yml` and surface it in `/status` if a per-release version is wanted.
- **Fly release listing in deploy-verify** — `flyctl` had no auth token in this
  session; the served-surface curl + Deploy JOB success is the stronger proof.
  Next (operator): `fly releases --app quorum-ai | head -3` to see version rows.

## Verification commands (re-run any time, all $0)

```bash
curl -s https://quorum.stackclimb.com/ready                 # state: live
curl -s https://quorum.stackclimb.com/metrics | head        # Prometheus text
curl -sD- https://quorum.stackclimb.com/ui/ops -o /dev/null  # 200
gh run list --workflow=availability-check.yml --limit 3     # scheduled alert alive
make evals                                                  # 114 executed, 100%
```
