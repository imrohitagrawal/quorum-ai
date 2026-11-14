# Failure modes: moving sentry-sdk from 2.63.0 to 2.73.0

Written 2026-11-13, before review, on the branch that moves the lock.

Production installs sentry-sdk from `uv.lock` (ADR-0164), so this bump changes the client that
production runs. ADR-0163 ("nothing private reaches Sentry") was measured on 2.63.0, and its
tests check the channels and options that version had. The risk of a minor version is not that
a known guard breaks (the tests would show that) but that the library adds, renames or turns on
something the tests do not know about. Listed before review, from ADR-0163 and
`2026-10-13-w56-sentry-privacy-failure-modes.md`:

1. **A new channel that skips both hooks.** 2.63.0 had three (span streaming, logs, metrics;
   failure mode 12). A later version can add another item type that is sent without passing
   `before_send` or `before_send_transaction`.
2. **A switch changes meaning.** `enable_metrics=False` already stopped working in 2.72.0
   (ADR-0163 decision 1), and `enable_logs` has a second switch in `_experiments`. A switch this
   repository passes may become a no-op, or a second switch may turn a channel back on.
3. **A default turns on.** A new default-on integration, or a changed default for
   `send_default_pii`, `include_local_variables`, `trace_propagation_targets` or request-body
   capture, sends data the options never mention.
4. **The envelope gains a header no hook sees.** ADR-0163 decision 4 removes the dynamic
   sampling context because 2.63.0 copies it into the envelope's `trace` header after the hooks.
   A later version can copy other request data the same way.
5. **The hooks see less.** If the SDK moves request headers, exception values or breadcrumbs to
   a new key, the scrubber's walk still covers the event (decision 3), but the header allow-list
   (decision 2) matches only the `request.headers` it knows.
6. **The tests pin the wrong thing.** A test that passes on 2.73.0 proves only what it checks;
   a mutation that turns a new channel on must go red, or the gap is unwatched.

## What the checks found

Each item was checked against the 2.73.0 source, and the repository's tests were run on 2.73.0.

- Item 2 happened. `enable_logs=False` no longer stops a line written through
  `sentry_sdk.logger`: driven with production's options, 2.73.0 sent a `log` item holding a
  key, and 2.63.0 sent none. The fix is a `before_send_log` hook that drops every log
  (ADR-0163, update of 2026-11-13).
- Items 2 and 3, a near miss. 2.73.0 adds `data_collection`, which supersedes
  `send_default_pii`. Unset, it is derived from `send_default_pii=False`, and headers, cookies
  and the address were redacted or absent as before.
- Items 1, 4 and 5 did not happen: no new item type was sent, the envelope carried no `trace`
  header, and request headers kept their shape.
- Item 6 is why the log gap went unseen: the existing test pins the switch values, not what
  reaches the transport. The new test counts `log` items.
