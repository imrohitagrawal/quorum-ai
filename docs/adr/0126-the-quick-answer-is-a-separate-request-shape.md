# ADR-0126: The quick answer is a separate request shape, priced and run as one answer plus the judge

## Status

Accepted — 2026-09-25, first of four pull requests. The owner decided the
mode on 2026-09-24 (CHG-012 D1, their words: *"Guard: separate mode:
"quick", Copy: "Quick answer — one model, no debate", show info message that
"four models by default, 2 debates and 1 sourced answer" which we have been
using in this product as a feature available, Price posture: judge on, cost
gate kept"*), and the rest that evening, recorded in
`docs/analysis/2026-09-24-w5-parked.md`: the judge's verdict shows in three
levels with reasons and evidence; *"I agree that we show no agreement figure
on quick answers. Rest I agree."*; and the judge does *"verification only"*.
The design below is the session's.

**This pull request changes nothing a user of the workspace can see.** The
browser never sends `mode`, so every run it starts is a panel, priced and
run exactly as before. A client calling the API directly can ask for a quick
answer from now on.

## Context

W4 made the panel two to four models and kept one model out (ADR-0087: a
lone answer has nothing to agree with). W5 is the one-model product the
owner asked for, as its own shape rather than a panel of one. The read-only
map of 2026-09-24 found that one slot is refused in four places (the request
validator, the estimator, the stage-detail word, the debate and synthesis
prompts) and that the measured receipt always emits the panel's four rows.

## Decision

1. **The request.** `mode: Literal["panel", "quick"] = "panel"` on the base
   the estimate and create requests share, so both price the same shape. A
   closed set: `"fast"` is a 422, not a priced panel.
2. **The count.** `mode: "quick"` takes exactly one model, refused otherwise
   with `A quick answer takes exactly one model.` (the typed
   `INVALID_MODEL_SLOT` envelope). The panel range is checked INSTEAD, never
   widened: one model without `mode` is still refused with `Between 2 and 4
   model slots are required.`, and `MIN_SLOT_COUNT` stays 2.
3. **The estimate and the bound** share `_cost_components` with
   `quick=True`: the one answer (its search context and fee as for any
   slot), the judge when one is configured, and no debate round, round-two
   critique input or synthesis. `by_stage` is `initial_answers` and `judge`;
   `by_model` is the model and the judge, with no writer row. The judge's
   reserve on the bound is unchanged, so it still reserves five synthesis
   sections of evidence a quick run never produces: loose, never short.
4. **The token** binds a third shape, `"quick"` (ADR-0123's vocabulary), so
   a quick quote cannot confirm a panel run of the same list, nor the
   reverse.
5. **The run.** `QueryRun.mode`, set at create and echoed on the create,
   result and active-run responses. After the one answer, debate and
   synthesis are stamped `skipped` with `Not part of a quick answer.`, the
   run goes `initial_answers_running` to `completed`, and no debate or
   synthesis service is called. The pipeline writes that status through
   `update_status`, which does not consult `ALLOWED_TRANSITIONS` (the panel's
   own `synthesis_running` to `completed` write does the same); the table
   gains the edge so it describes the pipeline, not because anything enforces
   it. A quick answer that fails lists only `initial_answers` as failed,
   with debate and synthesis stamped with the quick reason (tested for no
   usable answer and for no server key; the run-deadline path calls the
   same helper and has no quick test), and the notice
   `This quick answer did not complete. Review the failed step before relying
   on it.`, since there is no synthesis to rely on.
5a. **No follow-up context.** A quick request with a non-empty `context` is
   a 422 (`A quick answer takes no follow-up context.`), on the estimate,
   create and safety-warnings routes alike: the rule lives in the one
   `_check_context` the three share, so the probe never advises what create
   refuses (issue #155). The context is
   priced into and sent to debate and synthesis only, which a quick answer
   does not run, so accepting it would take the user's context and use none
   of it. Follow-ups on a quick answer were not among the owner's decisions;
   refusing is the honest default until they are.
6. **The receipt.** `build_measured_breakdown(quick=True)` emits the same
   rows as the estimate, and refuses debate or synthesis spend on a quick
   run, which demotes the receipt to `estimated` instead of hiding money.
7. **What is served.** `result.agreement` is `null` and
   `position_movements` is empty on a quick answer (the owner's decision).
   The evaluation is COMPUTED on every run, on the serving path and before
   the cost is read, because that is where a configured judge first
   dispatches: its dollar must be inside the figure the ledger books. On a
   quick answer it is then withheld (`evaluation: null`) until the second
   pull request gives it its own trust shape, since the panel composite would
   count one answer's "1 of 1" as agreement. The first draft skipped the
   computation instead, which moved the judge's first dispatch to
   persistence, after the booking; review measured the ledger short by the
   judge's cost, and
   `test_the_judge_dollar_is_inside_the_figure_the_ledger_books[quick]` now
   pins the order.
   **Known gap until the second pull request:** a quick run whose judge fires
   is billed for it, and the verdict is kept only in the in-memory memo the
   second pull request will serve from; it is not shown, stored or audited.
   Production is not affected today: live execution is off there
   (`/status` reads `live_execution: false`), every answer is a local
   simulation, and the judge is dispatched only for an answer outside
   `NOT_INVOKED_PATHS`, so it never fires on a production quick run.
8. **The run store** keeps its NOT NULL agreement columns; a quick run
   stores 0 of 0, "nothing measured", and no evaluation or trust row (the
   panel composite is not written for it). Nothing in `src/` reads the
   agreement columns back. The `mode` column and the quick evaluation row are
   the second pull request.

## Measurements

Measured on the `wp/w5-quick-backend` worktree at `81eee7a` plus this
change, and reproduced unchanged by review on the tree merged with #505
(ADR-0125) at `fb7ac48`. Static
price table (`_FALLBACK_CATALOG`), no network, no paid call. The judge is
priced as `openai/gpt-5-mini`, a judge the static table lists. Production's
judge was `openai/gpt-4.1-mini` in the 2026-09-10 telemetry (CHG-007); the
static table does not list it, and production's current setting is a secret
that was not read.

| run | point | bound | band | `by_stage` |
|---|---|---|---|---|
| default panel of four | $0.1074 | $0.1684 | allow | 5 rows |
| quick, `openai/gpt-4o-mini` | $0.0099 | $0.0162 | allow | answer $0.0078, judge $0.0021 |
| quick, `anthropic/claude-haiku-4.5` | $0.0150 | $0.0270 | allow | answer $0.0129, judge $0.0021 |
| quick, `google/gemini-2.5-flash` | $0.0116 | $0.0203 | allow | answer $0.0095, judge $0.0021 |
| quick, `nvidia/nemotron-3-nano-30b-a3b` | $0.0094 | $0.0151 | allow | answer $0.0073, judge $0.0021 |

Query: `What is the capital of Australia and why was it chosen?`.

Tests: `tests/integration/test_quick_mode_backend.py` and
`tests/unit/test_quick_mode_pricing.py`; RED before the change, mutation
results in the pull request.

## Rejected alternatives

- **A panel of one** (widening `MIN_SLOT_COUNT` to 1). The owner chose a
  separate mode; a panel of one also reaches the debate and synthesis
  prompts, which are undefined at one model.
- **A separate estimator.** It would drift from the panel's arithmetic; the
  shared function with a flag keeps one token model.
- **Trimming the judge's evidence reserve for quick.** It would make the
  bound tighter by pricing the judge from a smaller evidence block; that is
  a new money figure, and loose-but-safe needs no decision.

## Consequences

- Board row W5 is pinned on the composer sentence the third pull request
  adds, so it reads PENDING until the mode has a UI.
- The second pull request: the safety-notice carrier, the quick trust shape
  (the judge's verdict with reasons and evidence), and the run store's
  `mode` column. The third: the workspace control and result view, with its
  e2e spec. The fourth: the judge prompt, verification only.
- No FR or AC row yet: nothing is user-visible until the third pull request,
  which adds them with the tests that trace them.
