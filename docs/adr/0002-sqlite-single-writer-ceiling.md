# ADR-0002: SQLite stores stay single-writer (one connection, one lock, no WAL)

## Status

Accepted — 2026-07-19 (R2 Phase 0, ledger RB-3)

## Context

Two durable stores back Release 2's trust & evaluation surfaces:

- `src/product_app/feedback_store.py` — append-only audit event sink.
- `src/product_app/run_history_store.py` — one row per terminal query run (FR-014).

Both use the same shape: **one** `sqlite3.Connection` opened with
`check_same_thread=False` and `isolation_level=None` (autocommit), guarded by
**one** `threading.RLock`, in the default `journal_mode=DELETE`. Every statement
from every request thread is therefore serialised through a single lock and a
single connection. That is a single-writer design, and until now it was an
undocumented accident of the original implementation rather than a decision.

Two questions had to be answered with data before it could be called a decision:

1. Is the single-writer ceiling anywhere near the load we actually put on it?
2. Does contention break *correctness* (lost writes, `database is locked`,
   torn rows), which would make it a bug rather than a capacity limit?

A third issue surfaced alongside: neither store was ever closed. The suite
emitted `ResourceWarning: unclosed database` four times at teardown — the two
singletons built at `product_app.main` import, plus the two displaced when
`tests/unit/test_sentry_init.py` reloads `main`.

## Decision

**Keep the single-writer design. Do not switch to WAL, per-thread connections,
or a connection pool.** Revisit only when a measurement shows the ceiling is
being approached, or when the deployment stops being single-instance.

Fix the lifecycle instead:

- `close()` is idempotent (`_closed` flag) and de-registers the store.
- Each store registers itself in a module-level `weakref.WeakSet`; an
  `atexit`-registered `_close_open_stores()` closes whatever is still open at
  process exit — this covers the long-lived singleton nothing else ever closed.
- `__del__` closes best-effort, covering a store dropped without `close()`
  (a displaced singleton, a helper that forgot teardown).

**`configure()` deliberately does NOT close the store it displaces.** Callers
such as `tests/security/test_operations_info_leak.py` stash the live store,
install their own, and `configure(original)` it back; closing on displacement
would hand them a dead connection. The `WeakSet` + `atexit` + `__del__` trio
covers the displaced store without that hazard.

## Measurements (2026-07-19, macOS/darwin 25.5.0, Python 3.13, local APFS SSD)

Contention benchmark: 256 upserts into `RunHistoryStore` on a file-backed
temp DB, threads released together from a `threading.Barrier`, median of 5 runs
(`scratchpad/measure_and_mutant.py`, reproduced by `tests/test_store_concurrency.py`):

| threads | median wall | throughput | per-write |
|--------:|------------:|-----------:|----------:|
| 1  | 56.0 ms | 4 574 writes/s | 0.219 ms |
| 2  | 68.8 ms | 3 723 writes/s | 0.269 ms |
| 8  | 57.2 ms | 4 477 writes/s | 0.223 ms |
| 32 | 57.4 ms | 4 461 writes/s | 0.224 ms |
| 64 | 56.4 ms | 4 542 writes/s | 0.220 ms |

`FeedbackStore` at 32 threads: 256 events in 60.6 ms → **4 223 writes/s**.

The curve is **flat**: throughput is the single writer's, and adding threads
neither helps nor (materially) hurts. That is the ceiling, and it is ~4 500
writes/s per store.

Journal-mode comparison (same harness, synthetic 200-byte rows, one connection
+ one lock, median of 5):

| journal_mode | 1 thread | 32 threads |
|---|---:|---:|
| DELETE (current) | 4 973 writes/s | 4 987 writes/s |
| WAL | 24 711 writes/s | 18 148 writes/s |

WAL is ~4–5× faster on this synthetic. It is still **not** adopted: the
measured demand is nowhere near the ceiling (below), WAL adds sidecar
`-wal`/`-shm` files on the Fly volume and a checkpoint/`fsync` durability
profile that has not been validated against a Fly machine restart, and the
readers here are a nightly audit job, not a concurrent read fleet. The number is
recorded so a future change is a decision with data behind it, not a guess.

### Headroom against real demand

One query run writes ~15 feedback events + 1 run-history row, over a workflow
whose NFR budget is P50 ≤ 45 s / P95 ≤ 120 s (docs/11 NFR-001). That is well
under **1 write/s per concurrent run**. At the measured ~4 500 writes/s ceiling
the stores have roughly three orders of magnitude of headroom. The single
writer is not, and is not close to being, the bottleneck.

### Correctness under contention

`tests/test_store_concurrency.py` (32 threads, 256 writes per store) asserts and
passes: no lost writes, no duplicate/merged rows, monotonic AUTOINCREMENT ids,
no `database is locked`, no crossed fields between writers, and a correct
`ON CONFLICT` collapse when every thread upserts the same `query_run_id`.
10/10 runs green, in both fixed and random test order.

The tests bite. Mutating `record_terminal_run` into the "obvious" scaling change
(a fresh per-thread connection, `timeout=0`, still no WAL) produced **240
`sqlite3.OperationalError: database is locked` and 240 lost writes out of 256**,
and failed 3 of the 4 concurrency tests. That mutant is precisely why the
single-connection design is kept.

## Consequences

- The stores are safe to call from any request thread; the lock, not the
  caller, provides the serialisation.
- Throughput is capped at one writer (~4 500 writes/s measured). A future
  workload that approaches it — bulk backfill, evaluation replay over history —
  must re-measure before assuming this ADR still holds.
- **Multi-instance deployment is still out of scope** (as `fly.toml` already
  documents). Two Fly machines sharing a volume would break this design; that
  path needs fly-postgres, not a journal-mode change.
- No `ResourceWarning: unclosed database` remains in the suite (4 → 0, verified
  with `python -X dev -m pytest tests/`).

## Rejected alternatives

- **WAL journal mode** — measured 4–5× faster, rejected for now: unvalidated
  durability/checkpoint behaviour on the Fly volume and no demand for the
  throughput. Locked as "do not change without measuring"; this ADR is the
  measurement, and it says *not yet*.
- **Per-thread connections / a pool** — empirically worse without WAL: 94 % of
  writes lost to `database is locked` in the mutant run above.
- **Closing the displaced store inside `configure()`** — breaks the
  save-and-restore idiom used by existing tests; see Decision.

## Related

- Ledger item RB-3 (`docs/analysis/R2-plan-review-findings.md`)
- Tests: `tests/test_store_lifecycle.py`, `tests/test_store_concurrency.py`
- `docs/24-adr-index.md` needs an entry for this ADR (owned elsewhere).
