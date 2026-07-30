# Pending deletion — staging, not storage

**Created 2026-07-30. Owner: Rohit Agrawal. Tracking issue: see below.**

32 session handoff documents, staged here while their content is extracted to a
permanent home. **This directory is temporary by design and must not survive the
work package that created it.**

## Why staging rather than deleting outright

Three of these files were **untracked** and were deleted earlier today with `rm`.
They were recovered only because an unrelated `git add -A` had left them as
dangling blobs, recoverable with `git fsck --lost-found`. That was luck, not
process. Committing them here is the first time they have ever been recoverable.

The other 29 were tracked and always recoverable — for those, staging buys
reviewability rather than safety.

## The condition for deleting this directory

**All four must hold. Each is a measured check, not a judgement.**

1. **Every section accounted for.** A section-level inventory of all 32 files
   exists, and every heading maps to a destination in the extraction ledger.
   The check must print `N sections found, N accounted for, 0 unclassified` —
   a check that cannot state its denominator has verified nothing.
2. **Independent extraction agrees.** Read-only reviewers extract rule-bearing
   content **without seeing the ledger**, and their findings are a subset of what
   already landed. Anything they find that the ledger missed is the measure of the
   extraction's coverage.
3. **Destinations hold the content**, verified by grep against the destination:
   rules in `AGENTS.md`, stories in the case study, tasks as issues, derived facts
   dropped **with a recorded reason**.
4. **The case study exists.** These files are its raw material. Deleting them
   before it is written destroys the source for the artifact they are meant to
   become.

## Why the reviewers must not read the ledger

On 2026-07-30 the first extraction was "verified" by grepping `AGENTS.md` for the
rules already extracted. It reported success. It was **circular** — structurally
incapable of finding a rule never seen — and **17 operating rules were missed**,
including three blocking CI gates and the requirement for explicit human approval
before merging.

Handing reviewers the ledger and asking "is this right?" reproduces that failure
with more participants. The instruction must be: *read these files, list every
rule-bearing statement, then diff against the destination.* Independent
extraction, then comparison.

## If you are reading this and the condition is not met

The directory has outlived its purpose and is now the thing it was created to
prevent. `docs/learning/` in this repository was created in the initial commit,
given a licence, and held no content for the project's entire life — an unowned
directory becomes permanent. Either finish the extraction or delete the directory
and rely on git history (`git show <sha>:<path>`), but do not leave it here.

## Contents

29 files restored from `8536627^`, each verified **identical by `git hash-object`**
to the committed blob. 3 files (`COST-FAILOPEN-CLOSEOUT`, `COST-OPS-BACKLOG`,
`STREAM-B-CLOSEOUT`) recovered from dangling blobs at 16,994 / 17,768 / 20,440
bytes, matching their pre-deletion sizes.
