# Session prompt: bring-your-own key build, and the board row W28

Written by the session of 2026-10-17 (transcript `8267786b`). This file is
the session's wording. The owner's decisions are the CHG rows it names.

**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`. Read it first,
and follow it for roles, review rounds, gates, merging, production checks and cleanup.

## Read first

1. `docs/README.md`, then the newest `docs/analysis/<date>-session-handoff*.md`.
2. `docs/65-open-work.md`: row W28 and its Parked line (`make parked-check`). **Start only if W85, W86,
   W100, W87, W88, W80, W75 and W76 all read DONE** (CHG-061). If one does not, stop and say so.
3. `docs/19-change-control-log.md`: CHG-011 (D8, D9), CHG-026 (a), (b) and (f), CHG-047, CHG-059,
   CHG-061, CHG-062 and CHG-075 to CHG-080 (the owner's W28 decisions of 2026-10-17).
4. **The one W28 analysis:** `docs/analysis/2026-10-17-w28-key-storage-research.md`. Sections 9 to 13
   are the build's brief: operations, failure modes, the judge and the banners, the constraints, and
   the tests T1 to T32. Then ADR-0180 (the decided design), ADR-0121 (superseded by ADR-0180; its
   first status sentence is pinned by tests, so it is never edited), ADR-0123 (the token binds panel
   and shape), ADR-0130 (the 2026-09-24 hard stop on stored provider keys, lifted by CHG-075 for a
   user's own OpenRouter key, and for the later optional Tavily key by the option the owner chose in
   CHG-078, which CHG-075 records) and ADR-0163 (Sentry). Section 12's line numbers are on `a2af06c`:
   re-derive each on your own base before you build on it.
5. **Outside the repository**, in the owner's evidence folder: `~/Projects/quorum-ai-evidence/2026-10-17/w28-research/`
   (six research reports, `r1-fly.md` to `r6-repo.md`, with every source and command) and
   `~/Projects/quorum-ai-evidence/2026-10-17/w28-inputs/` (the two inventories, the research brief, and
   the 21 key-safety tests of 2026-10-13); and the raw map of 2026-09-29,
   `~/Projects/quorum-ai-evidence/2026-09-29/workflow-reports/byok-pr1-map-wf_aedbee72-7a1.md`. They are
   agents' reports: check each claim before you build on it.
6. **The owner's OpenRouter sign-in trial.** Section 16 of the research file lists what it settles
   (U1 to U8). If its results are not yet recorded there as "[measured by the owner, date]", ask the
   owner for them before building the connect flow; the steps are in `r2-openrouter.md`.
7. `git ls-remote origin 'refs/heads/*'` and `gh pr list --state open`.

## The items, in order

W28 is several pull requests, one concern each, each deployed and checked live before the next.
The feature stays off on the live site until the owner turns it on. Route each with
`make skill-route ITEM=W28` and again with `make skill-route DIFF=origin/main`: expect the
sign-in-session, money, ai-output-judge, interface, privacy-retention and settings classes. Money,
sign-in and privacy are touched, so the failure-modes role runs first; sections 9 to 11 of the
research file are its starting list, not a substitute.

1. **W28 pull request 1: connect, store, remove, and the resolver, off by default.**
   - A setting, off by default (in `.env.example` too), with the key routes answering 404 while off.
   - OpenRouter sign-in only (CHG-077): start and callback routes on their own path, registered with
     `add_api_route` (55 of 55 decorated functions); S256 PKCE and a one-time `state` bound to the
     session, both kept on the server; `state` checked before the pending entry is discarded (W80's
     lesson); the code exchanged on the server; the callback query redacted.
   - Storage per account (CHG-076) in its own table, added by a guarded migration with
     `PRAGMA secure_delete`: AES-256-GCM, a fresh 12-byte nonce, associated data binding the account
     id, the master-key version and the purpose; the last 4 characters, a SHA-256 fingerprint and the
     dates. A new master-key setting, not `QUORUM_TOKEN_SECRET`; production refuses to start without it
     only when the feature is on. Rotation by version (ADR-0180 decision 4).
   - Status (last 4, dates, the OpenRouter limit if any, the no-limit warning, CHG-077), remove
     (deletes the row; no run spends a user's key yet, so the mid-run rule waits for pull request 2),
     "Also remove my OpenRouter key" on sign-out-everywhere, ticked by default (CHG-076), and account
     deletion.
   - The resolver at `query_run_orchestration.py:1247-1248`, returning today's key and source exactly
     while the setting is off; the misconfiguration check reads the resolved key; fail closed, never the
     app's key (ADR-0180 decision 8).
   - **The board in the same pull request:** W28's needle is re-pinned to one only the last W28 pull
     request removes, and the tests that pin W28's frozen row and plant on it move to a synthetic row,
     with the reason (research file, section 12 item 3). `docs/41-security-controls.md` CTRL-006 is
     corrected once the security session's rows no longer own that file; a new measure there first
     needs a reviewed change to the id rule, since SC-01 to SC-99 are all used (section 12 item 8).
   - Tests first, with their "red when" lines: T1 to T4, T7 to T14, T16 to T18, T20 to T23, T28, T30
     and T31 (section 13). Build every canary key at run time (`"sk-or-v1-" + secrets.token_hex(32)`),
     never as a literal: GitHub push protection is on for this repository.
2. **W28 pull request 2: a run on the user's key.** Live answers and the judge on by default, no
   operator setting (CHG-077, CHG-080): one predicate for "this run holds a key that may be spent",
   read by the three places that read the app's flag today; the judge on the user's key, needing only
   its model id, as a priced `by_stage` row; the user's budget window ($5 default) and per-run cap
   ($0.50 default), asked before a run would cross either; the shared daily ceiling, the per-account
   app allowance and the live window not applied to a user-key run (CHG-078, CHG-080); the app's
   Tavily key never spent on it (CHG-078); removal or replacement of the key during a run: the page
   asks whether to stop or finish, and no answer means stop (CHG-078); the banners, the receipt,
   `/status` and the watchdog per section 11 (the readiness banner reads the account's key status
   from the key's own route, because `/ready` has no session); the stale judge comment at
   `main.py:1745-1751` corrected (section 11). Tests T5, T6, T15, T24 to T27, T29 and T32, and two
   more, written first: whether a user-key run's spend enters the shared daily ceiling's total
   (`feedback_store.py` `_spend_total_locked` has no credential-source filter), with an exact count;
   and live answers and the judge on by default on a user-key run (ADR-0121's table).
3. **W28 pull request 3: peer critique as the user's per-run choice** on a user-key run (ADR-0121,
   carried into ADR-0180; the token already binds the shape, ADR-0123), with a test for the choice
   and for its "on by default" in ADR-0121's table. `_peer_critique_in_effect` (`main.py:402` on
   `a2af06c`) is a fourth place that reads the app's posture.
4. **Later, not required for W28 to work:** an optional Tavily key of the user's own (CHG-078),
   pasted on a locked-down page; test T19 there (and on any validator pull request 1 adds).

The abuse-limit numbers for signed-in users with their own key (the owner's 2026-09-23 words, quoted
in ADR-0180, are put to the owner as an abuse-limit question), the audit-row retention and the key
metadata's (`docs/48-data-retention.md`, "Pending approval"), the privacy text, which law applies,
OpenRouter's terms (U9), whether a key is personal data (U13) and the page copy are not decided
(ADR-0180, "Not decided"): ask the owner in one batch at the start, with examples and a
recommendation each. For the user-journey tester: `docs/113-user-journeys.md` has no own-key journey
yet, and row W94 (limits at scale, among them that sign-in-only sessions have no site-wide cap) overlaps the
abuse limits. Also check whether a board row now owns short Fly
token lifetimes (none did on 2026-10-17; the two app deploy tokens expire in 2046): every design
relies on keeping the circle that can deploy small, so raise it with the owner if none does.

## Approvals

Sending this prompt approves the following for each W28 pull request above, and the
end-of-session handoff (docs only).
- Push and open the pull request.
- Squash-merge through `make close-guard`, with `EXPECT_CLOSE=""`.
- Deploy, with the feature off.

Each needs every required gate green and every reproduced blocker fixed. Nothing else is allowed:
- no paid call;
- no `fly secrets` change: setting the master key and turning the feature on for the live site are the
  owner's, so give the owner the exact commands, with a check before and after;
- no change to GitHub's repository settings;
- no attack on production;
- no change to an OpenRouter, Fly or Google account.

## End of session

1. Write the narrative handoff. Every "merged" or "in production" must cite its pull request.
2. Write the next session's prompt from `.agents/skills/work-item-delivery/prompt-template.md`.
3. In the handoff pull request, move this file into `docs/archive/YYYY-MM/` (run `ls` there first;
   add a date suffix if the name exists) and commit the next prompt at the root.
4. Run `make handoff` last. It prints the line for the owner to paste; end the closing status block
   with that line under "Next action".
