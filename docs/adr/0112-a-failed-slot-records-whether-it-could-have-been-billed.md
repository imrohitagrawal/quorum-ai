# ADR-0112: A failed slot records whether it could have been billed

## Status

Accepted — 2026-09-12.

**Authorises nothing.** No `**Authorises:**` line; it may not be cited to
sanction a live-execution posture or a paid run.

**Changes no money.** Nothing prices anything from the field this adds. It is the
prerequisite ADR-0012 deferred, not the decision ADR-0012 declined to take.

## Context

Issue #105 asks whether treating every 5xx as possibly-billed rests on evidence.
ADR-0012 (2026-08-05) answered *not yet* and said so precisely: **"Do not change
the classification. `_UNBILLED_HTTP_STATUSES` is unchanged, and a `503` still
reads as possibly-billed … the honest input is a week of production logs, which
do not exist yet."** ADR-0031 then set the bar for ever changing it — per status
code, `n >= 30`, `router_refusal/n >= 0.95`, `provider_named == 0`.

Both are still right, and **the sample ADR-0031 needs was already being
collected.** `telemetry_sink.py` routes `upstream_provider_http_error` — which
has always carried `billing_class`, `status_code` and `provider_name_present` —
into a durable `telemetry-billing.jsonl` on the Fly volume, and
`scripts/telemetry_classification_report.py` already computes ADR-0031's
per-status verdict from it. An earlier draft of this ADR claimed the signal
"could not reach the code that would use it" and was "collectable in-process for
the first time". Both were false, and the second was the draft's central
justification.

**The narrower true claim is what this change is for: the verdict could not reach
the COST LAYER.** In `_live_openrouter_response`:

```python
if result is None or isinstance(result, _SearchRejected | _DispatchedUnmeasured):
    return None
```

Both verdicts collapsed into a single `None`, so `_failed_answer` recorded a slot
that produced nothing with no indication of whether it had cost money. The log
knew; the record did not. That is why #105's conservative posture books the whole
pre-run estimate for a run whose every slot failed.

**This field is NOT an input to ADR-0031's bar.** That bar is per status code, and
`InitialModelAnswer` carries no status code — only `error_code="PROVIDER_UNAVAILABLE"`.
The distribution ADR-0031 wants comes from the JSONL, as it already did. What the
slot record enables is a *cost* decision, and only that.

