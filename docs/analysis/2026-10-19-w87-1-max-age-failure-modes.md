# W87-1 failure modes: a session ends at a maximum age

Written before any code, for board row W87's first pull request, and committed with the fix
(CHG-060). The full list for W87 also covers a recent sign-in before deleting an account (W87-2)
and an operator command to end sessions (W87-3). Those parts are still open, so they stay outside
the repository until they ship; this file lists only what W87-1 is about.

The facts were read on `main` at `8463a72` (W86 merged), in a `git archive` copy. "Measured" means
the session ran a probe with temporary databases; "read" means it read the code and ran nothing.
The design is ADR-0174. The build closed FM-1 to FM-7, FM-22, FM-23, FM-25, FM-26, and the four
points Codex added (C1 to C4). FM-8, FM-9 and FM-10 are accepted and recorded. FM-24 was answered
by the owner (CHG-069). Three limits are recorded, not built (section 3).

## 0. Facts the design rests on

| # | Fact | How it was found |
|---|---|---|
| F1 | Expiry looked only at idle time: `(now - last_used_at) > idle_limit` | read; measured: a cached session created 30 days earlier and used recently was not expired |
| F2 | Every request that passes `require_session` renews the session | read |
| F3 | Sign-in rotates the session: a new id, a new anti-forgery token and a new `created_at`. So a signed-in session's `created_at` is the moment its Google sign-in finished | read |
| F4 | `created_at` is written to the durable row and read back after a restart | read |
| F5 | The durable read and the purge checked only `last_used_at`, never `created_at` | read |
| F6 | The guard against a time in the future checked only `last_used_at` | read |
| F11 | The per-network mint count looks back over a rolling 24 hours and is inclusive: a mint at t0 still counts at exactly t0 + 24 h, and no longer at t0 + 24 h + 1 µs | measured |
| F12 | The mint is recorded before the session is created, so the mint's time is no later than `created_at` | read |
| F13 | An invite link counts under its own key with a cap of 12, in the same window; an allow-listed visitor records no mint | read |
| F14 | A sign-in-only session (ADR-0139) is in memory only and could be resumed without limit | read |
| F21 | The run deadline is 720 seconds by default | read (`config.py`) |
| F22 | The idle reminder says "because nothing has happened on this page", and the note after it "after N minutes with nothing happening" | read |
| F23 | The page timed its first idle check from the page load, at the idle length minus the warning | read |
| F24 | Any 401 on a run poll showed the generic "Session expired" | read |

## 1. The maximum age itself

