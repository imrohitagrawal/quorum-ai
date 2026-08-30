# ADR-0084: Every paid call streams, and a stream must say it finished

## Status

Accepted — 2026-08-30

## Context

Board row **W1** ("stream the provider call"), the largest open item, taken
ahead of ranking on the product owner's instruction of 2026-08-30. Row **W15**
(two docstring references to a `_bound_sniff_time` that has no definition) is
clubbed in under rule 17g: same file, same reading, one reviewer, one deploy.

### The non-streaming transport is measurably broken for the models we ship

`_post_messages` posted a non-streaming request and read one JSON body. A
socket timeout is per-`recv`, never cumulative, so the shape of the failure is
not "slow" but "invisible". Measured against the live API on 2026-08-26 and
recorded in `docs/analysis/2026-08-26-b3-timeout-probe.md`:

| `openai/gpt-4o-mini`, same model and endpoint | worst inter-chunk gap |
|---|---|
| non-streamed, `max_tokens=2000` (the 2026-08-26 "spike" run) | **22.440 / 25.055 s** |
| streamed, `max_tokens=3000` (the B3 probe) | **0.478 / 0.208 s** |

Its own source calls this the paired comparison — same model, same endpoint,
same client — and it is the strongest evidence available here. **The token caps
differ**, which an earlier draft of this table hid by labelling both rows
`max_tokens=3000`; read it as its source states it, not as a controlled
experiment.

Against `openrouter_timeout_seconds = 8.0`, the non-streamed gaps trip the
stall detector on a healthy call. The consequence is not a slow answer: the
call is billed, `_DISPATCH_UNMEASURED` is returned, the user is shown a failed
slot, and the run's receipt degrades to `estimated` — money spent, nothing
shown, nothing measured.

**Scope, because the sweeping version of this sentence is false.** The probe
measured that bite on ONE of the four shipped answer models, and it explicitly
calls the per-`recv` bite a property of the MODEL rather than of the endpoint:
`nvidia/nemotron-3-nano-30b-a3b`, a default slot, measured 5.722 / 7.589 s —
under the cap. Streaming is chosen because it removes the failure mode wherever
a model has it, not because every shipped model has it.

### What streaming ADDS, and why it needs a new check

Chunked framing carries no length. `_iter_body_within_budget` restores an
`IncompleteRead` guard that `read1` had silently dropped, but that guard reads
`HTTPResponse.length`, which is `None` for a chunked response — and every
streamed response is chunked. So a stream that delivers three of forty frames
and then closes CLEANLY raises nothing at all. Measured on loopback: such a
response returns its prefix with no exception and `resp.length is None`.

Without an application-level terminator that prefix is valid, is served as a
whole answer, is priced, and reports `is_truncated=False`. That is the exact
defect the `IncompleteRead` restore was written to prevent, reached by a
different route — the third appearance of "replacing a read drops a guarantee
nobody had a test for".

## Decision

**One transport in `ProviderExecutionService`. Every call it makes streams; the
reassembled payload is fed to the four existing extractors unchanged; and a
stream that never says it finished is classified dispatched-but-unmeasured.**

**It is not the only paid caller in the repository, and saying otherwise would
be false.** `feedback_audit.py:671` posts to the same `/chat/completions`
endpoint with the same bearer credential, non-streaming, with a blocking
`response.read()`. It is untouched here: it is operator-invoked (no workflow
runs it — `grep -rln feedback_audit .github/workflows/` is empty), it is not on
the query-run path, and it is a separate concern under rule 17. Recorded rather
than glossed, because this ADR's own rationale for having one reader is that a
second unexercised one on a paid seam loses money quietly — and one exists.

