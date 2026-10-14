# W55 — how the ledger key wipe can fail (failure modes, 2026-10-14)

Role: failure modes, read-only. Item: W55, owner decisions CHG-033 (c) and CHG-044
(`docs/19-change-control-log.md` rows 37 and 48). Tree: branch `w55/ledger-key-wipe` at
`b15ed14`.

What is to be built, in one line: after 48 hours, every `recorder = 'cost'` row loses its
spend key (the `account_id` column and the `"account_id"` key in `payload`), and every
`session_minted` row loses the visitor's address (the `"ip"` key in `payload`). The row, its
amounts, time, event type and run id stay.

How this was checked. Probes ran in a `git archive HEAD` copy under the session scratchpad,
with `PYTHONPATH` pointed at the copy's `src/` (the module path printed was the copy's).
Python 3.12.13, SQLite 3.50.4, macOS, local SSD. No network, no production. Each item says
MEASURED (a probe printed it), READ (from the named line of code or doc), or UNVERIFIED (with
the check that would settle it).

## A. When the wipe runs

1. **A timer alone can miss days.** `fly.toml` sets `min_machines_running = 0` and
   `auto_stop_machines = "stop"` (READ). A stopped machine runs no thread. Rows sit on the
   volume with their key until the machine next starts. No trigger inside the app can wipe
   while the machine is stopped.
2. **A start-only wipe can miss days too.** The store opens once per process, at import in
   `main.py`, and again only when `store_reconnect.py` reopens it after a fault (READ,
   `store_reconnect.py` header). A machine that stays up keeps rows un-wiped for
   48 hours plus its uptime. How long the machine stays up is UNVERIFIED. Check:
   `fly machine status <id> --display-config` and the boot lines in `fly logs` (both free and
   read-only). The availability check (`.github/workflows/availability-check.yml`, cron
   `*/15`) hits `/ready`, and `auto_start_machines = true` starts a stopped machine on any
   request, so the machine probably starts several times a day. That is UNVERIFIED too;
   repo notes say the real cron cadence is hours, not 15 minutes.
3. **A write-path-only wipe runs only with traffic.** With no traffic there are no new rows,
   but old rows keep aging past 48 hours un-wiped. A day of `/ui` visits with no runs writes
   mint rows but calls no recorder that runs during a query.
4. **Latest un-wiped age under each design** (the wipe cut is 48 hours):

   | Design | While the machine runs | While it is stopped |
   |---|---|---|
   | Timer only (every T) | 48 h + T | until the next start, then 48 h + T after that |
   | At store open only | 48 h + uptime (unbounded) | until the next start; wiped at that start |
   | Each write, throttled to once per T | 48 h + T + time to the next write | until the next start AND a write |
   | At open + throttled write-path pass | 48 h + T while there is traffic, else until the next start | until the next start; wiped at that start, before serving |

   No design reaches a hard 48 hours. docs/48 must state the real bound, not "48 hours".
5. **Inside `record()` is the wrong place.** `try_record_cost_charge` calls `self.record()`
   while it holds the store lock (READ, `feedback_store.py` ~1582). `record()` treats any
   exception in its `try` as a failed insert. If a wipe error landed in that `try`, a charge
   that DID land would bump `lost_billed_writes`, raise the money ERROR and return
   `METERING_UNAVAILABLE`, so a live run would be degraded for a wipe fault. The wipe must
   run outside `record()` and outside the charge's and the mint's lock hold. `record_event()`
   (the module wrapper, ~1965) is called by the recorders that run during a query (provider,
   synthesis, debate, model slot, safety), never by the charge path. It is a safe hook.
6. **A one-shot marker is the wrong shape.** The F-01 relabel is guarded by a
   `schema_migrations` marker because its rule must apply once (READ, ~395-410). The wipe is
   the opposite: new rows keep turning 48 hours old, so it must run again and again. Do not
   reuse the marker pattern. The cost of a standing rule is the one the F-01 comment warns
   about: a wrong WHERE clause rewrites fresh rows on every pass. Item 14 below is the
   matching test.
