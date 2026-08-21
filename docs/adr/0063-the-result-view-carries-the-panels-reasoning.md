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
3. The section is captioned "One critique per round, written by the moderator
   across all four answers — Quorum does not record which model said which
   line." **The honesty rule is unchanged**: the backend records one
   `critique_text` per round with no per-model attribution, so the surface is
   round-level and says so. It must never grow per-model exchange cards; that is
   #290, which is not built.
4. The transcript link stays. The transcript still adds the per-model **opening
   answers**, which the result view does not carry.
5. In the Markdown export, `## Where each model stood` becomes
   `## Opening positions` and keeps only the `- **Opening:**` line. The three
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
