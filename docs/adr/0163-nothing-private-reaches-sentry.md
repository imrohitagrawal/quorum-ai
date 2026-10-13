# ADR-0163: Nothing private reaches Sentry

## Status

Accepted — 2026-10-13. The scope is the owner's: W56 widened to "nothing private reaches
Sentry" (CHG-042 (a)), and "drop the address, keep the id" for the ceiling alert, for signed-in
and anonymous visitors alike (CHG-043). The design below (a header list to keep, a key walk over
the whole event, one options function) is the session's.

## Context

Four private values can leave the process inside a Sentry payload: the visitor's address, the
anti-forgery token, the account header, and a key inside an error message. The evidence is in
`docs/analysis/2026-10-13-w56-sentry-privacy-failure-modes.md` (cited as "failure mode N") and
findings S1 and S2 of `docs/analysis/2026-10-13-security-review.md`. Those probes ran on
`7ac9a79` with sentry-sdk 2.63.0; they were not re-run here. In short:

- **Request headers reach Sentry on every event kind.** Transactions, error events, and events
  from worker threads that inherit the request's scope all carried `fly-client-ip`,
  `x-csrf-token`, `x-csrf` and `x-account-id` (failure modes 1, 2 and 4). The SDK's own header
  filter knows only seven names, none of ours, and its `EventScrubber` matches exact key names,
  none of ours either (failure mode 1).
- **The ceiling alert carried the address twice**: once as `extra.client_ip`, and once as the
  `fly-client-ip` header, beside `account_id` (failure modes 2 and 3).
- **A key in an exception message reached Sentry** in `exception.values[].value`, the chained
  cause included, while the JSON log line for the same traceback printed `[REDACTED]`
  (failure mode 8). The log redaction (ADR-0041) never touched Sentry's exception values.

This record changes three earlier statements without editing their bodies:

