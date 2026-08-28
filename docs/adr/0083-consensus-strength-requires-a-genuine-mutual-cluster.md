# ADR-0083: Consensus strength requires a genuine mutual cluster, and a panel of one has none

## Status

Accepted — 2026-08-28

## Context

Two pre-existing, independently filed defects in
`compute_consensus_strength` (`src/product_app/synthesis_consensus.py`), both
scoped OUT of ADR-0075 on purpose (rule 17, one concern per change) and left
as open board rows W6 (#383) and W10 (#382). They are clubbed into one PR here
because both are the SAME kind of bug — the module disagreeing with itself
about what "strong" evidence looks like — and both live in the same file.

### #382 (W10): degree is not mutuality

`_has_strong_overlap` asked "do ≥3 texts each have ≥2 overlap PARTNERS?" —a
per-node DEGREE check. 4-gram Jaccard overlap is symmetric but not
TRANSITIVE: A~B and B~C does not give A~C. A 4-cycle defeats the degree check:

```
A~C, A~D, B~C, B~D          (present)
A~B, C~D                    (absent)

degrees: [2, 2, 2, 2]        every text clears "≥2 partners"
largest MUTUALLY overlapping set: 2  (two disjoint pairs)
```

Every text clears the degree bar, so the shipped rule read this panel
"strong" — a human looking at it sees two disjoint pairs, exactly the 2-vs-2
split #354 exists to catch. Exhaustive count at N=4 (#382, verified
2026-08-26): of 26 degree-based "strong" verdicts, 3 (11.5%) have no mutually
overlapping trio at all. At N=5: 793 verdicts, 157 (19.8%) false.

### #383 (W6): a panel of one is not unanimous

