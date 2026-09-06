# ADR-0101: The clipped-critique figure was never measured on a critique

## Status

Accepted — 2026-09-05.

Corrects a claim carried in `src/product_app/telemetry_sink.py` and
`tests/unit/test_telemetry_correlator.py`, and identifies its origin in
ADR-0093's own *Measured* table. Narrows, but does not supersede, ADR-0093's
`finish_reason` rationale.

**Authorises nothing.** No `**Authorises:**` line; it may not be cited to
sanction a live-execution posture, and it moves no money constant. It is in
part a decision NOT to move one.

## Context

Two committed files stated that the #290 probe *"measured seven of eight
**critique calls** returning `"length"`"*, and a root continuation prompt
escalated that to *"full price for a truncated critique … **live in production
right now**"*, ranking a cap change as the next work package.

Three commands refute the measurement claim.

**1. The probe measured ANSWER models, not critics.**
`docs/analysis/2026-08-26-session-handoff.md:38` describes the source:
`a2_probe.py`, *"4 default slot models × 2 repeats, `max_tokens=2000`, a prompt
that genuinely fills the cap"*. It was a standalone timeout probe. Filling the
cap was the probe's METHOD — the input was written to do it — so
`finish_reason: "length"` on seven of eight is the setup working, not a finding
about any product path.

**2. Peer critique did not exist yet.**

```
$ git log --format="%h %ad %s" --date=short -S"def _build_peer_round" \
    -- src/product_app/debate.py | tail -1
5aed777 2026-09-03 feat(debate): peer critique (#290), behind a default-off flag
```

The probe ran 2026-08-26, eight days earlier. No critique call was reachable.

**3. No critique call has run since, either.** Production `/status` reports
`last_live_charge_at = 2026-09-01T21:02:46Z` and `global_daily_spend_usd = 0`.
`5aed777` was committed `2026-09-03 05:52:20 +0530` = `2026-09-03T00:22:20Z`,
so production's last paid run predates the feature by **27.3 hours**.

**Stated at the width of the evidence, as of 2026-09-05:** no critique call was
recorded anywhere in this repo, and production had taken no live charge since
`5aed777` landed. **Both ceased to be true on 2026-09-06**, when a production
run made eight real critique calls — see ADR-0102, which supersedes this
paragraph and the severity finding below.
Those are the two things measured. `/status` reads ONE deployment, so it cannot
see a laptop run with the flag flipped and a personal key — though a simulated
run dispatches nothing by construction (`_call_debate_model` returns `None`
before any request when live execution is off). "Zero critique calls anywhere,
ever" is an inference from an absence of records, not a measurement, and this
record does not make it.

### Where the word came from — and it is NOT downstream

**The first draft of this ADR said the word "critique" was "inserted
downstream, in transcription", and that ADR-0093 "did not make the error".
Both were false, and adversarial review refuted them with one command.** The
correction is recorded rather than quietly replaced, because a record about a
false claim that carries its own false claim is the failure it exists to name.

ADR-0093's *Measured* table, written 2026-09-01 in `d860b2a` — two days before
peer critique existed — labels the probe **"critique"** twice, and states its
population plainly:

| line | text |
|---|---|
| `0093:43` | `Worst per-`recv` gap, **2000-token critique**, non-streamed \| 25.055 s (`openai/gpt-4o-mini`) \| #290 probe, 2026-08-26, **8 paid calls**` |
| `0093:45` | `Wall clock, **2000-token critique** \| 6.385 s – 26.492 s **across the four slot models** \| #290 probe` |

So ADR-0093 does state the population — *"across the four slot models"* — and
it is the document that first called those answer-model calls a "critique".
Read in its own context the label is defensible shorthand: the probe was a
PROXY, the same four models at the same 2000-token cap, run to answer *"can
peer critique be built on this transport?"* Its verdict (`0093:31`) was that it
could not.

But shorthand for a proxy, sitting in a table headed *Measured*, is what
downstream files inherited. They did not fumble a transcription; they read the
table as written and added the one word — "calls" — that the table's own
framing invited. `0093:327`'s careful *"seven of eight **calls**"* is the
exception in that document, not the rule.

**The correction is therefore upstream framing, not downstream discipline.**
That matters, because "someone mis-transcribed it" implies the fix is to be
more careful, and this record would then be the third document to be careful
and still be wrong.

## Decision

### State the figure's population at every site that states the figure

Both call sites now name what was measured (four answer models, a cap-filling
prompt, 2026-08-26), name what was not (any critique), and say so in the
imperative — `NOT YET MEASURED ON A CRITIQUE` — so the next reader cannot
re-derive the stronger claim from the weaker text. `finish_reason` remains
justified on exactly the ground ADR-0093 gave it: a clipped critique WOULD be
full price for truncated text on a healthy-looking receipt, and no cost row can
carry that. It is the field that will settle the question, not evidence the
question is already settled.