**A worse case was hiding inside the collapse.** A 200 with an invisible completion (the F-06 / #175 shape) also returned `None`
from this boundary — the one verdict meaning "provably not billed", on a call that
was dispatched.

## Decision

**Carry the verdict to the slot record, and price nothing from it.**

1. `_live_openrouter_response` returns `_DISPATCH_UNMEASURED` through instead of
   flattening it. `_SearchRejected` still collapses to `None` — it is a 400/404
   on the `:online` id, already an unbilled status, and the bare-id retry above
   it has already run.
2. The invisible-completion guard returns `_DISPATCH_UNMEASURED` rather than
   `None`. **This changes nothing about F-06's intent**: the caller still refuses
   to treat it as an answer and still does not flip `provider_attempt_order`,
   because only a real `LiveProviderResult` does that.
3. `produce_initial_answer` maps the outcome to a verdict and `_failed_answer`
   stamps `InitialModelAnswer.billing_class`.

**`BILLING_NOT_BILLED` / `BILLING_POSSIBLY_BILLED` are the strings the failure
logs already used**, promoted from log text to constants and reused at all seven
log sites so the vocabulary cannot drift between what is logged and what is
recorded.

**`None` on a slot that produced an answer.** The field asks "for a slot that
produced nothing, could it still have cost money?" — a question that does not
apply to a slot whose cost is already itemised from its captured usage. It is a
failed-slot discriminator, not a classification of every call. Mutation 07 is the
version that stamps it unconditionally.

## What this does NOT license

**It is not evidence for narrowing the classification.** ADR-0031's bar is a
distribution over ≥30 samples per status code, and #105's own measured evidence
is n=2 runs. This field is not that sample and cannot be: ADR-0031's bar is per status
code, and the slot record carries none.

**The triple is still weaker than the ledger.** The RCA for #105 named this
exactly: whether OpenRouter recorded a generation at all is knowable only from their
ledger (`docs/analysis/2026-09-10-window-measurements.md`).
The in-app signal remains *all slots failed AND zero usage captured AND zero
telemetry rows*, and this ADR adds a fourth, better term — **and none was
possibly-billed** — without claiming the conjunction is sufficient. Deciding
that is a separate ADR with a real distribution behind it.

**It does not restate historical receipts.** Past runs carry no verdict, so any
future analysis must treat their absence as unknown rather than as `not_billed`.

## Rejected alternatives

- **Derive the verdict in the cost layer from the HTTP status.** Impossible: the
  status is discarded before any cost code runs, which is the defect. Deriving it
  downstream would mean re-plumbing the status instead of the conclusion, and the
  conclusion is what the classification already encodes.
- **Widen `_UNBILLED_HTTP_STATUSES` now.** Rejected: that is precisely the
  decision ADR-0012 declined on the evidence and ADR-0031 set a bar for. Doing it
  here would use a plumbing change as cover for a money decision.
- **Book failed runs at $0 on the strength of this field.** Rejected as
  fail-open on a money rail. `test_a_reconciliation_with_no_measured_figure_leaves_the_estimate_standing`
  exists because an earlier revision defaulted a missing figure to zero, and its
  docstring calls that "free money".
- **~~Make the field a strict enum. Deferred.~~** TAKEN, after review refuted the
  deferral in one grep: `cost_source: Literal["estimated", "measured"]` already
  ships on a serialised money field in this same `openapi.yaml`, rendering as
  `type: string` + `enum` with nothing extra to decide. The draft's `str` accepted
  `"definitely_billed_lol"` and served it. The field is now
  `Literal["not_billed", "possibly_billed"] | None`.
- **Record the verdict on completed answers too.** Rejected; see "None on a slot
  that produced an answer".

## Consequences

- `InitialModelAnswer.billing_class` crosses the API boundary as an additive
  optional string defaulting to `null` (`openapi.yaml`, +8 lines). No consumer
  reads it.
- A dispatched-but-unusable slot now reports `possibly_billed` where it used to
  be indistinguishable from a refusal. **No run changes `cost_source`**: the
  honesty gate keys on `status is COMPLETED` and `token_usage is not None`, both
  untouched, so every run that was `estimated` still is.
- Two tests in `tests/unit/test_provider_stubs.py` asserted the old collapse at
  this boundary, one with a docstring calling it "the observable contract". Both
  are updated to assert the sentinel and to say why the contract moved — the
  thing they were protecting was the flattening itself.
- The seven log sites now reference constants. Identical values, so any test
  asserting on logged text is unaffected.

### Added after review

Three lenses reviewed the first version. The code was right on the boundary and
wrong at the edges, and one claim was load-bearing and false:

- **Two of the three failed-slot constructors recorded no verdict.**
  `cancelled_answer` and `deadline_exceeded_answer` build FAILED slots directly,
  so both defaulted to `None` — the value this ADR reserved for "produced an
  answer". A reviewer demonstrated a run end to end where two deadline-cut slots
  had POSTed, were still generating, and were indistinguishable in this field
  from the two slots that answered. **That is the field-drift footgun those
  constructors' own docstrings warn about, fired in the file that documents it.**
  Cancelled is now `not_billed` (its call site checks `_should_stop` before
  dispatch); deadline-cut is `possibly_billed` (its call site says the cut future
  "keeps running on its pool thread … its late answer is simply never recorded").
- **`_failed_answer`'s `billing_class` had a default**, and the default was the
  money-understating value. It is now required: a caller who forgets it gets a
  type error, not a silent `not_billed`.
- **One assignment was provably dead**, kept alive by a comment this same change
  had made false. The comment said it covered the F-06 empty-text shape; that
  shape is now routed to `_DispatchedUnmeasured` one frame earlier.
- **Narrowing the success branch by `isinstance(LiveProviderResult)` breaks a
  duck-typed test double** (`_FakeLiveResult`), silently routing it down the
  failure path — measured, three tests red. The branch narrows by EXCLUSION
  instead, and mutation 11 is that mistake.

**One verdict is unpinned, and that is recorded rather than hidden.** The
CANCELLED slot's verdict has no observable surface: a cancelled slot is not
recorded in `initial_answers` at all — measured, after the real cancel path runs
no slot carries `error_code == "CANCELLED"` there — so nothing can read it back.
It is set at the call site for correctness and symmetry, it has no mutation, and
adding one would be unkillable. DEBT-016 carries it. The sibling deadline verdict
IS pinned at its call site, and that is the one where a wrong value would be a
false money claim.

## How this is proven

`scripts/proofs/failed_slot_billing_verdict_mutations.py` — **11 mutations, all
KILLED** against a green 89-test baseline, every restore byte-identical with
`diff -q` from a `cp` copy, never `git checkout`, re-run after `make format`.

The verdict is pinned in **both directions by one table**: three outcomes the classification treats as preceding generation (401, 402,
429) plus one that provably never dispatched (connection refused) and four that
provably follow dispatch (500, 503, read timeout, torn body). A single-direction
test would pass against an implementation that hardcoded either constant —
mutations 02 and 03 are those two implementations, and each dies on the half of
the table it contradicts. Mutations 08-11 are the four review findings above.

The retry chain is also pinned now: a searching slot can POST twice, and an
unbilled 404 followed by a dispatched 500 must record `possibly_billed`. Every
other test in the file drives `search=False`, so the production default
(`ModelSlot.search` is True) had gone untested.

Mutation 04 is the important one: the invisible-completion path reporting
`not_billed`. It is the only failure mode where money provably moved, so
asserting the unbilled verdict there would be worse than the flattening this ADR
removes — a falsehood rather than a refusal to answer.
