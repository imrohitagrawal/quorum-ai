# Session handoff — 2026-10-18

The session of 2026-10-18 local (2026-10-17 UTC, transcript `9888e48e`) ran
`CONTINUE-BYOK-RESEARCH-FINISH-W28-PROMPT.md`, archived by this pull request as
`docs/archive/2026-10/CONTINUE-BYOK-RESEARCH-FINISH-W28-PROMPT.md`. It finished the W28 key-storage
research that the session of 2026-10-17 (transcript `8267786b`) stopped under the stop rule. A
security session (transcript `b12e5f2a`) ran in parallel on rows W85 to W76. The source of truth is
`git log` and the ADRs; this note says where things stand.

## Shipped

| Pull request | Merge commit | What | Decisions it added or rests on |
|---|---|---|---|
| #576 | `5ae015e` | W28 research: the one W28 analysis (`docs/analysis/2026-10-17-w28-key-storage-research.md`), ADR-0180, the requirement repairs of decision 6, the superseded notes and the archived plan, `CONTINUE-BYOK-BUILD-W28-PROMPT.md`. Documents only | added ADR-0180, CHG-075 to CHG-082; rests on CHG-047, CHG-049, CHG-059, CHG-061, CHG-062 |

This session checked #576 in production: of the three Deploy runs for `5ae015e`, the Deploy job of
run 39080566865 concluded `success` and the other two were cancelled; `/status` `build_sha` read
`5ae015ef1d5d8e6c7abedc4a16e948d6c2e2aaa7` and `/ready` returned 200. #576 changed documents only,
so nothing new is visible in the running app.

After that check the session closed draft #525 and deleted the branch `w28/byok-pr1-plan` (CHG-047: its
one file is `docs/archive/2026-10/2026-09-29-byok-pr1-plan.md`, on `main` since #576, its body
byte-identical; commit `7bdfa87` stays reachable as `refs/pull/525/head`). This pull request points
W28's Parked line at that file and adds row W110.

## What happened

- The session cut a new branch from `main` after W85 (#575), carried the old local branch over (every
  line it added or removed, checked by a sorted comparison), and applied the stop-rule plan's items 1
  to 23 (`~/Projects/quorum-ai-evidence/2026-10-17/w28-research/50-stop-rule-root-cause-and-plan.md`),
  running the command that settles each replacement before writing it.
- Two things it was handed were false, and it corrected them from the source: the plan's time for
  ADR-0180's quote (the question was asked at 17:59:06Z, not 18:03:47Z), and the 2026-10-17 session
  record's claim that the session's two views never reached the owner (its closing message at
  20:53:10Z gave them).
- The narrow re-check (a reviewer and Codex) found two replacements false a third time: "with no
  re-entry" in ADR-0180's Context, and "so the other reuses that verdict" in the research file's
  section 11 (a reader that times out waiting on the judge gets no verdict:
  `query_run_orchestration.py:2497-2504` at `a2af06c`). The session stopped for good, as the prompt
  required, and asked the owner.
- The owner chose B: delete the two phrases with no new wording, one re-check, then ship, and open a
  board row for the deploy circle (CHG-082). The re-check of the deletions passed.

## What the owner decided this session

- CHG-082: *"B, and open the row"*: the W28 research pull request ships with the two failing phrases
  deleted; the deploy circle gets row W110.

## Left for the owner

- **The OpenRouter sign-in trial**, before the W28 build: "The owner's trial" at the end of
  `~/Projects/quorum-ai-evidence/2026-10-17/w28-research/r2-openrouter.md` (about 20 minutes, a
  throwaway account). Optional: Fly's `secretkeys` trial, section (b) of `r1-fly.md`.
- **Row W110**, the deploy circle: mostly the owner's own account settings.
- **The evidence folders** `~/Projects/quorum-ai-evidence/2026-10-17/` and `2026-10-18/` are untracked
  with no remote; the W28 build prompt points at the first. Back them up, or decide they can go.
  The second holds the re-check reports and `w28-branches.bundle`, the two local W28 branches' commits
  (the 2026-10-17 review reports cite them), deleted from the repository after #576 merged.
