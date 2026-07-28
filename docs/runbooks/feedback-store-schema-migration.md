# Runbook: feedback-store schema migrations (`schema_migrations`)

Covers the durable SQLite store at `/data/feedback_events.sqlite3` on the Fly
volume, and the once-only migrations recorded in its `schema_migrations` table
(today: `f01_preview_billing_relabel`, shipped with F-01 / PR #95).

The schema itself — DDL, the F-01 migration's selection and rewrite, and why it
is marker-guarded — is documented in
[`docs/23-data-model.md`](../23-data-model.md), section
**"Shipped durable stores (SQLite)"**. This runbook is the operator half: what
happens on boot, what the signals mean, and what to do when the volume is not
writable.

---

## What happens on boot

The migration runner is invoked from `FeedbackStore.__init__`, so it runs on
**every** store open. In order:

1. `_SCHEMA` is executed unguarded — the `events` table plus its two indexes,
   all `IF NOT EXISTS`, so on an existing database this is a no-op needing no
   write.
2. The migration runner opens a best-effort `try`, executes
   `CREATE TABLE IF NOT EXISTS schema_migrations …`, and checks for the marker
   row.
3. If the marker is present it returns immediately. Otherwise it runs the
   migration and the marker insert inside one `BEGIN IMMEDIATE` transaction,
   `ROLLBACK` on any error.

Only the first open after a new migration is added rewrites data. Every later
open is the `IF NOT EXISTS` DDL plus one primary-key `SELECT` against
`schema_migrations`.

**Who opens the production database.** On the Fly machine, only the app
process, once, at startup (`main.py`). There is no other opener: the nightly
`feedback-audit.yml` workflow runs on `ubuntu-latest`, not on the machine, and
does not set `FEEDBACK_DB_PATH` — so its `FeedbackStore.from_env()` calls open
`.data/feedback_events.sqlite3` inside a fresh checkout, a different and empty
database. In practice that means **the F-01 migration ran exactly once on
`/data/feedback_events.sqlite3`, at the first app boot after the F-01 deploy**,
and it will not be retried without a machine restart.

## Signals, and the one that lies by omission

Two log lines, quoted verbatim from `src/product_app/feedback_store.py`:

| Level | Message | Emitted when |
| --- | --- | --- |
| `INFO` | `feedback_store: relabelled %s pre-F-01 estimate-preview rows from cost_guardrail_accepted to cost_estimate_previewed` | **Only when ≥ 1 row was repaired** |
| `WARNING` | `feedback_store: F-01 preview backfill did not run: %s` | The repair was attempted and raised |

> ⚠ **The absence of the `INFO` line does not mean the migration did not run.**
> It sits behind an `if relabelled:` guard, so a migration that ran, matched
> zero rows and wrote its marker logs **nothing at all** — which is the normal
> steady state on every boot after the first. The marker row in
> `schema_migrations` is the only reliable evidence. Do not infer status from
> the log.

Two more lines come from the *call sites*, not the store, and mean something
much bigger — see "Locked database" below. Both are `ERROR`:

```
feedback_store: could not open SQLite sink — persistence is disabled AND the
per-account 24h daily spend cap will not be enforced for the life of this
process (no reconnect path; restart once the database is reachable): %s
```

```
costs: feedback store unavailable, so the USD 0.20 per-account 24h daily spend
cap is NOT being enforced — every estimate is passing the cap check unmetered.
… Repeats suppressed for 60.0s.
```

## Confirming the migration landed (read-only, $0)

The runtime base image is `python:3.12-slim` (`Dockerfile`), so `python3` is in
the container and the snippet below needs nothing but the standard library.
Open an interactive shell and paste it.

Use the `mode=ro` URI. A plain read-write `sqlite3.connect` against the live
production database takes locks and can create a `-journal` sidecar on the
volume the app is actively writing — and, per "Locked database" below, holding
a lock against this file yourself risks becoming case (a) or (b) for the *next*
process that opens it, up to and including silently disabling the daily spend
guard (case (a)). (A raw `sqlite3.connect` does *not* apply the migration —
only `FeedbackStore.__init__`/`FeedbackStore.from_env()` do that, since only
they run the migration check — but there is no reason to take the write path
to read a handful of counts.)

```bash
fly ssh console --app quorum-ai
```

```bash
python3 - <<'EOF'
import sqlite3
c = sqlite3.connect("file:/data/feedback_events.sqlite3?mode=ro", uri=True)
q = lambda s: c.execute(s).fetchall()
print("marker      :", q("SELECT name, applied_at FROM schema_migrations"))
print("unrepaired  :", q("SELECT COUNT(*) FROM events WHERE recorder='cost'"
                         " AND event_type='cost_guardrail_accepted'"
                         " AND query_run_id IS NULL"))
print("billed      :", q("SELECT COUNT(*) FROM events WHERE recorder='cost'"
                         " AND event_type='cost_guardrail_accepted'"))
print("billed w/run:", q("SELECT COUNT(*) FROM events WHERE recorder='cost'"
                         " AND event_type='cost_guardrail_accepted'"
                         " AND query_run_id IS NOT NULL"))
print("disagreeing :", q("SELECT COUNT(*) FROM events"
                         " WHERE json_extract(payload,'$.event_type') <> event_type"))
EOF
```

Every count except the last is scoped to `recorder='cost'`, matching
`_F01_PREVIEW_SELECT` and `daily_spend_for` — both of which filter on the
recorder as well as the event type. A `cost_guardrail_accepted` row from a
different recorder is not a charge and not a migration target.

| Check | Healthy answer |
| --- | --- |
| `marker` | exactly one row, `f01_preview_billing_relabel`, with an `applied_at` timestamp |
| `unrepaired` | `0` — nothing left for the migration to fix |
| `billed` vs `billed w/run` | **equal** — every row still counted as a charge is attached to a real run |
| `disagreeing` | `0` — no row's `payload` contradicts its `event_type` column |

`json_extract` needs SQLite's JSON1 extension, which is compiled in by default
in the image's `libsqlite3`. If it errors, drop that last check rather than
opening the database read-write to work around it.

### What it looked like in production

Measured read-only against `/data/feedback_events.sqlite3` on prod
`build_sha` `025bd83` (operator session, 2026-07-27):

| Check | Measured |
| --- | --- |
| Marker | `f01_preview_billing_relabel`, `applied_at` `2026-07-27T15:53:58.869968+00:00` |
| Remaining `cost_guardrail_accepted` with NULL `query_run_id` | 0 |
| Surviving `cost_guardrail_accepted` rows | 16, **all** with a non-NULL `query_run_id` |
| Rows whose payload disagrees with the column | 0 |
| Rows repaired by the migration | 18 |

That is the healthy shape: the marker exists, the unrepaired count is zero, and
every event still counted as a charge is attached to a real run.

The last row is the one number the snippet above does **not** yield — the
repaired count is not recoverable from the database after the fact, because a
relabelled row is indistinguishable from a natively-written preview (see the
rollback note in `docs/23-data-model.md`). It came from the operator's session
at the time; the durable evidence is the marker plus the three zero/agreement
counts above it.

---

## Failure mode: read-only volume

**Symptom.** On boot, `WARNING feedback_store: F-01 preview backfill did not
run: attempt to write a readonly database`. No marker row appears.

**What it means.** This is the *documented, tested* degradation
(`tests/integration/test_f01_preview_billing_backfill.py::test_read_only_database_degrades_to_pre_backfill_behaviour_instead_of_failing_to_boot`).
The store still opens — `_SCHEMA`'s statements are no-ops on an existing
database — so:

- Reads keep working — the store object is real and its health query succeeds.
  MEASURED 2026-07-28 with the DB file *and* its directory `chmod`-ed
  unwritable. Before issue #109 `/status` therefore reported the fully green
  `feedback_db: "connected"` throughout the fault; it now reports
  `feedback_db: "degraded"` with `feedback_writes: "failing"` from the first
  swallowed write onward. Between boot and that first write attempt the honest
  answer is `feedback_db: "connected"`, `feedback_writes: "unverified"` —
  nothing has been lost yet, because the first event that *could* be lost is
  the one that flips the signal.
- Writes fail per event and are swallowed with
  `WARNING feedback_store: failed to persist event recorder=%s type=%s:
  attempt to write a readonly database`. The audit trail gains no new rows, and
  nothing replays them later — `record` has no retry and no queue.
- The pre-F-01 rows stay as they were, so the spend already on disk is
  over-counted — bounded to the 24 h rolling window `daily_spend_for` reads.
- **But the larger effect runs the other way: the ledger freezes and the daily
  spend cap silently stops firing.** `cost_guardrail_accepted` rows are among
  the swallowed writes, so `daily_spend_for` keeps returning the total from
  before the fault no matter how much is spent during it. MEASURED (re-measured
  2026-07-28): charges each worth a quarter of `DAILY_CAP_USD` → `daily_spend_for`
  still `0` and `threshold_action` `allow` with a confirmation token minted,
  where without the fault the **fifth** such charge is the one that `BLOCK`s.
  (Not the fourth — the guard is a strict `already_spent + estimated >
  DAILY_CAP_USD`, so four quarter-cap charges land the ledger exactly *on* the
  cap without exceeding it. An earlier revision of this runbook said "four";
  the boundary is now pinned by
  `tests/integration/test_feedback_store_write_failures.py::test_block_lands_on_the_fifth_quarter_cap_charge_not_the_fourth`.)
  Case (a)'s loud bypass ERROR still does not fire here — `store is not None` —
  but since issue #109 `record` raises its own rate-limited ERROR naming the
  disarmed cap, and `/status` reports `feedback_db: "degraded"` with
  `feedback_writes: "failing"` instead of the old bare `connected`. Net
  direction is **under**-metering: free spend, permanently lost from the audit
  trail.
- Recovery is *not* automatic even after `chmod`. MEASURED: SQLite opened the
  file `O_RDONLY`, so the existing handle keeps failing every write once the
  volume is writable again; a **fresh** open (i.e. a process restart) writes
  normally. The charges swallowed during the fault are still absent afterwards.

**Action.** Restore write access to the volume, then **restart the machine** —
the restart is required for writes at all, not just for the migration. The
migration is likewise retried on the next store *open*, not continuously —
nothing re-attempts it inside a running process. Re-run the read-only checks
above and confirm the marker now exists and that new `events` rows appear.
Alert on `/status` `feedback_writes == "failing"` and on the `feedback_store:
a BILLED cost event ... was NOT persisted` ERROR (issue #109, rate-limited to
one per 60 s so it keeps re-firing for the length of the outage rather than
decaying to a single line). Treat either, or a sustained run of the
`failed to persist event` WARNING, as a spend-guard outage. Before issue #109
that WARNING was the ONLY signal this fault produced once the F-01 marker was
applied — the production steady state: MEASURED 2026-07-28, a read-only open
against an already-marked database emitted no record at all at open time, and
still does not. Before the marker is applied you also get the boot `F-01
preview backfill did not run` WARNING in the Symptom above, but that one fires
once, at the open, and does not repeat for as long as the fault lasts.

## Failure mode: locked database

"Locked" is not one case. SQLite has more than one lock level, and which one
the *other* connection holds decides whether the app gets no store at all, or
a store that *opens* but whose writes are swallowed for as long as the lock is
held — the ledger freezes and the daily spend cap silently stops firing.
**Neither case is benign: MEASURED 2026-07-28, the per-account 24 h daily spend
cap stops being enforced in both.** They differ in blast radius and in
recovery, not in whether money leaks. **Tell the two apart by which boot record
appears — and note the two sit at different log levels: case (a) is an `ERROR`,
case (b) a `WARNING`.** Grep for the message text across both levels, never for
one level alone: filtering on `WARNING` matches only case (b) and hides case
(a) entirely — and do not read case (b)'s lower log level as a lower severity.
Do not triage on the word "locked" in isolation either — it appears in both.

| Appears | Does *not* appear | Case |
| --- | --- | --- |
| `ERROR feedback_store: could not open SQLite sink — persistence is disabled AND the per-account 24h daily spend cap will not be enforced … database is locked` | `F-01 preview backfill did not run` | (a) no store at all — EXCLUSIVE, **or** RESERVED on a database with no schema yet |
| `F-01 preview backfill did not run: … database is locked` | `could not open SQLite sink` | (b) RESERVED on an already-schema'd database — the store *opens*, but every write made while the lock is held is swallowed: the ledger freezes and the spend cap silently stops firing. Writes resume by themselves once the holder releases (no restart needed, unlike (a)); the events lost in between never come back |

Case (a) also produces, at most once a minute for as long as the process
lives, `ERROR costs: feedback store unavailable, so the USD 0.20 per-account
24h daily spend cap is NOT being enforced …`. That record is the one to alert
on: it fires from the money path itself, so it is present even if the boot log
has already rotated away.

### (a) No store at all — EXCLUSIVE, or RESERVED before the schema exists

**Symptom.** On boot, `ERROR feedback_store: could not open SQLite sink —
persistence is disabled AND the per-account 24h daily spend cap will not be
enforced …: database is locked`, roughly 5 s after the store open is attempted
(MEASURED 5.37 s — Python's `sqlite3.connect` default `timeout` of 5.0 s, which
`FeedbackStore` does not override). **No** `F-01 preview backfill did not run`
warning — the migration runner is never reached.

**Which lock levels land here.** EXCLUSIVE always. RESERVED **also** lands here
when the database has no schema yet — see case (b) for why that is not the
contradiction it looks like.

**What it means — this is worse than the read-only case.** An EXCLUSIVE hold by
another connection blocks even reads, so the unguarded
`self._conn.executescript(self._SCHEMA)` in `__init__` raises
`sqlite3.OperationalError: database is locked` *before* the best-effort
migration runner is entered — even though every statement in `_SCHEMA` is
`IF NOT EXISTS` and would otherwise be a no-op. (A RESERVED hold on a
database with no `events` table yet gets there by the other route: on a fresh
file those statements are real writes.) The constructor therefore never
returns. The app does **not** crash — `main._configure_feedback_store` wraps
the construction in `try/except Exception` — but it starts with **no store at
all**:

- `feedback_store.get_store()` returns `None` for the lifetime of the process.
- Every `record_event` call is a silent no-op. **Nothing is persisted**, not
  just the migration.
- `costs.py` guards the daily spend cap with `if store is not None:` — so with
  no store the **24 h per-account daily cap is skipped entirely**. This is the
  headline operational consequence: a spend guard is absent. As of P1 / issue
  #101 it is no longer *silently* absent — the boot `ERROR` above names it, and
  `costs` repeats it at `ERROR` at most once a minute for as long as the
  process serves estimates. The behaviour is unchanged and deliberately so:
  the decision taken in the working session on issue #101's "operator decision
  required" item (item 3) is **loud only, do not fail closed**, because denying
  every priced request on a storage fault is the worse outage. **That decision
  is not yet recorded in a durable artifact** — as of this writing #101 carries
  no comment stating it, and no PR references it — so it lives here and in the
  `costs.py` comment until it is written onto the issue. Fail-closed was
  considered and declined; do not reintroduce it as a "fix" without reopening
  that decision.
- `/status` reports `feedback_db: "disconnected"` — reserved for exactly this
  fault. A store that is present but whose health query raises reports
  `"error"` instead, and one that is present and readable but cannot write
  reports `"degraded"` (issue #109); do not confuse the three. `feedback_writes`
  is `"failing"` here too: with no store, events are definitively not landing.
- Anything else that calls `FeedbackStore.from_env()` — the
  `feedback_audit` entry points `_load_events_by_recorder` and
  `generate_status_md` — does so **unguarded** and would raise outright. On the
  Fly machine nothing does (see "Who opens the production database"), so this
  matters only if you run the audit against the volume by hand, e.g. via
  `fly ssh console` with `FEEDBACK_DB_PATH` pointed at `/data`.

**Action.**

1. Find the lock holder. A true EXCLUSIVE hold blocks reads too, so it is
   rarer than case (b) below — look for another connection mid-`VACUUM`,
   mid-commit, or one that issued an explicit `BEGIN EXCLUSIVE` against
   `/data/feedback_events.sqlite3`. Close it. If the volume is brand new and
   the file has no `events` table yet, an ordinary uncommitted
   `BEGIN;`/`UPDATE` (RESERVED) is enough to land here too — check for that
   before concluding the holder must be doing something exotic.
2. Restart the machine. The store is a process-wide singleton configured once at
   import; there is no reconnect path.
3. Confirm recovery by the presence of the store, not by the absence of the
   warning: the marker checks above should succeed and new `events` rows should
   appear after a query run.

**Code/doc discrepancy — CLOSED (P1 / issue #101).**
`_backfill_f01_preview_rows`'s docstring used to say a "read-only or locked DB
leaves the rows as they were … the repair still lands the moment the volume is
writable again", which was accurate for read-only and wrong for the locked
case in three ways: the whole sink is lost (not just the repair), the account
ends up **under**-metered rather than over-metered because the spend cap is
skipped, and nothing lands until the process is restarted. The docstring now
states the per-fault matrix, and both lock levels are covered by
`tests/integration/test_feedback_store_locked_database.py`:

| Test | Pins |
| --- | --- |
| `test_exclusive_lock_on_a_fresh_database_prevents_the_store_from_opening` | EXCLUSIVE, fresh DB → raises; no backfill warning |
| `test_exclusive_lock_still_blocks_when_the_schema_is_already_present` | EXCLUSIVE blocks readers too, so an existing schema does not save the open |
| `test_reserved_lock_on_a_fresh_database_also_prevents_the_store_from_opening` | RESERVED, fresh DB → **also** raises |
| `test_reserved_lock_with_the_migration_applied_opens_cleanly_and_enforces_the_cap` | the benign case, and that the cap really does BLOCK with a store |
| `test_reserved_lock_with_the_migration_unapplied_opens_but_skips_the_migration` | exactly one backfill warning, marker still absent |
| `test_boot_against_a_locked_database_logs_an_error_naming_the_skipped_cap` | the app boots, `get_store()` is `None`, exactly one ERROR naming the cap |
| `test_missing_store_skips_the_daily_cap_and_logs_it_once_per_window` | the cap is skipped, the estimate is unchanged, one ERROR per minute |

The read-only path is covered separately by
`tests/integration/test_f01_preview_billing_backfill.py`.

### (b) RESERVED lock on an already-schema'd database — the store opens, but its writes are swallowed while the lock is held

**Symptom.** On boot, `WARNING feedback_store: F-01 preview backfill did not
run: database is locked`. **No** `could not open SQLite sink` ERROR, and **no**
`costs: … daily spend cap is NOT being enforced` ERROR.

**What it means — this is the case the "Find the lock holder" step above is
actually describing when the holder is a `sqlite3` shell.** A RESERVED lock
(taken by any connection that has issued `BEGIN` and a write statement, e.g. an
operator's `sqlite3` shell that ran `BEGIN;` then an `UPDATE`, and never
`COMMIT`/`ROLLBACK`) blocks *other writers* but not readers, and not
`CREATE TABLE IF NOT EXISTS`/`SELECT`s against objects that already exist. So
`self._conn.executescript(self._SCHEMA)` in `__init__` **succeeds** — it is a
no-op on an existing database, exactly as designed — and the store
constructs normally. Only `_backfill_f01_preview_rows`'s
`self._conn.execute("BEGIN IMMEDIATE")` needs a write lock, and that is the
one call that raises `database is locked` and is caught by its own
best-effort `except`.

> **"RESERVED is benign" holds ONLY once the schema exists.** On a fresh
> database every statement in `_SCHEMA` is a real write, so a RESERVED hold
> blocks `executescript` and the open fails exactly like case (a) — spend cap
> and all. MEASURED, and pinned by
> `test_reserved_lock_on_a_fresh_database_also_prevents_the_store_from_opening`.
> First boot against a brand-new volume is precisely when a maintenance shell
> is most likely to be attached, so treat "RESERVED" as mild only after
> confirming the `events` table is already there.

Measured directly against both lock levels, with a real second connection
holding a real `BEGIN EXCLUSIVE` / `BEGIN IMMEDIATE`, in
`tests/integration/test_feedback_store_locked_database.py`:

- `feedback_store.get_store()` returns a **working** store — this is not the
  same failure as (a).
- The F-01 migration did not run this boot; no marker row appears in
  `schema_migrations`.
- Ordinary `record()` calls made *while the RESERVED lock is held* fail and are
  swallowed one event at a time
  (`WARNING feedback_store: failed to persist event recorder=%s type=%s: %s`),
  and resume succeeding the moment the other connection commits or rolls back —
  no restart needed for that half, unlike case (a). Nothing replays the events
  lost in between; `record` has no retry and no queue.
- **The daily spend cap therefore stops firing.** `store is not None`, so
  `costs.py` takes the metered branch and `_log_daily_cap_bypassed` never
  runs — but the `cost_guardrail_accepted` rows that *are* the meter are among
  the swallowed writes, so `daily_spend_for` keeps reading a **frozen ledger**:
  the total stays at whatever was on disk when the lock was taken, and every
  charge made during the hold is lost for good. This is **under**-metering (free
  spend), not the over-metering of a skipped migration. MEASURED (reviewer probe
  reproduced 2026-07-28): charges each worth a quarter of `DAILY_CAP_USD`
  recorded under a `BEGIN IMMEDIATE` hold → `daily_spend_for` still `0` and
  `threshold_action` `allow` with a confirmation token minted, where without the
  lock the **fifth** such charge is the one that `BLOCK`s. (Not the fourth —
  see the read-only section above for the strict-`>` arithmetic; an earlier
  revision of this runbook said "four".)
- **Since issue #109 this is no longer silent.** `record` now keeps two
  monotonic write-health stamps and emits a rate-limited (one per 60 s) ERROR —
  `feedback_store: a BILLED cost event ... was NOT persisted` — whenever a
  `cost`/`cost_guardrail_accepted` write is lost, and `/status` reports
  `feedback_db: "degraded"` with `feedback_writes: "failing"`. It is still true
  that case (a)'s `costs:` bypass ERROR does **not** cover this case (`store is
  not None`), and that `product_app.main` logs nothing, so do not treat "no
  cap-bypass ERROR" as "the cap is enforced" — watch `feedback_writes` and the
  `feedback_store:` ERROR instead. The per-event `failed to persist event`
  WARNING is still emitted once per swallowed write, unrated, for the other
  (telemetry) event types. Because the RESERVED hold is the self-clearing
  shape, `feedback_writes` returns to `ok` on its own after the first write
  that lands once the lock is released — the events lost in between are still
  gone.

**Action.**

1. Find the lock holder — almost always a manual `sqlite3` shell left open in
   `fly ssh console` with an uncommitted `BEGIN`/`UPDATE`, or an interrupted
   maintenance script. `COMMIT` or `ROLLBACK` it (or kill the process).
2. Ordinary writes resume on their own once the lock clears — no restart
   required for that. The migration itself is **not** retried automatically
   (`_backfill_f01_preview_rows` only runs from `__init__`); if getting
   `schema_migrations` populated now matters, restart the machine so the next
   `__init__` gets a clear lock.
3. Confirm recovery: new `events` rows appear right away once the lock is
   released; the marker row only appears after the restart in step 2.

## Adding the next migration

- Give it a new `name` and add it to the runner **inside** the guarded block —
  never to `_SCHEMA`. A new `CREATE TABLE` in `_SCHEMA` breaks the first open of
  a read-only database and converts a skipped repair into a dead sink.
- Keep the data rewrite and the marker insert in the same transaction, so a
  crash cannot leave the database half-migrated and marked.
- Record a rollback note, or a documented reason rollback is not safe, in
  `docs/23-data-model.md` `### Applied migrations` — `docs/23-data-model.md`
  `## Migration Strategy` requires it.
- Ask whether the migration's `WHERE` clause is a policy nothing enforces on the
  write side. If so it **must** be marker-guarded: run every boot, it would keep
  rewriting rows written after it, and if the rewrite removes spend the failure
  direction is under-metering.
