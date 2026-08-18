# ADR-0056: Extra redaction covers the key, object and cycle positions, and a back-edge becomes a placeholder

## Status

Accepted — 2026-08-18. Closes issue #341.

Extends [ADR-0046](0046-extra-redaction-walks-dict-and-list-values-recursively.md)
(the recursive walk over `extra={...}` — note its title says *values*, and that
turned out to be exactly the scope of the defect), which in turn sits on
[ADR-0041](0041-record-factory-redaction-closes-the-sentry-bypass.md) (a record
factory is what closes the Sentry bypass) and
[ADR-0040](0040-global-log-redaction-filter-over-per-call-site-fixes.md) (one global
scrub instead of per-call-site fixes). Constrained by
[ADR-0023](0023-sentry-payloads-are-scrubbed-on-every-path-and-frame-locals-are-not-collected.md): `main.py`'s
`_scrub_user_text` is a USER-PROSE scrubber, not a credential scrubber, and this
ADR does not lean on it. Supersedes one consequence of ADR-0046 — see
"What ADR-0046 said and what changed" below.

## Context

Every position ADR-0046's walk did not cover leaked to Sentry, and only to Sentry:
the stdout sink was already clean in all four cases, because `JsonFormatter` scrubs
the fully-rendered JSON string where a key is just more text, while Sentry's
`LoggingIntegration` reads `record.__dict__` directly and never reaches that scrub.

Four bypasses, each reproduced against a REAL `sentry_sdk` client (2.63.0) with a
`before_breadcrumb` capture hook — the harness
`tests/unit/test_logging_config_sentry_redaction.py` already used. Reproduced on
this branch as failing tests before the fix; the verbatim failure text below is
from `pytest --tb=line` on that RED run.

1. **Dict KEY position.** `_redact_extra_value`'s dict branch rebuilt the mapping
   as `{key: _redact_extra_value(item, ancestors)}` — the key never reached
   `_redact_secrets`.
   `the secret-shaped dict KEY reached a Sentry breadcrumb: {'error': {'sk-or-v1-1234567890abcdefKEYPOSITION': 'rate-limited', 'ok-key': 'fine'}}`
2. **Top-level extra KEY position (`record.__dict__`).** The same gap one level up,
   in `make_record_with_extra_redaction`.
   `the secret-shaped top-level extra KEY reached a Sentry breadcrumb: {'sk-or-v1-1234567890abcdefTOPKEY': 'v', 'ok-key': 'fine'}`
3. **Non-string, non-container objects.** `make_record_with_extra_redaction`
   skipped any value failing `isinstance(value, (str,) + _EXTRA_CONTAINER_TYPES)`,
   so `extra={"error": exc}` — the exception OBJECT rather than `str(exc)`, one
   keystroke from `synthesis.py`'s real call shape — went through untouched.
   `bytes` and any object with a secret-carrying `__repr__` leaked the same way.
   `the secret inside a non-string extra object reached Sentry: {'error': RuntimeError('Bearer sk-or-v1-1234567890abcdefOBJECT'), 'attempt': 2}`
4. **Cycle back-edge.** The cycle guard returned the ORIGINAL ancestor container,
   splicing an untouched plaintext subtree into the redacted result — AND leaving
   `record.__dict__` cyclic, so `JsonFormatter`'s `json.dumps` raised
   `ValueError: Circular reference detected`, `logging.Handler.handleError`
   swallowed it, and the operator's stdout line was dropped entirely.
   `the cycle back-edge carried an unredacted subtree to Sentry: {'error': {'inner': {'api_key': '[REDACTED]', 'parent': {'inner': {'api_key': 'sk-or-v1-1234567890abcdefCYCLICLEAK', 'parent': {...}}}}}}`

