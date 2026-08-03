# ADR-0009: sentences the system dictates are stripped before consensus scoring

## Status

Accepted — 2026-08-04 (issue #180, part 1 of 2)

## Context

`synthesis_consensus` decides whether a panel of model answers agrees. It
tokenises each answer's opening 200 characters into word-level 4-grams and asks
whether any pair shares a Jaccard overlap `>= 0.1`. The same population feeds
three primitives — `_overlap_partner_counts`, `_polar_split`,
`_opening_majority_flags` — and the result drives the user-visible
"N of M models aligned" headline.

Some of the words being compared are not the models'. This system orders the
decision-support caveat verbatim (`synthesis._RECOMMENDATION_PROMPT` rule 1:
*"Always end with this sentence verbatim"*) and `synthesis_length._CaveatEnforcer`
appends it when it is missing.

### Measured on `main` (`b0a8b2a`), by executing the real functions

The caveat contains the word **"support"** ("decision support only"), and
`_polar_split` keys on `support`/`oppose` as a polar pair. A panel split 2-vs-2
in open disagreement, each answer carrying the caveat:

| | classification |
|---|---|
| bodies alone | `divided` |
| same bodies + caveat | **`strong`** |

A panel that openly disagrees was reported as agreement.

### A premise that had to be corrected first

The issue, and this ADR's first draft, said the caveat reaches the panel's own
answers. Refuted by execution: `providers.py` contains **0** occurrences of
"decision support" and does not import `_CaveatEnforcer`; the prompt that
mandates it is the *synthesizer's*, and it orders the sentence at the END while
`_excerpt` reads the FIRST 200 characters. The caveat therefore lands reliably
in the **final synthesis text** — which `_opening_reflected_in_final` compares
un-excerpted — and only incidentally in a model's own answer.

## Decision

Strip the caveat with **`safety.strip_own_caveat`**, applied **once, where the
population is built**, plus once on the final text inside
`_opening_reflected_in_final`.

- **Reuse, do not reimplement.** `safety.strip_own_caveat` already existed for
  this exact sentence — comma-tolerant, opening-optional — written after
  "adversarial review broke it 4 attempts out of 4". A hand-rolled
  whitespace-only matcher was written here first and is not kept: it missed the
  truncated form this app itself emits
  (`synthesis_length._truncate_with_caveat_present`) and a caveat with no oxford
  comma. Two matchers built from one constant drift.
- **At the population level, not per primitive.** This is what fixes the
  measured `_polar_split` defect above. An earlier draft stripped inside
  `_overlap_partner_counts` only, and `_polar_split` went on reading "support"
  out of the caveat.

### Rejected alternatives

- **Raise `_OVERLAP_JACCARD_THRESHOLD`.** The module's own comment explains the
  threshold is deliberately low to catch "all four models answer the same
  factual question with slightly different wording". Raising it trades a false
  positive for a false negative and loses the case the threshold exists for.
- **Stop mandating the caveat.** It is a safety disclosure; removing it to fix
  a scoring bug inverts the priority.
- **Generic boilerplate or stop-word detection.** Unmeasured, and it would
  discard model words we have no evidence are boilerplate. The set of sentences
  *this system dictates* is known exactly.

## Consequences

- A polar-opposed panel carrying the caveat now classifies `divided`.
- Genuine agreement is unaffected: four answers sharing substantive phrases
  still return `[3, 3, 3, 3]` with the caveat present (row 4).
- The templated fallback wording "This **is** decision support only…"
  (`synthesis.py:1064`) leaves a two-word residue "This is" after stripping.
  Every substantive word is removed, so it no longer clusters; the residue is
  recorded rather than claimed to be absent.
- **Deliberately NOT fixed here — part 2.** An answer produced without invoking
  a model (`ProviderPath.LOCAL_SIMULATION`) carries
  `providers._local_simulation_text`, one template differing only by the model
  id. Four such slots measure pairwise Jaccard **0.500–0.579** against the 0.1
  threshold, `_overlap_partner_counts` `[3, 3, 3, 3]`, and read as "4 of 4
  models aligned" for four models nobody asked. It is a separate concern: a
  13-test blast radius, of which four assert the present behaviour as correct
  (`test_synthesis.py:78` defends it in a comment), and it needs a decision
  about what demo mode should say and whether `provider_path` or the text
  itself is the right discriminator — `providers.py:546` shows a
  `LOCAL_SIMULATION` slot can carry live text. Filed as its own issue with this
  reproduction.

## Verification

- `tests/unit/test_consensus_boilerplate_blindness.py` — 7 tests, 7 input
  classes, each row mapped to the mutation that reddens it, including which
  rows are controls and which mutation does *not* touch them.
- Full suite after the change: 2280 passed, 0 failed.
