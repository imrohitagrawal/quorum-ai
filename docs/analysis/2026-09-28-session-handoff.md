# Session handoff — 2026-09-28

The session ran the queue in `CONTINUE-2026-09-25-ULTRACODE-PROMPT.md` §5
(the owner confirmed the order on 2026-09-25 at 16:02:06Z, as that file
records). The record of what merged is `git log origin/main`; each pull
request body carries its evidence. This page says only what is NOT in
`git log`.

## Merged and running in production

`git log --oneline 864898c^..a2801da` lists them: W30 #514, W31 #516,
W32 #517, W7 part 2a #518, W7 part 2b #519 (and #515, a test-server fix). `/status` reported
`build_sha` `a2801da…` after #519's deploy (one Deploy job succeeded,
run 36347465450; two were cancelled by concurrency).

## In flight: W7 part 3, pull request A — NOT merged

- Branch `origin/w7/session-safety` at `14dde83` (pushed, no pull request).
  Worktree `quorum-ai-wt-w7c` holds it locally.
- What it is: sign out everywhere, sign-in events, a limit on starting a
  sign-in (CHG-021 c to e; ADR-0137 on the branch). Values are PROPOSED —
  AWAITING OWNER.
- History: two review rounds; round 2 reproduced two defects that round 1's
  own fixes had added. The owner approved one bounded simplifying round
  (2026-09-28, 12:14:14Z), committed as `14dde83`.
- **What it still needs, in order:** the mutation proof
  (`uv run python scripts/proofs/w7_session_safety_mutations.py`, in a
  `git archive` copy), all gates and both e2e lanes on `14dde83`, then ONE
  final review of the simplifying round. Merge only if that review finds no
  reproduced blocker; otherwise park it and ask the owner. The runs of
  those checks on `14dde83` died when the disk filled (ENOSPC), so nothing
  about `14dde83` is measured yet beyond the affected test files passing
  locally before the disk filled.

## Still queued (§5), not started

1. **W7 part 3, pull request B: idle expiry** with a keep-active reminder
   (CHG-021 b). Board needle: `ABSENT src/product_app/config.py ::
   signed_in_idle_minutes`. Read first: the failure-mode page on the
   branch above (`docs/analysis/2026-09-28-w7-session-safety-failure-modes.md`)
   and ADR-0137. A read-only map found, on `a2801da`, that an idle-expired
   signed-in session becomes a new counted anonymous session, so after two
   in a day an address gets 429 and cannot even start signing in again;
   sign-in is on in production, so this can happen today. The map's
   reports were not committed; re-measure before relying on them.
2. **W29** (#447 judge wiring, ADR-0124): DRAFT, and stop if the input
   reserve moves a money value.
3. **BYOK (W28)**: the first pull request as a DRAFT only; ADR-0121 stays
   PROPOSED — AWAITING OWNER.

## Waiting on the owner

- #511 retest; the Google Audience check.
- The allow-list and invite-link secrets: the exact commands are in
  `DEPLOY.md` and the bodies of #516 and #517 (no `fly secrets` command was
  run by the session).
- PROPOSED values: W31 and W32 bounds (ADR-0133, ADR-0134); ADR-0137's four
  values (on the branch).
- Open questions recorded in ADRs: how long the cost ledger and Sentry may
  keep the spend key (`docs/48`, ADR-0136); whether sign-out everywhere
  should cancel runs already running, and whether other devices it signs
  out should get a session the daily cap does not count (ADR-0137).
- #519's advisory mutation job was cut at its deadline (UNMEASURED; 9
  survivors listed in a comment on the pull request).

## Traps this session paid for

- **Disk.** Parallel reviewers each ran `uv sync` in their own
  `git archive` copy; with a proof copy and the e2e lanes that filled the
  disk and killed runs mid-way (their results do not count). Check
  `df -h /System/Volumes/Data` before fanning out; a copy can reuse an
  environment with `UV_PROJECT_ENVIRONMENT=<main checkout>/.venv` when its
  dependencies match.
- **The decorated-function cap.**
  `tests/unit/test_mutation_test_set_integrity.py` caps decorated
  functions under `src/product_app` at 55, and the tree is at 55: a new
  `@field_validator` or `@router` route turns a required check red. Use
  `add_api_route`, and check a rule outside a decorator.
- **A fix round can add the next blocker.** In #519 the round-1 fixes added
  two defects that round 2 reproduced; in W7 part 3 pull request A, both of
  round 2's blockers came from round-1 fixes for ADVISORY findings. Record
  advisory items; fix only what blocks.
- **zsh does not split `$VAR` into words**: use `${=VAR}` for a list of
  test files.
- **A mutation proof must run every test file the change can break**, not
  only the feature's own; #519's first fix turned 7 tests red in another
  file.