**This is LATENT, not live — defence in depth.** No call site puts a container, an
object, or a computed key into `extra` today.
`grep -rn "extra={" src/ | grep -v logging_config` returns 12 lines, of which 2 are
prose (`telemetry_sink.py:105`, `request_id.py:90` are comments). The remaining 10
are real call sites, and reading all of them, none passes a container or an
object — only strings, numbers, booleans and `None`. (Two details an earlier draft
of this paragraph got wrong: `providers.py`'s `**_billing_evidence_shape(exc)` is
not a string literal at the call site, and both it and
`query_run_orchestration.py`'s `status_value.value if status_value else None` can
pass `None`/`False`. Both are covered by `_SECRET_FREE_SCALAR_TYPES`, so the
conclusion stands.) Priority is unchanged by this fix.

**`main.py`'s `before_send` does not save you.** Driven with the real hook imported
from `src/product_app/main.py`, capturing the serialized envelope after
`before_send`: `SECRET SURVIVED PRODUCTION before_send: True`. `_scrub_user_text`
touches `request.data`, `extra[*query*|*prompt*]` and frame variables only — never
`event["breadcrumbs"]` — and carries no credential regex. That is ADR-0023's stated
scope, not a bug in it. Fixing `before_send` is a separate concern and a separate
PR; it is deliberately not in this diff.

**The existing test was vacuous, and proven so.** With `_redact_extra_value`'s body
replaced by `return value` — extra redaction removed ENTIRELY —
`test_a_self_referential_extra_dict_does_not_crash_the_log_call` on `origin/main`
still passed (`1 passed`; whole file `6 failed, 11 passed`). It installed
`logging.NullHandler()` and asserted only "does not raise", so it never formatted
the record and never read a breadcrumb — blind to both consequences of the very
input it was named after. It was STRENGTHENED in place rather than partnered:
under the same mutation the strengthened version now fails
(`the cycle back-edge carried an unredacted subtree to Sentry: ...`).

## Decision

Redact every position, and never hand back a container the walk refused to descend
into.

1. `_redact_extra_value`'s dict branch redacts KEYS as well as values, at every
   depth, and `make_record_with_extra_redaction` does the same for
   `record.__dict__` keys (written through `record.__dict__` rather than
   `setattr`/`delattr`, because a key there is not guaranteed to be a `str`).
2. A key collision gets a numeric discriminator via `_disambiguated_key` instead of
   overwriting, at both levels. Inside `_redact_extra_value` it runs on every key,
   so an untouched literal `"[REDACTED]"` key cannot be clobbered by a redacted
   one; in the record factory it runs only on the keys redaction actually changed,
   which is sufficient there because a key it did not change is already the key
   sitting in `record.__dict__` and is never re-inserted.
3. Non-container, non-`str` values go through `_redact_text_form`, which inspects
   `str()`, `repr()` AND `__sentry_repr__()` — the three ways a sink is known to
   turn an object into text — and replaces the value only when one of them actually
   carries a secret. Numbers, booleans and `None` (`_SECRET_FREE_SCALAR_TYPES`) skip
   it entirely: every redaction pattern needs a specific ASCII token (`Bearer`,
   `sk-`, `AKIA`, `api_key=`) and no text form of those types produces one — **of
   those types EXACTLY, which is why the test is `type(value) in ...` and not
   `isinstance`.** An earlier draft of this point said "those types" while the code
   used `isinstance`, and that is false for a SUBCLASS: `sentry_sdk`'s serializer
   renders numbers via `isinstance(obj, (bool, int, float))`, a tuple that does not
   contain `complex`, so a `complex` subclass falls through to `safe_repr` and its
   TEXT form is what gets published. Measured row below.
   This covers `sentry_sdk`'s object-RENDERING paths. Its `Mapping` and sequence
   branches walk contents instead, which is why point 6 exists.
4. A cycle back-edge returns `_CYCLE_PLACEHOLDER` (`"<cycle>"`), and a container past
   the depth cap returns `_DEPTH_CAP_PLACEHOLDER` (`"<max-depth>"`), instead of the
   original container.
5. Both `key.startswith("_")` guards — the redaction hook's and
   `JsonFormatter.format`'s — get an `isinstance(key, str)` companion, and every
   rebuilt mapping puts its keys through `_serializable_key`, so a key `json.dumps`
   cannot take (a `tuple`) is folded to its `str` form instead of costing the
   operator the whole line.
