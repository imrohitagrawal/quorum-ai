# ADR-0046: `extra={...}` redaction walks dict/list values recursively, not just top-level strings

## Status

Accepted — 2026-08-14 (issue #313 residual gap)

## Context

ADR-0041 added `make_record_with_extra_redaction`, which redacts every
top-level `extra={...}` field whose value is a `str`. Its guard was:

```python
if key in _RESERVED_RECORD_ATTRS or key.startswith("_") or not isinstance(value, str):
    continue
```

The `isinstance(value, str)` check was a deliberate scope decision — ADR-0041's
docstring reasoned "a non-string value cannot carry a secret-shaped substring
the way `str()`-of-something can." That reasoning holds for `int`/`bool`/`None`
but is false for `dict` and `list`: those containers routinely hold strings one
level down, and `isinstance(value, str)` is `False` for a dict, so the entire
value — and every secret inside it — was skipped, not just the container
itself.

Confirmed by a real reproduction, not a hypothetical: a real `sentry_sdk`
client wired to a `before_breadcrumb` capture hook (the same method ADR-0041
used), calling

```python
logger.warning("...", extra={"error": {"api_key": "sk-..."}})
```

The raw key reached the Sentry breadcrumb's `data` field in full plaintext.
This is the same Sentry-bypass class ADR-0041 closed for a plain top-level
string extra — `Logger.callHandlers` reads `record.__dict__` directly and
never goes through `JsonFormatter`'s final-string scrub — just triggered by a
container-shaped value instead of a string-shaped one.

## Decision

Redact `extra={...}` values **recursively**: a new helper,
`_redact_extra_value`, redacts a `str` directly, walks a `dict`'s values and a
`list`'s elements (rebuilding a fresh container at each level rather than
mutating in place), and leaves any other value (`int`, `bool`, `None`, or
anything else not itself worth walking) unchanged — the same "non-string
scalars carry no secret-shaped text" reasoning ADR-0041 already established,
now scoped correctly to apply only to genuine scalars instead of to every
non-`str` value including containers.

`make_record_with_extra_redaction`'s per-key guard changes from
`isinstance(value, str)` to `isinstance(value, (str, dict, list))`, so a
dict/list extra is now handed to `_redact_extra_value` instead of skipped
outright.

**Rebuild, never mutate in place.** The dict/list a call site passes as
`extra={...}` may be a variable the caller logs again, inspects, or
serializes elsewhere after the log call returns. `_redact_extra_value`
returns a **new** container at every level (`{k: _redact_extra_value(v) for
k, v in value.items()}`, `[_redact_extra_value(v) for v in value]`) rather
than assigning into the original dict/list — so a caller's own object is
never silently altered by the act of logging it. This is proven directly:
`test_a_dict_valued_extra_is_not_mutated_in_place` logs a dict extra, then
asserts the original object still equals an untouched copy taken before the
log call.

### Rejected alternative: redact only one level deep

Walking exactly one level (the dict's direct values, the list's direct
elements) would have caught the exact reproduction shape above but not a
secret nested two levels down (a dict inside a list inside a dict — a
realistic shape for e.g. `extra={"context": {"attempts": [{"detail":
secret}]}}`). The recursive walk has no depth limit, so it is not vulnerable
to the next call site nesting one level deeper than whatever a
one-level-deep fix happened to cover. Proven by
`test_a_secret_doubly_nested_dict_in_list_in_dict_never_reaches_sentry`,
which fails under a one-level-deep implementation and passes under the
recursive one.

## Consequences

- Every genuine dict/list-nested secret in an `extra={...}` field is now
  redacted before it reaches a Sentry breadcrumb or event, at any nesting
  depth, matching the guarantee ADR-0041 already gave top-level string
  extras.
- A caller's own `extra={...}` dict/list object is never mutated as a side
  effect of logging it — the redacted value only ever replaces
  `record.__dict__[key]`, never the caller's original object.
- `tuple`-valued extras are still left untouched, same as before this
  change — no observed call site uses one, and a tuple is not the JSON-like
  shape this redaction targets. If a future call site logs a
  tuple-of-strings extra, it would need the same treatment `dict`/`list` got
  here.

## Related

- ADR-0040: global log-redaction filter in `JsonFormatter`, over
  per-call-site fixes.
- ADR-0041: record-factory redaction closes the Sentry bypass, and first
  established (then under-scoped) the `isinstance(value, str)` extra check
  this ADR replaces.
- ADR-0042: module-level idempotency flag for chained record factories —
  unrelated defect in the same function, fixed separately.
