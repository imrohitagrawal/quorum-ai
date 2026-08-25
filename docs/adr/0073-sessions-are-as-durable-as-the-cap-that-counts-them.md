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

**A deploy is not the only way to reach it, and a deploy alone is already
enough.** Two claims, kept apart because only one of them is measured:

* **MEASURED.** Every merge redeploys — no workflow has a paths filter, so even
  a docs-only merge restarts the process. This repo merges several times a day,
  so the lockout is reachable daily without anything unusual happening.
* **INFERRED, NOT OBSERVED.** `fly.toml` sets `min_machines_running = 0` with
  `auto_stop_machines = "stop"`, which means an idle machine stops and the next
  visitor arrives at a fresh process. I did **not** observe that happening. A
  free probe of production at 2026-08-26 03:54 IST read `uptime_seconds`
  `20011.0` (5.56 h) against a deployed `build_sha` of `34bbc64`, whose commit
  is 5.78 h old — so the process had been up since its deploy and had **not**
  restarted while idle in that window. An earlier draft of this ADR read "the
  restart interval is hours, not weeks" off that same uptime figure, which the
  number does not support; settling it needs `fly logs` or a longer
  observation, and the merge-redeploy path above makes it unnecessary to.

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
durable rows are a write-through mirror, read only when the cache misses. A
warm session therefore never touches SQLite on read — measured at 0 SELECTs
across 500 warm lookups.

The miss path is **not** only the restart case, and an earlier draft of this
ADR said it was. Any unknown, expired or forged cookie also misses, and
`require_session` runs on every authenticated route — measured at 500 SELECTs
for 500 forged cookies. Before this change an unknown cookie cost a dict
lookup; it now costs one indexed SELECT under the store lock, and it is
reachable unauthenticated. What bounds it is the pre-existing per-IP burst
limiter (`query_runs._InMemoryIpRateLimiter`, 10/min in production), which caps
how fast one address can drive that path at all. Flagged here rather than left
implicit because it is exactly the load characteristic ADR-0002's headroom
argument turns on.

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
300s keeps the loss to 4.17% of the 2h `SESSION_TTL` and bounds one session's
durable write rate at 1 per 5 minutes however hard it is used. (An earlier
draft called it "the largest value keeping the loss under 5%". It is not —
5% of 7200s is 360s, so 359 would be. The bound is right; the superlative
was not, and it is dropped rather than corrected because nothing turns on
being maximal.) The error is one-directional: a restored session's remaining life
is understated by at most the interval, never overstated.

**6. The 429 becomes a rendered page** (`templates/session-capped.html`) with a
`Retry-After` header derived from the DECIDING mint still inside the window —
the `count - cap`-th oldest, which equals the oldest only when `count == cap`.
Taking the oldest would under-report the wait whenever more mints are in the
window than the cap allows, and the page would then tell a visitor to come
back while the cap is still refusing them. Applies to both `/ui` and
`/v1/session`. The sentence rounds UP to whole hours, so it never advertises a
return time earlier than the header does. The JSON `detail.code` is unchanged — `app.js`
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

**Mutation proofs.** Each defect below was injected, the suite run, and the
file restored from a copy — never `git checkout` — with `diff -q` confirming a
byte-identical restore every time. Baseline and final both **40 passed**,
across `tests/integration/test_durable_sessions.py`,
`tests/integration/test_session_cap_page.py`,
`tests/security/test_durable_session_store.py` and
`tests/unit/test_session_cap_retry_hint.py`:

| Mutant | Result |
|---|---|
| `get()` stops restoring from the durable store | 3 failed, 37 passed |
| `fetch()` stops enforcing expiry on the read | 2 failed, 38 passed |
| `_digest()` returns the raw session id | 1 failed, 39 passed |
| `clear()` stops emptying the durable half | 1 failed, 39 passed |
| The per-request write throttle is removed | 2 failed, 38 passed |
| `frees_at` uses `stamps[0]` instead of `stamps[index]` | 1 failed, 39 passed |
| `revoke()` leaves the durable row behind | 1 failed, 39 passed |
| The throttle counts successes instead of attempts | 1 failed, 35 passed |
| The purge stops removing future-dated rows | 1 failed, 35 passed |
| `Retry-After` returns to second precision | 3 failed, 33 passed |
| `_require_aware` stops checking `tzinfo` | 1 failed, 23 passed |
| `/ui` 429 reverts to the bare sentence | 4 failed, 32 passed |

