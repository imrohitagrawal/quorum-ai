# ADR-0165: Ledger keys and session addresses are wiped after 48 hours

## Status

Accepted — 2026-10-14. The keep time and its scope are the owner's: CHG-033 (c) chose 48 hours
for an anonymous network's key in the cost ledger, CHG-044 (a) widened it to every cost-ledger
row, signed-in and anonymous alike, and CHG-044 (b) added the visitor's address in session rows
(board row W55). The design below (the method, its three triggers, the one-hour throttle,
`secure_delete`, the one-shot `VACUUM`, "never raises", the trigger outside the money lock) is
the session's. So is wiping `invite:<link id>` mint keys along with addresses: the owner was
asked about raw IP addresses (CHG-044 (b)), and an invite key sits in the same `"ip"` field.

## Context

`src/product_app/feedback_store.py` keeps one `events` table. Until now it was append-only:
recorders only ever `INSERT`, and nothing deleted or edited a row except the one-shot F-01
relabel and `delete_all_session_mints_for_tests`, a test-support method that deletes mint rows
and has no caller in `src/`. Two kinds of row in it carry an identifier nothing reads after
24 hours:

- **Cost-ledger rows** (`recorder = 'cost'`) hold the spend key twice: in the `account_id`
  column and as `"account_id"` in the JSON `payload`. The key is a keyed hash of a signed-in
  account's Google subject, or of an anonymous visitor's network (ADR-0136, ADR-0144). The
  spend rails read it only inside 24 hours (`daily_spend_for`, `try_record_cost_charge`).
- **Session-mint rows** (`recorder = 'session'`, `event_type = 'session_minted'`) hold the
  visitor's address in `payload["ip"]`: an IPv4 address, an IPv6 /64, or `invite:<link id>`
  (`main.py` `_daily_cap_key`). The new-session limit reads them only inside
  `SESSION_MINT_WINDOW`, 24 hours (ADR-0132).

So both identifiers stayed on the production volume forever. CHG-044 records the production
counts the owner was shown: 142 cost rows, all older than 48 hours and all holding a key; 71
session rows, 70 older than 48 hours.

The failure modes were listed before the design, in
`docs/analysis/2026-10-14-w55-ledger-key-wipe-failure-modes.md` (38 items, cited below as FM
plus the item number).

This record changes these earlier statements without editing their bodies:

- ADR-0002 line 11 calls the store an "append-only audit event sink", ADR-0016 lines 53 and 145
  call the sink and the ledger append-only, and ADR-0073 line 296 says the `events` table "is
  append-only by contract". Read all of them now as: rows are never deleted, and amounts are
  never edited; identifiers are removed from old rows in place. (ADR-0073 line 66 and ADR-0055
  line 296, "nothing prunes" the table, stay true: no row is deleted. ADR-0055 line 296 says
  `feedback_store.py` "records that nothing prunes that table"; that wording no longer exists
  there, since this change reworded the comment to "Nothing deletes rows from this table".)
- ADR-0132 line 91 says nothing prunes the table and each new-session row keeps the address
  with no end date. Since this record the address goes after 48 hours.
- ADR-0144 line 76 rejects an alternative because it "writes a visitor's address into rows
  nothing deletes". That was true when written; the session rows are now wiped too.
- ADR-0163 line 144 says how long the ledger keeps a signed-in key "has not yet been asked".
  CHG-044 (a) has decided it: 48 hours. How long Sentry keeps it is still not asked.

## Decision

In `feedback_store.py`:

- `IDENTIFIER_KEEP = timedelta(hours=48)`, `IDENTIFIER_WIPE_INTERVAL = timedelta(hours=1)`,
  and a frozen dataclass `WipeResult(cost_keys_wiped, session_addresses_wiped,
  malformed_payloads)`.
