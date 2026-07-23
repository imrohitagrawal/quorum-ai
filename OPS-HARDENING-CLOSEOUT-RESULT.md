# RESULT — Ops hardening + observability deferred-item closeout

**Status: COMPLETE (2026-07-23).** One PR (#91, squash `9555701`), closes #86.
Deploy JOB run `30022024397` **success** (parallel `30021948212` cancelled =
concurrency dedupe, expected). Prod verified by content, not by `/health` 200.

## What shipped (six pieces, one PR)

| # | Piece | Where | Bite-proof |
|---|---|---|---|
| A | CSP `base-uri 'none'; form-action 'none'` (closes #86) | `main.py:_CSP_POLICY` | exact-string + parsed-directive pins across 9 routes incl. 404 (`test_security_headers.py`); both UIs green on chromium/firefox/webkit (csp-smoke + ops e2e, `--retries=0`) |
| B | `/ready` reasons = closed vocabulary; exception detail log-only | `readiness.py` (`APPROVED_REASON_PREFIXES`) | hostile-exception leak test keyed off leaked VALUES; closed-set sweep over all 5 probe states; RED-proven vs old producer |
| C | `/status` `sentry` → vendor-neutral `error_tracking` | `main.py`, `feedback_audit.py` (snapshot + STATUS.md row w/ legacy fallback), `openapi.yaml` regenerated | `test_operations_info_leak.py` (vendor name absent from whole payload); `test_feedback_audit.py` both key directions |
| D | `gate-min-executed` false-green fix | `Makefile` | RED proven live (missing XML → traceback → **exit 0**); now missing-file check + non-2-counts guard + sums all direct `<testsuite>` children; shell-level tests RED→GREEN via copy-aside revert |
| E | Alert rule 2 MECHANISED — 5xx SLO, $0 | `error-rate-check.yml` (cron `7,37 * * * *` + dispatch only) + `scripts/error_rate_probe.py` | 15 unit tests: alert ≥1% (SLO is "<1%", boundary alerts), min-delta skip both directions, counter-reset skip both directions, malformed-scrape ALERT, timestamp tolerance; trigger surface pinned by `test_error_rate_check_workflow.py` |
| F | Build-SHA passthrough | `deploy.yml --build-arg` → Dockerfile `ARG/ENV BUILD_SHA` → `/status.build_sha` | env-set/unset tests; **proved itself on prod** (below) |

## Prod verification (2026-07-23, post-deploy)

```
curl -sI https://quorum.stackclimb.com/ui/ops | grep -i content-security-policy
  → … base-uri 'none'; form-action 'none'
curl -s https://quorum.stackclimb.com/status | jq -r .build_sha
  → 9555701da8d780976925d48f7e216992ade84273   (== merged SHA, exact)
curl -s https://quorum.stackclimb.com/status | jq 'has("sentry"), .error_tracking'
  → false, "active"
/ready → {"state":"live","reasons":[],"catalog_drift_ids":[]}
```

**New one-line deploy check for all future sessions:**
`curl -s https://quorum.stackclimb.com/status | jq -r .build_sha` == merged SHA.

Rule-2 proof dispatch: run `30022211861` **green** — measured 120.4 s window,
Δtotal=8 → honest `SKIP_LOW_TRAFFIC` (floor 25) on real prod data, exit 0.

## Review (exactly 2 cycles, as capped)

Both cycles ran as parallel workflows (breaker + correctness lens, every
finding independently re-verified by a dedicated refuter agent).

- **Cycle 1 — 6 confirmed, all fixed:** exception detail was dropped from the
  log too (now logged privately; healthy-INFO line keyed off `reasons`);
  `>` vs the "<1%" SLO boundary (now `>=`); `testsuites` wrapper counted only
  its first suite (now sums direct children); regex rejected the spec's
  optional trailing timestamp (perpetual-silent-skip trap; now tolerated);
  dispatch checkout `github.ref` vs stamped `github.sha` race (both jobs
  pinned); the workflow's trigger discipline was prose-only (structural test
  added).
- **Cycle 2 — 7 confirmed, all fixed:** stale `--status-json` consumer would
  render `| Sentry | None |` (renamed + legacy fallback); `iter()` double-
  counted nested suites (direct children only); stale dispatch echo/comment +
  gate-job checkout; probe except-net missed `http.client.HTTPException`/
  `ValueError` (alert still fired, but as a raw traceback — polished);
  docs/80 stale CSP-gap paragraph (now records the close); "two watchers" →
  three-watcher division of labour.
- Post-cycle-2, CI's changed-lines gate (95%) correctly caught the one
  uncovered fixed line — covered by two `generate_status_md` tests
  (`4b3641f`), which is the gate doing its job, not a third review cycle.

## Guardrails held

- `/metrics` response bytes untouched; exposition contract green.
- All four ops endpoints stay public (OD-1) — content hardened, access unchanged.
- No fabricated numbers: threshold = documented 1% SLO; window measured and
  logged per run; min-delta floor (25) documented with its rationale in the
  script; quiet prod windows skip honestly (observed live).
- Hermetic/$0 throughout: public GETs only; no paid runs, no secret changes.

## Deferred / follow-ups (deliberate, small)

- `feedback_audit.py`'s audit-report table still says "Sentry" in its own
  Markdown *report* body (line ~875 renamed; the audit LLM-report template is
  untouched — internal operator artifact, not a public surface).
- `error-rate-check.yml`'s min-delta floor means genuinely quiet half-hours go
  unjudged (documented in workflow header + docs/80; rule 1 covers liveness).
- Nested-`<testsuite>` XML shapes beyond pytest's flat output are handled
  (direct-children sum) but not exhaustively speced — pytest is the only
  producer.
