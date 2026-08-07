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
had no issue for it, so "tracked separately" tracked nothing for four days.

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

### Why these values, and what they are NOT

**They are not measured from production traffic, and nothing in this repository
retains the data that would measure them.** Verified, not assumed:
`run_history_store`'s `runs` table has no per-source or per-token columns and is
empty locally; `providers.py` emits no info/warning logs at all; the Fly log
ring held 100 lines with no `cost_estimate_accuracy` entry. Setting a guardrail
value from an unmeasured number is exactly what this repo forbids.

So the values are instead chosen to **strictly dominate the bound this codebase
already enforces in production on the other search path** — which makes the
change provably unable to drop a citation a live run currently shows the judge:

| Axis | Already enforced (Tavily) | Chosen | Dominates? |
|---|---|---|---|
| Lines | 4 slots × 5 = 20 | 32 | yes, 32 > 20 |
| Title | 300 | 300 | yes, equal |
| URL | unbounded | 300 | n/a — new floor |

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
run that then bills more." Users see a slightly higher "up to $Y", and the
$0.25 and $5/24h rails trip marginally earlier, in exchange for the figure
covering an input it previously ignored entirely.

## Alternatives rejected

**Cap the count only, leave the fields whole.** Rejected: an unbounded title is
an unbounded reserve, so the price term could not be derived and the cap would
remain dishonest. One 5000-character title defeats it.

**Bound at `_extract_citations` instead**, i.e. at the provider boundary.
Rejected: those `SourceReference`s also feed the UI and the citation-coverage
metric, whose denominator is answers-with-a-primary-source. Truncating there
could move a user-visible number and break a displayed link. `source_lines` was
verified to feed **only** the judge prompt — `grep -rn source_lines src/` shows
four sites, all inside `evaluation.py` — so bounding there is provably
side-effect-free.

**Mirror Tavily exactly (5 per answer).** Rejected: it would drop citations the
`:online` path legitimately returns beyond the fifth, degrading judge grounding
to buy a tighter bound nobody needs. The bound exists to cap the tail, not to
shape normal operation.

**Set the caps from real traffic.** Rejected as currently impossible, per the
retention findings above. Recorded as a known gap rather than faked.

## Consequences

- The judge's input is bounded on every path, and the bound is priced.
- `max_cost_usd` remains **not** an unqualified true ceiling, for one unrelated
  reason that predates this ADR: a judge model absent from the catalog is
  reserved at the default per-1k rate, which under-reserves for 102 of the 335
  live catalog models (ADR-0017, Decision 4). The `costs.py` comment now says
  exactly that instead of naming the source block.
- A run whose provider returns more than 32 citations shows the judge the first
  32. No user-facing surface changes: the UI, the citation-coverage metric and
  the trust score read the `SourceReference`s, not `source_lines`.
- The `app.js` hedge stays, now resting only on `cost_system_prompt_tokens` and
  `cost_web_search_context_tokens` — the half of #268 that remains open and is
  blocked on telemetry that does not exist.
