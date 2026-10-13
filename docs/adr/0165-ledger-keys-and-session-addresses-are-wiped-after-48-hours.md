# ADR-0165: Ledger keys and session addresses are wiped after 48 hours

## Status

Accepted — 2026-10-14. The keep time and its scope are the owner's: CHG-033 (c) chose 48 hours
for an anonymous network's key in the cost ledger, CHG-044 (a) widened it to every cost-ledger
row, signed-in and anonymous alike, and CHG-044 (b) added the visitor's address in session rows
(board row W55). The design below (the method, its three triggers, the one-hour throttle,
`secure_delete`, "never raises", the trigger outside the money lock) is the session's.

## Context

`src/product_app/feedback_store.py` keeps one `events` table. Until now it was append-only:
recorders only ever `INSERT`, and nothing deleted or edited a row except the one-shot F-01
relabel. Two kinds of row in it carry an identifier nothing reads after 24 hours:

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
  line 296, "nothing prunes" the table, stay true: no row is deleted.)
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
    payload where the payload is valid JSON (`json_remove`, behind `json_valid` in a `CASE`).
    The column is cleared even when the payload is malformed; such a row is counted in
    `malformed_payloads`;
  - a `session_minted` row loses `"ip"` from its payload (`json_remove`, so the key is gone,
    not set to null). Its account id and time stay.
  - Only rows that still hold an identifier are touched, so a repeat pass changes nothing.
  - NULL, never a sentinel: the per-account rail filters `account_id = ?`, which NULL never
    matches, and the global rails drop that predicate and still count the row (FM 18).
- **The cut.** The cut is computed as an aware-UTC `isoformat()` string, the exact format every
  production writer stores. Rows ending `+00:00` are compared as text, which is exact for that
  format with or without a microsecond fraction (FM 15) and is how the 24-hour rails already
  compare. Any other stored shape (another offset, a naive stamp) is compared with `julianday`,
  which compares instants; unreadable text gives NULL and is never wiped.
- **One transaction, with `secure_delete`.** When at least one row is due, the pass sets
  `PRAGMA secure_delete = ON`, runs one `BEGIN IMMEDIATE` transaction (count the malformed rows,
  update cost rows, update session rows, commit), and restores the previous setting. When no
  row is due it writes nothing at all.
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
  3. after `try_record_cost_charge` returns `RECORDED` and after `try_record_session_mint`
     records, with the same throttle, so a deployment whose only traffic is charges or new
     visitors still wipes.
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
| A read-only database | any UPDATE raises `attempt to write a readonly database`, even `WHERE 0` | MEASURED, FM 8; the open still succeeds: `test_a_read_only_database_still_opens_and_the_wipe_returns_zeros` |
| Journal mode and busy timeout | `delete`, 5000 ms | MEASURED, FM 7 and 10; `journal_mode` re-read by this session's probe: `delete` |
| Cost of a pass | 20,000 cost rows (1 h to about 1,000 h old) plus 2,000 session rows: open including the first pass 0.036 s, leaving exactly the 940 cost rows under 48 hours keyed; a second pass 0.0056 s, changing nothing | MEASURED by this session, SQLite 3.50.4, macOS, local SSD; Fly's shared CPU and volume are slower by an UNVERIFIED amount |
| An outside reader holding a read transaction | the UPDATE waited the 5 s busy timeout, then raised `database is locked` | MEASURED, FM 10; the same reader makes a billed INSERT fail today, so the production check below must not hold one |
| SQLite version on the Fly machine | not recorded in the repo (`python:3.12-slim` by tag) | UNVERIFIED, FM 28; JSON functions are built in from 3.38; check with `fly ssh console -C "python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'"` |
| Fly volume snapshot retention | not set or recorded anywhere in the repo | UNVERIFIED, FM 31; check with `fly volumes snapshots list <volume id>` |

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
  fresh rows on every pass, is pinned by the 47-hour partner rows in every wipe test.
- **Stamping a write failure when the wipe fails.** That would read `failing` on `/status` from
  boot on a read-only volume and degrade every run until a record landed, and a corrupt row would
  raise a false write failure (FM 9). The wipe logs its own WARNING instead.
- **`VACUUM`.** It would also clear space freed before `secure_delete` was on, but it takes an
  exclusive lock and needs free space about the size of the file (FM 29). Not done here.

## Consequences

- The `events` table is no longer strictly append-only: rows are never deleted and amounts never
  change, but identifiers are removed from rows older than 48 hours. The module docstring, the
  class docstring and the code comments that called it append-only now say so.
- The 48 hours is a floor, not a ceiling. While the app runs and writes, a key or address can stay
  up to about one more hour plus the time to the next write; while the machine is stopped, until
  its next start, when the open-time pass removes it before the store serves anything.
  `docs/48-data-retention.md` states this bound.
- A store opened on a database with due rows now writes at open. On an already-wiped,
  already-migrated read-only volume it still writes nothing, which `store_reconnect.py` depends
  on. On a read-only volume with due rows the pass fails and logs one WARNING at each open; no write
  lands there, so the write-path trigger never fires.
- The operator CLI that opens the live file under `fly ssh console` (`docs/23-data-model.md`)
  also runs the open-time pass: a second writer for milliseconds (FM 11).
- **The production check after the deploy** (FM 36 and 37): inside the machine, read-only
  (`mode=ro`), one autocommit statement per count, counts only, never an interactive shell left
  open on the file. Count cost rows older than 50 hours still holding a key, and session rows
  older than 50 hours still holding `"ip"`: both should read 0. Partners: cost rows older than 50
  hours (at least 142) and session rows older than 50 hours (at least 70). The query is in the
  failure-modes doc, section H, and in `docs/runbooks/feedback-store-schema-migration.md`. The
  deploy itself starts a new process, so the open-time pass will have run; its INFO line in
  `fly logs` shows how many rows it changed.

## What it cannot see

- **Fly volume snapshots** keep un-wiped copies until they age out; how long Fly keeps them is
  UNVERIFIED (FM 31). A restored snapshot is re-wiped at its first open.
- **Freed pages from before this change, and the deleted rollback journal.** `secure_delete`
  cleans only space freed from now on; older free space (for example from the F-01 relabel) and
  the blocks of a deleted `-journal` file may still hold old keys until reused (FM 29, FM 30).
- **The in-memory cost ring** (`InMemoryCostEventRecorder`, up to 1,024 events) holds keys until
  eviction or process exit, which on a quiet machine can be longer than 48 hours (FM 32).
- **Logs and Sentry.** A ceiling-degraded run sends the key to Sentry as `account_id`; how long
  Sentry keeps it is not asked (FM 34).
- **Accounts created before the spend key existed (pre-W7).** Their spend key equals their
  account id (`session_store.py`, the `spend_key = account_id` backfill), and that id stays on
  the account's provider, synthesis, debate, model-slot, safety and sign-in rows in the same table
  and in `run_history.sqlite3` (FM 33). Those rows are outside CHG-044's words, which name cost
  rows and session rows only. Recorded here for the owner, not widened.
- **The 48 hours is measured on the wall clock.** A forward clock step wipes early, but the rails
  read the same clock, so they had already stopped reading those rows (FM 17).
