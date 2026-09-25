# ADR-0127: A quick answer shows the judge's verdict, its reasons and the sources it checked

## Status

Accepted — 2026-09-25, W5's second of four pull requests. The owner decided
what a quick answer shows on 2026-09-24 (recorded in
`docs/analysis/2026-09-24-w5-parked.md`, their words): *"how the judge's
verdict should display for single-model answers: Judge: well
supported/partly supported/not supported along with reasons and artifacts to
support why well supported/partly supported/not supported."*; *"I agree that
we show no agreement figure on quick answers. Rest I agree."* The "rest" is
the session's recommendation as the parked page words it: "the pre-question
safety check's warnings are carried onto the quick-answer result page", and
the run is stored as quick. This pull request carries only the HIGH-STAKES
caveat, not the always-on sensitive-data warning, because the high-stakes
caveat is the one the panel's synthesis shows; that narrowing is the
session's. The mapping
from the judge's scores to three levels, and every mechanism below, are the
session's design. **Backend only**: the browser never sends `mode` until
W5's third pull request, so nothing changes for the workspace.

## Context

ADR-0126 made a quick answer serve no evaluation, because the panel's trust
composite would score one answer's "1 of 1" as agreement. The served result
carries no judge text at all (decision D-5), because the judge's
`rationale` is model-written text about provider prose. The owner's decision
needs a quick answer to show the verdict, its reasons and its evidence.
Failure modes were listed before the code: `docs/analysis/2026-09-25-w5-quick-verdict-failure-modes.md`.

## Decision

1. **`quick_verdict` on the result**, `null` on every panel run and on a
   quick run that has not finished (no judge has been asked yet): `level`,
   the judge's `faithfulness`, `grounding` and `hallucination_risk`,
   `reasons`, `sources_checked`, `judge_status`. Built in
   `src/product_app/quick_verdict.py` after the evaluation has run (the
   judge dispatches there, ADR-0126), from the per-run judge memo.
2. **Four levels, not three.** `not_checked` whenever there is no conforming
   verdict (no judge configured, the call failed, a non-conforming answer),
   so a level is never shown that the judge did not give. Otherwise:
   `not_supported` whenever `verdict_supports_verification` refuses it (a
   zero, or high risk; #267); `well_supported` when faithfulness and
   grounding are both 4 or more (`WELL_SUPPORTED_MIN_SCORE`), risk is low,
   AND the judge was shown at least one source (a verdict on an answer it
   could check against nothing cannot read "well supported");
   `partly_supported` otherwise. The threshold is a design choice, not a
   calibration: nothing in this repo measures what a judge's 4 means.
3. **Reasons in the app's words, never the judge's.** `reasons` is a list of
   sentences this app writes from the judge's three scores and the number of
   sources it checked. The judge's own `rationale` is not served anywhere.
   It is model-written text about provider prose, and a cited page can steer
   it. The first draft of this pull request served it after reducing every
   link to its host. Two review rounds kept finding shapes that got through,
   among them a URL glued to a word, HTML-entity schemes, IPv6 hosts and
   soft-hyphen splits, and the cleaning itself could lengthen the text past
   its limit, which failed the response. Cleaning free text with a pattern is
   a list of known bad shapes, and the list was never complete, so the
   approach was dropped (see "Re-planned" below).
4. **The sources the judge saw**, from `judge_evidence_sources`, now the one
   function `build_judge_evidence` also uses to number the prompt's SOURCES
   block, so the served list cannot drift from the judge's (capped at
   `JUDGE_MAX_SOURCE_LINES`, fields truncated as the judge read them). These
   are the answer's own citations, which a panel page already shows.
5. **The safety caveat.** `result.safety_notice` on a quick answer, running
   or finished, is the synthesis's own `HIGH_STAKES_NOTICE_FRAGMENT`, decided
   by the same rule, now the module function `high_stakes_required` (query
   and context). `null` on panel runs, which keep
   `final_synthesis.high_stakes_notice`.
6. **The run store's `mode` column.** Added in place to an existing database
   (`ALTER TABLE runs ADD COLUMN mode TEXT NOT NULL DEFAULT 'panel'` when
   absent), so every run stored before W5 reads "panel"; a second process
   losing the race to add it ("duplicate column name") opens normally, and
   any other error still stops the store. The orchestrator writes the run's
   mode. Nothing of the verdict is stored.
7. **D-5 stays whole.** No judge-written text reaches a client; the served
   evaluation projection has no judge field; the keys `judge` and
   `rationale` stay banned at every depth; a sentinel rationale is pinned to
   reach no quick and no panel response.

## Re-planned after two review rounds

Round 1 found that the link cleaning let full URLs through; its fix widened
the cleaning, and round 2 found both more shapes and a new defect the fix
introduced (the cleaned text could exceed its 4,000-character limit and fail
the response, which also skipped the run's billing correction). Two fixes in
a row adding defects is this repo's signal to change the approach rather
than patch again (AGENTS.md rule 12). The root cause was serving free,
steerable text at all. The replacement serves only values the app controls:
an enum, three integers or enums from the judge's strict schema, sentences
the app writes from them, and citations the answer already carries. The
owner's "reasons and artifacts" are met by the scores, the app's sentences
and the sources; the judge's per-claim evidence, pointing into text already
on the page, is W5's fourth pull request.

## Measurements

On `wp/w5-quick-served` at `e8c7503` plus this change; no network, no paid
call; the judge seam is stubbed.

| what | result |
|---|---|
| the level table, boundaries on both sides | `test_the_level_follows_the_verdict`: 8 cases pass (4/4/low well; 4/3 and 5/5/medium partly; 1/1/low partly; a zero or high risk not supported) |
| RED before the change | the 14 tests written first all failed on the pre-change source (no `quick_verdict` field, no `safety_notice`) |
| full suite and mutations on the final head | recorded in the pull request |

## Rejected alternatives

- **Three levels only.** A missing verdict would have to borrow one of them,
  which is failure mode 2.
- **Serving the judge's rationale, cleaned.** Built, reviewed twice, and
  dropped; see "Re-planned".
- **Serving the rationale through the evaluation projection.** It would open
  D-5 for panel runs too.
- **Per-claim evidence now.** Today's verdict has no claim list; it needs the
  verification-only judge prompt, W5's fourth pull request.
- **Rebuilding the runs table.** A rebuild on a production volume risks the
  rows it copies; an in-place `ADD COLUMN` with a default does not.

## Consequences

- An API client asking for a quick answer now receives the judge's verdict
  when a judge ran. In production today none does: live execution is off, so
  quick answers are local simulations, which are never judged; they read
  `not_checked` (production's `/status` read `live_execution: false` on
  2026-09-25).
- The third pull request renders `quick_verdict` and `safety_notice`, and
  adds the FR and AC rows.
- The judge's prompt still says it scores "one multi-model answer"; the
  fourth pull request changes it for quick answers.
