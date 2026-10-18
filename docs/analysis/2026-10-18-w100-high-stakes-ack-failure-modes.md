# W100 failure modes: a high-stakes acknowledgement only for a ticked box

Written before any code, and committed with the fix (CHG-060). The build closed F1 to F10 and F12 to F16 (ADR-0173); F11, reading `required_warnings` from a 422 to take the same hold, is advisory and was not built, and the screen-reader behaviour in F12 is UNVERIFIED.

Read on `main` at a839ba9. Line numbers are `src/product_app/static/app.js` unless named otherwise.

## 0. What I ran (measured, $0, simulated server on 127.0.0.1:18230, `git archive HEAD` copy)

A Playwright script (`probe.js`) against the real server, with the question
"Should I sign this employment contract with a non-compete clause?" ("contract" matches `HIGH_STAKES_PATTERN`, safety.py:36-44):

| Scenario | Box visible at click | Box ticked | Create body `safety_acknowledgements` | Create status |
|---|---|---|---|---|
| A. fill, click Run now at once | no | no | `sensitive_data` + `high_stakes` | 202 |
| B. background check aborted, wait 1.5 s, Run now | no | no | `sensitive_data` + `high_stakes` | 202 |
| C. fill, click See the estimate at once, Ctrl+Enter on the cost gate | no (box is not on the cost-gate view at all) | no | `sensitive_data` + `high_stakes` | 202 |
| D. positive partner: fill, wait 1.5 s | yes; Run now disabled | no | no create | none |
| E. Run now at once, the create body has `high_stakes` removed in flight | no | no | `sensitive_data` only | 422; page shows "Please check the form" / "Required safety acknowledgements are missing." on the composer |

So the defect is real by three paths, the gate works when the probe has answered (D), and the server does refuse a missing acknowledgement (E).
`warningAcknowledgements` run under node returns every warning passed in, high_stakes included (measured).
Follow-up probe (`followup.js`, 2 simulated runs): a follow-up carrying the simulated previous answer as context got `["sensitive_data"]` only, so the simulated answers for "Postgres or MySQL for a small team?" and "What are the key metrics for measuring SaaS customer retention?" do not trip the check (n=2, simulated only; real model answers can).

## 1. Every path that creates a run

There is ONE create call: `api("/v1/query-runs", ...)` at app.js:9560, inside `proceedWithRun` (9481). Grep of every `query-runs` call (7067, 9117, 9331, 9540, 9560, 9678, 9699, 9854, 9955, 9973, 9975) found no other POST to `/v1/query-runs`. Entry points to `proceedWithRun`:

| Path | Code | High-stakes check today |
|---|---|---|
| Run now (allow band, auto-proceed) | click 11790-11794 -> `startRun(true)` 9425 -> `estimateRun` 9085 -> `await proceedWithRun()` 9188 | `highStakesGateSatisfied()` 9438 at click time only, and only if the background probe has already answered |
| See the estimate -> cost gate "Approve & run" / "Run · $X" | `gateConfirmButton` click 11829-11833 -> `proceedWithRun` | none |
| Ctrl/Cmd+Enter on the cost gate | 11219-11224 -> `proceedWithRun` | none |
| Ctrl/Cmd+Enter on the composer | 11240-11242 -> `startRun()` (estimate-first, so it ends at the cost gate) | `estimateButton.disabled` and 9438 |
| Legacy `#proceed-run` (`proceedButton`) | 11822-11826 | none (the button lives in the hidden `#cost-confirmation` callout) |
| Expired confirmation retry | catch at 9631-9639 -> `estimateRun()` -> cost gate -> confirm | none (lands on the cost gate again) |
| Follow-up ("Review & run", Ctrl+Enter in the next-question box) | `reviewAndRun` 11003-11023 goes to the composer; it runs nothing itself | same as composer |
| Quick mode | same CTAs; `priced.quick` only | same |
| Landing Estimate/Run | `handoffFromLanding` 10838: hands off to the composer, runs nothing | same |
| Error-card actions | 10048-10217: every action returns to the composer or reloads; none creates | n/a |
| Page reload with a run in flight | `pollRun` 9678: re-attaches to an existing run, creates nothing | n/a |

**Design consequence:** the decision must live inside `proceedWithRun`, after the final `/v1/query-runs/warnings` answer (9540) and before `setCreateInFlight(true)` (9559). A check only in `startRun` misses the cost gate, its keyboard path and the legacy button.

