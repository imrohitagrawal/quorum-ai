# ADR-0176: An operator command ends signed-in sessions, and every process reads the cutoff on each request

## Status

Accepted — 2026-10-22, board row W87, the last of its three pull requests (W87-3). W87-1
(ADR-0174) built the maximum session age and W87-2 (ADR-0175) a recent sign-in before deletion.
The owner's decisions it builds on: the form, a command run on the machine (CHG-063 (d)); `--all`
ends signed-in sessions only (CHG-066 (d)); a signed-in request whose cutoff cannot be read is
refused as an expired session, and the command keeps no record of its runs (CHG-083 (a), (b)).
**Everything else below is the session's design.**

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
   that email as of its last sign-in, nothing changed; 2 usage (neither flag, both, `--email` given
   twice, an extra argument, or an email without exactly one `@`), nothing changed; 3 no file, not writable, locked past the busy timeout, not migrated, or
   not run as the file's owner, nothing changed; 4 the cutoff is written but the read-back found
   or could not check something.
4. **What it prints.** Counts and the cutoff only, and that it does not secure the Google account
   itself. A reader that has gone away (`BrokenPipeError`) does not change the exit code: it still
   says what the run did to the file. Usage errors print one fixed sentence: argparse's own `error()` echoed the arguments
   (Codex; the planner reproduced `unrecognized arguments: person@example.invalid`). Other errors
   name the exception type only. It stores no record of its runs (CHG-083 (b)).
5. **Every process reads the cutoff on each signed-in request.** `SessionRepository.get`'s
   cache-hit branch calls `_refused_by_durable_cutoff`, outside the repository lock. An anonymous
   session (the anonymous maximum age) never reads the store. Otherwise it reads
   `sessions_valid_after(account, lock_timeout=SIGNED_IN_CUTOFF_LOCK_TIMEOUT_S)`. A cutoff at or
   after the session's start ends the account's cached sessions (`end_sessions_of`) and refuses
   the request. It runs on the request thread, so a stalled GC thread cannot let a session
   through. The same guard ends another process's cached copy after a sign-out everywhere.
6. **Fail closed when the cutoff cannot be read (CHG-083 (a)).** The store not ready, its lock not
   acquired within 1.0 s, a closed store, or a failed read refuses the signed-in request; the 401
   is the generic `SESSION_EXPIRED`. The refusal leaves the cached copy, so the next request checks
   again. While the session-safety tables are not ready, `sessions_valid_after` answers by the
   account row (Codex's blocker): no row `(True, None)`, a row or a failed read `(False, None)`.
7. **The 1.0 s bound** (`session_store.SIGNED_IN_CUTOFF_LOCK_TIMEOUT_S`) covers the cutoff read's
   wait for the store lock only. It is above every routine hold measured (the first history sweep
   297 ms with `secure_delete` on, which the store always sets, ADR-0172; the command's 68 ms; 205 ms behind a 0.3 s outside write lock) and
   well under the 5 s a stuck write can take. A module constant, not a setting, like
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
11. **A restore decides the session's kind once.** `_restore` asks `is_anonymous` while the
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
- ADR-0002 gains a second writer. It is short and rare: one transaction of milliseconds per run.
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
  checked like a signed-in one's, including the 1 s bound.
- **A request already past its check** when the command commits finishes that request. It is
  checked again at its spend key (ADR-0137, decision 3), because `spend_meter_for` calls `get`.
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

## Related

- ADR-0002, ADR-0137, ADR-0138, ADR-0139, ADR-0144, ADR-0172, ADR-0174, ADR-0175
- `docs/41-security-controls.md` SC-104
- `docs/analysis/2026-10-17-asvs-5-level-2-check.md` V7.4.5, V7.5.2
- `docs/analysis/2026-10-20-w87-3-end-sessions-failure-modes.md`
- `DEPLOY.md`, "End sessions"
