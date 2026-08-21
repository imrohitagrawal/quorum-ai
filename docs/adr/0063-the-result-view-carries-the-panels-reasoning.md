# ADR-0063: The result view carries the panel's reasoning; the inferred position table goes

## Status

Accepted — 2026-08-22

## Context

An operator looked at a completed run and could not tell what the debate rounds
or the synthesis were telling them. The content was not missing. It was in the
wrong place, and the space it should have occupied was spent on an inference.

### 1. The round critiques were rendered into a container nobody can see

`renderDebateAndSynthesis` (`app.js`) builds a card per round from
`debate_outputs` and writes them into `#debate-output`. That element sits inside
`<section class="panel panel-section">`, and `app.css` carries:

```css
.layout > aside,
.panel.panel-section {
  display: none;
}
```

with **no view qualifier**. Measured in Chromium against the golden fixture on
this branch's parent (`568dd10`), reading `getBoundingClientRect()` and walking
ancestors for the first `display: none`:

| element | view | text length | box | first hidden ancestor |
|---|---|---|---|---|
| `#debate-output` | `result` | 470 chars | **0 × 0** | `SECTION.panel.panel-section [display=none]` |
| `#debate-output` | `live-run` | 52 chars | **0 × 0** | `SECTION.panel.panel-section [display=none]` |
| `#result-positions` | `result` | 1108 chars | **910 × 532** | none |
| `#result-synthesis` | `result` | 2362 chars | 910 × 1127 | none |

So the critique was built on every poll and painted at zero pixels on **every**
screen — not "shown during the run and hidden afterwards", which is what this
work package was originally scoped against. The premise handed in was wrong in
the direction that makes the defect worse.

The screen-isolation comment in `app.css` states the intent: the legacy panels
are hidden because "the result view now renders its own synthesis + follow-up
block … so nothing is lost by hiding the legacy sections." That is true of the
synthesis (`#result-synthesis` exists) and **false of the debate** — the result
view had no debate surface at all. The only route to the critique was the
"Read the full debate transcript →" link.

### 2. "How positions moved" cannot report what its column headers promise

`#result-positions` drew a four-column table: Model, Opening, After round 1,
Final. Tracing the backend:

- `opening` is `_opening_synopsis(answer_text)` (`debate.py`) — the model's own
  first sentence, truncated to 140 chars. **Observed.**
- `after_round_1`, `final`, `revised` and `revision_note` all come from
  `_stance_texts` (`debate.py`), whose body is a single dict lookup:

  ```python
  state = alignment.state if alignment is not None else AlignmentState.NO_ANSWER
  copy = _STANCE_COPY[(final_answer_provenance, state)]
  return (copy.after_round_1.format(focus=focus), copy.final, copy.revised, copy.revision_note)
  ```

  The key is the model's **final** alignment state. Nothing in that path reads a
  round-1 output. `focus` comes from `_focus_phrase`, which reads
  `DebateOutput.focus_areas` — the round's topic labels — never its
  `critique_text`.

The five strings the "After round 1" column can hold (`_OPENING_COPY`) are:

```python
NOT_INVOKED:          "This answer was not produced by a model, so there is no round-1 stance to place."
NO_ANSWER:            "No usable answer was returned, so there is no round-1 stance to place."
HELD_WITH_CONSENSUS:  "Opening clustered with the majority reading on {focus}."
MOVED_TO_CONSENSUS:   "Opening clustered as a minority reading on {focus}."
HELD_MINORITY:        "Opening clustered as a minority reading on {focus}."
```

Every one is a statement about the **opening**. Three begin with the word
"Opening". The last two are byte-identical, so the column cannot even separate a
model marked `revised` from one that held a minority position. Of the table's
twelve content cells on a four-model run, four carried an observation and that
observation was a truncated copy of text the transcript already shows in full.

The caption was honest — "Inferred from opening answers and panel consensus —
not a quoted transcript" — but honesty about a column header does not repair the
column header. A reader who sees "After round 1" expects a later timepoint.

