# ADR-0173: A high-stakes acknowledgement is sent only for a ticked box, and the run is held for it at the final check

## Status

Accepted — 2026-10-18, board row W100. The product owner made four choices: the line under the
buttons (CHG-063 (g)) and how each warning is acknowledged (CHG-065 (a) to (d)). Everything else
below is the session's design. The failure modes were listed before any code
(`docs/analysis/2026-10-18-w100-high-stakes-ack-failure-modes.md`, F1 to F16). Codex reviewed the plan
before any code (ADR-0168, decision 7). Its reviews are kept outside the repository; none has a
committed record. The first review found one problem (decision 2 below). The plan was revised, and a
second review confirmed that problem closed and named one more path (the second advisory under
Consequences). Codex did not review the code.

## Context

The server asks for two kinds of acknowledgement before a run (ADR-0006, `docs/41-security-controls.md`
SC-68): `sensitive_data` always, and `high_stakes` when the question names a medical, legal,
financial, safety or regulated topic. The server refuses a run without them and records them as
events. It cannot tell an acknowledgement the visitor gave from one the page made up, so the defect
and the fix are both on the page.

Before W100 the page had a tick box for the high-stakes warning, but it was checked in one place
only: when "Run now" or "See the estimate" was pressed, and only if a background warnings check,
sent after a half-second pause in typing, had already answered. Then `proceedWithRun` made a final
warnings check and sent back every warning it returned as acknowledged (`warningAcknowledgements`).
So the server recorded a high-stakes acknowledgement the visitor never gave whenever "Run now" came
before the background check answered, when that check failed, or when the run was confirmed on the
cost gate, whose confirm button and Ctrl/Cmd+Enter never looked at the box.

## Measured

| What | How | Result |
|---|---|---|
| The defect, before the fix | a Playwright script against a local simulated server, on `main` at `a839ba9` (failure modes, section 0) | "Run now" at once, a failed background check, and Ctrl+Enter on the cost gate each sent `sensitive_data` and `high_stakes` with the box unticked and got 202. With the background check answered first, the gate held. With `high_stakes` removed from the body, the server answered 422 |
| One place creates a run | `grep -n 'api("/v1/query-runs"' src/product_app/static/app.js` on this branch | one match, inside `proceedWithRun`; the failure modes (section 1) trace every entry point to it |
| The new tests fail without the fix | the builder's red run, before any `src/` change | unit `tests/unit/test_safety_acknowledgements_for.py`: `17 failed in 0.28s`. `e2e/tests/ui-parity/high-stakes-acknowledgement.spec.ts`: `10 failed`, `4 passed`. `e2e/tests/invariants/safety-acknowledgement.spec.ts`: `1 failed`, `1 passed` |
| The new tests with the fix | the builder's runs after the fix | unit: `17 passed in 0.86s`. The mocked spec: `14 passed (52.9s)`. Both blocking e2e lanes, run as `.github/workflows/e2e.yml` runs them with the AGENTS.md rule 13 flags: 459 and 126 tests executed, 0 failed, 0 skipped |
| The visual baselines cannot move | `outerHTML` of the result and transcript views on `goldenCompletedResp()`, dumped twice before the change and once after, compared with `cmp` | byte-identical: 27,187 bytes (result) and 17,858 bytes (transcript). The template and the stylesheet last changed before the "after" dump; that `app.js` did not change between that dump and the build commit is UNVERIFIED |

## Decision

1. **The check lives in `proceedWithRun`, after the final warnings check and the `generation`
   check, before the create.** Not at click time: the cost gate's confirm button, its
   Ctrl/Cmd+Enter and the legacy `#proceed-run` button all call `proceedWithRun` directly and never
   pass the click-time gate (`highStakesGateSatisfied`, called from `startRun`). The click-time gate
   stays as it was; it stops most holds before they cost an estimate.
2. **The tick is read from `state.highStakesAck` alone, not "ticked and the box is visible".** The
   cost gate hides the composer, and the box with it. Codex's plan review showed, with the real
   `setView` in a node probe, that a visibility condition held every confirmed run in a loop. A tick
   made before the cost gate still counts there. It clears when the box hides
   (`setHighStakesRequired(false)`) or when a run is created (decision 4).
3. **The sensitive-data acknowledgement stays automatic (CHG-065 (a)).** Its notice has no tick
   box and is always on screen above the question, so sending the question acknowledges it. Sending
   only ticked boxes would have made the server refuse every run.
4. **A fresh tick per run (CHG-065 (b)).** The tick clears once the create succeeds; the box stays
   as the background check says.
5. **A warning type the page does not know is never acknowledged (CHG-065 (c)).** The server then
   refuses the run and the visitor sees an error, never a silent consent.