6. `_EXTRA_CONTAINER_TYPES` names `Mapping`, not `dict`, so any mapping Sentry
   would walk is walked here first.
7. The redactor never compares a caller's object with a bare `!=`. `_differs`
   answers by identity where it can and treats an `__eq__` it cannot evaluate as
   "changed"; the value position does not compare at all any more.
8. The record factory replaces a top-level extra key when its redacted form has a
   different TYPE, not only a different value. A `str` subclass with a
   secret-carrying `__str__` redacts to an EQUAL plain `str`, so an equality test
   alone said "unchanged" and wrote the caller's original key object back for
   `sentry_sdk`'s `str(k)` to publish. Measured row below.
9. Rebuilding a container is wrapped in a `try`/`except` that degrades to
   `_UNREADABLE_PLACEHOLDER` (`"<unreadable>"`). Point 6 put caller code
   (`__iter__`, `__getitem__`, `items`) on the redactor's path for the first time,
   and a mapping that raises there took `logger.warning()` down with it — the
   dropped-line failure this ADR exists to close, at a new position. The container
   is replaced rather than passed to `_redact_text_form`, because a container this
   module could not finish reading may still hand Sentry — whose own traversal
   fails separately — a subtree nothing here inspected. Caught at the level that
   failed, so a broken sub-container costs only its own subtree.
10. Key disambiguation carries a per-base `next_suffix` memo across one mapping's
    rebuild. Rescanning from `2` for every collision is quadratic, and a
    per-API-key usage map collides on every key. Measured row below.

### What ADR-0046 said and what changed

ADR-0046's Consequences said the walk "degrades to *leave the excess depth
unredacted*". **That is no longer true**, and the change is deliberate, not
incidental to points 1-3.

The depth cap and the cycle guard are the same `return value` statement four lines
apart, and a cycle whose period EXCEEDS the depth cap trips the cap first — the
cycle guard never sees a repeated `id()` within 25 levels. Fixing only the cycle
guard would have left the dropped-line failure alive for that shape while the ADR
claimed it closed. Measured: with the cap still returning the original container, a
30-link cycle reproduces the empty stdout line
(`the stdout log line was dropped entirely (json.dumps raised on the long cycle)`).

The cost is that genuinely deep, non-cyclic data past 25 levels is now truncated to
`"<max-depth>"` rather than emitted unredacted. Given no call site passes a container
at all, truncating beyond 25 levels is the safer default. Issue #341's scope note
asked that the depth cap be left alone; **this crosses that line on purpose**, and
says so here rather than shipping a guarantee with a hole in it.

## Measured

Every row names the command that produces it. Anchors are greps, not line numbers.

