# ADR-0176: An operator command ends signed-in sessions, and every process reads the cutoff on each request

## Status

Accepted — 2026-10-22, board row W87, the last of its three pull requests (W87-3). W87-1
(ADR-0174) built the maximum session age and W87-2 (ADR-0175) a recent sign-in before deletion.
The owner's decisions it builds on: the form, a command run on the machine (CHG-063 (d)); `--all`
ends signed-in sessions only (CHG-066 (d)); a signed-in request whose cutoff cannot be read is
refused as an expired session, and the command keeps no record of its runs (CHG-083 (a), (b)).
**Everything else below is the session's design.**

**Amended 2026-10-25 by CHG-088** (the W87-3 follow-up; section "Amendment, 2026-10-25" below): a
signed-in request whose cutoff cannot be read is now refused as UNCHECKED, keeping its cookie and
creating nothing, not as an expired session; decisions 3, 4, 5, 6, 7 and 11 are amended in place,
each marked.

It amends ADR-0002 (the command is a second writer, short and rare), ADR-0137 (the durable cutoff
is now read on cache hits, not only on restore) and ADR-0144 decision 3 (a signed-in session on a
database without the session-safety migration is now refused, as a consequence of CHG-083 (a)).

The failure modes were listed before any code (W87's private list of 2026-10-18, section 4) and
are published with this change in
`docs/analysis/2026-10-20-w87-3-end-sessions-failure-modes.md`. Codex reviewed the plan four times
before any code (ADR-0168, decision 7); its reviews are kept outside the repository. Its findings
that changed the design are named in Decision.

## Context

Before W87-3 nothing but the user's own "sign out everywhere" ended an account's sessions (ASVS
V7.4.5). Facts the design rests on, read on `main` at `27ad8e4` unless marked:

- **A cache hit read nothing durable.** `SessionRepository.get` returned the cached object. The
  durable cutoff `accounts.sessions_valid_after` (ADR-0137) was read only when a session was
  restored from disk.
- **So deleting rows from another process ended nothing.** Measured by W87's failure-modes agent
  (2026-10-18) and again by the W87-3 planner: after another connection deleted the rows, the cached
  session still resolved, and the next persisted touch wrote its row back (`INSERT OR REPLACE`).
- **A latched readiness flag read as "no cutoff".** Measured by the planner after Codex found it:
  with the session-safety migration failing at open on a file that already held its marker, the
  store had `_safety_ready = False` and `sessions_valid_after` answered `(True, None)`, so the guard
  this ADR adds would have let every signed-in session through while the command, which checks only
  the file's marker, exited 0.
- **Importing `product_app.auth` starts the `session-gc` thread**, and building a `SessionStore`
  migrates, sweeps history and may `VACUUM` the file (ADR-0172).
- **Production runs one process on one machine with one volume**: the `Dockerfile` CMD passes
  `"--workers", "1"` and `fly.toml` has one `[[mounts]]` at `/data`. No test pinned the worker
  count before this change (`git grep -e '--workers' origin/main -- 'tests/*.py'` finds nothing);
  the one mount was already pinned, for the telemetry sink, by
  `tests/unit/test_telemetry_sink.py::test_fly_toml_points_the_telemetry_sink_at_the_persistent_volume`.

## Measured

| What | How | Result |
|---|---|---|
| The new and moved tests fail without the fix | the test designer's run of the eleven test files of commit `d27b2aa`, before any source change | `71 failed, 115 passed` |
| The same files with the fix, plus `test_risk_constant_pins.py` and `test_skill_router_work_item.py` | the builder's run on the code commit | `246 passed` |
| The three timing-sensitive files, ten times | the builder's run, load average 4.8 to 10 | `30 passed` in each of the 10 runs |
| The command's transaction | the planner's probe: `--all` on 10,000 accounts, 10,000 signed-in rows and 10,000 anonymous rows | 68.4 ms; 10,000 rows deleted, the 10,000 anonymous rows left |
| The cutoff read, **uncontended** | the planner's probes, 20,000 calls per run, SQLite 3.50.4, load average 4 to 6.6 | 3.87 to 4.25 µs per call; a cache-hit `touch` 0.87 to 0.90 µs before, 5.10 to 5.24 µs with the read. A request calls `get` one to four times, so about 4 to 25 µs (one call at 3.87 µs; four at up to 6.23 µs, the planner's prototype with the lock bound), against about 1,035 µs for the cheapest `TestClient` request measured |
| The cutoff read, **contended** | the planner's probe: another connection holds the write lock while an app write waits on it inside the store lock | 205 ms behind a 0.3 s hold; 922 ms behind 1.0 s; 5,156 ms behind 6.0 s (the app save gave up after its 5 s busy timeout). With no app write waiting, a read against a held write lock took 0.1 ms |
| The bound | the same probe with a 0.25 s bound behind the 1.0 s hold | `(False, None)` after 255 ms: refused, not waited |
| A whole request under contention | the planner's probe, a 0.05 s bound, the cutoff written | store lock held 0.35 s: 401 after 0.330 s; repository lock held by a save waiting 1.0 s: 401 after 1.030 s; another account, no contention: 200 |

