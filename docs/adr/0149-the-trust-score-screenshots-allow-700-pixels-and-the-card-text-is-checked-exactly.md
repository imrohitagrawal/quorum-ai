# ADR-0149: The trust-score screenshots allow 700 pixels, and the card's text is checked exactly

## Status

Accepted — 2026-10-06, board row W41. The value is the product owner's (CHG-027 (e): *"allow
700 px, those screenshots only"*, replacing the 589 px of CHG-026 (k)). The exact-text check
is the owner's choice after seeing what 700 px stops catching (CHG-030).

## Context

`e2e/tests/invariants/trust-score-visual.spec.ts` compares the trust-score card
(`#result-trust-score`) against a Linux baseline at 2 themes × 3 widths, with
`maxDiffPixels: 120`. It is a blocking check. It fails at random on unchanged code, which
blocks merges until someone re-runs the job.

### What the flake looks like (measured 2026-10-06)

Every failed attempt of every E2E workflow run created since 2026-09-10, the date of the
last commit to change the baselines (`c40b2e1`): 180 runs, each failed job's log read with
`gh api`. A run that passed on a re-run still shows its failed first attempt here.

| Screenshot | Pixels different | Times seen |
|---|---|---|
| dark @ 1440 | 589 | 5 (one run failed it on both attempts) |
| dark @ 768 | 589 | 2 |
| light @ 1440 | 644 | 3 |
| dark @ 375 | 234 | 1 |

The largest is 644 px. The diff image from today's failure (run 37473421803, light @ 1440)
shows where: only the second half of the bold caveat sentence ("…thesis did not include
one.") is shifted by a fraction of a pixel. The rest of the card matches. Older runs' images
have expired, so the dark-theme cases were not inspected.

On this Mac, with freshly made local baselines and no allowance at all, the unchanged spec
matched 60 times out of 60 (`--repeat-each=10`). The flake is a CI rendering effect; its cause
is not known.

### What 700 px stops catching (measured 2026-10-06)

Deliberate defects, each served by a fresh local server (the mutated bytes confirmed with
`curl`), compared with no allowance against fresh local baselines. Pixels per screenshot,
light 375 / 768 / 1440, then dark 375 / 768 / 1440:

| Defect | Pixels | Caught at 120 | Caught at 700 |
|---|---|---|---|
| One word changed ("verified" → "checked") | 308 / 558 / 558, 286 / 519 / 519 | all | none |
| The state line's text colour changed | 592 / 584 / 584, 612 / 609 / 609 | all | none |
| The card's accent colour changed | 1211 / 647 / 647, 1211 / 647 / 647 | all | 375 only |
| One letter dropped ("checks" → "check") | 210 / 1420 / 1420, 194 / 1343 / 1343 | all | 768 and 1440 only |
| The disclosure's font size changed | 4213 to 13659 | all | all |

The accent-colour, one-letter and font-size defects also passed all 119 tests in
`trust-score-invariants`, `verdict-band`, `rendering-invariants` and `axe-all-views`. No test
pins the card's wording: `git grep "Structural checks passed" -- tests e2e` finds only a
comment and a page-object docstring.

## Decision

1. `trust-score-visual.spec.ts` passes `maxDiffPixels: 700` to every screenshot it takes.
   `visual-snapshots.spec.ts` keeps `maxDiffPixelRatio: 0.01`.
2. The same spec checks, before the screenshot, that the card shows exactly its expected
   lines of text, in order, at every theme and width. A changed word, a dropped letter or an
   added line fails deterministically, whatever the pixel count.
3. `tests/unit/test_trust_score_visual_tolerance.py` pins both tolerances by reading the
   specs' code (comments removed), so a later edit cannot widen either one unnoticed.

## Rejected alternatives

- **Keep 120 px and hide the caveat line from the comparison** (offered to the owner in
  CHG-030). It would catch more, but it is not the value the owner decided.
- **700 px with no text check** (also offered). The card's wording would then have no check
  at all.
- **Retries.** The Playwright config defaults to zero retries (RB-4) and all five
  `npx playwright test` steps in `e2e.yml` pass `--retries=0`, so a failure is never hidden
  by a second try.
- **`maxDiffPixelRatio`.** A ratio scales with the image; on the 1440 px card 1% is about
  1,600 px, more than 700 and harder to reason about.
- **Re-seeding the baselines.** The flake happens on unchanged code against an unchanged
  baseline; a new baseline would flake the same way.

## Consequences

- The trust-score lane stops failing on the differences seen so far (all at or below 644 px).
  A difference above 700 px still fails.
- Still not caught by any check: a text or accent colour change in the card at 768 or 1440 px
  (584–647 px). The owner accepted this in CHG-030.
- If CI ever shows a flake above 700 px, this value is wrong; the owner decides the next one.
