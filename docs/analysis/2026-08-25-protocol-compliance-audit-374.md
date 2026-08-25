# Protocol compliance audit — package #374 (PR #375), 2026-08-25

Third package of the day: `make close-guard` refuses a close nobody named (issue #374). Built by one
sub-orchestrator with three planners, three round-one lenses (execution, prose + proportionality,
breaker), one round-two execution re-check; six gates; PR #375. Audited by an agent that did not do the
work, reading the package log, seven sub-transcripts and the diff, and re-running the mutations.

**Result: 11 followed, 3 broken (rules 8, 9, 12), 1 not applicable (rule 10).**

| # | Rule | Verdict | Evidence (auditor's, condensed) |
|---|---|---|---|
| 1 | One writer during build | FOLLOWED | Sub-orchestrator: 56 Bash, 7 Agent, no Edit/Write; all seven subagents 0 writes into the worktree; each mutated only its own archive copy. |
| 2 | Every lens executed | FOLLOWED | Bash calls: planners 14 / 8 / 9; reviewers 19 / 26 / 17; re-check 11. Every report carries run output. |
| 3 | Lenses diverse, 3 not 5 | FOLLOWED | approaches / failure modes / test design; execution / prose+proportionality / breaker; then one execution re-check. All 7 prompts carry the capitals read-only line. |
| 4 | Test proven to bite | FOLLOWED | RED `4 failed, 26 passed` before the change; ten mutations restored `diff -q`-identical. Auditor re-ran six on its own copy: never-refuse and always-refuse each `3 failed, 27 passed`; drop GitHub's parse from the union `2 failed`; the round-two pin `1 failed`. |
| 5 | Fix got its own review round | FOLLOWED | Round-one fix re-run by the execution lens; round-two fix (`4e5f85c`) re-checked; the final one-assertion commit (`1cbc6c6`) had no lens after it **and is listed by hash as unreviewed** in the report, which is what the rule requires at the cap. |
| 6 | Two rounds, capped | FOLLOWED | Round 1 on `896ad2a`, round 2 on `4e5f85c`, no third. |
| 7 | Premise verified first | FOLLOWED | First build-phase command, before any planner: the #371 body through `make close-guard` → `will close: #369 — none of them negated. OK.`, exit 0. |
| 8 | Inherited claims marked | **BROKEN** | Everything numeric was re-derived and holds (6 of 40 merged PRs differ by surface = 15.0%, re-derived by the auditor; 273/15 lines; 107 non-blank; eight CI-mode inputs byte-identical) — except one phrase: "a fifth caught by hand" was carried from AGENTS.md into a block headed "Measured yield" with no command behind it. |
| 9 | Gate number read from its log | **BROKEN** | Local and CI numbers pasted (quality `3607 passed`, api-contract 51, security 1143/0, CI pytest `3646 passed`, diff-cover honest-empty stated twice, two silent no-op diff-cover runs caught by a 0-byte log and re-run). Omission: the advisory mutation job printed `NO SCORE WAS PRODUCED … nothing in scope` and the package log recorded it only as "pass". |
| 10 | Merge text vetted | NOT APPLICABLE | No merge. The PR body and both commit messages were vetted before push (`0 closing reference(s)`, GitHub parse `[]`); the first draft commit carried `close #369` verbatim and the mandated grep caught it. |
| 11 | Sub-orchestrator did not merge | FOLLOWED | PR #375 `OPEN`, `mergedAt: null`. |
| 12 | Cleanup by name | **BROKEN** | The sub-orchestrator and five subagents deleted by name. The prose reviewer left a full archive copy and four files in the shared scratch root and never deleted them; the round-two re-check deleted a file name the sub-orchestrator had also used (disclosed in the log). Both are scratch, nothing in the repo. |
| 13 | Artefacts scrubbed | FOLLOWED | Diff, PR body, commit messages: 0 matches for absolute paths, usernames, scratch names, session ids. |
| 14 | Spec counted | FOLLOWED | Every item in #374 and every planner recommendation is in the diff; the one interpretation (compare against the UNION of merge text and GitHub's parse, because per-surface equality would refuse 15% of legitimate merges) is stated in the PR body and the ADR-0066 amendment. |
| 15 | Fix proportionate; target stated | FOLLOWED | The proportionality block was written before the first planner. The ~80-line target was exceeded (107 non-blank code+test lines) and the overrun is stated with its reason in the log, PR body and report. |

## Fix introduced a defect — YES, round 1

The round-one fix added a mypy `attr-defined` error in the new test (`Found 2 errors in 1 file`), caught
by `make quality`, fixed in the next commit and re-run by the execution lens.

## Gates green having measured nothing

- CI advisory mutation job: `NO SCORE WAS PRODUCED … nothing in scope` — **not stated** by the package (rule 9 break).
- Local `make diff-cover`, runs 1 and 2: 0-byte logs, exit 0 (a shell quoting slip made `make` build the default target) — stated, re-run literally.
- diff-cover run 3 and its CI job: honest-empty by design (`--cov=src`, the change is under `scripts/` and `tests/`) — stated.

## Main orchestrator's own checks before this note

Ran the new guard in the worktree: the #371 body is refused (`NOT expected but WILL close: #369`, Error 1); with `EXPECT_CLOSE=369` it passes; an expected-but-absent close is refused; the #373 merge text passes; `369a` exits 2. Two mutations by hand, restore proven, `30 passed`. Read the CI pytest log: `3646 passed`, `TOTAL 5847`, 95.28%.
