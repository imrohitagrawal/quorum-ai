# W87-2 failure modes: a recent sign-in before deleting an account

Written before any code, for board row W87's second pull request, and committed with the fix
(CHG-060). The list for W87 was written on 2026-10-18; its sections on the maximum age were
published with W87-1 (`docs/analysis/2026-10-19-w87-1-max-age-failure-modes.md`). This file holds
the sections on a recent sign-in before deletion and on the single-factor record, as W87-2's plan
corrected them, and the failure modes the plan and Codex's four plan reviews added. W87-3's part,
an operator command to end sessions, is still open, so it stays outside the repository until it
ships; numbers missing below are W87-1's or W87-3's.

The facts were read on `main` at `8463a72` (W86 merged) and re-read by W87-2's planner at `0f06765`
(W87-1 merged). "Measured" means a session ran a probe with temporary databases; "read" means it
read the code and ran nothing. The design is ADR-0175. The build closed FM-11 to FM-14, FM-17,
FM-18, FM-19, FM-21, FM-40 to FM-43, FM-47, FM-48 and FM-50 to FM-54, and recorded FM-15, FM-16
and FM-20 as accepted. Recorded limits are in section 5.

## 0. Facts the design rests on

| # | Fact | How it was found |
|---|---|---|
| F3 | Sign-in rotates the session: a new id, a new anti-forgery token and a new `created_at`, and the old session is revoked from both halves. So a signed-in session's `created_at` is the moment its Google sign-in finished | read |
| F15 | The callback sent the browser only to fixed paths, `/ui` or `/ui?sign_in=failed`; there was no redirect parameter | read |
| F16 | Signing in again as a different Google account switches the browser to that account; carry-over moves nothing from a signed-in session | read |
| F17 | `accounts.last_sign_in_at` is per account, stamped by a sign-in from any browser | read |
| F27 | The callback refused an ended session before it took the pending sign-in, so the entry stayed in memory | measured by the planner at `0f06765`: one entry left after the refusal |
| F28 | A live session revoked during the Google exchange still got `303 /ui` and a new cookie: the callback looked the session up once, before the exchange | measured by the planner at `0f06765`, with a stubbed exchange |
| F29 | `/v1/session` sent `account_id` for a signed-in account and nothing otherwise, so a failed account read looked anonymous | read by the planner; found by Codex |
| F30 | `is_anonymous` answers `True` only when the id is certainly in no accounts row, `False` when a row exists, and `None` when it cannot be read | read |

## 1. Recent sign-in (10 minutes) before deleting an account

