# Measured-accuracy PILOT — engine vs operator labels (n = 7)

**Scope, stated on its face:** `n = 7`, human-labeled, on hand-authored golden
fixtures. This is a **pilot — not a population estimate, do not extrapolate**.
It is NOT the quality-ledger Part 2 measurement — Part 2
(`docs/metrics/quality-ledger.md`) requires real captured four-model runs with
human labels and **stays em-dash** until those exist. The pilot's value is
narrower and honest: on 7 cases a qualified human actually judged, the
engine's mechanically-derived faithfulness verdict agrees with the human
subject-matter judgment.

**Label provenance.** The 7 `correctness` labels were authored by the
**operator (Rohit Agrawal, 2026-07-22)** against named authoritative sources
(OWASP/MDN, NIST SP 800-63B, PostgreSQL docs, Node.js release schedule, ISTQB,
Node.js diagnostics docs) and transcribed verbatim into
`tests/evals/pilot/operator_labels.json` — full text, sources, and reviewer
per label. The harness authored **zero** labels and may never alter one; a
disagreement is reported, not "fixed".

## The agreement mapping — declared BEFORE computing

Engine verdict = `evaluate_layer_a(...).faithfulness_label`, re-derived
through the **real Layer-A engine** on every run of the harness (never read
from a fixture or hard-coded). Operator `correctness` uses the operator
queue's enum, which is defined in the engine's own three-value vocabulary:

| Engine `faithfulness_label` | Operator `correctness` | Agreement |
|---|---|---|
| `faithful` | `faithful` | identity |
| `unfaithful` | `unfaithful` | identity |
| `partial` | `partial` | identity |

Agreement is the **identity comparison** on the shared enum — mechanically,
there is **zero post-hoc tuning freedom**: no re-bucketing step exists in
`tests/evals/pilot/loader.py` that could be adjusted after seeing a result,
and `test_agreement_is_derived_by_running_the_real_engine` pins the
comparison to exactly `engine_verdict == operator_correctness`.

## Result — computed by the harness, pinned by a test

Computed by `tests/evals/pilot/loader.py::compute_pilot()` through the real
engine; `tests/evals/test_accuracy_pilot.py::test_the_pilot_doc_records_exactly_the_computed_verdicts`
asserts this table equals the fresh computation, so this page cannot drift
from the measurement.

| Case | Engine verdict (derived) | Operator label (human) | Agree |
|---|---|---|---|
| `fabricated-citation-launder` | unfaithful | unfaithful | yes |
| `grounded-consensus` | faithful | faithful | yes |
| `human-as-of-date-fact` | partial | partial | yes |
| `partial-grounding-medium` | faithful | faithful | yes |
| `partial-live-two-failed` | partial | partial | yes |
| `preserved-false-consensus` | faithful | faithful | yes |
| `wholly-refused` | partial | partial | yes |

Agreement: **7 / 7** on n = 7 (pilot — not a population estimate, do not
extrapolate).

Reading the rows: the sharpest case is `fabricated-citation-launder` — a
fluent, confidently-cited answer laundering invented statistics that the
human graded `unfaithful` against NIST SP 800-63B and the engine lands as
`unfaithful`/high-risk. The three `partial` agreements include the
policy-correct refusal (capped at partial by the refusal rule — a good
outcome, not a defect) and two degraded runs where trust is limited by
incompleteness, not error.

**Not a blind inter-rater study.** The operator labeled these cases with the
engine's verdicts already visible (the golden gate asserts them in CI), and
each label was graded against the named external source, not against the
engine. So 7/7 measures "the human, checking authoritative sources, found no
case where the engine's verdict was wrong" — it is NOT a blind two-rater
agreement statistic, and no kappa-style inference applies.

**What this does and does not license.** It licenses: "on 7 human-labeled
golden cases, the engine's faithfulness verdict matched the human judgment
7/7." It does not license any statement about hallucination rate,
faithfulness, or accuracy of the product in general — those are Part 2
numbers and remain unmeasured (em-dash). The fixtures are hand-authored
real-shaped runs, not captured production runs, and n = 7 has no statistical
power over a population.

## Guard rails (mechanised in `tests/evals/test_accuracy_pilot.py`)

- **Rejects** an empty label set — an unlabeled pilot must never silently
  report 100%.
- **Rejects** a `correctness` outside {faithful, unfaithful, partial}, a
  `case_id` with no golden case, a duplicate `case_id`, and a label missing
  its provenance (source/reviewer/note).
- **Re-derives** every engine verdict through `evaluate_layer_a`; a
  monkeypatched-engine test proves the harness actually calls the engine.
- **Pins** quality-ledger Part 2 to em-dash: a test fails if any Part 2 slice
  cell carries a measured-looking value.

---

## Process-metrics panel — **PROCESS (not accuracy)**

> **Badge: PROCESS.** Everything below measures *how the system is built and
> tested*, not whether its answers are correct. None of it may be cited as an
> accuracy, quality, or hallucination number.

| Process metric | Value | Source |
|---|---|---|
| Golden-set coverage | 10 hand-authored cases spanning all 3 faithfulness labels, all 3 risk bands, refusal, false-consensus, high-stakes (asserted by the gate) | `tests/evals/test_golden_set_gate.py::test_the_golden_set_is_not_empty_and_covers_the_signal_space` |
| Structural-gate posture | Blocking hermetic gate: engine structural verdicts vs declared signals on every golden case; judge-OFF honesty (band `unverified`, score `None`) asserted per case | `tests/evals/test_golden_set_gate.py` (runs in CI via `uv run pytest`) |
| E2E flake rate | **0 / 960** spec executions | Flake scan, GitHub Actions run `29911231157` (recorded in PR #69) |
| Operator-label queue | 4 deferred subject-matter labels (clinical, tax-financial, as-of-date, self-harm-safety); `human-as-of-date-fact` is now labeled in this pilot's artifact — the remaining 3 stay open, optional, safety-case-first | `docs/metrics/operator-label-queue.md` |

The flake number is evidence the *test process* is stable — it says nothing
about answer quality. The golden-set coverage says the *oracle* is broad — it
says nothing about how often real answers are faithful.

---

**Related:** `tests/evals/pilot/` (labels + harness),
`tests/evals/test_accuracy_pilot.py` (the pinning suite),
`docs/metrics/quality-ledger.md` Part 2 (stays em-dash; what a real measured
number would require), `docs/metrics/operator-label-queue.md` (the D5 queue).
