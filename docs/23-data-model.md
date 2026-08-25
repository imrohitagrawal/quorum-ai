# Data Model

## Scope

This data model is the planning baseline for Release 1. It is not a migration script. Exact column types, indexes, encryption implementation, and retention jobs must be finalized during implementation planning.

## Storage Assumption

Use a relational database for account-owned workflow state and query results. The workflow requires ownership checks, state transitions, cost records, source references, and result retrieval; relational constraints are the safest first baseline.

## Tables

| Table | Purpose | Key Fields | Classification |
|---|---|---|---|
| `accounts` | Local account reference mapped from auth provider. | `id`, `auth_subject`, `status`, `created_at` | Account data |
| `provider_credentials` | BYO OpenRouter key metadata and encrypted secret reference. | `id`, `account_id`, `provider`, `secret_ref`, `status`, `created_at`, `deleted_at` | Secret metadata; encrypted secret value stored outside plain tables where possible |
| `query_runs` | Top-level run state and ownership. | `id`, `account_id`, `query_text`, `status`, `correlation_id`, `estimated_cost_usd`, `started_at`, `completed_at` | User-provided content; operational metadata |
| `query_model_slots` | Four selected model slots for a run. | `id`, `query_run_id`, `slot_number`, `model_id` | Configuration data |
| `safety_acknowledgements` | Warning versions shown/acknowledged for a run. | `id`, `query_run_id`, `warning_type`, `warning_version`, `acknowledged_at` | Compliance/safety metadata |
| `search_attempts` | Search attempt and fallback metadata. | `id`, `query_run_id`, `slot_number`, `provider`, `status`, `fallback_used`, `latency_ms`, `error_code` | Operational metadata |
| `source_references` | Visible source links associated with answers/synthesis. | `id`, `query_run_id`, `url`, `title`, `provider`, `retrieved_at`, `attached_to_type`, `attached_to_id` | Third-party content metadata |
| `model_answers` | Per-model answer output and status. | `id`, `query_run_id`, `slot_number`, `model_id`, `status`, `answer_text`, `latency_ms`, `error_code`, `usage_json` | AI-generated content; operational metadata |
| `debate_rounds` | Round one and round two critique outputs. | `id`, `query_run_id`, `round_number`, `status`, `critique_text`, `latency_ms`, `error_code` | AI-generated content |
| `syntheses` | Final synthesized answer. | `id`, `query_run_id`, `status`, `consensus_text`, `disagreement_text`, `source_support_text`, `uncertainty_text`, `recommendation_text` | AI-generated content |
| `cost_records` | Estimated and actual provider usage cost. | `id`, `query_run_id`, `stage`, `provider`, `model_id`, `estimated_usd`, `actual_usd`, `usage_json` | Cost/operational metadata |
| `workflow_events` | Non-secret event stream for auditability and observability. | `id`, `query_run_id`, `event_type`, `created_at`, `metadata_json` | Operational metadata; no full secrets or raw provider errors |

## Classification

| Data Element | Classification | Handling |
|---|---|---|
| Query text | User-provided content; may contain sensitive data despite warnings. | Show pre-submit warning; minimize logging; include in provider calls only after accepted execution. |
| Model/debate/synthesis text | AI-generated content derived from user query and external sources. | Store for result retrieval; do not market as guaranteed correct. |
| Source URLs/titles/snippets | Third-party retrieved content. | Preserve attribution; treat as untrusted content for prompt-injection purposes. |
| Account identity | Personal/account data. | Protect with auth, account ownership checks, least-privilege access. |
| App-owned provider keys | Secret. | Secret store/environment only; never in browser, logs, prompts, or analytics. |
| BYO OpenRouter key | User secret. | Account-scoped, encrypted/secret-store backed, removable, never returned after submission. |
| Cost/latency/failure metadata | Operational metadata. | Safe for dashboards only after redaction and aggregation rules. |

## Key Constraints

- `query_runs.account_id` is required for every run.
- Only one non-terminal `query_runs` row may exist per account.
- `query_model_slots` must contain exactly four slots before a run can be accepted.
- `provider_credentials.account_id` is required for BYO keys and must be unique per active provider/account pair.
- Provider keys are not stored in logs, workflow events, model prompts, browser payloads, or source references.
- Query results must be filtered by account ownership for every read path.