| Choice | Decision | Why |
|---|---|---|
| Streaming mode | **always on, no flag** | the non-streamed path is the one measured to lose money; keeping it as a fallback preserves a known-broken reader that only runs in an emergency |
| Terminator | `[DONE]` **or** a non-null `finish_reason` **or** a top-level `error` | `[DONE]` alone is unmeasured against this upstream; requiring it could classify every healthy call unmeasured |
| No terminator | `_DISPATCH_UNMEASURED` + `upstream_provider_stream_incomplete` | tokens were generated and may have been billed, and we cannot say what arrived |
| `usage` | last frame carrying one; never summed, never invented | correct whether the upstream sends one final total or a running total |
| `finish_reason` | an unclean value LATCHES | the documented shape repeats `stop` on the usage chunk, which would erase a real truncation |
| Answer text | `delta.content` only, whitelisted by name | `delta.reasoning` would corrupt the judge's strict-JSON reply |
| Choices | index 0 only | everything downstream reads `choices[0]` |
| `stream_options` | **not sent** | see below |

The extractors — `_extract_message_content`, `_extract_usage`,
`_finish_reason_indicates_truncation`, `_extract_citations` — are reused
BYTE-UNCHANGED. The reassembler's whole job is to produce the payload an
equivalent non-streamed call would have returned, so the two shapes cannot
drift apart. `tests/unit/test_stream_reassembly_equivalence.py` is that
contract.

### `stream_options: {"include_usage": true}` is deliberately not sent

The claim "usage arrives in the final chunk with no opt-in" is recorded as
SETTLED by both `docs/adr/0078` and the B3 probe. Re-checked here: **both
attribute it to OpenRouter's documentation, not to a probe row, and the probe
script was not retained.** Per rule 11 it is therefore **ASSUMED, not
measured**, and both documents are corrected in this change to say so.

Sending the field would itself be a bet on unmeasured upstream behaviour — the
symmetric violation of rule 8c. **That an unrecognised body field yields HTTP
400 from OpenRouter is itself UNMEASURED**; it is the premise, not a finding.

What IS verified is the chain that follows IF it 400s, and the mechanism is
worth stating correctly because a first draft of this paragraph got it wrong.
The `_SEARCH_REJECTED` mapping does **not** come from `_UNBILLED_HTTP_STATUSES`
membership: it comes from the explicit `if exc.code in (400, 404) and
model_id.endswith(":online")` branch, which returns *before* that set is
consulted. That fires the bare-id retry, which takes a second 400, and only
*there* does membership matter — it makes the second call return `None` rather
than the unmeasured sentinel, so every slot drops to local simulation.
Demonstrated end to end: two paid dispatches, then a $0 fallback. A total,
silent product outage that costs nothing and therefore looks healthy to every
gate in this repository.

Being wrong the other way costs receipts their `measured` label. That is the
honest direction — it overstates uncertainty rather than understating a charge
— and it is the pre-streaming status quo, not a regression.

**It is measurable at $0 rather than argued.** `_log_call_token_shape` already
emits `usage_absent` on every call, and this change adds `stream_terminator`
beside it. Reading the two together over real traffic settles both open
questions at once: whether usage arrives, and whether `[DONE]` is ever sent.
The same field keeps pre- and post-streaming rows separable, so issue #268's
dataset is not corrupted by mixing two regimes in one percentile.

## Rejected alternatives

### A kill-switch flag keeping the non-streaming reader — REJECTED

Tempting as insurance. Rejected because reverting requires a deploy either way
(live execution is itself a deployed flag), because it doubles the state space
on the one code path that spends money, and above all because the "safe"
fallback is the path measured to trip its own timeout on a healthy call. The
emergency path would be the untested one.

### Buffering the whole SSE body, then parsing — REJECTED on memory

Simplest diff, and it would have reused the existing reader untouched.

**The magnitude here was overstated in a first draft and is corrected rather
than deleted.** What is MEASURED is the frame count: the B3 probe records a
2,594-token answer arriving in **4,194 frames**. It kept no byte column and its
script was not retained, so any wire-byte figure is a MODEL at roughly 300
bytes per frame — about 1.2 MB, against roughly 10 KB for the same answer
non-streamed. The earlier text gave "1,262,550 bytes over 4,196 frames … ~119x"
as though measured; the frame count contradicted the source by two, and the
ratio divided wire bytes by body bytes while the sentence claimed *resident*
bytes per call, which is a different quantity and a much smaller multiple.