The last four rows were measured on the sub-suites that own them rather than
the full four-file set, so their totals are smaller; the failure counts are
what matter. The `frees_at` row is stated as the exact mutation used, because
an adversarial reviewer trying two other natural formulations of "use the
oldest" got 2 failed rather than 1 — the row is a measurement of one specific
mutant, not a general property.

Two pins outside that suite were proved the same way: halving
`SESSION_MINT_WINDOW` reds `test_the_session_mint_window_is_pinned`, and making
a failed sink open raise reds
`test_a_boot_that_cannot_open_the_sink_still_serves_sessions`.

**One mutant that did NOT die, and what it cost.** Disabling `_require_aware`'s
`tzinfo` check left the entire suite green, because `_is_implausibly_future`
then raises `TypeError` subtracting a naive value from an aware one and the
same `except` swallows it. Two independent guards is a fine position; a guard
nothing can observe is not, because the day the future check is simplified away
the naive path reopens silently. `test_require_aware_refuses_a_naive_timestamp_on_its_own`
now asserts that function's own contract, and reds under the mutant.

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
- **This sink gets no `store_reconnect`.** `store_reconnect.py` opens with
  "Background reconnect for the **two** durable SQLite sinks" and defines
  `maybe_reconnect_feedback_store` / `maybe_reconnect_run_history_store` only.
  So if the boot open fails, or the handle dies mid-life, durability stays off
  until the process restarts — unlike its two siblings. That is survivable
  precisely because losing durability is the pre-ADR-0073 behaviour rather than
  an outage, and because the fault self-heals on the next restart, which is the
  event this whole ADR is about. Stated here rather than left for the next
  reader to discover; `session_store.get_store`'s docstring cites
  `store_reconnect` as the reason to resolve the store at call time, which is
  true of the mechanism but must not be read as "this sink reconnects".
- **Test isolation now depends on `clear()` emptying the durable half.**
  `tests/conftest.py` calls it before and after every test; a clear that
  emptied only the dict would cross-contaminate the suite and fail somewhere
  unrelated. Pinned by a test with a positive partner.

### Found by adversarial review, and left open on purpose

**The mint cap fails fully OPEN when the feedback database is unwritable.**
`try_record_session_mint` ignores `record()`'s return value, so on a read-only
volume it admits every request while writing nothing. Measured across the 2x2
of (session sink healthy/broken) x (feedback store healthy/broken), cap 2, ten
attempts:

| feedback store | session sink | minted | refused | rows on disk |
|---|---|---|---|---|
| healthy | healthy | 2 | 8 | 2 |
| healthy | read-only | 2 | 8 | 2 |
| read-only | healthy | **10** | 0 | 0 |
| read-only | read-only | **10** | 0 | 0 |

**Pre-existing, and unchanged by this ADR** — the identical script against
`origin/main` also gives 10. It is a separate concern (rule 17) and belongs in
its own PR; `try_record_cost_charge` on the same class already does check
`landed` and degrade, which is the shape the fix should take. What this change
DOES alter is the correlation: the session sink is now a second file on the
same volume, so one read-only volume degrades both halves at once.

**The refusal path scans the events table twice under the money lock.**
`try_record_session_mint` scans and returns `False`, then
`seconds_until_a_session_mint_frees` scans again, both holding
`FeedbackStore._lock` — the lock the spend rails use. Measured: 4 rows 0.01 ms,
1,000 rows 0.83 ms, 10,000 rows 8.09 ms, 50,000 rows 40.36 ms. Mint rows accrue
at 2 per IP per day, so 1,000 rows is roughly 500 distinct addresses in a day.
Accepted at this app's traffic, and recorded rather than left silent because it
is a NEW read on a path an unauthenticated caller can trigger. Folding the two
into one lock hold would change `try_record_session_mint`'s signature on a
money path, which is not worth it for the measured cost.

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