| FM | What could go wrong | How W87-2 answers it | Test (red when) |
|---|---|---|---|
| FM-11 | "Recent" is read from the account (`accounts.last_sign_in_at`, F17), so the victim signing in on their own laptop lets an old stolen cookie for the same account delete within those 10 minutes | The check reads the session's own start only | `tests/integration/test_recent_sign_in_for_deletion.py::test_the_check_reads_the_sessions_own_start_not_the_accounts_last_sign_in` (red when the check reads the account row) |
| FM-12 | Recency is stamped on the existing session, so a thief holding the cookie who gets the victim to finish a sign-in gains it too | The new sign-in goes through `issue_signed_in_session`, which revokes the old id; the thief's copy stops working | `tests/integration/test_recent_sign_in_for_deletion.py::test_the_re_sign_in_for_deletion_replaces_the_old_session` (red when the old cookie still answers 200) |
| FM-13 | The new sign-in comes back as a different Google account | Rewritten to the owner's answer (CHG-066 (c), with CHG-073 (d)'s words): an ordinary sign-in as that account; the first account's other sessions keep working, its row and history are untouched, the other account's row is created if new, nothing is deleted, and the panel says so. The other account may delete at once with its own email | `tests/integration/test_recent_sign_in_for_deletion.py::test_another_account_coming_back_is_an_ordinary_sign_in_and_deletes_nothing`; `tests/unit/test_recent_sign_in_markup.py::test_the_switched_line_names_the_sessions_own_email_escaped` |
| FM-14 | Recency is checked only in the page | The server refuses with 403 `RECENT_SIGN_IN_REQUIRED` before the email is compared; the page's deadline only chooses which step to show | `tests/integration/test_recent_sign_in_for_deletion.py::test_deletion_is_allowed_at_exactly_600_s_and_refused_1_us_later`; `::test_a_stale_session_with_a_wrong_email_is_told_to_sign_in_not_that_the_email_is_wrong` |
| FM-15 | The visitor spends more than 10 minutes typing after the new sign-in and is refused again | Accepted: the refusal shows the same step, and the visitor signs in again | the boundary test above |
| FM-16 | The new sign-in rotates the anti-forgery token, so other tabs get 403 on their next request | Accepted and recorded (ADR-0175, Consequences) | none |
| FM-17 | The new sign-in restarts the 12 hours | Intended: it is a fresh Google sign-in | `tests/integration/test_sign_in_recovery.py::test_a_recovered_deletion_sign_in_can_delete_at_once` |
| FM-18 | `max_age=600` or `prompt=login` would make Google ask for the password whenever its own sign-in is older than 10 minutes, against the owner-approved words "If you are still signed in to Google it takes one click." (CHG-063 (f)(1)) | Answered: neither is sent; the deletion start asks Google for exactly what the plain start asks. What the app's own time proves, and what it does not, is in ADR-0175, decision 2 | `tests/integration/test_recent_sign_in_for_deletion.py::test_the_deletion_start_asks_google_for_exactly_what_the_plain_start_asks`; `tests/integration/test_google_sign_in.py` still asserts `prompt` is absent from the plain start |
| FM-19 | The legacy test header sets the session's start to "now", so recency always passes | Deletion already refuses the legacy header (`NOT_SIGNED_IN`), before the recency check | `tests/integration/test_account_deletion.py::test_the_legacy_account_header_cannot_delete_an_account` |
| FM-20 | A restart during the sign-in loses the pending entry, which is in memory only | Accepted: "Sign-in did not complete" | none |
| FM-21 | An e2e test cannot wait 10 minutes; the server clock is real | The signed-in lane ages the session through its test-only handler (W87-1); the lane's floor rises from 35 to 43 in the same commit as the spec | `e2e/tests/signed-in/delete-recent-sign-in.spec.ts` |
| FM-52 | The page's deadline and the server disagree (the page was loaded fresh and the session aged since) | The server refuses, and the page shows the same "Sign in again" step for that refusal | `tests/unit/test_late_run_question_rules.py::test_the_delete_page_answers_a_recent_sign_in_refusal_with_its_own_sentence`; e2e `e2e/tests/signed-in/delete-recent-sign-in.spec.ts` "a page loaded fresh and then aged past 10 minutes is refused by the server and shows the same step" |

## 2. The way back from Google

| FM | What could go wrong | How W87-2 answers it | Test (red when) |
|---|---|---|---|
| FM-47 | "Sign in again" pressed seconds before the 12 hours end comes back to a failed sign-in, because the session ended during the round trip (ADR-0174's known limit) | Recovery: an ended session is accepted only when its durable row shows it ended by the signed-in 12 hours and nothing else, and no deletion of its account is under way or done (`SessionRepository.max_age_account`, which `end_reason` now answers from). The pending entry is taken first, on every attempt | `tests/integration/test_sign_in_recovery.py::test_a_sign_in_that_crosses_the_12_hours_completes`; `::test_a_sign_in_after_any_other_end_is_refused`; `::test_end_reason_and_max_age_account_agree`; `::test_a_callback_for_an_ended_session_leaves_no_pending_entry` |
| FM-48 | A signed-in visitor who cancels at Google comes back to a page that says nothing: the signed-in top bar returned before the failure notice was read | The signed-in top bar shows "Sign-in did not complete. Please try again." too | `tests/integration/test_recent_sign_in_for_deletion.py::test_a_cancel_on_a_deletion_sign_in_shows_the_failure_notice_signed_in` |
| FM-53 | A recovered session is revoked, signed out everywhere, or its account deleted, during the Google exchange, and the callback still signs the browser in (Codex measured all three) | The recovery condition is checked again after the exchange together with the account row write, under the session repository's lock, which a deletion takes before it removes any row (`SessionRepository.upsert_if_recoverable`): a deletion that comes first refuses the sign-in with nothing written, and one that waits for the write then removes the row (`tests/integration/test_sign_in_recovery_no_account_write.py`, `tests/integration/test_sign_in_recovery_lock.py`). It is checked again after the account row, right before the new session is issued. The remaining windows are in section 5 | `tests/integration/test_sign_in_recovery.py::test_a_recovered_session_ended_during_the_exchange_is_refused`, with partner `::test_the_same_stubbed_exchange_without_interference_completes`; `::test_a_deletion_under_way_before_the_callback_is_refused_before_the_exchange` |
| — | A new return path appears, or one takes a value from the request | Four fixed paths, pinned by literal, read from the real `Location` header of all 16 callback outcomes | `tests/integration/test_recent_sign_in_for_deletion.py::test_every_callback_outcome_ends_on_one_of_four_fixed_paths`; `tests/unit/test_risk_constant_pins.py::test_the_recent_sign_in_constants_are_pinned` |

## 3. The late-run question

| FM | What could go wrong | How W87-2 answers it | Test (red when) |
|---|---|---|---|
| FM-50 | The anonymous question kept across sign-in (CHG-073 (c)) is put back for someone else using the same tab much later, or a question typed as one account is saved as another's | The anonymous entry is put back once within 900 seconds of when it was saved (the arithmetic is ADR-0175, decision 14). The save is classified by what `/v1/session` said, never by the markup, and nothing is saved once the page load's identity changed | `tests/unit/test_late_run_question_rules.py::test_an_anonymous_entry_is_put_back_up_to_900_000_ms_and_not_after`; `::test_a_retry_that_brings_another_account_saves_nothing`; `::test_a_retry_that_turns_anonymous_saves_nothing`; e2e `e2e/tests/signed-in/delete-recent-sign-in.spec.ts` "the anonymous card saves under the account the bootstrap names, not the markup" |
| FM-51 | The other-account notice names a stale email (the HTML can be made stale by another tab) | The email comes from `GET /v1/account/history`, which answers for the cookie's own session, inserted as text; no line when that route fails | e2e `e2e/tests/signed-in/session-max-age.spec.ts` (the other-account test asserts the notice with the new account's email) |
| FM-54 | A bootstrap that cannot tell the session's kind (a failed read, F29) is read as anonymous, so account B's question is saved as anonymous and put back for account C (Codex) | `/v1/session` sends `anonymous: true` only when `is_anonymous` answers `True` (F30), and neither field when it cannot tell; the page saves nothing then | `tests/integration/test_session_max_age_routes.py::test_a_bootstrap_that_cannot_read_the_account_names_neither`; `::test_a_signed_in_bootstrap_whose_account_read_fails_is_not_called_anonymous`; `tests/unit/test_late_run_question_rules.py::test_a_missing_account_is_never_read_as_anonymous` |