The decision stands on the direction, which holds under either reading: with up
to 16 initial-answer workers plus synthesis on a 512 MB machine (`fly.toml`),
and a transient copy at `b"".join()` + `.decode()`, buffering is a materially
larger resident cost on a path with **no success-path byte cap at all**.
`_read_body_within_budget` was turned into the generator
`_iter_body_within_budget` instead, so exactly one loop still touches the
socket and every transport guard is shared rather than reimplemented.

### Treating a socket EOF as the end of the answer — REJECTED

This is the defect above. Rejected on the measurement, not on principle.

### Asserting truncation from a MISSING `[DONE]` — REJECTED

`_finish_reason_indicates_truncation`'s standing doctrine is that a malformed
response must never be able to *assert* truncation. Reporting the call
unmeasurable says "we cannot tell", which is true; marking the answer
"(shortened)" would invent a fact about the upstream.

### Adding a new classification for an in-band error — REJECTED as scope

A 200 whose body carries a top-level `error` is a pre-existing live defect on
the non-streaming path (it returns a real result with empty text). Fixing it
only for streams would make the two paths disagree about the same upstream
condition; fixing it for both is a money-classification change that deserves
its own reviewer. The reassembler carries the `error` through and lets the
existing code decide, exactly as the non-streamed shape does.

## Consequences

- **The `IncompleteRead` guard is now inert on the normal path** and the
  terminator check is what covers it. Stated rather than left to be discovered:
  the guard is kept because it still catches a proxy that buffers a stream into
  a `Content-Length` body, and
  `test_a_body_cut_short_of_its_content_length_is_never_served_as_an_answer`
  still proves it bites. That test is also what caught a real defect in this
  change: exiting the frame loop on `[DONE]` left the body generator suspended
  so the guard never ran. The loop now drains.
- **`openrouter_call_budget_seconds` is the only wall-clock brake left.**
  Keep-alive comments reset the per-`recv` timer; reproduced on loopback, a
  comment every 1.0 s under an 8.0 s socket timeout read to completion in
  **12.044 s** with the timeout never firing. ADR-0078 decided to keep the
  budget and this is why. **Do not lower `openrouter_timeout_seconds` toward
  the measured 0.478 s streamed gap** — it would cut healthy paid calls and
  turn them into charges with no receipts.
- **The population of issue #105's dataset changes.** A mid-generation failure
  that used to arrive as a 5xx `HTTPError` can now arrive in-band on a 200.
  Anyone settling #105 must not compare pre- and post-streaming records as one
  sample. `upstream_provider_stream_incomplete` is added to
  `telemetry_sink.BILLING_EVENTS` so the new failure mode reaches the durable
  file rather than repeating the omission corrected on 2026-08-26.
- **An accepted divergence:** a non-streamed `message.content` may be a LIST of
  parts, joined with `"\n"` by `_extract_message_content`. A stream has no way
  to express that, so such a message arrives as one run of characters.
- **Not fixed here, and not made worse:** `_extract_citations` reads a FLAT
  annotation (`annotation["url"]`), while OpenRouter documents a NESTED
  `url_citation` object. If that documentation is right the annotations path
  has been dead all along and the inline-markdown fallback is what produces
  sources today. This change carries annotations across faithfully in whatever
  shape they arrive; it does not claim to fix the shape. Settling it needs one
  live `:online` call, which is spend.
- **No money constant moves.** `SOFT_THRESHOLD_USD`, `HARD_LIMIT_USD`,
  `DAILY_CAP_USD` and `GLOBAL_DAILY_CEILING_USD` are untouched (ADR-0081), and
  so are every `max_tokens` cap and every timeout.
- **W15 closes with it:** the two dangling `_bound_sniff_time` references now
  name `_read_within_budget`, which is what actually bounds that read —
  verified by reading the call site, not by recalling it.
