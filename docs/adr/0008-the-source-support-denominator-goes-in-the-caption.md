# ADR-0008: the Source support denominator goes in the caption, and states no exclusion count

## Status

Accepted — 2026-08-04 (issue #193)

## Context

The "Source support" trust card rendered a bare percentage:

```
Source support
75%   · 5 sources cited
Share of the answers that came back carrying a primary source.
```

#171's enforcement rule, quoted verbatim in issue #193, requires: *"every
user-facing trust number must state its denominator and what it excluded —
'coverage 100% (4 of 4 answers, 0 excluded)', never a bare '100%'."* A bare 75%
names no denominator: "3 of 4" and "15 of 20" are both 75% and are very
different claims.

Two decisions had to be made, and both are reversible, which is why they are
recorded rather than left implicit in a diff.

## Decision 1 — the counts go in the CAPTION, not on the value line

The first implementation (PR #236, abandoned) put them on the value line:
`75% (3 of 4 answers)`. Measured against the rendered card, that is wrong.

| Surface | What it renders | Measured at |
|---|---|---|
| Agreement card, VALUE | `3 of 4` (+ sub `aligned`) | `app.js`, the `accent: "agreement"` card |
| Source support card, VALUE | `75%` (+ sub `· 5 sources cited`) | `app.js`, the `accent: "source"` card |
| Both | siblings in the same 3-up `#result-trust` grid | `workspace.html`, `#result-trust` |

The two cards sit side by side. `75% (3 of 4 answers)` puts a bare fraction
directly beside a card whose headline value *is* a bare fraction, measuring an
unrelated quantity — how many models AGREED versus how many answers CITED A
SOURCE. On the golden fixture both are literally `3 of 4`. The value line also
already carries `· 5 sources cited`, a third quantity, so the reader is invited
to compute 75% of 5.

The caption already existed and already stated the meaning without numbers, so
moving the counts there **replaces** a generic sentence instead of adding a
fourth number:

```
Source support
75%   · 5 sources cited
3 of 4 answers came back carrying a primary source.
```

### Rejected alternatives

- **Counts on the value line** (`75% (3 of 4 answers)`). Rejected for the
  collision above, and because it widens the value line in a 3-up grid that is
  already tight at 375px.
- **Drop the percentage from the verdict band's coverage-caution line so the
  number appears once.** Rejected on evidence: that line is where WP-B/F-18 is
  pinned (`verdict-band.spec.ts`, "a genuine 0% coverage IS still reported"),
  and it needs a magnitude — 79% and 0% are both "below target" and mean very
  different things. The duplication that remains is one number, on failing runs
  only, with a warning attached that the card does not carry.
- **Show the counts only when the coverage target is missed.** Rejected: the
  bare percentage is least defensible on a *good* run, where no caution line
  exists to explain it.

## Decision 2 — no exclusion count is displayed

#171's rule has two halves. This builds the denominator and NOT the "K
excluded" half. Reasons, in order:

1. It is not a served field. `CitationCoverage` carries `answer_count`,
   `sourced_answer_count` and `sourced_answer_ratio`. The exclusion count would
   be the slot count minus `answer_count`, and the slot count lives on a
   different object (`AgreementSummary.total`). Deriving one number from two
   objects that are documented to count different populations is how the
   denominators diverge in the first place (see Consequences).
2. A third number is the density the issue's own reporter objected to.

This is the reversible half of this ADR. Reversing it means adding the slot
count to `CitationCoverage` and extending `sourceSupportCaption`.

## Decision 3 — the caption must agree with the percentage above it

Found by adversarial review, not by design. `coveragePct` comes from
`sourced_answer_ratio`; the counts come from two other fields; nothing made them
consult each other. Reachable results before the fix:

| Payload | Value line | Caption |
|---|---|---|
| `ratio: ""`, counts 4/3 | `—` | `3 of 4 answers…` — hands back the 75% the card just suppressed |
| `ratio: "0.10"`, counts 4/3 | `10%` | `3 of 4 answers…` — two numbers on one card that contradict |

`CitationCoverage` validates `sourced <= answer` but never checks the ratio
against the counts, so no server-side guard covers this. The caption now renders
only when a usable ratio exists AND agrees with the counts to within 0.01 (the
ratio is quantised to 2dp upstream, so the tolerance covers rounding only).

## Consequences

- **The two cards can show different denominators on a degraded run, and that is
  correct.** `AgreementSummary.total` counts every initial answer *including*
  failed ones (`debate.py`); `citation_coverage.answer_count` excludes them
  (`synthesis.py` — failed/cancelled/deadline-exceeded slots carry 0). So one
  failed slot out of four renders "2 of 4 aligned" beside "1 of 3 answers came
  back…". The words "came back" carry the distinction. Recorded because it looks
  like a defect to anyone who has not read both definitions.
- **"3 of 4" can appear three times on one screen** — the verdict band's "3 of 4
  models aligned", the Agreement card's value, and this caption — when the
  alignment and sourcing counts coincide. Two of those three are pre-existing
  and are the same measurement shown twice.
- **The `sourced > total` clause is now unreachable** and is kept as defence in
  depth, documented as unprovable by any test while decision 3 stands.
- **A visual baseline reseed is required before merge.** The change alters
  rendered text inside the region `visual-snapshots.spec.ts` photographs, and
  that lane is blocking.

## Verification

- `e2e/tests/invariants/source-support-denominator.spec.ts` — 20 tests, an
  input-class table in the header, each row mapped to the mutation that reddens
  it. Every mapping except the `sourced > total` clause was run and confirmed.
- Invariants lane re-measured end to end: `187 passed (3.7m)`; floor raised
  167 → 187.
