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

## Journey J-009: A signed-in visit while the session store cannot be checked

### Trigger

Asha is signed in. For a while the server cannot check signed-in sessions: the session database is not ready (for example after a start-up read error), busy for more than 6 seconds, or failing to read.

### Steps

1. She reloads the page. Instead of the workspace she sees "Your account is briefly unavailable" and "Quorum could not check your sign-in just now. This usually clears within a minute. Nothing has been deleted.", with one link, "Try again". Her cookie is kept and no new session is opened, however many times she reloads (`e2e/tests/signed-in/store-unchecked.spec.ts`, J1).
2. She leaves the tab open. The page reloads itself every 60 seconds; once the server can check her session again, the reload brings back her workspace, still signed in with the same cookie (J1).
3. In a tab that was already open, she presses Run. The card says "Briefly unavailable" and "We could not check your sign-in just now. Try again in a minute." Her question stays in the box; "Try again" sends the same question without reloading the page (J2). In History, the rows stay, with the same sentence and a "Try again" (J4).
4. The idle check meets the same refusal. It does not tell her she was signed out; it checks again a minute later (J4c).
5. An anonymous visitor who presses "Sign in with Google" in that time stays on Quorum and sees "Sign-in is briefly unavailable. Try again in a minute." (J3).
6. Asha's open tab presses "Start a session" from the boot card: she lands on the "briefly unavailable" page, and after the window "Try again" brings back her same sign-in (J5, the owner's "Both doors" example).
7. A short hold of the database (3 seconds) delays her reload and keeps her signed in (J6).

### Success Criteria

- A cookie that could not be checked is never swapped for a new anonymous session, never served the workspace, and never touched: its life is not extended and its CSRF token is not rotated.
- No session is opened and none of the network's two daily sessions is spent while the window lasts.
- The page carries no session id, CSRF token, email or form, and sets no cookie.
- A session the server knows has ended (its 12 hours, its idle limit, sign-out, sign out everywhere, the operator command) is treated as ended, not as briefly unavailable.
- Decided by the product owner on 2026-10-23 and 2026-10-25 (CHG-088); design ADR-0176's amendment of 2026-10-25.
- Known limits: if the trouble lasts until a restart, the page keeps saying "usually clears within a minute" and keeps reloading; the operator sees `session_store` on `/status` and a log line. With no session database at all (it failed to open at start), a returning visitor gets a fresh anonymous session and must sign in again after the fix (CHG-088 (g)).

## Journey J-010: Using Quorum in two tabs

### Trigger

A person has Quorum open in one tab, with a question typed or a run going, and opens Quorum again in a second tab of the same browser: by typing the address, from a bookmark, or from a link in a chat app or on another site.

### Steps

1. The second tab opens and starts as usual. If another tab of the site is renewing its session at the same moment, the second tab waits its turn, so it can start up to about 10 s later than it would today (about 20 s only in a rare order of its two waits, read from the code, not measured; ADR-0178, Known limits). Nothing appears in the first tab: no message, no reload.
2. They go back to the first tab and press "Run now", "See the estimate", "Review & run" or "Stop run". It works, as it does in the second tab. "Sign out" and "Stay signed in" work there too.
3. If, in the second tab, they signed out, signed in as another account, signed out everywhere or deleted the account, the first tab's next action is refused with "Security check failed" and the button "Refresh session". The reload shows who is signed in now. The same happens to a tab whose account changed in another tab while it was still starting: it is refused, even though its page looks ready, it puts back no saved question, and "Start a session" reloads it.
4. If the first tab missed the change (a click sent at the very moment the second tab opened, a tab restored with the Back button, or a browser that cannot pass the change on), its next action is refused the same way, once, and "Refresh session" puts it right. The reload passes its new token to the other open tabs of the same person, so it does not break them, except when the browser cannot pass the token on, when the reload's wait for its turn runs out (10 s), after the site's stored data was cleared, or for a tab that itself had to renew without sharing: those tabs are refused the same way, as before (ADR-0178, Known limits).

### Success Criteria

- When it works, nothing new is on screen, at phone or desktop width.
- A tab never takes over another person's session: a tab signed in as one account never runs, spends or saves History as another account, and a tab drawn signed out never does so as an account, except when the server could not tell who the page or its session answer was for (ADR-0178's first known limit). Two anonymous tabs count as the same person (a known, accepted limit).
- A refused action is refused once and is never retried without the person; nothing is charged for it.
- The session's anti-forgery token is never shown, stored in the page's storage or put in a URL.
- Decided by the product owner on 2026-10-18 (CHG-071) and 2026-10-25 to 2026-10-26 (CHG-089); design ADR-0178.
