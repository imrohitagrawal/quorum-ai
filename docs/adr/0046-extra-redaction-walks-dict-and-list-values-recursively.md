# ADR-0046: `extra={...}` redaction walks dict/list/tuple/set values recursively, bounded by a depth/cycle guard

## Status

Accepted — 2026-08-14 (issue #313 residual gap)

**Superseded on the DEPTH-CAP BEHAVIOUR by
[ADR-0056](0056-extra-redaction-covers-key-object-and-cycle-positions.md)**
(2026-08-18, issue #341). This ADR left a container past the cap — and a cycle
back-edge — returned AS-IS, unredacted. ADR-0056 substitutes `"<max-depth>"` and
`"<cycle>"` instead, because returning the original container is what let a
secret below the cap reach Sentry and what left `record.__dict__` cyclic, so
`json.dumps` raised and the operator's stdout line vanished. ADR-0056 also
extends the walk to any `Mapping` and to the object text positions. Everything
else here still stands, in particular why a record factory and not a filter.

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
secret}]}}`). An unbounded recursive walk is not vulnerable to the next call
site nesting one level deeper than whatever a one-level-deep fix happened to
cover. Proven by
`test_a_secret_doubly_nested_dict_in_list_in_dict_never_reaches_sentry`,
which fails under a one-level-deep implementation and passes under the
recursive one.

### Review finding: an unbounded recursive walk is itself a crash risk

A same-day adversarial review of this change (before merge) found that an
*unbounded* recursive walk trades one bug for another. Two real triggers,
both confirmed live by actually calling `logger.warning()`:

1. **A self-referential container.** `d = {}; d["self"] = d;
   logger.warning("x", extra=d)` recurses forever and raises
   `RecursionError` straight out of the logging call — a single malformed
   `extra={}` would take down every log call that reaches it, which is worse
   than the plaintext-secret bug this change exists to fix.
2. **A merely very deep, non-cyclic container** (~2000 levels) exhausts
   CPython's default recursion limit the same way, with no `id()` ever
   repeating — so a cycle guard alone does not stop it; an explicit depth
   cap is needed too.

The same review also found that a secret sitting inside a `tuple` nested in
an otherwise-redacted dict/list — a realistic shape,
`extra={"tokens": (secret,)}` — reached a real Sentry breadcrumb in
plaintext, because the walk originally recognised only `dict`/`list` and
returned any other value, tuple included, unchanged.

**Decision, revised:** `_redact_extra_value` now takes an `_ancestors:
frozenset[int]` parameter tracking the `id()` of every container on the
current recursion PATH (not every container ever seen — two sibling
branches legitimately referencing the same object is normal aliasing, not a
cycle, and both must still be walked). A container whose `id()` is already
on that path is a genuine cycle and is returned unchanged rather than
recursed into again. A module-level `_MAX_EXTRA_REDACTION_DEPTH = 25` caps
recursion depth independently of the cycle guard, catching the deep
non-cyclic case; #313's own reproduction shapes are 2-3 levels deep, so 25
is generous headroom for any real call site while bounding a pathological
one. Past either limit, the remaining sub-value is returned as-is
(unredacted below that point) rather than raising — a stalled/crashed log
call is worse than an edge case no real call site will hit.

`_EXTRA_CONTAINER_TYPES` widens from `(dict, list)` to
`(dict, list, tuple, set, frozenset)`, closing the tuple gap and the same
gap for `set`/`frozenset` by construction. Each recursion level passes a new
frozenset (`_ancestors | {id(value)}`) to its own children rather than
mutating a shared set, so sibling branches never see each other's ancestry.

Proven by 4 new tests: a self-referential dict and a 2000-level-deep dict
each log successfully instead of raising `RecursionError`; a secret inside
a tuple and inside a set are each redacted before reaching the breadcrumb,
with a non-secret sibling element surviving as the positive partner.

## Consequences

- Every genuine dict/list/tuple/set-nested secret in an `extra={...}` field
  is now redacted before it reaches a Sentry breadcrumb or event, up to 25
  levels deep, matching the guarantee ADR-0041 already gave top-level
  string extras.
- A caller's own `extra={...}` container is never mutated as a side effect
  of logging it — the redacted value only ever replaces
  `record.__dict__[key]`, never the caller's original object.
- A self-referential or pathologically deep `extra={...}` container can no
  longer crash a log call by raising `RecursionError`. **The rest of this
  bullet, "the walk degrades to leave the excess depth unredacted", was
  superseded by ADR-0056** — the excess depth is now replaced by
  `"<max-depth>"`, and a cycle back-edge by `"<cycle>"`. As written here it
  was also incomplete: leaving the excess unredacted still crashed the STDOUT
  path for a cyclic container, because the result stayed cyclic and
  `json.dumps` refused it.
- `_MAX_EXTRA_REDACTION_DEPTH = 25` is a deliberately generous, unmeasured
  bound — no real call site is known to nest anywhere near that deep. If a
  genuine call site is ever found nesting close to the cap, the right fix is
  raising the constant with evidence of the real shape, not silently
  swallowing more.

## Related

- ADR-0040: global log-redaction filter in `JsonFormatter`, over
  per-call-site fixes.
- ADR-0041: record-factory redaction closes the Sentry bypass, and first
  established (then under-scoped) the `isinstance(value, str)` extra check
  this ADR replaces.
- ADR-0042: module-level idempotency flag for chained record factories —
  unrelated defect in the same function, fixed separately.