- `FeedbackStore.wipe_expired_identifiers(*, now=None) -> WipeResult`. For every row with
  `recorded_at` strictly before `now - 48h`:
  - a cost row (every event type) gets `account_id = NULL`, and loses `"account_id"` from its
    payload where the payload is valid JSON (`json_remove`, behind `json_valid` in a `CASE`);
  - a `session_minted` row loses `"ip"` from its payload (`json_remove`, so the key is gone,
    not set to null). Its account id and time stay.
  - **A payload that is not valid JSON**, in either kind of row, is replaced whole with the
    fixed text `{"payload_unreadable_wiped": true}` (`UNREADABLE_PAYLOAD_MARKER`), a cost row's
    column is cleared too, and the row is counted in `malformed_payloads` as well as in its
    kind's total. `json_remove` cannot edit such text, and it may hold a key or an address.
    Until review round 2 the cost UPDATE cleared only the column and left the text, and a mint
    row, or a cost row with no column key, was never even due, so a damaged row kept its
    identifier for ever (found by the round-2 Codex review, reproduced by the round-2 fixer:
    `tests/unit/test_w55_regressions.py` section 4 went red on the round-1 build with
    `assert (0, 0) == (1, 1)`). No writer produces such a row (every insert is `json.dumps` of
    a dict), so this reaches only damaged rows. Replacing the text cannot move a total: the
    meters `json.loads` every payload they sum (`feedback_store.py` `_spend_total_locked`,
    `amount = Decimal(str(json.loads(row["payload"]).get("estimated_cost_usd", "0")))`) and
    read only the last 24 hours. A malformed charge inside that window does not count as zero:
    it makes `daily_spend_for` and `global_daily_spend` raise `JSONDecodeError` (MEASURED by
    the round-2 fixer's scratch probe on the round-1 build; this change does not touch that
    code). One side effect, MEASURED by the same probe on this build: `iter_events()` over the whole table raised `JSONDecodeError` on such
    a row before the wipe and reads the marker after it.
  - Only rows that still hold an identifier are touched, so a repeat pass changes nothing.
  - NULL, never a sentinel: the per-account rail filters `account_id = ?`, which NULL never
    matches, and the global rails drop that predicate and still count the row (FM 18).
- **The cut.** The cut is computed as an aware-UTC `isoformat()` string, the exact format every
  production writer stores. Rows ending `+00:00` are compared as text, which is exact for that
  format with or without a microsecond fraction (FM 15) and is how the 24-hour rails already
  compare. Any other stored shape (another offset, a naive stamp) is compared with `julianday`,
  which compares instants; unreadable text gives NULL and is never wiped. The strict `<` is
  pinned on both branches (`test_the_cut_is_exact_for_whole_second_stamps_and_cuts`,
  `test_the_julianday_cut_is_strict_for_a_row_with_another_offset`).
- **One transaction.** When at least one row is due, the pass runs one `BEGIN IMMEDIATE`
  transaction (count the malformed rows, update cost rows, update session rows, commit). When
  no row is due it writes nothing at all.
- **`secure_delete` on for the whole connection.** `__init__` sets `PRAGMA secure_delete = ON`
  on the store's connection before anything else (pinned as the open's first statement by
  `test_secure_delete_is_the_first_statement_the_store_runs_at_open`) and nothing turns it off. Turning it on only
  for the wipe, as the first build did, is not enough: ordinary inserts move cells when a page
  splits and leave the old bytes in free space, which no later wipe rewrites (measurements
  below). It is a connection setting, not a write, so a read-only file accepts it.
- **One `VACUUM`, once per file.** Space freed before this release still holds old copies.
  After the open-time wipe (an order that is not load-bearing and not pinned: `secure_delete`
  is on for both, so either order leaves no copy), `__init__` runs `VACUUM` once and records
  `w55_vacuum_after_secure_delete` in `schema_migrations`, like the F-01 relabel; a file with
  that row is never vacuumed again. It runs only in `__init__`, before the store is published,
  so never inside a charge's or a mint's lock hold. It never stops the store opening: on a
  read-only file, a locked file (after the 5 s busy timeout) or a full disk it logs one INFO
  line, writes no marker and is tried again at the next open. It is INFO so that a read-only
  volume with no row due still shows only the backfills' warnings at boot; a read-only volume
  WITH rows due also logs one wipe WARNING (`identifier wipe did not run`) at every open. On an already-marked file it only reads
  the marker, so an already-migrated read-only volume still opens with zero writes.