- **ADR-0023's title**, "Sentry payloads are scrubbed on every path", was true of the user's
  question and the sign-in callback's query only. Of the request header values, the SDK's own
  filter already removed seven (`cookie`, `authorization`, `x-forwarded-for` and four more; see
  Measurements); ours (`fly-client-ip`, `x-csrf-token`, `x-csrf`, `x-account-id`) went through.
  Key-shaped text was not scrubbed in exception values, `message`, `extra`, `tags`, `contexts`
  or spans until this change. (Key-shaped text in log messages was already redacted by
  ADR-0041's record factory before Sentry made breadcrumbs of them.)
- **ADR-0144 decision 5** says the ceiling alert "now carries the network key beside" the
  visitor's address, "so Sentry can pair the two". After this change the alert carries the key
  and no address.
- **ADR-0132, lines 108-110**, say the alert "reads `request.client.host`" and "was designed to
  carry the visitor's" address. It no longer reads or sends it.

## Decision

1. **One options function.** `main._sentry_options()` returns every keyword production passes to
   `sentry_sdk.init` except the DSN, and production calls exactly
   `sentry_sdk.init(dsn=SENTRY_DSN, **_sentry_options())`. The tests initialise Sentry with the
   same function, and a test pins that the real call passes nothing else. It also pins
   `send_default_pii=False` (on, it would send cookies, `REMOTE_ADDR` and `user`; failure mode 11).
   Three channels skip both hooks (failure mode 12), and each is switched off in the options:
   metrics with `enable_metrics=False` (sentry-sdk 2.63.0 defaults it to on; review round 1
   measured a key in a metric attribute reaching the transport as a `trace_metric` item), log
   forwarding with `enable_logs=False` (review round 2: 2.63.0 also turns it on through
   `_experiments["enable_logs"]`, and a mutation adding that left every earlier test green), and
   span streaming by passing no `_experiments["trace_lifecycle"]`.
2. **Header values are kept only for a list of eight names**, matched on the lower-cased name:
   `accept`, `accept-encoding`, `accept-language`, `connection`, `content-length`,
   `content-type`, `host`, `user-agent`. Every other value becomes `[REDACTED]`; a `headers`
   value that is not a dict is replaced whole. The list is `_SENTRY_HEADER_ALLOWLIST` in
   `main.py`.
3. **Every string in the event goes through `logging_config._redact_secrets`**, the same
   patterns the JSON log uses. The walk builds a copy, goes at most 32 containers deep, and past
   that replaces the container with `[REDACTED]` rather than raising (the SDK drops an event
   whose hook raises; failure mode 16). It covers exception values and their causes, `message`,
   `logentry`, `extra`, `tags`, `contexts`, breadcrumbs and spans without naming each one.
4. **The trace's dynamic sampling context is dropped.** The SDK copies a visitor's incoming
   `baggage` header into `contexts.trace.dynamic_sampling_context`; after both hooks have run,
   `sentry_sdk/client.py` (2.63.0, lines 1114-1123) pops that key and sends it as the envelope
   header `trace`, which no hook sees. Review round 1 measured `sentry-user_segment=<address>`
   reaching that header. The scrubber removes the key, so no envelope carries a `trace` header.
5. **All three steps run inside `_scrub_user_text`**, the function both hooks already share
   (ADR-0023 decision 1), so neither the error path nor the transaction path can be left out
   (failure mode 17).
6. **The ceiling alert drops the address and keeps the spend key** (CHG-043).
   `CostEstimationService.record_guardrail_event` and `try_record_run_charge` no longer take a
   `client_ip` parameter, the `client_ip` extra is gone, and the plumbing that carried
   `request.client.host` from `create_query_run` down to them is removed. `account_id`,
   `estimated_cost_usd`, the ceiling, and the global spend when a store is configured, stay in
   the alert with their values. The `query_run_id` key also arrives, but its value is
   `[REDACTED]`: an older rule in `_scrub_user_text` blanks every extra whose name contains
   "query" (it predates W56 and is left alone; see Consequences). The session limits' own use
   of the address (`auth.py`, `main.py`) is untouched.
7. **The session-limit error carries no address** (review round 2). `SessionMintCapExceeded`'s
   message was the visitor's address, so a failure raised while `/ui` handled a refused mint
   sent the address to Sentry as the chained exception's `value`, past the header scrub. Its
   message is now fixed (`new-session limit reached for this network`), and the address it is
   given is not kept, since nothing read it. A grep of `src/` for other exceptions built from an
   address-like value found one more, `source_fetcher.py`'s resolve timeout, which names the
   host of a cited web page, not the visitor; it is left as is.

## Measurements

| What | Result | Command or source |
|---|---|---|
| Header names the SDK filters on its own | 7: authorization, cookie, proxy-authorization, set-cookie, x-api-key, x-forwarded-for, x-real-ip | `.venv/bin/python -c "from sentry_sdk.integrations._wsgi_common import SENSITIVE_HEADERS as S; print(sorted(set(S)))"` |
| Our six names on the SDK `EventScrubber` list | 0 of 6 (`client_ip`, `fly-client-ip`, `x-csrf-token`, `x-csrf`, `x-account-id`, `forwarded`) | `.venv/bin/python -c "from sentry_sdk.scrubber import DEFAULT_DENYLIST as D; ..."` |
| The W56 tests against the tree before this change (`18299a0`) | `6 failed, 22 passed, 10 errors` (the 10 errors are the missing `_sentry_options`) | `git archive 18299a0` into a scratch folder, then `pytest tests/security/test_w56_nothing_private_reaches_sentry.py tests/unit/test_global_spend_ceiling.py` there |
| The same two files after this change | `38 passed` | `.venv/bin/python -m pytest <the two files> -q -p no:cacheprovider --no-cov` |
| This change with the header scrub and the key walk both removed, in a scratch copy | `12 failed, 9 passed` in the W56 file: every leak test goes red, the options and signature tests stay green | same scratch-copy method, the two calls deleted from `_scrub_user_text` |
| Nesting depth of a serialised event | 12 for an error event with a chained cause and frame locals ON; 4 for a transaction | a local probe that initialises Sentry with a capture transport and measures the depth inside `before_send` and `before_send_transaction` |
| Incoming `baggage` reaches the envelope header `trace` (round 1) | before the fix: `sentry-user_segment=203.0.113.99` in the serialised envelope; after: absent, and the transaction still continues the visitor's trace id | `tests/security/test_w56_regressions.py::test_incoming_baggage_does_not_reach_the_envelope_header`, run before and after |
| Metrics skip both hooks (round 1) | before `enable_metrics=False`: items `['event', 'trace_metric']` and the key in the serialised envelope; after: no `trace_metric` item and no key | `tests/security/test_w56_regressions.py::test_a_metric_produces_no_envelope_item`, and a probe with `enable_metrics=True` |
| A visitor-sent `sentry-trace` header forces sampling | 50 of 50 requests sent a transaction with it, 5 of 50 without, at `traces_sample_rate=0.1` | inherited from failure mode 10; not re-measured here |

## Rejected alternatives

- **A list of headers to drop.** None was built. The probe measured `X-CSRF` (the second token
  header `auth.py` accepts) and `Forwarded: for=<address>` leaking, and a list to drop holding
  only the three named headers (`Fly-Client-IP`, `X-CSRF-Token`, `X-Account-Id`) would have
  missed both (failure modes 5 and 6). Every new header would be sent until someone remembered to add it. The cost of a list to
  keep is the opposite mistake: a header an operator wants is redacted until someone adds it.
  That mistake is visible in Sentry; the other one is not.
- **Dropping both the spend key and the address from the ceiling alert.** The key is what an
  operator acts on when the ceiling trips, and the owner chose to keep it (CHG-043). Without the
  address and without the server secret, the key says nothing about who sent the request
  (ADR-0144 decision 5).
- **Stripping headers in a middleware.** Sentry wraps the app outside every middleware and reads
  the raw request scope, and `VisitorAddressMiddleware` needs `Fly-Client-IP` to work (failure
  mode 13).
- **Scrubbing only in `before_send`.** It is never called for transactions, where S1 was
  measured (failure mode 17).
- **Relying on Sentry's server-side scrubbing.** By then the data has already left the process,
  and what the organisation has set there is UNVERIFIED (failure mode 22).

## Consequences

- An operator reading a Sentry event sees eight header values and `[REDACTED]` for the rest. To
  see another header, add its name to `_SENTRY_HEADER_ALLOWLIST` on purpose, with a reason.
- A key-shaped string in any field arrives as `[REDACTED]`; the text around it still arrives.
- The ceiling alert names the spend key, not the visitor. Matching it to a network needs the
  server secret, as before.
- `docs/48-data-retention.md` rows for the signed-in and anonymous spend keys say the alert
  carries the key without the address. How long the cost ledger keeps the anonymous network's
  key: decided: 48 hours (CHG-033 (c)); not yet built (board row W55). How long the ledger keeps a
  signed-in account's key, and how long Sentry may keep either key, has not yet been asked.
  CHG-043 decides only what the alert carries.
- `tests/security/test_w56_nothing_private_reaches_sentry.py` holds the end-to-end checks:
  capture through a real transport, sweep the whole payload, and a partner beside every
  "absent" check. `tests/security/test_w56_regressions.py` holds the review round 1 and round 2
  checks, with a transport that keeps whole envelopes, headers included.
- **The `query_run_id` value arrives blanked (advisory).** The rule in `_scrub_user_text` that
  predates W56 replaces every extra whose name contains "query" or "prompt" with `[REDACTED]`,
  so the alert's `query_run_id` key arrives with no usable value. W56 leaves that rule alone (it
  guards the user's question and is out of scope here).
- With no `trace` envelope header, Sentry receives no dynamic sampling context from this app.
  Sampling is decided in the process (`traces_sample_rate`); whether the Sentry organisation
  relies on server-side dynamic sampling is UNVERIFIED (its settings were not read).
- **Harmless text can be over-scrubbed.** The walk applies the log patterns to every string, so a
  labelled-credential shape that holds no credential loses its tail:
  `authorization: missing header` arrives as `[REDACTED] header` (run through
  `_redact_secrets`). No current `src/` message has that shape as far as a one-line grep can
  tell: over the 36 `.py` files in `src/product_app` other than `logging_config.py`, lines with
  `raise`, a logger call, `capture_*`, `set_extra`, `set_tag` or `detail=` that also hold a
  credential label followed by `:` or `=` numbered 0 (the same grep counts 1 on
  `raise ValueError('authorization: missing header')`). A message built across several lines
  is not covered by that grep, so beyond it this is UNVERIFIED.

## What it cannot see

- **Gaps in the key patterns.** `_redact_secrets` misses a key glued to a word, a
  percent-encoded key and a key without its prefix (failure mode 20). This change inherits those
  gaps; W76 owns them.
- **Breadcrumb text and the query string.** A log message holding an address, or an address or
  key in a URL query, is redacted only if it matches a key pattern (failure modes 7 and 9; W76).
  No route is known to take either in its query today (UNVERIFIED across every route).
- **Dict keys.** The walk redacts values, not keys, so a key-shaped dict key (a tag name, an
  `extra` name) is sent as is. Redacting keys could merge two keys into one `[REDACTED]`.
- **Sampling (advisory).** A visitor can force every one of their requests into a transaction
  with a `sentry-trace` header (failure mode 10). Review round 2 measured it again on this
  branch: `forced=40/40 plain=2/40 rate=0.1` (reported by the reviewer, not re-run by the
  session). It costs Sentry quota only; the scrub applies to every transaction, so no data
  leaves through it. Nothing here limits it.
- **Source lines in stack frames (advisory).** Sentry sends a few source lines around each stack
  frame (`context_line`, `pre_context`, `post_context`), and the key walk applies the log
  patterns to them too. Over `src/`, 9 lines that do not start with `#` change when run through
  `_redact_secrets` (3 code lines, for example `readiness.py:300`
  `api_key = settings.openrouter_api_key`, and 6 docstring lines), so a frame on one of them
  arrives with that line partly `[REDACTED]`. Counted by running `_redact_secrets` over every
  line of every `.py` file under `src/` and skipping lines whose first character is `#`.
- **Outgoing trace headers (advisory, outside W56).** `trace_propagation_targets` is not set, and
  sentry-sdk 2.63.0 defaults it to `['.*']` (`consts.py`, `MATCH_ALL`), so outgoing requests to
  OpenRouter and Google carry `sentry-trace` and `baggage` headers. They go to those third
  parties, not to Sentry, so W56 does not cover them (reported by review round 2).
- **The board row's evidence.** W56's needle in `docs/65-open-work.md` pins only the alert fix
  (`scope.set_extra("client_ip", client_ip)` gone from `costs.py`). The header scrub and the key
  walk are pinned by the tests named under Consequences, not by the board (advisory).
- **Sentry's own settings.** Server-side scrubbing and retention in the Sentry organisation are
  UNVERIFIED.
- **A future channel.** Three channels skip both hooks: span streaming, log forwarding and
  metrics. Turning one on adds a path through `before_send_span`, `before_send_log` or
  `before_send_metric`, which this scrubber does not run in. All three are off. What the tests
  pin: `enable_metrics` and `enable_logs` are `False` in `_sentry_options()`; its `_experiments`
  (production sets none today) holds no `enable_logs`, `enable_metrics` or `trace_lifecycle`; and, with
  the real options, a metric sends no `trace_metric` item and a `logging.warning` sends no `log`
  item. No test sends a span with streaming on. Turning a channel on must add the scrub to it. A
  channel a later SDK version adds, or a new switch for an existing one, is not covered by any
  test here.
- **`docs/48-data-retention.md` has no gate.** A false sentence re-added there, or a citation
  of a CHG row that does not exist, passes every check. This predates W56 and is advisory.
