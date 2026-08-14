# ADR-0042: A module-level flag governs `install_redaction_record_factory` idempotency, not a marker on the current factory

## Status

Accepted — 2026-08-14 (issue #313, PR #315 round-2 review follow-up)

## Context

ADR-0041 added `install_redaction_record_factory`, guarded by:

```python
current = logging.getLogRecordFactory()
if getattr(current, "_i313_redaction_factory", False):
    return
```

— "if the factory installed right now is already mine, do nothing." That
check only looks at the OUTERMOST factory. `setup_json_logging` calls this
function and then `install_request_id_record_factory()` right after, which
wraps its OWN factory on top (`request_id.py:105-117`, the same pattern).
So after one `setup_json_logging()` call, the outermost factory carries the
request-id marker, not the redaction one.

`setup_json_logging`'s own docstring claims re-running it is safe — "so
calling this from both the app and the audit script never doubles the
output" — but that claim was only ever verified for the handlers it
manages directly, not for the two record factories it installs as a side
effect. Measured 2026-08-14 with a subprocess calling
`install_redaction_record_factory()` + `install_request_id_record_factory()`
three times in a row, counting the resulting factory chain by walking each
closure's `current` cell: **3 layers after the first call, 5 after the
second, 7 after the third** — unbounded growth, two new layers every time,
because the redaction check (blind to the request-id marker) always wraps
again, and the request-id check (now facing a chain whose outermost layer
is the just-added redaction wrap) does too.

Two consequences, both real:

- **Performance.** Every log record in the process now pays for N redundant
  `getMessage()` + regex passes instead of 1, growing without bound for the
  life of the process.
- **Reentrancy.** With two redaction layers chained (request-id factory
  sandwiched between them), a message argument whose `__str__` itself logs
  recurses through BOTH layers, because each layer's own reentrancy guard
  (a per-thread flag, see the factory's docstring) is checked only against
  ITS OWN state — one layer's guard does not know the other layer is also
  mid-redaction. Measured: one level of `__str__`-that-logs, which the
  single-layer guard bounds to depth 1, reached depth 2 once a second layer
  existed.

## Decision

Track installation with a plain **module-level boolean**
(`_redaction_factory_installed` in `logging_config.py`), checked and set
**before** anything about the currently-installed factory is inspected.
A second call — from anywhere, at any point relative to
`install_request_id_record_factory()` — is now a true no-op regardless of
what else has been chained on top in between.

The per-thread reentrancy guard inside the factory closure is also moved to
be checked and set **before** calling `current(*args, **kwargs)`, not
after — so a reentrant call triggered from inside that inner call (e.g. by
a chained factory further down, or by argument formatting during the inner
call) is caught by this layer's own flag instead of slipping through the
gap between "record built" and "guard set."

## Rationale

- A module-level flag is simpler to reason about than trying to make the
  marker-on-current check walk the whole chain (which would need to know
  how to unwrap arbitrary future factories, including ones this module
  knows nothing about) — and it matches the actual invariant that matters:
  "has THIS module's installer already run," not "is THIS module's factory
  currently the outermost one."
- Checking the reentrancy guard before calling `current()` closes the
  specific ordering gap the double-chain scenario exposed, but is also
  correct in the single-layer case: the guard now protects the ENTIRE
  make-record pipeline this closure is part of, not just this closure's own
  post-processing step.

## Consequences

- `install_redaction_record_factory()` is now safe to call any number of
  times, in any order relative to `install_request_id_record_factory()`,
  from any thread — matching what `setup_json_logging`'s docstring already
  claimed about the module as a whole.
- **`request_id.install_request_id_record_factory` has the same
  marker-on-current defect and is NOT fixed here** (rule 17, one concern
  per pull request — this PR's concern is issue #313's redaction path).
  Measured behaviour: in the 3-call subprocess reproduction above, the
  request-id layer also grows (its own marker check has the identical
  blind spot, mirrored from this module). A future PR should apply the same
  module-level-flag fix there; tracked as a follow-up, not filed as a
  separate issue here to avoid backlog churn ahead of triage.
- `tests/unit/test_logging_config_sentry_redaction.py::test_calling_setup_json_logging_repeatedly_does_not_grow_the_factory_chain`
  pins the chain-length invariant via a subprocess (isolated from other
  tests' process-global logging state) and is red against the reverted
  marker-on-current check (measured `[3, 5, 7]` instead of `[N, N, N]`).

## Rejected alternatives

- **Make the marker check walk the whole factory chain**, unwrapping each
  layer via its closure's `current` cell until a match is found or the
  chain ends. Rejected: fragile (depends on every factory in the chain,
  including future ones this module has never heard of, exposing its
  `current` cell the same way), and solves a problem a simple flag solves
  without the introspection.
- **Leave it as a "known gap, unfixed"** the way ADR-0041 left the
  `exc_info` gap. Rejected: unlike that gap (no current call site triggers
  it), this one is triggered by `setup_json_logging`'s own documented
  contract — "safe to call from both the app and the audit script" — which
  the audit script script literally does, making this a live, not
  hypothetical, path.

## Related

- Issue #313.
- ADR-0041 — introduces `install_redaction_record_factory`; this ADR fixes
  a defect in that function's idempotency and reentrancy handling.
- `request_id.py`'s `install_request_id_record_factory` — shares the exact
  same marker-on-current pattern and the same latent defect, deliberately
  left unfixed here per the Consequences section above.
- `tests/unit/test_logging_config_sentry_redaction.py` — the chain-growth
  and reentrancy-ordering tests added alongside this fix.
