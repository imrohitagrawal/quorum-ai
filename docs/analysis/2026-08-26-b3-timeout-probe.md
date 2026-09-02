# B3 timeout probe — raw results, 2026-08-26

**10 paid OpenRouter calls, all successful, against an authorised ceiling of 10.**
Standalone script: no app run, no `/ui` request, no deploy, no config change,
`OPENROUTER_LIVE_EXECUTION_ENABLED` untouched throughout. Method: `urllib` with
`read1(65536)` in a loop, timestamping every chunk, so the reported gap is true
socket-arrival cadence rather than an artefact of a large blocking read.

Decisions taken from these numbers are in ADR-0078. This file is the evidence,
not the argument.

## A. The synthesis leg — `openai/gpt-5-mini`, NON-streamed, `max_tokens=3000`, n=6

The cap synthesis actually uses, and 1.5x anything the earlier spike probed.

| # | wall (s) | ttfb (s) | max gap (s) | chunks | finish | completion tokens |
|---|---|---|---|---|---|---|
| 1 | 25.072 | 1.050 | 0.572 | 64 | stop | 2427 |
| 2 | 28.260 | 0.950 | 0.601 | 73 | stop | 2894 |
| 3 | 29.027 | 1.153 | 0.643 | 74 | stop | 2653 |
| 4 | 30.778 | 1.748 | 0.631 | 78 | stop | 2819 |
| 5 | 30.947 | 0.909 | 0.624 | 79 | length | 3000 |
| 6 | 40.170 | 0.848 | 0.621 | 98 | stop | 2753 |

- wall: min **25.072**, median **30.778**, max **40.170**
- max inter-chunk gap: min **0.572**, max **0.643**
- against `openrouter_timeout_seconds = 8.0`: **6 of 6 exceed on wall clock, 0 of 6 on the per-recv gap**

This model DRIBBLES: 64-98 chunks, every gap an order of magnitude under the
cap. The 8s timeout could not have fired on any of the six. The four default
ANSWER models buffer instead, and were measured at 5.7-25.1s gaps. Both
behaviours are real on the same endpoint through the same client, which is why
ADR-0078 treats the per-recv bite as a property of the MODEL.

## B. Streamed cadence, `max_tokens=3000`

| model | wall (s) | max gap (s) | median gap (s) | frames | keep-alive frames | completion tokens |
|---|---|---|---|---|---|---|
| `openai/gpt-5-mini` | 26.440 | 0.417 | 0.0000 | 4194 | 16 | 2594 |
| `openai/gpt-5-mini` | 30.161 | 0.420 | 0.0000 | 4908 | 16 | 2943 |
| `openai/gpt-4o-mini` | 16.305 | 0.478 | 0.0000 | 1736 | 21 | 845 |
| `openai/gpt-4o-mini` | 9.860 | 0.208 | 0.0000 | 1794 | 1 | 893 |

### The paired comparison that matters

Same model, same endpoint, non-streamed versus streamed:

| `openai/gpt-4o-mini` | max inter-chunk gap |
|---|---|
| non-streamed (2026-08-26 spike, `max_tokens=2000`) | **22.440 / 25.055 s** |
| streamed (this probe, `max_tokens=3000`) | **0.478 / 0.208 s** |

Roughly two orders of magnitude. This is the strongest evidence available for
building the streaming transport, and it is a PAIRED sample rather than two
unrelated numbers.

### What this settles, and what it does not

- **Settled:** streaming collapses the inter-chunk gap; keep-alive comment
  frames exist and are counted below.
- **SETTLED BY MEASUREMENT 2026-08-31.** See the block at the end of this file:
  24 of 24 live production calls reported `usage_absent: false` and
  `stream_terminator: "done"`. What follows is the correction that stood
  between 2026-08-30 and that measurement, kept because the reasoning is the
  point: that `usage` arrives in the final chunk of a stream with **no opt-in**
  required was **ASSUMED, not measured**. It came from OpenRouter's streaming
  documentation, read 2026-08-26; no probe row here records it, and this
  script was not retained, so the raw frames cannot be re-read to check. The
  completion-token counts in the streamed table above are consistent with a
  usage object having been seen, but that is an inference, not a record. The
  claim is load-bearing — if it is wrong, every streamed run's receipt falls
  back to `estimated` — so it is marked rather than repaired. ADR-0084 designs
  for it being wrong (absent usage is reported absent, never fabricated) and
  adds `stream_terminator` to the token telemetry so production traffic settles
  it at no cost.
