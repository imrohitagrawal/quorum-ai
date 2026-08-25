# Protocol compliance audit — package #369 (PR #371), 2026-08-25

Phase F of the autonomous work-loop prompt (root-level; tracked since this pull request): an auditor that did not do the work reads the
package's contemporaneous log, the sub-orchestrator's transcript and the diff, and decides per rule
whether the protocol was FOLLOWED, not whether it is good. Verdicts and evidence below are the auditor's;
the main orchestrator re-ran the two highest-consequence claims itself (mutation proof, CI log number)
before this note was written.

**Result: 12 followed, 1 broken (rule 5), 1 not applicable (rule 10).**

| # | Rule | Verdict | Evidence (auditor's, condensed) |
|---|---|---|---|
| 1 | One writer during build | FOLLOWED | Sub-orchestrator transcript at audit time: 74 Bash calls, 8 Agent spawns, 0 Edit/Write (82 Bash after the later merge-and-renumber step); every worktree edit is in that one transcript. All 8 planners/reviewers worked in their own `git archive` copies; no subagent wrote into the worktree. |
| 2 | Every lens executed, none only read | FOLLOWED | Bash calls per agent: planners 12 / 25 / 19; round-1 reviewers 16 / 14 / 15; round-2 reviewers 12 / 15. Every report ends with a commands-run section. |
| 3 | Lenses diverse, 3 not 5 | FOLLOWED | Planners: approaches / failure modes / test design. Reviewers: execution / prose / vacuity, then execution / vacuity-of-the-fix. 3 → 3 → 2. Gap noted: the rule-11a prose instruction was in the prose lens only. |
| 4 | Test proven to bite | FOLLOWED | Six D4 mutations, each with verbatim `E` output and a `diff -q` restore; auditor re-ran three on its own archive copy: plant `@functools.cache` → `2 failed, 7 passed` naming `product_app.synthesis_consensus:_stance_majority_flags [decorated]`; empty population → `assert 0 >= 20`; empty inventory → `3 failed, 6 passed`; restores proven. |
| 5 | Fix got its own review round | **BROKEN** | The round-1 fix (commit `4f2f173`) was reviewed. The round-2 fix (`009c021`) and the post-gate fix (`ada74dd`) were pushed with **no reviewer** — last review spawn 10:22 UTC, those commits 10:29 and 10:34, push 10:45. The final report did not list them as unreviewed leftovers. |
| 6 | Review capped at two rounds | FOLLOWED | Two rounds; leftovers recorded (equivalent survivors in ADR-0073; "does not run mutants" in the PR body; the close decision escalated). |
| 7 | Premise verified first | FOLLOWED | D1 re-ran the count on `3f5d335` before any build write: 384 mutants / 11 for the function → 373 / 0 with `@functools.cache`; pragma guard `5 passed` with the decorator planted. |
| 8 | Inherited claims marked | FOLLOWED | Every number in the ADR and PR body traces to a saved artefact from this package; the one forward-looking rate is marked "an assumption, not a measurement"; the stale "34 of the 40" is quoted as stale Makefile text. |
| 9 | Gate number read from its log | FOLLOWED (gap) | Local and CI numbers pasted (pytest `3612 passed`, `TOTAL 5847 … 95%`; Schemathesis `51`; validate-and-test `3571`). Two required contexts (FR traceability, e2e) were taken as ticks; the auditor read them (`29 requirements`; `51 passed`, `8 passed`). |
| 10 | Merge text vetted before merge | NOT APPLICABLE | No merge. **Recorded:** the PR body contained "If that is enough to close #369, close it on merge". GitHub parsed it as `closes [369]`. `make close-guard` printed `will close: #369 — none of them negated. OK.` and CI's `scripts/check_close_keywords.py` refuses only *negated* keywords — both would have let it through. Caught by the main orchestrator reading the body in Phase E; body reworded; GitHub's parse is now `[]`. |
| 11 | Sub-orchestrator did not merge | FOLLOWED | `gh pr view 371 --json state,mergedAt` → `OPEN`, `mergedAt: null`. |
| 12 | Cleanup by name | FOLLOWED | Every deletion names its target; the one wildcard (`d4/*.bak`, `d6/*.bak`) is confined to the package's own scratch subdirectories. No `git clean`, no `git stash`, no `git checkout <file>`. |
| 13 | Artefacts scrubbed | FOLLOWED | `gh pr diff 371` and the body and four commit messages: 0 matches for absolute paths, usernames, scratch-directory names or session identifiers. |
| 14 | Spec counted against implementation | FOLLOWED (one omission) | Report marks ~20 items BUILT / PARTLY / OMITTED. Auditor's own count agrees except one: the issue's third option ("fail when a changed function in scope generates zero mutants while its body changed") is omitted **and not named** in the report or the ADR. |

## Fix introduced a defect — YES, round 1

The round-1 fix (`4f2f173`) introduced two defects: its new wiring test accepted a canned re-raised
message (found by the round-2 vacuity lens, fixed in `009c021`), and it cited three hypothetical paths
that `tests/unit/test_cited_paths_resolve.py` then rejected (`make quality` exit 2; fixed in `ada74dd`).
The package log's D6 sentence "no fix in either round introduced a defect that a reviewer or a mutation
demonstrated" is contradicted by the package's own final report. This is the measured pattern the loop
prompt's rule 2 describes: the correction is more suspect than the original.

## Gates green having measured nothing

Stated as such by the package rather than called passes: local `make diff-cover` and the CI
`Changed-lines coverage >= 95% (blocking)` job ("nothing to measure" — no `src/` Python changed), and the
advisory mutation job (`scope.txt` empty). Not silent; honest-empty by design.

## What this one row says about the protocol (opinion, marked)

- Rule 5 collides with rule 6 on a package whose second-round fix needs a third look: the protocol's own
  answer is "ship with the leftovers written down", and the leftover was not written down. Reading: right
  but ignored — one row is noise; a repeat is the signal.
- Rule 10's tooling has a measured blind spot: a **non-negated** closing keyword the author did not intend
  passes both `make close-guard` and the CI body check, because both only refuse negation. `close-guard`
  does print the issue it will close; the protection is the human reading that line.

## Outcome, after the audit

PR #371 was **closed unmerged** at 11:21 UTC on 2026-08-25, on the human's decision taken in a second
session: the defect stands, but an 867-line inventory guard is disproportionate to a hole in an
**advisory** gate that had, per that comment, produced one real score (job 97606765828) and, per
`docs/metrics/defect-discovery-audit.md`, has caught 0 of 16 `src/` defects. #369 was re-scoped to
printing the `[decorated]` note the scope step already emits (roughly ten lines). The branch and
worktree were removed by that session; the work remains reachable at `refs/pull/371/head`.

This does not change the row: Phase F audits whether the protocol was followed, and it was, 12 of 14.
What it exposes is a gap the fourteen rules do not cover — **none of them asks whether the fix is
proportionate to the gate's measured yield**, which is the rule the repository's own "before adding a
gate" paragraph states and which this package's three planners and five reviewers did not raise. The
protocol was followed and still produced a pull request the human would not merge; proportionality is
a candidate fifteenth rule, for the human to decide.
