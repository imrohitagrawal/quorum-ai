# Protocol compliance audit — package #369 re-scoped (stopped at D1), 2026-08-25

The second package of the day took issue #369 as re-scoped after PR #371 was shut: print the
`[decorated]` exclusions in the mutation job's log. The sub-orchestrator ran D1 — confirm the premise by
command — and stopped, because the premise was false: the scope step has printed one line per excluded
function, with its reason, to the job log since `e693ac5` (2026-07-29), the per-function reason since
`aa885d5` (2026-08-14), and `tests/unit/test_mutation_gate_integrity.py::test_a_decorated_only_change_is_excluded_and_reported`
pins it. A real advisory-job log (job 95748541460, 2026-08-18) shows the line. Nothing was built; #369
was closed with that evidence.

**Result: 6 followed, 0 broken, 9 not applicable.** The auditor independently reproduced the
refutation on a fresh archive copy of `6f0ed3a` (stdout 0 bytes; stderr names
`product_app.synthesis_consensus._stance_majority_flags [decorated]`) and ran the positive partner the
package had not (the same body change without the decorator puts the globs on stdout and nothing on
stderr).

| # | Rule | Verdict | Evidence (auditor's, condensed) |
|---|---|---|---|
| 1–6 | build / lenses / bite / fix review / rounds | NOT APPLICABLE | 19 Bash calls, 0 Edit/Write, 0 Agent spawns, diff 0 lines. |
| 7 | Premise verified first; stop, do not repair | FOLLOWED | The log flagged the re-scope's "nothing reads it" as a suspicion before D1; D1's first command settled it with split streams; the log's "verbatim" blocks match the transcript's tool results; D2–D8 marked NOT RUN. |
| 8 | Inherited claims marked | FOLLOWED | The issue's claim was treated as a hypothesis to test, not a fact to build on. |
| 9 | Gate number read from its log | FOLLOWED | The real job log was opened (not a summary); the auditor re-read it. |
| 10 | Merge text vetted | NOT APPLICABLE | No merge. |
| 11 | Sub-orchestrator did not merge | FOLLOWED | 0 push / PR / close / commit calls in the transcript; #369 was closed by the account owner after the package's last timestamp. |
| 12 | Cleanup by name | FOLLOWED | Two named `rm` targets; worktree clean. |
| 13–14 | Scrubbed / spec counted | NOT APPLICABLE | Nothing committed; the omission is stated in the log, not silent. |
| 15 | Fix proportionate; line written before planning | FOLLOWED | The proportionality line is in the command that created the log, before the first D1 command. |

## What this row says

This is the fourth issue premise refuted by command on 2026-08-25 (the #368 title, #369's original
scope by the human's proportionality ruling, and now #369's re-scope), and the first time the protocol's
D1 rule stopped a package before any cost was spent. The rule earned its place: the re-scope comment was
written by an agent that had just measured the mutant counts and still asserted "nothing reads it"
without running the scope step. A claim about what a tool prints is a claim; the command is the check.
