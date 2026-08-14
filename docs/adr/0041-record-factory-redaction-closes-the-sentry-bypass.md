# ADR-0041: Redact at the log-record factory, not only in `JsonFormatter`

## Status

Accepted — 2026-08-14 (issue #313, PR #315 review follow-up)

## Context

ADR-0040 added `_redact_secrets`, applied to the fully-rendered JSON string
inside `JsonFormatter.format()`. That protects the stdout sink. It does not
protect Sentry.

`main.py` calls `sentry_sdk.init(...)` with no `integrations=` override, so
`LoggingIntegration` is active with its defaults. That integration works by
patching `logging.Logger.callHandlers` — see the existing explanation in
`telemetry_sink.py`'s `_configure_token_logger` docstring, written for a
different logger on the same code path. `callHandlers` runs on the
ORIGINATING logger and dispatches directly to Sentry's patched hook; it never
touches `JsonFormatter`, which is only wired to a `StreamHandler` sitting on
the ROOT logger. So a secret logged via any of the 9 raw-exception call sites
named in ADR-0040 (`logger.warning("...: %s", exc)`) reached a Sentry
breadcrumb in full plaintext whenever `SENTRY_DSN` is configured — production.

Measured 2026-08-14 with a real `sentry_sdk` 2.63.0 client and an in-memory
`before_breadcrumb` capture hook (the same reproduction method as
`test_the_token_record_never_becomes_a_sentry_breadcrumb`): logging
`RuntimeError("401 Unauthorized: Bearer sk-or-v1-...SECRET")` through
`product_app.feedback_audit`'s logger produced a breadcrumb whose `message`
field carried the token unredacted. `main.py`'s `before_send` /
`before_send_transaction` hooks (`_redact_sentry_event`,
`_scrub_user_text`) do not help either: they scrub only named user-prose
fields from `request.data`, `extra`, and stack-frame `vars` — they never
touch `event['breadcrumbs']`, and carry no credential-shaped regex.

This makes ADR-0040's stated consequence — "every current and future call
site logging through the root logger's `JsonFormatter` gets secret-shaped
substrings scrubbed automatically" — **false for the Sentry egress path**,
which is the higher-consequence sink (third-party SaaS) of the two.

## Decision

**Add a second redaction stage, at record-creation time, via
`logging.setLogRecordFactory`** (`install_redaction_record_factory`,
`src/product_app/logging_config.py`), installed from `setup_json_logging` —
the same entry point `main.py` already calls before `sentry_sdk.init`.

The factory wraps `record.getMessage()` (the `msg %% args` interpolated
text) through the *same* `_redact_secrets` patterns ADR-0040 already
maintains, and — only if a substitution actually happened — replaces
`record.msg` with the redacted text and clears `record.args`. Because a
`setLogRecordFactory` hook runs inside `Logger.makeRecord()`, before
`Logger.handle()` calls either `filter()` or `callHandlers()`, every later
consumer of the record — the root logger's `JsonFormatter`, Sentry's
breadcrumb/event handlers, pytest's `caplog`, any future handler — sees the
same already-redacted text. This is the same mechanism
`request_id.install_request_id_record_factory` already uses for a different
reason (visibility to every handler, not just one), so it is not a new
pattern in this codebase.

`_redact_secrets` and `_REDACTION_PATTERNS` are unchanged and shared between
both stages — the record-factory stage does not duplicate or diverge from
ADR-0040's pattern set.

## Rationale

- **A `logging.Filter` does not close this gap either.** A filter added to
  the ROOT logger's `Logger.filters` only runs inside that logger's own
  `handle()` call — records logged through a *child* logger
  (`product_app.feedback_audit`, etc.) never reach it, because
  `Logger.callHandlers` walks ancestor **handlers**, not ancestor
  **loggers'** `filter()` methods. A filter would have to be attached to
  every current and future logger individually to get the same coverage a
  record factory gets for free. This narrows ADR-0040's own "Rejected
  alternatives" entry for `logging.Filter`, which reasoned about a
  per-handler filter and was correct about that case, but did not consider
  (because the Sentry bypass was not yet known) that a filter is the wrong
  tool for this problem regardless of where it is attached.
- **Redacting `record.msg`/`record.args` in place, not a copy, is what makes
  every consumer agree.** An alternative — computing a redacted string only
  for `JsonFormatter`'s use and leaving the record itself untouched — would
  leave the Sentry path exactly as unprotected as before, since Sentry reads
  the record directly.
- **Scope is deliberately the same as ADR-0040's: `getMessage()`, not
  `exc_info`.** None of the 9 named call sites pass `exc_info=True`; all of
  them interpolate `str(exc)` via `%s`. A future call site that does use
  `exc_info=True` would still leak an unredacted traceback into Sentry's
  event capture (which reads the exception object directly, not through
  `formatException`) — this is a known, accepted gap, not fixed here, same
  posture as ADR-0040's own "regex-shape" limitation.

## Consequences

- The claim in ADR-0040 that "every current and future call site... gets
  secret-shaped substrings scrubbed automatically" is now true for the
  Sentry breadcrumb/event path as well as stdout — corrected here rather
  than by editing ADR-0040's already-accepted text.
- Two redaction call sites now exist for the same pattern set
  (`JsonFormatter.format`'s final-string scrub, and the record factory's
  `getMessage()` scrub). This is deliberate redundancy, not drift: the
  stdout path keeps its own scrub because it also covers the exception
  traceback text (`formatException` output), which the record factory does
  not touch.
- `record.args` is cleared to `None` whenever a substitution happens. Any
  code that reads `record.args` directly (not `record.getMessage()`) after
  a redacted record has already been constructed would see `None` instead
  of the original arguments. No call site in this repo does that today
  (verified: `grep -rn '\.args\b' --include='*.py' src/product_app | grep -i
  record` returns exactly one hit — this module's own assignment).
- `record.exc_info`-based traceback capture (not used by any of the 9
  ADR-0040 call sites today) remains unprotected on the Sentry path. Tracked
  as the same open follow-up ADR-0040 already recorded for bringing those
  call sites to the `providers.py` structured-logging convention.

## Rejected alternatives

- **Add every current logger to `ignore_logger()`,** the mechanism
  `telemetry_sink.py` already uses for the token stream. Rejected: that
  logger's records are meant to stay OUT of Sentry entirely (a different,
  narrower goal). These 9 call sites' records are ordinary application
  warnings/errors that operators want in Sentry — just with secrets
  scrubbed first, not suppressed.
- **A `logging.Filter` on every individual logger.** Rejected per Rationale
  above: does not compose with future call sites the way a record factory
  does, and would need per-logger registration that nothing enforces.
- **Scrub inside `_redact_sentry_event`/`_redact_sentry_transaction`
  (`main.py`).** Rejected: those hooks run in `before_send`/
  `before_send_transaction`, which fire for events and transactions but
  **not** for breadcrumbs at all (breadcrumbs are attached to whatever event
  eventually fires, and the measured leak was a breadcrumb's `message`
  field). Fixing this at the Sentry-hook layer would need a third hook
  (`before_breadcrumb`) in addition to the two that already exist, adding a
  third place to keep in sync with `_REDACTION_PATTERNS`, versus the
  record-factory fix needing none.

## Related

- Issue #313.
- ADR-0040 — the original redaction decision this ADR extends; its
  `_REDACTION_PATTERNS` are reused unchanged here.
- `tests/unit/test_logging_config_sentry_redaction.py` — real `sentry_sdk`
  client, `before_breadcrumb` capture, positive and negative controls, plus
  a structural test that `setup_json_logging` actually wires the factory
  (not only that the factory works when called directly).
- `telemetry_sink.py`'s `_configure_token_logger` docstring — the
  pre-existing explanation of the same `callHandlers` patching mechanism,
  for a logger this ADR's fix deliberately does NOT apply to (see Rejected
  alternatives).
- `request_id.py`'s `install_request_id_record_factory` — the pre-existing
  precedent for using `setLogRecordFactory` to reach every handler
  uniformly.