The planner's figures are inherited by this ADR, not re-measured by the build.

## Decision

1. **The command.** `python -m product_app.end_sessions --email ADDRESS | --all`
   (`src/product_app/end_sessions.py`). It opens its own connection with `mode=rw` (it never
   creates a file) and a 5 s busy timeout (`COMMAND_BUSY_TIMEOUT_S`, Python's default and the
   app's; ADR-0002 measured that `timeout=0` loses writes), turns on `secure_delete`
   (ADR-0172), refuses a file without the `w7_session_safety` marker or not owned by the effective
   user, and never migrates. In one `BEGIN IMMEDIATE` transaction it raises
   `sessions_valid_after` (never lowers it) and deletes the matched accounts' rows created at or
   before the cutoff. `--email` runs the SQL sign-out everywhere runs
   (`session_store.RAISE_SESSIONS_CUTOFF_SQL` and `DELETE_SESSIONS_BEFORE_SQL`, the same objects),
   once per matched account; it matches after `strip()` and `casefold()` on both sides, as account
   deletion does, and ends every match. `--all` runs its own two statements
   (`RAISE_ALL_CUTOFFS_SQL` and `DELETE_ALL_SIGNED_IN_BEFORE_SQL`): it raises every account's cutoff
   and deletes only rows whose account id is in an accounts row, so anonymous sessions keep running
   (CHG-066 (d)). The cutoff is `isoformat()` of the UTC time, because the
   app compares cutoffs as text.
2. **A read-back**, in a second short transaction: it deletes again any matched row created at or
   before the cutoff (a request in flight can have written one) and checks every matched account's
   stored cutoff is not lower. A row found, a lower cutoff, or a read-back that could not run is
   exit 4; running again is safe.
3. **Exit codes.** 0 written and read back, or `--help`, which changes nothing; 1 no account has
   that email as of its last sign-in, or (amended, CHG-088 (f)(3)) `--all` found no account at
   all, both printing the database path, nothing changed; 2 usage (neither flag, both, `--email` given
   twice, an extra argument, or an email without exactly one `@`), nothing changed; 3
   `SESSION_DB_PATH` not set or empty (the command never falls back to the app's default, which is
   a path under the working directory, where a stray store would take the run; break-it round
   2), no file, not writable, locked past the busy timeout, not
   migrated, or not run as the file's owner, nothing changed (amended, CHG-088 (f)(2): busy says
   "The sessions database is busy. Run the command again. Nothing was changed."); 4 the cutoff is
   written but the read-back found or could not check something.
4. **What it prints.** Counts and the cutoff only, and that it does not secure the Google account
   itself; and (amended, CHG-088 (f)(3)) the resolved database path when nothing matched, the
   one printed value the operator did not type (it comes from `SESSION_DB_PATH`). An output that cannot be written (any `OSError`: a reader that has gone away, a full
   disk, a file-size limit) does not change the exit code, `--help` included: every line, the
   help too, goes through one writer that catches it, so the code still says what the run did
   to the file. Usage errors print one fixed sentence: argparse's own `error()` echoed the arguments
   (Codex; the planner reproduced `unrecognized arguments: person@example.invalid`). Other errors
   name the exception type only. It stores no record of its runs (CHG-083 (b)).