6. **A held run shows the toast that existed and the new line (CHG-065 (d)).** The toast says
   "Acknowledge the decision-support notice before running this query."; the line says "Tick the box
   above to run this question." (CHG-063 (g), `docs/33-content-design.md` COPY-002). Focus moves to
   the box, which is scrolled to the centre.
7. **A failed or malformed final check fails closed.** `safetyAcknowledgementsFor` throws when the
   answer has no warnings list, so the existing error is shown and nothing is created. An aborted
   check takes the existing error path too.
8. **How the hold behaves.** The estimate is dropped, so the next press prices the question afresh
   and, where confirmation is needed, asks again. The view returns to the composer, since the box is
   not on the cost gate. The hold returns inside the existing `try`, so the `finally` releases the
   latch and the spinner. No error card is shown: nothing failed, a step is missing.
9. **Each acknowledgement is exactly `{warning_type, version}`,** with the version the final check
   returned. The server refuses extra keys since W85, so a field such as `ticked` would break every
   run.
10. **Where the line sits.** `#high-stakes-held` is a sibling right after `.composer-footer`, inside
    the composer view, so it is under the buttons at every width. It is hidden by default with its
    own `[hidden]` rule, because the stylesheet has no global one. While it shows, the box has
    `aria-describedby="high-stakes-held"`. It hides in one place, `syncHighStakesHeld`, called
    whenever the gate or the tick changes, so it never outlives the box.
11. **The visual baselines.** The line is inside the composer view and hidden by default, so the
    result and transcript baselines cannot change. The `outerHTML` dump above is the proof (AGENTS.md
    rules 13d and 13e); no baseline was re-seeded.

## Consequences

- Every high-stakes run needs its own tick. A held run that is retried costs one more estimate and
  one more final check, out of the 30 requests a minute per account that warnings, estimate and
  create share (`query_runs.py`, `_enforce_account_rate_limit`).
- The background check is now only a convenience. The final check is the authority.
- The two e2e lane floors rise by the new tests only: 455 to 457 and 96 to 110. They keep the slack
  they had rather than taking the local counts (459 and 126).
- Advisory, not built:
  - **F11:** when the server refuses a run for a missing acknowledgement (422), the page shows
    "Please check the form" rather than the hold. Reading `required_warnings` from that answer to
    take the same hold is defence in depth. It is not needed while the page never sends an unticked
    run.
  - **Leaving during the final check:** Codex's second plan review found that a ticked run
    continues after the visitor leaves the composer (for example by "How it works") while the final
    check is answering. Its in-memory probe printed `activeView=landing, ack=true, creates=1`. The
    acknowledgement was given, so this is not a false acknowledgement. It comes from leaving the
    page not cancelling a pending create (`enterLanding` does not change `estimateGeneration`), which
    was already so before W100.
  - **Screen readers:** what a screen reader announces when focus moves to the box and the line
    appears is UNVERIFIED. No screen reader was run.
  - That no real model's answer, carried into a follow-up, trips the high-stakes check in a
    real-server test is UNVERIFIED. Only two simulated follow-ups were measured.

## Rejected alternatives

- **Check only at click time (in `startRun`).** It misses the cost gate, its Ctrl/Cmd+Enter and the
  legacy button.
- **Require the box to be visible as well as ticked.** It holds every confirmed run (decision 2).
- **Read the tick before the final check's `await`.** A tick withdrawn while the check answers
  would still be sent (F4).
- **Treat a failed final check as "no warnings".** It sends nothing, so the server refuses, or,
  combined with a filter, a failure reads as "not high-stakes" (F10).
- **A tick box for the sensitive-data notice too.** The owner chose to keep it automatic (CHG-065
  (a)).
- **Keep the tick across runs.** The owner chose a fresh tick per run (CHG-065 (b)).
- **The line only, without the toast.** The session recommended it; the owner chose both
  (CHG-065 (d)).
- **A fix on the server.** The server cannot tell a ticked acknowledgement from a made-up one.

## Related

- Code: `src/product_app/static/app.js` (`safetyAcknowledgementsFor`, `proceedWithRun`,
  `holdForHighStakesAck`, `syncHighStakesHeld`), `src/product_app/templates/workspace.html`,
  `src/product_app/static/app.css`.
- Tests: `tests/unit/test_safety_acknowledgements_for.py`,
  `e2e/tests/ui-parity/high-stakes-acknowledgement.spec.ts`,
  `e2e/tests/invariants/safety-acknowledgement.spec.ts`.
- ADR-0006 (the high-stakes scan), ADR-0171 (the request models refuse extra keys), CHG-060 (the
  detail held back until this fix shipped), CHG-063 (g), CHG-065.
