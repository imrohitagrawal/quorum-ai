# W48 — help for new users: journeys and failure modes before the code

Written 2026-10-05 before the change. Board row W48. Decision: CHG-027 (g), the owner's
words: *"Help for new users: build both — contextual help on by default (one short hint
per new idea: the cost estimate, the trust score, History; each shown once per device with
"Got it"), and an optional 1-minute tour opened only from a "Take the tour" link on the
landing page and in "How it works", never automatically, skippable at every step, keyboard
and screen-reader accessible, sharing its text with the hints. Its own work item after W37
and the anonymous-spend change, built the same way (journeys and acceptance tests
first)."* Design: ADR-0145. This item moves no money.

## What the page has today (read on `40249a6`)

- "How it works" is the landing page itself: the top bar's "How it works" reopens the
  landing view; the landing's own "How it works" scrolls to its example preview
  (`.landing-preview`). The top bar is hidden on the landing, result, live-run and
  transcript views.
- The cost estimate's first full showing is the cost gate (`data-view="cost-gate"`, card
  `#cost-review-card`). The trust score is `#result-trust-score` on a panel result (not on
  a quick answer). History is a signed-in-only `<details id="account-history">` in the top
  bar; anonymous visitors have none.
- No dialog exists anywhere in the page. The one remembered flag is
  `quorum.workspaceSeen` in `localStorage`, read and written inside try/catch.
- The page-wide Escape key goes back from the cost gate, closes a tooltip, and, while a
  run is active, **cancels the run**.

## Journeys (each becomes an acceptance test)

1. **A first visit, anonymous.** Lands on the landing; sees "Take the tour" beside "How it
   works"; does not take it. Asks a question, presses "See the estimate": the cost gate
   shows the estimate hint once. Presses "Got it": it goes and does not come back on a
   reload or a later estimate. Runs: the result shows the trust-score hint once; "Got it".
   No History hint (no History).
2. **A first visit, signed in.** The composer shows the History hint by the History control
   once; "Got it". The estimate and trust-score hints as in journey 1.
3. **The tour from the landing.** Presses "Take the tour": a dialog opens with step 1 of N,
   focus inside it. Next, Back, and "Skip the tour" on every step; Escape closes it; focus
   returns to the link. The question typed on the landing is still there. The steps for the
   estimate, the trust score and History use the same words as the hints.
4. **The tour from "How it works".** From the composer, the top bar's "How it works" opens
   the landing, where the link is; the landing's "How it works" scrolls to the preview,
   which has its own "Take the tour".
5. **Keyboard only and screen reader.** Every hint's "Got it" and every tour control is
   reachable by Tab, named, and the dialog is announced with its step ("Step 2 of 5").
6. **A returning visitor.** Hints already dismissed never show; the tour never opens by
   itself.

## Failure modes and the design answer

| # | Failure | Harm | Answer |
|---|---|---|---|
| 1 | The tour opens by itself (first visit, a timer, a stored flag). | Against the owner's words: "never automatically". | It opens only from a "Take the tour" control's click; no code path opens it on load. A test reloads and waits, and asserts no dialog. |
| 2 | Escape in the tour reaches the page-wide handler, which cancels a running run or leaves the cost gate. | A run stopped by closing help. | The tour handles Escape itself and stops it there; it is opened only from the landing. (Review found this premise false: an estimate requested earlier can move the view under the open tour; the tour now closes when the view leaves the landing.) A test opens the tour and presses Escape: the dialog closes and nothing else changes. |
| 3 | Focus is lost when the tour closes, or Tab leaves the open dialog. | Keyboard users stranded. | Focus moves to the dialog's heading on open, Tab stays inside while open, and focus returns to the control that opened it. |
| 4 | A hint shows again after "Got it" (storage not written, or the key read wrongly). | Nagging; against "shown once per device". | One `localStorage` key per hint, written on "Got it"; read in try/catch. |
| 5 | Storage is blocked (private window, disabled site data). | A hint that can never be dismissed, or a crash. | Read failures count as "not seen" so the hint shows; "Got it" hides it for the page's life even if the write fails. Never throws. |
| 6 | A hint covers the thing it explains or the buttons next to it (at 390 px, or under the toasts). | Help that blocks the task. | Hints are inline in the page flow, not floating; a test checks the explained control is still clickable at 390 px. |
| 7 | A hint is placed inside `#result-trust-score` or `#cost-review-card`. | Breaks the trust score's rendering contract (no digits on the unverified branch, the disclosure always present) and the card's tests. | Hints sit beside those elements, never inside. |
| 8 | Hints appear in every existing test's screenshots and layouts. | Visual baselines and geometry specs move for help that is not what they test. | The shared e2e boot fixture marks the hints as seen, as it already marks the workspace seen; the help specs start without the flags. |
| 9 | The tour's text and the hints' text drift apart. | Against "sharing its text with the hints". | One table of help text in `app.js`; the hints and the tour steps read it. A unit test asserts each hinted idea's tour step equals its hint. |
| 10 | The hint text claims something false (History kept longer, the estimate called a price). | Misleading help. | Each sentence is checked against the code it describes in review: History keeps the newest 5 questions for 30 days, with how each run went and never the answer (CHG-023, `docs/48`); the estimate is a planning figure (its accuracy is unmeasured, ADR-0016), and nothing runs until approved when the estimate is asked for first. |
| 11 | The landing gets taller and the "Choose models →" button drops below the first screen on a phone. | The landing's main action hidden (`landing-cta-reachable.spec.ts`). | Both buttons sit in lines the landing already has (ADR-0145 decision 4, which superseded "one more line" when the density bound left no room); the density test is run with its own setup before and after. |
| 12 | The tour is opened mid-hand-off (after "Choose models →" was pressed). | The hand-off moves to the composer under the dialog. | Opening the tour cancels a pending hand-off, as the landing's "How it works" already does. |
| 13 | The History hint shows to an anonymous visitor, or points at a control that is not there. | A hint about nothing. | Shown only when `#account-history` is on the page. |
| 14 | A screen reader hears nothing for a hint, or hears every hint on every view change. | Help that is invisible, or noise. | A hint is a labelled note in the reading order next to the control, not a live region; the tour is a labelled dialog. |
| 15 | The tour claims to be 1 minute but is long, or cannot be skipped from a step. | Against the owner's words. | Five steps of one or two sentences; "Skip the tour" on every step. |
| 16 | Reduced motion: the tour animates or scrolls smoothly. | Discomfort for people who asked for less motion. | No animation; the existing reduced-motion rules apply. |