- **Never raises.** Any exception is caught; the pass logs one WARNING line (the SQLite reason,
  or only the exception's type name for anything else, never a key or an address) and returns
  zeros. A pass that changed rows logs one INFO line with the three counts (WARNING when
  `malformed_payloads` is not zero). The stamps behind `write_health()` and
  `lost_billed_writes()` are not moved.
- **Three triggers, all outside every money lock hold:**
  1. at every store open, after the two one-shot backfills (every start, deploy, reconnect,
     restored snapshot);
  2. from the public `record()`, after a row lands, at most once per
     `IDENTIFIER_WIPE_INTERVAL` on the store's monotonic clock;
  3. after `try_record_cost_charge` returns `RECORDED`, and after `try_record_session_mint`'s
     insert attempt returns (whether or not its row landed, since the insert swallows a
     failure; a mint the limit refuses returns before it), with the same throttle, so a
     deployment whose only traffic is charges or new visitors still wipes. A cost
     reconciliation starts no pass.
  The three check-and-record methods (charge, reconciliation, mint) hold the store lock across
  their insert, so they call a private `_insert_event()` that has no trigger. Every trigger
  calls the public method by name through one guard that catches anything it raises.

## Measurements

| What | Result | How |
|---|---|---|
| Stored time shapes | `2026-10-13T21:09:10.716036+00:00`, and `2026-10-01T09:00:00+00:00` when the microseconds are zero | MEASURED, FM 14 |
| Text comparison for UTC rows, with and without a fraction, and at exactly the cut | correct in all three cases (`+` sorts before `.`); a `+05:30` or `-05:00` row compares wrongly as text | MEASURED, FM 15; the offset case is pinned by `tests/unit/test_w55_identifier_wipe_edges.py::test_a_row_stamped_with_another_offset_is_compared_by_instant` |
| A plain UPDATE leaves the old bytes in the file | 73 copies of a key after wiping 50 rows; 0 with `secure_delete` on | MEASURED, FM 29; pinned by `test_wiped_key_bytes_do_not_stay_in_the_database_file` (40 copies before, 0 after) |
| One malformed payload, unguarded | the whole UPDATE raised `malformed JSON` and changed no row | MEASURED, FM 24; pinned by `test_a_malformed_payload_does_not_stop_the_others` |
| A malformed payload past the cut, round-1 build | a cost row's text kept its key (only the column was cleared); a mint row, or a cost row with no column key, was never due and kept its text | found by the round-2 Codex review and reproduced by the round-2 fixer; now replaced with the marker, pinned by `test_an_unreadable_cost_payload_past_the_cut_loses_its_key` (with and without a column key), `test_an_unreadable_mint_payload_past_the_cut_loses_its_address` and the partner `test_an_unreadable_payload_inside_48_hours_is_left_alone` |
| A read-only database | any UPDATE raises `attempt to write a readonly database`, even `WHERE 0` | MEASURED, FM 8; the open still succeeds: `test_a_read_only_database_still_opens_and_the_wipe_returns_zeros` |
| Journal mode and busy timeout | `delete`, 5000 ms | MEASURED, FM 7 and 10; `journal_mode` re-read by this session's probe: `delete` |
| Cost of a pass | 20,000 cost rows (1 h to about 1,000 h old) plus 2,000 session rows: open including the first pass 0.036 s **on the first build**, leaving exactly the 940 cost rows under 48 hours keyed; a second pass 0.0056 s, changing nothing. The open now also runs the one-shot `VACUUM`: 0.09-0.14 s (row below) | MEASURED by the first build's session, SQLite 3.50.4, macOS, local SSD; Fly's shared CPU and volume are slower by an UNVERIFIED amount |
| An outside reader holding a read transaction | the UPDATE waited the 5 s busy timeout, then raised `database is locked` | MEASURED, FM 10; the same reader makes a billed INSERT fail today, so the production check below must not hold one |
| SQLite version on the Fly machine | not recorded in the repo (`python:3.12-slim` by tag) | UNVERIFIED, FM 28; JSON functions are built in from 3.38; check with `fly ssh console -C "python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'"` |
| Fly volume snapshot retention | not set or recorded anywhere in the repo | UNVERIFIED, FM 31; check with `fly volumes snapshots list <volume id>` |
| `secure_delete` on only during the wipe (the first build) | copies left in the file after the wipe: review (Codex) measured 20 public charges leaving 20 key copies and 100 mints leaving 29 address copies; review (break-it) measured a brand-new file with 40 rows leaving 26 of the 40 column keys in page 2's unused space; this session measured 200 public charges and 200 public mints leaving 15 key copies and 8 address copies. With it on for the connection: 0 and 0 | the review figures are INHERITED from round 1, not re-run here; this session's figure is MEASURED by a scratch probe and pinned by `tests/unit/test_w55_regressions.py::test_public_writes_leave_no_copy_of_a_key_or_address_after_the_wipe` (red with the first build's setting: `assert 15 == 0`) |
| No `secure_delete` at all, on the seed of `test_wiped_key_bytes_do_not_stay_in_the_database_file` | 19 copies of the key and 5 of the address after the wipe; 0 and 0 with it | MEASURED by this session (3 runs, same counts), SQLite 3.50.4 |
| Copies in free space from before any store opened the file (300 rows deleted with `secure_delete` off) | 42 copies before the first open; 0 after it | MEASURED; pinned by `tests/unit/test_w55_regressions.py::test_the_first_open_vacuums_away_copies_left_in_free_space` |
| The one-shot `VACUUM` on a 20,000-row file | 18,000 cost rows plus 2,000 session rows (12.6 MB, 8.5 MB after): 0.034, 0.042, 0.053 s, whole open 0.09-0.14 s including the first wipe; 20,000 provider rows of 2 KB (87.6 MB, 85.2 MB after): 0.365, 0.411, 0.433 s | MEASURED by this session, SQLite 3.50.4, macOS, local SSD, load average about 6.8; Fly is slower by an UNVERIFIED amount |
| Cost of a pass at scale | 300,000 cost rows plus 300,000 session rows plus 200,000 other rows: first pass 1.14 s, a pass with nothing due 0.128 s, both under the store lock | INHERITED from review round 1, not re-run here |

## Rejected alternatives

- **A timer thread.** `fly.toml` sets `auto_stop_machines = "stop"` and
  `min_machines_running = 0`, so a stopped machine runs no thread and a timer alone can miss days
  (FM 1). The open-time pass covers a machine that starts; the throttled write-path pass covers
  one that stays up.
- **Wiping inside `record()` under the lock.** `try_record_cost_charge` calls the insert while
  holding the store lock, and the insert treats any exception in its `try` as a lost write. A
  wipe fault there would turn a charge that landed into `METERING_UNAVAILABLE`, bump
  `lost_billed_writes` and raise the money ERROR, and a slow pass would stall every charge behind
  it (FM 5). Pinned by `test_a_failing_wipe_never_changes_a_charge_or_a_record`,
  `test_a_raising_wipe_never_changes_a_charge` and
  `test_the_wipe_never_runs_inside_the_charge_lock_hold`.
- **Deleting old rows.** The amounts are the ledger; the owner's question offered wiping the key
  only ("rows and amounts always stay"), and the audit job reads rows over whatever window it is
  given (`feedback_audit --window-hours`).
- **Wiping anonymous rows only.** A row does not say whether its key is a network's or an
  account's. The owner chose every row (CHG-044 (a)); the other options offered were "Anonymous
  only, from now on" and "Anonymous only, guessed for old rows".
- **A one-shot migration marker**, like the F-01 relabel. New rows keep turning 48 hours old, so
  the rule must run again and again (FM 6). The matching risk, a wrong WHERE clause rewriting
  fresh rows on every pass, is pinned by the rows under 48 hours that these tests check keep
  their identifier: in `tests/unit/test_w55_identifier_wipe.py`,
  `test_cost_rows_past_48_hours_lose_both_keys_and_nothing_else`,
  `test_the_48_hour_cut_is_strict`, `test_session_mint_rows_lose_the_address_whatever_its_shape`,
  `test_the_mint_cap_still_counts_after_a_wipe`, `test_metering_is_unchanged_by_a_wipe`,
  `test_opening_the_store_wipes_expired_rows` and
  `test_the_record_path_wipe_uses_the_wall_clock_not_the_rows_time`; in
  `tests/unit/test_w55_identifier_wipe_edges.py`,
  `test_a_row_stamped_with_another_offset_is_compared_by_instant`; in
  `tests/unit/test_w55_regressions.py`, `test_the_cut_is_exact_for_whole_second_stamps_and_cuts`.
  (The one-shot `VACUUM` IS marker-guarded: it removes old copies, a job done once per file.)
- **Stamping a write failure when the wipe fails.** That would read `failing` on `/status` from
  boot on a read-only volume and degrade every run until a record landed, and a corrupt row would
  raise a false write failure (FM 9). The wipe logs its own WARNING instead.
- **`VACUUM` on every pass, or on a timer.** It takes an exclusive lock for its whole run and
  needs free space on the order of the file's size (FM 29), and with `secure_delete` on for the
  connection there is nothing new for it to clear. The first build did no `VACUUM` at all;
  review round 1 showed that left copies written before this release, so it now runs once per
  file (Decision above).

## Consequences

- The `events` table is no longer strictly append-only: rows are never deleted and amounts never
  change, but identifiers are removed from rows older than 48 hours. The module docstring, the
  class docstring and the code comments that called it append-only now say so.
- The 48 hours is a floor, not a ceiling. While the app runs, a key or address goes at the first
  write that comes at least an hour after the previous pass: about one more hour with steady
  traffic, and until the next write when there are none. While the machine is stopped it stays
  until the next start, when the open-time pass removes it before the store serves anything.
  Fly volume snapshots may keep older copies (retention UNVERIFIED).
  `docs/48-data-retention.md` and the runbook state this bound.
- The first open after this release rewrites the whole file once (`VACUUM`). Measured above at
  0.034-0.053 s for 20,000 ledger-shaped rows and 0.37-0.43 s for 20,000 rows of 2 KB. Where it
  cannot run it adds one failed attempt to each open until it can, up to the 5 s busy timeout
  when another connection holds a lock.
- A store opened on a database with due rows now writes at open. On an already-wiped,
  already-migrated read-only volume it still writes nothing, which `store_reconnect.py` depends
  on. On a read-only volume with due rows the pass fails and logs one WARNING at each open. No
  `record()` row and no charge lands there, so those two triggers never fire; a new session that
  passes its limit still starts a (throttled, failing) pass, because the mint trigger fires
  whether or not its row landed, so expect at most one more wipe WARNING an hour. On a read-only
  volume that has not had the one-shot `VACUUM` yet, that also fails at each open, at INFO.
- The operator CLI that opens the live file under `fly ssh console` (`docs/23-data-model.md`)
  also runs the open-time pass: a second writer for milliseconds (FM 11).
- **The production check after the deploy** (FM 36 and 37): inside the machine, read-only
  (`mode=ro`), one autocommit statement per count, counts only, never an interactive shell left
  open on the file (an open read makes the next billed write fail, and stacks the next open's
  waits to 10-22 s; see "Recorded limits" below). Count cost rows older than 50 hours still holding a key, and session rows
  older than 50 hours still holding `"ip"`: both should read 0. Partners: cost rows older than 50
  hours (at least 142) and session rows older than 50 hours (at least 70). The query is in the
  failure-modes doc, section H, and in `docs/runbooks/feedback-store-schema-migration.md`. The
  deploy itself starts a new process, so the open-time pass will have run; its INFO line in
  `fly logs` shows how many rows it changed.

## What it cannot see

- **Fly volume snapshots** keep un-wiped copies until they age out; how long Fly keeps them is
  UNVERIFIED (FM 31). A restored snapshot is re-wiped at its first open.
- **Deleted rollback journals, and a file the one-shot `VACUUM` has not yet reached.** The
  blocks of a deleted `-journal` file (including the one the `VACUUM` writes, which holds the
  old pages) may hold old keys until the filesystem reuses them (FM 30). Until the `VACUUM` has
  run on a file (it waits for a writable, unlocked volume with room), space freed before this
  release still holds old copies there (FM 29).
- **The in-memory cost ring** (`InMemoryCostEventRecorder`, up to 1,024 events) holds keys until
  eviction or process exit, which on a quiet machine can be longer than 48 hours (FM 32).
- **Logs and Sentry.** A ceiling-degraded run sends the key to Sentry as `account_id`; how long
  Sentry keeps it is not asked (FM 34).
- **Accounts created before the spend key existed (pre-W7).** Their spend key equals their
  account id (`session_store.py`, the `spend_key = account_id` backfill), and that id stays on
  the account's provider, synthesis, debate, model-slot, safety and evaluation rows in the same
  table (the evaluation recorder writes `account_id=query_run.account_id`,
  `query_run_orchestration.py` ~1966-1969) and in the `runs` table of `run_history.sqlite3`
  (`run_history_store.py:147`) (FM 33). Sign-in events are not in this table: they are in
  `sessions.sqlite3`'s `sign_in_events`, kept 30 days and at most 10 rows per account, and
  deleted with the account. Those rows are outside CHG-044's words, which name cost rows and
  session rows only. Recorded here for the owner, not widened.
- **The 48 hours is measured on the wall clock.** While the clock is stepped forward, the rows a
  wipe takes early are rows the rails, reading the same clock, have already stopped reading
  (FM 17). Once the clock is put right that no longer holds: a step of more than 24 hours at a
  wipe removes keys from rows that are really under 24 hours old, so after the correction that
  account's spend from those rows no longer counts and it can spend its daily cap once more.
  Round-2 break-it reviewer's measurement, with a clock 48 hours or more ahead, not re-run
  here: a cap of 0.30 spent, then 0.30 again. (The 24-hour threshold is this record's
  arithmetic: a step of X hours wipes rows really older than 48 - X hours.) The global rails
  drop the key predicate and still count those rows, so the deployment-wide ceiling holds.
- **A payload that is valid JSON but not an object** (a JSON string or array holding a key's
  text) keeps its text: only text that is not valid JSON is replaced. MEASURED by the round-2
  fixer's probe (`"0dd0-key-in-a-json-string"` and `[1, "0dd0-key-in-an-array"]` both kept). No
  writer produces one (every insert is `json.dumps` of a dict); recorded, not built.

## Recorded limits (review round 2)

The round-2 break-it reviewer measured the limits below (and the clock-step case in "What it
cannot see" above). They are that reviewer's figures, not re-run by the fixer. Review triage
classed them as advisory, recorded rather than built.

- **The open's waits stack when another connection holds a read.** With an outside connection
  holding a read transaction on the file, an open took 10.81 s on a small file and 21.74 s on
  20,000 rows, against 0.00 s on `main`: on `main` an already-migrated open writes nothing,
  while this build's open has more than one step that may write (the wipe, the one-shot
  `VACUUM`), and each can wait out the 5 s busy timeout. How the 21.74 s splits between the
  steps was not measured. Only an operator shell or a hand-run CLI could hold such a read.
  `fly.toml`'s HTTP check on `/ready` has `grace_period = "20s"` (`fly.toml:186`), so a start
  stalled this long could be failing its first health checks. The production check in
  Consequences above must therefore be the quick `mode=ro` one-shot query, never an open
  `sqlite3` shell.
- **The first wipe is one transaction, so a disk short of room never gets wiped.** Measured on
  a 13.8 MB, 20,000-row file: with 6.3 MB free every open logs `database or disk is full` and
  the keys stay; with 11 MB free the wipe runs and the `VACUUM` waits; with 13 MB or more both
  run. The production file's size and the volume's free space are UNVERIFIED; check with
  `fly ssh console -C "df -h /data"` and `ls -l /data/feedback_events.sqlite3`.
- **WAL mode would hold copies in the `-wal` file until a checkpoint.** `secure_delete` zeroes
  freed space in the main file; in WAL mode the old pages would sit in `-wal` until it is
  checkpointed and overwritten. This store does not use WAL: no line in `src/` sets
  `journal_mode` (`grep -rn journal_mode src/` prints nothing), so SQLite's default rollback
  journal (`delete`) applies, ADR-0002 rejects WAL by name, and FM 7 measured `delete` on a file
  the store made. The production file's own mode is UNVERIFIED (WAL is a setting stored in the
  file, so a tool that once set it would leave it set); check with a `mode=ro` connection and
  `PRAGMA journal_mode`.
