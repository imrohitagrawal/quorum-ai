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

A third line comes from the *call site*, not the store, and means something
much bigger — see "Locked database" below:

```
feedback_store: could not open SQLite sink, persistence disabled: %s
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

- Reads keep working. The daily spend cap still queries `daily_spend_for`.
- Writes fail per event and are swallowed with
  `feedback_store: failed to persist event recorder=%s type=%s: %s`. The audit
  trail gains no new rows.
- The pre-F-01 rows stay as they were, so affected accounts remain
  over-metered — bounded to the 24 h rolling window `daily_spend_for` reads.

**Action.** Restore write access to the volume, then **restart the machine**.
The migration is retried on the next store *open*, not continuously — nothing
re-attempts it inside a running process. Re-run the read-only checks above and
confirm the marker now exists.

## Failure mode: locked database

"Locked" is not one case. SQLite has more than one lock level, and which one
the *other* connection holds decides whether the app gets no store at all, or
a store that boots and runs fine minus one migration. **Tell the two apart by
which `WARNING` appears** — not by the word "locked" in isolation:

| Appears | Does *not* appear | Case |
| --- | --- | --- |
| `could not open SQLite sink, persistence disabled: database is locked` | `F-01 preview backfill did not run` | (a) EXCLUSIVE — no store at all |
| `F-01 preview backfill did not run: … database is locked` | `could not open SQLite sink` | (b) RESERVED — store is fine, only the migration was skipped |

### (a) EXCLUSIVE lock — no store at all

**Symptom.** On boot, `WARNING feedback_store: could not open SQLite sink,
persistence disabled: database is locked`, roughly 5 s after the store open is
attempted — Python's `sqlite3.connect` default `timeout` of 5.0 s, which
`FeedbackStore` does not override. **No** `F-01 preview backfill did not run`
warning — the migration runner is never reached.

**What it means — this is worse than the read-only case, and worse than the
source docstring implies.** An EXCLUSIVE hold by another connection blocks
even reads, so the unguarded `self._conn.executescript(self._SCHEMA)` in
`__init__` raises `sqlite3.OperationalError: database is locked` *before* the
best-effort migration runner is entered — even though every statement in
`_SCHEMA` is `IF NOT EXISTS` and would otherwise be a no-op. The constructor
therefore never returns. The app does **not** crash — `main.py` wraps the
construction in `try/except Exception` — but it starts with **no store at
all**:

- `feedback_store.get_store()` returns `None` for the lifetime of the process.
- Every `record_event` call is a silent no-op. **Nothing is persisted**, not
  just the migration.
- `costs.py` guards the daily spend cap with `if store is not None:` — so with
  no store the **24 h per-account daily cap is skipped entirely**. This is the
  headline operational consequence: a spend guard is silently absent.
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
   `/data/feedback_events.sqlite3`. Close it.
2. Restart the machine. The store is a process-wide singleton configured once at
   import; there is no reconnect path.
3. Confirm recovery by the presence of the store, not by the absence of the
   warning: the marker checks above should succeed and new `events` rows should
   appear after a query run.

**Known code/doc discrepancy.** `_backfill_f01_preview_rows`'s docstring says a
"read-only or locked DB leaves the rows as they were … the repair still lands
the moment the volume is writable again". That is accurate for read-only and
inaccurate for the EXCLUSIVE case, in both halves: it loses the whole sink
(not just the repair), and nothing lands until the process is restarted. Only
the read-only path has a test; the EXCLUSIVE path has none. Filed as a
follow-up; this runbook documents the measured behaviour, not the docstring's
claim.

### (b) RESERVED lock — store opens fine, only the migration is skipped

**Symptom.** On boot, `WARNING feedback_store: F-01 preview backfill did not
run: database is locked`. **No** `could not open SQLite sink` warning.

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
best-effort `except`. Measured directly against the two lock levels
(`tests/scratch_docsfix` during doc review, since neither this runbook nor
the source has a test for either lock case today):

- `feedback_store.get_store()` returns a **working** store — this is not the
  same failure as (a).
- The F-01 migration did not run this boot; no marker row appears in
  `schema_migrations`.
- The daily spend cap keeps working (`store is not None`), reading whatever is
  already on disk — same as the read-only case, affected accounts stay
  over-metered for the 24 h window, nothing more.
- Ordinary `record()` calls made *while the RESERVED lock is held* also fail
  and are swallowed one event at a time
  (`feedback_store: failed to persist event recorder=%s type=%s: %s`), and
  resume succeeding the moment the other connection commits or rolls back —
  no restart needed for that half, unlike case (a).

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