5. **Every process reads the cutoff on each signed-in request.** `SessionRepository.get`'s
   cache-hit branch calls `_refused_by_durable_cutoff` (amended: since CHG-088, `lookup` calls
   `_check_cached`, once per lookup), outside the repository lock. An anonymous
   session (the anonymous maximum age) never reads the store. Otherwise it reads
   `sessions_valid_after(account, lock_timeout=SIGNED_IN_CUTOFF_LOCK_TIMEOUT_S)`. A cutoff at or
   after the session's start ends the account's cached sessions (`end_sessions_of`) and refuses
   the request. It runs on the request thread, so a stalled GC thread cannot let a session
   through. The same guard ends another process's cached copy after a sign-out everywhere.
6. **Fail closed when the cutoff cannot be read (CHG-083 (a)).** The store not ready, its lock not
   acquired within 6.0 s, a closed store, or a failed read refuses the signed-in request; the 401
   is `SESSION_UNCHECKED` (amended, CHG-088: it was the generic `SESSION_EXPIRED`, and a page load
   minted over the cookie; now the cookie is kept and nothing is created). The refusal leaves the cached copy, so the next request checks
   again. While the session-safety tables are not ready, `sessions_valid_after` answers by the
   account row (Codex's blocker): no row `(True, None)`, a row or a failed read `(False, None)`.
7. **The 6.0 s bound** (`session_store.SIGNED_IN_CUTOFF_LOCK_TIMEOUT_S`) covers the cutoff read's
   wait for the store lock only. Amended by CHG-088 (b), the owner's "Raise to 6 seconds" (it was
   1.0 s). It is above the app connection's own busy timeout, 5 s (`APP_BUSY_TIMEOUT_S`, now
   explicit), which is how long the store's own write can wait inside the store lock; the old
   reason, "well under the 5 s a stuck write can take", is withdrawn (the amendment says why). A module constant, not a setting, like
   `_CLOSE_LOCK_TIMEOUT_S`: no repository rule asks for a setting, and nothing measured needs one.
8. **`save` is conditional and truthful.** One `INSERT OR REPLACE ... SELECT ... WHERE NOT EXISTS
   (... sessions_valid_after >= created_at)` statement, so a request that read the old cutoff and
   waited on the command's lock cannot write a cut-off row back after the commit. It returns
   `rowcount == 1` (Codex: the old `_write` said `True` for zero rows). While not ready it writes
   only a row certainly in no accounts row. `flush` now goes through `get`, so it runs the guard
   (Codex: it read the cache directly).
9. **Sign-in refuses while not ready.** `upsert_google_account` needs both the accounts and the
   session-safety flags, so a sign-in in that state says "did not complete" instead of making a
   session the next request refuses.
10. **Readiness is validated, and recovers.** One read-only function, `_readiness_from_schema`
    (two `SELECT`s and one `PRAGMA`), checks the markers, the tables (including
    `spend_key_carry`, which Codex showed a legacy file can lack) and the columns. The constructor
    calls it after its migrations, so it is never more permissive than before and stricter for a
    marker without its table or column. `refresh_readiness` calls the same function under the store
    lock, only while not ready, and only ever raises a flag; it never writes. The GC tick calls it
    once a tick (`auth._refresh_store_readiness`, in its own `try`, logging the exception type
    only), so a file that is readable again reopens signed-in access within about one GC interval
    (60 s) without a restart.
11. **A restore decides the session's kind once.** `_restore` (amended: `_restore_lookup` since
    CHG-088) asks `is_anonymous` while the
    accounts flag is up and `has_no_account_row` otherwise, as `spend_meter_for` does, and uses that
    one answer for the refusal and the lifetime. An id in no accounts row has no cutoff, so its
    cutoff is not read; any other kind while the session-safety tables are not ready is refused
    (`cutoffs_available()`), and otherwise its cutoff is read as before. While ready, a failed kind
    lookup still gets the signed-in limits (W87-1).
12. **One machine is a prerequisite.** The command reaches only the volume it runs beside. Two tests
    pin it (`tests/unit/test_one_machine_deployment.py`): exactly one worker in the `Dockerfile`
    CMD, and exactly one `[[mounts]]` in `fly.toml`.

## Consequences

- An operator can end one account's sessions, or every signed-in session, from `fly ssh`
  (`DEPLOY.md`, "End sessions"). Every process on the machine refuses them from its next request.
