# W86 failure modes: delete old signed-in history for every account, and turn on `secure_delete`

**Outcome (W86, ADR-0172):** the build closed F1-F6, F10-F13, F15, F16, F19, F20, F25 and F26 (F8, F9 and F24 needed no code); F7, F14, F17, F18, F21, F22 and F23 are recorded as limits in ADR-0172. Line numbers below are those of `main` at `a2af06c`, before the change.

Role: FAILURE-MODES, read-only. Tree: main checkout at `a2af06c`, `git status` clean before and after.
Probes ran from a scratch folder with `PYTHONDONTWRITEBYTECODE=1` and temporary databases; the folder is deleted.
One Docker image (`python:3.12-slim`) was pulled to measure its SQLite build and then removed (`docker rmi`, it printed `Deleted: sha256:a6e3…`).
Labels: MEASURED = a probe in this session printed it. READ = read in the code or docs at the cited line. INHERITED = taken from an ADR, not re-run. UNVERIFIED = not checked.

## 0. What the code does today (READ)

- `record_history` deletes old rows for the saving account only: `DELETE FROM history WHERE account_id = ? AND completed_at < ?` (`src/product_app/session_store.py:701-704`). The count delete is per account too (`:705-710`). Both run inside the write's `BEGIN IMMEDIATE` (`:671`).
- `history_for` filters on read: `completed_at >= cutoff ... LIMIT keep_count` (`:733-737`). So an old row is hidden but stays on disk.
- The keep values come from settings: `history_keep_count = 5` (`ge=1, le=50`) and `history_keep_days = 30` (`ge=1, le=365`) (`src/product_app/config.py:832-833`). `account_history._write` passes them, with wall-clock `now` (`src/product_app/account_history.py:81-85`).
- The connection is opened with no pragma at all: `sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)` (`session_store.py:392-396`). So it uses the default busy timeout (5 s), `journal_mode=delete`, `auto_vacuum=0` (MEASURED on a fresh store), and the build's default `secure_delete`.
- An existing periodic sweep: the `session-gc` daemon thread. It starts at **import of `auth`** (`src/product_app/auth.py:713`), runs `_gc_tick` every `SESSION_GC_INTERVAL_S = 60.0` (`auth.py:681`, `:700-710`), and calls `session_repository.purge_expired()`. That deletes expired session rows from the durable store (`auth.py:513-527` → `session_store.py:792-819`). `_gc_tick` catches and logs every exception, so the thread never dies (`auth.py:684-697`). Tests: `tests/security/test_durable_session_store.py:366` (survives a raise) and `:391` (really purges).
- The session store opens once, at `main` import (`src/product_app/main.py:819`). `store_reconnect.py` never reopens it (`grep session_store src/product_app/store_reconnect.py` printed nothing). So "at open" means "at process start".
- The model to copy is ADR-0165 (W55, `feedback_store.py`). It turns on `PRAGMA secure_delete = ON` as the open's first statement (`feedback_store.py:549`) and runs one `VACUUM` per file, marked in `schema_migrations` (`:813-858`). The pass runs at open, plus a throttled pass on writes at most once per `IDENTIFIER_WIPE_INTERVAL = 1 h` (`:321`, `:1218-1229`). Each trigger goes through a guard that never raises (`:1231-1241`).
- `fly.toml` sets one machine (`min_machines_running = 0`, `auto_stop_machines = "stop"`), `strategy = "rolling"`, `auto_rollback = true` and a 1 GB volume at `/data`. The Dockerfile runs `uvicorn ... --workers 1` (`Dockerfile:89-92`). The runtime stage is `FROM python:3.12-slim` by tag, with no digest (`Dockerfile:39`).

## 1. Where and when the sweep runs

**F1. A write-path-only fix leaves the same bug in place.** If `record_history` simply drops `account_id = ?` from its age delete, every account is swept, but only when *someone* saves. Trigger: no signed-in user finishes a run for 31+ days, or sign-in is unused, which is likely at today's traffic. Test: two accounts; A has a 31-day row and never writes again; call the sweep entry point with no write at all; count A's rows with a raw `SELECT COUNT(*)` on a second connection. Design: keep the write-path delete (it is free), but do not let it be the only trigger.

