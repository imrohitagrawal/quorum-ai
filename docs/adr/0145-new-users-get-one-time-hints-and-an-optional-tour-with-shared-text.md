# ADR-0145: New users get one-time hints and an optional tour, with shared text

## Status

Accepted — 2026-10-05, board row W48. The product owner decided the behaviour on
2026-10-04 (CHG-027 g): *"Help for new users: build both — contextual help on by default
(one short hint per new idea: the cost estimate, the trust score, History; each shown once
per device with "Got it"), and an optional 1-minute tour opened only from a "Take the
tour" link on the landing page and in "How it works", never automatically, skippable at
every step, keyboard and screen-reader accessible, sharing its text with the hints."* The
shape and every word of the help text are the session's design, listed under Consequences
so the owner can overturn them. Journeys and failure modes, written before the code:
`docs/analysis/2026-10-05-w48-help-and-tour-journeys-and-failure-modes.md`.

## Context

The page explains its three new ideas nowhere a first-time visitor will meet them: the
estimate is a card with figures, the trust score is a block of signals, and History
appears in the top bar after sign-in. There is no dialog in the page, and the page-wide
Escape key cancels a running run. "How it works" is the landing page itself.

## Decision

1. **One table of help text** in `app.js`, keyed by idea (the estimate, the trust score,
   History), plus two tour-only steps. The hints and the tour read the same table; the
   tour's steps for the three ideas are the hints' words.
2. **Three hints, on by default, each once per device.** Each is an inline note placed
   next to what it explains, never inside it and never floating over it, with a "Got it"
   button:
   - the estimate hint above the cost card on the cost gate (`#cost-review-card`);
   - the trust-score hint above the trust score on a panel result (`#result-trust-score`,
     when it is shown);
   - the History hint beside the signed-in History control (`#account-history`), shown on
     the composer only, and only when that control is on the page; it never covers the
     History control.
   A hint is a labelled note (`role="note"`) in the reading order, not a live region, and
   it takes no focus. "Got it" hides it and writes one `localStorage` key for that idea.
3. **Storage is best effort.** A read that fails counts as "not seen", so the hint shows;
   "Got it" hides the hint for the life of the page even if the write fails; nothing
   throws.
4. **The tour opens only from a "Take the tour" control** (a button, since it does not
   navigate): one in the landing's nav row beside "How it works", and one at the end of
   the example preview that the landing's "How it works" scrolls to. **Neither may make
   the landing taller**: the phone density check (`landing-cta-reachable.spec.ts`) had
   about 26 px of room on `40249a6` (scroll height 1567 against its 1593.6 bound,
   measured by the test designer), less than one button line, so both sit in lines the
   landing already has. Below 600 px wide the nav button moves up to the brand line,
   which has room, and the header's side padding drops from 32 px to 16 px; it stays
   inside the nav row in the page's structure. Measured by the builder at 390, 375 and
   360 px wide: scroll height unchanged (1567, 1611, 1635). The top bar's "How it works" opens the landing, where both
   are. Nothing opens the tour on load, on a timer or from a stored flag. Opening it cancels
   a pending landing hand-off, as "How it works" already does, and keeps the typed
   question.
5. **The tour is a modal dialog** (`role="dialog"`, `aria-modal="true"`, labelled by its
   heading, which names the step: "Step 2 of 5"): five steps of one or two sentences —
   asking a question, the models, the estimate, the trust score, History — with Back
   (shown but disabled on step 1), Next (Done on the last) and "Skip the tour" on every
   step. The dialog sits outside the landing view in the page, so the landing's word
   checks do not read it. Focus goes to the heading on
   open and on each step, Tab stays inside, Escape closes it and is handled inside the
   dialog only, and focus returns to the control that opened it. No animation.
6. **Existing tests keep their pages**: the shared e2e boot fixture marks the three hints
   as seen, as it already marks the workspace as seen; the new help specs start without
   those flags.

## Rejected alternatives

- **A tour that points at the live controls** (spotlights on the real cost card, trust
  score, History). Those controls do not exist on the landing, where the tour starts; the
  tour would have to run a fake question or describe things the visitor cannot see yet.
- **Hints as tooltips on the existing info icons.** Those open on hover and focus only,
  not on touch, and are dismissed by moving away, so "once, with Got it" cannot be
  honoured.
- **Remember "seen" on the server.** Needs a session or account write for anonymous
  visitors; the owner asked for once per device.
- **Open the tour on the first visit.** Against the owner's "never automatically".

## Consequences

- New keys in the visitor's browser storage: one per hint. No server storage, no new
  data kept; `docs/48` is unchanged.
- The landing does not grow: the two tour buttons sit in existing lines (decision 4).
- Calls taken by the session (the owner may overturn any of them): (i) where each hint
  sits; (ii) the tour as five text steps in a dialog rather than pointing at live
  controls; (iii) two "Take the tour" controls, in the nav row and at the end of the
  preview; (iv) a blocked storage read shows the hint; (v) every word of the help text,
  recorded in `app.js`'s help table (`helpTextTable`), quoted in AC-059 and listed as COPY-007 to COPY-011 in `docs/33`; (vi) the
  tour buttons fitted into existing landing lines because of the density bound.
