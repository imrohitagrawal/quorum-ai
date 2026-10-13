# W56 failure modes: how "nothing private reaches Sentry" can fail

Date: 2026-10-13. Role: failure modes, before any code. Tree: `7ac9a79`, sentry-sdk 2.63.0.

The four private values: the visitor's address, the anti-forgery token, the account header,
and a key inside an error message. The owner decided to drop `client_ip` for everyone and keep
`account_id` (the spend key) in the alert.

**How this was measured.** A pytest probe ran in a `git archive HEAD` copy, so the
outbound-socket guard in `tests/conftest.py` was on. The copy is deleted. It used production's
hooks and `send_default_pii=False`, with a capture transport and every request sampled. It sent
`Fly-Client-IP`, `X-CSRF-Token`, `X-CSRF`, `X-Account-Id`, `Forwarded`, `X-Real-IP`,
`X-Forwarded-For`, `Cookie` and `User-Agent` through six cases:

- A: `/health`, which sends a transaction.
- B: the real `record_guardrail_event(global_ceiling_reached=True, client_ip=...)` inside a sync route.
- C: the same call from a bare thread.
- D: an async route that raises with a key in the message.
- E: `logger.exception` with a chained cause.
- F: a thread started inside a request.

"Probe X" below means one of these cases.

## Where the values still escape after a fix that only edits one place

1. **Transaction headers.**
   - Where: `request.headers` on transactions.
   - Evidence (probe A): `fly-client-ip`, `x-csrf-token`, `x-csrf` and `x-account-id` all
     arrived. The SDK's own header filter covers only the following: `x-forwarded-for`,
     `x-real-ip`, `cookie`, `set-cookie`, `authorization`, `proxy-authorization` and
     `x-api-key` (`sentry_sdk/integrations/_wsgi_common.py:27-40`, `:212-228`). The built-in
     `EventScrubber` matches exact key names (`sentry_sdk/scrubber.py:15-61`, `:117`), and
     none of our names is on its list, `client_ip` included.
   - Test: capture a real transaction through a transport, then sweep the whole serialised
     payload for each value. Do not test a hand-built dict.

2. **The ceiling alert carries the address twice.**
   - Where: the `cost_guardrail_degraded_to_simulation` event.
   - Evidence (probe B): `extra.client_ip` AND `request.headers.fly-client-ip`, beside
     `account_id`. The real route `create_query_run` is a sync `def`
     (`src/product_app/query_runs.py:660-661`). It books the charge before `Thread.start()`
     (`:974-1008`), so the alert is sent with the request attached.
   - So deleting `costs.py:1489-1490` alone still pairs the spend key with the address in the
     same event. This also settles S1's UNVERIFIED line: error and message events carry the
     same headers (probes B, D and E).
   - Test: run the alert inside a request, then assert `account_id` is present and the address
     is absent from the whole event.

3. **Bare-thread alert.**
   - Where: the alert sent with no request attached.
   - Evidence (probe C): no headers, but `extra.client_ip` was still there. Fixing headers
     only leaves this; fixing the extra only leaves item 2.
   - Test: both cases, with and without a request.

4. **Worker threads inherit the request's headers.**
   - Evidence: `ThreadingIntegration(propagate_scope=True)` forks the request's scope into
     every new `Thread` (`sentry_sdk/integrations/threading.py:31`, `:78-92`). Probe F: an
     exception captured in a thread started inside a request carried the private headers.
     Re-measured in W56 review round 1, with the header scrub removed in place and the W56
     worker test run: the event carried the values of the four private headers
     (`fly-client-ip`, `x-csrf-token`, `x-csrf`, `x-account-id`) and of the unknown header,
     and the address (sent in both `fly-client-ip` and `forwarded`).
     Production's run worker is such a thread (`query_runs.py:1005`), so every provider or
     judge error sent after the response is affected.
   - Test: probe F's shape.

5. **A second token header, and header case.**
   - Evidence: `auth.py:1142` accepts `X-CSRF` as well as `X-CSRF-Token`. Probe A leaked both.
     The header names reach the hook in lowercase (`fly-client-ip`), so a case-sensitive match
     on `Fly-Client-IP` misses.
   - Test: send `X-CSRF`, and send mixed-case header names.

6. **Address headers the visitor sends.**
   - Evidence: `Forwarded: for=<ip>` leaked (probe A). Fly was measured keeping a client's own
     `X-Forwarded-For` (`auth.py:113-117`); whether it keeps a client's `Forwarded` is
     UNVERIFIED.
   - UNVERIFIED, not probed but the same mechanism: `True-Client-IP`, `X-Client-IP`,
     `CF-Connecting-IP`.
   - Test: send an unknown header holding an address, and assert it is dropped.

