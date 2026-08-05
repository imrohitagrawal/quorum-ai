# ADR-0005: Reconnect the durable SQLite stores in the background, not at boot only

## Status

Accepted — 2026-08-03 (major-issues batch, issue #123)

## Context

`feedback_store` and `run_history_store` each opened their sink exactly once,
at import time in `main.py`. A transient lock at boot — or a volume that went
read-only mid-life — disabled the per-account spend cap and run-history
persistence **for the entire process lifetime**, recoverable only by restart.

Measured fault shapes that produce it (`tests/integration/
test_feedback_store_write_failures.py`, real SQLite): an EXCLUSIVE lock, a
RESERVED lock on a database with no schema yet, an unwritable volume with no
database file yet. Separately, #109 measured the shape where the store *opens*
fine and later stops writing.

## Decision

Attempt a **reopen on a background thread**, triggered from the request path
(`CostEstimationService.estimate()`), cooldown-gated at
`settings.store_reconnect_cooldown_seconds` (60 s), switchable off via
`settings.store_reconnect_enabled` (default on).

The trigger keys on the **write-health signal** (#109), not on
`get_store() is None`: a store that opened successfully but can no longer write
would never trigger a reopen keyed on absence alone, and that is the production
shape a read-only volume produces.

`run_history_store` has no equivalent signal, so its trigger is deliberately
narrower — absence only. That asymmetry is stated rather than papered over.

## Consequences

- A recovered volume is picked up within one cooldown window, no restart.
- The reopen cost (up to SQLite's 5 s lock-open timeout) is paid on a daemon
  thread, never on a user's request.
- A sustained outage costs at most one reopen attempt per cooldown window, not
  one per request — the DoS `/status` would otherwise invite.
- **Turning `store_reconnect_enabled` off also disables ADR-0004's
  fail-closed mechanism**, because that mechanism is gated on "a reopen was
  tried and did not restore the ledger". Documented on the setting.
- `configure()` deliberately does not close the store it displaces
  (ADR-0002), so installing a fresh handle is as safe as any other caller
  already relies on.

## Rejected alternatives

- **Restart-only recovery** (the status quo). Rejected: a transient lock at
  boot silently disabled a money guard for the life of the process, with one
  boot-time WARNING as the only trace.
- **Reopen synchronously on the request path.** Rejected: a failed reopen costs
  a 5 s lock-open timeout, paid by a user.
- **A periodic timer thread.** Rejected as more machinery for the same effect;
  the request path already provides a natural, load-proportional tick, and a
  process serving no traffic has nothing to recover for.

## Related

- ADR-0002, ADR-0004; issues #101, #109, #122, #123
- `src/product_app/store_reconnect.py`
- Tests: `tests/unit/test_store_reconnect.py`
