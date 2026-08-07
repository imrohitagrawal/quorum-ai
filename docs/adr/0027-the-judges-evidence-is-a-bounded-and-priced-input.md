# ADR-0027: The judge's evidence is a bounded and priced input

## Status

Accepted — 2026-08-07 (issue #268, the half the issue body does not name).

Completes [ADR-0017](0017-the-spend-cap-prices-every-billable-call.md), which
made the spend cap price the judge *call* but left the judge's *input* unbounded
and unreserved. Depends on the same operator decision ADR-0017 records: the
Layer-B judge will be **permanently ON** in production.

## Context

`max_cost_usd` is the figure the user approves and the figure the guardrail
gates on (ADR-0016: "a cap means its number"). ADR-0017 added a judge term to
it, reserving for four inputs — the answers, the synthesis sections, the judge
system prompt, and the query — each from a cap this codebase enforces.

A fifth input was neither bounded nor reserved: `JudgeEvidence.source_lines`.

`costs.py` said so itself, in a comment ending *"Tracked separately — do NOT
restore the 'true ceiling' wording until `build_judge_evidence` bounds its
source lines."* Nothing tracked it. `gh issue list --state open` on 2026-08-07
had no issue for it, so "tracked separately" tracked nothing. The comment was
added by `4ba4147` (#269) and is removed by this commit.

**The two search paths were not bounded alike.** Measured on `b904ce6`:

| Path | Count cap | Title cap | URL cap |
|---|---|---|---|
| Tavily (`_parse_tavily_results`) | `tavily_max_results` = 5 per answer | `_MAX_SOURCE_TITLE_LEN` = 300 | none |
| OpenRouter `:online` (`_extract_citations`) | **none** | **none** | **none** |

`_sanitize_source_url` strips fragments and applies a host denylist; it bounds
length not at all. So on the `:online` path — the default, since every slot
ships `search: bool = True` — the judge prompt grew with whatever a provider
chose to emit.

### Measured on `b904ce6`, hermetic, $0

Driving `build_judge_evidence` + `build_judge_prompt` with 4 answers × 25
citations, each a 5000-character title and a 5000-character URL:

```
user prompt sent to the paid judge call: 1,003,263 characters
```

That is **250,816 input tokens** at the repo's 4-chars-per-token model. Priced
at the fallback rate a judge model absent from the catalog gets
($0.001/1k), the input of that single call costs **$0.2508** — which is,
to the cent, the entire `hard_limit_usd = 0.25` per-account rail it is supposed
to be metered against. The approved cap reserved **$0** of it.

This is the tail, not normal traffic. It needs no attacker: a provider that
returns verbose citation titles produces it.

## Decision

**1. `build_judge_evidence` caps the source block on three axes.**

```python
JUDGE_MAX_SOURCE_LINES = 32
JUDGE_MAX_SOURCE_TITLE_LEN = 300
JUDGE_MAX_SOURCE_URL_LEN = 300
```

Fields are truncated *before* formatting and numbered *after* the count cap, so
the ordinals stay contiguous — a hole would point the prose's `[7]` at a line
that is not in the list.

**2. `costs.py` reserves exactly that block**, derived from those three
constants rather than chosen independently:

```
32 lines × (300 title + 300 url + 10 scaffolding) / 4 chars-per-token = 4,880 tokens
```

Deriving rather than restating is the point: raising a cap raises the reserve in
the same edit, so the bound and its price cannot drift apart.

**3. When the count cap binds, the budget is spent round-robin across the four
answers, not first-come.** This was added after review. The first
implementation took a flat `[:32]` over the concatenated sources, which spends
the whole budget on the earliest slots: at 12 citations each, slots 1-2 keep all
12, slot 3 keeps 8, and **slot 4 keeps none** — while `MODEL_ANSWER_4` is still
in the prompt and still scored for `grounding` ("do the answer's citation
markers point at the listed sources?"). That marks a model down for citations
the judge was never shown. Round-robin gives each answer an equal share, and a
slot with fewer sources than its share does not waste the remainder — the
leftover flows to slots that still have sources.

Below the cap this is a no-op. Measured over 400 random slot/citation shapes,
391 of them at or under the cap: **0 differed** from `origin/main`, order
included.

### Why these values, and what they are NOT

**They are not measured from production traffic, and nothing in this repository
retains the data that would measure them.** Verified, not assumed:
`run_history_store`'s `runs` table has no per-source or per-token columns and is
empty locally; `providers.py` logs only on failure paths — four WARNING/ERROR
records (`grep -nE "_LOGGER\.(info|debug|error|warning|exception|log)"
src/product_app/providers.py` → lines 1228, 1264, 1568, 1893), none carrying a
per-source or per-token field; the Fly log
ring held 100 lines with no `cost_estimate_accuracy` entry. Setting a guardrail
value from an unmeasured number is exactly what this repo forbids.

So the values are instead chosen to **strictly dominate the only count bound
this codebase already enforces** — the Tavily path's:

| Axis | Already enforced (Tavily) | Chosen | Dominates? |
|---|---|---|---|
| Lines | 4 slots × 5 = 20 | 32 | yes, 32 > 20 |
| Title | 300 | 300 | yes, equal |
| URL | unbounded | 300 | no — a new floor |

**That argument covers the Tavily path only, and an earlier draft of this ADR
over-claimed from it.** It said the caps were "provably unable to drop a
citation a live run currently shows the judge". That is false, and this ADR's
own Consequences section contradicted it two screens later. The DEFAULT path is
OpenRouter `:online` (every slot ships `search=True`), and it has no upstream
count cap at all — so a run whose four answers return more than 32 citations
between them **does** now show the judge fewer sources than it would have
before. That is the deliberate trade: a bounded, priced prompt in exchange for
the tail of a list nobody bounded. A Tavily URL longer than 300 characters is
likewise newly truncated.

What is true, stated narrowly: **no source line the Tavily path can produce is
dropped** (its worst case is 20 lines of ≤300-char titles, all of which fit),
and below 32 total sources the output is byte-identical to the previous
behaviour — measured over 400 random slot/citation shapes, 391 at or under the
cap, **0 differing** from `origin/main`, order included.

The slot count is not a guess: `model_slots` enforces *"Exactly four model slots
are required."* The caps are literals rather than reads of `tavily_max_results`,
because that is an env-overridable knob and this repo has twice rejected keying
a bound off a runtime-tunable value.

### Effect on the approved figure

Measured under pytest's 12-entry fallback catalog, four `vendor/model-N` slots,
the 33-character reference query:

| | Before | After | Change |
|---|---|---|---|
| Judge term | $0.0285 | $0.0334 | +17.2% |
| `max_cost_usd` (judge ON) | $0.1349 | $0.1398 | +3.6% |
| `max_cost_usd` (judge OFF) | $0.1064 | $0.1064 | unchanged |

The cap goes **up**. That is the intended direction: `_estimate_bound_usd` is
documented as a figure that "can only ever over-protect, never wave through a
run that then bills more." Users see a slightly higher "up to $Y", in exchange
for the figure covering an input it previously ignored entirely.

**Only one money rail reads the bound**, and an earlier draft of this ADR named
two that do not. The point estimate is untouched by this change — every line of
it sits inside `if price_judge:`, which only `_estimate_bound_usd` sets — so:

| Rail | Reads | Moved by this change? |
|---|---|---|
| per-call confirm/block band (`costs.py:638`) | the **bound** | yes, marginally |
| cumulative per-account guard (`costs.py:664`) | `estimated` | no |
| $0.20 per-account daily cap (`costs.py:822`) | `estimated` + ledger | no |
| $5/24h global ceiling (`costs.py:861`) | recorded ledger only | no |

The $5/24h ceiling in fact accumulates *slower* after this change, not faster:
it meters reconciled actuals, and truncating the source block shrinks the real
judge prompt on verbose-annotation runs.

## Alternatives rejected

**Cap the count only, leave the fields whole.** Rejected: an unbounded title is
an unbounded reserve, so the price term could not be derived and the cap would
remain dishonest. One 5000-character title defeats it.

**Bound at `_extract_citations` instead**, i.e. at the provider boundary.
Rejected: those `SourceReference`s also feed the UI and the citation-coverage
metric, whose denominator is answers-with-a-primary-source. Truncating there
could move a user-visible number and break a displayed link. `source_lines` was
verified to feed **only** the judge prompt: `grep -rn source_lines src/` prints
seven hits in three files on this branch — four code sites, all inside
`evaluation.py`, plus three comments that merely name it (`costs.py`,
`static/app.js`, and one more in `evaluation.py`) — so bounding there touches no
user-facing surface.

**Mirror Tavily exactly (5 per answer).** Rejected: it would drop citations the
`:online` path legitimately returns beyond the fifth, degrading judge grounding
to buy a tighter bound nobody needs. The bound exists to cap the tail, not to
shape normal operation.

**Set the caps from real traffic.** Rejected as currently impossible, per the
retention findings above. Recorded as a known gap rather than faked.

## Consequences

- The judge's **source block** is bounded on both search paths, and priced. The
  other four inputs keep the bounds they already had: the query by
  `_QUERY_TEXT_MAX_LENGTH`, the synthesis sections by `SYNTHESIS_SECTION_MAX_TOKENS`,
  the system prompt by being a constant, and the answers by
  `initial_answer_max_tokens` on the call that produced them. Note that last one
  is a bound on the GENERATING call, not a clamp at the prompt: `debate.py` and
  `synthesis.py` both defensively clamp `answer_text` at 8000 chars and
  `build_judge_evidence` does not. Not changed here — out of scope, and named so
  the next reader does not have to rediscover it.
- `max_cost_usd` remains **not** an unqualified true ceiling, for two reasons,
  neither introduced here: a judge model absent from the catalog is reserved at
  the default per-1k rate, which under-reserves for 102 of the 335 live catalog
  models (ADR-0017, Decision 4); and `build_judge_prompt`'s own scaffolding —
  the two delimiters, `QUESTION: `, `SOURCES:`, the `MODEL_ANSWER_N:` and
  `SYNTHESIS_X:` headers and the blank lines — has no reserve term. Measured by
  building a prompt with every field empty: **290 chars** at four slots (≈73
  tokens, $0.00007 at the fallback rate), +18 per extra slot.
- A run whose four answers return more than 32 citations between them shows the
  judge 32, allocated **round-robin across the slots** so no slot is silently
  unrepresented — a flat first-32 slice would have evicted slot 4 entirely while
  `MODEL_ANSWER_4` stayed in the prompt and stayed scored for grounding. Below
  32 the output is byte-identical to before, order included.
- No user-facing surface changes: the UI, the citation-coverage metric and the
  trust score read the `SourceReference`s, not `source_lines`.
- The `app.js` hedge stays, now resting only on `cost_system_prompt_tokens` and
  `cost_web_search_context_tokens` — the half of #268 that remains open and is
  blocked on telemetry that does not exist.