The stance branch (the moderator's own reading, when there is one):

```python
if len(sizes) == 1 or max(sizes.values()) >= _required_cluster(len(stance)):
    return "strong"
```

At N=1, `sizes` has exactly one key, so `len(sizes) == 1` is trivially true.
Separately — and this is the part worth stating explicitly, because it is not
obvious from reading the code — the SECOND clause is *also* true at N=1,
independent of the first: `_required_cluster(1) == 1` (`panel_size // 2 + 1`),
and the sole answer's group size is always 1, so `1 >= 1`. Both clauses call a
single answer "unanimous". A panel of one has nothing to corroborate it; that
is not what "strong" is supposed to mean. The overlap branch (no live
moderator) already answered `"weak"` for the identical N=1 shape, via
`_classify_divided_or_weak` — a single text cannot form a polar split, which
needs ≥2 texts.

### Why now, together

Both are pre-existing, latent-at-shipped-panel-size defects: #382 is invisible
at N≤3 (a degree-2 requirement over 3 nodes already forces a triangle) and
only bites once a real 4-node overlap graph can be a non-clique, which is
today's shipped panel size. #383 is reachable today on any degraded run that
loses 3 of 4 slots. Neither needs `OPENROUTER_LIVE_EXECUTION_ENABLED`. Board
row W10 also blocks W4 (variable panel size): #382 ends *"whoever lifts those
caps must fix this primitive first."*

## Decision

**1. `_has_strong_overlap` requires an actual mutually-overlapping trio (a
triangle in the overlap graph), not degree ≥2.**

A new primitive, `_overlap_adjacency`, returns the full pairwise boolean
matrix rather than per-node counts. `_overlap_partner_counts` is now DEFINED
in terms of it (row sums), so the two can never drift apart — the previous
version computed both independently from scratch. `_has_strong_overlap` walks
every 3-subset of the adjacency matrix and checks for one where all 3 pairs
are present:

```python
def _has_strong_overlap(completed_texts: list[str]) -> bool:
    n = len(completed_texts)
    if n < 3:
        return False
    adjacency = _overlap_adjacency(completed_texts)
    return any(
        adjacency[i][j] and adjacency[j][k] and adjacency[i][k]
        for i, j, k in itertools.combinations(range(n), 3)
    )
```

The threshold stays the literal `3` (a triangle), **not** generalised via
`_required_cluster` to the panel size — ADR-0075 already measured why not,
and that reasoning is untouched by this change: at `panel_size` 2 and 3,
`_required_cluster` returns 2, so a bar built on it would certify "strong" on
a SINGLE EDGE (two contradicting answers sharing opening boilerplate).
`test_row7_the_overlap_bar_refuses_a_majority_cluster_that_is_a_single_edge`
(`test_consensus_is_n_relative.py`) still pins that unchanged.

**N=3 behaviour is identical before and after.** With only 3 nodes, "all 3
have degree ≥2" already forced every node to touch both others — i.e. a full
triangle. The fix is visible only at N=4, where degree ≥2 no longer implies
mutual overlap.

**2. A panel of exactly one completed answer reads `"weak"`, not `"strong"`,
checked CENTRALLY before any branch is reached.**

```python
completed = [answer for answer in initial_answers if counts_as_evidence(answer)]
if not completed:
    return _classify_divided_or_weak(completed_texts=[])
if len(completed) == 1:
    return "weak"

stance = _usable_stance(initial_answers, debate_outputs)
if stance is not None:
    if len(stance) == 1:      # the duplicate-slot residual, below
        return "weak"
    sizes: dict[str, int] = {}
    ...  # unchanged
```

**Correction, 2026-08-29.** The first version of this fix guarded only the
STANCE branch (`if len(stance) == 1: return "weak"`, inside `if stance is
not None:`), on the stated belief that the OVERLAP branch (no usable stance)
already answered `"weak"` for the identical N=1 shape via
`_classify_divided_or_weak`. Review found that claim false for a reachable
shape: `_debate_signals_convergence` — one of the overlap branch's two
"strong" paths — is called unconditionally on `debate_outputs`, with **no
population-size gate at all**. A live debate round whose STANCE failed to
parse (the moderator replied in prose rather than JSON — a real, independent
failure mode; `debate.parse_moderator_output`'s own docstring documents
prose and stance parsing failing separately) but whose *critique text*
happens to contain a convergence keyword reached `"strong"` for a genuine
one-answer panel through this second path — the exact defect #383 exists to
close, surviving through a route the fix's own justification claimed was
already safe. Reproduced end to end (two independent verifiers, both
unrefuted): a 1-completed/3-failed panel, one `DebateOutput` with
`panel_stance=None` and `critique_text` containing "converged", returns
`"strong"` under the stance-only guard and `false_consensus_preserved=False`
downstream — the flag that gates the green banner.

The fix is now checked centrally, on `len(completed)`, before either branch
runs — closing the gap for every downstream signal at once rather than
patching `_debate_signals_convergence` individually. The stance branch keeps
a narrower residual guard on `len(stance) == 1` for the DUPLICATE-SLOT case
`test_row11_the_stance_bar_counts_scored_slots_not_completed_answers`
(`test_consensus_is_n_relative.py`) pins: `len(completed)` counts answers
while `len(stance)` counts distinct scored slots, and the two diverge only
when two completed answers share a `slot_number` — a shape where
`len(completed) > 1` but the stance population still collapses to one slot.

This matches the overlap branch's existing answer for the ordinary N=1
shape, rather than inventing a fourth `ConsensusStrength` literal. Traced
end to end, not merely asserted on the returned string:
`Synthesizer._is_false_consensus_preserved` is
`consensus_strength in {"weak", "divided"}`, and `false_consensus_preserved
=== false` is one of the required conjuncts of `isConsensusResult` (`app.js`,
the single green-banner gate, AC-019) — so this is what stops a genuine
one-answer run from ever qualifying for the green "unanimous panel" surface,
not merely a change to an internal literal.

### Rejected: connected-component instead of clique, for #382

A plausible-looking alternative to a full triangle check: require the overlap
GRAPH to be connected (or have a component of size ≥3), which is cheaper to
compute and easier to explain. **This does not fix the reproduction.** The
4-cycle counterexample above IS one connected component of size 4 — A-C-B-D-A
is a cycle through all four nodes — so a connected-component check would
still read it "strong". "These three answers mutually agree" means a clique,
not a component; a component only means "reachable via some chain of
overlaps", which is exactly the transitivity assumption that does not hold.
Pinned directly:
`test_row5_the_four_cycle_is_connected_but_not_a_clique`
(`test_consensus_requires_mutual_cluster.py`) asserts both facts about the
same graph — connected, no triangle — so a reviewer proposing this
alternative sees the test fail rather than having to re-derive the
counterexample.

### Rejected: a fourth `ConsensusStrength` literal for N=1

`ConsensusStrength = Literal["strong", "weak", "divided"]` is unchanged.
Nothing else in the module treats N=1 as a distinct category, "weak" already
serves as the catch-all for thin signal (0-1 completed answers with no polar
split), and the overlap branch already answers `"weak"` for this exact shape.
A new state would touch the type, every consumer's `match`/comparison, and
templated prose selection, for a distinction the module does not otherwise
draw. Deferred without a measured need for it.

### Considered and confirmed out of scope: generalising `_has_strong_overlap`'s threshold by panel size

A W10 planning pass suggested the clique SIZE itself could become the natural
generalisation point once panel size varies (W4). Correct in the abstract,
but doing so now would risk re-deriving `_required_cluster`'s formula for the
overlap bar — exactly the alternative ADR-0075 already rejected and this ADR
reaffirms. If W4 ships a variable panel size, re-derive the overlap
threshold's behaviour at each reachable N from real graphs, the way #382 did
for N=4 and N=5 — do not assume the stance bar's formula transfers.

## Consequences

- **The only N=4 verdict that moves** is a genuine 4-cycle overlap graph (or
  any other non-clique degree-2-everywhere shape) — measured at 3 of 26
  previously-"strong" verdicts (#382). Every 4-node graph containing a real
  triangle is unaffected, including every existing test fixture and visual
  baseline, none of which encode a 4-cycle.
- **The only stance verdict that moves** is N=1: `"strong"` becomes
  `"weak"`. N≥2 stance verdicts are byte-identical (ADR-0075's N-relative
  majority bar, untouched).
- `_overlap_partner_counts`'s observable behaviour (its return value for real
  text) is unchanged — it is now derived from `_overlap_adjacency` rather than
  computed independently, verified in
  `test_partner_counts_is_still_the_adjacency_row_sums`. Every existing
  consumer (`_opening_majority_flags`, and the row 7-9 controls in
  `test_consensus_is_n_relative.py`) is unaffected.
- `test_consensus_is_n_relative.py`'s `test_row12_the_overlap_bar_is_
  exhaustively_unchanged` was retired: its premise (`_has_strong_overlap` is
  a pure function of the DEGREE vector `_overlap_partner_counts` returns) is
  now false by design — the shipped formula's DECISION depended only on
  degree, and the new one needs full adjacency to test mutuality. (**A
  first draft of this bullet additionally claimed a genuine K4 and the
  4-cycle both produce `[2, 2, 2, 2]` — that is false and was caught by
  review; K4 gives every node degree 3. See the correction in
  `test_consensus_requires_mutual_cluster.py`'s "Structural change this
  required" section for the accurate reasoning and the exhaustive check
  that at N=4 a degree sequence alone is, in fact, always sufficient to
  determine triangle-presence — the real justification for reading full
  adjacency is that it is correct at every N by construction, not that
  degree information is fundamentally insufficient at N=4.**) The equivalent
  guard is rebuilt in `test_consensus_requires_mutual_cluster.py` over the
  ADJACENCY-matrix space instead, at panel sizes 0-5, against an
  independently-written triangle oracle.
- Board row W6's original Evidence needle (the pre-existing majority-bar
  line, `if len(sizes) == 1 or max(sizes.values()) >= _required_cluster(len(stance)):`)
  is untouched by this fix — the guard is a new line ADDED before it, not a
  replacement. That needle would have stayed `PENDING` forever regardless of
  whether the defect was fixed. Re-pinned to
  `ABSENT ... :: if len(stance) == 1:`, which is genuinely absent before this
  change and present after.
- Board row W10 is unblocked; row W4 no longer waits on anything from this
  package (`docs/65-open-work.md`).
- `_overlap_adjacency`'s two early-`continue` guards on an empty text
  (`if not current: continue` / `if not other: continue`) were REMOVED.
  Review demonstrated both were equivalent mutants of the `union == 0`
  guard alone (a coverage-driven test had been written to justify keeping
  them, but deleting either one left that test green) — simpler to delete
  the dead branches than to keep untested-in-substance defensive code,
  per this repo's own ADR-0069 precedent.
