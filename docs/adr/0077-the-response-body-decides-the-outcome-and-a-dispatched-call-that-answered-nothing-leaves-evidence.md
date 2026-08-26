# ADR-0077: The response body decides the outcome, and a dispatched call that answered nothing leaves evidence

## Status

Accepted — 2026-08-26

## Context

The approved plan scheduled this work as *"B1 — re-classify billing for in-band
stream errors, a blocking prerequisite for streaming"*: every branch in
`_post_messages` keys on the HTTP status line, so a mid-stream failure arriving
as `200 OK` plus an SSE error event would be read as a success.

**The premise is correct and the remedy was not.** Two free checks settled it
before any code was written.

**The vendor contract, confirmed.** OpenRouter's error documentation states that
once the first token is written the status and headers are committed, so *"the
error must arrive in-band as an SSE event"*, and gives the frame: an object of
type `chat.completion.chunk` carrying a **top-level `error`** and
`choices[0].finish_reason == "error"`.

**A `$0` probe with a deliberately invalid key**, which costs no tokens:

```
$ curl -sS -N -D - -X POST https://openrouter.ai/api/v1/chat/completions \
    -H "Authorization: Bearer sk-or-v1-0000...0000" -H "Content-Type: application/json" \
    -d '{"model":"openai/gpt-4o-mini","stream":true,"max_tokens":1,"messages":[...]}'
HTTP/2 401
content-type: application/json
server: cloudflare
{"error":{"message":"User not found.","code":401}}
```

So a **pre-dispatch** refusal under `"stream": true` still arrives as a plain
HTTP status with a JSON body, not as SSE. `_UNBILLED_HTTP_STATUSES` keeps
working unchanged, exactly as the plan assumed.

**What the plan got wrong: its own bite-proof passes before the code exists.**
Driving the real `_post_messages` through the `product_app.providers.urlopen`
seam on `cb4b6fd`, with the documented mid-stream frame delivered as an SSE
body:

```
SSE: 3 deltas then documented error frame     posts=1 -> _DISPATCH_UNMEASURED
SSE: clean stream, usage in final chunk       posts=1 -> _DISPATCH_UNMEASURED
200 JSON: top-level error, no choices         posts=1 -> LiveProviderResult(text='', usage=None)
200 JSON: partial content + finish_reason=error
                                              posts=1 -> LiveProviderResult(text='half an ans',
                                                          usage=40/7/47, trunc=False)
CONTROL 200 JSON: healthy completion          posts=1 -> LiveProviderResult(text='hello',
                                                          usage=10/5/15, trunc=False)
```

An SSE body fails `json.loads`, lands in the existing catch-all, and is already
classified possibly-billed. **The error case needs no change.** The only line
that is wrong is the *clean* stream — and fixing that means writing the parser,
which is the next package. A test asserting "an error stream is possibly
billed" would therefore have shipped green against `main`, unable to fail when
a later parser drops the error frame. That is precisely the vacuity rule 6b
exists to stop.

**What IS wrong, today, with no streaming involved,** is the last two lines
above:

1. A provider that broke part-way through is **indistinguishable from one that
   finished**. `_finish_reason_indicates_truncation` reported `True` only for
   the literal `"length"`, so `finish_reason: "error"` yielded `trunc=False`.
   That partial text counts toward `live_count`, the agreement tally and the
   citation-coverage denominator, and the "(shortened)" marker never paints.
2. A 200 whose body parses but yields no usable answer recorded **nothing at
   all** — the only dispatched-failure path in the function that logged no
   event. Reachable without any exotic assumption: a bare `{}`, a truncated but
   valid JSON object, a CDN's JSON denial page (`Server: cloudflare` is already
   on every response). Two of the four events that *do* log —
   `upstream_provider_transport_error` and `upstream_provider_body_unreadable` —
   carried no `billing_class` and were **filtered out of the durable billing
   file** by `telemetry_sink.BILLING_EVENTS`, which admitted exactly two names.
   The consequence is pointed: the most expensive live failure mode measured in
   this work — a healthy chunked response abandoned by the per-`recv` socket
   timeout — surfaces as `upstream_provider_transport_error`, so it was
   invisible in the very dataset issue 105 is to be settled from.

The full enumeration, its evidence and the three lens claims that did **not**
survive re-checking are in
`docs/analysis/2026-08-26-b1-provider-billing-failure-modes.md`.

## Decision

**The response body decides the outcome, and a dispatched call that produced no
answer leaves evidence.** Three changes, no transport change.

**1. `finish_reason: "error"` means the answer is not complete.**

```python
_UNCLEAN_FINISH_REASONS: frozenset[str] = frozenset({"length", "error"})
```

A closed set of two, not "anything other than `stop`". `"content_filter"` stays
out: it means the provider *refused*, which is a different event from running
out or breaking, and `tests/unit/test_providers.py` pins it as non-truncation
on purpose.