## Retention

Retention is not finalized. Until product owner approval:

- Keep query text, outputs, source references, and run metadata only as long as needed for MVP result retrieval and validation.
- Do not store full prompt/output content in logs.
- Use synthetic or redacted fixtures for tests.
- Define deletion/export behavior before production launch if durable account history remains in scope.

See `docs/48-data-retention.md` for the retention decision record.

## Shipped durable stores (SQLite) — not the planning baseline above

Everything above this heading is the Release 1 **planning baseline** (see `## Scope`): a relational design that has not been built. Nothing in `## Tables` above exists as a real table today. This section is the opposite — it records the durable schema that actually ships, so the two are never confused.

Source of truth: `src/product_app/feedback_store.py`. Every DDL and log string below is quoted verbatim from it.

### Where it lives

| Environment | Path | Set by |
|---|---|---|
| Production (Fly) | `/data/feedback_events.sqlite3` | `FEEDBACK_DB_PATH` in `fly.toml` `[env]`, on the `quorum_data` volume mounted at `/data` (`[[mounts]]`) |
| Dev (default) | `.data/feedback_events.sqlite3` | `feedback_store.DEFAULT_DB_PATH`; `from_env()` creates the parent directory. `.data/` is gitignored |
| Tests | `:memory:` | `feedback_store.configure_for_tests()`, which constructs `FeedbackStore(":memory:")` |

The production path is pinned to the persistent volume deliberately: the rootfs default is wiped on every deploy, which previously erased the self-improving-loop history (issue #27, recorded in the `fly.toml` comment).

Unlike its sibling `RUN_HISTORY_DB_PATH` — which `tests/conftest.py` pins to `:memory:` for the whole suite — `FEEDBACK_DB_PATH` is **not** pinned in tests. A test that imports `product_app.main` without setting it opens the on-disk dev default; only tests that opt into `configure_for_tests()` get `:memory:`.

Ownership and concurrency are decided in [`docs/adr/0002-sqlite-single-writer-ceiling.md`](adr/0002-sqlite-single-writer-ceiling.md): one connection, one `RLock`, `journal_mode=DELETE`, no WAL. In production the application process is the **only** process that opens this file at all. There used to be a scheduled `feedback-audit.yml` GitHub Actions workflow that also called `FeedbackStore.from_env()`, but it ran on a GitHub-hosted runner with no `FEEDBACK_DB_PATH` set, so it silently audited its own empty checkout-local database rather than the volume — a green signal that meant nothing (issue #103). That workflow was removed rather than wired to a Fly credential it never had; the audit CLI (`feedback_audit.py`) still exists for a human to run by hand against the real file, per the runbook below. `run_history.sqlite3` is a sibling store on the same volume under the same ADR; its schema is out of scope here.

**The opener is not read-only.** `FeedbackStore.__init__` — reached both by the app at boot and by the audit CLI's own `feedback_audit._load_events_by_recorder` / `generate_status_md` (both call `FeedbackStore.from_env()`) — always opens an ordinary read-write `sqlite3.connect` and always runs the migration check in the same call. There is no separate read path that skips it. Whoever points `FEEDBACK_DB_PATH` at `/data` first and opens it after a migration ships is the one that applies it — app or a manually-run audit script alike (e.g. running the audit against the live file from `fly ssh console`, as the runbook's locked-database section describes).

### Tables

`events` — one row per recorder call. Created unguarded on every open (`FeedbackStore._SCHEMA`):

```sql
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorder TEXT NOT NULL,
    event_type TEXT NOT NULL,
    account_id TEXT,
    query_run_id TEXT,
    recorded_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_recorded_at_idx
    ON events (recorded_at);
CREATE INDEX IF NOT EXISTS events_recorder_idx
    ON events (recorder, event_type);
```

`schema_migrations` — the applied-migration ledger (`FeedbackStore._MIGRATIONS_DDL`):

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)
```

**Why `schema_migrations` is deliberately not part of `_SCHEMA`.** `_SCHEMA` runs unguarded in `__init__`. On an existing database every statement in it is already a no-op, so it needs no write. Adding a brand-new `CREATE TABLE` there would make the *first* open of an existing **read-only** database raise `attempt to write a readonly database` — turning "the relabel could not run" back into "Quorum does not start". So `schema_migrations` is created inside the migration runner's best-effort `try` instead. The source records this as measured, not theorised.

### Applied migrations

| Name | What it does | Rollback |
|---|---|---|
| `f01_preview_billing_relabel` | Relabels pre-F-01 estimate previews out of the billed event type | None; see below |

#### `f01_preview_billing_relabel`

Shipped with the F-01 fix (PR #95). Before that fix, `POST /v1/query-runs/estimate` — a pure preview — recorded `cost_guardrail_accepted`, the one event type both spend guards count, with a NULL `query_run_id`. The code fix stops *new* rows of that shape but is not retroactive, and this table is durable. `FeedbackStore.daily_spend_for` filters on `event_type` alone, so without the migration every preview written in the 24 h before the fix shipped keeps double-metering its account for a full rolling day afterwards — real users stay wrongly over-capped by the very bug that was just fixed.

**Selection** (`_F01_PREVIEW_SELECT`):

```sql
SELECT id, payload FROM events
WHERE recorder = 'cost'
AND event_type = 'cost_guardrail_accepted'
AND query_run_id IS NULL
```

**Rewrite.** For each matched row, both the `event_type` column and the `event_type` key inside the row's `payload` JSON are set to `cost_estimate_previewed`, via `UPDATE events SET event_type = ?, payload = ? WHERE id = ?`. Both, because the audit job keys off payload field names: a row whose column says "previewed" while its payload still says "accepted" is not an audit trail, it is two contradictory claims.

**One-shot.** A marker row is inserted with `INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)`, where `name` is `f01_preview_billing_relabel` and `applied_at` is `datetime.now(UTC).isoformat()`. Every open creates the table `IF NOT EXISTS`, then checks for the marker (`_migration_applied`) and returns immediately when it is present.

**Atomic.** The rewrite and the marker insert run inside one `BEGIN IMMEDIATE` transaction, with `ROLLBACK` on any exception. A crash mid-way leaves the database in the pre-migration state and the next open retries; there is no half-relabelled-and-marked state. `tests/integration/test_f01_preview_billing_backfill.py` pins this with a deliberately corrupt row.

**Why it is marker-guarded rather than run on every boot.** The `WHERE` clause is a *policy* ("an accepted cost event with no run id is not a charge") and nothing enforces that policy on the write side. Run unguarded on every open, it would silently zero any *future* row of that shape. That is a **fail-open spend guard**: the direction it fails in is "the account is under-metered" — free money. Applying it exactly once, over the rows that exist the first time the fixed code opens the database (pre-fix rows by construction), bounds the blast radius to the migration it is, and needs no assumption about what any later writer does.

**Rollback note** (required by `## `sessions.sqlite3` — the durable session sink (ADR-0073)

