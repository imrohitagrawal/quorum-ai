# User Journeys

## Journey J-001: Cross-Validate An Important Answer

### Trigger

The user has an important question and does not want to rely on one model's answer.

### Steps

1. User opens the application.
2. User sees warnings that high-stakes outputs are decision support only and that sensitive/private data should not be submitted until privacy controls are defined.
3. User enters one query.
4. User reviews the four default model slots and optionally replaces any model with an OpenRouter-supported model.
5. User starts the run.
6. The system gets source-backed responses from all four models.
7. The system shows each model output with source links.
8. The system runs debate/critique round one, where models review gaps, contradictions, and weak claims in each other's outputs.
9. The system runs debate/critique round two, where models respond to critique and refine their positions.
10. The synthesizer creates the final answer.
11. User reviews consensus, disagreement, final recommendation, and cited support.

### Success Criteria

- The user can see where models agree and disagree.
- The final answer does not hide uncertainty.
- Source links are visible for material claims.
- The result is framed as decision support, not guaranteed truth.

## Journey J-002: Replace Models Before Running

### Trigger

The user wants to compare different OpenRouter-supported models than the defaults.

### Steps

1. User opens the model selection area.
2. User replaces one or more default model slots.
3. The system validates that four model slots are selected.
4. User runs the query using the selected models.

### Success Criteria

- User can replace all four models.
- The UI makes model identity visible before execution.
- Unsupported or unavailable model selections are blocked or clearly explained.

## Journey J-003: Handle A High-Stakes Query

### Trigger

The user asks a medical, legal, financial, safety, or regulated-domain question.

### Steps

1. System detects or receives the query as high-stakes.
2. System shows decision-support-only warning.
3. User chooses whether to continue. The run is held until the user ticks the acknowledgement box: a run started before the box appears is stopped at the final warnings check, back on the question, with the line "Tick the box above to run this question." under the buttons and focus on the box. Each new run needs a fresh tick (W100, ADR-0173, CHG-065 (b)).
4. If the run continues, the output includes limitation language and source-backed uncertainty.

### Success Criteria

- The product does not present itself as professional advice.
- The warning appears before the user relies on the result.
- The final synthesis preserves uncertainty and disagreement.

## Journey J-004: Sensitive Data Warning

### Trigger

User may include private, personal, confidential, or regulated information in the query.

### Steps

1. System displays a clear warning near query entry.
2. User is told not to submit sensitive/private data until privacy controls are defined.
3. User can revise the query before running.

### Success Criteria

- Warning is visible before submission.
- Product does not claim sensitive-data safety.
- Privacy posture remains honest until controls are designed and validated.

## Journey J-005: Signing in after the network's anonymous sessions are used up

### Trigger

A person on a network (an office, a home, a VPN) whose address has opened its daily allowance of new anonymous sessions loads Quorum with no live session — typically after signing out, after an idle expiry, or as a colleague arriving on the same network.

### Steps

1. The page says the network has reached its limit of new sessions in 24 hours, that an already-open session still works, and that signing in is not limited by this.
2. The person presses "Sign in with Google" and completes Google's sign-in.
3. They land on the workspace signed in, with their history, and can run a query under their account's own limits.

### Success Criteria

- No reachable state locks a person out of signing in (tested as a property over session states and events).
- The sign-in-only session that carried the sign-in is never counted as a new session and can spend nothing.
- Decided by the product owner on 2026-09-29 (CHG-026 a); design ADR-0139; acceptance AC-053.

## Journey J-006: Asking several questions in one visit

### Trigger

A person asks a question, reads the result, and wants to ask another — from the result, from the debate, after stopping a run, or with the browser's Back button.

### Steps

1. From the landing page they type a question; the page lands on the models with a hint naming "See the estimate" and "Run now".
2. They run it. On the result, the next-question box is empty; they type a new question there, or press "New question" or the logo.
3. Every question they asked in this tab stays in "This session" until they press "Clear"; Back returns to the view they left.

### Success Criteria