## 2. Failure modes

Each: what goes wrong / trigger / test / design answer.

### F1. The literal reading of "only for a box the visitor ticked" breaks EVERY run (most likely missed)
- **What:** `sensitive_data` is always required (safety.py:263-283; `tests/unit/test_safety_warning_policy.py::test_sensitive_data_warning_is_always_required`). It has no tick box: the page shows it as a permanent `role="note"` above the question (templates/workspace.html:231-235, COPY-001) and acknowledges it AUTOMATICALLY by echoing the final check's list (9568). Scenarios A-E show it sent with no visitor action. If the fix sends only ticked boxes, `sensitive_data` is never sent and the server refuses every run with 422 (query_runs.py:740-759).
- **Trigger:** any question, any path.
- **Test:** real-server e2e (page-journey.spec.ts style, no `page.route`) that runs a plain question and asserts the create gets 202 and its body holds exactly one `sensitive_data` acknowledgement. Every existing real-server spec (page-journey, follow-up-context, real-integration-smoke) would also go red, which is a free detector. Unit: the pure function below with `[sensitive_data]`, unticked -> `[sensitive_data]`.
- **Design:** change only the `high_stakes` entry. Keep `sensitive_data` automatic, and say in the ADR why: the notice is always on screen above the box, so sending the question is the acknowledgement. This is a policy (rule 16d) and is itself "an acknowledgement the visitor did not tick"; name it in the ADR and ask the owner only if the reviewers think CHG-063 (g) covers it. CHG-063 (g)'s question text is about the high-stakes warning only.

### F2. Unknown or future warning types
- **What:** if the server adds a third type, today's page auto-acknowledges it. A filter written as "drop high_stakes unless ticked" keeps doing that.
- **Design:** decide on purpose. Recommended: an allowlist, `sensitive_data` automatic, `high_stakes` only when ticked, anything else NOT sent (the server then refuses with 422 and the visitor sees an error rather than a silent consent). Record it in the ADR.
- **Test:** pure-function case `[sensitive_data, "new_type"]` -> `new_type` absent.

### F3. Adding a field to the acknowledgement breaks every run
- **What:** `SafetyAcknowledgement` has `extra="forbid"` since W85 (safety.py:178-184). Sending e.g. `{warning_type, version, ticked: true}` gets 422 on every create.
- **Design:** keep the `{warning_type, version}` shape; take `version` from the FINAL check's answer, never a constant (the server compares versions, safety.py:308-321).
- **Test:** `tests/unit/test_request_model_bounds.py` already validates the page's shapes; add the new function's output to its valid bodies.

### F4. Reading the tick before the await
- **What:** on the Run now path the composer stays on screen while the estimate and the final check are in flight, and the box is enabled. A visitor can untick during that window. A snapshot of `state.highStakesAck` taken before `await api(".../warnings")` (9540) sends a consent the visitor withdrew.
- **Design:** read `state.highStakesAck` (and the box is visible) AFTER the final check answers and after the `generation` check (9546).
- **Test:** parity-behavior style: route the final warnings call to wait for a page signal; untick during the wait; release; assert no create (held). Mutation: move the read above the await, test goes red.

### F5. Stale tick from an earlier question
- **What:** `state.highStakesAck` resets only in `setHighStakesRequired(false)` (9293-9299). A visitor who ticked for question 1 and asks a second high-stakes question (follow-up, or edits the text) keeps the tick, because the probe never answers "false" in between. The box is visibly ticked, so it is "a box the visitor ticked", but for a different question.
- **Design:** the safe minimum for W100 is to send `high_stakes` only when the final check returned it AND the box is ticked at that moment. Whether a new run should require a fresh tick (reset on run creation) is a product decision; do not add it silently. If the owner wants it, reset in `proceedWithRun` after a successful create.
- **Test:** pure function: `[sensitive_data]` with ticked=true -> no `high_stakes` sent (stale tick on a non-high-stakes question must not send one; the server records whatever it is sent, safety.py:339-368, so this would be recorded).