- **NOT settled: the keep-alive CADENCE.** Counts of 1, 16, 16 and 21 per call,
  with no regular spacing recorded. Any figure quoting a fixed interval is
  unsupported by this probe.
- **NOT settled: a p95 for anything.** n=6 on one model and n=2 on two models
  give maxima, not tails.
- **NOT probed at all:** the judge leg (still assumed at ~5s), the debate
  moderator model, and the Tavily search leg.

### A correction to an inherited number

The approved plan and the 2026-08-26 session handoff both state "8 of 8 exceed
it on wall clock". Against their own table it is **7 of 8** — 6.385s does not
exceed 8.0. The per-recv figure they give, 6 of 8, is correct, and that is the
number that decides anything.


---

# MEASURED, 2026-08-31 — the live window that settled it

Two production runs on build `2d94f6c`, 04:52Z and 04:56Z, inside the declared
window `2026-08-31T04:05Z-05:45Z` (owner `imrohitagrawal`, judge on). Read off
`/data/telemetry-tokens.jsonl` via `fly ssh console`, which is the only place
`stream_terminator` is written.

| Question | Verdict | Evidence |
|---|---|---|
| Does `usage` arrive with no `stream_options`? | **YES** | `usage_absent: false` on **24 of 24** calls |
| Is `data: [DONE]` sent? | **YES** | `stream_terminator: "done"` on **24 of 24** calls |
| Do all four default answer models honour `stream: true`? | **YES** | 8 of 8 `:online` slot calls completed live; `live_count` 4/4 and `local_count` 0 in both runs |

The 24 records span six distinct models — the four answer slots, the
debate/synthesis model (`openai/gpt-5-mini`) and the judge
(`openai/gpt-4.1-mini`) — so the result is not one vendor path generalised.

**The pre/post split works.** `stream_terminator` is absent from **0 of 30**
records written before the window and present on **all 24** after it, so the
two regimes cannot be silently mixed into one percentile. That was the reason
for adding the field, and it is now demonstrated rather than intended.

**`stream_options` is confirmed unnecessary** and stays off the wire. ADR-0084
rejected sending it partly on the argument that its failure mode was a silent
total outage; that argument no longer has to carry the decision, because the
premise it was hedging is now measured true.

## Unplanned: issue #268's missing measurement

The same records carry `injected_tokens_est` — provider-reported input tokens
minus what we sent — for the eight `:online` calls, which is exactly the figure
#268 was opened to obtain and had never had:

```
2173  2256  2267  2268  2344  2427  2504  2510
```

**8 of 8 exceed `cost_web_search_context_tokens = 2000`**, by 9-26%, across all
four default models. The constant was grounded on a single run (`d7785cd8`);
this is the first real distribution behind it. Under-estimating input is the
FAIL-OPEN direction, since the cost guardrail keys off the estimate.

**The constant is deliberately not moved here** — it is a money guardrail and
ADR-0081 freezes this class pending a measured bound. n=8 on one question shape
is a start, not a bound: every row shares one query, one prompt size and one
day. Recorded on #268 so the next person starts from data.

### SUPERSEDED as a sample size, 2026-09-01 — the shapes were varied

The "one question shape" limitation above was the explicit reason for a second
window (`ae9865f` open, `014b010` closed, ~54 minutes, **$0.1649** actual spend
over three runs). Three deliberately different shapes were run — broad
comparative, ambiguous low-signal, narrow factual — giving 12 more `:online`
calls:

```
-63  2353  2370  2449  2477  2500  2520  2570  2595  2668  2719  2890
```

**11 of 12 exceed 2000**, by up to 44% (max 2890). Pooled with the 20 `:online`
calls already in `/data/telemetry-tokens.jsonl`, the distribution is now
**n=32 across four question shapes, 27 over**, range -63 to 2890.

Two corrections to how the figure above was produced, both worth keeping:

- The headline "8 of 8" counted one window's slot calls, not the file. The file
  already held **20** `:online` readings at that point, of which 16 exceeded
  2000 — so "8 of 8" was a true statement about a subset presented as the
  sample.
- A negative `injected_tokens_est` is real (the provider reports FEWER input
  tokens than were sent) and an extraction using
  `grep -o '"injected_tokens_est": *[0-9][0-9]*'` **silently drops those rows**.
  Parse the JSON; do not pattern-match it. Rule 8 applies to analysis, not only
  to tests.

The constant STILL does not move. ADR-0081 freezes the class pending a measured
bound and W3 stays STOP; one day's traffic on four shapes is a better sample,
not yet a bound.
