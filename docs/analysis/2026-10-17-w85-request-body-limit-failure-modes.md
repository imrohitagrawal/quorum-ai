# W85 failure modes (FAILURE-MODES role, read-only)

**Outcome (added when W85 was built, 2026-10-17).** The build closed A1, A2, A3, A4, A8, A9 and A11,
and A6 as far as the server goes (no `Connection: close`). Recorded as advisory, not built: A5, A7,
A10, A12, and what Fly's proxy shows on an early 413 (A6, UNVERIFIED). The decisions and the
measured before-and-after table are in ADR-0171. This list was written before any code, by a
read-only agent; its text below is unchanged except that home-folder paths are now repo-relative
and one citation (ADR-0120, section D) was rewritten to the ADR's real file name.

Tree: the W85 worktree at `a2af06c`. Versions measured: starlette 1.3.1, fastapi 0.137.2, uvicorn 0.49.0, h11 0.16.0, httptools 0.8.0, pydantic 2.13.4.
Production runs `uvicorn ... --workers 1` (Dockerfile:89-95) with `uvicorn[standard]`, so httptools is the parser. Fly `hard_limit = 100` connections (fly.toml:173-176), `memory = "512mb"` (fly.toml:197).
"Measured" = I ran it (in-process TestClient or raw ASGI, or a loopback uvicorn with a stand-in middleware written to the planned design). "UNVERIFIED" = not run.

## A. Not handled by the planned design (ranked)

**A1. A body UNDER 1 MB still blows the memory, through the 422 response.** Measured with the current models and one anonymous cookie from `GET /v1/session`. No CSRF token is needed, because `enforce_csrf` runs inside the handler, after validation.
| body (<= 1 MB) | result |
|---|---|
| `{"query_text":"x","model_slots":[1,1,...]}` 1,000,034 B | 422, 500,000 `field_errors`, **47.4 MB response, 521 MB Python peak, 7.3 s** |
| `safety_acknowledgements: [{}, ...]` 900,135 B to `POST /v1/query-runs` | 422, 600,000 field_errors, **58.3 MB response, 651 MB peak, 8.7 s** |
| `context` with 80,000 keys, int values | 422, 80,000 field_errors, 7.3 MB response, 89 MB peak |
| `context` with 80,000 keys, null values | 422, 1 error, but the message lists every key: a 789 KB echo |
The process max RSS reached 1.58 GB. A list `max_length` fixes the list rows: Pydantic stops at 1 error (`too_long`, peak ~0 MB, measured). It does NOT fix `context`: a dict `max_length=2` with bad values still gave 80,000 `string_type` errors (measured).
Fix: cap the number of `field_errors` in `_format_validation_error` (main.py, around line 920). Also refuse an over-size `context` (more than 2 keys) in a `mode="before"` validator, before Pydantic checks each value.
Test: post each row above. Assert status 422, `len(field_errors) <= cap`, response under (say) 10 KB.

**A2. `extra="forbid"` CREATES a new amplifier.** Measured: a 1,040,138-byte body with 111,000 unknown top-level keys, through a forbid subclass and the app's own `_format_validation_error`, gave 111,000 `extra_forbidden` errors, a **9.5 MB response, 130 MB peak and 1.8 s** on the event loop. The same body today is accepted with unknown keys ignored (14.6 MB peak).
The nested `SafetyAcknowledgement` multiplies this: (number of items) x (unknown keys per item).
Measured fix: a `model_validator(mode="before")` that compares the keys with `model_fields` and raises one `ValueError` gives 1 error, 8 MB peak, 0.005 s. Keep `extra="forbid"` as well, for the OpenAPI document. Capping the number of field_errors (A1) covers the response size either way.

