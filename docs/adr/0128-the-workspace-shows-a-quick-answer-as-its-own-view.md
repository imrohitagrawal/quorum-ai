# ADR-0128: The workspace shows a quick answer as its own view

## Status

Accepted — 2026-09-25, W5's third of four pull requests. The product owner
decided on 2026-09-24 (CHG-012 D1, their words): *"Guard: separate mode:
"quick", Copy: "Quick answer — one model, no debate", show info message that
"four models by default, 2 debates and 1 sourced answer" which we have been
using in this product as a feature available, Price posture: judge on, cost
gate kept"*; and that evening (`docs/analysis/2026-09-24-w5-parked.md`):
*"Judge: well supported/partly supported/not supported along with reasons and
artifacts to support why well supported/partly supported/not supported."* and
*"I agree that we show no agreement figure on quick answers."*

Those words are the owner's. **Every other choice below is the session's
design**, listed as such under "Decisions the owner did not make".

## Context

ADR-0126 gave the API a `mode: "quick"` request (one model, no debate or
synthesis, judge priced when configured) and ADR-0127 made a finished quick
answer carry `quick_verdict` and `result.safety_notice`. The browser never
sent `mode`, so no user could reach either. The read-only map of 2026-09-24
(the parked page, "Why it is not one pull request") listed what the
workspace assumed about a panel: no result renderer for a single answer, a
live strip and a cost gate that name four stages, "Initial answers × 4", a
degraded banner that reads "None of the 1 models", and thirteen e2e files
that wait on the verdict band. It also found one the map did not name, by
reading the terminal branch: the poll opens the result view only when a
synthesis exists, so a quick answer, which has none by design, would have
stayed on the live view for ever.

## Decision

1. **The control.** A checkbox in the model-slot fieldset, labelled "Quick
   answer — one model, no debate". While it is on, the fieldset carries
   `data-quick="true"` and CSS hides slots 2 to 4, the remove and add
   controls, the "Choose two to four" help line and the panel shape line; the
   note "four models by default, 2 debates and 1 sourced answer" is shown.
   Turning it off removes the attribute and hides the note, nothing else.
   It starts off on every page load.
2. **The requests.** `runRequestBody` builds both bodies. A panel body is the
   pre-W5 body, key for key and in order. A quick body sends slot 1 alone and
   `mode: "quick"`. Neither ever sends `context`: the browser sends none on
   any run (the follow-up box only pre-fills the composer), so nothing had to
   be disabled to honour ADR-0126's refusal of quick follow-up context.
3. **The cost gate.** A quick estimate's meta line reads "1 model · no debate
   · judge check · sourced answer where search succeeds" when the estimate
   priced a stage besides the answer (the judge), and "… · no judge configured
   · …" when it did not, because a deployment with no judge runs none. The
   stage row reads "The answer" instead of "Initial answers × 4".
4. **The result view.** A quick result hides the verdict band and ring, the
   trust cards, the trust score, the debate, the synthesis card and the
   transcript link (their content is cleared too) and shows `#result-quick`:
   the safety notice when the result carries one; the judge's verdict,
   headed "Judge: Well supported / Partly supported / Not supported / Not
   checked" from `quick_verdict.level`, with the scores, the app-written
   reasons as a list, the sources the judge checked, and one sentence saying
   the scores are not calibrated; then the answer through `setProse`, its
   source chips (the synthesis card's builder, moved into
   `buildSourceChipRow` unchanged) and a sentence from its citation coverage.
   A later panel run un-hides the band, the trust cards and the transcript
   link; the other three set their own visibility when they render.
5. **What is read.** `quick_verdict.level`, `faithfulness`, `grounding`,
   `hallucination_risk`, `reasons` and `sources_checked`. Never
   `judge_status`: the D-5 guard in
   `tests/unit/test_evaluation_projection_has_no_judge.py` stays closed and
   green.
6. **The sources the judge checked are plain text**, "title — address",
   not links. The same citations are already safe links in the Sources row
   beneath, and `judge_evidence_sources` may have truncated these copies, so a
   second set of anchors would add only broken or duplicate links.