ADR-0093's table is left as it stands. An accepted ADR is a record and is
narrowed by a later one rather than rewritten; this record is that narrowing,
and it names the two lines so a reader arriving at them finds the correction.

### Do NOT move `DEBATE_ROUND_MAX_TOKENS`

It stays at `2000` (`src/product_app/debate.py:76`). The concern behind the
false claim is real and remains open: ADR-0096 made a round-2 reply carry a
critique AND a self-assessment, rationale, sources and a revised answer, and
`synthesis` reads those revised answers as its primary input — so the tail most
likely to be cut is the part that matters most. But whether 2000 fits that
reply is **unmeasured**, and the instruction attached to the work — *"measure
the real output length, do not guess a number"* — cannot be satisfied without a
paid run.

Raising a cap raises cost. Moving it on reasoning would be shifting a money
guardrail off a number nobody has measured, which is the failure ADR-0094
exists to prevent.

### The cap question is answered by the harvest, not before it

It folds into the first paid run inside the declared window. `finish_reason`,
`stage` and `slot_number` are already in `TELEMETRY_FIELD_NAMES`, so a
`debate_round_2` row is attributable to its critic the moment one exists. The
harvester must capture them; the run settles the cap; a cap change, if the data
supports one, is its own package with its own ADR.

## Rejected alternatives

**Delete the sentence.** It would remove the false claim and the field's
rationale together. `finish_reason` is a good field for the reason ADR-0093
gave; the defect is the population attached to the number, not the number's
relevance.

**Rewrite ADR-0093's table.** Rejected: an accepted ADR is a record of what was
decided and on what evidence. Editing its *Measured* rows now would erase the
origin of a defect that took two review rounds to locate, and leave this record
asserting a history the tree no longer shows.

**Raise the cap now and measure afterwards.** Rejected on this repo's own
record: an unmeasured guardrail move is what ADR-0094 pre-computed constants to
avoid, and the run that would validate the new value is the same run that would
have measured the old one. There is no ordering where guessing first is cheaper.

**Add a gate pinning the figure's population.** Tried, and withdrawn after two
review rounds. The gate scanned `src/` and `tests/` for the figure appearing
near the word "critique". Review demonstrated that its positive partner was a
tautology (the gate's own regex source kept the population non-empty, so
deleting the figure from both real files still passed), that a line wrap at
width 50–52 defeated it, and that it sat 11 characters from falsely accusing
prose that was true and was itself the correction. Fixing all three took it to
234 lines to police one sentence, still catching only near-verbatim
re-introduction and leaving `scripts/` unscanned. Measured against this repo's
own defect history — **0 of 16** `src/` defects caught by an automated check,
**10 of 16** by adversarial review
(`docs/metrics/defect-discovery-audit.md`) — the gate was not worth its
surface. Both review rounds found this defect class by reading. That is the
mechanism that works here, and this record is its output.

**Fix the root continuation prompt only.** The false sentence is shipped in
`src/`, where it outlives any prompt file.

## Consequences

- No behaviour change, no constant moved, no test outcome changed. Comments,
  a module docstring and documentation; the wire, the receipt and the bill are
  byte-identical.
- The "seven of eight" ratio now has **two** measured populations in this repo
  — wall-clock timeout exceedance
  (`docs/analysis/2026-08-26-b3-timeout-probe.md:87`) and answer-model
  cap-filling (this record) — and **no measurement at all** on the critique
  path. ADR-0093 already warned about the first collision; this adds the
  second, and says plainly the third has no number behind it.
- **SUPERSEDED 2026-09-06 by ADR-0102: severity is LIVE again**, and measured
  — a production run clipped 3 of 4 round-2 replies. The reading below was
  correct on its date and is kept as written.
- **The severity claim is downgraded from LIVE to LATENT**, as of 2026-09-05:
  nothing had been clipped in production because no critique call had run. That
  reading is DATED on purpose. A live-execution window is open until
  2026-09-08T07:51:25Z with the critique path armed, so the first paid run
  changes it and no gate would notice — which is also why no such sentence is
  left in `src/`.
- A work package ranked first as *"free, live in production, unblocked"* was
  none of the three. Re-ranking on a refuted premise is rule 20's mandatory
  stop, taken here.
- **This record needed two review rounds and was wrong in between.** Its first
  draft over-reached ("the count of critique calls ever made, anywhere, is
  zero" on one deployment's evidence), and its second mis-stated ADR-0093's
  contents. Both were caught by review, not by a gate — which is the evidence
  for the rejected alternative above.