**A3. A client disconnect mid-body becomes an unhandled 500 plus an ERROR log.** The design says "buffer; on exceeding answer 413", and it does not say what to do on `http.disconnect`. The natural "return" was measured at every position inside the security-headers `BaseHTTPMiddleware`: `RuntimeError: No response returned.` was raised and a 500 was sent. uvicorn logs "Exception in ASGI application" at ERROR. Whether Sentry captures it is UNVERIFIED (its default integrations are on, logging_config.py:595).
Today the same disconnect gives a clean 400 (measured: FastAPI turns `ClientDisconnect` into `HTTPException(400)`, fastapi/routing.py:454).
Fix: on disconnect, pass a receive to the app that replays what was read and then the disconnect, so today's 400 path stays. Or send a response yourself.
Test: raw ASGI call with messages `[{"type":"http.request","body":b"x"*1000,"more_body":True},{"type":"http.disconnect"}]`. Assert nothing is raised and the status is not 500.

**A4. Trusting a Content-Length at or under 1 MB is a bypass.** If the design forwards without counting whenever a Content-Length is present and <= 1 MB, it can be beaten. Measured under h11: `Content-Length: 5` plus `Transfer-Encoding: chunked` gave scope header `b"5"`, and the app received **2,097,152 bytes**. httptools refuses that request with 400 (measured). But uvicorn falls back to h11 whenever httptools fails to import, and TestClient enforces neither.
Fix: always count bytes, whatever the header says.
Test: the TestClient case (`headers={"content-length":"5"}` with a 2 MB body) and the raw h11 case.

**A5. Memory under 100 concurrent bodies of about 1 MB.** Raw ASGI, 100 concurrent requests of 1,040,082 bytes in 64 KB chunks, all ending in 422:
- without the middleware: tracemalloc peak 216 MB, max RSS 310 MB;
- with the planned design (a list of chunks, then a join, then a replay): **peak 323 MB, max RSS 85 -> 453 MB**.
tracemalloc inflates RSS, so take these as relative numbers. The production container is UNVERIFIED. The extra ~100 MB is the second copy, made while the chunk list and the joined bytes both exist.
At the 1 MB limit, 100 connections (the Fly hard_limit) come close to 512 MB.
Options: buffer into one `bytearray` and drop the list; cap concurrent buffering; or a lower limit. The owner set 1 MB, so the session can only propose that last one.
Test: this concurrency probe, with a stated RSS ceiling.

**A6. A 413 sent before the body is read: what the client sees.** Measured on loopback, both parsers. The raw client got the 413 in every case.
- Without `Connection: close`, uvicorn keeps the connection and reads and discards the rest of the declared body. The 2 MB case ended in a read-timeout with the socket still open. This costs no memory (`on_body` returns once the response is complete, httptools_impl.py:313). It does cost bandwidth, for as long as the client keeps sending.
- With `connection: close`, the client sees a RESET while it is still sending.
- Behind Fly's proxy: whether the browser gets the 413, or a 502 or a reset, is **UNVERIFIED**. No production probe was made.

**A7. Metrics cannot tell a 413 from other errors, or do not count it at all.** Measured in fresh processes:
- If the limit is outside the instrumentator, a 413 is not counted at all.
- Innermost (inside `PrometheusInstrumentatorMiddleware`), it is counted, but as `status="4xx"`, grouped together with 401 and 422. An unmatched path gets `handler="none"`; a bogus method gets `method="OTHER"`. The labels are bounded.
So a 413 flood cannot be told apart from 401 and 422. If that matters, add a dedicated counter, or turn off status grouping.
`http_request_size_bytes_sum` adds the claimed Content-Length even when the body is refused (prometheus_fastapi_instrumentator/metrics.py:292). That is cosmetic.

**A8. Placement decides the headers and the request id.** `add_middleware` inserts the newest layer outermost. Today's order, outer to inner: security-headers (`@app.middleware`, main.py:899), VisitorAddress, RequestId, NormalizeMethod, Instrumentator. Measured:
| added where | security headers | X-Request-ID | counted in metrics |
|---|---|---|---|
| after main.py:899 (outermost) | **no** | **no** | no |
| between :715 and :899 | yes | **no** | no |
| before :708 (RequestId), after :701 | yes | yes | no |
| before :667 `.instrument(app)` (innermost) | yes | yes | yes, as 4xx |
The design needs it before line 667 for all three, or before line 708 if metrics are not wanted. Test: assert `x-request-id`, `x-content-type-options` and `content-security-policy` on the 413 response.

