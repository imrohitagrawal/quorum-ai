# ADR-0127: A quick answer shows the judge's verdict, its reasons and the sources it checked

## Status

Accepted — 2026-09-25, W5's second of four pull requests. The owner decided
what a quick answer shows on 2026-09-24 (recorded in
`docs/analysis/2026-09-24-w5-parked.md`, their words): *"Judge: well
supported/partly supported/not supported along with reasons and artifacts to
support why"*; *"I agree that we show no agreement figure on quick answers.
Rest I agree."* (the rest being the session's recommendations: carry the
safety caveat onto a quick answer, and store the run as quick). The mapping
from the judge's scores to three levels, and every mechanism below, are the
session's design. **Backend only**: the browser never sends `mode` until
W5's third pull request, so nothing changes for the workspace.

## Context

ADR-0126 made a quick answer serve no evaluation, because the panel's trust
composite would score one answer's "1 of 1" as agreement. The served result
carries no judge text at all (decision D-5), because the judge's
`rationale` is model-written text about provider prose. The owner's decision
needs a quick answer to show exactly that. Failure modes were listed before
the code: `docs/analysis/2026-09-25-w5-quick-verdict-failure-modes.md`.

## Decision

1. **`quick_verdict` on the result**, `null` on every panel run: `level`,
   `reasons`, `sources_checked`, `judge_status`. Built in
   `src/product_app/quick_verdict.py` after the evaluation has run (the
   judge dispatches there, ADR-0126), from the per-run judge memo.
2. **Four levels, not three.** `not_checked` whenever there is no conforming
   verdict (no judge configured, the call failed, a non-conforming answer),
   so a level is never shown that the judge did not give. Otherwise:
   `not_supported` whenever `verdict_supports_verification` refuses it (a
   zero, or high risk; #267); `well_supported` when faithfulness and
   grounding are both 4 or more (`WELL_SUPPORTED_MIN_SCORE`) and risk is
   low; `partly_supported` otherwise. The threshold is a design choice, not
   a calibration: nothing in this repo measures what a judge's 4 means.
3. **Reasons as plain text.** The judge's rationale, with every URL reduced
   to its host, so an injected page cannot put a clickable destination under
   the product's "Judge" label. Capped at 4,000 characters by the verdict
   schema. The UI must render it as text, never through the Markdown
   renderer; that is the third pull request's contract.
4. **The sources the judge saw**, from `judge_evidence_sources`, now the one
   function `build_judge_evidence` also uses to number the prompt's SOURCES
   block, so the served list cannot drift from the judge's (capped at
   `JUDGE_MAX_SOURCE_LINES`, fields truncated as the judge read them).
5. **The safety caveat.** `result.safety_notice` on a quick answer is the
   synthesis's own `HIGH_STAKES_NOTICE_FRAGMENT`, decided by the same rule,
   now the module function `high_stakes_required` (query and context).
   `null` on panel runs, which keep `final_synthesis.high_stakes_notice`.
6. **The run store's `mode` column.** Added in place to an existing database
   (`ALTER TABLE runs ADD COLUMN mode TEXT NOT NULL DEFAULT 'panel'` when
   absent), so every run stored before W5 reads "panel"; the orchestrator
   writes the run's mode. Nothing of the verdict's text is stored.
7. **D-5 narrowed, deliberately.** `quick_verdict.reasons` is the one path
   by which judge prose reaches a client; the keys `judge` and `rationale`
   stay banned at every depth of the served schema, the served evaluation
   projection still has no judge field, and the frontend ban is unchanged
   until the UI pull request, which must justify its own change.

## Measurements

On `wp/w5-quick-served` at `e8c7503` plus this change; no network, no paid
call; the judge seam is stubbed.

| what | result |
|---|---|
| the level table, boundaries on both sides | `test_the_level_follows_the_verdict`: 8 cases pass (4/4/low well; 4/3 and 5/5/medium partly; 1/1/low partly; a zero or high risk not supported) |
| RED before the change | the new test file fails at import (`product_app.quick_verdict` does not exist); the 14 tests written first all failed |
| full suite | `4749 passed, 67 skipped` before the registry entry; gates in the pull request |
| mutations (copy aside, clear `__pycache__`, restore, `cmp`; baseline 123 passed) | 12 of 12 killed: the threshold 4 to 3; low risk dropped; the refusal rule dropped; no verdict read as partly; URLs served whole; sources uncapped; a panel run given a verdict; no safety notice; no migration; stored mode always "panel"; the verdict read without the memo; reasons dropped |

## Rejected alternatives

- **Three levels only.** A missing verdict would have to borrow one of them,
  which is failure mode 2.
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
  `not_checked`.
- The third pull request renders `quick_verdict` and `safety_notice`, and
  adds the FR and AC rows.
- The judge's prompt still says it scores "one multi-model answer"; the
  fourth pull request changes it for quick answers.
