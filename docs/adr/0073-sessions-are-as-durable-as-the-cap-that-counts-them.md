# ADR-0073: Sessions are as durable as the cap that counts them

## Status

Accepted — 2026-08-26

## Context

Two halves of one identity had opposite lifetimes.

The per-IP session **mint cap** (`auth.SESSION_MINT_CAP_PER_IP = 2` per rolling
24h) is durable on purpose. Its own comment says why: this app deploys many
times in quick succession, and an in-memory counter would silently reset the
cap on every deploy — the exact weakness the burst limiter already has and that
this mechanism exists not to repeat.

The **sessions** that cap counts were not durable. They lived in
`auth.InMemorySessionRepository`, a process dict.

So a restart erased the visitor and kept the evidence that they had already
spent their mints. The cookie in their browser resolved to nothing, and the
replacement they needed was refused. Reproduced before any code was written:

```
MINT 1 -> 200   account 2eb6dc34-eb39-4daf-afd8-e95b425817b0
MINT 2 -> 200
--- restart: in-memory repository cleared; the SQLite file untouched ---
RETURNING VISITOR /v1/session -> 429
  {"detail":{"code":"SESSION_MINT_CAP_EXCEEDED", ...}}
RETURNING VISITOR /ui         -> 429
  "This IP has reached today's limit on new sessions. ..."   (149 bytes, no HTML)
```

**This is not a deploy-only event.** `fly.toml` sets `min_machines_running = 0`
with `auto_stop_machines = "stop"`, so the machine stops whenever the app goes
idle and the next visitor arrives at a brand-new process. A live probe of
production during this work read `uptime_seconds` ≈ 15,615 (about 4.3 hours),
so the restart interval is hours, not weeks.

### Failure modes enumerated before the design (rule 16e)

This is auth code, so the list came first. The ones that shaped the design:

| Mode | Why it matters here | What the design does |
|---|---|---|
| Session fixation | A durable store makes "upsert the presented id" look natural | A presented id is only ever looked up. No path writes a row for a caller-supplied id |
| Bearer token at rest | The cookie IS the identity (no login), so volume read access would equal every live cookie | Only `sha256(session_id)` is stored; the token never is |
| Replay past expiry | A durable row outlives the process that would have purged it | Expiry is a condition of the READ, not only of the purge |
| Identity reset on restore | A restored session minting a fresh `account_id` silently resets that account's 24h spend history | The restored row carries the original `account_id`; pinned by test |
| Cap bypass by resuming | If resume is free, is the cap meaningless? | It already was free, and stays so. The bound is unchanged — see *Rejected alternatives* |
| Corrupt row | A NULL or non-UUID account id | Fails CLOSED: the row is treated as absent and a fresh session is minted |
| Read-only volume | The app must still boot and serve | Measured, below. Every unwritable shape either opens cleanly or is caught at boot |
| Concurrent writes | ADR-0002 pinned single-writer SQLite | One connection, one `RLock`, autocommit, no WAL — the same shape |
| Per-request writes | `require_session` touches on EVERY authenticated request | The write-through is throttled; ADR-0002's headroom never measured per-request load |
| Unbounded growth | Nothing prunes the sibling `events` table, and that cost is measured there | The 60s GC daemon purges both halves and reports what it deleted |

## Decision

**1. A separate `SessionStore` on its own SQLite file** (`session_store.py`),
sibling to `feedback_store` and `run_history_store`, path from
`SESSION_DB_PATH`, pointed at the persistent volume in `fly.toml`.

Not a new table inside `FeedbackStore`, for two reasons. It would put a
per-request auth read behind the same single connection and lock as the spend
rails, which is precisely the load ADR-0002 said to revisit only on a
measurement nobody has taken. And it would route a *user-facing availability*
fault through `/status.feedback_db`, the operator's *money* signal.

**2. The process dict stays the authority while the process lives.** The
durable rows are a write-through mirror, read only when the cache misses —
which is the restart case and nothing else. A warm session never touches SQLite
on read.

**3. Every durable write is best-effort.** When the sink is absent or refuses,
every method behaves exactly as it did before the sink existed. This app has no
login, so a storage fault that stopped sessions being *issued* would be a total
outage — strictly worse than the lockout being fixed. The degradation direction
is "sessions work but do not survive a restart", never "nobody can start one".

**4. `sha256(session_id)` is the primary key; the raw id is never written.**
Plain SHA-256, deliberately not an HMAC: the input is already 192 bits of
`secrets.token_urlsafe(24)` so a key buys nothing, and a keyed digest would
need a secret that survives restarts — the very property this app lacks
(`costs.py` warns at import that `QUORUM_TOKEN_SECRET` is generated per process
when unset). A keyed digest would therefore lock every visitor out on exactly
the restart this module exists to survive.

The CSRF token IS stored in clear. It is useless without the cookie it is bound
to, and the cookie is what the digest withholds. A test pins that the two
secrets stay independent, because that argument collapses if one ever reveals
the other.

**5. `touch` writes through at most once per `SESSION_TOUCH_PERSIST_INTERVAL_S`
(300s).** `require_session` touches on every authenticated request. ADR-0002
pinned this design against roughly sixteen writes per RUN, not one per REQUEST.
300s is the largest value keeping the loss under 5% of the 2h `SESSION_TTL`,
and it bounds one session's durable write rate at 1 per 5 minutes however hard
it is used. The error is one-directional: a restored session's remaining life
is understated by at most the interval, never overstated.

**6. The 429 becomes a rendered page** (`templates/session-capped.html`) with a
`Retry-After` header derived from the oldest mint still inside the window, on
both `/ui` and `/v1/session`. The JSON `detail.code` is unchanged — `app.js`
reads it.

