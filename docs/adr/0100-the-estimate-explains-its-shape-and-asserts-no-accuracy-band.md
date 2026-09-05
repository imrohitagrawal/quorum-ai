# ADR-0100: The receipt explains why the Synthesis row shrinks

## Status

Accepted — 2026-09-04.

Implements the resolution ADR-0095 already chose for the est->actual pairing.
Supersedes nothing.

**Authorises nothing.** No `**Authorises:**` line; it may not be cited to
sanction a live-execution posture, and it moves no money constant.

## Context

On a peer-critique run the receipt's "Cost by model · est → actual" column pairs
two DIFFERENTLY SHAPED breakdowns, and the reader cannot tell why from the rows
alone. Verified in `costs.py`:

- the ESTIMATE prices both debate rounds inside the writer row
  (`inner_call_cost = 2 * debate_round_cost + synthesis_cost`). Under the peer
  shape `debate_round_cost` is `max(peer_round_cost, moderator_round_cost)`,
  where `peer_round_cost` sums all four slot models — so on any run where the
  peer figure wins, every critique dollar sits in one row named "Synthesis" and
  the four per-model rows carry none;
- the ACTUAL breakdown emits a `kind="critique"` row per critic and SUBTRACTS
  them from the writer row: `writer_cost = debate_total - critique_total +
  synthesis_cost`.

So the writer row shrinks between the two columns while four charges appear
that the estimate never showed. It reads as a saving plus four surprises.

**Nothing is lost, and the qualifier matters.** Each column re-sums to its own
total (`_reconcile_usd_lines`), and `by_stage` attributes the debate rounds
correctly on BOTH paths. The estimate total and the actual total are DIFFERENT
numbers, and the Total row shows both — so a note claiming "the totals agree"
would be refuted by the row directly above it. The first draft of this change
said exactly that, and adversarial review caught it.

## Decision

### Ship the estimate-side note ADR-0095 specified, and nothing else

ADR-0095 recorded the gap and ruled out the alternatives in its own words:
*"the resolution would be an estimate-side note in the UI, not silence"*, and
*"Emitting a row for a call that may not happen is a claim, so the rows stay
measured-path-only"*. Stated precisely: those sentences sit in ADR-0095's
**Consequences**, in conditional mood, alongside *"defensible but not
resolved"* — so they RULE OUT the alternatives rather than pre-approving a
wording. This record makes the wording decision they left open.

The note names the movement and keeps the qualifier the code comment already
had: *"Each column still adds up to its own total — only the attribution
moves."*

### Key it on the run's own rows, not on a flag

`hasItemisedCritiqueRows` reads `kind === "critique"` off the ACTUAL breakdown.
A peer-shaped run whose critics all fell back is billed nothing, and gets no
explanation for charges it never had. The browser cannot see
`PEER_CRITIQUE_ENABLED`, and should not need to: the question the note answers
is about THIS receipt's shape.

## Rejected alternatives

**Split the estimate's Synthesis row, or rename it.** Forbidden by ADR-0095,
which rejected a shape-dependent label, and by
`tests/unit/test_risk_constant_pins.py`, which pins that the estimate row and
the measured row carry the SAME label — `app.js` pairs them on
`${kind} ${model_id}`, so renaming one path renders two unpaired half-rows on a
money surface.

**Emit estimate-side critique rows.** Forbidden by ADR-0095 in those words: the
estimate cannot know which slots will be eligible, and a row for a call that may
not happen is a claim.

**Also rewrite the `#cost-confirmation` cost tooltip, which promises the bill
lands within "10-30%" of the estimate.** That claim IS unsourced. It was
dropped from this change for two reasons found in review, both verified:

1. **No user can see it.** `#cost-confirmation` carries `hidden` in the
   template and `app.js` sets `.hidden = true` and never false. The repo
   already recorded this in four places, including
   `docs/32-ui-state-matrix.md` (*"stays hidden"*) and a test deleted by #127
   for that reason. Rewording it would have been a fix to nothing, and the
   gate written for it would have PINNED dead markup in place — the anti-pattern
   ADR-0099 exists to remove.
2. **The replacement was itself false.** It read *"What you approve is a cap —
   every call is length-limited to keep the run inside it."* `costs.py` forbids
   that in its own words — *"Do not restore an unqualified 'true ceiling'
   wording while these hold"* — and `max_cost_usd`'s own docstring says *"'real
   cost never exceeds it' is not a guarantee this figure can make"*. It bounds
   OUTPUT only; the `:online` search fee is priced at `0.0` by accepted
   decision and is unpriced in the bound.

**The live cost copy is already careful** — *"The 'up to' figure is what you're
approving — the worst case this run is priced at"* — which is the deliberately
narrow wording an earlier review refused to strengthen. There is no false
accuracy claim on a surface a user reads, so removing one is not urgent work.
The dead block is recorded as debt, not fixed here: it is a different concern
from this note (rule 17), same call this session made for ADR-0099's dead panel.

## Consequences

- No `costs.py` change, no constant moved, no rename, and the figure the user
  approves is byte-identical. A copy change on a money surface, not a money
  change — the distinction ADR-0081 and ADR-0094 make load-bearing.
- `goldenRespWithCritiqueRows` now MIRRORS the server: it subtracts the critique
  total from the writer row and holds the run total fixed. It previously
  appended the rows and raised the total, which inverted the effect — the
  Synthesis row rendered unchanged, so the phenomenon this note explains was
  absent from the fixture that gates it.
- The e2e assertion pins the WHOLE sentence and requires the note to be
  VISIBLE. An unanchored substring match was defeated in review by a note that
  read *"the totals do NOT agree. Dispute this invoice. only the attribution
  moves"* and stayed green.
- `tests/unit/test_receipt_attribution_note.py` drives the predicate under Node
  with equal-length inputs, because the two e2e fixtures (10 rows and 6 rows)
  cannot distinguish `kind === "critique"` from `rows.length > 6` — review
  defeated the browser gate with exactly that.
