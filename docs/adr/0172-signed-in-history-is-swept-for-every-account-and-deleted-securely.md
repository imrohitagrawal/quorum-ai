# ADR-0172: Signed-in history is swept for every account, at every open and hourly, and the session store deletes securely

## Status

Accepted — 2026-10-18, board row W86. The keep rule itself is the product owner's (CHG-023,
`docs/48-data-retention.md`: at most `history_keep_count` (5) questions per account, none completed
more than `history_keep_days` (30) days ago). No new owner decision was needed: this change makes the
code meet the approved rule. Everything below about how and when it is met is the session's design.
The failure modes were listed before any code
(`docs/analysis/2026-10-17-w86-history-sweep-failure-modes.md`, findings F1 to F26). Codex reviewed
the plan before any code (ADR-0168, decision 7). Every Codex finding and figure in this record comes
from the Codex plan reviews of this session, which are kept outside the repository; none has a
committed record. By those reviews, Codex found four problems; the plan was revised, and a
second pass confirmed three of them closed, held the fourth (the daemon racing tests) open, and raised
one more (an interval setting). Both are answered below (decision 6 and the rejected alternatives);
Codex did not review those answers again.

## Context

Before W86, `SessionStore.record_history` deleted old rows only for the account that was saving
(`DELETE FROM history WHERE account_id = ? AND completed_at < ?`, and a per-account count delete).
`history_for` hid older rows on read, so the page was right, but an account that stopped using the
site kept its old questions in the file for ever, against the approved rule (CHG-023).

The session store also never set `PRAGMA secure_delete`. On this repository's local SQLite (the
`.venv`: Python 3.12.13, SQLite 3.50.4) the default is off; CI's default is UNVERIFIED (nobody has
read it there). Where it is off, a deleted row's bytes stay in the page's free space, readable by
anyone who holds the file. The feedback store has had it on since W55 (ADR-0165).

## Measured

All figures are the failure-modes role's measurements (F10, F11, F19, F20, F21 in the failure-modes
file), taken on 2026-10-17 with temporary databases, except the busy-timeout probe, which is from
Codex's plan review of this session (kept outside the repository). Local: SQLite 3.50.4, Python
3.12.13, macOS, load average about 12.