| Claim | Command | Result |
|---|---|---|
| Two distinct secret keys collapse into one entry without a discriminator | `python -c` over `_redact_secrets` on `{S1:"a", S2:"b"}` | `{'[REDACTED]': 'b'}` — 2 entries in, 1 out |
| Every kind of legal dict key stays hashable after redaction | `python -c` over `_redact_extra_value` for str/int/float/bool/None/tuple/frozenset/bytes/custom-object keys | all hashable; a key that could become unhashable would have to contain a `list`/`set`, and `{(["x"],):1}` is already a `TypeError` |
| The cycle placeholder survives `json.dumps` and is not itself redacted | `python -c 'json.dumps({"a":"<cycle>"})'`; `_redact_secrets("<cycle>")` | `{"a": "<cycle>"}`; `<cycle>` |
| A bare `!=` against a caller's object crashed the log call | `logger.warning("boom", extra={"o": obj})` for an object whose `__ne__` raises / returns a non-bool, on this branch before `_differs` and on `origin/main` | branch: `ValueError: ne exploded`, `ValueError: truth value of an array is ambiguous` raised out of `logger.warning`; `origin/main`: line emitted normally |
| A bad-`__eq__` extra KEY never reaches this module at all | same call with the object as the KEY, redaction factory NOT installed | raises inside CPython's own `Logger.makeRecord` (`logging/__init__.py:1655`, `key in ["message", "asctime"]`) on 3.12.13 |
| A secret inside a non-`dict` `Mapping` reached Sentry | a `collections.abc.Mapping` subclass with no custom `__repr__`, through `sentry_sdk.serializer.serialize` | before: `{"headers": {"authorization": "sk-or-v1-...LEAK"}}`; after: `{"headers": {"authorization": "[REDACTED]"}}` |
| A secret in `__sentry_repr__` reached Sentry | an object with clean `__str__`/`__repr__`, same serializer | before: `{"o": "authorization: Bearer sk-or-v1-...LEAK"}`; after: `{"o": "clean"}` |
| A `tuple` extra key cost the operator the stdout line | `logger.warning("boom", extra={("a","b"): "v"})`, and the same key nested | before: stream empty, `TypeError: keys must be str, int, float, bool or None, not tuple` swallowed by `handleError`; after: line emitted with the key as `"('a', 'b')"` |
| STDOUT is unchanged against `origin/main` **for the eight shapes named here** | scalars, nested dict, list, secret string, object, tuple, frozenset, typical — through a `StringIO` `StreamHandler` wearing `JsonFormatter`, timestamps blanked, `diff` of the two trees' output | no difference. (`frozenset` matches only after normalising element ORDER: that is per-process hash-seed noise on both trees — six runs of one tree printed both orders) |
| STDOUT DOES change for a `Mapping` that is not a `dict` subclass | the same probe extended to a `Mapping` subclass, `ChainMap`, `MappingProxyType`, `defaultdict`, `OrderedDict`, `Counter` and `bytes` | the first three now render EXPANDED (`{"accept": "json"}`) where `origin/main` printed a repr (`<Bag object at 0x…>`, `ChainMap({'a': 1})`, `{'a': 1}`) — decision point 6 working, and an improvement, but not "unchanged". The other four are byte-identical: `defaultdict`/`OrderedDict`/`Counter` are `dict` subclasses the old walk already covered, and `bytes` was already caught by `JsonFormatter`'s final-string scrub |
| A `complex` SUBCLASS reached a breadcrumb in plaintext | a `complex` subclass with a secret-carrying `__repr__`, through `sentry_sdk.serializer.serialize` | before (and on `origin/main`, identically — a pre-existing position, not a regression): `{"v": "Bearer sk-or-v1-…LEAKME"}` while stdout showed `"[REDACTED]"`; after: redacted in both. `int` and `float` subclasses did NOT leak in the value position — Sentry renders them as the number — but are matched by exact type too, because "which subclass does the current SDK take a numeric branch for" is not a property to depend on |
| A subclassed top-level extra KEY reached a breadcrumb in plaintext | a `str` subclass key with a secret-carrying `__str__`, same serializer | before (and on `origin/main`, identically): `{"Bearer sk-or-v1-…LEAKME": "v"}`; after: redacted. The nested form of the same shape (an `IntEnum` key, `{"by_status": {Status.RATE_LIMITED: 3}}`) leaked the same way and is closed by the exact-type scalar test |
| Walking `Mapping` turned a survivable log call into a dropped line | a `Mapping` whose `__getitem__` raises (a lazy header bag / a view over a released connection), and a `list` subclass whose `__iter__` raises | before: `RuntimeError` out of `logger.warning()` into the caller, stream EMPTY — where `origin/main` emitted the line; after: line emitted, the container replaced by `"<unreadable>"`, its clean sibling extras intact |
| Key disambiguation was quadratic | a per-API-key usage map (every key `sk-…`, so every key collides), `NullHandler`, wall clock around ONE `logger.warning` | before: 0.0122s at 500 entries, 0.2176s at 2000, 1.5019s at 5000 (3x entries → ~9x time); after: 0.0011s / 0.0040s / 0.0123s (10x entries → ~11x time), against 0.0013s at 5000 on `origin/main`. Absolute times are machine-dependent; the SHAPE of the curve is the finding |
| STDOUT for the cyclic shape goes from dropped to emitted | same probe | before: the stream is EMPTY; after: one complete JSON line carrying the `message` and every non-cyclic extra. An earlier version of this row quoted an exact byte length — that number moves with the probe's logger name, module, function and line number, and the probe was never in the repo, so no reader could re-derive it |
| A non-`str` extra key crashed the log call before the fix | `logger.warning("x", extra={1: "v"})` | `AttributeError: 'int' object has no attribute 'startswith'` — raised by this redaction hook, not the stdlib |
| An object whose `__str__` logs re-entered the redactor | that shape with a `NullHandler`, in a standalone script, guard removed | 166 nested `__str__` calls; 1 with the guard. The count is stack-depth dependent — the same mutation run inside pytest prints 160 — so treat the magnitude, not the digits, as the finding |
| `extra={...}` call sites in `src/` today | `grep -rn "extra={" src/ \| grep -v logging_config` | 12 lines, 2 of them prose; no real call site passes a container or an object |
| Each defect's test bites | `cp` the source aside, revert one branch of the Decision above at a time, re-run, restore, `diff -q` | every branch listed in Decision was mutated on its own and went RED on exactly its own test(s); each restore verified by `diff -q` |
| The strengthened cyclic test is no longer vacuous | `_redact_extra_value` body → `return value` | `origin/main`'s version: `1 passed`. Strengthened version: `1 failed` |