- ADR-0002 gains a second writer. It is short and rare: per run, one short write transaction and
  one read-back, a second short transaction.
- ADR-0137: sign-out everywhere is now seen by other processes too.
- ADR-0144 decision 3: on a read-only database that predates the spend key, a signed-in session
  used to restore and be metered under its own id. No cutoff can be read there, so it is now
  refused, and so never metered (CHG-083 (a)).
- Every signed-in request reads the store one to four times more; anonymous requests do not.
- An ended signed-in visitor's next page load mints a counted anonymous session, as after sign-out
  everywhere or the 12 hours.

## Known limits

- **Another machine** is not reached: its volume is separate. The two pins above hold the layout.
- **Matching can end look-alike addresses.** `casefold()` folds some distinct characters together,
  for example the Kelvin sign (U+212A) to `k` and `ß` to `ss`, so `--email` can also end an account
  whose stored address differs from the typed one in such a character. It is the rule account
  deletion uses (`account_deletion.py`), it errs toward ending too many, and the output gives only
  a count, so it does not show which accounts matched.
- **The email stays in the operator's shell history**, and in `ps` inside the machine while the
  command runs. That is the owner's form (CHG-063 (d)).
- **Anonymous sessions are affected in one case.** CHG-083 (a)'s option text said "Anonymous
  visitors are not affected"; that holds except when the read of the session's account row (or its
  cutoff) fails, so its kind is unknown. Then a restore of an anonymous row is refused (as a failed
  cutoff read already refused one), a save while not ready writes nothing, and an anonymous session
  restored while ready with a failed kind lookup carries the signed-in age, so its cache hits are
  checked like a signed-in one's, including the 6.0 s bound.
- **A request already past its check** when the command commits finishes that request. It is
  checked again at its spend key (ADR-0137, decision 3), because `spend_meter_for` calls `get`
  (`lookup` since CHG-088).