7. **The query string is kept with personal data off.**
   - Evidence: `_asgi_common.py:96`. Re-measured in W56 review round 1 on the fixed tree:
     `GET /health?addr=203.0.113.88&k=<key>` sent a transaction whose `request.query_string`
     was `addr=203.0.113.88&k=[REDACTED]`, so the address still arrives and the key is now
     redacted by W56's key walk. Today's scrubber clears the query only on the sign-in callback
     path (`main.py:160-166`).
   - No route is known to take a key or an address in its query today (UNVERIFIED across
     every route). The general case overlaps W76.

8. **Exception messages, including chained causes.**
   - Evidence (probe D): the key was in `exception.values[0].value`. Probe E: the key sat in
     `values[0]`, the CAUSE, while the outer exception's message was harmless. A fix that
     cleans only the last value misses it.
   - The JSON log line for the same traceback printed `wrapped [REDACTED]`. The log redaction
     (ADR-0041) does not reach Sentry's exception values.
   - Also scrub `message` (from `capture_message`) and `logentry.formatted` and
     `logentry.params`. Probe E put the address in both `logentry` fields.
   - A key in `logentry`: UNVERIFIED. The record factory did redact it in a breadcrumb
     message (probe D).

9. **Breadcrumbs (overlaps W76; do not widen W56).**
   - Evidence: logging breadcrumbs keep the message text; probe D sent
     `'visitor 203.0.113.88'`. Http breadcrumbs keep `http.query` raw, key included.
   - By grep, no log call in `src/` writes the address today. ADR-0132:106-107 records that
     the uvicorn access log shows Fly's proxy address, not the visitor's.
   - Test trap: `TestClient`'s own requests appear as `httplib` breadcrumbs in later events.
     A sweep for a value you put in a test URL goes red because of the test, not the app.

10. **Sampling is not a limit.**
    - Evidence: an incoming `sentry-trace: <trace>-<span>-1` header forces sampling
      (`sentry_sdk/tracing.py:1203-1211`; `strict_trace_continuation` defaults to off,
      `consts.py:1322`). Probe at `traces_sample_rate=0.1`: 5 of 50 plain requests sent a
      transaction; 50 of 50 with the header did.
    - "About 1 in 10" (the W56 row, `docs/65:153`) is a typical rate, not a ceiling. Any
      visitor can send every one of their requests.

11. **What the SDK does NOT send with personal data off.** The fix need not chase these.
    - `request.env.REMOTE_ADDR`: `_asgi_common.py:102-104`.
    - `request.cookies`: `starlette.py:706`, `:720`; `fastapi.py:121`.
    - `user`: `starlette.py:357`. Probe: `user` was None and no `env` key was present.
    - The `Cookie` header value: probe A, its value did not arrive.
    - All of these return if `send_default_pii` is turned on, and no test pins it: grep of
      `tests/` for `send_default_pii` finds nothing. Pin it.

12. **Three channels outside both hooks.** (This item named two until W56 review round 1,
    which found the third, metrics, ON by default.)
    - Span streaming (`_experiments={"trace_lifecycle": "stream"}`) copies every unfiltered
      header into `http.request.header.*` span attributes (`_asgi_common.py:118-121`,
      `asgi.py:320-324`). It runs `before_send_span`, not `before_send_transaction`.
    - `enable_logs` runs `before_send_log` (`client.py:1200-1215`). It has a second switch:
      `utils.py:2077-2084` (`has_logs_enabled`) also reads `_experiments["enable_logs"]`. Review
      round 2 found a mutation adding that switch left every test green; W56 now passes
      `enable_logs=False` and a test pins both switches.
    - Both are off: `tracing_utils.py:112-116`, `consts.py:1316`.
    - Metrics: `enable_metrics` defaults to True (`consts.py:1319`) and sends `trace_metric`
      items, which run `before_send_metric`, not either hook. Review round 1 measured a key in a
      metric attribute reaching the transport. W56 now passes `enable_metrics=False`.
    - Test: pin that `init` turns on none of the three.

## Design failure modes

13. **Stripping headers in a middleware does nothing.** Sentry wraps `Starlette.__call__`
    outside every app middleware (`starlette.py:432-443`), and reads the raw scope.
    `VisitorAddressMiddleware` copies the ASGI scope (`auth.py:130`) and needs `Fly-Client-IP` to
    work. Scrub in the hooks.

14. **List of headers to drop, or list of headers to keep.**
    - No list to drop was built. The probe measured `X-CSRF` and `Forwarded` leaking (items 5
      and 6), which a list to drop holding only the three named headers would have missed.
    - A list to keep fails the other way: it drops headers an operator needs. Choose them on
      purpose, for example `host`, `user-agent`, `accept`, `content-type` and `x-request-id`.
    - Test: an unknown header must be dropped. That test goes red for a list-to-drop design.

