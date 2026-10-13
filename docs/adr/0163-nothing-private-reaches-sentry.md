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
  question only. Headers and key-shaped text were not scrubbed on any path until this change.
- **ADR-0144 decision 5** says the ceiling alert "now carries the network key beside" the
  visitor's address, "so Sentry can pair the two". After this change the alert carries the key
  and no address.
- **ADR-0132, line 108**, says the alert "reads `request.client.host`" and "was designed to
  carry the visitor's" address. It no longer reads or sends it.

## Decision

1. **One options function.** `main._sentry_options()` returns every keyword production passes to
   `sentry_sdk.init` except the DSN, and production calls exactly
   `sentry_sdk.init(dsn=SENTRY_DSN, **_sentry_options())`. The tests initialise Sentry with the
   same function, and a test pins that the real call passes nothing else. It also pins
   `send_default_pii=False` (on, it would send cookies, `REMOTE_ADDR` and `user`; failure mode 11)
   and that log forwarding and span streaming, two channels outside both hooks, stay off
   (failure mode 12).
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
4. **Both steps run inside `_scrub_user_text`**, the function both hooks already share
   (ADR-0023 decision 1), so neither the error path nor the transaction path can be left out
   (failure mode 17).
5. **The ceiling alert drops the address and keeps the spend key** (CHG-043).
   `CostEstimationService.record_guardrail_event` and `try_record_run_charge` no longer take a
   `client_ip` parameter, the `client_ip` extra is gone, and the plumbing that carried
   `request.client.host` from `create_query_run` down to them is removed. `account_id`,
   `estimated_cost_usd`, `query_run_id`, the ceiling, and the global spend when a store is
   configured, stay in the alert. The
   session limits' own use of the address (`auth.py`, `main.py`) is untouched.

## Measurements

| What | Result | Command or source |
|---|---|---|
| Header names the SDK filters on its own | 7: authorization, cookie, proxy-authorization, set-cookie, x-api-key, x-forwarded-for, x-real-ip | `.venv/bin/python -c "from sentry_sdk.integrations._wsgi_common import SENSITIVE_HEADERS as S; print(sorted(set(S)))"` |
| Our six names on the SDK `EventScrubber` list | 0 of 6 (`client_ip`, `fly-client-ip`, `x-csrf-token`, `x-csrf`, `x-account-id`, `forwarded`) | `.venv/bin/python -c "from sentry_sdk.scrubber import DEFAULT_DENYLIST as D; ..."` |
| The W56 tests against the tree before this change (`18299a0`) | `6 failed, 22 passed, 10 errors` (the 10 errors are the missing `_sentry_options`) | `git archive 18299a0` into a scratch folder, then `pytest tests/security/test_w56_nothing_private_reaches_sentry.py tests/unit/test_global_spend_ceiling.py` there |
| The same two files after this change | `38 passed` | `.venv/bin/python -m pytest <the two files> -q -p no:cacheprovider --no-cov` |
| This change with the header scrub and the key walk both removed, in a scratch copy | `12 failed, 9 passed` in the W56 file: every leak test goes red, the options and signature tests stay green | same scratch-copy method, the two calls deleted from `_scrub_user_text` |
| Nesting depth of a serialised event | 12 for an error event with a chained cause and frame locals ON; 4 for a transaction | a local probe that initialises Sentry with a capture transport and measures the depth inside `before_send` and `before_send_transaction` |
| A visitor-sent `sentry-trace` header forces sampling | 50 of 50 requests sent a transaction with it, 5 of 50 without, at `traces_sample_rate=0.1` | inherited from failure mode 10; not re-measured here |

## Rejected alternatives

- **A list of headers to drop.** It had already missed two that leaked when measured: `X-CSRF`,
  the second token header `auth.py` accepts, and `Forwarded: for=<address>` (failure modes 5 and
  6). Every new header would be sent until someone remembered to add it. The cost of a list to
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
  carries the key without the address. How long the cost ledger keeps the key is still open
  (W55).
- `tests/security/test_w56_nothing_private_reaches_sentry.py` holds the end-to-end checks:
  capture through a real transport, sweep the whole payload, and a partner beside every
  "absent" check.

## What it cannot see

- **Gaps in the key patterns.** `_redact_secrets` misses a key glued to a word, a
  percent-encoded key and a key without its prefix (failure mode 20). This change inherits those
  gaps; W76 owns them.
- **Breadcrumb text and the query string.** A log message holding an address, or an address or
  key in a URL query, is redacted only if it matches a key pattern (failure modes 7 and 9; W76).
  No route is known to take either in its query today (UNVERIFIED across every route).
- **Dict keys.** The walk redacts values, not keys, so a key-shaped dict key (a tag name, an
  `extra` name) is sent as is. Redacting keys could merge two keys into one `[REDACTED]`.
- **Sampling.** A visitor can force every one of their requests into a transaction with a
  `sentry-trace` header (failure mode 10). Nothing here limits that; it is advisory, and the
  scrub applies to every transaction anyway.
- **Sentry's own settings.** Server-side scrubbing and retention in the Sentry organisation are
  UNVERIFIED.
- **A future channel.** Turning on span streaming or log forwarding adds a path through
  `before_send_span` or `before_send_log`, which this scrubber does not run in. A test pins both
  off; turning one on must add the scrub to it.
