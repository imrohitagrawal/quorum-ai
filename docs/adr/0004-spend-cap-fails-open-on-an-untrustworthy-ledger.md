# ADR-0004: The per-account spend cap fails OPEN on an untrustworthy ledger

## Status

Accepted — 2026-08-03 (major-issues batch, issues #101 / #109 / #122 / #123)

## Context

The per-account cap (`DAILY_CAP_USD`, $0.20 / 24 h) is metered by summing rows
from the SQLite feedback store. The question this ADR settles: **what should a
priced request do when that ledger cannot be trusted?**

"Cannot be trusted" has three measured shapes (`feedback_store.py` documents
each, and `tests/integration/test_feedback_store_write_failures.py` reproduces
them against real SQLite, no mocks):

1. **No store at all** — the boot-time open raised and `main` swallowed it.
2. **Writes failing now** — a RESERVED lock, a read-only volume, a full disk.
3. **Rows silently missing** — the subtle one. `record()` swallows a failed
   write, so a dropped *billed* charge leaves the ledger short. Any later
   unrelated write (an ordinary telemetry row) re-stamps `write_health()` back
   to `"ok"`, so the ledger **looks** healthy while under-reporting money.

Issue #122 asked whether to refuse (fail closed) or serve (fail open). Issue
#101 had earlier chosen "loud only" without recording why.

## Decision

**Fail open, loudly. Never meter against a ledger known to be incomplete.**

Concretely, in `CostEstimationService.estimate()`:

- Meter the cap **only** when `feedback_ledger_may_be_metered(store)` — i.e.
  there is no positive evidence the rows are missing money.
- Otherwise **serve the request** and emit the rate-limited
  `_log_daily_cap_bypassed()` ERROR. Do not consult `daily_spend_for`, because
  a confident wrong number is worse than an admitted unknown.
- A **fail-closed** mechanism exists, complete and tested, behind
  `settings.daily_cap_fail_closed`, **defaulting to `False`**. Activation is a
  human decision, not an inherited default.

## Measurements

**The leak this replaces** (real `FeedbackStore`, real second connection holding
`BEGIN IMMEDIATE`, every billed write lost then masked by one ordinary
telemetry write):

| run | requests allowed | real spend | ledger reports | rows on disk |
|---|---:|---:|---:|---:|
| leaking wiring | 12 (unbounded; the loop stopped) | **$0.3180** | $0.00 | 0 |
| control — same fault, masking write removed | 2 | $0.0530 | — | 0 |

Against a $0.20 cap. The **only** difference between the two runs is a write
that has nothing to do with billing. This is F-01, the leak
`lost_billed_writes` exists to make unmaskable, and it survived #109, #122 and
#123 intact because nothing on the allow path read that counter.

**Bounded exposure of failing open.** During a total ledger fault the in-memory
cumulative rail (`costs._cumulative_spend_for`) is untouched — it reads a
process-memory ring, not SQLite — and still binds each account at
`HARD_LIMIT_USD` ($0.25). New accounts need sessions (2/24 h per IP, durable).
Exposure is therefore tens of cents, not unbounded.

**The deciding inconsistency.** `GLOBAL_DAILY_CEILING_USD` ($5, **25× larger**
than the cap this guards) already chooses fail-open on the *identical* fault,
deliberately and in a comment: *"a storage fault must not silently turn into
'everyone gets simulated answers'"*. Fail-closing the small rail while its
bigger sibling fails open is incoherent.

**Cost of the alternative.** Fail-closed refuses **every** priced request from
**every** account for the duration of the fault — the store is global while the
cap is per-account, so one account's dropped row denies everyone.

## Consequences

- During a storage fault the app stays up and under-meters by at most the
  amount the in-memory rail permits.
- The ERROR is the only signal; it must stay alerted on. `/status` exposes
  `feedback_db`, `feedback_writes` and `feedback_lost_billed_writes`.
- **`/status` reports no field meaning "traffic is being refused"** — if
  fail-closed is ever switched on, that gap must be closed first, or an
  operator reading `feedback_writes: ok` will conclude the fault is over while
  users are still being turned away.
- The cap under-counts permanently after any lost charge; lost charges stay
  lost (`record()` has no retry and no queue). Accepted since #101.
- `lost_billed_writes` is per-process and assumes `--workers 1`
  (see ADR-0002). Multi-instance breaks this design, not just this rail.

## Rejected alternatives

- **Fail closed by default.** Rejected on the numbers above: it protects tens of
  cents by risking total unavailability, and contradicts the larger rail. The
  mechanism is kept behind a default-off flag so the choice stays available
  without being the default.
- **Reserve-then-commit in one transaction** — *the correct design, deferred.*
  `BEGIN IMMEDIATE; INSERT reservation; SELECT sum(...) WHERE account=? AND ts
  > now-24h; COMMIT`. The affordability answer then comes from the same
  transaction as the charge, so a failed write cannot be invisible to the read
  — which is the root cause of every defect above. It needs no extra writes:
  the billed `cost_guardrail_accepted` row already exists on the create path.
  Deferred because it restructures the money path and this batch was already
  carrying nine issues; it is the recommended next change to this surface, and
  it would delete the flag, both trust predicates and the background reconnect.
- **Probe-on-demand ("can you write?" at decision time).** Rejected: a synthetic
  probe write is the same information as the real one for strictly more I/O,
  and a probe-write on `/status` was previously measured as a DoS vector. The
  authorisation half of that objection dissolves on an authenticated priced
  path, but the extra write does not earn its place next to reserve-then-commit.
- **Move the meter off SQLite** (Postgres, Redis, a ledger service). Correct at
  scale and wrong here: a network dependency and an operational surface to
  protect a $0.20 per-account cap on a single-instance demo. ADR-0002 already
  fixed single-instance SQLite as the deployment shape; revisit both together
  when multi-instance is real.
- **Per-account fault scoping** (one account's lost row denies only that
  account). Attractive, but `write_health`/`lost_billed_writes` are per-store
  by construction and making them per-account means the reserve-then-commit
  redesign anyway.

## Related

- ADR-0002 (SQLite single-writer ceiling — the constraint this sits on)
- Issues #101, #109, #122, #123
- `src/product_app/store_reconnect.py`, `src/product_app/costs.py`
- Tests: `tests/unit/test_stale_ledger_spend_policy.py`,
  `tests/integration/test_stale_ledger_block_on_a_real_volume.py`
- `docs/24-adr-index.md` needs an entry for this ADR.