| FM | What could go wrong | How W87-1 answers it | Test (red when) |
|---|---|---|---|
| FM-1 | The check is added to `is_expired` only, and a restart restores an old row whose last use is recent | The durable read refuses the row too, and the restore checks it | `tests/integration/test_session_max_age_routes.py::test_a_restart_does_not_bring_back_a_session_past_12_hours` (red when the restore's check is removed) |
| FM-2 | A row whose `created_at` is in the future never reaches its maximum age | Refused by the read and deleted by the purge, as a future `last_used_at` already was | `tests/security/test_session_max_age_durable.py::test_a_row_that_started_in_the_future_is_refused_and_purged` |
| FM-3 | An off-by-one makes the owner's 24 hours false at one instant, because the mint count is inclusive (F11) | A strict `>`: alive at exactly the limit, ended 1 µs later | `tests/unit/test_session_max_age.py::test_a_mint_counts_while_its_session_is_alive_and_both_end_together` (red with `>=`) |
| FM-4 | The claim "an ending session never uses up one of the network's 2" is read too broadly | ADR-0174 states only what holds: a session ended by its 24 hours has always aged out of the count; one ended sooner, by idle time or sign-out, still holds its slot | `tests/unit/test_session_max_age.py::test_a_session_ended_by_its_24_hours_frees_its_slot_and_an_idle_end_does_not` |
| FM-5 | Invite-link and allow-listed sessions are exempted by mistake | No exemption: an invite session is alive at 24 h and ended at 24 h + 1 µs, and its replacement counts once under the invite's key | `tests/unit/test_session_max_age.py::test_an_invite_session_ends_at_24_hours_and_its_replacement_counts_once`; `::test_an_allow_listed_session_also_ends_at_24_hours` |
| FM-6 | A sign-in-only session is resumed without limit (F14) | It gets the anonymous 24 hours | `tests/unit/test_session_max_age.py::test_a_sign_in_only_session_is_not_resumed_past_24_hours` |
| FM-7 | The reported end is still `last_used_at + idle_limit` once the maximum age is nearer | Every issue and resume path reports the nearer end | `tests/unit/test_session_max_age.py::test_every_issue_and_resume_path_reports_the_earlier_end` |
| FM-8 | The cookie's `Max-Age` stays at 2 hours and is renewed | Accepted: the server decides, and the cookie is never lengthened | none needed |
| FM-9 | A signed-in session ends at 12 hours, the page reloads, and the new anonymous session counts against the network's 2; on a network that has used both, the visitor gets the capped page | Accepted: that page still offers sign-in (ADR-0139) | none |
| FM-10 | A wall-clock jump forward ends sessions early; one back extends them | Accepted; FM-2 bounds the far-future case | none practical |

## 2. What the page says, and runs near the end

| FM | What could go wrong | How W87-1 answers it | Test (red when) |
|---|---|---|---|
| FM-22 | The idle reminder appears 5 minutes before the 12 hours end, offers "Stay signed in", which cannot help, and blames inactivity (F22) | The owner's own warning (CHG-066 (a)), counted down (CHG-070 (d)), without "Stay signed in" | `tests/unit/test_max_age_reminder_text.py::test_the_warning_never_blames_inactivity_or_offers_to_stay`; e2e `e2e/tests/signed-in/session-max-age.spec.ts` "five minutes before the 12 hours end, the page warns without offering to stay" |
| FM-23 | A page loaded near the 12 hours schedules its first check almost 2 hours out (F23) | The reminder carries the time left by the maximum age, and the first check is timed from the nearer end | `tests/integration/test_session_max_age_routes.py::test_the_signed_in_page_carries_the_time_left_by_its_maximum_age` |
| FM-24 | A run outlives its session, and its result is lost | Answered by the owner (CHG-069): a run, or its estimate, is refused in the session's last 12 minutes, for anonymous visitors with their own words, and **no anonymous session is renewed early** | `tests/integration/test_late_run_refusal.py::test_an_anonymous_session_with_719_seconds_left_is_refused_with_its_own_words`; `tests/integration/test_session_max_age_routes.py::test_reloading_an_anonymous_page_near_its_end_keeps_the_same_session` |
| FM-25 | The reason is guessed when it cannot be read (no store, or no row) | Never guessed: the 12-hour words only when the durable row shows a signed-in session past 12 hours | `tests/integration/test_session_max_age_routes.py::test_with_no_store_the_page_is_never_told_12_hours`; `tests/security/test_session_max_age_durable.py::test_every_other_end_reads_as_the_generic_expiry` |
| FM-26 | Anonymous pages have no reminder (ADR-0138, decision 3) | Unchanged, and answered by the owner: an anonymous visitor near the end gets the refusal of FM-24, not a reminder | as FM-24 |

Codex added four points in its plan reviews (kept outside the repository):

| # | What could go wrong | How W87-1 answers it | Test |
|---|---|---|---|
| C1 | `require_session` ignored what the touch returned, so a session that passed its lookup and reached its limit before its touch was still let through | A failed touch is a 401 | `tests/integration/test_session_max_age_routes.py::test_a_session_that_ends_between_its_lookup_and_its_touch_is_refused` |
| C2 | The idle status route answered the generic expiry, so the last reminder poll lost the 12-hour reason | The route gives the same reason as every other route | `tests/integration/test_session_max_age_routes.py::test_the_idle_status_route_gives_the_same_reason` |
| C3 | Reading the adjustable run deadline as the refusal window makes the approved "less than 12 minutes" false at a higher deadline (with the refusal reading a 3,600-second deadline, refusals would start with 3,600 seconds left) | The window is its own constant, 720, pinned by literal | `tests/unit/test_session_max_age.py::test_the_maximum_ages_and_the_late_run_window_are_pinned_by_literal` |
| C4 | Adding the two new error codes breaks a pin that lists every `AuthError` member | The pin was moved with the code | `tests/unit/test_enum_membership_pins.py` |

## 3. Limits recorded, not built

- **A run can still end after its session.** The refusal guarantees 720 seconds of session when the
  run is admitted. The run deadline is checked at three points, and a stage started before it runs
  to its own timeout: up to about 9 minutes past the deadline at today's 720 seconds, by reading. A
  deadline set higher, up to its 3,600 maximum, lets a run admitted with 720 seconds left go on for
  the deadline minus 720 seconds after the session ends, before any stage overshoot: 48 minutes at
  3,600. That result is then lost to an anonymous visitor, and in practice to a signed-in one, since
  History keeps no answers and a run has no address of its own (by reading; not run).
- **Signing in across the end.** "Sign in again" pressed seconds before the 12 hours end can come
  back as a failed sign-in, because the callback refuses a return whose original session has ended
  (Codex, by executing the callback). Signing in once more works. W87-2 adds the recovery path.
- **The reason needs the durable row.** Without a store, or after the purge, the 401 is the generic
  expiry (FM-25's chosen side).