**A9. The `model_slots` bound must be 5 or more, and needs an ADR.** `test_estimate_refuses_one_and_five_slots_with_the_range_message[5]` (tests/integration/test_panel_size_api_and_workspace.py:90) expects the typed `INVALID_MODEL_SLOT` for 5 slots. A `max_length` of 4 turns it into a generic `VALIDATION_ERROR` (ADR-0120 decision 6 measured exactly this). A count between 5 and the bound stays typed; above the bound it is generic. That bound is new behaviour.
ADR-0120 decision 6 says "The API edge is not bounded to the range". Bounding the edge at all, even above 4, changes that decision, so it needs an ADR in the same pull request (rule 16d).
Put the same bound on `slot_search`: its length mismatch is typed (model_slots.py:495, test at :157).
There are 2 `WarningType` values (safety.py:150), so `safety_acknowledgements` needs a bound of at least 2. Allow some room for repeats; whether any client repeats an acknowledgement is UNVERIFIED.

**A10. Strings with no length bound (the design covers only lists).** These rely on the 1 MB limit alone: `model_slots[]` items, `SafetyAcknowledgement.version`, `CostConfirmation.confirmation_token`, and the keys of `context`. ASVS V2.2.1 calls for limits on these too.

**A11. Snapshot and contract gates.** `extra="forbid"` adds `additionalProperties: false`, and list bounds add `maxItems`, to `QueryRunEstimateRequest`, `QueryRunCreateRequest`, `QueryRunWarningsRequest`, `SafetyAcknowledgement` and `CostConfirmation`. All five are in `app.openapi()` today (measured). So `make openapi-check` goes red until `openapi.yaml` is regenerated.
Schemathesis (`tests/contract/test_api_contract_schemathesis.py`) generates valid data, so it should not hit the new rules. `KNOWN_CONTRACT_DEFECTS` keys on status plus failure class. A 413 is undeclared, but the fuzzer does not send bodies over 1 MB, so this is low risk. Not run: **UNVERIFIED**. Settle it with `make api-contract` and `make openapi-check`.

**A12. The middleware delays every request until its whole body has arrived.** Today a GET with `Content-Length: 50` and 5 bytes sent is answered at once, because no handler reads it. With buffering, the request waits for all 50 bytes. uvicorn has no timeout on reading a request body, so this hangs until the client gives up (measured: no response, read-timeout). Slowloris already exists for body-reading routes; this widens it to every route. Low impact, but name it.

## B. Already handled by the design, or by the server (measured unless marked)
- Invalid Content-Length values `-1`, `abc`, `+5`, `1_0`, `0x10`, `9999...` (23 digits), `5, 5`, conflicting duplicates, and CL plus TE: httptools answers 400 before the app runs (measured). h11 also 400s the malformed and conflicting ones; it collapses `5, 5` into `b"5"` and lets CL plus TE through (see A4). `" 5"` is trimmed to `b"5"` by both.
  Under TestClient anything can arrive, so parse defensively: a bare `int()` raising `ValueError` would be a 500. Python's `int()` also accepts `"1_0"` and non-ASCII digits.
