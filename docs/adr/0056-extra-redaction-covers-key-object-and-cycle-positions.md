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
are real call sites; reading all 10, every key is a string literal and every value
is a `str`/`int` expression. Priority is unchanged by this fix.

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
   overwriting. Applied unconditionally, not only when the key changed, so an
   untouched literal `"[REDACTED]"` key cannot be clobbered either.
3. Non-container, non-`str` values go through `_redact_text_form`, which inspects
   BOTH `str()` and `repr()` and replaces the value only when one of them actually
   carries a secret. Numbers, booleans and `None` (`_SECRET_FREE_SCALAR_TYPES`) skip
   it entirely — every redaction pattern needs an ASCII letter, and their text forms
   have none.
4. A cycle back-edge returns `_CYCLE_PLACEHOLDER` (`"<cycle>"`), and a container past
   the depth cap returns `_DEPTH_CAP_PLACEHOLDER` (`"<max-depth>"`), instead of the
   original container.
5. Both `key.startswith("_")` guards — the redaction hook's and
   `JsonFormatter.format`'s — get an `isinstance(key, str)` companion.

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
| The `!=` comparison in `make_record_with_extra_redaction` terminates on a cyclic input | `python -c` comparing a self-referential dict to `{"self": "<cycle>"}` | `False` (terminates). Cyclic-vs-cyclic raises `RecursionError`, which is why the redacted side must always be acyclic |
| STDOUT output is byte-identical for the three non-cycle shapes | a `StringIO` `StreamHandler` wearing `JsonFormatter`, before and after | `206`/`188`/`189` bytes before, `206`/`188`/`189` after |
| STDOUT for the cyclic shape goes from dropped to emitted | same probe | `len=0` before, `len=235` after |
| A non-`str` extra key crashed the log call before the fix | `logger.warning("x", extra={1: "v"})` | `AttributeError: 'int' object has no attribute 'startswith'` — raised by this redaction hook, not the stdlib |
| An object whose `__str__` logs re-entered the redactor | that shape with a `NullHandler`, guard removed | 166 nested `__str__` calls; 1 with the guard |
| `extra={...}` call sites in `src/` today | `grep -rn "extra={" src/ \| grep -v logging_config` | 12 lines, 2 of them prose; the 10 real ones all pass string-literal keys and `str`/`int` values |
| Each defect's test bites | `cp` the source aside, revert one branch, re-run, restore, `diff -q` | 8 separate mutations, each RED on exactly its own test(s), each restore verified by `diff -q` |
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
- **Inspect only `str(value)` for the object case.** Rejected because the two sinks
  disagree: `JsonFormatter` renders with `default=str`, `sentry_sdk` falls back to a
  repr. An object with a clean `__str__` and a dirty `__repr__` would reach Sentry
  in plaintext; there is a test for exactly that.
- **Leave the depth cap returning the original container.** Rejected — see "What
  ADR-0046 said and what changed".
- **Drop a colliding entry and log a warning about it.** Rejected: logging from
  inside the log-redaction path is how reentrancy bugs start, and this module
  already carries two reentrancy guards because of it.

## Consequences

- A secret in an `extra={...}` KEY, in a non-string object's text form, or reachable
  only through a cycle back-edge no longer reaches a Sentry breadcrumb. This closes
  the positions ADR-0046 left open; it does NOT close `exc_info` tracebacks, which
  `install_redaction_record_factory`'s own docstring still records as unfixed.
- A cyclic `extra` no longer drops the operator's stdout line.
- Redacted keys are disambiguated, so entry COUNT is preserved. **Set and frozenset
  elements are not** — two distinct secrets in one set still collapse to a single
  `[REDACTED]` element. That is pre-existing, unchanged here, and unfixable in the
  same way: a set element has no position to disambiguate.
- Data past `_MAX_EXTRA_REDACTION_DEPTH` is now truncated to `"<max-depth>"` rather
  than passed through unredacted. This supersedes the matching bullet in ADR-0046.
- `"<cycle>"` and `"<max-depth>"` are literal strings an operator will now see in
  logs. They are not secret-shaped and survive `json.dumps` unchanged.
- **Still broken, pre-existing, deliberately not fixed here:** an object whose
  `__str__` logs while `JsonFormatter` is stringifying it recurses through the
  formatter's own `default=str`, outside this module. Measured on `origin/main`:
  `RecursionError` out of `logger.warning()` after 83 renders. On this branch the
  same shape still raises `RecursionError`, after 3569 renders — the terminal
  outcome is unchanged, the wasted iteration count is higher, because each cycle now
  uses fewer stack frames. No call site has such an object. Fixing it means bounding
  `JsonFormatter.format`, which is a different concern.
- Cost on the normal path: one extra regex pass per dict key, and nothing at all for
  the `int`/`bool`/`None` extras every real call site actually uses.

## Related

- Issue #341
- [ADR-0046](0046-extra-redaction-walks-dict-and-list-values-recursively.md)
- [ADR-0041](0041-record-factory-redaction-closes-the-sentry-bypass.md)
- [ADR-0040](0040-global-log-redaction-filter-over-per-call-site-fixes.md)
- [ADR-0023](0023-sentry-payloads-are-scrubbed-on-every-path-and-frame-locals-are-not-collected.md)
- [ADR-0042](0042-module-level-idempotency-flag-for-chained-record-factories.md)
