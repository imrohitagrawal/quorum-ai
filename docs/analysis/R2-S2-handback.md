# R2-S2 handback — evaluation engine + output-correctness gate

**Branch:** `feat/r2-s2-evaluation-engine` · **HEAD:** `01e69f2` · **Base:** `main` @ `46adcc4` (#51)
**Pushed:** NO. **Merged:** NO. **Deployed:** NO. No paid path activated, no secret rotated.
**Date:** 2026-07-20.

> **SUPERSEDED IN PART — 2026-07-20 (R2-S2.1, HEAD `fa1c824`).** Everything
> below describes the tree as of `01e69f2`. **DEBT-011 has since been FIXED**
> and the four `xfail(strict=True)` acceptance tests it refers to are now
> ordinary PASSING tests, so every statement below of the form "4 xfailed are
> deliberate" / "the residual is unresolved" is HISTORY, not the current tree.
> Current: 1015 passed / 4 skipped / **0 xfailed**, cov 89.51%. See
> `docs/63-technical-debt-register.md` (DEBT-011 resolved, **DEBT-012** opened)
> and `tests/unit/test_evaluation_refusal_decoupling.py`. What is NOT
> superseded: S2 acceptance itself — the full adversarial re-review to a
> fixpoint was not run in S2.1, so S2 remains **BUILT, NOT ACCEPTED**.

This file is the durable handback. Chat evaporates and
`docs/session-handoff.md` is regenerated wholesale by
`scripts/session_handoff.py`, so neither can hold it. The authoritative phase
status lives in `docs/analysis/R2-plan-review-findings.md` (**PHASE STATUS**),
which points here.

---

## Status in one line

**S2 is BUILT and PROVEN, but NOT ACCEPTED.** Every gate is green and the
headline output-correctness work is done — but a bounded three-round
adversarial review reached its FS-7 bound **without a fixpoint**, and the
residual (**DEBT-011**) is blocking for S3. Do not read the green suite as
"S2 done".

## Gates (re-run them; do not trust this table)

| Gate | Result |
|---|---|
| `make validate` | PASS — all 10 factory gates |
| `make fr-completeness` | PASS — 27 requirements in docs/17 AND docs/18 |
| `make api-contract` | PASS — 29 Schemathesis tests (floor 18) |
| `make perf-gate` | PASS — 10/10 consecutive runs (see the flake note below) |
| `make diff-cover DIFF_BASE=origin/main` | **99%** (floor 95), 1 line missing |
| `uv run pytest tests/ -q` | **989 passed / 4 skipped / 4 xfailed**, coverage **89.49%** (floor 88) |
| `ruff check` · `ruff format --check` · `mypy src` | clean |

The **4 xfailed are deliberate** — they are the DEBT-011 residual, pinned
`strict=True` (see below). They are not flakes and must not be deleted.

## Commits (8, unpushed)

| SHA | Unit |
|---|---|
| `b00c149` | docs: FR-015 + AC-041..043 + the FS-9 docs-before-code set |
| `b4884d9` | test: EN-7 doc-vs-CI consistency gate |
| `1c02ea7` | fix: DEBT-010 skill-router `PLACEHOLDER_RE` |
| `01c2de6` | test: DEBT-008 mutation oracle for the RB-3 store lifecycle |
| `a4cb01d` | feat: the output-correctness gate + the FR-015 evaluation engine |
| `9bb32fd` | feat: persist + serve the evaluation, behind the account boundary |
| `a891b39` | fix: the confirmed adversarial findings + the recorded residual |
| `01e69f2` | docs: ledger reconciliation |

---

## What is DONE and proven

**OC-2 (the headline) — DONE.** The product's trust figure was a citation
*count* composite that can never tell whether a citation *supports* its claim.
`tests/evals/test_trust_calibration.py` holds an adversarial pair — a faithful
answer and a fluent, confident one sprinkled with fabricated citations — that
are identical on every measurable the product had, and a **standing test proves
the count-only proxy cannot separate them**. That test must stay green forever;
it is the reason the rest exists.

Both resolutions shipped:

1. **`citation_marker_grounding`** — a deterministic Layer-A signal measuring
   the share of inline citation markers that resolve to a real, non-fallback
   source. Separates the pair **1.000 vs 0.038**. Distinguishes *no markers*
   (`None` = unknown, excluded from the composite with weights renormalised)
   from *markers resolving to nothing* (≈0, the fabrication signature).
2. **Structural suppression** — while `TrustScore.support_verified` is False,
   `score` **IS** `None` and `band` **IS** `"unverified"`. There is no key on
   the served model a client can read as a confidence number.
   `StubEvalJudge.verifies_support = False` (a stub verifies nothing), so
   judge-OFF and stub-ON are byte-identical (NFR-012) and **every** hermetic run
   serves `unverified`.

**OC-1 — PARTIAL, deliberately not DONE.** Harness + blocking gate exist and
bite. The corpus is **five hand-authored real-SHAPED fixtures, not captured
four-model runs** — its README says so in a provenance header. Real runs and
human labels are an operator task (below); none were faked.

**OC-4 — em dashes kept, as a recorded decision.** A faithfulness number from a
corpus hand-authored by the same slice would be the engine grading itself, which
`docs/metrics/quality-ledger.md`'s own honesty rule forbids. The honest numbers
(5/5 engine-vs-label agreement, the 1.000/0.038 separation) are recorded there
as a clearly-separated **process** number.

**Engine.** Layer-A weights are ADVISORY (FS-6) and honest about which parts are
measured: `agreement_ratio` is **excluded** because it measured non-monotone on
the corpus (simulated run 3/4, genuinely divided panel 0/4); high-stakes signals
excluded because one case cannot calibrate a safety penalty. Layer-B is
key-gated on `QUORUM_EVAL_JUDGE_API_KEY` mirroring `_tavily_enabled`, OFF by
default, reuses `providers.call_with_prompt`; provider prose is treated as
attacker-controlled (delimited, delimiters neutralised); malformed ⇒ no verdict.
Recorded honestly: `call_with_prompt` exposes no temperature parameter, so
"temperature 0" is *requested in prompt text, not enforced*.

**Boundary + hermeticity.** AC-043 pinned by
`tests/unit/test_evaluation_auth_boundary.py` (401 unauthenticated, 404
cross-account, asserted on the response **body**, against a run that actually
has an evaluation). Judge-OFF makes **zero** seam calls (spy).
`to_eval_json` drops the judge rationale at the persistence boundary (PII).

**Housekeeping.** EN-7 DONE (four-valued effective status over *all* workflows;
found and fixed two genuine pre-existing drifts; RED-proven three ways plus an
anti-vacuity guard). DEBT-008 DONE (deselect-by-path → by-marker; the RB-3 scope
goes 27 killed / 2 no-tests → **40 killed / 0 no-tests**). DEBT-010 DONE
(416-file sweep, both directions proven).

---

## >>> READ THIS BEFORE TOUCHING THE ENGINE: DEBT-011 <<<

`detect_refusal` was rewritten twice and **each attempt moved the defect rather
than removing it**:

| Round | Approach | New mislabelling it created |
|---|---|---|
| 1 | whole-text substring | a hedge ⇒ refusal ⇒ fabricating run laundered |
| 2 | + "markers ⇒ not a refusal" | genuine safety refusal ⇒ `unfaithful`/`high` |
| 3 | first-sentence anchor | apology-first refusal missed ⇒ `unfaithful`/`high`; one-sentence safety disclaimer still launders a wholly-fabricating run ⇒ `partial`/`low` |

Every laundering finding is *"refusal short-circuits fabrication"*; every
false-accusation finding is *"refusal missed, so grounding 0.0"*. **The fault is
structural — a refusal branch is being allowed to decide a fabrication
question.** My read (deliberately not acted on unreviewed): refusal should stop
being a classifier branch entirely — report it as a signal and never let it
override the grounding verdict — and synthesis prose needs an honest ceiling
(or `None`) rather than the pooled one.

All four reproduced shapes are pinned in
`tests/evals/test_refusal_fabrication_residual.py` as **`xfail(strict=True)`**,
so a later fix turns them XPASS and **reds the suite**, forcing this record to be
updated. A passing control proves R-1 is laundering, not general weakness.

- **R-1 / R-3 (HIGH, laundering):** a run whose slots open with a safety
  disclaimer or an ordinary hedge and then fabricate citations is served at the
  **lowest** hallucination risk — in exactly the high-stakes medical/legal/
  financial domains this product targets.
- **R-2 (HIGH, false accusation):** an apology-first genuine refusal linking a
  crisis resource is served `unfaithful`/`high`. **Measured gotcha:** widening
  the anchor alone will NOT fix R-2 — its decline uses the two-word "can not"
  spelling, absent from `_REFUSAL_PHRASES`.
- **R-4 (MED):** synthesis prose still resolves ordinals against the **pooled**
  run bibliography, so invented high ordinals there can score full grounding.

**Why it was tolerable to land:** numeric trust is suppressed in every run
(`support_verified` is False without a real judge) and **no UI reads these
labels** — verified, `app.js` has zero references. That bounds the blast radius;
it does **not** make the labels correct. The API *does* serve them and they *are*
persisted. **Blocking for S3 (FR-016)**, which is what would first put them in
front of a user.

Six docstring claims contradicted by measurement were corrected in the same
commit, including one asserting the failure was "in the SAFE direction" — it is
not, and both directions are now named.

---

## Operator-gated / deferred

1. **DEBT-011** — decide the refusal/fabrication design before S3 surfaces any
   label. A build prompt appears to exist at `S2.1-DEBT-011-BUILD-PROMPT.md`
   (untracked; not written by the S2 session).
2. **OC-1 real labels** — captured four-model runs + **human** labels, especially
   medical/legal/financial, need a qualified reviewer. No paid run was made and
   no captured run was fabricated.
3. **DEBT-009** — still advisory; no ubuntu CI perf numbers exist yet, so step (1)
   of its repayment plan is genuinely unstarted.
4. **OC-3 (S4), OC-5 (S3)** — untouched, correctly still `BUILD`.
5. **study/publish** — phase-EXIT follow-up, not a blocker on this slice.

## Known wrinkles for the next session

- **perf-gate flake:** it failed **once** under load in a chained run, then
  passed **10/10** standalone. I could not reproduce it and did not capture the
  assertion. Reported because it corroborates DEBT-009 (macOS-derived budgets are
  load-sensitive, which is why that CI job is advisory).
- **`query_runs.py:1478`** is the one uncovered line on the slice diff — the
  non-terminal early `return` in `_persist_run_evaluation`. A reviewer argued it
  is currently unreachable; it is retained as a guard.
- **Untracked, not mine, left alone:** `MORNING-REPORT.md`,
  `S2-BUILD-PROMPT.md`, `S2.1-DEBT-011-BUILD-PROMPT.md`,
  `design_handoff_quorum_ui/`.
- The 4 xfails are load-bearing records. Deleting them to get a "clean" suite
  would destroy the residual.

## Review record (EN-5: findings live below the line, not in a commit message)

Round 1: five lenses, **32 raised → 23 refuted** by independent verifiers → **9
confirmed** by reproduction. Round 2 fixed those and **introduced regressions**.
Round 3 fixed the regressions and surfaced **10 more**. Bound reached; stopped
per FS-7 rather than grinding a fourth un-reviewed redesign.

The two most valuable catches — both invisible to a green suite — were the
headline signal under-firing **4×** on the exact corpus case built to catch it
(ordinals resolved against a duplicate-inflated source pool), and a **fabricated
calibration number** in a docstring (claimed corpus separation 0.04; measured
0.154). Both are now re-measured and **executable**: tests re-derive the
separation from the corpus and sweep cuts inside and below the interval, so the
comment cannot rot again.