**F2. A timer alone misses a stopped machine.** ADR-0165 rejected a timer for this reason (INHERITED, ADR-0165 "Rejected alternatives"). Here the timer already exists (`session-gc`), so it adds no new machinery. Design (recommended):
(a) `SessionStore.sweep_history(*, keep_count, keep_days, now) -> (age_deleted, count_deleted)`, a store method that takes `now` as an argument;
(b) call it once in `__init__` after `_migrate_history` (covers every start, deploy, `auto_rollback` and snapshot restore);
(c) call it from `_gc_tick`, throttled on a monotonic clock to once an hour like `IDENTIFIER_WIPE_INTERVAL`, in its **own** `try` block after `purge_expired`.
Remaining bound: while the machine is stopped, nothing runs, so a row can sit past 30 days until the next start. Reads already hide it. State this bound in `docs/48` as ADR-0165 did. Test: open a store on a file seeded with a 31-day row and assert 0 rows after `__init__`; call `_gc_tick` twice inside the hour and assert the sweep ran exactly once (cardinality).

**F3. One raising purge also skips the sweep.** If the sweep shares `_gc_tick`'s single `try` with `purge_expired`, a raise in the purge skips it on every tick. `test_the_gc_daemon_survives_a_purge_that_raises` (`tests/security/test_durable_session_store.py:366`) replaces `session_repository` with a fake that has only `purge_expired`. A sweep reached through `session_repository` would hit `AttributeError`, the broad `except` would swallow it, and that test would stay green while the sweep never runs. Design: call `session_store.get_store()` directly (resolved at call time, as `session_store.py:1179-1186` requires), in a separate `try`. Test: the purge raises, and the sweep still deletes a due row.

**F4. The sweep is on the wrong clock.** `tests/unit/test_account_history_store.py` uses a fixed `NOW = 2026-09-26` (`:20`) and passes `now=NOW`. A sweep inside `record_history` that reads `datetime.now(UTC)` would delete the test's "29.9 days old" row: by wall-clock time it is already about 51 days old today. That turns `test_rows_older_than_30_days_are_dropped_and_never_shown` (`:136`) red now, and every fixed-date test into a time bomb. Design: every sweep takes `now`; only the callers (`_gc_tick`, `__init__`, `account_history`) read the clock.

**F5. The daemon thread races tests.** The thread starts at import in every test process, and the global store is `:memory:` (`tests/conftest.py:62`). Any integration test that seeds a past-30-day row into the global store, and expects it still on disk before the code under test removes it, would flake about once a minute. Worse, the race could satisfy a deletion test with no code under test running at all (a vacuous pass). Design: tests drive `_gc_tick` or `sweep_history` directly; deletion tests count the row before (positive partner, rule 7). The daemon's throttle stamp must be resettable, or tests pin it through the tick.

**F6. A sweep on the hot read path.** Putting the delete in `history_for` makes every History open a write. That breaks the rule `auth.py:518-520` records ("must stay free of writes"). Reject.

## 2. Several machines, restarts, second writers