- Content-Length smaller than the body: the server frames by Content-Length, so the app gets only that many bytes (measured: 3 of 20; httptools 400s the rest). Larger than the body: the request hangs (A12; this happens today too).
- Exactly 1,048,576 bytes gives 200 and 1,048,577 gives 413, both with Content-Length and chunked (measured, loopback, both parsers). A chunked 2 MB body gives 413.
- Exceptions raised inside `receive()`: FastAPI turns any exception into 400 "There was an error parsing the body", except `HTTPException`, which it re-raises (fastapi/routing.py:450-457). The design answers before calling the app, so this does not apply. A "lazy" design that raises inside receive would give 400, not 413.
- gzip and Content-Encoding: nothing decompresses request bodies. A gzip body gives 400 today (measured). The limit counts bytes on the wire. Fly decompressing request bodies: UNVERIFIED, and unlikely.
- Lifespan: the app has a lifespan (main.py:606, :637). The middleware must pass any scope that is not `http` through untouched. Test it with `with TestClient(app):`. There are no websocket routes.
- Methods that carry no body (GET with a 2 MB body) get 413 (measured). No GET handler reads a body, so nothing is lost.
- Deep nesting (100,000 `[`) gives 400, not a crash (measured).
- Routes needing more than 1 MB: none. The body-taking routes are `/v1/query-runs` (create, estimate, warnings, DELETE), `/v1/account/delete`, `/v1/invite`, `/v1/session/keep-active`, `/v1/auth/google/start`, `/v1/auth/sign-out` and `/v1/auth/sign-out-everywhere`. There are no uploads or forms.
  The largest legitimate body is 100,220 bytes in ASCII. Worst case from the browser: `JSON.stringify` writes 6-byte `\u00XX` escapes only for control characters and lone surrogates, so 100,117 such characters is about 600 KB, still under 1 MB.
  A Python client using `ensure_ascii=True` (the plain `json.dumps` default) sends 12 bytes per emoji, so 100,117 emoji would be 1.2 MB. No such client was found. httpx 0.28.1, which TestClient uses, does not do this (UNVERIFIED reading).
- Page copy: app.js already has `413: "The request was too large to send."` (app.js:1724).

## C. Every client body, checked against `extra="forbid"`
- **app.js:** estimate `{query_text, model_slots[, mode][, context]}` (`runRequestBody`, app.js:190). Create: the same, plus `safety_acknowledgements:[{warning_type, version}]` (app.js:9253) and `cost_confirmation:{estimated_cost_usd, confirmation_token}|null` (app.js:9548). Warnings `{query_text[, context]}` (app.js:867). Context `{prior_question, prior_synthesis}` (app.js:813). **Every key is a model field, so forbid breaks nothing on the page.** The other bodies (account delete `{confirm_email}`, invite `{token}`) go to models that already forbid; the sign-in and sign-out calls send no body.
- **e2e:** `e2e/tests/navigation/navigation.spec.ts:58,71` sends `model_ids` (not a field). It is in a blocking lane (e2e.yml:465). It still passes: the first test accepts `[200,400,401,422,500]` and the second only asserts that a status exists. `parity-behavior.spec.ts:1313` sends `{query_text, model_slots}`, which is fine. The other e2e bodies are mocked responses (`route.fulfill`).
- **Python tests and scripts:** an AST scan of 134 dict literals carrying `query_text` (49 files), 52 literal posts to `/estimate` and `/warnings`, and every subscript assignment in files that call query-runs found **no key outside the model**. No `scripts/` file or workflow calls `/v1/query-runs`. This is a static scan: helpers that build bodies indirectly, or path constants, could be missed. The check that would settle it is the full suite, run on a copy with forbid on. **UNVERIFIED by running.**

## D. ADRs
- ADR-0120 decision 6 (`docs/adr/0120-a-panel-is-two-to-four-models-and-a-panel-of-two-is-described-honestly.md`, decision 6): the edge is not bounded, to keep the typed envelope. W85's list bounds change it (A9).
- No ADR covers request size or a 413 envelope. A grep of `docs/adr` for 413, body size, too large, REQUEST_TOO_LARGE and extra=forbid found none. So the 1 MB limit, the failure posture and the envelope need a new ADR (rule 16d).
- ADR-0163 (nothing private reaches Sentry) matters for A3 if the 500 reaches Sentry.

## E. Residue I caused
My first `import product_app.main`, run from inside the worktree at 21:30:43-44, created two gitignored paths: `.data/` (three sqlite files) and `src/product_app/__pycache__/`. I did not delete them, because my instructions forbid writing to the worktree. Every later run used a scratch cwd, `:memory:` databases and `PYTHONDONTWRITEBYTECODE=1`.