7. **Shutdown mid-pass is safe.** `kill_timeout = "5s"` then SIGKILL (READ, `fly.toml`). The
   database runs in rollback-journal mode (MEASURED: `PRAGMA journal_mode` → `delete`), so a
   killed transaction is rolled back at the next open. The wipe is repeatable, so the next
   pass finishes the job. Keep each pass in one transaction (or one statement per table).

## B. Write safety

8. **A read-only database raises even when there is nothing to wipe.** MEASURED on a
   read-only file: `UPDATE events SET account_id = NULL WHERE 0` raised `attempt to write a
   readonly database`, and so did the matching UPDATE. Opening the store did not raise
   (`write_health` read `unverified`). So a wipe at open on a read-only volume raises every
   boot. It must be caught, as the F-01 and cutover backfills are (~584-640, ~674-720), or the
   app stops starting: the exact F-01 lesson.
9. **Write health: stamp or not, decide on purpose.** Today an already-migrated read-only
   database writes nothing at open, and `store_reconnect.py` depends on that (READ, the
   `_feedback_reopen_tried_without_recovery` note: "opens WITHOUT RAISING ... attempts ZERO
   writes at open time"). If the wipe stamps `_last_write_failure_at` when it fails,
   `/status` reads `failing` from boot and `feedback_ledger_may_be_metered` turns false, so
   every run degrades to simulation until a record lands. That is arguably right on a
   read-only volume, but it changes measured behaviour pinned by
   `tests/integration/test_stale_ledger_block_on_a_real_volume.py`,
   `tests/integration/test_feedback_store_locked_database.py`,
   `tests/integration/test_feedback_store_write_failures.py`,
   `tests/unit/test_stale_ledger_spend_policy.py` and `tests/unit/test_spend_cap_state_table.py`.
   A wipe failure caused by a corrupt row (item 19) would also stamp a false write failure,
   the shape the F-01 `except` already documents. Safest: the wipe logs its own WARNING and
   leaves both stamps alone. Whichever is chosen, run those five files.
10. **An outside reader stalls the wipe and every charge behind it.** MEASURED: with a second
    connection holding an open read transaction, the UPDATE waited the 5-second busy
    timeout (MEASURED: `PRAGMA busy_timeout` → 5000) and raised `database is locked` after
    5.23 s. The real wipe would hold the store's single lock for that time (ADR-0002: one
    connection, one lock, no WAL), so every charge, mint and recorder write waits behind it.
    The same open reader made a billed INSERT fail after 5.21 s with `lost_billed_writes = 1`
    (MEASURED). That second hazard exists today; the production check in section H must not
    trigger it.
11. **A second writer exists.** The audit CLI run by hand from `fly ssh console` calls
    `FeedbackStore.from_env()` on the live file (READ, `docs/23-data-model.md:80`, the runbook
    "Who opens the production database"). A wipe at open then runs from a second process
    while the app runs. The pass is milliseconds, so the risk is small, but it is a second
    writer against ADR-0002's single-writer design.
12. **A large UPDATE is cheap here.** MEASURED on a 120,000-row table (100,000 provider rows
    of 2 KB, 20,000 cost rows): the first pass wiped 19,000 old cost rows in 0.021 s; the
    second pass changed 0 rows in 0.003 s, and the 1,000 newer rows kept their key. Query plan:
    `SEARCH events USING INDEX events_recorder_type_time_idx (recorder=?)`. Only the
    `recorder` prefix is used, because the wipe does not name an event type, so each pass
    reads every cost row ever written. Production had 142 cost rows on 2026-10-13 (read-only count, CHG-044). Fly's
    shared CPU and volume will be slower; by how much is UNVERIFIED.
13. **A full disk makes the wipe fail.** An UPDATE needs room for its rollback journal.
    Removing a key does not shrink the file (no `VACUUM` anywhere in `src/`, per the
    runbook, when this was written; review round 1 added one `VACUUM` per file at open,
    ADR-0165). On `database or disk is full` the wipe must log and carry on. It cannot help a
    full volume.