## 4. The single-factor record and the line near "Sign in"

| FM | What could go wrong | How W87-2 answers it | Test (red when) |
|---|---|---|---|
| FM-40 | The line goes in the static template and changes the anonymous, sign-in-off page that the blocking visual baselines render | It is rendered only in the sign-in branch of the top bar; with sign-in off that branch is still the empty string | `tests/unit/test_recent_sign_in_markup.py::test_with_sign_in_off_the_top_bar_is_still_empty`; `::test_the_two_step_line_is_not_in_the_workspace_template` |
| FM-41 | Which "Sign in" controls get the line | Answered by the owner (CHG-073 (e)): beside the top bar's "Sign in with Google" and on the capped sign-in page only; not by the 12-hour messages. Reading the cards' sign-in buttons as outside "near Sign in" is the session's | `tests/unit/test_recent_sign_in_markup.py::test_the_two_step_line_is_beside_sign_in_on_the_anonymous_top_bar`; `::test_the_two_step_line_is_below_the_capped_pages_sign_in_button`; `::test_the_two_step_line_is_absent_from_the_signed_in_top_bar` |
| FM-42 | The top bar is dense at phone width | The line takes a row of its own under the buttons at 600 px and below | e2e `e2e/tests/signed-in/delete-recent-sign-in.spec.ts` "the 2-Step line sits beside Sign in with Google at 1440 and 390 px" |
| FM-43 | The ADR or `docs/41` claims Google enforces 2-Step Verification | Both say the app cannot see or require it (ADR-0175, decision 15; SC-03) | prose review |

## 5. Recorded limits

- The anonymous 24 hours are not recovered: the purge would race the callback, and recovery would need
  a new carry-over path. The visitor sees "Sign-in did not complete", and the question is still put back.
- `max_age_account` can read a row a moment before a revoke deletes it (Codex).
- A revocation or a sign-out everywhere between the last recovery check and the new session is not
  seen: the person who has just signed in with Google as that account gets a working new session.
  The result is the same as an ordinary sign-in, and recovery does not refuse it. The live path has
  no check after the exchange (F28); it is pinned unchanged by
  `tests/integration/test_sign_in_recovery.py::test_the_live_path_is_unchanged_by_a_revoke_during_the_exchange`;
  the same check on the live path is advisory, not built.
- The anonymous question is lost after 900 seconds, when the bootstrap could not tell the session's
  kind, and after any identity change in the page load until a reload. It is never shown to another
  account.
- The classification is as fresh as this tab's bootstrap.