| What | Figure |
|---|---|
| Sweep with nothing due, 100,000 rows over 20,000 accounts (a full `SCAN history`) | 2.7-2.9 ms |
| First age sweep deleting 66,763 of those rows, `secure_delete` off / on | 116 ms / 297 ms |
| All-accounts count sweep (`ROW_NUMBER() OVER (PARTITION BY account_id ...)`), nothing over the limit | 22-26 ms |
| The same with the limit lowered from 5 to 2 (5,125 rows deleted) | 100-104 ms |
| A realistic file (300 accounts x 5 rows) | about 2 ms |
| A sweep's `COMMIT` while another connection holds a read transaction (default 5 s busy timeout) | waited 5.22 s, then `database is locked`; nothing deleted (F11) |
| Statements run with a 1 ms busy timeout | 213 ms (Codex's plan review; no committed record): the busy timeout bounds neither run time nor the store's lock |
| Copies of deleted questions left in the file after 3,600 writes and a sweep of 300 accounts | 614 with `secure_delete` off; 25 with it on only for the sweep; 0 with it on from open (F19) |
| `secure_delete` set on one connection, read on a second connection to the same file | `0`: the setting is per connection (F19) |
| `PRAGMA secure_delete = FAST` read back | `2`; SQLite's documentation says FAST leaves traces on freelist pages (F19) |
| `VACUUM` on the 614-copy file | 0 copies after, 3 ms for 450 KB (F20) |
| `VACUUM` on a read-only file | `attempt to write a readonly database` (F20) |
| `PRAGMA secure_delete` default on the `python:3.12-slim` tag (Debian 13, Python 3.12.15, SQLite 3.46.1) | `1`, with `SECURE_DELETE` in `compile_options` (F21) |
| The same default in the repository's `.venv` (SQLite 3.50.4) | `0`, no `SECURE_DELETE` option (F21) |

## Decision

1. **`SessionStore.sweep_history(*, keep_count, keep_days, now) -> (aged, over_count)`** applies the
   keep rule to every account. The cut is `_to_utc(now) - timedelta(days=keep_days)`, the same
   expression `record_history` and `history_for` use, and rows strictly before it go (the exact
   complement of the read's `>=`). Then every row past an account's newest `keep_count` goes. It has
   no account filter, so a row whose account is gone is aged out like any other. It takes `now` as an
   argument; only its callers read the clock.
2. **A read first.** When no row is due, the sweep writes nothing (no `BEGIN`, no `DELETE`).
   Otherwise both deletes run in one `BEGIN IMMEDIATE` transaction.
3. **It never raises.** On any `sqlite3.Error` it rolls back an open transaction (a failed `COMMIT`
   leaves one open, and the next `BEGIN` would fail; Codex's plan review), logs one WARNING carrying
   only SQLite's reason, never a question or an account id, and returns `(0, 0)`. When it deletes
   anything it logs one INFO line with the two counts. No time bound is claimed (table, Codex row).
4. **One order everywhere: `completed_at DESC, query_run_id DESC`**, in `record_history`'s count
   delete, `history_for`'s read and the sweep, so for equal timestamps the rows kept are the rows
   shown (F16).
5. **It runs at every open of the store** (in `__init__`, after the migrations), with the wall clock
   and the settings' values. That covers every start, deploy, rollback and restored snapshot.
6. **And from the `session-gc` daemon at most once an hour**, `HISTORY_SWEEP_INTERVAL_S = 3600.0` in
   `auth.py`, on the monotonic clock. The sweep is in its own `try` after the session purge, so a
   purge that raises cannot skip it, and it reaches the store through `session_store.get_store()` at
   call time, not through `session_repository` (F3). The throttle state is a `HistorySweepState`
   stamped when it is made, so the daemon's first sweep is due an hour after import. When the app
   starts, `main.py` imports `auth` (the stamp) before it opens the store (the open-time sweep), so that is
   a little under an hour after the open-time sweep. Tests pass their own state and an injected
   monotonic time to `_gc_tick` (F5; Codex's re-check showed that resetting a shared stamp would make
   the real daemon due at once), and `tests/conftest.py` holds the daemon's own state never due for
   the whole run, so a run that lasts hours cannot have the daemon sweep a store a test installed. The stamp moves before the sweep, so a failing sweep (a read-only
   volume) is retried an hour later, not every minute.
7. **The write-path deletes stay** (F1). They are free, and they keep a saving account within the
   rule between sweeps.
8. **`PRAGMA secure_delete = ON` is the store connection's first statement**, before the schema and
   the migrations, and nothing turns it off. `ON`, not `FAST`. It is set in code although the
   production image's tag already defaults to `1`, because the image is pulled by tag, not digest,
   and the local `.venv` defaults to `0` (F21; CI's default is UNVERIFIED).
9. **One `VACUUM` per file**, recorded in `schema_migrations` under `w86_secure_delete_vacuum`
   (`SECURE_DELETE_VACUUM_MARKER`), the W55 pattern (ADR-0165). It cleans space freed before W86. It
   is skipped for an in-memory database. It never raises: on a read-only, locked or full volume it
   logs INFO, writes no marker and is tried again at the next open.

## Rejected alternatives

- **Drop the account filter from `record_history`'s delete and stop there.** Every account would be
  swept, but only when someone saves a question. With no signed-in traffic for 30 days, nothing runs
  (F1).
- **A timer-only sweep.** A stopped machine runs no thread: `fly.toml` sets
  `auto_stop_machines = "stop"` and `min_machines_running = 0`. ADR-0165 rejected a timer for the same
  reason. Here the timer is the existing `session-gc` daemon, added to, not a new thread, and the
  open-time sweep covers the stopped machine's next start (F2).
- **A sweep on the read path** (`history_for`). It would make every History open a write, against the
  rule `auth.SessionRepository.purge_expired` records that the hot path stays free of writes (F6).
- **An interval setting** (Codex's second plan review). The repository's precedent for this kind of
  throttle is a module constant: ADR-0165's `IDENTIFIER_WIPE_INTERVAL`, pinned by a literal test in
  `tests/unit/test_risk_constant_pins.py`; this one is pinned the same way. Codex cited a rule that
  configuration must hold tunable intervals; a search of the repository (`git grep -i "tunable"`, 25
  lines in 15 files besides this record) found no rule that an interval must be a setting. A
  setting would add an operator knob nobody has asked for, and a longer value would keep questions
  longer than the approved rule (CHG-023) allows.
- **A sweep on every 60-second tick.** It holds the store lock every session restore and spend-key
  read waits on, for 2 ms to about 300 ms (table). Hourly keeps that rare.
- **`secure_delete` on only for the sweep.** It left 25 copies where on-from-open left 0 (F19).
- **`secure_delete = FAST`.** Leaves traces on freelist pages (F19).
- **A new index on `completed_at`.** A schema change needing a guarded migration, for a scan measured
  at about 3 ms on 100,000 rows (F10).
- **An explicit orphan delete.** Rows of a deleted account come only from hand edits or restores, and
  the age sweep removes them after 30 days anyway. Deleting them at once was not in the owner's words
  (F17).

## Consequences

- An idle account's questions now leave the file within about an hour after their 30 days while the
  app runs, and at the next start when it was stopped. `docs/48-data-retention.md` says so in the
  signed-in history row.
- Account deletion and every other delete in the session store now zero the freed bytes, including
  the email and Google subject of a deleted account (F17).
- The list of security measures gains SC-100 (the sweep) and SC-101 (`secure_delete` and the
  `VACUUM`) in `docs/41-security-controls.md`; the history half of SC-80's gap is closed (its other
  gaps, outside W86, keep it PARTIAL).
- Every store file gains one `schema_migrations` row, `w86_secure_delete_vacuum`.

## Limits, recorded and not built

- **F14, rows dated in the future.** A row stamped while the clock was ahead is never aged out, and
  the count rule keeps it as the newest. `purge_expired` deletes both ends for sessions; doing the
  same for history is a design choice outside the owner's words.
- **F17, orphan rows** stay until their 30 days, as above.
- **F18, sign-in events** are still pruned per account, at that account's next event.
  `docs/48-data-retention.md` approves exactly that ("none older than 30 days as of the account's
  next event (an account with no later event keeps its rows until it is deleted)"), so changing it is
  the owner's decision, not this change's.
- **F22, the rollback journal.** During a delete transaction the `-journal` file holds the deleted
  text. After the commit the file is gone, but its disk blocks are not overwritten, so the text may
  survive at the filesystem level until they are reused. No pragma fixes this; WAL is ruled out by
  ADR-0002.
- **F23, Fly volume snapshots** keep copies taken before a sweep. How long Fly keeps them is
  UNVERIFIED (`fly volumes snapshots list <id>` would settle it). A restored snapshot is swept at its
  first open.
- **F21, production's own default.** What the running image reports for `PRAGMA secure_delete` is
  UNVERIFIED; the tag measured `1`. If it is `1`, the byte test's mutation (removing the pragma)
  would not bite inside that image. It bites locally, where the default is `0`; whether it bites in
  CI depends on CI's SQLite default, which is UNVERIFIED.
- **A rollback to an older writer, then forward again.** W86, then a build without
  `secure_delete`, then W86 again leaves one copy of a question that the older build pruned: its
  delete does not zero the bytes, and the `VACUUM` does not run again because its marker survives in
  `schema_migrations` (Codex reproduced this in its review of this session; no committed record).
  Production's image tag (`python:3.12-slim`) defaults `secure_delete` to `1` (F21), so a rollback
  there writes securely too; what the running machine reports is UNVERIFIED, as above.
- **F7, a second process.** Any process that imports `product_app.auth` against the production file
  (an operator's `python` under `fly ssh console`) starts its own daemon and its own open-time sweep:
  two writers, which ADR-0002 forbids. The session purge already has this exposure. No code answer is
  proportionate; the runbook is where it belongs.
- **No time bound.** A first sweep of a large backlog holds the store lock for as long as it takes
  (297 ms measured for 66,763 rows locally; Fly's shared CPU is slower by an UNVERIFIED amount).