- **The bound is not a bound on the request.** A refused request can still wait on the repository
  lock (held by another request's save) or on the 401's reason lookup (`store.fetch`, unbounded),
  as requests already do; the planner measured 0.330 s and 1.030 s. After the lock is taken, the
  read itself can wait only while another connection is mid-commit; that wait is not bounded
  separately.
- **Recovery waits for the GC tick**: up to about 60 s after the file is readable again, longer
  while the GC thread is stalled. A file whose migration marker is missing stays not ready until a
  restart on a writable volume, as before. A latched history flag still needs a restart.
- **Account deletion in another process** is still not seen on a cache hit (production runs one
  process).
- **Inherited, not re-measured**: the contended figures above and FM-29's 5.43 s.

## Rejected alternatives

- **Deleting rows only.** It ends nothing while the process lives, and the next touch writes the row
  back (Context).
- **A request log with watermarks, applied by the GC thread** (W87's first design: the command
  records a request, the GC tick applies it and stamps a confirmation the command waits for).
  Codex showed it needed heartbeat confirmation, replay after a purge and request ids that cannot be
  reused; a stalled GC thread also delayed enforcement. The cutoff only rises and is never purged,
  so a late process has nothing to miss, and the request thread enforces it.
- **A GC-thread poller** of the cutoffs. The same stall problem, and up to a minute of exposure.
- **A configurable lock timeout.** Nothing measured needs one (decision 7).
- **A record of runs** (a sign-in event or a log table). The owner chose none (CHG-083 (b)).
- **Treating an unreadable cutoff as "none".** That is the open side; the owner chose closed
  (CHG-083 (a)).

## Amendment, 2026-10-25: CHG-088 (the W87-3 follow-up)

### Why

W87-3 shipped, and a session-store problem then signed people out. While a signed-in session's
cutoff could not be read, every page load and every `GET /v1/session` treated the cookie as "no
session": it minted a new anonymous session, replaced the cookie and spent one of the network's 2
daily sessions, and the visitor stayed signed out after the store recovered. The failure-modes
agent measured it before any design (`docs/analysis/2026-10-25-w87-3-followup-failure-modes.md`,
probe P1: `GET /v1/session while unreadable: 200 | sets cookie: True | new id: True`). The owner
decided what should happen instead (CHG-088 (a) to (g)). **Everything below that is not quoted
from CHG-088 is the session's design.**

### The states, one outcome each

"Unchecked" means: keep the cookie, mint nothing, touch nothing.

| # | Where the session is | Store | Outcome |
|---|---|---|---|
| S1-S3 | cached anonymous; cached signed-in with no store; cached signed-in, cutoff read, not covered | any | served |
| S4 | cached signed-in, cutoff covers it | ready | ended (the mint path) |
| S5, S6 | cached signed-in (S6: its kind was unknown at its restore) | not ready, lock not taken within the bound, closed, or the read failed | **unchecked** |
| S7 | not cached, no usable row (absent, idle, over 24 hours, will not parse) | any | ended |
| S8 | not cached, the row read itself failed, or the store is closed | — | **unchecked**, kind unknown |
| S9 | not cached, anonymous by its account row | any | restored |
| S10 | not cached, known signed-in, past its 12 hours or its idle limit | any | ended, before any not-ready exit |
| S11 | not cached, account deleted or ended by sign out everywhere in this process | any | ended |
| S12, S13 | not cached, signed-in (S13: kind unknown) | not ready, or its cutoff read fails | **unchecked** |
| S14, S15 | not cached, signed-in or unknown | ready, cutoff read | ended if it covers the session, else restored |
| S16 | any presented cookie | **no store object** (it failed to open at start) | no session, the mint path, as before: the owner's exception (CHG-088 (g)) |
| S17 | a session this process saw end (12 hours, idle, sign-out, sign out everywhere, deletion, the command's cutoff read on a cache hit) | any, a failing read included | ended, from memory, before any read |
| S18 | cached signed-in whose cutoff read failed and whose 12 hours or idle limit ran out during the wait | — | ended |

### Measured

| What | How | Result |
|---|---|---|
| The new tests fail without the change | the test designer's run of the 9 test files on `a236b31`, before any source change | `78 failed, 150 passed, 1 skipped` |
| The same files with the change | the builder's run on the build commit | `2 failed, 226 passed, 1 skipped`: the two failures are test-designer defects the builder reported rather than fixed (T7c's partner, and two constants missing from the risk-constant registry), each to be settled before merge |
| `/ui` for a cached signed-in cookie behind a held store lock, at the 6.0 s bound | the builder's in-process probe (`TestClient`, another thread holds `SessionStore._lock`), load average 9.7 | 3.0 s hold: 200 with the same cookie in 3.008 to 3.021 s (3 runs); 5.5 s hold: 200 in 5.511 s; 7.0 s hold: the 503 page in 6.013 s, no `Set-Cookie` |
| A refused unchecked API request ends at the bound | `tests/security/test_unchecked_session_keeps_its_cookie.py::test_t14_an_unchecked_api_refusal_ends_at_the_bound_not_the_hold` (bound patched to 0.2 s, 1.5 s hold) | under 0.7 s; before the change it waited for the hold (the test designer's red run: `1.508` s, `SESSION_EXPIRED`) |
| The timing-sensitive files, ten times | the builder's runs of `test_signed_in_cutoff_on_cache_hits.py`, `test_session_store_not_ready_fails_closed.py` and `test_unchecked_session_keeps_its_cookie.py`, load average 6.9 to 11.8 | `1 failed, 81 passed` in each of the 10 runs; the one failure is T7c's partner every time (deterministic, not timing) |
| Threads behind a long hold | inherited from the failure-modes agent (P2), not re-measured: anyio's 40 threads, an 8.0 s hold, 45 signed-in requests | `/ready` answered in 7.70 s at the 6.0 s bound and 7.71 s at 1.0 s; a 3.0 s hold at 6.0 s: `codes={200: 45}` |

### Decisions

A1. **`get` keeps returning `None` for every refusal.** Its outside callers keep their `is None`
    meaning, so no truthy "refused" value can reach the spend key or the sign-in callback. A new
    `SessionRepository.lookup(session_id) -> Lookup` says why: `Lookup(session)` (served),
    `Lookup(None)` (no session or ended) or `Lookup(None, Unchecked.SIGNED_IN | UNKNOWN_KIND)`.
    `unchecked` is never set with a session (`test_t19_...`, one case per state).
A2. **One cutoff read per lookup, then `use`.** A lookup reads the durable cutoff at most once and
    `use(session, rotate_csrf=...)` records the use with no second read. Two bounded reads in a row
    could wait twice the bound, and a cutoff written between them is applied from the next
    request, as decision 5 already says of requests in flight. Cutoff reads per request for a
    signed-in cached cookie: 1 for `/ui`, `/v1/session`, the idle check and a route whose only
    check is `require_session`; 2 for "Stay signed in"; 3 for an estimate; 4 for a run creation
    (the deliberate re-checks: the spend key, ADR-0137 decision 3, and admission inside the run
    store's lock). `test_t3_cutoff_reads_per_request` pins each count. `/ui`'s two time-left
    numbers and the idle route's write-through use the session already checked
    (`max_age_seconds_left_of`, `recent_sign_in_seconds_left_of`, `flush_session`), so a later
    read's refusal can no longer read as "0" or be ignored (Codex F2).
A3. **The ended list.** `SessionRepository._ended_ids` records each session this process drops
    because it ended, for 24 hours. `lookup` answers "ended" for those before any store read, so a
    session known to have ended is never called "briefly unavailable" when the store then fails
    (Codex F3). A cached session whose cutoff read failed and whose 12 hours or idle limit passed
    during the wait is ended too; a cutoff written elsewhere that cannot be read stays unchecked.
A4. **A known signed-in row past its 12 hours is ended first** (FM-1.8), before the not-ready
    exit. A row whose kind is unknown is not ended by the signed-in limits there: it may be an
    anonymous session inside its 24 hours.
A5. **Both doors (CHG-088 (c)).** `/ui` answers a 503 page (A6); `/v1/session` and every API route
    answer 401 `SESSION_UNCHECKED` (the owner's "Still a 401 (your CHG-083 choice)", CHG-088
    (e)). Neither sets a cookie, mints, touches or rotates anything. `/v1/session` answers 401,
    not 503, so every JSON door has one code and one status: the session's choice. The unchecked
    branches never call `end_reason`, whose `store.fetch` has no time bound, so a refused request
    ends at the cutoff read's bound (T14). Admission keeps today's durable read inside the run
    store's lock; its unchecked branch refuses with `SESSION_UNCHECKED`.
A6. **The page (CHG-088 (d), "Same, plus auto-reload").** `templates/session-unchecked.html`:
    503, `Retry-After: 60`, `Cache-Control: no-store`, no `Set-Cookie`. A meta refresh to `/ui`
    after `main.UNCHECKED_PAGE_REFRESH_S` (60) seconds, not script, and one "Try again" link to
    `/ui`. Its one script is the capped page's pre-paint theme gate, byte for byte. It carries
    nothing from the request: no session id, CSRF token, email, data island or form.
A7. **The words follow what the server knows.** For a session known to be signed in, the owner's
    words. For one whose kind is unknown (its row or its account row could not be read), the
    session's variant: "session" for "account" and "sign-in", nothing else changed. The open
    tab's card title is "Briefly unavailable", the owner's heading with its subject deleted, also
    the session's. Both are shown to the owner in the pull request (`docs/33-content-design.md`,
    COPY-022 to COPY-027).
A8. **The open tab retries in place (CHG-088 (e)).** `app.js`: `SESSION_UNCHECKED` has a title and
    no reload action. Run, "See the estimate" and the cost card's approval pass their own function
    as "Try again", so the typed question stays; History keeps its rows and offers "Try again";
    the idle check keeps checking and never says "signed out"; "Stay signed in" shows the sentence.
A9. **Sign-in is refused before Google (CHG-088 (f)(1)).** Both starts answer 503
    `SIGN_IN_UNAVAILABLE` with `Retry-After: 60` when there is no store or its accounts or
    session-safety flags are down. The check reads the two flags only: no lock and no statement.
    It sits after the host check and before the deletion check and the limiter, so a refused start
    spends nothing (ADR-0175's order: 404, 401/403, 409, 503, 403, 429).
A10. **The log line and `/status` (CHG-088 (f)(4), (5)).** One limiter per process,
    `auth._UncheckedRefusals`: the first unchecked refusal logs at once, later ones are counted,
    and the first line 60 s or more after the last one (the monotonic clock) reports them; the GC
    tick flushes a trailing count. The cause is `not_ready` or `not_read`, from the flags. The
    session's words: `signed-in requests refused: the session cutoff could not be checked
    (not_ready=N not_read=M); K refused since the last line`. No id, email or traceback. The
    store's own "could not read a sessions cutoff" and "could not read a session" warnings are
    throttled the same way, per store, and the first line after a window says how many were left
    out. `/status` gains `session_store`: `ready`, `not_ready` or `absent`, from the flags only;
    `/ready` is unchanged.
A11. **The command (CHG-088 (f)(2), (3)).** Busy is SQLite's code (`sqlite_errorcode & 0xFF ==
    SQLITE_BUSY`), never its text, so `SQLITE_LOCKED` is not called busy. Busy at the marker read
    or the write (a busy `COMMIT` included, which is rolled back) prints the owner's sentence and
    exits 3; the read-back keeps its exit 4 sentence, since the change is saved there. `--all`
    with no account rolls back before anything is written and exits 1 with "No account is recorded
    in <path>. Nothing was changed."; `--email` with no match exits 1 with "No account has that
    email address as of its last sign-in in <path>. Nothing was changed." The two sentences are the
    session's; the owner accepted "print the database path". The path is resolved, from
    `SESSION_DB_PATH`, printed to standard error (which escapes what it cannot encode), and an
    output that cannot encode it is escaped rather than raised.
A12. **The bound is 6.0 s, and the coupling is the app connection's busy timeout (CHG-088 (b)).**
    What holds the store lock past a second is the store's own statement waiting on another
    connection's lock, for up to its connection's busy timeout, while it holds `SessionStore._lock`.
    That connection passed no `timeout=`, so it used Python's default, 5 s (a default
    `sqlite3.connect` reports `PRAGMA busy_timeout` 5000, measured for the plan). It is now explicit,
    `session_store.APP_BUSY_TIMEOUT_S = 5.0`, and the bound is pinned above it
    (`tests/unit/test_cutoff_bound_six_seconds.py`). The owner's option named "the command's 5 s
    busy timeout"; the command's is also 5 s, and the one that governs the app's own hold is the
    app connection's. The old reason in decision 7, "well under the 5 s a stuck write can take",
    is withdrawn: a refused request then waited the whole hold anyway, in the 401's unbounded
    reason lookup (inherited from the plan's availability measurement, 3.06 s at a 3 s hold), which
    A5 removes. Still a constant, not a setting.
A13. **No store at all is today's behaviour (CHG-088 (g)).** When the store failed to open at start,
    nothing can be checked and no cookie can be told from a made-up one, so a presented cookie gets
    a fresh anonymous session as before; sign-in is refused before Google (A9) and `/status` says
    `absent`. The owner's exception to "keep the cookie, create nothing".

### Rejected alternatives

- **A new return type for `get()`.** Its callers read `None` as "no session": `git grep -nE
  "session_repository\.(get|touch|rotate_csrf)\(" 7e777d1 -- src` counts 12 call sites (8 in
  `auth.py`, 3 in `google_signin.py`, 1 in `account_deletion.py`); a truthy refusal reaching the
  spend key or the sign-in callback would be read as a session.
- **`end_reason` to tell unchecked from ended.** Its `store.fetch` has no time bound, so every
  refusal would wait the whole hold.
- **Classifying both reads of a request.** Two bounded reads could wait twice the bound; the second
  adds nothing.
- **A script retry on the page, or the workspace with a banner.** The page would then carry the
  app's script and data, the two things it must not hold for a cookie that could not be checked.
- **200 for the page.** A cache or a monitor would read a refusal as a served page.
- **A new exit code for busy.** The owner kept exit 3 ("exit 3 as today").
- **A readiness field on `/ready`.** The owner's (4) says `/ready` is unchanged; Fly's health check
  reads it.
- **A configurable bound.** The owner chose a value; decision 7's reason for a constant stands.
- **A memory-only admission check** (the plan's first answer to FM-5.8). Codex's probe showed it
  accepts a run from a session another process ended after the spend-key check
  (`memory_external_end: accepted; runs_stored=1`, against `401 SESSION_EXPIRED; runs_stored=0`),
  which weakens ADR-0174 decision 11. Admission keeps its durable read
  (`test_t61_admission_refuses_a_session_another_process_ended_after_the_spend_key`).
- **The "briefly unavailable" page when there is no store at all** (option A of CHG-088 (g)). Every
  returning visitor, and anyone with an old or made-up cookie, would be locked out for the whole
  fault, with "usually clears within a minute" false throughout. The owner chose today's behaviour.

### Known limits

- **Threads.** anyio's default limiter is 40 threads (measured in the `.venv` by the failure-modes
  agent; the production image's is UNVERIFIED). Behind a store-lock hold longer than 6 s, more
  than 40 concurrent signed-in requests still delay `/ready` (7.70 s, inherited; Fly's check times
  out at 5 s, `fly.toml`). Refused unchecked requests now end at the bound, but an ended session's
  401 still looks up its reason with no time bound, and a restore's row read, kind read and cutoff
  read have no bound either.
- **The page's latency.** A cached signed-in page load waits for a held store lock up to 6.0 s
  before the page or the workspace (measured above: 3.0 s for a 3 s hold). Before the amendment
  it was refused after 1.0 s and minted a new session, whose save then waited for the rest of the
  hold (the plan's journeys measurement, 2.52 s at a 2.5 s hold, inherited).
- **The sign-in start as a whole is not bounded.** The pre-check takes no lock, but the start's
  own authentication can write a due touch under the store lock first (Codex F4).
- **The ended list** is lost at a restart and an entry is pruned after 24 hours; a failing read of
  that cookie afterwards gives "unchecked" (the page or the 401), never access. Its memory has no
  fixed bound: one entry per session that ended in this process in 24 hours, which grows with the
  number of addresses seen (UNVERIFIED in size). Sign-in-only sessions are left out.
- **Admission holds the run store's lock longer.** During a session-store hold, admission's
  durable read can hold `InMemoryQueryRunRepository._lock` up to the 6 s bound (it was 1 s), and
  every run operation behind that lock waits: 15 `with self._lock:` statements in
  `query_run_orchestration.py` (`grep -cE "^\s+with self\._lock:"`), polling reads included. Pre-existing: an ended
  session's reason lookup there has no time bound either.
- **Sign-in passes the pre-check during a lock hold** (the flags say ready); the account write can
  still give up after Google, and the page says "did not complete".
- **Long windows.** A missing migration marker lasts until a restart, and a malformed cutoff value
  until someone repairs it; the page keeps saying "usually clears within a minute". `/status` says
  `not_ready` for the first and `ready` for the second; the log line's `not_read` shows it.
- **The page keeps reloading** for as long as the window lasts: one `/ui` a minute per open tab,
  each counted in the invite and allow-list request counters on `/status`.
- **A session of unknown kind stays unknown** for its life: its cache hits are checked like a
  signed-in one's and get the "session" words.
- **No store at start (A13):** a returning visitor spends one of the network's 2 daily sessions and
  signs in again after the fix; the sign-in sentence's "briefly" is false for that fault.
- **The log line is per process** and flushed by the GC tick; a stalled GC thread holds back the
  trailing count (the first line still prints). `/status` says only the three states: a refusal
  caused by a lock held too long happens while it says `ready`.
- **The command prints the path only when nothing matched.**
- **Lock fairness**: Python's `RLock` gives no order; two queued app writes could make a read lose
  twice (UNVERIFIED).
- **The start's 503 tells a cookie holder the store is not ready**: kept on purpose, since
  `/status` says the same publicly.
- **Fly passing an app's 503 page through to the visitor** is UNVERIFIED; the 429 capped page does
  reach visitors (ADR-0139).
- **The theme gate** is the capped page's copy, not shared code; its comment was reworded so the
  page names no script file.

## Related

- ADR-0002, ADR-0137, ADR-0138, ADR-0139, ADR-0144, ADR-0172, ADR-0174, ADR-0175
- `docs/41-security-controls.md` SC-104
- `docs/analysis/2026-10-17-asvs-5-level-2-check.md` V7.4.5, V7.5.2
- `docs/analysis/2026-10-20-w87-3-end-sessions-failure-modes.md`
- `DEPLOY.md`, "End sessions"
- CHG-088; `docs/analysis/2026-10-25-w87-3-followup-failure-modes.md`; `docs/113-user-journeys.md` J-009
