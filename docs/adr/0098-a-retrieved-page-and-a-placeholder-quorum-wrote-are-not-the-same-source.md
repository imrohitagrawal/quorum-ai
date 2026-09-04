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
| "not the model's OWN citation" | `citation_coverage` numerator (`_completed_answer`'s `primary_source_count`) | yes |
| "a Quorum-authored `example.test` placeholder" | the UI stub badge (`isStubSource`, chip row) | **no** |
| "not a real source" | the Markdown export (`buildRunMarkdown`'s Sources block) | **no** |

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

The `if self._live_execution_enabled(...): return self._failed_answer(...)` guard
in `produce_initial_answer` returns a FAILED slot before the `use_fallback`
branch whenever live execution is on, and that branch's own comment says so
(*"with live execution ON this whole branch is unreachable"*). The reachable
site is the SUPPLEMENT — the `_tavily_search` call inside the
`live_response.answer_text` arm — which attaches search results to a
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

**3. All THREE source surfaces share one predicate, keyed on the provider path
rather than on `is_fallback`.** `isStubSource` is used by the chip row, the
Markdown export and the transcript model-card list. `local_simulation` and
`fallback_search` keep the stub badge and stay non-clickable; a `web_search`
source is a working link.

The predicate reads BOTH wire shapes (`isFallback` and `is_fallback`) on
purpose: the first two surfaces receive a camelCase projection and the third
receives the raw server object, so a single-casing predicate would silently
evaluate `undefined === true` on one surface and drop its fail-safe clause with
nothing failing. A review round caught exactly that as a latent trap.

**3a. A retrieved page is MARKED, not merely un-badged.** It carries a neutral
`web search` origin tag (chip and transcript) and `— via web search` in the
export. Without it, removing the false "not a real source" badge would have
replaced one contradiction with another: four retrieved chips rendering
identically to model-cited ones directly beneath a trust card that, by
Decision 2, still reads *"0 sources cited"*. Two independent reviewers
converged on this; the truthful middle is to say where the page came from and
claim nothing about who cited it.

**4. The prose stops claiming zero when sources are on screen — on BOTH paths.**
The `source_support` section distinguishes "no model cited its own sources" from
"there is no evidence here".

This needed two edits, not one, and the first draft shipped only the first.
`base` — the templated sentence — is used ONLY when the live synthesis call
returns nothing. With live execution on, which is the configuration the defect
was measured in, that section is written by the model from `directives`, which
said *"Source coverage: 0% … carried at least one primary source"* and nothing
about retrieved pages. A note naming the retrieved count and the
distinction is therefore added alongside the templated sentence, and the count
itself lives in ONE helper (`count_answers_with_retrieved_sources`) that both
consumers call, because two matchers built from one idea drift.

The note is scoped to the Source-support section (`_with_retrieved_note`), NOT
appended to the shared `directives` block. `_user_prompt` is built once and
handed to all five sections; a first attempt put the note there, and a reviewer
found it landing in the RECOMMENDATION prompt — beside the rule that steers
"pause for human review" when coverage is under 80%. The note ends "do not
describe the run as having no sources at all", which is not a sentence to place
next to a safety posture.

**5. `WEB_SEARCH` joins `NOT_INVOKED_PATHS`, not `INVOKED_PATHS`.** Unreachable
today, but it is the fail-safe reading: a web search returning a page is not a
model being asked a question, and the honest default is the one that does not
claim a model spoke.

## A decision reversed inside review, and why

**A `model_was_invoked` guard was added to the retrieved-count, then removed.**

A reviewer objected that with a Tavily key and live execution OFF, real
retrieved pages attach to a SIMULATED answer, so counting them credits a web
search for text no model produced. The guard was added. A later reviewer
measured what it did: the chip row and the transcript still rendered four
linked "web search" pages while the prose, now counting zero, said *"No model
returned visible source references for this query."* That is verbatim the
contradiction this ADR exists to remove, recreated by its own fix.

The objection was about the SENTENCE's subject, not the count. It said
"responding models", which is false of a simulated run. The sentence now says
"answers on this run" — true on both paths — so the count can describe exactly
what the surfaces render.

**The rule this yields, and the reason it is written down:** the count and the
three rendering surfaces are one decision, not four. Guarding one of them alone
makes prose and pixels disagree by construction. Two consecutive review rounds
produced defects here precisely because each finding was patched where it was
reported rather than at the shared decision.

## What is gated, and what deliberately is not

The three surfaces do not carry equal weight, and their gates should not either:

| Surface | User-visible? | Gate |
|---|---|---|
| Chip row | yes | blocking e2e (`source-expander.spec.ts`) |
| Markdown export | yes | blocking e2e, added this round |
| Transcript list (`renderSourceList`) | **no** | text pin only |

The transcript list writes into `#model-grid`, inside
`<section class="panel panel-section">`, which `app.css` hides unconditionally
with `display: none`. MEASURED in a real browser: `#model-grid` present,
`isVisible: false`, computed `display: none`; four `.source-list` elements, all
`isVisible: false`. A reviewer correctly reported that surface has no executing
gate; it is deliberately not given one, because an e2e test there would drive
markup no user can reach. `test_the_transcript_surface_is_pinned_by_text_because_nobody_can_see_it`
goes red if that panel is ever un-hidden, at which point it earns a real gate.

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
- **The run summary still says "Roughly N% of those answers carried at least one
  visible source reference."** This ADR quotes that sentence as *the*
  contradiction — the sources are visibly on screen — and does not change it.
  It sits in the consensus/divided summary builders, not in `source_support`,
  and rewording a headline the verdict band leans on is a separate concern with
  its own blast radius. Recorded here rather than fixed quietly, because an ADR
  that names a falsehood and silently leaves it is worse than one that never
  named it.
- **The `<80%` coverage rule still fires.** Because Decision 2 deliberately
  freezes the arithmetic, `target_met` is still `False` on a run whose evidence
  was entirely retrieved, so `_RECOMMENDATION_PROMPT` rule 3 still steers the
  recommendation toward *"pause for human review"*. Measured byte-identical
  before and after this change. A reader of the commit could otherwise conclude
  that pressure was removed; it was not.
- **Whether retrieved evidence SHOULD raise the trust band.** Left open
  deliberately, for data from the live window rather than a blind decision.


- The judge still never sees page CONTENT — it receives `[i] title :: url` only
  (`evaluation.py:1729-1732`). The disclosure copy is corrected in this same PR;
  the underlying capability gap is not closed here.
- Citation coverage still measures only model-authored citations. A user wanting
  "is this backed by anything?" does not have a single number for it.