A third SQLite file on the same volume, path from `SESSION_DB_PATH`
(`fly.toml` pins it to `/data/sessions.sqlite3`; `tests/conftest.py` pins it to
`:memory:`; unset it defaults to `.data/sessions.sqlite3`). Same shape as its
two siblings under ADR-0002: one connection, one `RLock`, autocommit, no WAL.

It exists because the per-IP session **mint cap** is durable and the sessions
it counts were not, so a restart erased the visitor and kept the evidence that
they had already spent their mints. Every merge redeploys — no workflow has a
paths filter — so that restart happens daily; `fly.toml` also sets
`min_machines_running = 0`, which should stop an idle machine too (inferred
from the config, not observed).

```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_digest TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_last_used_idx
    ON sessions (last_used_at);
```

**`session_digest` is `sha256(session_id)`, and the session id itself is never
written.** The cookie is the whole credential — this app has no login — so
storing it would make read access to the volume equivalent to holding every
live visitor's cookie. `csrf_token` IS stored in clear, because it is useless
without the cookie the digest withholds; a test pins that the two secrets stay
independent, since that argument fails if either reveals the other.

**Classification.** `account_id` is a pseudonymous identifier, as elsewhere in
this document. `csrf_token` is a secret at rest. No query text, no personal
data, no IP address — the IP lives only in the `events` mint rows.

