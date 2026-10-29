# ADR-0187: The workspace shows one run at a time

## Status

Accepted — 2026-10-30, board rows W127 and W49. It makes the page meet rules the owner has already
accepted: ADR-0140's calls (CHG-027 (b)), among them that going home drops anything still in flight
for the question being left and that Back returns to the view the user left. No new owner decision
was needed. Everything below about how those rules are met is the session's design; Codex reviewed
the plan twice before any code.

## Context

The workspace is one page (`src/product_app/static/app.js`). Every region a run fills (the live
view, the result, the transcript) survives into the next run unless something clears it. Before
this decision each way into a run reset its own hand-picked list of fields, and no answer was
checked against the run it was asked for:

- `pollRun` drew whatever its GET returned, then checked one page-wide flag,
  `state.terminalHandled`, which outlived its run. Polls overlap (one every 750 ms, whether or not
  the last one has answered).
- Stop (`cancelRun`) toasted "Run cancelled." whatever the DELETE returned, opened a result only
  when `final_synthesis` existed, and wrote no "This session" entry.
- "Go to run" (`goToActiveRun`, W49) kept the finished run's flag and question.
- A session-list click (`restoreTrailRun`) drew whichever GET answered last, and kept the error
  card of the run before.
- The composer's running total was written once by `estimateRun` and reset only by the
  high-stakes hold. The slot cells took the estimate's rows by position onto whatever panel was
  there when it answered.
- `.live-debate` sets `display: flex`, which beats the `hidden` attribute, and nothing overrode it.

## Decision

1. **One run scope.** `state.runScope = {id, runId, terminalHandled, closed}` names the run the
   page is showing. `beginRunScope(runId, question?)` replaces it (never resets it in place) on
   every move that changes which run is current: a new run, "Go to run", the boot path and a
   session-list restore. It drops what the page kept for the previous run, untags every
   run-scoped region and empties the live view's run content. An adopted run has no question the
   page knows (`ActiveQueryRunResponse` carries none), so it shows "—", never the composer's text.
   Navigation never clears the scope, so Back to a kept result still names its run.
2. **Every answer is checked against the scope it was asked for, before anything is drawn.** A poll
   captures the scope as it is sent and is dropped unless that scope is still current, open and
   not finished, and the answer is for its run. A failed poll is checked the same way, so it raises
   no connection notice after Stop. A restore is drawn only while its click is the latest one and
   the view has not changed since.
3. **One terminal path.** `finishRun(result, scope)`, `pollRun`'s terminal branch moved out
   unchanged, runs once per scope and is shared by Stop. Stop closes the scope while its DELETE is
   in flight and disables `#live-stop`; a failed DELETE opens it again. The toast says what the
   server returned. "Stop it & start new" says "stopped" only when the DELETE answered `cancelled`.
4. **Tags are written by the renderer that fills the region.** Each run-scoped region in
   `workspace.html` carries `data-run-scope`; the renderer that fills it sets `data-run-id` from the
   result it was given, at the moment it writes. `<html data-run-id>` is derived in `setView`: the
   scope's run on the live-run, result and transcript views, absent elsewhere. The transcript
   writes its caption and its demo banner from the result it is given on every render.
5. **The composer's amounts are derived.** The total shows the estimate's amount, and the slot
   cells its rows, only while the inputs on screen equal the inputs it priced: the trimmed
   question, the ordered model ids, quick mode and both follow-up values, every one of which enters
   the estimate request. Otherwise the total reads "—" and the cells show the page's own figure.
   They are painted while the composer is on screen and when it comes back on screen.
6. **`.live-debate[hidden] { display: none; }`**, and a quick run's live view also empties the host.
7. A blocking e2e invariant, `e2e/tests/invariants/run-scope.spec.ts`, checks after every transition
   that each visible run-scoped region with text carries the page's run id, that a run view has at
   least one such region, and that the composer, cost confirmation and landing have none.

## Measurements

Reproduced in a real browser on `f10c754`, before the change:

| Lead | Runs | What the visitor saw |
|---|---|---|
| A quick run after a panel run | 4 of 4 | the panel run's round cards in the quick run's live view |
| "New question" after a run | 3 of 3 | the finished run's amount beside an empty box |
| Stop pressed after a quick run had finished | 3 of 3 | "Completed" with the toast "Run cancelled.", and no answer |

The rest were traced in the code and are now each driven by the spec above: a late answer for an
earlier run drawn as the current one; a poll answered after Stop putting the run back as running,
toasting a second time, or raising the connection notice; "Go to run" after a finished run never
reaching its result (W49); a restore keeping the previous error card or answering out of order; a
transcript keeping another run's caption or demo banner; two DELETEs from two clicks; and slot cells
showing the priced panel's rows on a changed panel.

The spec has 21 cases, each at 1440 and 390 px (42 tests). On `f10c754` all 42 failed; after the
change all 42 pass. The unit file `tests/unit/test_w127_run_scope_functions.py` has 14 tests (12
failed and 2 positive partners passed on `f10c754`; 14 pass after).

## Rejected alternatives

- **A global `[hidden] { display: none !important; }`.** It would have fixed the round cards in one
  line, but it changes every component at once: `.field-error[hidden]` keeps `display: flex` on
  purpose and hides with visibility and opacity, and every other `[hidden]` rule in `app.css` (48
  lines name one) is scoped to its own component. A rule that outranks every author display is a change to the whole page, not to
  this defect.
- **Stamping the tags centrally** (in `setView`, or in one pass after each render). A central stamp
  marks a region with the current run whether or not anything re-rendered it, so the leftover
  content this decision exists to catch would be tagged as current and the invariant would pass
  over it.
- **Dropping an estimate still loading when the visitor goes to the landing.** It belongs to the
  same family, but AC-059, ADR-0145 and `help-and-tour.spec.ts` describe that arrival as it is, and
  ADR-0140 defines home as the composer. It changes behaviour the owner decides, so it is W51, its
  own pull request.

## Consequences

- A run's answer, a restore's answer and a failed poll are acted on only for the scope that asked.
  An answer that is somehow for another run id is now ignored rather than shown.
- `state.terminalHandled` stays as a field for the code that reads it, as a mirror of the scope's.
- A finished run's question, Copy/Export text, transcript snapshot and demo-banner cache no longer
  survive into the next scope, whichever way it starts.
- The composer total behind a result is not repainted until the composer is shown again; the
  composer is hidden there, so nothing visible changes.
- A new run-scoped region must carry `data-run-scope` and be tagged by its renderer, or the
  invariant fails on it.
- Not covered: the signed-in History view (no e2e lane here signs in to it), and the boot path's
  adoption, which no page action reaches today.

## Related

- ADR-0128 decision 9 (a quick run shows no debate area), ADR-0140 decisions 4 to 6, ADR-0142
  decision 3 ("a stale answer is ignored"), ADR-0143 decisions 5 and 6, ADR-0173.
- `docs/32-ui-state-matrix.md` (terminal handling, quick answers and Stop).