## C. The 48-hour cut

14. **The stored time format.** MEASURED: rows read back as
    `'2026-10-13T21:09:10.716036+00:00'`, and as `'2026-10-01T09:00:00+00:00'` when the
    microseconds are zero (Python's `isoformat()` drops them). Every production writer
    stamps `datetime.now(UTC)` (READ: `record_event` ~1987, and the `now or
    datetime.now(UTC)` defaults in the charge, reconcile, void and mint methods).
15. **Comparing the text is right only while every row is in UTC.** MEASURED against a
    cutoff of `10:00:00.500000+00:00`: rows with and without a fraction compared correctly as
    text (`+` sorts before `.`), and so did a row exactly at the cutoff. A `+05:30` row that
    was older compared as newer (missed wipe, the safe direction). A `-05:00` row that was
    newer compared as older (wiped early). `julianday(recorded_at) < julianday(?)` gave the
    right answer in all five cases, including a 6-digit fraction. Production writes only
    `+00:00`, so text comparison is safe there today; tests may pass other offsets. Either
    use `julianday` (it skips the index, and returns NULL for unreadable text, so those rows
    are never wiped and should be counted), or keep text and state the UTC assumption.
16. **The boundary.** Use a strict `recorded_at < now - 48h`. A row at exactly 48 hours waits
    one more pass. That is harmless.
17. **Clock steps add no metering error WHILE the clock is wrong, if the wipe and the rails
    share one clock.** A backward step makes rows look younger: they are wiped late (safe). A
    forward step of more than 24 hours would wipe rows that are really inside the 24-hour
    window. But the rails compute their window from the same wall clock, so after such a step
    they already leave those rows out. The wipe is always 24 hours behind the rails' window,
    whatever the clock reads. **Narrowed in review round 2:** once such a step is CORRECTED,
    those rows are back inside the per-account window without their key, so that account can
    spend its daily cap once more. The round-2 break-it reviewer measured it (clock 48 hours
    or more ahead at a wipe, then corrected: a cap of 0.30 spent, then 0.30 again; not re-run
    by the fixer). The global rails still count the rows, so the deployment-wide ceiling
    holds. Recorded in ADR-0165, "What it cannot see". This holds only if the wipe uses the same clock as the rails. If the wipe
    reads the wall clock while a test injects a fixed `now` into the rails, rows seeded at a
    fixed past date lose their key mid-test. How many tests seed old rows and then read them
    by key is UNVERIFIED. Check: run the suite once with the wipe in place, and grep for
    `datetime(20` in tests that call `daily_spend_for`, `try_record_session_mint` or read
    `account_id`. Recommendation: give the wipe its own injectable clock, never the write
    path's `now` argument (a test passing a far-future `now` would wipe everything).

## D. Not breaking metering

18. **A wiped row is never counted for one account, and still counts in the global total.**
    MEASURED: one charge with a key and one with a NULL key, both 1 hour old, $0.10 each.
    `_spend_total_locked(account_id=a)` returned 0.10. The global call
    (`account_id=None`) returned 0.20. The per-account SQL is `AND account_id = ?`
    (READ, ~1107), and NULL never equals anything, so a wiped row can never be counted for a
    NULL account or for every account. The global rails drop the predicate, so a wiped row
    still counts there, and the global sum does not change. Use NULL, not `''` or a
    sentinel id: a sentinel would be summed for anyone whose key equals it.
19. **A late reconciliation cannot reach a wiped row.** `try_record_cost_reconciliation`
    keys on `query_run_id` and refuses a run with no `cost_guardrail_accepted` row inside 24
    hours (READ, ~1650-1658). It never reads `account_id`. So a reconciliation more than 24
    hours late is already refused, wipe or not. The corrections query in
    `_spend_total_locked` does filter on `account_id` (READ, ~1150), but only inside the
    24-hour window, which the wipe never touches.
20. **A late void is harmless.** `void_cost_charge` has no window guard (READ, ~1676-1705),
    so a void could in theory be written for a charge already wiped. It would be written
    with a key, change no sum (its charge is outside the window), and lose its key on the
    pass after it turns 48 hours old. In practice a void is written seconds after its charge,
    for a run that never started.

## E. Not breaking readers of old rows

21. **Readers in `src/`.** `grep -rn` for `iter_events`, `payload.get("ip")`,
    `["account_id"]` and `.account_id` (READ):
    - `feedback_audit._load_events_by_recorder` (`feedback_audit.py:867`) reads payload
      fields by name; `grep -n account_id src/product_app/feedback_audit.py` prints nothing.
    - The three mint readers (`try_record_session_mint`, `seconds_until_a_session_mint_frees`,
      `session_mint_count_for_ip`) filter `payload.get("ip") == ip` over the last 24 hours
      only. A removed key reads as `None` and matches no address.
    - `last_live_charge_at` reads `recorded_at` only.
    - No code outside `feedback_store.py` reads session-mint rows.
    So no `src/` reader needs the key after 24 hours.
22. **Tests read `account_id` on recent rows** (for example
    `tests/integration/test_anonymous_spend_per_network.py:223,542,842,899`,
    `tests/integration/test_session_cap_sign_in.py:124,135,286`). Rows written "now" are not
    eligible, so these should hold. Rows seeded at a fixed past date are the risk (item 17).
23. **The `"ip"` value is not always an address.** It is the address, an IPv6 /64, or
    `invite:<link id>` for an invite link (READ, `main.py:1902`, `_daily_cap_key`). Wipe the
    key whatever its value. Nothing reads an invite key after 24 hours either. The owner's
    words say "address"; the build note should say invite keys are wiped too.

## F. Editing the JSON

24. **One malformed payload stops the whole wipe.** MEASURED: an unguarded
    `UPDATE ... SET payload = json_remove(payload, '$.account_id')` over eight rows raised
    `malformed JSON` because of one bad row, and changed none, the valid rows included. If
    that error were swallowed, nothing would ever be wiped, silently. `json_type` raises the
    same error on malformed text, even inside a SELECT.
25. **Guard the JSON part, but not the column part.** MEASURED: `WHERE json_valid(payload)
    AND json_type(payload, '$.account_id') IS NOT NULL` ran without error and changed 2 rows
    (SQLite evaluated `json_valid` first; the order of `AND` is not promised by SQLite's
    docs, so `CASE WHEN json_valid(payload) THEN ... END` is the safer form). But in that
    single statement the two malformed rows kept their `account_id` column key. NULL the
    column in its own clause (or statement), and count the malformed rows instead of
    skipping them silently. **Review round 2:** clearing the column was not enough. The text
    of a malformed payload can itself hold the key (or, in a mint row, the address), and
    `json_remove` cannot edit it, so the first build left it for ever. Such a payload past the
    cut is now replaced whole with `{"payload_unreadable_wiped": true}` (ADR-0165).
26. **Restrict to rows that still hold a key.** MEASURED: putting the guard in the `SET`
    (`CASE ... ELSE payload END`) "updated" 8 of 8 rows, including rows with no key. Without
    a "still holds a key" condition each pass rewrites every old row: honest counts are
    lost, the journal grows with history, and the pass is no longer close to free. With the
    condition, the second pass changed 0 rows (item 12).
27. **`json_remove` changes the text, not the data.** MEASURED: output is compact
    (`{"event_type":"a","x":0.30000000000000004,...}`), keeps `é` escapes, and keeps a
    20-digit integer and a float exactly; `json.loads` of the result equals the original
    minus the key. A payload without the key comes back unchanged in content (but
    compacted). `{"account_id": null}` is found by `json_type` (`'null'`) and removed. For
    `"ip"`, `json_remove` gives `{}`; `json_set(..., NULL)` would leave `{"ip":null}`.
28. **SQLite version in production is UNVERIFIED.** The runtime image is
    `FROM python:3.12-slim` (READ, `Dockerfile:39`, a tag, not a digest). Its Debian release,
    and so its SQLite, is not recorded in the repo. JSON functions are built in from SQLite
    3.38, so any current Debian has `json_remove`. Check (free, read-only):
    `fly ssh console -a quorum-ai -C "python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'"`.
    If the function were missing, the UPDATE would raise `no such function`; the catch in
    item 8 covers it, but it would log at every start.

## G. What the wipe cannot reach

29. **Deleted bytes stay in the file.** MEASURED: 50 rows holding one key, then the UPDATE.
    SQL found 0 keyed rows, but the raw file still held **73** copies of the key. With
    `PRAGMA secure_delete=ON` on the connection: 0 copies. The default is off (MEASURED:
    `0`). Without it, the section H count reads 0 while the key is still on disk. Turning it
    on cleans only space freed from then on. Space already freed before (for example by the
    F-01 relabel's rewrites) can still hold old keys; only a `VACUUM` rewrites the whole file.
    A `VACUUM` takes an exclusive lock and needs free space about the file's size. The
    file's size and the volume's free space are UNVERIFIED (check: `ls -l /data` and
    `df -h /data` inside the machine).
30. **The rollback journal.** In `delete` journal mode the old pages are copied to a
    `-journal` file, which is deleted after the commit. The filesystem may keep those blocks
    until reused. SQLite cannot reach them. UNVERIFIED.
31. **Fly volume snapshots.** No setting or doc in the repo names snapshot retention
    (`grep -rni snapshot_retention` over `fly.toml`, `docs/`, `DEPLOY.md` prints nothing).
    Fly's documented default is a daily snapshot kept 5 days. That is from Fly's docs, not
    measured here: UNVERIFIED. Check: `fly volumes list -a quorum-ai`, then
    `fly volumes snapshots list <volume id>`. Until those snapshots age out they hold
    un-wiped keys and addresses. A restored snapshot brings them back until the next pass;
    a wipe at open re-wipes them at the first start.
32. **The in-memory cost ring.** `InMemoryCostEventRecorder` keeps up to 1,024 events with
    `account_id` (READ, `costs.py` ~668-720). It lives until eviction or the process stops.
    On a quiet machine that stays up it can hold a key longer than 48 hours. It is memory,
    not disk.
33. **Other recorders keep an account id beside the same run id.** Provider, synthesis,
    debate, model slot, safety and evaluation rows write `account_id` into the same table
    (READ: `providers.py:720`, `synthesis.py:455`, `debate.py:947`, `model_slots.py:208`,
    `safety.py:231`, `query_run_orchestration.py` ~1966-1969 for the evaluation recorder).
    Sign-in events are NOT in this table: `google_signin.py` writes them to
    `sessions.sqlite3`'s `sign_in_events` (`session_store.record_sign_in_event`), kept 30 days
    and at most 10 rows per account and deleted with the account (corrected in review round
    1; this item first listed sign-in rows here). They carry the session's account id, not the
    spend key, so an anonymous network's key does not survive there. But for a signed-in
    account created before W7 the spend key IS the account id (READ, `session_store.py:472`,
    `UPDATE accounts SET spend_key = account_id`), so that key stays, unwiped, on every
    non-cost row of that account. `run_history.sqlite3` keeps an `account_id` per run in its
    `runs` table (READ, `run_history_store.py:147`), same consequence. This is outside CHG-044's
    words. It should be reported to the owner, not widened silently.
34. **Sentry and logs.** A blocked or ceiling-degraded run sends `account_id` to Sentry
    (READ, `costs.py` ~1483). How long Sentry keeps it is "not yet asked" (docs/48 rows 13,
    14). A grep of log calls for `account_id`, `client_ip` and `spend_key` arguments found
    none; multi-line log calls were not fully checked: UNVERIFIED.
35. **The session row keeps its account id.** CHG-044 (b) wipes the address only. The
    `session_minted` row keeps the session's random account id in its column (READ, ~1749).
    With the address gone it links to no network.

## H. The production check

36. **The count now that every cost row is in scope** (not only anonymous ones). Run inside
    the machine, read-only (`mode=ro`), autocommit, one statement, counts only. Never leave
    an interactive `sqlite3` shell open on the file: item 10 measured an open read
    transaction making a billed write fail.

    ```python
    import sqlite3
    c = sqlite3.connect("file:/data/feedback_events.sqlite3?mode=ro", uri=True)
    old = "julianday(recorded_at) < julianday('now', ?)"
    has_key = ("(account_id IS NOT NULL OR CASE WHEN json_valid(payload) "
               "THEN json_type(payload, '$.account_id') IS NOT NULL ELSE 0 END)")
    has_ip = "CASE WHEN json_valid(payload) THEN json_type(payload, '$.ip') IS NOT NULL ELSE 0 END"
    mint = "recorder = 'session' AND event_type = 'session_minted'"
    q = {
        "cost_keyed_past_cut": f"recorder = 'cost' AND {old} AND {has_key}",
        "mint_addressed_past_cut": f"{mint} AND {old} AND {has_ip}",
        "cost_rows_past_cut": f"recorder = 'cost' AND {old}",      # partner: expect >= 142
        "mint_rows_past_cut": f"{mint} AND {old}",                  # partner: expect >= 70
        "malformed_payloads": "recorder IN ('cost', 'session') AND NOT json_valid(payload)",
    }
    for name, where in q.items():
        args = ("-50 hours",) if "?" in where else ()
        print(name, c.execute(f"SELECT COUNT(*) FROM events WHERE {where}", args).fetchone()[0])
    ```

    MEASURED on a toy database (one keyed cost row, one addressed mint row and one malformed
    cost row, all 3 days old): it printed `1, 1, 2, 1, 1` and did not raise on the malformed
    row. It has not been run in production.

    Expect the first two to read 0 and the two partners to read at least 142 and 70. A zero
    with an empty partner proves nothing. The cut is 50 hours, not 48: with a throttled
    pass (T = 1 hour, say), rows between 48 and 49 hours old may legitimately still hold a
    key. Use 48 hours + T + a margin, and also print the 48-hour figure for information. A
    positive partner that newer rows are untouched (cost rows under 24 hours old holding a
    key) is only proof if there has been traffic in the last day.
37. **The wipe must have RUN before the check can read 0.** With a wipe at open, the deploy
    itself triggers it: `strategy = "rolling"` starts a new process, which opens the store at
    import. Even the `fly ssh console` session used for the check starts a stopped machine,
    which opens the store and wipes. So a 0 cannot tell "wiped at this start" from "wiped
    all along". With a write-path or timer trigger alone, nothing runs until traffic or the
    timer fires, and the check can read non-zero after a good deploy. Have each pass log one
    INFO line with counts only (rows changed per table, malformed rows counted), and read it
    in `fly logs` after the deploy. The Fly log ring holds about 100 lines (READ, `fly.toml`
    comment), so read it soon after the deploy.

## I. Docs that state the old retention

38. **Sweep: 9 files to update, plus about 10 code comments.** Found with
    `grep -rn "W55\|deletes cost-ledger\|outlives the 24\|Nothing prunes\|append-only\|retention policy"`
    over `docs/` and `src/` (archive and dated analysis files left as history):
    - `docs/48-data-retention.md` row 13: "Nothing in `src/` deletes cost-ledger rows, so it
      outlives the 24 hours there"; status "Pending approval: how long the ledger ... not yet
      asked". CHG-044 (a) has now decided the signed-in key's ledger keep: 48 hours.
    - `docs/48-data-retention.md` row 14: the same sentence; status "not yet built (board
      row W55)".
    - `docs/48-data-retention.md`: a NEW row for the visitor's address in session-mint rows
      (CHG-044 (b)); `grep -n -i "mint\|session_minted" docs/48-data-retention.md` prints
      nothing today. State the real bound from item 4, the invite-key note (item 23), and
      what the wipe cannot reach (section G).
    - `docs/65-open-work.md:152`, board row W55: UNPINNED, and its text says anonymous rows
      only. It needs a needle the build adds or deletes.
    - `docs/adr/0163-nothing-private-reaches-sentry.md:144`: "How long the ledger keeps a
      signed-in account's key ... has not yet been asked". Now decided.
    - `docs/adr/0132-the-session-limits-count-the-visitor.md:91`: "Nothing prunes that table
      ... each new-session row keeps the visitor's address (or /64) with no end date". False
      after the wipe.
    - `docs/adr/0144-*.md:76`: rejected alternative "Writes a visitor's address into rows
      nothing deletes". History; a pointer may help.
    - `docs/runbooks/feedback-store-schema-migration.md:357`: "no pruning, retention policy
      or `VACUUM` anywhere in `src/`". "Retention policy" becomes false. This runbook is also
      the natural home for the section H check.
    - `docs/23-data-model.md:80`: "The opener is not read-only ... always runs the migration
      check". With a wipe at open it also rewrites rows.
    - Code comments calling the sink "append-only" or saying nothing prunes it:
      `feedback_store.py:9, 209, 350, 1207, 1686`, `query_run_orchestration.py:1094`,
      `costs.py:1694`, `query_runs.py:966`, `main.py:759`, `run_history_store.py:14`; and
      ADR-0002:11 and ADR-0016:53 ("the sink stays append-only"). The wipe updates rows in
      place, so "append-only" needs a qualifier ("rows are never deleted; keys are wiped
      after 48 hours"), not a rewrite of history.
    - Not to edit: `docs/19` CHG-033 (c) and CHG-044 (owner records),
      `docs/analysis/2026-10-13-security-review.md` (line 405 only orders W55), and the dated
      analysis files `2026-09-25-w30-visitor-address-failure-modes.md:66` and
      `2026-07-30-extraction-ledger.md:254`.

## Recommended trigger design

One method, `wipe_expired_keys(now=None) -> (cost_rows, mint_rows, malformed)`, called from
three places, each outside every money lock hold:

1. **At store open**, after the two backfills, inside its own `try`. Never raises; logs a
   WARNING on failure. This covers every start, every deploy, every reconnect, and every
   snapshot restore.
2. **From `record_event()`**, after its insert, throttled by the monotonic clock to once per
   hour. This covers a machine that stays up with query traffic.
3. **After `try_record_session_mint` returns** (in `auth.issue_session`, outside the lock),
   with the same throttle. This covers a machine that stays up with only new visitors.

Each pass: one `BEGIN IMMEDIATE` transaction; `PRAGMA secure_delete=ON` on the connection;
NULL the column for every eligible row; `json_remove` only where `json_valid`; restrict to
rows that still hold a key; a strict 48-hour cut on the wipe's own injectable clock; one INFO
line with counts; leave the write-health stamps alone. Bound to state in docs/48: "48 hours,
while the app runs, until the first write at least an hour after the previous pass (about
one hour more with steady traffic, until the next write with none); while the machine is
stopped, until its next start; and up to the volume snapshot retention (UNVERIFIED, Fly's
default is 5 days) in snapshots." (Corrected in review round 1: this said "up to about one
hour more while the app runs", which is false when the app runs without writes.)

Tests this needs, each with what turns it red:
- A cost row 47 h 59 m old keeps its key and still counts in `daily_spend_for`; one 48 h 1 s
  old loses both the column and the payload key. Red if the cut is dropped or moved.
- `daily_spend_for` and `global_daily_spend` read the same before and after a pass. Red if
  the wipe touches a row inside 24 hours.
- A second pass changes 0 rows. Red if the "still holds a key" condition is removed.
- One malformed payload does not stop the other rows being wiped, and its column key is
  still NULLed. Red if `json_valid` guards the column too, or is removed. (Since review
  round 2 its text is replaced with a fixed marker too, in cost and mint rows alike.)
- A read-only database still opens, and the wipe's failure changes no charge outcome. Red
  if the wipe's `try` is removed.
- A wipe that raises inside the charge path never bumps `lost_billed_writes`. Red if the
  wipe is moved into `record()`.
- The raw file holds no copy of a wiped key. Red if `secure_delete` is dropped.