- `fly tokens list --scope org` (U12), which the sessions' permission settings refused.

## For the security session (rows W71 to W101 are its, so this session did not edit them)

Checked by this session on the #576 tree:
- **W99**: its clause "`docs/18-requirement-traceability-matrix.md` names test files that never
  existed" is no longer true: every test path docs/18 cites exists. Its "docs/40 lists
  bring-your-own key as built" is now marked "not built" there.
- **W76**: its clause "Sentry breadcrumbs keep a key" conflicts with `main.py:182-202`: since W56 the
  whole event, breadcrumbs included, goes through the redaction; what survives is key shapes the
  pattern misses, which is W76's second clause, and dict keys, which are not redacted (ADR-0163).
- `docs/analysis/2026-10-17-asvs-5-level-2-check.md:295` says the volume's encryption is UNVERIFIED;
  `fly volumes list -a quorum-ai --json` printed `encrypted: true` on 2026-10-17.
- `docs/41-security-controls.md` CTRL-006 goes false when the W28 build lands, and every id SC-01 to
  SC-99 is used, so a new measure needs a reviewed change to the id rule first.

## Next sessions

- The security session continues from `CONTINUE-SECURITY-W85-W76-PROMPT.md`.
- `CONTINUE-BYOK-BUILD-W28-PROMPT.md` (at the root since #576) starts only when W85, W86, W100, W87,
  W88, W80, W75 and W76 all read DONE (CHG-061). `make handoff` prints a paste line for each root
  prompt named `CONTINUE-...-PROMPT.md`, sorted by name, so the W28 line comes first though it must wait.

## Advisory leftovers (recorded, not fixed)

From the two re-checks' reports (`~/Projects/quorum-ai-evidence/2026-10-18/w28-finish/`), not re-run by this session except where marked:

- Section 6, pattern 3 lists LangSmith among gateways that never show a stored key; `r3-products.md`
  marks LangSmith's provider-key read-back UNVERIFIED (Codex, the re-check).
- Section 6's table marks Make "not stated" for re-entry, while `r3-products.md` 3.2 counts it among
  stores that keep the key across restarts.
- Section 11's "COMPLETED at `:1664`" is the panel run's line; a quick-answer run completes at `:1437`.
- T26's "From" column cites only CHG-078, though its replacement half is the session's design.
- CHG-082 does not say that the session first recommended A "by the rule" at 21:46:13Z, nor that the
  owner's reply was the wording the session offered.
- `make fr-completeness` compares no titles and no AC ids, so the FR-012 and AC-025 repairs are
  pinned by no check (research file, section 18; measured by this session).

## Traps learned

- **zsh reads `$B:s` as a substitution.** `git show $B:src/...` failed with "ambiguous argument
  'a2af06cy_run...'"; write `"${B}:src/..."` or a literal.
- **A plan written to stop errors carried two of its own.** Both of its inherited facts that this
  session checked were wrong (item 2's time, and the record's "never reached the owner"). Check a
  plan's sources too, not only the text it asks you to change.
- **Deleting worked where rewording had failed three times.** Each rewrite of the judge's timing and
  the product headline added a new claim; deleting the failing phrase added none.
- **The W54 PDF tests can fail on this Mac with no code change.** Late in the session about 60 of
  them failed (`unusable` instead of `fetched`), though the same source code, unchanged since #576,
  gave 0 failures in `make quality` hours earlier, and none in #576's CI on Linux. Measured: the non-blocking `os.write` to the PDF child's pipe at
  `source_fetcher.py:630` raised `BlockingIOError: [Errno 35]`, which the reader turns into
  `unusable`. Why this Mac refused the write then is UNVERIFIED (free memory pages were low). Production
  is Linux; a write that the selector reports ready but the kernel refuses is still unhandled there, a
  lead for a later code row, not a reproduced production fault.
- **Disk.** Free space was 306 MB at the start and came back to about 11 GB during the session, from
  outside this work.
