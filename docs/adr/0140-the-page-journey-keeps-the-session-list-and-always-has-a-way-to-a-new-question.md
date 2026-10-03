# ADR-0140: The page keeps the session list, opens an empty question box, and always has a way to a new question

## Status

Accepted — 2026-10-03, board row W33 (slice A) and W43. The product owner
reported bugs 1, 2, 6, 9 and 10 on 2026-09-29 and 2026-09-30 (M07 points 1, 2, 6,
9; M23); W43 was found by W34's product review, not by the owner. The owner
decided the follow-up box (CHG-026 g) and agreed the composer-hint fix the session
proposed (CHG-026 m; M24, *"Rest, I agree"*). The shape below is the session's
design. The points that are the session's own calls, not the owner's, are listed
under Consequences so the owner can overturn them.

## Context

Measured on `e2b32b2` in real Chromium against the real server (simulated runs,
as in production today), signed in and anonymous:

| Report | Measured today | Cause |
|---|---|---|
| Bug 1: "Start fresh" removes the session's questions | 2 entries → 0 on clicking "Start fresh", before anything runs; "Follow up on this" does not bring them back | The "Start fresh" handler calls `clearSessionTrail()` (since `431071d`, PR8, 2026-07-25); a blocking spec asserts it |
| Bug 2: the old follow-up stays in the box | After a follow-up run the next-question box still holds it; "Review & run" with an empty box pre-fills the previous question | Run end clears only `#query-text`; the empty-box branch copies `state.liveQueryText` (since `17ed2b5`, #13, 2026-07-11) |
| Bug 6: no way to the homepage from a result | Result header controls: Copy, Export, theme; brand is a `<span>`; browser Back → `about:blank` | `app.css` hides the top bar on the result, live-run and transcript views; no history entries |
| Bug 9: empty "This session" panel | Heading only; a fixed empty bar at 390 px; a dead "Clear" after clearing | The empty branch of `renderSessionTrail` hides the list and nothing else |
| Bug 10: after a landing question the page focuses the question, not the models | Focus on `query-text`; at 390 px the focused box sits under the fixed list bar | `goToComposer()` focuses the textarea |
| W43 (W34's product review): the empty box is red on load | Red border, `aria-invalid="true"`, "Question is required." on every plain load, anonymous too | Boot runs the validator, which marks length 0 invalid (since `ed70ade`, #5) |

None of these is a regression: each has behaved this way since it shipped, and
three blocking tests, in two specs, pinned two of them as intended. The failure modes were listed
before the code:
`docs/analysis/2026-10-03-w33a-page-journey-failure-modes.md`.

## Decision

1. **Only "Clear" empties the session list.** "Start fresh" no longer does. When
   the list reaches its 10-entry cap, a line says so.
2. **Every finished run empties the next-question box, and nothing pre-fills the
   composer** — not "Review & run", not a mode button.
3. **"Follow up on this" and "Start fresh" are hidden until W37.** With no
   pre-fill they do the same thing, and the page sends no context to the models,
   so a "Following up on: …" line (CHG-026 g) would claim something that does not
   happen — the owner's point in M08 point 5 is that without the context the
   models cannot know it is a follow-up. The note under the box says
   each question is answered on its own for now. W37 brings both buttons back
   together with the context and the "Following up on: …" line.
4. **A way to a new question from every view that has none.** On the result and
   transcript views the brand is a real link to `/ui`, and the top-bar logo is
   too; a click goes to the composer without reloading, so the session list is
   kept, and it clears any error card and cost confirmation. From a result or a
   transcript the composer opens empty (that question has already run). The
   top-bar logo never deletes a question the user typed and has not run: from the
   composer or the cost confirmation it keeps the text. The result header gains a
   "New question" button. The live-run view gets one only once the run is no
   longer in progress (stopped, failed or timed out); while it runs, the view
   keeps Stop alone, because a run that finishes switches to the result and
   empties the question box, which would lose text typed meanwhile.
5. **Going home drops anything still in flight for the question being left.** An
   estimate that answers after the user has gone home is ignored: it opens no
   cost confirmation, starts no run and shows no error. A run only ever submits
   the question that was priced, never text typed into the box while the estimate
   was loading.
6. **Browser Back works inside the page.** Entering the result or transcript view
   adds one history entry, and so does going home from them, so Back after "New
   question" returns to the result rather than leaving the site. The cost
   confirmation and the live-run view are never history entries. A Forward to a
   result that is no longer in memory shows the composer.
7. **The empty list explains itself.** One line ("Questions you ask in this tab
   appear here."), "Clear" hidden while there is nothing to clear, and at phone
   width an empty panel is not pinned over the page. After "Clear", focus moves to
   the panel heading. The panel's accessible name is its visible title. The
   list's small text (status and time) meets WCAG AA contrast in both themes.
8. **After a landing question the page lands on the models.** A hint directly
   above the model slots takes focus: *"Your four models are picked for you —
   change any if you like. Then press **See the estimate** to check the cost
   first, or **Run now** to start straight away (it still asks first if the cost
   needs your approval)."* It counts the models actually shown (one in quick
   mode) and recounts when quick mode or the panel changes; when the high-stakes
   acknowledgement is showing it says to tick that first and focus goes there. A
   small step marker above the composer reads *Question → Models → Estimate and
   run*, with the current step marked.
9. **The empty question box is not an error until the user tries to submit.**
   1–11 characters is advice, never an error state.

## Rejected alternatives

- **Show the whole top bar on the result, live-run and transcript views.** Brings
  back the double header and the per-view theme toggles that `theme-toggle.spec.ts`
  and `parity-behavior.spec.ts` were written around.
- **Make the brand a plain link with a full page load.** Simpler, but the reload
  empties the session list — bug 1 by another route.
- **Keep the follow-up toggle with no effect, or show "Following up on: …" now.**
  A dead control, or a false claim about what the models see.
- **Keep the session list across reloads in `sessionStorage` now.** A run made
  while anonymous answers 404 after signing in, so restored entries need a "no
  longer available" state of their own; W36 stores history properly.
- **Rename the landing's "Estimate" and "Run the debate" to the composer's
  names.** Suggested by the session in the owner log (M24 row), not part of
  CHG-026 (m). Neither landing button runs anything; a landing "Run now" would be a
  false label, and running from the landing contradicts M23. Left as they are.
- **Hash routing for Back.** Changes reload behaviour and deep links for nothing.

## Consequences

- Browser code, template and styles only: no server route, setting, schema or
  stored datum changes; `docs/48` is unchanged.
- The full-page result and transcript screenshots change. Their Linux baselines
  must be re-seeded through `seed-visual-baselines.yml` before merge and checked
  by eye (AGENTS.md rules 13d, 13e).
- Three blocking tests in `session-trail.spec.ts` and `parity-behavior.spec.ts`
  pinned the bugs, and `degraded-banner.spec.ts` and `quick-answer.spec.ts` relied
  on the pre-fill; all four files are rewritten in this pull request by the test
  designer.
- Calls taken by the session (the owner may overturn any of them): (i) "homepage"
  means the composer, not the landing page; (ii) the follow-up mode buttons are
  hidden until W37; (iii) the landing buttons keep their names; (iv) the hint's
  real button names come from the session's reply of 2026-09-30 05:12Z to M24's
  *"What do you suggest?"*, and the "(it still asks first …)" clause was added by
  this session on 2026-10-03 (failure-mode row 20); the owner has answered
  neither; M24 itself asked for "click on Estimate … or … click on Run".
- Known limits, recorded rather than fixed here: after a run the page scrolls to
  the result heading, so the header's way home starts above the fold, and for a
  few seconds the run toasts can cover it; a landing example chip clicked during
  the hand-off pause is lost (older than this change).
- Known limits: the session list is still lost on a reload, sign-in, sign-out or
  idle expiry (W36); at phone width a list with entries still covers up to 40% of
  the screen height.
- `ADR-0128` says the follow-up box "only pre-fills the composer"; that sentence
  is history and is superseded here.
