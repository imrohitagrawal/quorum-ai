# ADR-0034: `docs/NN-*.md` numbering ranges are documented and gated

## Status

Accepted — 2026-08-11 (repo-housekeeping PR 6)

## Context

`docs/` uses a two-digit (now sometimes three-digit) numeric prefix on most
top-level filenames. Nothing in the repository ever wrote down what the
ranges mean. Grepping for range language before this ADR returns zero hits
in `docs/`, `AGENTS.md`, or anywhere else — verified:

```
$ grep -rln "numbering scheme\|number range\|docs/NN" docs/ AGENTS.md
(no output)
```

The predictable result: **14 numbers collided** (00, 02, 03, 04, 09, 19, 29,
34, 70, 71, 72, 73, 91, 95 — 28 files), accumulated silently over the
project's history because nothing checked a new doc's number against the
existing tree before it was committed. Housekeeping PR 4 resolved all 14
(see that PR and `docs/analysis/2026-08-11-repo-structure-audit.md`), and
this ADR is what stops the next 14 from accumulating the same way.

## Decision

**The ranges below are the record.** They were derived by reading the
post-PR4 tree (no earlier version of this scheme existed to preserve), not
invented — each range groups files that were already thematically
clustered:

| Range | Theme | Notes |
|---|---|---|
| 00–01 | Entry / dashboard | `00-factory-console.md`, `01-product-brief.md` |
| 02–09 | Discovery | personas, stakeholders, source-of-truth, problem/success framing, scope, roadmap |
| 10–19 | Requirements | FR/NFR, acceptance criteria, glossary, edge cases, registry, traceability, change control |
| 20–29 | Architecture & domain | architecture, domain model, API/data contracts, ADR index, business rules, state machines |
| 30–39 | UX & delivery process | UX design, accessibility, content design, Jira/Confluence process docs |
| 40–49 | Safety, security & risk | threat model, security controls, AI safety, privacy, risk register |
| 50–59 | Test strategy | test strategy/data, contract/resilience testing, AC-to-test map, flaky register |
| 60–69 | Implementation planning | implementation plan, vertical slices, delivery decomposition, tech debt, feature flags |
| 70–79 | Release | CI/CD, release plan, rollback, release evidence/checklist |
| 80–89 | Observability & ops | observability, SLOs, alerts, runbooks, incident response, dashboards |
| 90–99 | Product & publishing | feedback loop, naming, visual assets, demo storyboards, study/FAQ/article/LinkedIn plans |
| 100–110 | Production feedback & skills | production signals, customer feedback, incident learnings, external-skills strategy, command reference |
| **111–124** | **Collision-resolution overflow (housekeeping PR 4)** | **Not a theme** — the 14 files bumped off their original collided number. See table below. |

**111–124 is explicitly not a new thematic range.** It exists because PR 4
needed *somewhere* to put the losing half of each collision without
inventing a numbering redesign mid-cleanup (that would have been a much
larger, riskier diff — see PR 4's own PR body). Anyone picking a number for
a genuinely new doc should use a free slot **inside** the range that
matches its theme, not append after 124. Known free slots as of this ADR
(re-derive before using — this list decays):

```
$ git ls-files 'docs/*.md' | grep -E '^docs/[0-9]' | sed -E 's#^docs/([0-9]+)-.*#\1#' | sort -n | uniq \
    | awk 'NR>1 && $1-prev>1 {for(i=prev+1;i<$1;i++) print i} {prev=$1}'
```
→ 25, 26, 27 (architecture range), 58 (test-strategy range), 65–69
(implementation range), 75–79 (release range).

### What moved to 111–124, and why (from PR 4)

| New # | File | Old # | Kept at old # instead |
|---|---|---|---|
| 111 | start-here | 00 | factory-console (33 references vs. 3) |
| 112 | personas | 02 | stakeholder-map (4 vs. 0) |
| 113 | user-journeys | 03 | source-of-truth (8 vs. 0) |
| 114 | success-metrics | 04 | problem-statement (9 vs. 6) |
| 115 | release-scope | 09 | roadmap (5 vs. 4) |
| 116 | signoff-record | 19 | change-control-log (4 vs. 3) |
| 117 | event-catalog | 29 | state-machines (2 vs. 0) |
| 118 | qa-test-charter-jira | 34 | jira-issue-authoring (8 vs. 4) |
| 119 | performance-model | 70 | ci-cd-plan (7 vs. 1) |
| 120 | load-test-plan | 71 | release-plan (4 vs. 0) |
| 121 | capacity-plan | 72 | rollback-plan (4 vs. 0) |
| 122 | bottleneck-analysis | 73 | release-evidence (14 vs. 0) |
| 123 | session-handoff-template | 91 | product-naming (4 vs. 1) |
| 124 | demo-evidence | 95 | production-readiness-review (14 vs. 5) |

## Enforcement

`tests/unit/test_docs_numbering_no_collisions.py` fails the moment a new
`docs/NN-*.md` collides with an existing number — see that test for the
exact assertion and its RED proof. This is the gate this ADR exists to
justify; a documented convention nobody checks is exactly how the 14
collisions this ADR is cleaning up after happened in the first place.

### Rejected alternative: renumber everything into clean, gapless ranges

Rejected. It would touch every one of the ~60 validator literals and ~149
config references AGENTS.md documents (see rule 1.1), for a purely
cosmetic gain (closing gaps that don't cause any functional problem — a
gap is not a collision). The actual defect is collisions, not gaps; fixing
only the actual defect is the smaller, safer, equally-effective diff.

### Rejected alternative: leave the scheme undocumented, rely on review

Rejected — this is exactly what the 14 collisions are evidence against.
Human review already had every opportunity to catch each of the 14 as it
landed and did not, over what the git history shows is months of separate
commits. A documented scheme with a mechanical gate is the only thing that
scales past "someone happened to notice."

## Consequences

- A contributor picking a number for a new top-level doc now has a table
  to consult and a gate that catches a mistake immediately, instead of
  discovering it in a future audit.
- The 111–124 range reads as an irregular tail to a new reader. This ADR
  is that reader's explanation — link to it from `docs/24-adr-index.md`
  (auto-generated) and, if a future reader asks "why are 111-124 like
  that," this document is the answer.
- If `docs/` grows enough that a themed range fills up (e.g. 00–09 discovery
  is already fully occupied with zero free slots), the next collision in
  that range will need a **new** ADR extending or splitting the scheme —
  this one only documents what exists today, not a plan for future growth.