7. **The shortfall banner at one model.** `describePanelShortfall` takes
   `quick` and returns its own two sentences (no answer; a simulated answer);
   every panel string is unchanged.
8. **Copy and Export.** A quick Copy summary: question, "Quick answer (one
   model, no debate) from <model>:", the answer, the judge's heading, the run
   id. A quick Export: provenance first (the one-model banner when the answer
   was not live), the mode, the judge's section with reasons, scores and
   checked sources, the safety notice, the answer through the same
   sanitiser as the panel export, and the shared Sources lines
   (`sourcesMarkdownLines`, moved out of the panel export unchanged). Neither
   carries an agreement figure; "Live model answers: N of M" becomes "Answer:
   from a live model / from Quorum's local simulation / none returned".
9. **The live view.** A quick run's stage strip shows the answer stage
   alone, and the debate area and its caption are hidden.
10. **The transition.** `resultIsShowable` opens the result view for a panel
    run with a synthesis (as before) or a quick run with its answer.

## Measurements

On `wp/w5-quick-ui`, based on `9b0c9da`; no network except localhost, no paid
call.

| what | result |
|---|---|
| RED before the change | `tests/unit/test_quick_answer_ui.py`: 9 failed, 1 passed (the landing check, a negative with its partner, passes either way); `quick-answer.spec.ts`: 8 of 8 failed |
| panel views byte-identical | outerHTML of the composer, the result view (before and after Copy/Export), the transcript and the cost gate, the Copy text, the Export file and both request bodies, dumped on `goldenCompletedResp()` before and after: the bodies, Copy, Export, transcript and cost gate are byte-identical; the composer and result view are identical once the two new, hidden nodes (`#quick-mode`, `#result-quick`) and their HTML comments are removed and whitespace between tags is collapsed |
| the first blocking e2e lane | 298 passed on `9b0c9da`; recorded with this change in the pull request |
| a real quick run | the local server (simulation) served `mode: "quick"`, five progress stages with debate and synthesis `skipped`, `agreement: null`, `final_synthesis: null`, `quick_verdict.level: "not_checked"`, `safety_notice: null` for a non-high-stakes question; the e2e fixture follows that shape |

## Decisions the owner did not make (the session's)

- Where the control sits (top of the model-slot fieldset) and that it is a
  checkbox; hiding the "Choose two to four" help line while it is on.
- The "Not checked" heading and its sentence; the order of the quick result
  (notice, verdict, answer); the scores line wording; the calibration
  sentence; the level colours (blue, amber, red, grey — never the consensus
  green).
- Plain-text sources the judge checked (decision 6).
- The quick cost-gate sentence, "no judge configured", and "The answer" as
  the stage label.
- The one-model banner sentences, the quick Copy and Export shapes, the
  completion toast "Run completed. See the answer below."
- The live view's single stage and hidden debate area.
- Sending no follow-up context rather than disabling the control during a
  follow-up (decision 2).

## Rejected alternatives

- **A panel of one on the panel view.** The ring would read "1/1 carried" and
  the trust composite would score one answer as agreement: the figure the
  owner decided against.
- **Rebuilding the slot grid with one card while on.** It would have to
  re-render the other three on the way back, so "off" could not be proved
  identical to the page before; hiding by attribute makes it trivially so.
- **Linking the judge's sources.** Decision 6.
- **Reading `judge_status`** to say why a verdict is missing. It would open
  the D-5 guard for a sentence the level already implies.

## Consequences

- Board row W5 derives DONE: its needle is the control's label. The fourth
  pull request, the verification-only judge prompt, is still open; the row's
  title and section say so.
- FR-018 and AC-051 trace the behaviour; `quick-answer.spec.ts` joins the
  first blocking lane, and AGENTS.md's invariant spec count is 22.
- The visual baselines are untouched: `goldenCompletedResp()` is unchanged
  and the two new nodes are hidden on a panel run.
