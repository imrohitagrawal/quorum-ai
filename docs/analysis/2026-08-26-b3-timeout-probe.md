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
  frames exist and are counted below; `usage` arrives in the final chunk of a
  stream with **no opt-in** required (OpenRouter streaming documentation, read
  2026-08-26) — the open question that could have made streaming break the
  cost ledger.
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