## Rejected alternatives

- **Fix `main.py`'s `before_send` instead.** Measured not to help
  (`SECRET SURVIVED PRODUCTION before_send: True`) and it is the wrong layer:
  ADR-0041 already decided that the record factory, not a Sentry hook, is where this
  belongs, because it makes every consumer see the same redacted record. Repairing
  `before_send` is still worth doing for the breadcrumbs Sentry synthesises itself —
  a separate concern, a separate PR.
- **Redact keys with a plain dict comprehension.** Measured to lose an entry
  silently (see the first Measured row). A redactor that drops data is a worse
  failure than the one it fixes.
- **Stringify every extra value unconditionally.** Rejected on cost and on blast
  radius: it would change the type of every non-secret object extra and pay a
  `str()` plus four regex passes per record. `_redact_text_form` returns the
  ORIGINAL object whenever neither text form carries a secret, so only a genuine
  hit changes anything.
- **Inspect only `str(value)` for the object case.** Rejected because the sinks
  disagree: `JsonFormatter` renders with `default=str`, `sentry_sdk` prefers
  `__sentry_repr__` and otherwise falls back to a repr. An object with a clean
  `__str__` and a dirty `__repr__` — or a dirty `__sentry_repr__` — would reach
  Sentry in plaintext; there is a test for each.
- **Guard reentrancy with a single per-thread flag.** That was the first form, and
  round 2 measured the cost: the flag was held for the whole `str`/`repr` window,
  so a log call issued from inside one object's `__str__` skipped object-text
  redaction for a DIFFERENT object, and that object's secret reached a breadcrumb
  in plaintext. An `id()`-keyed set stops only the genuine self-reference.
- **Model "how Sentry renders" and stop there.** Rejected as a design: the
  serializer has several branches, and this ADR's first draft covered the repr one
  and claimed the object position closed. Containers are now walked (point 6) and
  all three text renderers inspected (point 3), but the honest statement is the one
  in Consequences — this covers the paths that have been measured, not a proof.
- **Leave the depth cap returning the original container.** Rejected — see "What
  ADR-0046 said and what changed".
- **Drop a colliding entry and log a warning about it.** Rejected: logging from
  inside the log-redaction path is how reentrancy bugs start, and this module
  already carries two reentrancy guards because of it.

## Consequences

- A secret in an `extra={...}` KEY, in a non-string object's text form (`str`,
  `repr` or `__sentry_repr__`), inside a non-`dict` `Mapping`, or reachable only
  through a cycle back-edge no longer reaches a Sentry breadcrumb. Each of those is
  a measured row above.
- **What is still open, stated rather than implied.** `exc_info` tracebacks are
  untouched — `install_redaction_record_factory`'s own docstring already records
  that. Sentry's serializer is covered on the branches that have been measured
  (mapping, sequence, `__sentry_repr__`, repr); a future SDK rendering path would
  need the same treatment, and nothing here proves one does not exist. A log call
  issued from inside an object's own `__str__` still cannot have that same object's
  text redacted — it is being rendered — though since round 2 it no longer affects
  any OTHER object on the inner record.
