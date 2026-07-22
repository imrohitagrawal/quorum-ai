# Quality Metric Ledger

**Purpose.** Make the methodology thesis *falsifiable* (plan Part E) and the
product thesis *measurable* (review-findings ledger row **OC-4**). The claim
"robust upfront planning + per-surface tests + review-to-fixpoint reduces escaped
defects and rework" and the claim "cross-validating four models reduces
hallucination" are both worthless until they are numbers in a tracked file. A
downward escaped-defect + rework trend across S1→S2→S3→S4, and a measured
hallucination/faithfulness trend, are the *evidence*; a flat or rising trend
refutes the claim. **No metric ⇒ no claim.**

**Honesty rule (binding).** Every cell that has not been measured is `—` (em
dash). A number appears here only if it was derived from a committed artifact
(commit, diff, tool output) that a reader can re-derive. Never estimate, never
back-fill a plausible value, never carry a target forward as if it were a
measurement.

---

## Part 1 — Process metrics (plan Part E)

These are measurable **today** from git history and tool output.

| Slice | Scope | Review findings per slice | Mutation score | Escaped defects | Rework commits |
|---|---|---|---|---|---|
| **S1** | FR-014 run-history persistence (`run_history_store.py`, `query_runs.py`) | **15** (see derivation) | **88.7%** (changed-function scope; measured range 87.2-88.7%) | **10** escaped the feat commit `d7469ce`; **1** further escaped the fix commit `8c09a26` | **2 of 4** branch commits (50%) |
| **S2** | Eval engine (FR-015, NFR-011/012) + OC gate | **9** (32 raised by a 5-lens fan, 23 refuted by independent verifiers; +10 more across 2 further rounds) | — (not re-measured for S2 scope) | **0 escaped a merged commit** (the branch is unpushed; all 9 were caught pre-merge) | **1 of 7** branch commits (14%) |
| S3 | Trust UI (FR-016) | — | — | — | — |
| S4 | Eval harness + golden set (FR-017) | — (pending the S4 review fan's landed findings) | — (not re-measured for S4 scope) | **0 escaped a merged commit** (caught pre-merge on the S4 branch) | — (pending the S4 branch commit count at merge) |

### Column definitions

- **Review findings per slice** — distinct findings raised by any review fan
  (pre-merge or post-merge) against that slice's diff, whether or not they were
  blocking. Should trend **down** as planning improves.
- **Mutation score** — `mutmut` score on the slice's changed **functions** —
  every function whose body overlaps a changed line, not the whole module
  (`make mutation-baseline`, advisory in CI). Should trend **up**.
- **Escaped defects** — findings a *later* phase raises about an *already
  merged* commit of that slice. Target → **0**. Counted against the commit they
  escaped, so a defect introduced by a fix commit is tracked separately from one
  that escaped the feature commit.
- **Rework commits** — commits on the slice's branch that fix or complete work a
  prior commit declared done, as a fraction of the slice's total commits.

### S1 derivation (how each number was counted)

Re-derivable with `git log --oneline 5f7b1a6..HEAD` and `git show <sha>`.

**Review findings = 15**, from three review passes:

| Pass | Artifact | Findings | Enumeration |
|---|---|---|---|
| Pre-merge review of the S1 diff | `d7469ce` commit body: *"adversarially reviewed … two findings fixed test-first"* | 2 | Count taken from the commit message; the individual findings were **not** recorded below the line, so only the count is verifiable. This is itself a methodology gap — see "Known fidelity limits". |
| Post-merge 5-lens executing fan | `8c09a26` (*"address S1 multi-angle PR review (5 executing reviewers)"*) + its diff | 12 | 2 code-behaviour, 3 test-coverage, 2 doc/comment-accuracy, 3 traceability, 2 accepted-debt (DEBT-006, DEBT-007 in `docs/63`). 0 blocking defects: the honesty gate, PII minimisation, API contract, auth boundary and concurrency all held under attack. |
| Re-review to fixpoint | `5ccd6f9` (*"3 executing agents … no new defects"*) | 1 | The one remaining uncovered branch (`_to_utc_iso` naive→assume-UTC). |

**Escaped defects = 10 (from `d7469ce`) + 1 (from `8c09a26`).** These are the
12 post-merge findings minus the 2 accepted-debt entries (debt is a recorded
trade-off, not a defect), enumerated from the actual diffs:

| # | Escaped from | Defect | Evidence |
|---|---|---|---|
| E-1 | `d7469ce` | Timestamps written with `.isoformat()` without UTC normalisation — ISO-TEXT lexical ordering is only correct while every value shares one offset | `run_history_store.py` `_to_utc_iso` added in `8c09a26` |
| E-2 | `d7469ce` | The `iter_runs(since=…)` filter had the same non-UTC comparison bug | same diff, `params.append(_to_utc_iso(since))` |
| E-3 | `d7469ce` | `ORDER BY completed_at DESC` had no tie-breaker → non-deterministic order for equal timestamps (paginated views) | `ORDER BY completed_at DESC, query_run_id DESC` |
| E-4 | `d7469ce` | `is_terminal` guard in `_persist_terminal_run` untested — **a mutant survived** | `test_non_terminal_run_is_not_persisted` added |
| E-5 | `d7469ce` | `iter_runs(limit=…)` untested | `test_iter_runs_limit_truncates` |
| E-6 | `d7469ce` | `from_env` on-disk `mkdir` path untested | `test_from_env_creates_parent_dir_for_on_disk_path` |
| E-7 | `d7469ce` | Docstring claimed `INSERT OR REPLACE`; the code is `ON CONFLICT DO UPDATE` (the eval-preservation safety property) — doc described behaviour the code does not have | `query_runs.py` docstring rewrite |
| E-8 | `d7469ce` | Idempotency test misleadingly named after the wrong SQL construct | `test_record_is_idempotent_insert_or_replace` → `…_upsert` |
| E-9 | `d7469ce` | NFR-011 / NFR-012 referenced but never defined | `docs/11` +26 lines |
| E-10 | `d7469ce` | FR-014 + NFR-011/012 missing from the requirement registry **and** the traceability matrix — green gates, real gap | `docs/17` +3, `docs/18` +3 |
| E-11 | `8c09a26` | The fix's own naive-datetime branch was uncovered | `5ccd6f9` (+16 test lines, module to 100% line coverage) |

**Mutation score = 88.7%** (measured range **87.2-88.7%** over five runs), from
`make mutation-baseline` on this branch (`docs/metrics/mutation-baseline.md`
§3): mutmut **3.6.0**, changed-function scope — 21 functions across
`query_runs.py`, `run_history_store.py` and `feedback_store.py`, 504 mutants →
**336 killed / 43 survived**, score = 336 / (336 + 43). The 123 timeouts are
excluded from the score as a measured `fork()`/`RLIMIT_CPU` harness artifact
(§5 of that file), not as kills. Re-derive with
`make mutation-baseline DIFF_BASE=origin/main`; scope in
`build/mutation/scope.txt`, score in `build/mutation/score.txt`. Advisory floor
`MUTATION_MIN_SCORE = 80`, so this row **passes**.

**This supersedes the 96.5% first recorded here.** That figure was measured on a
425-mutant scope taken *before* the RB-3 leak fix landed in the same worktree;
the fix added `close`/`__del__`/`_close_open_stores` and rewrote
`FeedbackStore.iter_events`, pulling 79 more mutants into the changed-function
scope, 32 of them unkilled. The tests did not get worse — a fix shipped without
behavioural tests strong enough to pin it, and the changed-function gate noticed
(mutation-baseline.md §3.1). The stable signal is the **43 survivors**
(byte-identical mutant names in all five runs), of which **19 are genuine,
killable coverage gaps** and 24 are equivalent/logging-only mutants (§3.2).
See also §1 of that file: the mutant that actually escaped the S1 suite is one
mutmut never generates, so the number is a floor, not a proof of test strength.

**Rework commits = 2 of 4.** Branch commits after `5f7b1a6`:
`d7469ce` (new work), `0cc2948` (docs — the S2→S4 continuation prompt, new
work), `8c09a26` (**rework**), `5ccd6f9` (**rework**). 2 rework / 4 total = 50%;
of the slice's *code* commits (`d7469ce`, `8c09a26`, `5ccd6f9`), 2 of 3 are
rework.

### Known fidelity limits for the S1 row

- The 2 pre-merge findings exist only as a count in a commit message; they were
  never written below the line. From S2 onward, **every review fan must land its
  findings in a tracked file** (as `docs/analysis/R2-plan-review-findings.md`
  does for the plan review) before the fix commit — otherwise the finding count
  is unauditable. This is exactly finding **EN-5**.
- Severity was not recorded per finding for S1, so no severity split is given.
- S1 predates the Phase-0 gates, so its numbers are a **baseline under the old
  rules**, not a demonstration of the methodology.

---

## Part 2 — Output-quality metrics (ledger row OC-4)

**These columns are SCHEMA-ONLY until S2/S4.** They exist now so the shape is
fixed before the numbers arrive, and so the absence of a number is visible
instead of silent. Process metrics (Part 1) measure *how we work*; these measure
*whether the product's thesis is true* — cross-validating four models reduces
hallucination. Without them the thesis is an assertion.

| Slice | Hallucination rate | Faithfulness | False-consensus preservation | Citation **support** rate | Trust-vs-correctness calibration error |
|---|---|---|---|---|---|
| S1 | — | — | — | — | — |
| S2 | — (pending S4) | — (pending S4) | — (pending S4) | — (pending S4) | — (pending S4) |
| S3 | — | — | — | — | — |
| S4 | — | — | — | — | — |

### Why S2 did NOT fill these cells (OC-4)

The S2 brief asked for real numbers here. **They are not eligible, and putting
them in would break this file's binding honesty rule** — so the cells stay em
dashes and the reason is recorded instead.

S2 built the *mechanism* (the engine, `citation_marker_grounding`, the
suppression rule) and a frozen corpus, but that corpus is **five hand-authored
real-SHAPED fixtures** whose labels encode what the engine's structural verdict
must be — not an expert judgement about the subject matter
(`tests/evals/corpus/README.md` states this in its own provenance header).
The reporting rules above require the label source; "hand-authored by the agent
that wrote the engine" is not a measurement of product quality, it is a
regression oracle for the engine's own logic. A faithfulness figure derived
from it would be the engine grading itself.

What S2 *can* honestly report is engine-vs-label agreement on that oracle,
which is a **process** number and belongs nowhere near Part 2:

| S2 engine-vs-label agreement (regression oracle, NOT product quality) | Value |
|---|---|
| Frozen corpus cases | 5 (hand-authored, real-shaped) |
| Engine structural verdicts matching hand-authored labels | 5 / 5 |
| Adversarial pair separation on `citation_marker_grounding` | 0.850 (faithful) vs 0.059 (fluent-but-unfaithful) — re-measured 2026-07-20 after DEBT-011; it was 1.000 vs 0.038 before |
| Judge configuration | OFF (`StubEvalJudge` sets `verifies_support=False`) |
| Served trust in every one of these runs | `unverified`, score `None` |

Five cases pin direction, not accuracy. The Part 2 cells need the S4 golden set
with real captured runs and human labels — and, for the high-stakes rows, a
qualified human reviewer (see the S2 handback's operator-flagged items).

**Also material to any future number here:** the interaction between refusal
detection and the fabrication verdict is now RESOLVED (**DEBT-011**, closed
2026-07-20 — the four cases are ordinary passing tests in
`tests/evals/test_refusal_fabrication_residual.py` and the invariants live in
`tests/unit/test_evaluation_refusal_decoupling.py`). Two things still stand
between this engine and a number that means what the column says: the labels
remain ADVISORY and uncalibrated until the S4 golden set (FS-6), and
**DEBT-012** — Layer A performs no I/O, so a run whose only citation markers
are fabricated URLs is reported as *unknown* rather than as fabrication.

### Column definitions and what will populate them

| Column | Definition | Populated by | Available from |
|---|---|---|---|
| **Hallucination rate** | Fraction of graded answers containing ≥1 claim unsupported by any retrieved source, on the human-labeled frozen corpus of real 4-model runs. | S2 eval engine (FR-015) run over the S4 golden set; blocking hermetic gate per **OC-1**. | **S4** (S2 gives the engine, S4 the labeled corpus) |
| **Faithfulness** | Fraction of material claims entailed by the cited source text (DeepEval/RAGAS faithfulness), judged against human labels — not against the stub pipeline (**OC-3**: self-referential bands cannot fail on a wrong answer). | S2 eval engine + S4 human-labeled `expected` bands. | **S4** |
| **False-consensus preservation** | Of cases where the four models agree on a *wrong* answer, the fraction the pipeline still surfaces as low-trust / disputed rather than confidently endorsing. This is the sharpest test of the product thesis: cross-validation is only valuable if correlated error is not laundered into confidence. | S4 golden-set subset built specifically of known false-consensus cases. | **S4** |
| **Citation SUPPORT rate** | Fraction of citations that actually **support** the claim they are attached to. Deliberately *not* a citation **count** — the whole point of **OC-2** is that today's TrustScore is a count composite (`estimate_material_claim_count = ceil(len/200)`) that never checks support, so a fluent answer with fabricated citations can score high. | S2 judge (support verdict per citation), graded against S4 labels. | **S2** (mechanism) / **S4** (measured rate) |
| **Trust-vs-correctness calibration error** | Mean absolute (or ECE-style) gap between the displayed TrustScore and the labeled correctness of the same answer. A fluent-but-unfaithful case with fake citations must score **low** trust; if the count-only score cannot distinguish it, Layer-B goes on or the numeric trust is suppressed for judge-OFF runs. | S2 trust-vs-truth calibration test (**OC-2**), then measured over the S4 golden set. | **S2** (pass/fail test) / **S4** (error number) |

**Reporting rules for these columns.** State the corpus (which frozen run set),
its size, the label source (human vs stub), and the judge configuration
(model/local Ollama vs Haiku, judge ON/OFF) alongside any number — a
faithfulness figure without its corpus and judge is not a measurement. Numbers
produced with `StubEvalJudge` are **not** eligible for this table (that is
finding OC-1); they may be recorded as stub-pipeline sanity data elsewhere, but
never in a cell that reads as product quality.

---

## How to update this ledger

Contract for the next slice. Do this **as part of the slice**, not afterwards —
a slice is not done until its row is filled.

1. **Land review findings below the line first.** Before the fix commit, write
   every finding into a tracked file with an ID and severity. The ledger's
   findings count must be re-derivable by counting those rows, not by trusting a
   commit message (the S1 gap).
2. **Add one row per slice to Part 1** and, once the eval engine exists, one to
   Part 2. Never edit a prior slice's row except to correct a demonstrable
   miscount — and then say so inline.
3. **Fill each cell from an artifact, and cite it** (commit SHA, tool command,
   or file path) in the derivation section below the table. If it cannot be
   re-derived by a reader, it does not go in.
4. **Unmeasured ⇒ `—`.** If a metric is pending on another workstream, write
   `— (pending <what>)` so the blocker is visible. Do not leave a cell blank and
   do not substitute the target value.
5. **Mutation score:** run `make mutation-baseline` (advisory, non-blocking) and
   record the score for the slice's changed **functions** (the scope the gate
   actually mutates), with the mutmut version and the functions mutated.
6. **Escaped defects:** count against the commit they escaped, and enumerate them
   — a bare count with no enumeration is not auditable.
7. **Read the trend, and say what it means.** After S2, state explicitly whether
   escaped defects and rework are trending down. If they are not, the
   methodology claim is refuted for that period and the plan text must be
   corrected — the ledger outranks the narrative.

### Open cells tracked elsewhere

| Cell | Blocker | Owner |
|---|---|---|
| All of Part 2 | Requires the S2 eval engine and the S4 human-labeled golden set. | S2 / S4 |

**Related:** plan Part E (`docs/R2-comprehensive-plan.md`), findings ledger
`docs/analysis/R2-plan-review-findings.md` (OC-1..OC-5, EN-5, RB-7),
`docs/63-technical-debt-register.md` (DEBT-006, DEBT-007).
