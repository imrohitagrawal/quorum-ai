# ADR-0149: The screenshot tests pin the Google Fonts stylesheet

## Status

Accepted — 2026-10-06, board row W41. The product owner chose this fix (CHG-031) after the
session found the cause of the trust-score screenshot flake. It replaces the 700 px allowance
of CHG-027 (e) and CHG-030, which was never merged. The allowance stays at 120 px, and the
exact-text check chosen in CHG-030 is kept.

## Context

`e2e/tests/invariants/trust-score-visual.spec.ts` compares the trust-score card
(`#result-trust-score`) against committed Linux images at 2 themes × 3 widths, allowing
120 differing pixels. It is part of a required merge check. It failed at random on unchanged
code.

### The failures (measured 2026-10-06)

Every failed attempt of every E2E workflow run created since 2026-09-10, the date of the last
commit to change the trust-score images (`c40b2e1`): 180 runs, each failed job's log read with
`gh api`. A run that passed when re-run still shows its failed first attempt here.

| Screenshot | Pixels different | Times seen |
|---|---|---|
| dark @ 1440 | 589 | 5 (one run failed it on both attempts) |
| dark @ 768 | 589 | 2 |
| light @ 1440 | 644 | 3 |
| dark @ 375 | 234 | 1 |

Two failures still had their images (runs 37473421803 and 36677984086, both light @ 1440). In
both, only the second half of the card's one bold sentence (font weight 600) had moved
sideways by a fraction of a pixel.

### The cause (measured 2026-10-06)

The page loads its fonts from Google Fonts: a stylesheet from `fonts.googleapis.com`, which
points at font files on `fonts.gstatic.com`. The test browser fetches it afresh in every test.

- Google usually answers with font addresses of the form `fonts.gstatic.com/s/…`. Both failed
  runs above received a different answer, with addresses of the form
  `fonts.gstatic.com/l/font?kit=…` (read from each run's saved trace).
- That second answer is a different version of the Geist font file. Measured with a font tool
  outside the browser (not in Chromium), its letter widths match the usual version at weights
  400, 500 and 700, and differ by about one font unit (1/1000 of the letter height), some wider
  and some narrower, at weights 550, 600 and 650: at weight 600, for 58 of 111 letters. The
  card's bold sentence uses weight 600.
- **Replaying that build** on CI's own Linux runner, against the committed images, gave the
  failures' exact numbers on every run (3 of 3 each): 644 px light @ 1440, 589 px dark @ 1440
  and dark @ 768, 234 px dark @ 375; also 644 px light @ 768 and 262 px light @ 375, which CI
  has not happened to hit. With
  the usual build, the same screenshots differ from the committed images by 0 px (run
  37507970530).
- **With the pin** (decision 1), the forced odd build gives 0 px on all six screenshots, 3 of 3
  runs each (run 37514492970).
- With the usual build, CI's browser drew the card identically in 2,368 screenshots at zero
  allowance (run 37504420419: 4 jobs of 592 screenshots, the 6 screenshots repeated about 100
  times; in 8 tests per job the question box never appeared, so no screenshot was taken). So
  nothing else in the card's drawing varies.
- In the 1,184 of those screenshots that fetched fonts live (2 jobs), Google never sent the
  second answer, so how often it does is not measured. Failures matching it occurred in 10 of
  the 180 runs above (2 confirmed from saved traces, 8 by their exact pixel counts).

### What a 700 px allowance would have cost (measured on macOS, 2026-10-06)

The owner first chose 700 px (CHG-027 (e), CHG-030). Deliberate defects, compared at zero
allowance against fresh macOS images (Linux counts may differ):

| Defect | Pixels (light 375 / 768 / 1440, dark 375 / 768 / 1440) | Missed at 700 |
|---|---|---|
| One word changed ("verified" → "checked") | 308 / 558 / 558, 286 / 519 / 519 | every width |
| The state line's text colour changed | 592 / 584 / 584, 612 / 609 / 609 | every width |
| The card's accent colour changed | 1211 / 647 / 647, 1211 / 647 / 647 | 768 and 1440 |
| One letter dropped ("checks" → "check") | 210 / 1420 / 1420, 194 / 1343 / 1343 | 375 |

The wording defects were confirmed with `curl` to be what the server sent; the colour defects
are confirmed by the screenshots changing. Before this change no test pinned the wording of the
card's state line or its other three lines (`git grep -F` for each line's text in `tests` and
`e2e` finds only two comments); the first line, the "Not verified"
disclosure, was already checked by `trust-score-invariants.spec.ts` and
`tests/unit/test_judge_disclosure_is_honest.py`.

## Decision

1. Both screenshot specs (`trust-score-visual.spec.ts` and `visual-snapshots.spec.ts`) answer
   the browser's Google Fonts stylesheet request with a saved copy of Google's usual answer,
   `e2e/fixtures/google-fonts.css`, through `pinGoogleFonts` in
   `e2e/fixtures/pinned-fonts.ts`. The font files themselves still come from Google, at the
   versioned `/s/` addresses that copy names. `e2e/fixtures/google-fonts.json` records where
   and when the copy was taken and its SHA-1.
2. The trust-score allowance stays at `maxDiffPixels: 120`; `visual-snapshots.spec.ts` keeps
   `maxDiffPixelRatio: 0.01`. No committed image changes.
3. The trust-score spec checks, before the screenshot, that the card shows exactly its expected
   lines, in order, at every theme and width (CHG-030). It reads the text the page lays out
   (`innerText`), so it does not see text added by CSS (`::before`, `::after`) and does see text
   made transparent with `opacity: 0`; the screenshot covers both.
4. `tests/unit/test_trust_score_visual_tolerance.py` pins, from the specs' code with comments
   removed: both tolerances, no screenshot tolerance set in `playwright.config.ts`, the pin
   called before each page load, the saved copy matching the stylesheet address in
   `workspace.html`, and the exact-text check. It reads code, so it cannot tell whether the
   route really serves the saved file; the e2e run on CI is the proof of that.

## Rejected alternatives

- **Allow 700 px** (CHG-027 (e), CHG-030). It treated the symptom, and missed wording and
  colour changes (table above).
- **Hide the bold sentence from the comparison** (offered in CHG-030). The cause is a font, not
  a line; any text at weight 550, 600 or 650 would flake the same way.
- **Save the font files too.** Removes the dependency on Google's servers during tests, but
  adds about 185 KB of binary fonts (the three files these pages load) to the repository for no
  measured gain: the `/s/` files returned the same bytes on every fetch measured.
- **Serve the fonts from the app itself.** It would also stop each visitor's browser contacting
  Google, but it changes what users download and the page's security policy; that is a product
  decision, not a test fix.
- **Retries.** The Playwright config defaults to zero retries (the repository's no-retry rule) and all five
  `npx playwright test` steps in `e2e.yml` pass `--retries=0`; nothing is retried
  automatically.

## Consequences

- The trust-score screenshots no longer depend on which answer Google sends.
- If the font link in `workspace.html` changes, the unit test fails until the saved stylesheet
  is captured again, and the screenshots change: the copy must be refreshed on purpose.
- If Google removes the `/s/` files the copy names, the screenshots fail on every run rather
  than at random.
- Visitors' browsers still receive whichever answer Google sends; the difference is a fraction
  of a pixel and is not a product defect.
