# W5, second pull request: how serving the judge's verdict on a quick answer can fail

Written before the code (AGENTS.md rule 16e). The owner decided on
2026-09-24 that a quick answer shows *"Judge: well supported/partly
supported/not supported along with reasons and artifacts to support why"*
(`docs/analysis/2026-09-24-w5-parked.md`). Today the served result carries
no judge text at all (`tests/unit/test_evaluation_projection_has_no_judge.py`,
decision D-5), for the reason listed first below. This page lists what can
go wrong when that changes, and the design answer to each.

| # | Failure | Harm | Design answer |
|---|---|---|---|
| 1 | **Injected text in the reasons.** The judge reads the answer and its cited pages, both of which an attacker can influence; its `rationale` can repeat or be steered into attacker text: a link, a phone number, "ignore the warning above". | The page shows attacker text under the product's "Judge" label. | Serve the reasons as PLAIN TEXT: the server reduces every link-shaped token to its bare host or removes it (ADR-0127 lists the shapes) and the served field is documented as model-written; the UI pull request renders it with `textContent`, never the Markdown renderer. Length is already capped at 4,000 characters by the verdict schema. |
| 2 | **A level the judge never gave.** No judge configured, the call failed, or the verdict was refused as non-conforming, and the page still reads "well supported". | False assurance on the one surface meant to give assurance. | A fourth level, `not_checked`, is served whenever there is no conforming verdict, and the level is derived only from a verdict object, never defaulted. |
| 3 | **A generous mapping.** Scores of 0-5 mapped so loosely that a verdict with a zero or `hallucination_risk: "high"` reads "partly supported". | The quick page would contradict the rule the panel trust score already applies (`verdict_supports_verification`, #267). | `not_supported` whenever that rule refuses the verdict (a zero, or high risk); `well_supported` only at the top of both scales with low risk; everything else `partly_supported`. The thresholds are the session's design, recorded in the ADR as such. |
| 4 | **The reasons reach a panel run.** | The panel page's D-5 guarantee is broken silently. | The field exists only on the quick verdict object, which is `null` on every panel run; a test pins both, and the D-5 ban test is narrowed deliberately to that one path. |
| 5 | **The reasons are stored.** | Model-written text about provider prose lands in the durable store, which ADR-0013's privacy posture keeps free of prose. | Nothing of the verdict text is persisted; the run store gains only the `mode` column. |
| 6 | **"Artifacts" that are not the judge's.** The page lists sources the judge never saw (it caps them at `JUDGE_MAX_SOURCE_LINES`). | The evidence list overstates what was checked. | The served sources come from the SAME selection function `build_judge_evidence` uses, factored out, not a second copy. |
| 7 | **A stale or foreign verdict.** | One run's verdict shown on another. | Read from the per-run memo keyed by the run id, as the panel's `judge_status` is. |
| 8 | **No carrier for the safety notice.** A quick answer to a high-stakes question shows no caveat, because the only carrier today is the synthesis. | The caveat the owner agreed to keep disappears on exactly the runs with no synthesis. | `result.safety_notice` on a quick answer: the same `HIGH_STAKES_NOTICE_FRAGMENT` the synthesis uses, decided by the same `_high_stakes_required` rule (query and context). |
| 9 | **The mode column breaks the existing database.** Production's run store is a SQLite file on a volume; a new NOT NULL column without a default, or a table rebuild, fails or loses rows on deploy. | Run history stops being written in production. | `ALTER TABLE runs ADD COLUMN mode TEXT NOT NULL DEFAULT 'panel'` when the column is absent, tested against a database created with the old schema. |

Not in this pull request: the per-claim evidence (claim, source, supports /
contradicts / unsourced). Today's verdict schema has no claim list, so it
needs the judge prompt change, which is W5's fourth pull request
("verification only", the owner's words of 2026-09-24).
