# W7, 2a — signed-in history: failure modes first

Written before the code (AGENTS rule 16e), for board row W7 (the second of
W7's pull requests, split in two: 2a history, 2b account deletion; the split
is the session's, because they are two concerns a reviewer should see
separately). Account deletion, the hashed spend key and the cross-device
revocation are 2b.

## What the owner decided

- CHG-012 D7 (2026-09-24), their words: *"the purpose of sig-in is to
  preserve the history of the searches from a account. THis can be limited
  to last 5 searches for example if we face issue in storage."* and *"the
  whole purpose will be forfeited if we delete the history on every
  sign-out! but yes on account deletion we should remove"*. The session's
  design summarised back and not contested: keep the last 5 runs AND drop
  runs older than 30 days, both settings; a summary row per run, not the
  run; nothing deleted on sign-out.
- CHG-021 (a) (2026-09-25, 08:56:57Z): *"do carry them over, but only the
  runs from the same browser session, at the moment of sign-in, capped by
  the same keep-the-last-5 rule"*.
- 2026-09-26, 15:05:11Z (transcript `949ac7cb`, `type: user` record answering the session's
  question tool): may history store the text of each question? The owner
  selected the session-drafted option *"Yes, store the question
  (Recommended)"* — kept only for signed-in accounts, at most the last 5,
  none older than 30 days, removed with the account; the answer text is not
  stored. This settles `docs/48`'s "pending approval" for this case.

## Measured on main, by the read-only map (run at 62c5a4d, before W32 merged)

- No store holds question text durably: the run-history `runs` table is
  metrics-only by contract, and the in-memory run repository forgets a
  finished run after 1 hour. History needs its own table.
- Sign-in revokes the anonymous session and issues a new one bound to the
  Google account id; nothing keeps the anonymous account id. The callback
  can read it only before the revoke.
- A run in flight keeps the account id it started with, finishes, is billed
  and is written under it.
- The workspace pins "Results are ephemeral" in the composer lede
  (test_workspace_html_copy.py) and the result footer (parity-behavior
  spec), and the full-page visual baselines include the session-trail panel.

## Failure modes, and the design's answer to each

1. **Answer prose leaks into history.** The row holds the question, when it
   ran, its status and mode, the number of models, the verdict caption and
   its estimated cost. Never an answer, a source or a judge rationale. A
   test pins the table's columns.
2. **An anonymous visitor's questions are kept.** A history row is written
   only when the run's account is a signed-in account (an accounts row
   exists). Anonymous runs write nothing new.
3. **The keep rules drift.** After every write, the account's rows beyond the
   newest `HISTORY_KEEP_COUNT` (5) and any older than `HISTORY_KEEP_DAYS` (30)
   are deleted, in the same transaction. Reading also filters by age, so a
   row past 30 days is never shown even if no write has pruned it.
4. **Carry-over takes someone else's runs.** Only the runs of the session
   that is signing in join, and only if that session is anonymous: a
   session already signed in as account A that signs in as B carries
   nothing (review round 1 reproduced A's question moving into B's history
   through a direct API call). The store also refuses to move a run from one
   account's history to another's.
5. **The promised race: a run still running at sign-in.** It finishes under
   the anonymous id. The callback records that the anonymous id now belongs
   to the signed-in account (in memory, for as long as a run can last); when
   that run finishes, its row goes to the signed-in account's history too. A
   test starts a run, signs in while it runs, finishes it, and finds it in
   history exactly once.
6. **Written twice.** The row is keyed by `query_run_id`; a second write for
   the same run replaces it, so a double-fire or a carry-over of a run that
   also finishes later cannot duplicate it.
7. **Nothing deleted on sign-out.** Sign-out touches only the session.
   A test signs out and signs in again and finds the same history.
8. **Someone else's history.** History is rendered only into the page of the
   request's own signed-in session, for that account's rows; there is no
   separate history endpoint to probe. An anonymous page carries none.
9. **Storage fault.** A failed history write logs and does not fail the run
   (same posture as run history); a failed read shows "Your history could
   not be loaded just now", never an empty history or someone else's rows.
10. **The copy stays false.** For a signed-in visitor the composer lede
    says what is kept (the last 5 questions, 30 days) and what is not (the
    answer: export one to keep it). The result footer and receipt lines
    ("this result vanishes when the session ends") stay: they are about the
    answer, which is still not kept. Anonymous visitors see the existing
    copy, byte-identical (visual baselines are anonymous).
11. **Deletion is not built yet.** The owner's approval says the questions
    are removed when the account is deleted. Account deletion is W7's next
    pull request (2b); until it ships, a signed-in account's questions are
    removed only by the keep rules (5, 30 days).
12. **The history box on a phone.** A panel anchored to the History button
    ran off the screen's left edge at 390px, and one centred over the page
    covered the button that closes it (both seen in screenshots). On narrow
    screens the open box takes its own row under the button.
13. **Question length.** The question is stored as sent, bounded by the
    existing request limit.

14. **Keyboard.** The history panel scrolls; a scroll box a keyboard cannot
    reach is a SERIOUS axe failure (review measured it in WebKit). The panel
    is focusable and named, and the disclosure closes on Escape.
