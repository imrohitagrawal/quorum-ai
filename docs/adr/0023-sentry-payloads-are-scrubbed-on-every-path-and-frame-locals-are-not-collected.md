# ADR-0023: Sentry payloads are scrubbed on every path, and frame locals are not collected

## Status

Accepted — 2026-08-07

## Context

`main.py` initialised Sentry with `send_default_pii=False` and a `before_send`
hook whose docstring said it *"ensures that if a future change accidentally
includes request bodies, query text is still redacted."*

That claim was tested by execution on 2026-08-07 — the DSN was pointed at a
loopback HTTP collector and the suite was run with credentials un-blanked, so
the collector received exactly what the real Sentry project would have. **The
user's question left the process on two independent paths.**

**1. `before_send` is never called for transaction items.** Counted on one run,
by envelope item type:

| Envelope item | `request.data` | Count |
|---|---|---|
| `event` | `[REDACTED]` | 8 of 8 |
| `transaction` | **RAW** | 9 of 9 |

Transactions require a separate `before_send_transaction` hook, which was not
set. With `traces_sample_rate=0.1` this was **~10% of production requests**
shipping the raw request body — `query_text` included — to Sentry.

**2. Stack-frame locals were never touched.** In error events the question
appeared under `exception.values[].stacktrace.frames[].vars`:

```
vars.payload      QueryRunCreateRequest(query_text='...')
vars.body_bytes   b'{"query_text":"...","model_slots":[...]}'
vars.query_run    QueryRun(query_text='...')
vars.kwargs.payload  / vars.values.payload   (the same content again)
```

`_redact_sentry_event` rewrote `request.data` and `extra[*query*]` only. Note
that the redaction *worked* on the keys it knew about — `request.data` really
was `[REDACTED]` on error events. The defect was **scope**, not correctness,
which is why it survived review: the code did exactly what it said, and what it
said was not enough.

Scale, measured on the same run: **287 envelopes** delivered by a full suite;
145 `event` + 35 `transaction` in a smaller slice, 141 of them `error` level,
because no explicit `integrations=` argument is passed and the SDK's default
`LoggingIntegration` promotes every `ERROR` log record to an event.

This was found while answering an operator's question about what to check in
Sentry after an unrelated credential incident — not by a gate, and not by
review. It had been live in production for as long as the DSN has been set.

## Decision

**Scrub on every outbound path, and stop collecting frame locals at the source.**

1. **`_scrub_user_text` is shared by both hooks.** `before_send` and
   `before_send_transaction` now delegate to one function, so a path cannot be
   protected in one direction and not the other. Every branch in it corresponds
   to a place the query was *observed* escaping; none is hypothetical.

2. **`include_local_variables=False`.** This is the guarantee; the scrubber is
   defence in depth. Pattern-matching frame locals means enumerating the ways
   user text can be reached, and the same session had already lost that game
   once — a ban on credential-bearing assertions listed `not` and `len()` and
   was defeated by `bool()`. Turning capture off removes the class rather than
   the instances.

3. **`_USER_TEXT_FIELDS` keys on FIELD names, not variable names.** The leak
   arrived under five different variable names (`payload`, `body_bytes`,
   `query_run`, `kwargs.payload`, `values.payload`) for one piece of content,
   and the next refactor would invent a sixth. The field names
   (`query_text`, `answer_text`, `final_synthesis`, `rationale`, `prompt`) are a
   bounded set, and a test pins every entry to a real occurrence in `src/` so a
   rename cannot silently shrink the redaction set.

Non-user diagnostic content is deliberately preserved and asserted: the frame's
`function`, the exception `type`, the request `url`, and locals that carry no
prose (e.g. `account_id`). A hook that returned `{}` would satisfy every
absence check and destroy error tracking, so the "both directions" test is not
optional.

## Rejected alternatives

**1. Set `send_default_pii=False` and trust it.** This is what existed. It was
already set, and the query still left the process. The flag governs *some*
categories the SDK considers PII; a request body and a frame local are not
among them.

**2. Scrub frame locals by variable name.** Rejected for the reason in
Decision 3 — it is an enumeration, and enumerations lose. Kept only as the
defence-in-depth layer *behind* `include_local_variables=False`, where being
incomplete is tolerable rather than load-bearing.

**3. Drop `traces_sample_rate` to 0 to kill the transaction path.** This would
have closed the measured leak, and it was rejected because it removes
performance monitoring to fix a redaction bug. The hook is the proportionate
fix; the sample rate is a product decision, not a privacy control.

**4. Disable `LoggingIntegration` so `ERROR` logs stop becoming events.** Out of
scope here, and arguably wrong — those events are the point of error tracking.
Noted because it is the reason the *volume* is high, and a future decision to
tune it should be made on cost, not on privacy.

## Consequences

- Sentry error reports lose local-variable detail. That is a real cost to
  debugging, accepted deliberately: user prose in a crash report is not
  recoverable once sent, and a stack trace without locals is still actionable.
- The two hooks share one implementation, so the next payload surface someone
  adds is protected on both paths or neither — a failure that is at least
  symmetrical and testable.
- **This says nothing about what is already stored in Sentry.** The fix stops
  future sends. Historical events, including any real user queries captured
  from production transactions, remain in the project until deleted there. That
  is an operator action and is called out in the pull request.
- The redaction set is pinned to the tree but **completeness is not provable
  offline**. A new prose field added to `src/` without being added to
  `_USER_TEXT_FIELDS` would go unredacted in the defence-in-depth layer, though
  `include_local_variables=False` still covers the frame-locals path.
