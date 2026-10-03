# W33 slice A — the page journey: failure modes before the code

Written 2026-10-03 before the change (AGENTS.md rule 16e). Slice A of board row W33
covers the owner's bugs 1, 2, 6, 9 and 10 of 2026-09-29/30 and board row W43, all in
the browser page (`app.js`, `workspace.html`, `app.css`). The owner's words are in
`docs/analysis/2026-09-29/OWNER-DISCUSSION-LOG.md` (M07 points 1, 2, 6, 9; M08 point
5; M23; M24); the decisions are CHG-026 (g) and (m); the root causes are in
`docs/analysis/2026-09-29/owner-bugs-root-causes.md`. Design: ADR-0140.

Today's behaviour was re-measured on `e2b32b2` in real Chromium against the real
server (simulated runs, as production runs today), signed in and anonymous, at 1440
and 390 px, by a read-only design reviewer. Its probes and their output are in this
session's scratchpad, not in the repository.

| # | Failure mode | Consequence | Design answer |
|---|---|---|---|
| 1 | "Start fresh" wipes the "This session" list (bug 1). | Earlier questions gone, no undo. | Nothing but the "Clear" button empties the list. |
| 2 | The list keeps at most 10 entries and drops the oldest silently; it now fills more often because nothing else empties it. | Silent loss. | A line says "Showing your last 10 questions" once the cap is reached. |
| 3 | A reload, sign-in, sign-out, idle-expiry reload or account deletion reloads the page and empties the list. | List lost. | Known limit, written in ADR-0140. Keeping questions across reloads is W36 (stored history). Not in this slice. |
| 4 | The result's next-question box keeps the last follow-up (bug 2). | The user deletes it before typing. | Every finished run empties the box. |
| 5 | "Review & run" with an empty box pre-fills the previous question into the composer (bug 2). | Not the blank box the owner asked for. | No pre-fill, in any mode. |
| 6 | With no pre-fill, "Follow up on this" and "Start fresh" do the same thing, and no context reaches the models (`app.js` header comment: the browser sends no `context`). Showing "Following up on: …" would claim a context that is not sent — the owner's M08 point 5. | A control that does nothing, or a false claim. | Both mode buttons are hidden until W37 sends the previous question and answer. The note says each question is answered on its own for now. |
| 7 | Ctrl+Enter inside the next-question box runs the hidden composer. | A false "Question is required" error over the typed text (measured). | Ctrl+Enter there does what "Review & run" does. |
| 8 | No visible way back to a new question from the result and transcript views (bug 6); the top bar is hidden there and the brand is a plain `<span>`. | Dead end. | The brand on those views and in the top bar is a real link to `/ui`; a click goes to an empty composer without a reload, so the list is kept. The result header gets a "New question" button. |
| 9 | A home control on the live-run view: when the run finishes, the page switches to the result and empties the question box. | Text the user typed meanwhile is lost. | No home control on the live-run view; it keeps Stop. |
| 10 | Going home leaves an error card or an open cost confirmation behind. | A stale error over an empty composer. | Every way home clears the error region and the cost confirmation. |
| 11 | Browser Back from a result leaves the app (measured: `about:blank`); on a phone the Back gesture loses the result and the list. | Lost work. | Entering the result or transcript view adds one history entry; Back returns to the composer. The cost confirmation and the live-run view are never history entries, so Back cannot reopen a spent estimate. A Forward to a result no longer in memory shows the composer. |
| 12 | Back after sign-out shows the signed-in page from the browser cache. | Privacy. | Measured not to happen: signed-in `/ui` is sent `no-store`. Unchanged. |
| 13 | The empty "This session" panel shows a heading and nothing else (bug 9); at 390 px it is a fixed empty bar over the page. | Looks unfinished; covers content. | One line: "Questions you ask in this tab appear here." "Clear" is hidden while the list is empty. At phone width an empty panel is not pinned. |
| 14 | At 390 px the fixed list bar covers the question box the page has just focused (measured with the landing hand-off). | The user cannot see what they type. | Same as 13 for the empty case. A list with entries still covers up to 40% of the screen; recorded as a limit. |
| 15 | "Clear" hides the button that has focus. | Focus drops to the page body. | Focus moves to the panel heading; a polite message says the list was cleared. |
| 16 | The panel is named "Conversation trail" for screen readers while it reads "This session". | The two names don't match. | The region takes its name from the visible title. |
| 17 | After a landing question the page focuses the question box, not the models (bug 10). | The user doesn't know the next step. | A hint directly above the models: "Your four models are picked for you — change any if you like. Then press **See the estimate** to check the cost first, or **Run now** to start straight away." It takes focus and is scrolled into view. |
| 18 | The hint names buttons the high-stakes gate has disabled. | "Press See the estimate" while it is greyed out. | When the gate shows, the hint says to tick the acknowledgement first, and focus goes there. |
| 19 | Quick-answer mode shows one model while the copy says "four". | False copy. | The hint and the hand-off note count the models actually shown. |
| 20 | "Run now starts straight away" over-promises: it still asks when the cost needs approval, and a spent daily allowance blocks it. | A broken promise. | The hint adds "(it still asks first if the cost needs your approval)". |
| 21 | Renaming the landing's "Estimate" and "Run the debate" to the composer's names (the session's suggestion in the owner log, not part of CHG-026 m): neither landing button runs anything, so a landing "Run now" would be a false label, and running from the landing contradicts M23. | A false label. | Not renamed in this slice; ADR-0140 records why. |
| 22 | An empty question box is red with "Question is required." on every page load, signed in or not (W43; since `ed70ade`). | Looks like an error the user made; screen readers announce "invalid". | The box is marked invalid only after a submit attempt. 1–11 characters is advice, not an error. |
| 23 | The landing hand-off timer and a chip click during it. | A second, stray focus move. | The existing latch is kept; the new focus move happens only on the timer path. |
| 24 | The full-page result and transcript screenshots (`visual-snapshots.spec.ts`, blocking) change with the header and the next-question block. | A red blocking lane that cannot be re-seeded locally (AGENTS.md rules 13d, 13e). | Re-seed through `seed-visual-baselines.yml` on the branch and check the new images by eye; prove the rest of the page unchanged with an `outerHTML` diff. |
| 25 | Existing blocking specs pin the bugs: `session-trail.spec.ts` (Start fresh clears the list), `parity-behavior.spec.ts` (the pre-fill), and `degraded-banner.spec.ts` and `quick-answer.spec.ts` rely on the pre-fill without saying so. | Fixing the bug turns them red. | The test designer rewrites them to assert the fixed behaviour, in the same pull request; the builder does not touch them. |

Added by review round 1 (2026-10-03: a break-it reviewer and a product reviewer, both
driving the real server in Chromium, and Codex reading the diff). The first build met
every row above and still failed these:

| # | Failure mode | Consequence | Design answer |
|---|---|---|---|
| 26 | Going home while an estimate is still loading: the late answer still acts (Codex and the break-it reviewer, reproduced). | A charged run of half-typed text; the cost confirmation reopening over an empty box; a false "Question is required" card. Editing the box during a "Run now" estimate already ran the edited text before this change. | Going home drops any estimate still in flight; a run submits only the question that was priced. |
| 27 | "New question" stepped history back, so the next Back left the site and a Forward reloaded with an empty list. | The list lost by the Back gesture — row 11 by another route. | Going home from a result or transcript adds a history entry. |
| 28 | The top-bar logo on the composer emptied a typed question (a 1,079-character question to 0 in one click). | Lost input. | The logo never deletes a question the user typed and has not run. |
| 29 | A stopped, failed or timed-out run stays on the live-run view, which has no way home. | A dead end — bug 6 by another route. | "New question" shows there once the run is no longer in progress. |
| 30 | The hint kept "four" after quick mode was turned on or a slot removed. | False copy (row 19 after the hand-off). | The hint recounts on every change of quick mode or the panel. |
| 31 | The list's status and time text measure 3.2:1 (light) and 3.41:1 (dark) at 10.9 px; older than this change, but the kept list now puts it on every result. | Fails WCAG AA contrast. | Darker tokens for those two classes. |
| 32 | The step marker the session proposed with the hint (2026-09-30 05:07Z), which the owner agreed to in M24, was not in the first design. | An agreed part of bug 10's fix missing. | Built: *Question → Models → Estimate and run* above the composer. |

What this list cannot see: whether the owner means the empty composer or the landing
page by "homepage" (M07 point 6). The design takes the composer, because a returning
visitor's `/ui` opens there and "How it works" stays one click away in its top bar.