**2. A 200 that yields no visible answer emits `upstream_provider_empty_answer`,
and the return value is unchanged.** The predicate is `is_visible`, matching the
gate that actually fails the slot in `_live_openrouter_response`, so the two
cannot disagree about a whitespace-only completion. The record carries
`model_id`, `billing_class` and `usage_absent` — no part of the body, because a
provider error string is upstream-controlled text of unbounded length.

**3. Every dispatched-failure record states the billing class it returns, and
reaches the durable file.** `_log_post_dispatch_failure` now emits
`billing_class`, and `BILLING_EVENTS` admits all five event names instead of
two.

### The defect this fix introduced, and what caught it

Rule 12 says to budget a round for your own fix adding a defect. It did, on the
first attempt. `first.get("finish_reason") == "length"` is **total over every
type**; `reason in frozenset(...)` is not — `["length"]` raises
`TypeError: unhashable type: 'list'`. That call sits inside the parsing `try`,
so an upstream sending a list would have taken a good, billed, **measurable**
response and silently downgraded it to `estimated`. It was caught by an
existing test, `test_malformed_payloads_never_assert_truncation[payload7]`,
whose "finish_reason is a list" row exists for exactly this. The fix is an
explicit `isinstance(reason, str)` guard, and the reason is written next to it.

## Rejected alternatives

### Building B1 as the plan specified — REJECTED on a measured vacuity

Sending `"stream": true` and adding an in-band error branch. Rejected because
the measurement above shows the error case is already classified correctly and
the proposed bite-proof is green on `main` before the code exists. Shipping it
would have added a branch whose test could not fail, in money code, which is
the F-01 shape rule 6b was written after.

### Collapsing the answerless 200 to `_DISPATCH_UNMEASURED` — REJECTED as a money regression

Tidier, and wrong. F-06 finding C moved usage extraction *above* the emptiness
guard precisely so the provider's own statement of what it charged survives an
empty completion. Returning the sentinel would discard it and force `estimated`
on a call whose cost is known. Pinned by
`test_a_stated_charge_survives_the_new_record`; the mutation that adds
`return _DISPATCH_UNMEASURED` to that branch reddens it.

**The defect was the silence, not the classification** — and that distinction is
the whole reason this change is small. The return values were already right.

### Widening `finish_reason` to "anything other than `stop`" — REJECTED

It sweeps in `content_filter`, reversing a deliberate decision, and it would
stamp "(shortened)" on any provider-specific reason string this product has
never seen. Pinned in both directions:
`test_content_filter_is_still_not_reported_as_shortened` and
`test_a_clean_stop_is_not_marked_shortened`.

### A new `error_envelope_code` telemetry field — REJECTED as unearned surface

Tempting, so that a 402-inside-a-200 could be told from a 502-inside-a-200. But
`TELEMETRY_FIELD_NAMES` is a curated allowlist checked in both directions, the
in-body code is not the HTTP status the issue-105 dataset is keyed on, and no
question anyone has asked needs it yet. `model_id` plus `usage_absent` is enough
to count these events. Add it when a reader is actually blocked.

### Folding this into the streaming package — REJECTED

The coupling is real but one-directional: this half bites today and the parser
does not need it to land first. Merging them would put a money concern and a
transport concern in one review, against rule 17, and make the largest and
riskiest diff of the three larger still.

### Leaving `shortened`'s meaning alone and inventing a second flag — REJECTED

`shortened` crosses the API boundary, so widening what it means is a real
change and is recorded here as one. But its user-visible job is already exactly
right for both causes — *do not present this as the model's complete view* — and
a second near-identical flag on the served schema would make every consumer
decide which one to read.

## Consequences

- A provider that fails part-way through is now marked. The served field
  `shortened` means "the provider did not finish", not only "it hit the token
  ceiling". Its docstring says so, and the set that decides it is named and
  commented so the next widening is a decision rather than a tidy-up.
- **`is_truncated` cannot fire in production today**, because
  `openrouter_live_execution_enabled` is `false` and no live body reaches this
  code. Like ADR-0075's stance branch, this is latent-correct: covered by tests
  and by eleven killed mutants, and by nothing observable in production. That is
  an honest report, not a gap papered over.
- The durable billing file gains three event names. All three are failure
  events and rare, so the 1 MiB × 4 rotation ceiling is unaffected — but a
  sustained upstream outage now writes there where it previously did not.
- The dataset issue 105 will be settled from is no longer missing its most
  expensive category. It is still **incomplete in a different way**, recorded
  here rather than fixed: a `:online` 400/404 returns `_SEARCH_REJECTED` before
  both the status set and the log, so 4xx counts under-report for the majority
  of initial-answer calls.
- The streaming package inherits a classifier that already understands the
  shape of a mid-stream error frame — a top-level `error` with
  `finish_reason: "error"` — so it adds a reader, not a second classification.
- **Nothing here settles what a streamed mid-generation failure costs.** The
  question of whether a stream that delivered real tokens and then errored
  should be served `measured` or `estimated` is deferred to the streaming
  package, where a body with usage in a final chunk can actually be produced.
