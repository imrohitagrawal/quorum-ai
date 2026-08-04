# ADR-0012: record the billing evidence for a provider error, and do not reclassify a 5xx yet

## Status

Accepted — 2026-08-05 (issue #105).

## Context

`providers._UNBILLED_HTTP_STATUSES` lists the HTTP statuses OpenRouter returns
by rejecting a request outright — `{400, 401, 402, 403, 404, 429}`. Those are
decided before any token is generated, so nothing can have been billed and the
caller keeps the run honestly `measured`. **Every other status, 5xx above all,
is treated as possibly-billed**, on the premise that a 5xx can follow a
generation that already consumed tokens.

Issue #105's finding is that **no evidence for that premise exists anywhere in
this repo**, and that OpenRouter's common `503 "No allowed providers are
available for the selected model"` is a router-level refusal decided before any
provider is engaged.

### Measured on `56edd1b`, before any change

Driven hermetically: a real `http.server` on loopback answering every
`POST /api/v1/chat/completions` with `503` and OpenRouter's real refusal body,
with the real `debate_stub_service` and `synthesis_stub_service` above it and
the real `_actual_cost` deciding the served figure. Reproduced independently
twice.

| Quantity | Value |
|---|---|
| HTTP requests served | 7 |
| `debate_call_usages` | `[(1, None), (2, None)]` |
| `synthesis_call_usages` | `[None, None, None, None, None]` |
| `cost_source` | `estimated` |
| **served `actual_cost`** | **`0.0328`** |
| **truly measurable (the 4 captured initial slots)** | **`0.00622500`** |
| **overstatement** | **5.269x** |

The direction is deliberate and is not itself the defect: the run is labelled
`estimated`, so no false precision is served. Understating a real CHARGE under
a `measured` label is the dishonesty F-06 exists to prevent, and that is the
opposite error.

### What is available at the decision point, and was being discarded

At `providers.py`'s `except HTTPError` branch the exception is a genuine
`HTTPError`, which carries `.headers` and `.read()`. An AST census of
`providers.py` **on `56edd1b`** found `exc.read()` / `exc.headers` accessed
**0 times** — the
only `.read()` calls are on the success path. So the evidence that decides the
question was arriving and being thrown away on every single provider error.

### Measured against the LIVE OpenRouter API, 2026-08-05

One deliberate probe, costing nothing (a 401 consumes no tokens), settled two
things no amount of local work could:

| Fact | Value |
|---|---|
| `Content-Length` on an error | **absent** |
| `Transfer-Encoding` | **`chunked`** |
| `Server` | `cloudflare` |
| error body | `{"error":{"message":"User not found.","code":401}}` (50 bytes) |
| `error.metadata` on that 401 | **absent** |
| `Access-Control-Expose-Headers` | `X-Generation-Id,`**`X-Provider-Name`**`,cf-ray` |

**The first version of this change was fatally wrong because of row 1**, and
every local gate was green on it. See "The design this replaced" below.

Row 6 was a gift: OpenRouter exposes the engaged provider as a **response
header**, so `provider_name_header` is captured as a second, independent
signal that survives a body which is unreadable, over-large or not JSON.

Two further measurements shaped the decision:

- The `URLError` branch — which issue #105 explicitly folds into the same
  review, because a connect timeout is classified the same conservative way —
  **logged nothing at all**. A possibly-billed classification was being made
  with no record whatsoever.
- `logging_config.JsonFormatter` folds `extra={...}` keys into the emitted JSON
  object — all except its reserved set, keys already in the payload, and
  `_`-prefixed keys (`logging_config.py:75-77`) — so the fields added here
  are visible to a production log aggregator without any further work.
  Confirmed by executing the formatter, not by reading it.

## Decision

**1. Do not change the classification.** `_UNBILLED_HTTP_STATUSES` is
unchanged, and a `503` still reads as possibly-billed. Issue #105's own
instruction is "do not change the classification on a guess about an external
API's semantics" — the honest input is a week of production logs, which do not
exist yet. A test pins every status's classification precisely so this stays
true until the data says otherwise.

**2. Record the evidence that will decide it,** as shape only:
`_billing_evidence_shape` reports `body_shape`, `body_bytes`,
`error_metadata_present`, `provider_name_present`, `provider_name_header` and
`sniff_time_bounded` onto the existing `upstream_provider_http_error` record,
alongside `billing_class`.

`body_shape` is one of `json`, `not_json`, `empty`, `unreadable` or
`too_large` — so a missing answer always says WHY it is missing.

**3. `provider_name_present` is three-valued, not boolean.** OpenRouter names
the provider it engaged at `error.metadata.provider_name`.

| Value | Meaning |
|---|---|
| `True` | a provider was named; a charge is possible |
| `False` | an error envelope arrived and named no provider — read together with `error_metadata_present` |
| `None` | unknown — unreadable, too large, empty, not JSON, or JSON carrying no `error` mapping |

Collapsing `False` and `None` into one falsy value is the specific defect this
avoids: the router refusal and a parse failure would become the same record,
and the log sample this exists to produce would be unreadable.

**`error_metadata_present` exists because `False` alone is not enough**, and
adversarial review is what surfaced it. Two bodies both report
`provider_name_present is False`:

| Body | `error_metadata_present` | What it means |
|---|---|---|
| `{"error": {"message": "No allowed providers", "code": 503}}` | `False` | the router refused; nothing was engaged — the #105 case |
| `{"error": {"code": 502, "metadata": {"raw": "overloaded"}}}` | `True` | a provider block exists carrying a provider's own error text, merely without a name — a provider very likely DID respond |

Counting the second as a router refusal in step 3 would license calling a
genuinely billed call unbilled, understating a real charge — the exact
dishonesty F-06 exists to prevent. The same applies to a `provider_name` of
`""` or `null`, which is reported `False` (truthiness, not `is not None`).

**4. Never log body content.** The values are a shape name, an integer and two
tri-state flags. An error body can echo the user's query text back verbatim.
This follows the rule `_log_post_dispatch_failure` already records for
exception messages, which can carry key material.

**5. The read is bounded in TIME, not gated on a header.** `exc.read()` is a
socket read carrying the connection's `openrouter_timeout_seconds` (8.0s).
Before sniffing, the socket timeout is lowered to
`_ERROR_BODY_SNIFF_TIMEOUT_SECONDS = 2.0` — best-effort, because reaching the
socket (`exc.fp.fp.raw._sock`) is CPython-implementation-specific, and the
record carries `sniff_time_bounded` so a platform where it fails says so
instead of silently reading as "no problem".

| Response shape | `main` | v1 (Content-Length gate) | **shipped** |
|---|---|---|---|
| body arrives promptly | 0.010s | 0.014s | 0.017s |
| body withheld, socket open | 0.010s | 8.009s | **2.013s** |
| **real OpenRouter error (chunked)** | not read | **NEVER READ — collects nothing** | **read** |

The byte bound `_ERROR_BODY_SNIFF_LIMIT_BYTES = 8192` still applies: past it
the body is reported `too_large` and not parsed.

**The design this replaced, and why it is worth recording.** v1 bounded the
TIME by refusing to read any body whose `Content-Length` was not declared.
Against a loopback server that was correct, elegant, and passed 20 mutations
and every gate. Against the real API it would have reported `no_length` for
**every single provider error**, because OpenRouter answers errors chunked —
so issue #105 step 1 would have shipped, deployed, gathered nothing for a
week, and looked healthy the whole time. A mitigation gated on an upstream's
behaviour is worth exactly as much as the measurement of that upstream, and
there was none. `test_a_chunked_body_with_no_content_length_is_READ` now pins
it.

**6. Log the `URLError` branch too,** with the reason's class name only, and
its billing class.

In both branches `billed` is computed once and feeds both the log and the
return, so a record can never disagree with the decision it describes.

## Rejected alternatives

**Add `503` to `_UNBILLED_HTTP_STATUSES` now.** Tempting, and a one-line
mutation proves it takes the measured run from `0.0328`/`estimated` to
`0.0062`/`measured`. Rejected: it decides an external API's semantics from one
synthetic body. A 5xx that genuinely follows a partial generation would then
understate a real charge under a `measured` label — the exact dishonesty F-06
exists to prevent. This is precisely the guess issue #105 forbids, and it is
pinned as a test row so a future change has to argue with it.

**Classify on the body at request time** — "5xx with no `provider_name` ⇒
unbilled". This is where the evidence points and is the likely eventual fix,
but it is the same decision as above with an extra condition, made from the
same absent data. It also cannot be validated without knowing how often the
key is absent for reasons other than a router refusal — which is what the log
sample will show.

**Log the whole body and decide later.** Rejected on data protection: the body
can carry the user's query text, and this would put it in a production log
aggregator. Shape is sufficient for the decision.

**Log only on 5xx.** Rejected: a known-unbilled `429`'s body shape is the
positive control that makes the 5xx sample interpretable. Logging both costs
one bounded read on a path that has already failed.

## Consequences

- Every provider HTTP error **except the `:online` search-rejection early
  return** now carries the evidence to settle #105, and every opener failure is
  recorded at all for the first time. The `:online` 400/404 returns before the
  log deliberately — it is a benign, expected probe signal — and
  `test_search_rejected_variant_still_returns_before_any_evidence_read` pins
  that it stays so.
- The 5.27x overstatement is **still live**. This ADR does not fix it; it makes
  it fixable with data instead of with a guess. Issue #105 stays open at step 1
  of 3.
- Step 2 is a human step — read a week of production logs, filtering
  `upstream_provider_http_error` by `status_code` and `provider_name_present`.
  Nothing automates it, and nothing here reminds anyone to do it.
- A bounded extra read happens on each provider error where the upstream
  declared a length of 8 KiB or less. It is on a path that has already failed.
  Measured cost against `main` on the shapes that DO get read: 0.020s → 0.014s,
  i.e. no measurable change.
- **Known gap, stated rather than implied:** `_billing_evidence_shape` consumes
  the body when it reads one. Nothing downstream reads it today (measured: 0
  accesses), but a future reader of `exc` on this path will find it empty. On
  the `no_length` and `too_large` paths the body is untouched.
- **Also stated:** the load-bearing schema claim — that OpenRouter names the
  engaged provider at `error.metadata.provider_name` — is **ASSUMED, not
  measured**. This repo holds no captured OpenRouter error body
  (`grep -rn provider_name src/ tests/ docs/ e2e/` outside the new code returns
  nothing). It comes from the issue. Step 2's log sample is what will confirm
  or refute it, and step 3 must not proceed if it is refuted.

## How this was verified

**Twenty-one** mutations, each applied to a copy and each confirmed to still
parse — a mutation that breaks collection proves nothing. **All twenty-one
killed**, by 45 tests. The load-bearing ones:

| Mutation | Killed by |
|---|---|
| **add `503` to `_UNBILLED_HTTP_STATUSES`** | `test_capturing_the_evidence_does_not_change_the_classification` |
| **gate the read on `Content-Length`** (the production-fatal v1 design) | `test_a_chunked_body_with_no_content_length_is_READ` |
| never bound the sniff time | `test_an_unreachable_socket_is_reported_not_silently_assumed` |
| hardcode `sniff_time_bounded` to `True` | `test_an_unreachable_socket_is_reported_not_silently_assumed` |
| drop the `X-Provider-Name` capture | `test_the_provider_name_header_is_captured_independently_of_the_body` |
| read unbounded instead of the byte bound | `test_the_error_body_read_is_actually_bounded` |
| raise the byte limit `8192` → `40000` | `test_oversized_body_is_reported_too_large_and_never_read` |
| collapse `provider_name_present` to `False` | `test_provider_engaged_body_reports_provider_name_present` |
| `bool(provider_name)` → `provider_name is not None` | `test_an_unusable_provider_name_reads_as_absent_not_present` |
| report an empty body as "no provider named" | `test_empty_body_reports_unknown_not_absent` |
| hardcode `error_metadata_present` to `False` | `test_an_unusable_provider_name_reads_as_absent_not_present` |
| treat any JSON body as a definitive answer | `test_json_that_is_not_an_error_envelope_reports_unknown` |
| log the raw body content | `test_a_body_that_raises_on_read_does_not_escape` |
| leak content in the `not_json` branch | `test_the_body_content_is_never_logged` |
| leak content in the `too_large` branch | `test_response_headers_never_reach_the_record_on_the_unread_path` |
| hardcode / delete the HTTP branch's `billing_class` | `test_the_http_record_states_the_same_billing_class_it_returns` |
| delete the `URLError` log statement | `test_opener_failure_is_logged_with_its_reason_class` |
| leak `str(exc.reason)` into the opener's `extra=` | `test_opener_failure_never_logs_the_exception_message` |
| narrow the guard so `OSError` escapes / move `len()` outside the `try` | `test_a_body_returning_a_non_bytes_value_does_not_escape` |

### What each instrument caught, in the order it caught it

The point of this table is that **each instrument found a class the previous
one could not**, and the last one — a single free call to the live API — found
the defect that would have made the whole change worthless in production.

| Instrument | What it found |
|---|---|
| TDD (write the test first) | the feature itself; 21 tests green |
| mutation round 1 | 2 vacuous assertions of my own: a byte bound asserted downstream of the read, and a truncation check a cut-off body satisfied anyway |
| prose review | a leak guard asserting only on `caplog.text`, which renders no `extra` fields — `str(exc.reason)` leaked into the production JSON with all 22 tests green |
| correctness review | **a real 1144x regression** (8.009s block on a withheld body); `billing_class` unasserted on the HTTP branch; the leak test reaching only 1 of 5 branches; `len()` outside the defensive `try`; `provider_name_present` conflating two different findings |
| mutation round 2 | the byte limit asserted against its own constant (rule 7a), so raising it survived |
| **one free call to the LIVE API** | **the `Content-Length` gate — added to fix the 1144x regression — would have read NOTHING in production, because OpenRouter answers errors chunked.** Also handed over `X-Provider-Name`, a second signal nobody knew existed |

Every earlier instrument was green on the design the last one destroyed.

## What is NOT done

Issue #105 stays **OPEN at step 1 of 3**, and the 5.27x overstatement is still
live in production. Step 2 is a human step: read a week of
`upstream_provider_http_error` records, grouped by `status_code`,
`billing_class`, `body_shape`, `error_metadata_present`,
`provider_name_present` and `provider_name_header`.

**Two risks to step 2, stated rather than discovered later:**

- Production daily spend was `$0` when this was written, so a week of logs may
  contain **no provider errors at all**. If so, step 2 needs deliberately
  provoked traffic, not patience.
- The `error.metadata.provider_name` schema is still **ASSUMED for a 5xx**. The
  live probe confirmed the envelope shape and that a 401 carries no `metadata`,
  but a real router-level 503 was not captured — the available key returns 401.
  Step 3 must not proceed until a real 503 body is in hand.