### F6. Hold on the cost gate shows nothing (the box is not on that view)
- **What:** `#high-stakes-gate` is inside `<div data-view="composer">` (workspace.html:268); the cost gate is a separate view (423). Measured in C: box not visible on the cost gate. A hold that only calls `setHighStakesRequired(true)` and focuses the tick box from the cost gate focuses a hidden element (focus silently fails) and the visitor is stuck on a gate whose Approve now does nothing.
- **Also:** the owner's words "Tick the box above" are false if the line is shown on the cost gate.
- **Design:** on hold, `setView("composer")` first, then `setHighStakesRequired(true)`, show the line, focus `#high-stakes-ack` with `scrollIntoView({block: "center"})` (as `focusHandoffHint` does, 873-885). Drop the estimate (`state.currentEstimate = null; state.pricedRun = null`) so after ticking the visitor presses Run now / See the estimate again and gets a fresh estimate and, in the confirmation band, a fresh token. The cost gate is never a history entry (633-648), so Back cannot reopen the dropped estimate.
- **Test:** e2e: route warnings so background probes return `[sensitive_data]` and the call after the estimate returns `[sensitive_data, high_stakes]`; click See the estimate; on the gate click Approve; assert zero creates, `[data-view="composer"]` visible, `#high-stakes-ack` focused, the line visible. Same with Ctrl+Enter on the gate.

### F7. Hold leaves a latch or spinner stuck
- **What:** `proceedWithRun` sets `state.creatingRun = true` and the confirm button loading (9536-9537); `startRun` holds `submittingRun` and both CTAs (9435-9447). A hold that `return`s before the `try` or throws past the `finally` strands them.
- **Design:** hold inside the existing `try` so the `finally` at 9643-9653 releases `creatingRun`, `createInFlight` and the spinner; never call `setCreateInFlight(true)` on the hold path; do not call `handleError` (no error card, no focus theft to `#error-region`, which `showError` focuses at 1055). `startRun`'s `finally` then re-runs `applyHighStakesGate` (9473), which now disables both CTAs because the gate is required and unticked: correct.
- **Test:** after a hold, tick the box and assert Run now is enabled and a second click creates exactly one run (count creates, rule 6b).

### F8. Focus stolen after the hold
- **What:** the hold runs inside `estimateRun` inside `startRun`; their `finally` blocks run after it. `setButtonLoading` does not move focus (8151-8160), so focus stays on the tick box. But a later change that calls `showError`, `revealCostGate` or `focusLiveHeading` on that path would steal it.
- **Test:** assert `#high-stakes-ack` is focused 1 s after the click, not just right after (as page-journey row 18, page-journey.spec.ts:1063-1076, does for the hint).

### F9. The background check and the final check fight over the box
- **What:** probes are token-guarded (9321-9338) but the final check does not bump the token. After a hold, a background probe for DIFFERENT text in the box (the visitor kept typing during the estimate; the run used the priced text, 9505-9510) can answer `false` and hide the box and reset the tick (9296-9299), with the line still showing "Tick the box above" over no box.
- **Design:** drop the estimate on hold (F6) so the next run prices the box's current text; tie the line's visibility to `highStakesAckPending()` (732 at commit a839ba9) in ONE place, `setHighStakesRequired` and the tick's change listener (11195-11202), so whenever the box hides or is ticked the line hides too.
- **Test:** e2e: hold, then type a non-high-stakes question; after the probe the box AND the line are both hidden.

### F10. A failed or slow final check
- **What:** the final check (9540) failing throws to the catch (9628) and `handleError` shows an error; no create. Safe today. A fix that wraps the call in `try { } catch { warnings = {warnings: []} }` "to not break runs" would send no acknowledgements and get 422, or, worse, if combined with F1's filter, treat a failure as "no high-stakes". A response with no `warnings` array throws `TypeError` at `.map` (9253-9258) and shows "Something went wrong".
- **Design:** a failed or malformed final check creates nothing and shows the existing error (fail closed). The background probe can stay best-effort (9342-9344) because the final check is now the authority.
- **Slow:** the final check is not time-bounded on the page. While it waits, Ctrl+Enter and the CTAs are latched (`creatingRun`, `submittingRun`), so no second create (parity-behavior.spec.ts "exactly one create" test, around 980).
- **Rate limit:** warnings, estimate and create share 30 requests a minute per account (query_runs.py:625-644; warnings route 1114). A typist fires one probe per 500 ms pause plus one per blur (11187-11191, 9348-9354). A 429 on the background probe is swallowed (gate stays open); a 429 on the final check is an error, no create. Hold-then-retry costs one extra estimate and one extra final check.
- **Test:** route the final warnings call to `abort()` and to `{}`: assert zero creates and an error shown.