**Retention.** Rows are deleted by the 60-second `session-gc` daemon once
`last_used_at` is older than `SESSION_TTL` (2h). Expiry is ALSO a condition of
every read, so a row that outlives the process that would have purged it still
does not resolve.

**Unguarded `_SCHEMA`, unlike `feedback_store`'s new DDL, and safe here only
because this store owns its own file** — the script is that file's initial
creation rather than a new table added to an existing database. Measured on
CPython 3.12.13 / SQLite 3.50.4: an existing file whose table is already
present opens on a read-only volume without writing; a missing table on a
read-only file, and a new file in a read-only directory, both raise out of
`__init__`, where `main._configure_session_store` catches them and the app runs
on in-process sessions. **A later schema change must NOT extend `_SCHEMA`** —
it would reintroduce the second shape on an existing read-only volume. Use a
guarded `schema_migrations` block then, exactly as `feedback_store` does.

**Boot behaviour.** A failed open logs at ERROR (`session_store: could not open
the SQLite sink`) and the app serves normally with sessions that do not survive
a restart — the behaviour of every release before ADR-0073. A failed WRITE on an
open store is swallowed and logged at WARNING, with the same consequence. The
direction is deliberate: sessions are the only credential, so a storage fault
must never stop one being issued.

## Migration Strategy` below). The migration ships **no inverse and one is not safe to add**. `POST /v1/query-runs/estimate` passes `query_run_id=None, preview=True` (`query_runs.py`), which `costs.py` maps to `cost_estimate_previewed` — the exact shape the migration produces. A relabelled row and a natively-written post-fix preview are therefore **indistinguishable by content** — same `event_type`, same payload shape.

`recorded_at < applied_at` is a **probable** signal that a row was touched by the migration, not a **sound** one — it is only guaranteed correct if the migration is guaranteed to run on the very first open of the fixed code, and it is not: the runner is best-effort (see the runbook's locked-database failure modes), so a transient failure can skip it on one boot while leaving the store fully able to write. Concretely: if an earlier boot hits the RESERVED-lock case and skips the migration, the app keeps writing *native* `cost_estimate_previewed` rows with `recorded_at` timestamps before the migration eventually succeeds on a later boot and stamps `applied_at` — and those native rows then satisfy `recorded_at < applied_at` despite never having been touched by the migration. The tell that this signal might be unreliable for a given database is the same one the runbook keys off: a `feedback_store: F-01 preview backfill did not run` `WARNING` in that instance's boot history means at least one boot skipped the migration, and the timestamp test cannot be trusted for rows recorded in that window. Absent any such warning across the database's whole history, the signal holds.

An inverse would have to re-bill both the genuinely-relabelled rows and any native rows the timestamp test wrongly catches, restoring exactly the over-metering the migration exists to remove. The remedy for a bad relabel is a volume-snapshot restore, not an inverse migration.

### Boot behaviour and operator signals

The runner is invoked from `FeedbackStore.__init__`, so it runs on *every* store open. In production that is one open: the app process at startup. It is not retried inside a running process.

Log lines, verbatim (`%s` are the runtime substitutions):

| Level | Message | When |
|---|---|---|
| `INFO` | `feedback_store: relabelled %s pre-F-01 estimate-preview rows from cost_guardrail_accepted to cost_estimate_previewed` | Only when at least one row was repaired |
| `WARNING` | `feedback_store: F-01 preview backfill did not run: %s` | The repair was attempted and failed (e.g. read-only volume) |

> **Operator trap.** The `INFO` line is behind an `if relabelled:` guard. **Absence of the log line does not mean the migration did not run** — a successful migration that matched zero rows still writes its marker and logs nothing. The marker row in `schema_migrations` is the only reliable evidence.

For what a read-only or locked volume means for the operator, and for the read-only checks that confirm the migration landed, see [`docs/runbooks/feedback-store-schema-migration.md`](runbooks/feedback-store-schema-migration.md).

## Migration Strategy

- Use forward-only migrations once implementation begins.
- Migration PRs must include rollback notes or a documented reason rollback is not safe.
- Every table carrying account-owned data must include ownership and deletion/retention strategy before release.
- Seed data must be synthetic and must not contain real prompts, credentials, provider responses, or personal data.

The first migration actually applied under these rules is `f01_preview_billing_relabel`; its rollback note is in `### Applied migrations` above.
