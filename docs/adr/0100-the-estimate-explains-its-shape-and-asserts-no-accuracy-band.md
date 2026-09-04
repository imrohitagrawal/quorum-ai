# ADR-0100: The estimate explains its shape, and asserts no accuracy band

## Status

Accepted — 2026-09-04.

Implements the resolution ADR-0095 already chose for the est->actual pairing,
and supersedes nothing. The tooltip decision is new.

**Authorises nothing.** No `**Authorises:**` line; it may not be cited to
sanction a live-execution posture, and it moves no money constant.

## Context

Two money surfaces told the user something they could not act on.

### 1. An accuracy band nobody measured

`workspace.html` promised: *"The actual provider bill may be **10–30% higher or
lower** depending on the model's output length and whether citations are
returned."*

Counted, not assumed: `grep` finds that string in exactly ONE place in the
repo. No test, no spec and no doc pins it, and no measurement supports it. The
only measured estimate-vs-actual comparison in the project — issue #256 — had
the actual at `$0.0767` against a `$0.0329` estimate, **+133%**, far outside
the promised band.

### 2. A receipt that reads as a saving when the money merely moved

Under peer critique the two columns of "Cost by model · est → actual" are
differently shaped, verified in `costs.py`:

- the ESTIMATE prices both debate rounds inside the writer row
  (`inner_call_cost = 2 * debate_round_cost + synthesis_cost`), and under the
  peer shape `debate_round_cost` is a SUM OVER ALL FOUR slot models. Every
  critique dollar sits in one row named "Synthesis"; the four per-model rows
  carry none.
- the ACTUAL breakdown itemises a `kind="critique"` row per critic and
  subtracts them from the writer row.

So the receipt shows one row that appears to have saved several cents and four
that appear to be charges nobody estimated. **No money is lost** — Total agrees
in both columns, and `by_stage` attributes the debate rounds correctly on BOTH
paths. Only `by_model` mis-attributes, and only on the estimate side.

## Decision

### 1. Say what protects the reader; assert no percentage

> "This is a planning estimate, not a quote. The actual bill depends on how long
> the answers and the debate run, so it can come in above or below this figure.
> What you approve is a cap — every call is length-limited to keep the run
> inside it."

Every clause is checkable. The cap claim is `_estimate_bound_usd`'s own
documented property — it is a true ceiling *because* each live call is capped
at exactly the token counts the bound prices (initial, debate, synthesis) — and
`app.js` already shows `max_cost_usd`, not the point estimate, as the approved
figure (issue #256's fix).

### 2. The estimate-side note, exactly as ADR-0095 specified

ADR-0095 pre-decided this and ruled out the alternatives in its own words:
*"the resolution would be an estimate-side note in the UI, not silence"*, and
*"a row for a call that may not happen is a claim, so the rows stay
measured-path-only"*. The note explains the shape; it adds no estimate-side
critique rows and renames nothing.

It is keyed on the run's OWN actual rows (`kind === "critique"`), not on a
deployment flag the browser cannot see, so a peer-shaped run whose critics all
fell back — billed nothing — carries no explanation for charges it never had.

## Rejected alternatives

**Replace 10–30% with the measured +133%.** Rejected, and this is the decision
worth recording. #256's own analysis names its largest single cause: the
estimate *"does not price the judge at all — $0.0109 is 33% of the entire
approved figure"*. ADR-0064 fixed exactly that (`costs.py` prices the judge
whenever one is configured, pinned by `test_bound_covers_the_judge.py`). So the
2.33x figure is **stale in the optimistic direction**, and no current
measurement replaces it. Correcting one unsourced number with a superseded one
is the failure mode AGENTS.md rule 4 exists for: *"When you CORRECT a false
claim, verify the REPLACEMENT before writing it."*

**Measure a fresh band first.** Correct, and deferred rather than dismissed: it
needs a paid run, which is a separate owner decision. The honest interim is to
assert no number, which costs the reader nothing they had — the old number was
not information, it was decoration.

**Split the estimate's Synthesis row, or rename it.** Forbidden by ADR-0095,
which rejected a shape-dependent label, and by
`tests/unit/test_risk_constant_pins.py`, which pins that the estimate row and
the measured row carry the SAME label because `app.js` pairs them on
`${kind} ${model_id}`. Renaming one path renders two unpaired half-rows on a
money surface.

**Emit estimate-side critique rows.** Forbidden by ADR-0095 in those words: the
estimate cannot know which slots will be eligible, and a row for a call that
may not happen is a claim.

## Consequences

- No `costs.py` change, no constant moved, and the figure the user approves is
  byte-identical. This is a copy change on a money surface, not a money change
  — the distinction ADR-0081 and ADR-0094 make load-bearing.
- The repo now asserts NO accuracy band anywhere a user can read one, and
  `test_no_user_facing_copy_promises_an_estimate_accuracy_band` sweeps both
  surfaces so it cannot quietly return.
- When a paid run finally measures the post-ADR-0064, post-ADR-0096 shape, the
  tooltip can gain a number that is real. Until then the silence is the honest
  state, and it is recorded here so a future session does not read it as an
  oversight and "fix" it with a guess.
