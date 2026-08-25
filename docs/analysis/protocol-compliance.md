# Protocol compliance ledger

One row per work package run under the autonomous work-loop prompt's Phase F. The auditor is
never the agent that did the work. Verdicts: F = followed, B = broken, N = not applicable. Evidence for each
verdict lives in the dated audit note linked in the last column.

Rules (numbers match the prompt's Phase F table):
1 one writer during build · 2 every lens executed, none only read · 3 lenses diverse, 3 not 5 · 4 test proven to bite ·
5 fix got its own review round · 6 review capped at two rounds · 7 premise verified first · 8 inherited claims marked ·
9 gate number read from its log · 10 merge text vetted · 11 sub-orchestrator did not merge · 12 cleanup by name ·
13 artefacts scrubbed · 14 spec list counted against implementation ·
15 fix proportionate to the gate's measured yield (added 2026-08-25 after package 1; scored from package 2 on)

| date | package | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | followed/broken/n-a | audit note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-08-25 | #369 → PR #371 (decorator mutation-surface inventory guard) | F | F | F | F | B | F | F | F | F | N | F | F | F | F | — (not yet a rule; the outcome says it would have been B) | 12 / 1 / 1 | `docs/analysis/2026-08-25-protocol-compliance-audit-369.md` |
| 2026-08-25 | #369 re-scoped (print `[decorated]` exclusions) — stopped at D1, premise refuted, nothing built | N | N | N | N | N | N | F | F | F | N | F | F | N | N | F | 6 / 0 / 9 | `docs/analysis/2026-08-25-protocol-compliance-audit-369b.md` |
| 2026-08-25 | #374 → PR #375 (close-guard refuses an unlisted close) | F | F | F | F | F | F | F | B | B | N | F | B | F | F | F | 11 / 3 / 1 | `docs/analysis/2026-08-25-protocol-compliance-audit-374.md` |

## Running tally after three packages (followed / broken / not applicable)

Rule 1: 2/0/1 · 2: 2/0/1 · 3: 2/0/1 · 4: 2/0/1 · 5: 1/1/1 · 6: 2/0/1 · 7: 3/0/0 · 8: 2/1/0 · 9: 2/1/0 · 10: 0/0/3 ·
11: 3/0/0 · 12: 2/1/0 · 13: 2/0/1 · 14: 2/0/1 · 15: 2/0/0 (scored from package 2).

No rule has been broken in two packages running. Four rules have one break each (5, 8, 9, 12); the
loop's own threshold for turning a rule into a gate is a repeat. Rule 10 has never applied because no
package merged inside the loop; the merge step was the human's each time.
