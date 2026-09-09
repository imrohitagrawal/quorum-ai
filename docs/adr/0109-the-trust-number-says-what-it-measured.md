# ADR-0109: The trust number says what it measured

## Status

Accepted — 2026-09-09.

**Authorises nothing.** No `**Authorises:**` line; it may not be cited to
sanction a live-execution posture.

## Context

The verified trust panel read `92 of 100 — high trust` and nothing else. It
named no scale and said nothing about what had been examined, so a reader could
not tell whether it was a claim about the ANSWER (it is not) or about automated
structural checks on the run's own output (it is).

Three facts established before designing anything:

- The composite is a weighted blend of seven signals (`LAYER_A_WEIGHTS`,
  `evaluation.py:1105`). The judge is a **gate** (`support_verified`), not the
  scorer — `TrustDiagnostics`' own docstring says "the judge never enters this
  arithmetic".
- `trust.diagnostics.contributions` was **already served** (`openapi.yaml`) and
  **already read** (`app.js`), but rendered only as up-to-three NEGATIVE lines
  for contributions below 1.0. **The data existed; only the display was
  missing.** No API change.
- The number in the repo is **92**, not the 96 the report quoted. `96` is the
  shape, not a value any fixture carries.

## Decision

Explain it on the **VERIFIED branch only**, and say what the number is not.

Three additions: a one-sentence basis line, a `TRUST_SIGNAL_LABELS` map, and a
list of the checks the run passed outright. The existing "why" list keeps the
ones that fell short, so the two together account for the signals the composite
actually weighed.

**No neutral label map existed.** `TRUST_WHY` was the only signal-key-to-English
map in the codebase and every string in it is a failure phrasing ("Not every
answer came from a live model"), unusable for saying what a run got right. That
is why the panel could list shortfalls and never say what was checked.

The met-list is driven off the **served** contributions array, never a hardcoded
seven: when `citation_marker_grounding` is unknown the server drops it and
renormalises the rest, so a run can legitimately carry six.

## Why verified-only is the right scope, not a shortcut

The unverified treatment is under a deliberately blunt contract (D-2): zero
digits, zero advisory-label words, no raw signal identifiers. The unexplained
headline **only ever appears on the verified branch**, so the explanation
belongs there and nowhere else.

It also happens to cost nothing in baselines. Every committed screenshot in
`trust-score-visual.spec.ts` drives `EVAL_MISSING_HIGH_STAKES`, which is
UNVERIFIED — as are six of the seven variants; `EVAL_VERIFIED_HIGH` is the only
verified one. **Measured, not assumed:** the surface's `outerHTML` was dumped
before and after the change on that variant and diffed **byte-identical**. So
the Linux baselines do not move and no CI re-seed is on this PR's path. Rule 13e
forbids trusting a local pixel comparison; an HTML diff is what it permits
instead.

A boundary test pins the scope, so "render it everywhere" cannot pass.

## Consequences

- Four new tests in the blocking invariants lane; the R3 identifier ban is
  re-asserted over the new lines.
- A verified-branch overflow check at 375/768/1440. The existing overflow test
  drives an unverified variant, so the branch that actually grew was not covered.
- New text uses `--text-secondary` on the existing tinted grounds, the pairing
  the a11y contrast walk already accepts; the D-6 GREEN RULE still holds.

## What this does NOT do

It does not defend the weights. `evaluation.py:1090-1104` records that their
exact magnitudes are "a judgement call, not a measurement", and that remains
true and unaddressed here. This change makes the composite legible, not correct.