- No route to a new question deletes the list, and none deletes a question they typed and have not run.
- What the cost confirmation describes is what runs and is charged.
- Reported by the product owner on 2026-09-29 and 2026-09-30 (M07, M23); design ADR-0140; acceptance AC-055.


## Journey J-007: A long signed-in visit

### Trigger

A signed-in person keeps one tab open and keeps using it for most of a day, so the session is never idle long enough to end, and the 12 hours since their sign-in run out.

### Steps

1. Five minutes before the 12 hours end, the reminder says "You will be signed out in about 5 minutes because 12 hours have passed since you signed in." It counts the minutes down and offers "Sign out now", not "Stay signed in", because staying cannot extend the 12 hours.
2. If they press "Run now" or "See the estimate" with less than 12 minutes left, the run is refused before anything is charged, on a card titled "Your session ends soon": "Your session ends in less than 12 minutes. Sign in again, then run this question." They press "Sign in again", complete Google's sign-in, and come back to the workspace with the question they typed still in the box, and a fresh 12 hours.
3. If they do nothing, at 12 hours the page says "You were signed out because 12 hours have passed since you signed in. Reload the page to sign in again." with "Reload the page".

### Success Criteria

- The page never says "nothing has happened on this page" when the 12 hours are the reason, and never says "12 hours" when they are not.
- No run starts with less than 12 minutes of session left; a refused run spends nothing.
- The typed question survives "Sign in again" once, in this tab only, and only when the same Google account comes back; another account gets an empty box and the line "You are now signed in as <email>. Your question was not kept because it was typed while signed in as another account." (CHG-073 (a), W87-2); a plain sign-in puts nothing back.
- Where the page offers no sign-in (sign-in off, or the fly.dev host), a signed-in visitor's card has the sign-in-off text and no "Sign in again" (review round 2).
- An anonymous visitor in the last 12 minutes of 24 hours is refused with "This session ends in less than 12 minutes, so this question cannot run now. Sign in to keep going, or reload the page after the session ends." (without the sign-in part when sign-in is off). Since W87-2 their "Sign in with Google" keeps the typed question too, and puts it back once within 15 minutes (CHG-073 (c); ADR-0175).
- Decided by the product owner on 2026-10-17, 2026-10-18 and 2026-10-19 (CHG-056 (c), CHG-063 (f)(2), CHG-066, CHG-069, CHG-070, CHG-073 (a) to (c)); design ADR-0174 and ADR-0175.
- "Sign in again" pressed seconds before the 12 hours end comes back signed in, with the question in the box. Until W87-2 it came back to a failed sign-in (ADR-0174's known limit, fixed by W87-2, ADR-0175).

## Journey J-008: Deleting an account a while after signing in

### Trigger

A signed-in person opens History and presses "Delete my account…" more than 10 minutes after the sign-in that made their session.

### Steps

1. Instead of the reminder, the panel says "For your safety, sign in with Google again before deleting your account. If you are still signed in to Google it takes one click." with one button, "Sign in again", which has the focus.
2. They press it and complete Google's sign-in, one click when still signed in to Google. They come back to the workspace with the account panel open and the focus on "Delete my account…".
3. They press it again, see the reminder, type their email, press "Continue" and then "Delete permanently". The account is deleted.
4. If Google signs them in as another account, they come back signed in as that account, and the panel says "You are now signed in as <email>. Nothing was deleted. To delete this account, press "Delete my account" again." The first account is untouched. If they cancel at Google, they stay signed in and the top bar says "Sign-in did not complete. Please try again."

### Success Criteria

- No session whose own sign-in is more than 10 minutes old can delete an account, whatever the page shows; the refusal deletes nothing.
- A sign-in on another browser never makes an old session fresh, and the new sign-in replaces this browser's session, so a copied cookie stops working.
- Google is asked for nothing new: no password prompt is forced.
- Decided by the product owner on 2026-10-17 to 2026-10-19 (CHG-056 (d), CHG-063 (f)(1), CHG-066 (c), CHG-073 (d)); design ADR-0175.
- Known limit: typing for more than 10 minutes after the new sign-in is refused again, and the visitor signs in again.