### F11. Server refusal is shown as a form error with no pointer to the box
- **What:** measured (E): 422 `VALIDATION_ERROR` "Required safety acknowledgements are missing." -> title "Please check the form" (ERROR_TITLES 898), focus moves to the error region. `ERROR_TITLES.SAFETY_ACK_REQUIRED` (897) is dead: the server never emits that code (grep of src finds it only in app.js).
- **Design (advisory, defence in depth):** the payload is kept on the error (`partial: payload`, 1800), so `error.partial.detail.required_warnings` can be read; if it names `high_stakes`, take the same hold path (composer, box, focus, line) instead of the form error. Not required for W100 if the page never sends the create without the tick.
- **Note:** the server cannot tell an automatic acknowledgement from a ticked one; no server test can bite on W100. The tests must be on the page.

### F12. Wrong-place line for screen readers and phones
- **What:** focus lands on the tick box, but the line sits "under the buttons" (CHG-063 (g)), far below on a phone: at <=600px the footer stacks (app.css:5779-5783) and the four model slots sit between the box (template 268) and the buttons (371-382). A polite live region fired at the same moment as a focus move is often cut off by the focus announcement (UNVERIFIED for NVDA/VoiceOver here).
- **Design:** put the line as a sibling right after `.composer-footer` (inside the composer view, before `.keyboard-hint` at 384), not inside the flex row, so it is under the buttons at every width. Link it to the tick box with `aria-describedby` while it shows, so a screen reader reads it with the focus announcement; optionally `role="status"` as well. Give it its own `[hidden] { display: none; }` rule: app.css has NO global `[hidden]` rule (grep finds only per-class ones, e.g. 474, 1086, 5533), so a class that sets `display` would show the line on every load.
- **Test:** e2e at 375 px and 1440 px: line visible after a hold, its box below `#run-now`'s box, no horizontal overflow, `#high-stakes-ack` has `aria-describedby` naming the line; axe scan of the held state (axe-all-views.spec.ts mocks `warnings: []` everywhere, 176/250/317/414, so it never sees the box today).

### F13. Two messages for one thing
- **What:** `highStakesGateSatisfied` (9358-9367) already shows a toast "Acknowledge the decision-support notice before running this query." and focuses the box. The hold would add the owner's line. Toast + line + focus = three signals, two wordings.
- **Design:** one helper for both the click-time block and the hold. Whether the toast stays is a copy decision; the owner added the line and said nothing about the toast. Do not drop the toast silently; state the choice in the ADR.

