# Analysis → Plan Brief (for a fresh session)

**How to use this file:** open a NEW chat session, paste the **PROMPT** block
below, then paste the full transcript of the prior working session beneath it.
The new session will read the transcript + the ground-truth sources and produce a
granular, verified, categorized implementation plan as durable repo files.

**Why a fresh session:** the prior session is very long and risks context
compaction; a clean session has full context budget to go module-deep. This brief
is the durable bridge (not a chat paste of learnings, which evaporates).

---

## PROMPT (paste into the new session, then paste the transcript below it)

```
You are taking over a large analysis + planning task for the `quorum-ai` project
(/Users/rohitagrawal/Projects/quorum-ai). Below this prompt I will paste the full
transcript of a ~30-hour working session. Turn it into a GRANULAR, VERIFIED,
categorized implementation plan — down to the smallest module — written as durable
repo files under docs/, NOT as chat.

VERIFY — do not trust the transcript blindly:
- It is a working log containing in-flight claims that were LATER CORRECTED within
  it (e.g. an early "0 skills were downloaded" claim was wrong; some GitHub issue
  statuses were stated imprecisely). Treat EVERY factual claim in the transcript
  as a HYPOTHESIS to verify, never settled fact.
- Establish ground truth FIRST by reading:
  • the memory dir MEMORY.md + all *.md memory files
  • docs/day-one-quality-standard.md and AGENTS.md
  • `gh issue list --state all` and `gh pr list --state all`
  • src/product_app/ (esp. static/app.js, static/app.css, costs.py, providers.py,
    query_runs.py, synthesis.py), .github/workflows/, and note that `.claude/` is
    gitignored (local-only) so a hook there is NOT shared/CI.
- Enumerate the FULL population before any "all / none / complete / it-works"
  claim (the session's core lesson: narrow-sample → confident-wrong-conclusion).

OUTPUT IN TWO PHASES:

Phase 1 — TAXONOMY FIRST. Before any detail, present the complete CATEGORY MAP:
list every category/aspect (below) with a one-line definition and its scope, as an
index/table of contents. Prove it is EXHAUSTIVE — every bug, finding, principle,
and task from the transcript + ground truth must map to exactly one category, with
nothing left uncategorized. Stop and present this taxonomy for review before
Phase 2.

Phase 2 — GRANULAR TABLES. THEN, for each category from Phase 1, produce a
module-level table, breaking every item down to the smallest actionable task, one
row each, with columns:
| Category | Sub-module | Task | Exact file/path | Mechanism (skill / AGENTS.md /
hook / CI-CD) | Enforcement gate | Measurement / prove-red | Status | Priority |
Depends-on |
Do NOT summarize at a high level. Mark anything you cannot verify as UNVERIFIED
rather than guessing.

CATEGORIES (aspects) to define in Phase 1 and detail in Phase 2:
1. Bug ledger — every bug/finding, verified against the issue tracker. Known
   corrections: issue #21 (deploy) should be CLOSED (fixed but still open); #26 is
   only PARTIALLY resolved (key fixed; the silent-fallback observability bug
   remains); the /metrics-404 and "deploy gate keys only on the CI workflow"
   findings are UNFILED.
2. Best practices / principles — verify-first + plan-first; holistic + real-eye
   VISUAL testing (screenshots, CSS/layout/color/alignment, not just
   functional/API); enforcement below-the-line (influence vs gate); skill ≠ gate,
   plan-doc ≠ test; decompose vertical→horizontal with per-deliverable measurement.
3. Enforcement machinery — golden realistic fixture; visual snapshots
   (toHaveScreenshot); global rendering/behaviour invariants (no raw markdown, no
   overflow, monotonic timers); real-integration smoke (not page.route mocks); CI
   wiring (the shared gate) vs local hook (`.claude/` is gitignored).
4. Mechanism map — each practice/finding → skill / AGENTS.md / hook / CI-CD, with
   the instruction-vs-real-gate rationale.
5. Skills strategy — build skills grounded in facts (how/where/what/expected/
   NOT-expected), not derivative "what-to-do" checklists; provenance hygiene
   (built-in / user-global / vendored / factory).
6. Application playbooks — how to apply all the above in (a) a NEW greenfield
   project, (b) the CURRENT project quorum-ai (retrofit + bug-backlog order),
   (c) ANY other existing project (generalized retrofit).
7. Methodology — plan thoroughly first → loop (verify→implement→verify→implement)
   → document; decompose into vertical canonical slices then horizontal splits;
   categorize, measure, and quality-gate each deliverable.

End with: what remains UNVERIFIED, and the single next execution step.
```

---

## Ground-truth reading list (the new session must read these, not just the transcript)

- `MEMORY.md` + the 8 memory files (`minimize-paid-production-runs`,
  `simulated-data-hides-real-bugs`, `verify-first-then-implement`,
  `narrow-sample-wrong-conclusion`, `prod-live-execution-falls-back`,
  `tdd-and-live-verification`, `manual-live-check-is-browser-dependent`,
  `plans-highlight-skills`)
- `docs/day-one-quality-standard.md`, `AGENTS.md`
- GitHub issues #18–#33; PRs #25 and #28 (both merged)
- `src/product_app/static/app.js` + `app.css`, `costs.py`, `providers.py`,
  `query_runs.py`, `synthesis.py`, `.github/workflows/`

## Known-correct baseline (already verified against ground truth)

- 8 memory files exist; MEMORY.md index = 8 entries.
- Issues that exist and are OPEN: #18, #19, #20, #21, #24, #26, #27, #29, #30,
  #31, #32, #33. #16 is CLOSED (original cost issue).
- PRs #25 (cost, merged) and #28 (UI + CI-gated deploy, merged).
- Corrections to apply: close #21; #26 stays open for the observability half; file
  the /metrics-404 and deploy-gate-scope findings (currently UNFILED).
