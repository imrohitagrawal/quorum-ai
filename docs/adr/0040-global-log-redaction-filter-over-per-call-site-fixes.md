# ADR-0040: A global log-redaction step in `JsonFormatter`, not per-call-site fixes

## Status

Accepted — 2026-08-14 (issue #313)

## Context

`src/product_app/logging_config.py`'s `JsonFormatter` serialises whatever
`LogRecord.getMessage()` produces with no scrubbing step. Nine call sites
across five modules pass a raw exception object as a `%s` argument, which
calls `str(exc)` with no filtering before it reaches the logger:

`feedback_store.py:521`, `run_history_store.py:416`, `feedback_audit.py:685`,
`feedback_audit.py:691`, `feedback_audit.py:995`, `store_reconnect.py:325`,
`store_reconnect.py:366`, `query_runs.py:2358`, `query_runs.py:2492`.

`providers.py`'s HTTP-error paths are careful by convention — they log
structured fields (status code, model id, error class name) and deliberately
never pass the exception object itself, because a response header can carry
key material verbatim. The 9 sites above do not follow that convention.

**Verified LATENT, not LIVE** (2026-08-13/14): the exception types actually
caught at these 9 sites are `sqlite3.Error`, `TimeoutError`, JSON parse
errors, and one `HTTPError`/`URLError` pair from an outbound eval-judge call.
None of these currently stringify to include a credential. So there is no
confirmed active leak today — only the absence of anything that would catch
one if a future call site reused one of these `except` blocks for something
that does carry a secret.

`tests/security/test_release_security_redaction.py` does not cover this: it
only asserts secrets don't leak into HTTP responses or in-memory event
recorders, never into logger output. This gap was invisible to CI before
this change.

Two fixes were on the table:

1. A global scrubbing step in `JsonFormatter` (or a `logging.Filter`) that
   redacts secret-shaped substrings from every record before it is emitted.
2. Audit and fix each of the 9 call sites to log structured, non-secret
   fields only, matching the `providers.py` convention.

## Decision

**Build (1): a global redaction step, applied to the fully-rendered JSON
line inside `JsonFormatter.format()`** (`_redact_secrets`,
`src/product_app/logging_config.py`). It runs a fixed set of regex patterns
— `Bearer <token>`, labeled assignments (`api_key=...`, `password=...`,
`authorization: ...`), and bare key-shaped tokens (`sk-...`, `AKIA...`) —
against the final JSON string, so it catches a secret wherever it lands:
`message`, the flattened `exception` traceback, or any `extra={...}` value.

This does NOT replace fixing the 9 call sites to log structured fields —
that is still the correct long-term shape, matching `providers.py`. It is
deliberately not done in this PR (see Rejected alternatives) because it is a
separate, larger, and lower-urgency concern once the filter exists.

## Rationale

- **The filter protects call sites that do not exist yet.** Approach (2)
  only protects the 9 sites named today. The next contributor who writes
  `logger.warning("upstream failed: %s", exc)` in a tenth location gets no
  protection from an audit of the current nine. A formatter-level filter
  protects every record built through `JsonFormatter`, present and future,
  with zero additional call-site discipline required.
- **Defense in depth over convention-following.** `providers.py`'s
  discipline (never pass the exception, log structured fields) is exactly
  the discipline that was NOT followed at the 9 sites — proving that
  convention alone is not durable. A mechanical backstop does not depend on
  every future author remembering the rule.
- **Lower blast radius per line of change.** Editing 9 call sites across 5
  modules to reshape their exception handling is a larger diff, touches more
  files, and carries more risk of behaviour change (e.g. losing detail an
  operator relied on) than one contained addition to one already-isolated
  module (`logging_config.py`, which nothing else in `src/` imports from
  except at logger-setup time).
- **Applied to the final string, not to individual fields.** An earlier
  version of the labeled-assignment pattern matched an optional trailing
  quote character and, on a message ending exactly at the JSON field
  boundary, consumed the JSON payload's own closing `"` — corrupting the
  output into invalid JSON. Fixed by dropping the quote-consuming group;
  the pattern now stops at the first non-token character, which is always
  true of the JSON delimiter. Recorded here because it is exactly the kind
  of subtle failure a global string-substitution filter is prone to, and
  future edits to `_REDACTION_PATTERNS` must re-run
  `tests/unit/test_logging_config_redaction.py` (which parses the formatter
  output as JSON, so a broken-delimiter regression fails loudly) before
  shipping.

## Consequences

- Every current and future call site logging through the root logger's
  `JsonFormatter` gets secret-shaped substrings scrubbed automatically. No
  call-site change is required to get this protection.
  **Correction (2026-08-14, ADR-0041):** this was true for the stdout sink
  only. Sentry's `LoggingIntegration` reads the log record directly — it
  never goes through `JsonFormatter` — so a secret logged at any of the 9
  named call sites reached a Sentry breadcrumb unredacted whenever
  `SENTRY_DSN` was configured. ADR-0041 adds a second redaction stage at
  record-creation time (`logging.setLogRecordFactory`) that closes this for
  breadcrumbs and events; see that ADR for the measured reproduction and
  what remains an open gap (`exc_info`-based tracebacks).
- The regex set is necessarily a **shape** match (`Bearer ...`, `sk-...`,
  `key=...`), not a value match against a known-secret list — it cannot
  catch a credential whose shape does not resemble any pattern here (e.g. a
  short numeric PIN, or a key format not yet seen in this codebase). This is
  the same class of limitation as any regex-based scrubber; the mitigation
  is defense in depth (the filter is a backstop, not the only control) and
  extending `_REDACTION_PATTERNS` as new secret shapes appear in this repo.
- Log messages that legitimately contain a `Bearer`-prefixed or
  key-shaped-looking string that is NOT a secret (unlikely in this
  codebase's domain — query text, run ids, cost figures) would also be
  redacted. Accepted: false positives on a log line are far cheaper than a
  false negative on a credential.
- The 9 call sites themselves are UNCHANGED by this PR — they still pass
  the raw exception. That is a known, accepted gap in this decision: the
  filter is the safety net, not a substitute for the `providers.py`-style
  structured-logging convention. A follow-up to bring the 9 sites in line
  with that convention remains open work, tracked separately from this ADR.

## Rejected alternatives

- **Fix only the 9 call sites (approach 2).** Rejected as the sole fix:
  protects only the current, named population and leaves every future
  call site unguarded. Not rejected as *complementary* work — see
  Consequences.
- **A `logging.Filter` attached per-handler instead of a formatter
  wrapper.** Equivalent in effect (both run before the record reaches
  output) but a `Filter` operates on the `LogRecord` object before
  `getMessage()`/`formatException()` render it to text, which is a worse
  fit here: the traceback text and any `extra` values are not yet strings
  at that point, so the filter would have to duplicate the formatter's own
  rendering logic to scrub them. Scrubbing the fully-rendered JSON string
  inside `JsonFormatter.format()` scrubs exactly what an aggregator would
  see, in one place, after all interpolation is done.
- **Field-by-field redaction (scrub `payload["message"]` and
  `payload["exception"]` separately, before `json.dumps`).** Considered and
  rejected: it would miss whatever lands in `extra={...}` (OD-3's
  `request_id`, a future call site's custom field) unless every such field
  is enumerated too. Scrubbing the final joined string covers all of them
  uniformly with one pass.

## Related

- Issue #313.
- `tests/unit/test_logging_config_redaction.py` — positive controls (Bearer
  token, `sk-...` key, key=value assignment, in both a plain message and a
  real logged exception) and negative controls (an ordinary message and a
  real non-secret exception message survive untouched).
- `tests/security/test_release_security_redaction.py` — the pre-existing
  secret-leak gate this PR does not touch; it covers HTTP responses and
  in-memory event recorders, a different surface from logger output.
- `src/product_app/main.py`'s `_scrub_user_text` — a related but distinct
  redaction step, field-name-keyed, that strips user PROSE (query text,
  answers) from Sentry events. Not a secret-shaped-substring scrubber and
  not reused here; different threat (accidental PII/prose leak to a
  third-party SaaS) from this ADR's (credential leak to stdout/the
  telemetry sink).