15. **A scrubber that deletes everything passes every negative test.** Each "not present"
    check needs a partner showing the thing is still there:
    - `user-agent` arrives.
    - Exactly 1 alert event, and at least 1 transaction.
    - `account_id`, `global_daily_ceiling_usd` and the `event_type` tag arrive.
    - The exception type and the safe part of its message (`upstream rejected`) arrive.

16. **A scrubber that raises loses the event silently.** The SDK catches the error and DROPS
    the event (`client.py:887-904`, `:914`). That is safe for privacy, but the ceiling alert
    vanishes.
    - Probe: the hook sees header values as `str`, and `''` for headers the SDK already
      filtered, so a string-only scrubber did not crash.
    - Still add `headers` set to None, a list, or missing to
      `test_redaction_survives_a_partial_event`.

17. **Fixing only `before_send`.** It never runs for transactions (`client.py:881-886`), and
    S1 was measured on a transaction. Put the header scrub in the shared `_scrub_user_text`.

18. **Changing shared objects.**
    - Safe: each event gets its own deep copy of `request` (`asgi.py:402-405`,
      `starlette.py:541`).
    - Also safe, in sentry-sdk 2.63.0: breadcrumbs. `client.py:870-879` serialises the event
      before `before_send` runs, and the serialiser builds new dicts, so the hook edits a copy.
      (This line said the opposite until W56 review round 2.) Measured: a hook that rewrote
      every breadcrumb message sent the rewritten text on two events, and the isolation scope's
      breadcrumb still read `original` afterwards (a scratch probe with a capture transport).

19. **The existing alert test cannot fail.**
    - Where: `tests/unit/test_global_spend_ceiling.py:276-309` mocks `sentry_sdk.push_scope`,
      and its fake `set_tag` throws values away.
    - Turning it into "`client_ip` not in `seen_extras`" passes over nothing in two cases.
      First, if the code moves off `push_scope`: the probe printed its DeprecationWarning at
      `costs.py:1482`, and after the move the mock catches nothing. Second, if the address
      moves into a tag, a context or the message.
    - Fix: assert `account_id` IS in `seen_extras` too, and add the real capture test from
      item 2.

20. **The key pattern has gaps; W76 owns them.**
    - `\bsk-[A-Za-z0-9_-]{10,}\b` (`logging_config.py:93`) misses a key glued to a word, a
      percent-encoded key, and a key without its prefix (security review section 2).
    - Reusing `_redact_secrets` for exception values inherits these gaps. W56's test should
      use a plain `sk-or-v1-` key and say why.

21. **Signed-in and anonymous visitors must get the same result.**
    - Both send `X-CSRF-Token`. A signed-in visitor also sends a session cookie, which the SDK
      already filters.
    - `account_id` is a spend key in both cases. For an anonymous visitor it is a keyed hash of
      the network (`session_store.py:163-172`).
    - Production refuses `X-Account-Id` (`config.py:984`), but any client can still send it,
      and the header still reaches Sentry.
    - Test both kinds of visitor, plus the inline legacy path (`query_runs.py:926-928`).

22. **Test hygiene and outside settings.**
    - `sentry_sdk.init` in a test leaves a global client and a patched `Thread.start` behind.
      Re-initialise with no DSN afterwards. UNVERIFIED that it breaks any current test.
    - Sentry's server-side scrubbing settings are not a substitute: the data has already left
      the process. What the organisation has configured is UNVERIFIED.

## Documents that say the address goes to Sentry

23. **Grep result.** `grep -rn -i sentry docs src tests configs` (archive excluded), filtered
    for `client_ip`, "visitor's address", "IP breakdown", "account/IP" or
    `request.client.host`, finds 11 files. `query_runs.py` and `costs.py` are added by hand
    because their lines split "Sentry" and the address.
    - **Update (7):**
      - `src/product_app/costs.py:1478-1490`, the code.
      - `src/product_app/query_runs.py:810-814`, a comment saying the alert "wants an IP
        breakdown".
      - `src/product_app/templates/ops.html:83`, "for the account/IP breakdown".
      - `docs/48-data-retention.md:14`: "in the same event as the visitor's address".
      - `tests/unit/test_global_spend_ceiling.py:276-309`.
      - `docs/adr/0132:108-110` and `docs/adr/0144:44`. Record the change in a new ADR rather
        than rewriting them.
      - ADR-0023's title, "scrubbed on every path", is contradicted by S1 until this ships.
    - **Leave (6):**
      - `docs/19` CHG-029 and CHG-042: the owner's words.
      - The `docs/65` W56 row: generated from the board check.
      - Three dated analysis documents (2026-10-04 W47, 2026-10-11 handoff, 2026-10-13
        security review).
      - `configs/skill-router.json:627`: a routing pattern, not a claim.
    - Grep of `tests/` and `scripts/` for `48-data-retention` finds no check that pins
      `docs/48`.