### F14. Existing tests that pin today's behaviour
- `e2e/tests/ui-parity/parity-behavior.spec.ts` "high-stakes gate disables BOTH composer CTAs (Run now included) until acknowledged" (984-1005): mocks `[{high_stakes, version "1"}]` with no `sensitive_data`. Stays green if the click-time gate is unchanged. Its mock version "1" is not the server's; fine for a mocked create.
- `e2e/tests/invariants/page-journey.spec.ts` row 18 (1063-1076): real server, hint says "tick", focus on `#high-stakes-ack`. Unaffected unless the hold path changes `focusHandoffHint`.
- `e2e/tests/invariants/quick-answer.spec.ts:142-144` pins the create body's KEYS (`safety_acknowledgements` must stay present, even as `[]`).
- `tests/unit/test_quick_answer_ui.py:160-179` and `tests/unit/test_w37_follow_up_page_functions.py:90-106` pin `runRequestBody` with `safety_acknowledgements: []`; unaffected if the new function feeds `extra`.
- About 20 specs mock warnings as `{ warnings: [] }` (grep list in this report's run). With F1's design they still send `[]` and the mocked create accepts it.
- Real-server specs: one question in all of e2e matches the high-stakes pattern, "Should I see a doctor about recurring headaches?" (page-journey.spec.ts:1066), and it never creates a run (grep of question literals). So no real-server spec should start holding. Measured by grep, not by running the suite.
- Lane floors: `scripts/check_e2e_executed.py --min` in e2e.yml (invariants 455, axe + parity 96); new tests raise the count, which passes, and the convention is to note the new number.

### F15. Visual baselines
- Baselines exist for the result and transcript views and the trust score (e2e/tests/invariants/visual-snapshots.spec.ts-snapshots, trust-score-visual.spec.ts-snapshots); none shows the composer. The composer view is `hidden` on those views. A new element INSIDE `<div data-view="composer">` that is `hidden` by default cannot change them.
- **Proof for review (rules 13d/13e):** dump `document.querySelector('[data-view="result"]').outerHTML` and the transcript view's on `goldenCompletedResp()` before and after; byte-identical. Do not add the line outside the composer view, do not touch `goldenCompletedResp()`, never `--update-snapshots`.

### F16. Docs that describe this flow (and two that are already false)
- `docs/32-ui-state-matrix.md:41` says the gate is "Race-fixed so a fast typist can't submit around it." False today (scenario A). `docs/design-handoff/AC-CROSSWALK.md:52` and `docs/design-handoff/SLICE_STATE.md:113` say "race-fixed" too. Correct them in the fix PR, to wording that is true after it.
- `docs/113-user-journeys.md` J-003 (49-66): step 3 "User chooses whether to continue" is what the fix makes true; add that the run is held until the box is ticked.
- `docs/33-content-design.md:15` COPY-002 "Continue only after acknowledging the warning." The new line needs a COPY row or a COPY-002 note, verbatim "Tick the box above to run this question."
- `docs/41-security-controls.md:127` SC-68 "PARTIAL" and lines 219 and 248; `docs/analysis/2026-10-17-w82-security-baseline.md:157`; `docs/65-open-work.md:197` row W100 is UNPINNED: give it a needle the fix must add (for example the new function's name in app.js).
- Template comments at workspace.html:264-267 and app.js:9263-9268 say the acknowledgement "is still delivered ... by the existing run flow": reword.
- ADR in the same PR (rule 16d): the hold, sensitive-data-is-automatic, unknown-types policy, toast decision.

## 3. Recommended design (one place, one pure function)

1. A self-contained pure function, testable with the existing node harness (`tests/unit/test_quick_answer_ui.py::_run_js`, which slices one function by brace count; no globals inside it):
   `safetyAcknowledgementsFor(warnings, highStakesTicked)` -> `{ hold: boolean, acknowledgements: [{warning_type, version}] }`.
   - `sensitive_data` -> always included.
   - `high_stakes` -> included if ticked; if not ticked, `hold: true`.
   - any other type -> not included (F2).
   - not an array -> throw (fail closed, F10).
   Cases with literals: `[sd]`,false -> `[sd]`; `[sd,hs]`,false -> hold; `[sd,hs]`,true -> `[sd,hs]`; `[sd]`,true -> `[sd]` (no `hs`, F5); `[]` -> `[]`; `[sd,"x"]` -> `[sd]`. RED IF: the old `warningAcknowledgements(warnings.warnings)` is wired back (cases 2 and 4 fail), or `sd` is filtered (case 1 fails).
2. In `proceedWithRun`, after the final check and the `generation` check, before `setCreateInFlight(true)`: compute with the CURRENT tick (F4); on `hold`: drop the estimate, `setView("composer")`, `setHighStakesRequired(true)`, show the line, focus the tick box, `return` inside the `try` (F6, F7). Otherwise send the computed list.
3. The line: one element after `.composer-footer`, its own `[hidden]` rule, shown only by the hold, hidden whenever `highStakesAckPending()` is false; `aria-describedby` from the tick box while shown (F12).
4. Keep the click-time gate (9438, 9270-9290) as is; it stops most holds before they cost an estimate.

## 4. Tests to write (each says what turns it red)
- Node unit: the function's six cases (above).
- e2e parity-behavior (mocked): fast Run now with a high-stakes final check -> 0 creates, box focused, line visible; tick -> one click -> exactly 1 create whose body has `high_stakes`. RED IF the hold is removed.
- e2e parity-behavior: cost gate Approve and Ctrl+Enter with the high-stakes final check -> 0 creates, composer view, box focused.
- e2e: untick during a held-open final check -> 0 creates (F4).
- e2e: final check aborted / `{}` -> 0 creates, error shown (F10).
- e2e real server (page-journey, no routes): a plain question still runs with exactly one `sensitive_data` acknowledgement, 202 (F1 positive partner).
- e2e real server: the high-stakes question, fast click -> no create; the server's record is unaffected (nothing to read from the page; count creates).
- e2e 375 px: line under `#run-now`, no overflow; axe on the held state.
- Visual: before/after `outerHTML` of result and transcript views identical.

## 5. UNVERIFIED
- Screen-reader behaviour of a live region fired with a focus move (F12).
- That no real-model follow-up context trips the check in CI (only two simulated follow-ups measured).
- That the full e2e lanes stay green; nothing here ran the suite.