- A cyclic `extra` no longer drops the operator's stdout line, and neither does a
  container whose own `__iter__`/`__getitem__`/`items` raises — that one is a
  failure this branch INTRODUCED by walking `Mapping` (decision point 6) and then
  closed (point 9). An unreadable container is reported as `"<unreadable>"`.
- A `Mapping` that is not a `dict` subclass (a header bag, `ChainMap`,
  `MappingProxyType`) now renders EXPANDED on stdout where `origin/main` printed a
  repr. Correct — it is the same walk that stops the secret inside it reaching
  Sentry — but it is a visible stdout change, so the "STDOUT is unchanged" row
  above is scoped to the eight shapes it measured rather than stated in general.
- Redacted keys are disambiguated, so entry COUNT is preserved. **Set and frozenset
  elements are not** — two distinct secrets in one set still collapse to a single
  `[REDACTED]` element. That is pre-existing, unchanged here, and unfixable in the
  same way: a set element has no position to disambiguate.
- Data past `_MAX_EXTRA_REDACTION_DEPTH` is now truncated to `"<max-depth>"` rather
  than passed through unredacted. This supersedes the matching bullet in ADR-0046.
- `"<cycle>"`, `"<max-depth>"` and `"<unreadable>"` are literal strings an operator
  will now see in logs. None is secret-shaped and all survive `json.dumps`
  unchanged. `"<unreadable>"` costs the container's whole contents, including
  entries that were read successfully before the failure — deliberate: a
  half-walked container is exactly the case where this module cannot say what it
  did not inspect.
- **Still broken, pre-existing, deliberately not fixed here:** an object whose
  `__str__` logs while `JsonFormatter` is stringifying it recurses through the
  formatter's own `default=str`, outside this module. Measured on `origin/main`:
  `RecursionError` out of `logger.warning()` after 83 renders. On this branch the
  same shape still raises `RecursionError`, after 7055 renders — the terminal
  outcome is unchanged, the wasted iteration count is higher, because each cycle now
  uses fewer stack frames. No call site has such an object. Fixing it means bounding
  `JsonFormatter.format`, which is a different concern.
- Cost. A dict key now goes through `_redact_secrets`, which is four compiled
  patterns, not one. Measured at 20,000 records per shape, best of three
  repetitions, `NullHandler`, branch against `origin/main`, on these three shapes
  stated so a reader can re-derive them:
  **A** `extra={"error": "<80-char string>", "attempt": 2}`,
  **B** `extra={"ctx": {"a": 1, "b": "t", "c": {"d": "u"}}}`,
  **C** `extra={"error": RuntimeError("<80-char string>"), "attempt": 2}`.
  The conclusion, which is what to carry away: the shapes `src/` actually logs
  (A and B) cost a few microseconds more per record, and an OBJECT-valued extra
  (C) costs noticeably more again — roughly half as much again as A on the same
  tree, and about triple what C cost on `origin/main` — which is the
  `str`/`repr`/`__sentry_repr__` renders plus their regex passes.
  **Absolute microsecond figures are deliberately not quoted.** An earlier version
  of this bullet gave them (~44-48µs, "+15µs"); re-running the same comparison on
  a different machine and load produced numbers roughly a fifth of those, with the
  ordering unchanged. The ordering reproduces; the digits do not.
  No call site pays the object cost today; this is here because the day someone
  writes `extra={"error": exc}` they will.

## Related

- Issue #341
- [ADR-0046](0046-extra-redaction-walks-dict-and-list-values-recursively.md)
- [ADR-0041](0041-record-factory-redaction-closes-the-sentry-bypass.md)
- [ADR-0040](0040-global-log-redaction-filter-over-per-call-site-fixes.md)
- [ADR-0023](0023-sentry-payloads-are-scrubbed-on-every-path-and-frame-locals-are-not-collected.md)
- [ADR-0042](0042-module-level-idempotency-flag-for-chained-record-factories.md)