**One correction to the record.** The work package asserted that no position can
ever move because the models never read each other (#290 is unbuilt), and cited
a production run whose four rows were byte-identical with `revised: false`. The
first half is not right as a mechanism claim: `revised` **is** reachable, and
`tests/resilience/test_fault_injection_lane.py` proves it at the served API
(`[m["slot_number"] for m in ... if m["revised"]] == [4]`). It requires a live
synthesis and ≥10 % 4-gram containment of a minority opening in the final text
(`_opening_reflected_in_final`, threshold `0.1`). That is a containment measure
between an opening and a synthesis — the model did not move; the synthesiser's
prose echoed it. So the flag is reachable and still does not mean what
"positions moved" says. The argument for removal rests on the column semantics
above, not on the flag being dead.

## Decision

**Put the round-level critique on the completed result view, and remove the
position table from the screen.**

1. `#result-debate` renders one card per entry in `debate_outputs`, in the slot
   `#result-positions` used to hold (after `#result-trust-score`, before the
   transcript link).
2. The cards are `buildTranscriptRound` **verbatim** — the same builder the
   transcript view uses. Reused rather than reinvented: it already routes
   critique prose through `setProse` (the Markdown renderer) instead of
   `textContent`, and one treatment for one kind of content means one place to
   change it.
3. The section is headed "The debate rounds" and captioned "One critique per
   round, covering all four answers together — Quorum does not record a
   per-model, line-by-line exchange." **The honesty rule is unchanged**: the
   backend records one `critique_text` per round with no per-model attribution,
   so the surface is round-level and says so. It must never grow per-model
   exchange cards; that is #290, which is not built.
4. **Each card discloses who wrote it.** `debate_mode` is `"live"` only when the
   configured moderator model's own response supplied the critique; on
   `"fallback"` the moderator was unconfigured, unreachable or returned nothing
   usable, and `critique_text` is Quorum's own template
   (`debate.py::_build_round_one_text`). A round that is not `"live"` carries a
   "Written by Quorum, not by a model" marker. It **fails closed** — an absent
   `debate_mode` gets the marker, matching the API schema, whose default for
   that field is `"fallback"`.
5. **The `Focus:` line is not shown on the result view.** `debate.py` passes the
   module constant `FOCUS_AREAS` to both rounds, so it is byte-identical on
   every card of every run; under a "Round N" header it reads as per-round
   metadata. That is the same "constant dressed as an observation" defect this
   ADR removes the table for. The transcript still shows it — pre-existing
   behaviour on a drill-down the reader chose to open, and a separate concern.
6. The transcript link stays. The transcript still adds the per-model **opening
   answers**, which the result view does not carry.
7. In the Markdown export, `## Where each model stood` becomes
   `## What each model opened with` and keeps only the `- **Opening:**` line.
   (Not `## Opening positions`: the same document already carries
   `**Opening positions carried into the final answer:** X of Y`, a tally, and
   one phrase meaning two things in one decision record is its own defect.) The three
   inferred lines (After round 1, Final, Revision note) are dropped for the same
   reason the columns were.

### Why the export keeps a reduced section rather than losing it

Deleting the export block outright was the simpler option and was rejected on
evidence. `export-and-expanders.spec.ts` drives six document-forgery cases
through **two** different escaping call sites — `final_synthesis.consensus`
(a block surface, `mdUntrustedBlock`) and `position_movements[0].opening` (a
list surface, `mdUntrustedInline` inside a `- **Opening:**` item). Its own
comment records that the list surface "is where round 3's fix broke". Removing
the block would have halved that coverage silently. Keeping the observed field
keeps both call sites live and drops only the inferred prose.

### Where the inline-Markdown coverage went

`.result-pos-text` was a `setInlineProse` surface that two `markdown-corpus`
tests targeted. It is gone, so `goldenRespWithProviderText(_, "inline")` and
`goldenRespWithMarkdownShapes` now write to
`final_synthesis.high_stakes_notice`, which `renderVerdictBand` renders through
the **same** `setInlineProse` into `<span class="result-verdict-caveat">`. Still
a span, so the "an inline surface may not gain block children" assertion means
what it meant. Re-pointed rather than deleted: those two tests guard the inline
path on the result view, and there would otherwise be none.

Likewise, the parity test asserting per-vendor avatar tints was re-pointed to
`.transcript-opening-avatar` (the surviving avatar surface) rather than deleted —
nothing else in the suite covered it. Its companion, which asserted the avatar's
inset from a `border-collapse: collapse` table edge, **was** deleted: the
transcript openings are not a table, so it has no subject left.

## Rejected alternatives

| Option | Why not |
|---|---|
| Reuse `renderDebateAndSynthesis` on the result view | It writes into `#debate-output` inside the `display: none` legacy panel and styles cards with `.round-card`, whose colours `tests/integration/test_phase3_ui_fixes.py` pins. Reusing it means either co-owning that gate or moving a dead path. `buildTranscriptRound` is the live, honest, Markdown-routed equivalent. |
| Keep the table, drop only the "After round 1" column | Leaves "Final" — also a `_STANCE_COPY` lookup — under a header implying an observed endpoint, and leaves a 4-row table above the thing the reader came for. The header was not the only problem. |
| Keep the table, relabel the columns honestly | Costs the same screen space to say "here is a classification of your openings", which the verdict band's tally already says in one line. |
| Delete the legacy `.panel.panel-section` and `renderDebateAndSynthesis` too | Correct, and out of scope for one concern. It also owns `#model-grid`. Recorded as a follow-up, not done here. |
| Collapse the critique behind a disclosure on the result view | The complaint was that the reasoning is not reachable. Putting it one click away is the state being fixed. |

## Consequences

- The result view grows by the rendered height of the run's critiques and loses
  the 532 px the table occupied. The Linux visual baselines for
  `result-verdict.png` must be re-seeded in CI
  (`seed-visual-baselines.yml`); `trust-score-visual`'s six element-scoped shots
  target `#result-trust-score`, a **preceding** sibling, and are unaffected.
- `position_movements` stays in the API and in `openapi.yaml` unchanged. This is
  a presentation decision; no schema, guardrail constant or backend behaviour
  moved. `revisedCount` still drives the verdict band's "N revised their
  position" suffix, which is **left as-is and flagged** — it is a different
  surface and a separate concern.
- A new blocking spec, `e2e/tests/invariants/result-debate.spec.ts` (9 tests),
  is registered in the first invariants lane; its floor moved 244 → 253,
  measured by running the lane, not by adding.
- `.result-debate` needs an explicit `[hidden] { display: none }`. An author
  `display: flex` beats the UA stylesheet's `[hidden]` rule, so without it the
  `hidden` attribute is inert and a run with no debate rounds paints an empty
  bordered card. The table this replaced set no `display`, so it never had the
  bug. Found by mutation, not by review: flipping `container.hidden` to `true`
  left all eight specs of the day green.

## What turns the tests red

Recorded per spec in `result-debate.spec.ts`; each was proven by mutation
(`cp` aside, mutate, restore from the copy, `diff -q`), with the mutation's
application confirmed by md5 before the run:

| mutation | tests killed |
|---|---|
| `container.hidden = false` → `true` | 4 |
| `renderResult` stops calling `renderResultDebate` | 8 |
| `setProse(body, …)` → `body.textContent = …` | 2 |
| two cards emitted per round | 2 |
| the round-level caption is dropped | 1 |
| a second body added inside each round card | 2 |
| `.result-debate[hidden]` rule removed | 1 |
| an "After round 1" `<th>` reintroduced | 1 |


## What adversarial review changed

Two independent read-only lenses ran against `f6939bf`. Both independently found
the same top finding, and it was a real regression in honesty, not a nitpick.

**The caption asserted authorship the data contradicts.** The first draft read
"written by the moderator across all four answers". Driven in Chromium with
`debate_mode: "fallback"` on both rounds and live answers elsewhere, a reviewer
measured **zero** lines anywhere on the result view mentioning simulation, demo,
local or fallback — while a full-width block of Quorum's own template sat under
a caption saying a model wrote it. (The first report of this carried a pixel
height of 547; a second lens measured 496 in four configurations on the same
tree and could not reproduce 547. The height is not load-bearing and the
unreproducible figure is dropped rather than repeated — the measured facts are
the zero disclosure lines and the displayed template text.) The `#result-degraded` banner covers the fully
simulated case; it does **not** cover live answers plus a fallen-back moderator.
`debate_mode` already recorded the truth and the UI read it in exactly zero
places. Decision items 3 and 4 above are the fix. Note the same view already
handled the analogous synthesis case correctly (`synthesis_mode !== "live"` →
`badge-summary`), so this was an inconsistency as much as an omission.

**The test named for the honesty rule could not enforce it.** The caption spec
asserted only `text.length > 0`. A reviewer replaced the caption with "Each
model read the other three answers and replied in turn — Round 2 is their
rebuttal to Round 1." and all nine specs stayed **green**. Dropping the caption
was caught; falsifying it was not. Now pinned in two places, both proven by
mutation: an e2e test on the rendered DOM, and
`tests/unit/test_ui_honesty.py::test_the_debate_section_copy_does_not_claim_the_models_answered_each_other`,
which extends the pattern already used for the OpenAPI description. That unit
gate reads the `mkEl` string literals rather than scanning the file, because
`app.js`'s comments here deliberately spell out the banned phrases to explain
the rule — the prose-matches-instead-of-code trap `tests/code_text.py` exists
for, and `code_without_comments` cannot help because it strips `#` comments, not
JavaScript `//` ones.

**Two specs were satisfiable by wrong implementations.** "Exactly one critique
body" passed a card that also carried four per-model paragraphs under any other
class; it now pins the card's child shape. "The positions table is gone" passed
a table restored under a different id or built from `role="columnheader"`; it now
asserts the movement DATA is unrendered, quoting the fixture's own values.

**The fixture omitted `debate_mode` entirely**, so by the schema's default the
golden "good run" was two template-written rounds and no gate could tell the
provenances apart. It now seeds `"live"` explicitly, with
`goldenRespWithTemplatedDebate()` as the contrast.

Also fixed from review: the `docs/32-ui-state-matrix.md` line filed
`#result-debate` inside the "Run details" disclosure (it is a top-level sibling,
visible with nothing clicked — the mis-file was inherited from the
`#result-positions` sentence and re-asserted rather than checked); the
"Revision counts are inferred from the panel's position movements" caption
pointed at a deleted surface; and two test docstrings still named the removed
cell as their subject.

**Refuted, and worth recording so it is not re-litigated:** the caption IS in the
accessible tree (`ariaSnapshot` confirms), and the removed table had the
identical `aria-label`-plus-visible-caption structure, so there is no
accessibility regression. The `[hidden]` sweep found no other element with the
author-`display` bug. `renderResultDebate` leaks no state between runs. The
export rename does not weaken the forgery gate — model text is demoted to level
5 before the allow-list is consulted. Both re-pointed test surfaces
(`.result-verdict-caveat`, `.transcript-opening-avatar`) were mutation-proven to
still bite. And every number in the original ADR and commit body was verified,
with one row marked UNVERIFIED by the reviewer: the `#debate-output` **live-run**
0 × 0 measurement was re-driven by me but not independently by them.

One item is left open by choice: a reviewer saw 2 failures in ~19 runs of this
spec in a hand-rolled harness with no `webServer`, never in CI's shape. It could
not be attributed to the diff and did not reproduce here. Given the zero-retry
policy on the blocking lane, a `flake-scan` pass is cheap insurance and is
recommended before this merges.

## Round two: what the fix itself broke

AGENTS.md rule 12 says to expect your own fix to introduce a defect and to budget
a round for it. It did, twice, and both were found by a lens reviewing only the
fix commit.

**The fix traded one false provenance claim for another.** Removing the position
table left `renderVerdictBand`'s caption pointing at a deleted surface
("inferred from the panel's position movements"), so round one rewrote it to
"inferred from the opening answers". That is wrong on both halves.
`revisedCount` reads `position_movements[].revised` (`app.js:2726-2730`, whose
own comment says so), and the backend defines `revised` as `opening_majority`
differing from `final_aligned` (`synthesis_consensus.py:510`) — a comparison of
the opening against the FINAL SYNTHESIS. Proved by control experiment in the
browser: emptying `position_movements` while leaving `model_answers`
byte-identical made the count and the caption vanish; emptying `model_answers`
while leaving `position_movements` intact changed neither. The caption now reads
"Revision counts compare each opening with the final answer — inferred, not
quoted." The lesson is narrow and worth keeping: **a sentence written to fix a
provenance claim is itself a provenance claim, and needs the same control
experiment.**

**The new unit gate's own vacuity guard did not fire.** `_extract_mkel_literals`
ended its window with a regex that was not anchored to the `mkEl` call. The
section title is written on ONE line, so its `)` is followed by `);` rather than
`),`+newline, and the scan ran on into the caption's call. The extraction for
`result-debate-title` therefore returned the title PLUS the caption — non-empty,
so the "could not locate … would pass vacuously" assertion was satisfied by the
wrong element. Measured consequence: **emptying the section heading kept all 3
new unit tests and all 13 e2e specs green.** A banned phrase planted in the
caption was also reported against the title. The window now scans to the
matching close paren, the extractions are asserted DISJOINT and heading-shaped,
and the e2e spec asserts `.result-debate-title` on its own rather than relying
on the head's combined text. Both proven: the emptied heading is now red in both
lanes.

Two smaller corrections from the same round: a docstring claimed a mutation
fails on `"read the other"` when it actually trips the `"per round"` guard first
and never reaches the banned-phrase loop; and a code comment still named
`"What the panel argued"`, the heading this ADR removed as a false exchange
claim.

**Refuted in round two, and worth recording.** The fail-closed marker holds: a
fully simulated run emits `debate_mode: "fallback"` on every round (driven end
to end through the served API, no paid calls), and `openapi.yaml` declares
`default: fallback` with no enum, so unknown values get the marker too. The
marker reaches both the result view and the transcript, and the transcript's own
caption does not contradict it. `showFocus` cannot be inverted by `{}` or
`undefined`. The marker's contrast is 5.63:1 light and 7.93:1 dark against the
card surface — both clear AA — and it IS within the axe gate's scope, because
that fixture carries no `debate_mode` and therefore renders the marker in four
scans across both themes. The Linux visual baseline stays valid: the masked
full-page diff is 6738 of 4,838,400 pixels (0.14%) against a 1% threshold.
