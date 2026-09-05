# ADR-0101: The clipped-critique figure was never measured on a critique

## Status

Accepted — 2026-09-05.

Corrects a claim carried in `src/product_app/telemetry_sink.py` and
`tests/unit/test_telemetry_correlator.py`. Narrows, but does not supersede,
ADR-0093's `finish_reason` rationale — ADR-0093's own wording is accurate and
is left untouched.

**Authorises nothing.** No `**Authorises:**` line; it may not be cited to
sanction a live-execution posture, and it moves no money constant. It is in
part a decision NOT to move one.

## Context

Two committed files stated that the #290 probe *"measured seven of eight
**critique calls** returning `"length"`"*, and a root continuation prompt
escalated that to *"full price for a truncated critique … **live in production
right now**"*, ranking a cap change as the next work package.

Three commands refute it.

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
so the last paid run predates the feature by **27.3 hours**. The count of
critique calls ever made, anywhere, is **zero**, and nothing is being clipped
in production.

ADR-0093 said this correctly on both counts: line 327 reads *"seven of eight
calls"* — no "critique" — and line 344 states plainly *"No critique call has
ever run, so every per-model number this design would expose is UNVERIFIED."*
The word was inserted downstream, in transcription, then hardened into a
severity claim. This is the decay AGENTS.md rule 11 measures, reproduced inside
the paragraph documenting it.

## Decision

### State the figure's population, not just its value

Both call sites now name what was measured (four answer models, a cap-filling
prompt, 2026-08-26), name what was not (any critique), and say so in the
imperative — `NOT YET MEASURED ON A CRITIQUE` — so the next reader cannot
re-derive the stronger claim from the weaker text. `finish_reason` remains
justified on exactly the ground ADR-0093 gave it: a clipped critique WOULD be
full price for truncated text on a healthy-looking receipt, and no cost row can
carry that. It is the field that will settle the question, not evidence the
question is already settled.

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

**Correct it to "seven of eight calls" and stop.** That is ADR-0093's accurate
wording, and it is accurate — but it survived transcription into a false claim
once already, because "the #290 probe" next to a critique-shaped consequence
reads as a critique measurement. Naming the four answer models and the
cap-filling prompt is what makes the re-derivation fail.

**Raise the cap now and measure afterwards.** Rejected on this repo's own
record: an unmeasured guardrail move is what ADR-0094 pre-computed constants to
avoid, and the run that would validate the new value is the same run that would
have measured the old one. There is no ordering where guessing first is cheaper.

**Fix the root continuation prompt only.** The false sentence is shipped in
`src/`, where it outlives any prompt file.

## Consequences

- No behaviour change, no constant moved, no test outcome changed. A comment
  and a module docstring; the wire, the receipt and the bill are byte-identical.
- The "seven of eight" ratio now has **two** measured populations in this repo
  — wall-clock timeout exceedance
  (`docs/analysis/2026-08-26-b3-timeout-probe.md:87`) and answer-model
  cap-filling (this record) — and **no measurement at all** on the critique
  path. ADR-0093 already warned about the first collision; this adds the
  second, and says plainly the third has no number behind it.
- **The severity claim is downgraded from LIVE to LATENT.** Nothing is being
  clipped in production because nothing has run. The exposure begins on the
  first paid run with `peer_critique_enabled`, which is exactly when the
  telemetry that measures it starts existing.
- A work package ranked first as *"free, live in production, unblocked"* was
  none of the three. Re-ranking on a refuted premise is rule 20's mandatory
  stop, taken here.