**F7. A second process writes the same file.** There is one machine and one worker (READ). But any process that imports `product_app.auth` against `/data/sessions.sqlite3` (for example an operator's `python` under `fly ssh console`) starts its own `session-gc` and, after this change, its own open-time sweep. That makes two writers, which ADR-0002 forbids (INHERITED). The session purge already has this exposure (READ). Design: document it in the runbook; no code answer is proportionate.

**F8. Rolling deploy and auto-rollback.** During a rolling deploy, whether old and new machines ever run at once on one volume is UNVERIFIED in the repo (a Fly volume attaches to one machine; the repo does not record this). Rollback matters for count (see F11). A kill in the middle of a sweep is safe: one transaction, and the hot journal rolls back at the next open (SQLite's documented behaviour; not re-measured).

**F9. Close during a sweep.** `close()` takes the lock with a 5 s bound and then closes the connection anyway (`session_store.py:1133-1147`). A sweep still running at exit would have its connection closed under it. A realistic pass takes milliseconds (F10), so the risk is low. No test is needed beyond keeping the pass short.

## 3. Lock contention and latency (single writer, ADR-0002)

**F10. Cost under the store lock.** Every store call (`fetch` on restore `auth.py:533`, `spend_key_for` on every metered estimate or run `auth.py:1028`, `account_for` `main.py:1134`) waits on the same `RLock` (`session_store.py:390`). MEASURED (SQLite 3.50.4, macOS, load average about 12), with 100,000 history rows over 20,000 accounts:

| Pass | Time |
|---|---|
| First age sweep, deleting 66,763 rows, `secure_delete` off | 116 ms |
| Same, `secure_delete` on | 297 ms |
| Nothing due (full `SCAN history`; the index leads with `account_id`) | 2.7-2.9 ms |
| All-accounts count sweep (`ROW_NUMBER() OVER (PARTITION BY account_id ...)`), nothing over the limit | 22-26 ms |
| Same, with the limit lowered from 5 to 2 (5,125 rows deleted) | 100-104 ms |
| Orphan sweep (`NOT EXISTS accounts`) | 6 ms |

A realistic file (300 accounts × 5 rows) sweeps in about 2 ms. Fly's shared CPU is slower by an UNVERIFIED amount. Design: an hourly throttle, not every 60 s. Check for due rows with a read before any write, as ADR-0165 does ("when no row is due it writes nothing"). No new `completed_at` index: it would be a schema change needing a guarded migration (`session_store.py:283-286`), and the measured scan is cheap.

**F11. An outside reader stalls every request for 5 s.** MEASURED: while a second connection held a read transaction, the sweep's `COMMIT` waited 5.22 s holding the store lock, then raised `database is locked`, and the row stayed. During those 5 s every session restore and spend-key read waits. `record_history` already has this exposure. Design: catch the error, log one WARNING, do not retry inside the tick; the production check must use one autocommit `mode=ro` statement per count (ADR-0165, inherited).

## 4. The age boundary and the time format

**F12. `<` against `<=`.** The read keeps `completed_at >= cutoff` (`:734`) and the write deletes `< cutoff` (`:702`): exact complements, so a row of exactly 30 days is shown and kept. "None completed more than 30 days ago" (`docs/48-data-retention.md:12`) means older than 30 days goes, which matches `<`. The sweep must use the same `<` and the same `cutoff = _to_utc(now) - timedelta(days=keep_days)` (`:666`), from `settings.history_keep_days`, never a literal 30. If it used `<=`, or a hard-coded 30 while the setting says otherwise, it would disagree with the read. Test: literals on both sides at the exact instant (a row exactly at the cut stays; one microsecond older goes), with a whole-second stamp and one with a fraction, as `test_the_cut_is_exact_for_whole_second_stamps_and_cuts` does for W55.

**F13. The stored format.** MEASURED: `_to_utc(...).isoformat()` stores `2026-09-17T12:00:00+00:00`, or `...12:00:00.000500+00:00` when there are microseconds. Text comparison is correct across both shapes (`+` sorts before `.`, MEASURED `True`). A `+05:30` value is normalised before storing (MEASURED). A naive value is taken as UTC (`session_store.py:175-178`). All UTC, so time zones and daylight saving do not apply; `timedelta(days=30)` is exactly 720 hours. Only an operator's hand-written row (a `Z` suffix, another offset, garbage text) compares wrongly. Garbage text sorts after digits, is never deleted, and `history_for` would then raise `ValueError` outside its `try` (`:741-754`). That fault exists today, and W86 is not required to fix it. Optional: the `julianday` fallback from ADR-0165.

**F14. Clock steps.** A forward step of N days at a sweep deletes rows N days early, and that cannot be undone. That is the "keep less" direction, and the write path already has it. A row stamped in the future (written while the clock was ahead) is never due, is listed first, and is protected by the count rule forever. `purge_expired` deletes both ends for this reason (`session_store.py:804-814`). Whether history should do the same is a design choice outside the owner's words: mark it a session proposal if built.

## 5. The count limit, deleted accounts, orphans

**F15. The count rule also matters for idle accounts.** Every write holds an account to 5 rows, so an idle account exceeds 5 only if the setting goes down. That happens when `HISTORY_KEEP_COUNT` is lowered, or when `auto_rollback = true` or a revert follows CHG-026 (i)'s planned 20. Reads hide the extra rows with `LIMIT`, but they stay on disk. Design: the sweep applies the count rule to all accounts in the same transaction (measured at 22 ms with nothing due). Test: an idle account with 7 rows and `keep_count=5` ends with exactly 5, the newest.

**F16. Tie-break drift.** The per-account delete orders by `completed_at DESC` with no tie-break (`:708`); so does the read (`:735`). A sweep with a different tie-break could keep a different row from the one the write path keeps, for equal timestamps. Design: one ordering, `completed_at DESC, query_run_id DESC`, in all three places.

**F17. Deleted accounts and orphans.** `delete_account` removes history in its own transaction (`:975-989`), and `record_history` refuses an absent account (`:682`). So orphans come only from hand edits or restores. An age sweep with no account filter removes them after 30 days anyway. An explicit orphan delete (6 ms measured) would remove them at once: that is a design choice, not owner-approved wording. Note: `secure_delete` also makes account deletion actually remove the email and Google subject bytes from the file. Today those bytes stay in free pages wherever the build default is off.

**F18. Sign-in events have the same pattern, and their documented rule allows it.** `record_sign_in_event` prunes only the saving account (`session_store.py:608-616`). But `docs/48-data-retention.md:16` says "none older than 30 days as of the account's next event (an account with no later event keeps its rows until it is deleted)". Sweeping them would change approved text, so do not widen W86 silently; ask the owner, or record it as a follow-up. The tests that seed old events, `tests/integration/test_session_safety.py:483` and `:755`, would race the daemon if events were swept.

## 6. `secure_delete`, free pages, journals, backups

**F19. It is per connection, so it must be the first statement.** MEASURED: after `PRAGMA secure_delete=ON` on the store's connection, a second connection to the same file reads `0`. MEASURED: residue of deleted questions in the file after 3,600 writes through `record_history` and a sweep of 300 accounts: **614** copies with it off; **25** with it on only for the sweep (copies left by earlier write-path deletes and page splits); **0** with it on for the whole connection from open. Design: first statement in `__init__`, before `executescript(_SCHEMA)`, as in `feedback_store.py:549`; nothing turns it off. Test: read `PRAGMA secure_delete` on `store._conn` and expect `1` (pin the literal). Also pin a byte-scan of the file after a delete, in both directions: copies exist with the pragma removed, and none with it. Use `ON`, not `FAST`. MEASURED: `FAST` reads back `2`, and SQLite's documentation says FAST leaves traces on freelist pages. The pragma is accepted on a read-only file (MEASURED: `ro` connection reads back `1`).

**F20. Old free pages already hold deleted text.** Space freed before this change keeps its bytes wherever the build default was off. MEASURED: a `VACUUM` took a file with 614 copies to 0 (3 ms for 450 KB). Design: one `VACUUM` per file in `__init__`, marked in `schema_migrations` (the W55 pattern). It never raises: on a read-only file it fails (MEASURED: `attempt to write a readonly database`), logs INFO and is retried at the next open. It needs free disk about the size of the file, and the volume is 1 GB. The existing read-only open tests guard this: `tests/security/test_durable_session_store.py:201-235`, `tests/integration/test_google_sign_in.py:857` and `:1006`, `tests/integration/test_spend_key.py:372`.

**F21. Production's build already deletes securely by default, probably.** MEASURED today, on the `python:3.12-slim` tag (Debian 13 trixie, Python 3.12.15): SQLite 3.46.1, `compile_options` includes `SECURE_DELETE`, and `PRAGMA secure_delete` defaults to `1`. MEASURED locally (the repo `.venv`, Python 3.12.13, SQLite 3.50.4): default `0`, with no `SECURE_DELETE` option. So:
(a) the pragma still matters: the image is pulled by tag, not digest, and the local build defaults to off (CI's default is UNVERIFIED: not measured);
(b) the mutation test (remove the pragma) bites locally, but not inside the production image; whether it bites in CI is UNVERIFIED;
(c) what the image running in production actually reports is UNVERIFIED. The free check is `fly ssh console -C "python3 -c 'import sqlite3;c=sqlite3.connect(\":memory:\");print(sqlite3.sqlite_version,c.execute(\"PRAGMA secure_delete\").fetchone())'"`.
If it reads 1, the old free pages in production are probably already clean, and the `VACUUM` is insurance.

**F22. The rollback journal.** MEASURED: in the middle of a delete transaction, `-journal` holds the deleted question text; after commit the journal file is gone and the database holds no copy. The journal's freed disk blocks are not overwritten, so text may survive at the filesystem level until the blocks are reused. That is not fixable with a pragma (TRUNCATE and PERSIST do not zero the content; WAL is rejected by ADR-0002). Record it as a limit, as ADR-0165 FM 30 did.

**F23. Snapshots.** Fly volume snapshots keep copies taken before the sweep. Their retention is UNVERIFIED: no file in the repo records it (`grep -rn snapshot docs/runbooks` names it UNVERIFIED in `feedback-store-schema-migration.md:800`). The free check is `fly volumes snapshots list <id>`. A restored snapshot is swept at its first open (F2 b).

**F24. Other stores holding question text.**
- The run-history store has no question column (`grep -n "query_text\|question" src/product_app/run_history_store.py` printed nothing).
- `feedback_store.py` has no `query_text` (grep printed nothing).
- The in-memory run store keeps the text for an hour after a run ends (`QUERY_RUN_TERMINAL_TTL`, `query_run_orchestration.py:143`).
- That no other durable store holds question text is INHERITED from ADR-0135's Context, not re-measured across telemetry JSONL, logs or Sentry. The general "Query text" row in `docs/48` (`:11`) is still "Pending approval".

## 7. Observability, existing tests and gates

**F25. What to show, and what not to.** `/metrics` carries only the HTTP instrumentator (`main.py:36`, `:668`); no app counter exists (no prometheus `Counter(` in `src/`). The comment in `fly.toml` saying there is no `/metrics` is stale (READ). Design: one INFO log line with the two counts when a pass deletes anything, and one WARNING on failure, carrying the SQLite reason only, never a question or account id. On a read-only volume, do not log a WARNING every tick (1,440 a day, as `auth.py:689-692` warns): check with a read first, and log a failure at most once an hour. Return the counts so tests assert cardinality (rule 6b).
Production check after deploy (free, `mode=ro`, one autocommit statement each): `SELECT COUNT(*) FROM history WHERE completed_at < <now-30d>` should read 0; the partner, `SELECT COUNT(*) FROM history`, shows rows exist; and `PRAGMA secure_delete` on a store connection. The INFO line of the open-time pass in `fly logs` gives the first counts.

**F26. Tests that pin today's behaviour, or will catch the change.**
- `tests/unit/test_account_history_store.py::test_pruning_one_account_leaves_another_alone` (`:165`): it stays green, but its docstring ("keep rules reach across accounts") becomes half wrong. The age rule now does; only the count must not.
- `::test_rows_older_than_30_days_are_dropped_and_never_shown` (`:136`): see F4.
- `tests/unit/test_risk_constant_pins.py::test_every_risk_constant_is_triaged` (`:1578`): class SQL constants in `session_store` are triaged too (`:855-860`). A new interval constant or SQL constant needs an entry, and a pinned literal for the interval (as `test_the_identifier_keep_and_wipe_interval_are_pinned` does, `:1482`).
- The GC tests at `test_durable_session_store.py:366` and `:391`: see F3.
- The read-only open tests in F20.

## Recommended design, in one paragraph

Turn on `PRAGMA secure_delete = ON` as the first statement of `SessionStore.__init__`. Add one marker-guarded `VACUUM` per file. Add `sweep_history(keep_count, keep_days, now)`: a read first; then, only if something is due, one `BEGIN IMMEDIATE` holding the all-accounts age delete (`completed_at < cutoff`, the exact complement of the read) and the all-accounts count delete (one shared tie-break). It returns both counts and never raises. Run it at open, and from the existing `session-gc` tick throttled to once an hour, in its own `try`. Keep the per-account write-path delete. Leave sign-in events to the owner (F18). In `docs/48` state the bound: about an hour after 30 days while running, until the next start while stopped, and snapshots UNVERIFIED.
