# W87-3 failure modes: the operator command that ends signed-in sessions

Written before any code, for board row W87's third pull request, and committed with the fix
(CHG-060). The list for W87 was written on 2026-10-18; its other sections were published with
W87-1 (`docs/analysis/2026-10-19-w87-1-max-age-failure-modes.md`) and W87-2
(`docs/analysis/2026-10-20-w87-2-recent-sign-in-failure-modes.md`). This file holds section 4, the
operator command, as W87-3's plan corrected it, and the failure modes the plan and Codex's four plan
reviews added (FM-49, FM-55 to FM-60). The design is ADR-0176.

The facts were read on `main` at `8463a72` (W86 merged) and re-read by W87-3's planner at
`27ad8e4` (W87-2 merged). "Measured" means a session ran a probe with temporary databases; "read"
means it read the code and ran nothing.

## 0. Facts the design rests on

| # | Fact | How it was found |
|---|---|---|
| F7 | While the process lives, the in-process cache is the authority: a cache hit returned at once, without reading the disk or any cutoff | read |
| F8 | A second connection that deletes the rows does not end a session the app has cached, and the app's next persisted touch writes the row back | measured (2026-10-18, and by the planner) |
| F9 | The store's connection waits 5 s for a lock; behind another connection's write transaction an app `save` blocked for 5.43 s holding the store lock, then failed with `database is locked` | measured (2026-10-18); inherited, not re-measured |
| F10 | `secure_delete` is per connection; a fresh connection reads 0 | measured |
| F18 | `accounts.email` is not unique, and changes only when its owner next signs in | read |
| F19 | Importing `product_app.auth` starts the `session-gc` thread; building a `SessionStore` migrates, sweeps history and may `VACUUM` | read |
| F31 | A store whose session-safety migration failed at open, on a file that already held its marker, answered "no cutoff" for every account | measured by the planner after Codex found it |

## 1. The command and how every process applies it

