# 2026-09-28 to 2026-09-30: the owner discussion, the engineering review, the harness plan

Copied into the repository on 2026-09-30 from the outside evidence folder
`~/Projects/quorum-ai-evidence/2026-09-29/` (local git history there, not
pushed). The probe scripts, screenshots, CSVs and the seven-plus-six research
lens reports stayed outside; the files here cite them by path.

## Read first, in this order

| File | What it holds | Read when |
|---|---|---|
| `NEXT-SESSION-PROMPT.md` | The plan: the owner's mandate, decisions, order of work, traps, the agent account | Starting any Quorum session |
| `OWNER-DISCUSSION-LOG.md` | Every owner message of the session, verbatim, with a status table per point | Before planning; update its Status column when a point is done |
| `ENGINEERING-REVIEW-2026-09-29.md` | Why the owner's bugs slipped past testing; the prevention plan | Designing the test lane, roles or checks |
| `owner-bugs-root-causes.md` | Root causes of the owner's bugs 1–9, with code lines (was `inv-results.md`) | Fixing any of bugs 1–10 |
| `approach-synthesis.md` | The development approach, enforcement layers and order (was `approach-research/synthesis.md`) | Planning the harness |
| `skills-tools-shortlist.md` | Tools and skills to adopt, defer, reject (was `skills-tools-research/shortlist.md`) | Choosing tools or skills |
| `NEW-PRODUCT-STARTER-PROMPT.md` | The prompt for the new-product starter | After Quorum steps 0–2 are DONE |

The decisions in these files are recorded as CHG-026 in
`docs/19-change-control-log.md`; that row is the record, these files are the
source it quotes. The research conclusions are PROPOSED until confirmed in plan
mode.

## Still outside the repository

`inv-*/probe/` (bug reproductions and the signed-in browser harness
`harness.py`), `eng-review/` (defect census CSV, probes),
`workflow-reports/` (review and code-map reports), `approach-research/` and
`skills-tools-research/` (the lens reports and the Codex and sceptic
contests), `findability/measure_reachability.py` (now
`scripts/measure_doc_reachability.py` here).
