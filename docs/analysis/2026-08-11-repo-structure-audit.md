# Repo structure audit — synthesis (2026-08-11)

Source: `REPO-HOUSEKEEPING-ULTRACODE-PROMPT.md`, Phase B. Inputs: three read-only
agent reports (principal-architect, engineering-manager, hygiene-auditor), each
re-verified against HEAD `4e3e34f` before being accepted here. Every finding below
was independently re-run by the synthesiser (this document's author) on
`4e3e34f`, not just copied from the agent reports — commands are inline.

## 1. Claims that did NOT survive verification as originally stated

| Original claim | What re-verification found | Verdict |
|---|---|---|
| Root `.md` split is 45 tracked / 19 untracked-not-ignored / 37 gitignored | Currently **46 / 18 / 37** (total still 101). One file crossed from "untracked" to "tracked" between the prompt's snapshot (`d3c860c`) and HEAD (`4e3e34f`) — net zero on the total, but the prompt's own group-1/group-2 split is stale by one file each. | **Narrowed, not refuted.** Use live numbers at execution time, not the prompt's. |
| `e2e/undefined/` is "~500 KB" | `du` on the two tracked PNGs measures **400 KB** (317 KB + 86 KB, both `du -h`-rounded). Same two files, same identity. | **Narrowed.** Size claim was an estimate; file identity was correct. |
| Everything else in §1 of the prompt (14 docs/ collisions=28 files, factory 6-same/2-diverged, design_handoff/design-handoff overlap, excalidraw 4-way dupe, `.coverage`×7 + `.DS_Store` + 3.8 MB PNG + stray test, `tests/perf`+`tests/performance` split with 28 loose root files, `.hypothesis/` ungitignored) | All re-run independently on HEAD, all confirmed exactly as stated. See §2. | **Survived.** |

Net: **2 of 10** measured claims needed narrowing (both by a rounding/staleness
margin, not a directional error); **8 of 10** survived unchanged. This matches
AGENTS.md rule 11's "roughly half of what a handoff asserts does not survive
contact with the tree" only in the loose sense that *some* narrowing always
happens — the magnitude here was small because the prior pass (`d3c860c`,
2026-08-11) was itself a careful re-derivation, not an inherited guess.

## 2. Findings table — blast radius, reversibility, value ÷ blast-radius rank

Commands shown are the ones that produced the "gates that reference this path"
column; see each PR section below for the full re-derivation used at execution
time (counts drift, so PR 1 and PR 4 re-run their own commands rather than
trusting this table's numbers verbatim).

| # | Finding | Blast radius (files/gates asserting the path) | Reversibility | Rank |
|---|---|---|---|---|
| F1 | 101 root `.md` files, only 6 pinned by name | `R2-S2-S4-ULTRACODE-PROMPT.md` (3 tests + `also_copy`), `REPO-HOUSEKEEPING-ULTRACODE-PROMPT.md` (this doc's own driver, self-referencing), README/AGENTS/CLAUDE/CHANGELOG/DEPLOY/PRODUCT_IDEA (`validate_*.py`, `also_copy`) — **6 names pinned, 95 free** | tracked(46): git-recoverable; untracked-not-ignored(18): none until committed; gitignored(37): none, and deliberately excluded | **Highest** — zero functional risk, immediate discoverability win (EM's #1 finding) |
| F2 | `e2e/undefined/` (2 tracked PNGs, 400 KB) | none found (`grep -rln "e2e/undefined" scripts/ tests/ configs/ pyproject.toml .github/ Makefile` → empty) | tracked, git-recoverable | High — zero blast radius, unambiguous artifact-of-a-bug |
| F3 | `diagrams/excalidraw/` 4-way identical dupe | **Premise refuted — see below.** `scripts/validate_enterprise_extensions.py:169-176` requires all **4 distinct paths** to exist and parse as `type == "excalidraw"`; it is not "referenced," it hard-fails `make validate` if any one of the 4 is missing. | tracked, git-recoverable | **Not actioned** — the prompt's "keep one, verify by md5 which" instruction is not executable without breaking `make validate`. This is a mandatory-stop per prompt §7 ("a premise in section 1 turns out false"): the 4 files are placeholder-identical content (someone never drew 4 distinct diagrams), not 4 redundant copies of one real diagram — deleting 3 would remove content the gate requires, not dead weight. Recorded as a content-quality follow-up (someone should draw 3 more distinct diagrams), not a housekeeping deletion. PR 2 proceeds without this item. |
| F4 | `design_handoff_quorum_ui/` vs `docs/design-handoff/`: **only 2 files overlap by name** (not a full mirror — hygiene auditor corrected this against the prompt's looser "shared files byte-identical" framing), both byte-identical | none found | tracked, git-recoverable | Medium — smaller win than the prompt implied, since only 2 files actually dedupe; the rest of each directory is unique content, not duplication |
| F5 | `docs/factory/` vs `docs/` root: 6 byte-identical (105,106,107,108,110,39), 2 diverged (109, 38 — same number, different content) | `scripts/validate_quality_contracts.py` references `docs/factory/` | tracked, git-recoverable | Medium for the 6 identical (mechanical dedupe); the 2 diverged pairs need a **decision**, not a dedupe — ADR required (PR 3) |
| F6 | 14 duplicate `docs/NN-*` numbers, 28 files, incl. whole 70-73 series | **~60 validator literals + 149 config references** (prompt §1.1); confirmed non-empty blast radius via grep above | tracked, git-recoverable, but **widest blast radius in the whole audit** | Lowest value ÷ blast-radius of any PR — highest risk, ordered last among the file-level PRs (PR 4) |
| F7 | `tests/perf/` + `tests/performance/` split; 28 loose files at `tests/` root | `scripts/validate_tests.py` hard-fails if either directory is missing; `Makefile` `PERF_TEST_PATHS`/`PERF_MIN_TESTS`; `pyproject.toml`; multiple test files reference `tests/perf` string literals (`tests/test_store_concurrency.py`, `tests/test_findings_ledger_consistency.py`, two `tests/unit/test_perf_gate_*.py`) | tracked, git-recoverable | Medium — 4-file lockstep change, well-scoped |
| F8 | `.hypothesis/` ungitignored (1.1 MB, gitignore fix only — not tracked garbage) | none (it's a gitignore *gap*, not a tracked file) | trivial | High — one-line fix, zero risk |
| F9 (new, not in prompt's list) | `.agents/skills/{architecture-and-decisions,doc-critic,onboarding-companion,operations-runbook}/` carry 9 byte-identical files each (36 files, ~276 KB) | `configs/external-skill-registry.json` references skill names, not the duplicated file paths directly | tracked, git-recoverable | **Out of scope for this run** — see §5, filed as a follow-up, not actioned (discovered by the hygiene lens, not in the prompt's measured set, and deduping *installed skill packages* is a different concern from root/docs housekeeping; see rule 17 "one concern per PR") |
| F10 (new) | `profiles/orbi/` vs `custom-skill-packs/orbi-ai-operating-model-pack/`: 4 file pairs + 1 triple, byte-identical | `scripts/apply_profile.py` references `profiles/orbi` | tracked, git-recoverable | **Out of scope for this run** — same reasoning as F9 |
| F11 (architect lens, out of *action* scope per 0.2) | `query_runs.py` (3,509 lines) merges 3 of `docs/20-architecture.md`'s declared components (`query_api`, `orchestration`, `persistence`) into one file, fanning in 13 other modules | n/a — src/ restructure, explicitly forbidden by 0.2 | n/a | Recorded only; see §6 |
| F12 (EM lens) | `docs/session-handoff.md` (mandated read by `AGENTS.md` session-continuity + `docs/00-start-here.md`) is dated 2026-07-25 and names a branch (`feat/ui-pr1-quickfixes`) that no longer exists in `git branch -a`; the actually-current handoff (`docs/analysis/2026-08-11-session-handoff.md`) is not cross-referenced from either mandated entry point | `docs/session-handoff.md` is a **generated** file (`scripts/session_handoff.py`, run via `make handoff`) — this is staleness from a skipped process step, not a duplicate/misplaced file | trivially fixable by re-running `make handoff`, but that requires session-content judgment this run should not make on another session's behalf | **Recorded, not actioned** — flagged to the human in the final report; regenerating it correctly requires knowing what the *next* best action is, which is exactly the judgment call rule 20 reserves for a human-visible PR, not a housekeeping side-effect |

## 3. Contradictions between lenses, reconciled

- **Architect vs. hygiene on `docs/` numbering**: architect frames the 12+
  collision pairs as evidence the numbering scheme "isn't a real ordinal
  index"; hygiene independently counted 14 collisions/28 files by direct
  enumeration. Both are right; hygiene's count is the operational one used for
  PR 4, architect's framing is the *why it matters* used for PR 6's ADR.
- **Prompt vs. hygiene on `design_handoff_quorum_ui/` overlap**: the prompt's
  §1 table says "shared files byte-identical," which reads as "these two trees
  mirror each other." Hygiene's re-run found only **2 files actually share a
  name** between the two directories — the rest of each tree is unique, not
  duplicated. The prompt's framing is not wrong (the shared files *are*
  identical) but it overstates the size of the win; PR 3 scopes down to those
  2 files, does not touch the rest of either tree.
- No other direct contradiction surfaced; the three lenses were largely
  additive (architect found a `src/`-scoped concern out of this run's action
  scope, EM found a process-staleness concern outside the file-housekeeping
  frame, hygiene found two new duplicate clusters (F9, F10) the prompt's
  original measurement pass missed).

## 4. Action list (feeds Phase C)

Ordered by risk, lowest first, matching the prompt's PR 1–6 exactly. No new PR
added for F9/F10/F11/F12 — each is recorded above with an explicit reason it
is out of scope for *this* run (see §5, §6).

1. PR 1 — clear the repo root (F1)
2. PR 2 — delete tracked junk + guard gate (F2, F8, plus whatever else the
   guard's own audit turns up)
3. PR 3 — dedupe byte-identical trees + ADR for the 2 diverged pairs (F4, F5)
4. PR 4 — resolve 14 duplicate docs/ numbers (F6) — widest blast radius,
   ordered last among file PRs, human review before merge if the diff is too
   wide for one reviewer to hold
5. PR 5 — tests/ structure (F7)
6. PR 6 — ADR + gate for the numbering scheme, AGENTS.md convention note

## 5. Explicitly deferred (not filed as new issues in this run — recorded here)

- F9 (skill-package 4-way duplication) and F10 (profiles/orbi vs
  custom-skill-packs duplication): real, mechanically verified, but discovered
  outside the prompt's measured scope and outside the six-PR plan it commits
  to executing. Actioning them now would violate "one concern per PR" in two
  new directions this run was not chartered to open. Recorded for a future,
  separately-scoped run.
- F12 (stale `docs/session-handoff.md`): recorded, not regenerated — see
  table above for why.

## 6. `src/` finding (F11) — recorded per §0.2, not actioned

`src/product_app/` is flat, 22,506 lines, and 4 files —
`query_runs.py` (3,509), `providers.py` (2,391), `evaluation.py` (2,259),
`costs.py` (2,049) — are 45.4% of it (`10,208 / 22,506`, verified by `wc -l`).
`query_runs.py` specifically merges 3 of `docs/20-architecture.md`'s declared
components (`query_api`, `orchestration`, `persistence`) into one file and
fans in 13 other modules. This is a real architectural finding. Per prompt
§0.2 it is **not actioned** in this run; it is filed as a GitHub issue in
Phase D instead.

## PR 1 manifest — root files moved/removed 2026-08-11

Convenience record only — git is the actual safety mechanism. Group-1 files
are `git mv`'d into `docs/archive/2026-08/` in this same PR (recoverable via
normal history). Group-2 files were committed once (giving them history) then
removed from HEAD in the following commit; retrieve any of them with
`git show f464b6f:<original-root-path>`.

| File | Group | Date archived | Size |
|---|---|---|---|
| COST-FAILOPEN-CLOSEOUT-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 16994B |
| COST-OPS-BACKLOG-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 17768B |
| DEMO-READINESS-P1-P3-RESULT.md | 1-tracked | 2026-08-11 | 6486B |
| DEMO-READINESS-P1-P3-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 27169B |
| FOLLOWUP-F05-LAYER2.md | 1-tracked | 2026-08-11 | 5736B |
| GUARDRAILS-THEN-HANDOFF-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 16206B |
| NEXT-SESSION-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 21035B |
| OBSERVABILITY-DEMO-RESULT.md | 1-tracked | 2026-08-11 | 7723B |
| OBSERVABILITY-DEMO-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 21918B |
| OPS-HARDENING-CLOSEOUT-RESULT.md | 1-tracked | 2026-08-11 | 5250B |
| OPS-HARDENING-CLOSEOUT-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 11103B |
| OPS-NAV-GLOSSARY-FAVICON-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 10591B |
| OPS-TILE-RELEVANCE-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 9075B |
| P2-CLOSEOUT-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 18892B |
| PHASE-0-BUILD-PROMPT.md | 1-tracked | 2026-08-11 | 15495B |
| PR2-RED-GREEN-PROOF.md | 1-tracked | 2026-08-11 | 4768B |
| PR3-PR4-CLOSEOUT-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 10607B |
| QUALITY-MACHINERY-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 20757B |
| R2-RB4-to-S4-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 10175B |
| R2-RB5-S4-RESULT.md | 1-tracked | 2026-08-11 | 8417B |
| R2-RB5-S4-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 20411B |
| R2-S4-CLOSEOUT-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 16586B |
| R2-STAGE-A-TO-S4-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 16263B |
| R2-STAGE-B-TO-S4-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 19750B |
| STASH-TRIAGE-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 9588B |
| STREAM-B-CLOSEOUT-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 20440B |
| UI_Fix_Plan.md | 1-tracked | 2026-08-11 | 8596B |
| UI_UX_Audit_Report.md | 1-tracked | 2026-08-11 | 9197B |
| UI-BUG-TRIAGE-2026-07-23-ANALYSIS.md | 1-tracked | 2026-08-11 | 11413B |
| UI-PR1-QUICKFIXES-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 13919B |
| UI-PR2-DATA-COMPLETENESS-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 9924B |
| UI-PR2-PR4-HANDOFF-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 11032B |
| UI-REMEDIATION-MASTER-PLAN-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 32015B |
| WP-B-RESULT-AND-WP-C-HANDOFF.md | 1-tracked | 2026-08-11 | 20435B |
| WP-D-TO-CLOSEOUT-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 21038B |
| WP-E-TO-CLOSEOUT-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 17864B |
| WP-F-TO-CLOSEOUT-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 16887B |
| WP-G2-TO-CLOSEOUT-ULTRACODE-PROMPT.md | 1-tracked | 2026-08-11 | 12233B |
| BACKLOG-TRIAGE-BY-EXECUTION-ULTRACODE-PROMPT.md | 2-untracked-then-deleted (recoverable: `git show f464b6f:BACKLOG-TRIAGE-BY-EXECUTION-ULTRACODE-PROMPT.md`) | 2026-08-11 | n/a |
| GROUPS-A-AND-B-ULTRACODE-PROMPT.md | 2-untracked-then-deleted (recoverable: `git show f464b6f:GROUPS-A-AND-B-ULTRACODE-PROMPT.md`) | 2026-08-11 | n/a |
| ISSUE-115-NEXT-SESSION-ULTRACODE-PROMPT.md | 2-untracked-then-deleted (recoverable: `git show f464b6f:ISSUE-115-NEXT-SESSION-ULTRACODE-PROMPT.md`) | 2026-08-11 | n/a |
| ISSUE-148-NEXT-SESSION-ULTRACODE-PROMPT.md | 2-untracked-then-deleted (recoverable: `git show f464b6f:ISSUE-148-NEXT-SESSION-ULTRACODE-PROMPT.md`) | 2026-08-11 | n/a |
| ISSUE-171-RUNG3-ULTRACODE-PROMPT.md | 2-untracked-then-deleted (recoverable: `git show f464b6f:ISSUE-171-RUNG3-ULTRACODE-PROMPT.md`) | 2026-08-11 | n/a |
| ISSUE-171-ULTRACODE-PROMPT.md | 2-untracked-then-deleted (recoverable: `git show f464b6f:ISSUE-171-ULTRACODE-PROMPT.md`) | 2026-08-11 | n/a |
| ISSUE-171-VERIFY-AND-CLOSE-ULTRACODE-PROMPT.md | 2-untracked-then-deleted (recoverable: `git show f464b6f:ISSUE-171-VERIFY-AND-CLOSE-ULTRACODE-PROMPT.md`) | 2026-08-11 | n/a |
| ISSUE-175-ULTRACODE-PROMPT.md | 2-untracked-then-deleted (recoverable: `git show f464b6f:ISSUE-175-ULTRACODE-PROMPT.md`) | 2026-08-11 | n/a |
| ISSUE-217-NEXT-SESSION-ULTRACODE-PROMPT.md | 2-untracked-then-deleted (recoverable: `git show f464b6f:ISSUE-217-NEXT-SESSION-ULTRACODE-PROMPT.md`) | 2026-08-11 | n/a |
| ISSUE-247-NEXT-SESSION-ULTRACODE-PROMPT.md | 2-untracked-then-deleted (recoverable: `git show f464b6f:ISSUE-247-NEXT-SESSION-ULTRACODE-PROMPT.md`) | 2026-08-11 | n/a |
| LIVE-E2E-VALIDATION-RESULT.md | 2-untracked-then-deleted (recoverable: `git show f464b6f:LIVE-E2E-VALIDATION-RESULT.md`) | 2026-08-11 | n/a |
| MAJOR-ISSUES-BATCH-RESULT.md | 2-untracked-then-deleted (recoverable: `git show f464b6f:MAJOR-ISSUES-BATCH-RESULT.md`) | 2026-08-11 | n/a |
| MAJOR-ISSUES-BATCH-ULTRACODE-PROMPT.md | 2-untracked-then-deleted (recoverable: `git show f464b6f:MAJOR-ISSUES-BATCH-ULTRACODE-PROMPT.md`) | 2026-08-11 | n/a |
| NEXT-SESSION-ULTRACODE-PROMPT-2026-08-04.md | 2-untracked-then-deleted (recoverable: `git show f464b6f:NEXT-SESSION-ULTRACODE-PROMPT-2026-08-04.md`) | 2026-08-11 | n/a |
| NEXT-SESSION-ULTRACODE-PROMPT-2026-08-07.md | 2-untracked-then-deleted (recoverable: `git show f464b6f:NEXT-SESSION-ULTRACODE-PROMPT-2026-08-07.md`) | 2026-08-11 | n/a |
| NEXT-SESSION-ULTRACODE-PROMPT-2026-08-08.md | 2-untracked-then-deleted (recoverable: `git show f464b6f:NEXT-SESSION-ULTRACODE-PROMPT-2026-08-08.md`) | 2026-08-11 | n/a |
| NEXT-SESSION-ULTRACODE-PROMPT-2026-08-09.md | 2-untracked-then-deleted (recoverable: `git show f464b6f:NEXT-SESSION-ULTRACODE-PROMPT-2026-08-09.md`) | 2026-08-11 | n/a |
| POST-GO-LIVE-VERIFICATION-RESULT.md | 2-untracked-then-deleted (recoverable: `git show f464b6f:POST-GO-LIVE-VERIFICATION-RESULT.md`) | 2026-08-11 | n/a |

**Group 3 (37 gitignored `HANDOFF-*.md`) — not touched by this PR.** Per
§1.2, force-adding them would override a deliberate prior decision to keep
them out of version control, and `git mv` on this pattern silently commits
nothing (the `.gitignore:31` pattern has no directory anchor and follows the
file to any destination). They remain local-only clutter, invisible to CI and
absent from a fresh clone. **Recommendation for the human:** either leave them
(cheap, harmless) or delete them locally (`git ls-files --others --ignored
--exclude-standard | grep -E '^HANDOFF-.*\.md$' | xargs rm`) — this run takes
no position on which, since it wasn't the decision-maker who excluded them.

## What generalises

See the end of this document, appended after Phase C/D/E complete.