| FM | What could go wrong | How W87-3 answers it | Test (red when) |
|---|---|---|---|
| FM-27 | A rows-only command: the cached session lives on and the next touch writes its row back (F8) | Every process reads the durable cutoff on each signed-in cache hit, on the request thread | `tests/security/test_signed_in_cutoff_on_cache_hits.py::test_the_command_ends_a_cached_session_at_once_with_the_gc_stalled` (red when the guard call in `get` is removed) |
| FM-28 | A row written back before the cutoff applied is restored after a restart | The restore reads the durable cutoff, as before; `save` is now conditional too (FM-55) | `tests/security/test_signed_in_cutoff_on_cache_hits.py::test_after_the_command_a_restart_restores_nothing_even_from_a_planted_row` |
| FM-29 | The command's lock blocks app writes (F9) | One short transaction (68 ms for 10,000 accounts, measured by the planner) and a read-back, with a nonzero busy timeout; ADR-0176 records it as a second writer, short and rare | `tests/integration/test_end_sessions_command.py::test_one_short_write_one_read_back_and_no_record_of_the_run` |
| FM-30 | The command builds a `SessionStore` or imports `auth` (F19) | Its own connection, the SQL shared as constants; it imports `session_store` for those only | `tests/integration/test_end_sessions_command.py::test_importing_and_running_the_command_starts_no_thread_and_builds_no_store` |
| FM-31 | `--email` matches 0, 1 or several accounts (F18) | `strip()` and `casefold()` on both sides; every match ends | `tests/integration/test_end_sessions_command.py::test_an_email_matches_after_strip_and_casefold_and_every_match_ends` |
| FM-32 | The operator types the account's current Google email but the row holds an older one | Exit 1: "No account has that email address as of its last sign-in. Nothing was changed." | `tests/integration/test_end_sessions_command.py::test_each_exit_code_and_nothing_changes_unless_it_is_0` |
| FM-33 | `--all` ending anonymous sessions would make every anonymous visitor mint again against the network's limit of 2 a day | Rewritten to the owner's answer (CHG-066 (d)): `--all` ends signed-in sessions only. Anonymous and sign-in-only sessions, and the mint count, are left alone | `tests/integration/test_end_sessions_command.py::test_all_leaves_anonymous_sessions_and_the_mint_count_untouched` |
| FM-34 | Ending sessions resets a spend envelope | Spend is keyed by network and account, not by session; the command never touches an account row's id or spend key | `tests/integration/test_end_sessions_command.py::test_the_spend_envelopes_and_spend_keys_are_unchanged` |
| FM-35 | The output carries personal data | Counts and the cutoff only; the email in `argv` stays in shell history and `ps` (the owner's form, CHG-063 (d); ADR-0176, Known limits) | `tests/integration/test_end_sessions_command.py::test_no_output_carries_an_email_an_id_or_an_argument` |
| FM-36 | Exit codes are unclear in a `fly ssh -C` script | Five codes, each tested; refusals change nothing (ADR-0176, decision 3) | `tests/integration/test_end_sessions_command.py::test_each_exit_code_and_nothing_changes_unless_it_is_0`; `::test_exit_4_when_the_read_back_finds_a_row_and_a_rerun_exits_0` |
| FM-37 | The machine is stopped, so `fly ssh` may not reach it | The runbook checks `fly machine list` and starts it first. Whether `fly ssh` reaches or starts a stopped machine is UNVERIFIED (`DEPLOY.md`, "End sessions"). A process that starts later reads the cutoff on its first request | runbook |
| FM-38 | Someone who signs in again after the command keeps working, including an attacker holding the Google account | Said in the output and the runbook: this does not secure the Google account itself | `tests/integration/test_end_sessions_command.py::test_no_output_carries_an_email_an_id_or_an_argument` (the sentence is asserted) |
| FM-39 | A new sign-in event outcome would be new stored data | None is added (CHG-083 (b)) | `tests/integration/test_end_sessions_command.py::test_one_short_write_one_read_back_and_no_record_of_the_run` (no `INSERT`) |
| FM-49 | Several processes on one file: a sign-out everywhere in one leaves another's cached copy working | The same guard: every process reads the durable cutoff on its next lookup | `tests/security/test_signed_in_cutoff_on_cache_hits.py::test_a_sign_out_everywhere_in_one_process_ends_the_other_processes_cached_copy`; `::test_another_process_applies_the_command_on_its_next_lookup` |

## 2. Added by the plan and its reviews

| FM | What could go wrong | How W87-3 answers it | Test (red when) |
|---|---|---|---|
| FM-55 | A write-back in flight: a request read the old cutoff, waited on the command's lock, and writes after the commit | `save` is one conditional statement and returns whether a row landed; `flush` goes through `get` | `tests/unit/test_session_store_conditional_save.py::test_save_refuses_a_cut_off_session_and_says_so`; `tests/security/test_signed_in_cutoff_on_cache_hits.py::test_flush_runs_the_guard_and_writes_nothing_back_for_an_ended_session` |
| FM-56 | The cutoff cannot be read on a cache hit: the store busy, closed, or failing | Refused as an expired session (CHG-083 (a); since CHG-088, refused as unchecked: `SESSION_UNCHECKED`, the cookie kept, nothing minted); the read waits at most 6.0 s for the store lock (1.0 s until CHG-088 (b)); the cached copy is kept for the next check | `tests/security/test_signed_in_cutoff_on_cache_hits.py::test_a_busy_store_lock_refuses_the_cache_hit_and_keeps_the_cache`; `::test_a_request_meeting_a_held_store_lock_is_refused_with_its_cutoff_unread`; `::test_an_unreadable_cutoff_on_a_cache_hit_refuses_it` |
| FM-57 | The `fly ssh` session lacks the app's environment, so the command opens another file | No `SESSION_DB_PATH`, or an empty one, is exit 3: the command never falls back to the app's default path under the working directory, where a stray store would take the run (break-it round 2). A wrong path is exit 3: the owner check's `os.stat` refuses a missing file, and `mode=rw` never creates one (a file gone between the check and the open). Without `PYTHONPATH`, Python itself exits 1 with `No module named 'product_app'`. The runbook names both signs and gives an explicit fallback form. Whether `fly ssh` sessions get the image and `[env]` variables is UNVERIFIED | `tests/integration/test_end_sessions_command.py::test_each_exit_code_and_nothing_changes_unless_it_is_0` (`[missing file]`, `[missing file past the owner check]`, `[SESSION_DB_PATH unset]`, `[SESSION_DB_PATH empty]`); `::test_no_session_db_path_is_exit_3_and_a_stray_store_is_untouched` |
| FM-58 | Run as root (the planner read flyctl v0.4.118's `--user` default as `root`), the command would write the app's file as a different user than the app; what that does to the file's journal is UNVERIFIED | Exit 3 unless the effective user owns the file, with "Run as the file's owner: fly ssh console --user quorum" | `tests/integration/test_end_sessions_command.py::test_each_exit_code_and_nothing_changes_unless_it_is_0` (`[not the file's owner]`) |
| FM-59 | The store's readiness is latched not ready (F31), so "no cutoff" let every signed-in session through while the command exited 0 (Codex). Also from the planner's own revision: anonymous sessions must not be judged by `is_anonymous` while the accounts flag is latched, since it then answers "unknown" for every id | While not ready, the cutoff read, `save` and the restore decide by the account row; signed-in reads and saves fail closed and sign-in refuses. A read-only re-validation, the same one the constructor uses, runs once per GC tick and reopens access when the schema passes | `tests/security/test_session_store_not_ready_fails_closed.py::test_a_latched_safety_flag_refuses_every_signed_in_path_and_serves_anonymous`; `::test_with_the_accounts_flag_latched_too_anonymous_is_judged_by_the_row`; `::test_a_good_file_recovers_with_two_selects_and_one_pragma`; `::test_the_legacy_shape_on_a_read_only_file_stays_not_ready`; `::test_one_kind_determination_per_restore_and_its_answer_is_used` |
| FM-60 | A usage error echoes the email (argparse's own message) | One fixed sentence for every usage error | `tests/integration/test_end_sessions_command.py::test_no_output_carries_an_email_an_id_or_an_argument` (`[usage extra argument]`) |

## 3. Recorded limits

ADR-0176, Known limits: another machine is not reached; the email stays in shell history; anonymous
sessions are affected when their account-row read fails; a request already past its check finishes;
the 6.0 s bound covers the cutoff read's lock wait only, not the request (1.0 s until CHG-088 (b)); recovery waits for the GC
tick; account deletion in another process is not seen on a cache hit. FM-29's 5.43 s is inherited,
not re-measured; the planner's contended measurements are in ADR-0176, Measured.
