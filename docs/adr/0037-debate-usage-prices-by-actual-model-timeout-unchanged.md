# ADR-0037: Debate usage prices by the model actually billed; the debate timeout stays 8.0s, unproven either way

## Status

Accepted — 2026-08-14

## Context

#290 is the peer-critique feature (each of the four answer models reads and
critiques the other three, instead of one fixed moderator model writing both
rounds). It was split into a scoped, mechanical prerequisite — this ADR — and
the behaviour change itself, which stays unbuilt.

**The billing bug.** `DebateResult.live_call_usages` (`src/product_app/debate.py`)
recorded each live debate call as `(round_number, TokenUsage)` — keyed by
round, never by model. The measured-cost path
(`query_run_orchestration._actual_cost`) priced every entry in that list at
`settings.debate_model_id`, unconditionally. Today that is harmless *by
accident*: `_call_debate_model` only ever dispatches
`settings.debate_model_id` (verified — `grep -n
"model_id=settings.debate_model_id" src/product_app/debate.py`, one call
site, and `_call_debate_model` takes no `model_id` parameter). The moment a
debate call dispatches a different model — which is exactly what peer
critique does — every one of its calls prices at the moderator's rate while
the receipt still reports `"measured"`.

**The timeout question.** `openrouter_timeout_seconds` is 8.0s
(`src/product_app/config.py:85`), and debate calls already run at
`DEBATE_ROUND_MAX_TOKENS = 2000` (`src/product_app/debate.py:66`) — the same
cap the issue's math applies to a hypothetical peer-critique call. A paid
probe (one call per slot model, trivial prompt, authorized separately from
this PR) measured:

| model | prompt tokens | completion tokens | latency |
|---|---:|---:|---:|
| `openai/gpt-4o-mini` | 18 | 8 | 2574 ms |
| `anthropic/claude-haiku-4.5` | 18 | 10 | 2264 ms |
| `google/gemini-2.5-flash` | 11 | 7 | 1294 ms |

All three returned HTTP 200 well inside the 8.0s budget. The probe's own
recommendation says why that is not the answer to the timeout question: with
completions of 7-10 tokens, the elapsed time is round-trip and TTFB (connect,
TLS, queue, first token), not sustained generation throughput. It does not
measure — and was not designed to measure — how long a real
`DEBATE_ROUND_MAX_TOKENS`-length (2000-token) completion takes.

## Decision

**1. `TokenUsage` gains an optional `model_id: str | None = None` field**
(`src/product_app/providers.py`). `DebateOrchestrationService._call_debate_model`
stamps it with the model actually dispatched, at the one seam that knows
both the request and the response. `_actual_cost` now prices each debate
usage record at `debate_usage.model_id or settings.debate_model_id` — the
`or` falls back to today's behaviour for the (currently nonexistent) case of
a record with no stamp, so nothing already in flight or persisted changes
shape.

**Rejected alternative: widen the `live_call_usages` tuple to
`(round, model_id, usage)`.** This is the shape the full peer-critique
design notes describe. Rejected for THIS PR because of blast radius, not
because it is wrong: 13 test files, 101 lines, assert against the current
`(int, TokenUsage | None)` tuple shape across unit and integration suites
(measured — `grep -rln "live_call_usages\|debate_call_usages" tests/ | wc -l`
→ 13; `grep -rn ... | wc -l` → 101). Carrying the model on the usage record itself — which is
also literally what the issue's own design notes ask for ("It needs a usage
record carrying `model_id`") — gets the same fix with a default-`None` field
addition instead of a tuple-shape migration touching every existing
call-site assertion. The tuple shape is free to widen later, when peer
critique's own PR needs `_call_debate_model` to take a required `model_id`
parameter and there is a real multi-model case to test against.

**2. `openrouter_timeout_seconds` (and the debate call path specifically)
stays unchanged at 8.0s in this PR.** The probe found no evidence of a
timeout risk — but by its own admission it did not measure the case that
matters (a full-length completion), so "no evidence" is not "sized to be
enough." Raising the number now, from data that does not speak to what
determines whether 2000 tokens fit in the budget, is exactly the kind of
guess rule 8c exists to forbid (a mitigation whose correctness depends on an
upstream behaviour nobody measured). **Not changing the number is therefore
also not a claim that 8.0s is proven sufficient** — it is a refusal to move
a money/reliability constant on data that admits it doesn't cover the
question.

## Consequences

- A run whose debate calls dispatch more than one model (peer critique, once
  built) will price each call correctly instead of uniformly at the
  moderator rate, without any further billing-layer change.
- The debate-specific worst-case-latency question — does a real
  `DEBATE_ROUND_MAX_TOKENS`-length completion fit in 8.0s — remains
  UNMEASURED. It blocks peer critique (which turns one such call per run
  into up to eight) more than it blocks today's single-moderator-call path,
  but the single-call path carries the same unmeasured risk today, described
  and left open by the same issue. The next probe needed to close this is
  exactly the one the original probe recommended: one call per slot model
  forced to generate close to the 2000-token cap, elapsed time measured,
  separately authorized (it costs real money at a much higher completion
  count than the trivial probe this ADR cites).
- `TokenUsage.model_id` is optional and additive; every existing constructor
  call across the codebase and test suite is unaffected. A `TokenUsage`
  built before this change (or by a caller that never learns which model it
  called, e.g. `_extract_usage`, which only sees the response body) is
  `model_id=None` and prices at the existing fallback.

## References

- Issue #290 (peer critique; this ADR closes its billing-and-timeout
  prerequisite, not the feature itself)
- ADR-0032 (the copy-vs-mechanism correction that split #290 out)
- `src/product_app/debate.py::DebateOrchestrationService._call_debate_model`
- `src/product_app/query_run_orchestration.py::_actual_cost`
- `tests/unit/test_actual_cost_source.py::test_debate_usage_is_priced_by_its_own_model_not_the_moderator_rate`
