# ADR-0098: A retrieved page and a placeholder Quorum wrote are not the same source

## Status

Accepted — 2026-09-04.

Narrows the PRESENTATION half of the `is_fallback` flag introduced in #247 and
reused by #31/#32. It overturns no earlier decision — the coverage arithmetic
that flag governs is deliberately left exactly as it was, for the reasons in
Decision 2 below.

(The status line above deliberately avoids the words "supersedes"/"replaced by".
`scripts/live_posture_check.py:_ADR_REVOKED_MARKERS` matches them on word
boundaries in the `## Status` line and would read this record as no longer
standing. Found by `test_only_the_three_genuinely_revoked_adrs_in_this_tree_are_refused`
going red on a first draft that said "Supersedes nothing".)

## Context

`is_fallback` was one boolean carrying three different meanings:

| Meaning read off the flag | Read by | Correct for a Tavily result? |
|---|---|---|
| "not the model's OWN citation" | `citation_coverage` numerator (`providers.py:759`) | yes |
| "a Quorum-authored `example.test` placeholder" | the UI stub badge (`app.js:3323`) | **no** |
| "not a real source" | the Markdown export (`app.js:3097-3098`) | **no** |

Two source shapes were byte-identical on the wire — `provider="fallback_search"`,
`is_fallback=true`:

- a page a REAL web search (Tavily) returned, and
- the `example.test` placeholder this product writes for itself when no search
  key is configured. `example.test` is IANA-reserved and resolves to nothing.

So the UI could not tell them apart even in principle.

### What the user actually saw — measured, not inferred

Probe: four live answers, none carrying inline citations, Tavily returning four
real pages. Driven through `produce_initial_answer`; output verbatim:

```
slot 1..4 sources : [('https://www.reuters.com/article-N', is_fallback=True)]
DEBATE prompt contains 'reuters.com': True
citation coverage : answer_count=4 sourced_answer_count=0 ratio=0.00 target_met=False
source_support    : "No model returned visible source references for this query."
summary           : "Roughly 0% of those answers carried at least one visible
                     source reference."
```

Four real sources were rendered on the page as chips at that moment — badged
`"fallback stub"`, non-clickable, exported as `"fallback stub, not a real
source"` — while the prose said there were none. The word *visible* is the
contradiction: they were visibly on screen.

It also had a downstream cost. `target_met=False` (0.00 < 0.80) fires
`_RECOMMENDATION_PROMPT` rule 3 (`synthesis.py:276-278`), which instructs the
synthesiser to *"recommend pausing for human review before any action"*. Runs
where real evidence WAS retrieved were made more likely to tell the user to stop.

### A premise this ADR had to correct first

The handoff that raised this asserted the reachable path was
`_fallback_sources` -> `_tavily_search`, and said not to re-ask. It is not.
Measured with a call-counting probe, live execution ON:

```
_fallback_sources: called 0x      _tavily_search: called 1x
provider_path    : openrouter_search      fallback_used: False
```

The guard at `providers.py:642` returns a FAILED slot before the fallback branch
whenever live execution is on, and the comment at `:672` says so. The reachable
site is the SUPPLEMENT at `providers.py:589`, which attaches search results to a
GENUINELY LIVE answer. That makes the defect worse than reported, not better:
it lands on real model answers, not demo ones.

## Decision

**1. A really-retrieved page gets its own provider path: `ProviderPath.WEB_SEARCH`.**
It is a SOURCE path only — no answer is ever stamped with it — so every
"was this slot simulated?" check that reads `answer.provider_path` is unaffected.
It does NOT mean the page was fetched or read: nothing in `src/` resolves a cited
URL. A search engine reported the page exists.

**2. `is_fallback` keeps its documented meaning and the coverage arithmetic does
NOT move.** A retrieved page is still not the model's own citation, still
`is_fallback=True`, and still does not raise `citation_coverage`. The verdict
band is therefore unchanged by this ADR, and no re-measurement is required.

**3. The UI and the export key off the provider path, not off `is_fallback`.**
A `web_search` source is clickable and labelled honestly. `local_simulation` and
`fallback_search` keep the stub badge and stay non-clickable.

**4. The prose stops claiming zero when sources are on screen.** The
`source_support` section distinguishes "no model cited its own sources" from
"there is no evidence here".

**5. `WEB_SEARCH` joins `NOT_INVOKED_PATHS`, not `INVOKED_PATHS`.** Unreachable
today, but it is the fail-safe reading: a web search returning a page is not a
model being asked a question, and the honest default is the one that does not
claim a model spoke.

## Rejected alternatives

- **Count retrieved sources toward `citation_coverage`.** Rejected: it silently
  moves the number the trust band leans on, and it conflates "the model showed
  its work" with "this claim is backed" — two different signals that the product
  should report separately. Whether retrieved evidence *should* raise the band is
  a real question, but it deserves data from the open live window, not a blind
  decision. Recorded as open, deliberately.
- **Flip `is_fallback` to `False` for Tavily results.** Rejected: that IS the
  change that moves coverage, by the back door, and it breaks the flag's
  documented meaning that two other consumers rely on.
- **Fix only the copy.** Rejected: impossible. Both shapes are identical on the
  wire, so no wording can distinguish them without a discriminator.
- **Reuse `provider="fallback_search"` plus a new boolean.** Rejected as a second
  flag meaning almost the same thing as the first — the overload that caused this
  defect. The enum already exists to carry exactly this distinction.

## Consequences

- The wire gains an enum member. `openapi.yaml` and the exhaustive enum pin
  (`tests/unit/test_enum_membership_pins.py`) are updated in this PR.
- Tests that pinned the OLD classification are inverted in the same commit, each
  with a positive partner proving the other shape still reads correctly.
- Still true after this change, and deliberately so: **no cited URL is ever
  resolved.** A `web_search` source means a search engine returned it, not that
  Quorum read it. ADR-0098 does not make the product L2.

## What this does NOT fix

- The judge still never sees page CONTENT — it receives `[i] title :: url` only
  (`evaluation.py:1729-1732`). The disclosure copy is corrected in this same PR;
  the underlying capability gap is not closed here.
- Citation coverage still measures only model-authored citations. A user wanting
  "is this backed by anything?" does not have a single number for it.