**7. The copy stops claiming a calendar boundary.** `try_record_session_mint`
cuts at `now - timedelta(hours=24)` — a rolling window. "today's limit" and
"the daily window resets" were both false, in the HTML and in the JSON.

## Measurements

**Read-only SQLite shapes** (CPython 3.12.13, SQLite 3.50.4, this machine).
This is what makes a separate file safe where a new table in an existing
database would not be:

| Shape | Result |
|---|---|
| Existing file, table already present, file read-only | Opens. `CREATE TABLE IF NOT EXISTS` is a no-op and writes nothing |
| Existing file, table missing, file read-only | `OperationalError: attempt to write a readonly database` |
| Brand-new file in a read-only directory | `OperationalError: unable to open database file` |
| `INSERT` on the read-only file from row 1 | `OperationalError: attempt to write a readonly database` |

Only the first shape can occur once this store has ever run, and it opens. The
other two raise out of `__init__`, where `main._configure_session_store`
catches them and the app runs on the dict alone. **No shape of an unwritable
volume stops Quorum booting**, which is the property `feedback_store`'s
`_MIGRATIONS_DDL` comment exists to protect and the reason its guarded-migration
block is not needed here. A later schema change to this store *would* need one:
adding a column or table to `_SCHEMA` reintroduces shape two.

**End-to-end, against a real killed-and-restarted uvicorn process** (not a
mocked restart), with the cap at 2:

```
fresh boot: 200                       cookie minted by process A
--- kill -9 process A; start process B on the same volume ---
mint 1: 200                           process B, cookie-less
mint 2: 429                           the cap still refuses new visitors
cookie-less 3rd visitor: 429
returning visitor (cookie from the DEAD process): 200   <- workspace served
session_minted rows: 2                the resume consumed no mint
```

**The rendered page**, driven in a real browser at 1440x900 and 360x740:

| Check | Light | Dark |
|---|---|---|
| axe violations (`wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`) | 0 | 0 |
| Horizontal overflow at 1440 | none (1440/1440) | none |
| Horizontal overflow at 360 | none | none |
| Theme resolved before paint | `light` | `dark` |
| `Retry-After` on a fresh cap | `86399` | — |

**Mutation proofs.** Every test in this change was shown to fail against a
deliberate defect and pass after restoring the file from a copy
(`diff -q` clean each time), on a 19-test suite:

| Mutant | Result |
|---|---|
| `get()` stops restoring from the durable store | 3 failed |
| `fetch()` stops enforcing expiry on the read | 1 failed |
| `_digest()` returns the raw session id | 1 failed |
| `clear()` stops emptying the durable half | 1 failed |
| The per-request write throttle is removed | 1 failed |
| The advertised wait is hard-coded to one hour | 2 failed |
| `/ui` 429 reverts to the bare sentence | 4 failed |

## Consequences

- **A restart is no longer an implicit global logout.** That property was
  accidental, and it was doing real security work: it bounded how long a leaked
  cookie stayed useful. It is now bounded only by `SESSION_TTL` (2h of
  inactivity). This is a deliberate trade, recorded so it is not rediscovered
  as a surprise.
- **A third SQLite file on the volume**, and a second file behind the local
  "delete `.data/*.sqlite3` to unpoison an e2e run" workaround.
- **`/status` gains no field.** A `session_store` health key belongs there, but
  saying so requires editing the `/status` docstring, which is embedded verbatim
  in `openapi.yaml` — owned by another work package in this batch. Filed as
  follow-up rather than smuggled in. The boot failure logs at ERROR meanwhile.
- **Test isolation now depends on `clear()` emptying the durable half.**
  `tests/conftest.py` calls it before and after every test; a clear that
  emptied only the dict would cross-contaminate the suite and fail somewhere
  unrelated. Pinned by a test with a positive partner.

## Rejected alternatives

**Add the table to `FeedbackStore`'s existing database.** Rejected: it puts a
per-request auth path behind the spend rails' single connection and lock
(ADR-0002), and routes an availability fault through the money health field.

**Store sessions as `events` rows with `recorder='session'`.** Rejected: the
`events` table is append-only by contract, while sessions need UPDATE and
DELETE; and resolution would become O(all session events) per request against a
table whose growth cost is already measured there (605 rows → 2.13 ms/charge,
180,020 rows → 96.40 ms).

**Add an absolute session lifetime** to bound accumulation, since durability
removes the restart backstop. Rejected on arithmetic, not on taste: the mint cap
is 2 new accounts per IP per 24h and stays durable, so reaching even a thousand
warm sessions from one address takes on the order of 500 days. Spend is
independently bounded by the per-account 24h cap and by `GLOBAL_DAILY_CEILING_USD`.
Adding a lifetime would mean choosing a guardrail number nobody has measured,
which is worse than the risk it addresses. Revisit if the mint cap is ever
raised.

**Extend a session past its TTL on restore**, so the returning visitor always
gets back in. Rejected: it would make expiry unenforceable and quietly convert
a 2-hour credential into a permanent one. Expiry semantics are unchanged; the
rendered 429 page is what serves the visitor whose session genuinely expired.

**Guess a `Retry-After` when the store cannot tell us.** Rejected: the header
is omitted instead. A fabricated value teaches a client to return at a time
nothing computed.

## Related

- ADR-0002 — SQLite stores stay single-writer. Re-read before this design, not
  after; its headroom paragraph is why `touch` is throttled.
- `feedback_store._MIGRATIONS_DDL` — the measured reason new DDL must not go in
  an unguarded `_SCHEMA` on an EXISTING database.
- Issue #100 §2.3 — the durable per-IP mint cap this change makes survivable.
