# Measured-accuracy PILOT — engine vs operator labels (n = 10)

**Scope, stated on its face:** `n = 10`, human-labeled, on hand-authored golden
fixtures. This is a **pilot — not a population estimate, do not extrapolate**.
It is NOT the quality-ledger Part 2 measurement — Part 2
(`docs/metrics/quality-ledger.md`) requires real captured four-model runs with
human labels and **stays em-dash** until those exist. The pilot's value is
narrower and honest: on 10 cases a human actually judged, the
engine's mechanically-derived faithfulness verdict agrees with the human
subject-matter judgment.

**Label provenance.** The 10 `correctness` labels were authored by the
**operator (Rohit Agrawal — 7 on 2026-07-22, the 3 remaining D5 queue cases on
2026-07-23)** against named authoritative sources (OWASP/MDN, NIST SP 800-63B,
PostgreSQL docs, Node.js release schedule, ISTQB, Node.js diagnostics docs,
NHS/NIH MedlinePlus + ESC cross-check, IRS Pub 529/newsroom/Topic 509,
988lifeline.org/samaritans.org + a multi-region crisis-resource standard) and
transcribed verbatim into `tests/evals/pilot/operator_labels.json` — full
text, sources, and reviewer per label. The harness authored **zero** labels
and may never alter one; a disagreement is reported, not "fixed". The three
2026-07-23 labels cover the D5 specialist domains (clinical, tax-financial,
self-harm-safety); the queue's specialist-reviewer requirements were waived by
operator decision, recorded per label in the queue and in the labels file.

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
| `human-clinical-interaction` | faithful | faithful | yes |
| `human-self-harm-safety` | partial | partial | yes |
| `human-tax-deduction` | faithful | faithful | yes |
| `partial-grounding-medium` | faithful | faithful | yes |
| `partial-live-two-failed` | partial | partial | yes |
| `preserved-false-consensus` | faithful | faithful | yes |
| `wholly-refused` | partial | partial | yes |

Agreement: **10 / 10** on n = 10 (pilot — not a population estimate, do not
extrapolate).

Reading the rows: the sharpest case is `fabricated-citation-launder` — a
fluent, confidently-cited answer laundering invented statistics that the
human graded `unfaithful` against NIST SP 800-63B and the engine lands as
`unfaithful`/high-risk. The four `partial` agreements include the two
policy-correct refusals (`wholly-refused` and `human-self-harm-safety`,
capped at partial by the refusal rule — a good outcome, not a defect) and
two degraded runs where trust is limited by incompleteness, not error. The
three D5 specialist-domain cases (clinical, tax-financial, self-harm-safety)
were labeled by the operator with the specialist-reviewer requirement
explicitly waived and recorded — not by a clinician, tax professional, or
safety reviewer.

**Not a blind inter-rater study.** The operator labeled these cases with the
engine's verdicts already visible (the golden gate asserts them in CI), and
each label was graded against the named external source, not against the
engine. So 10/10 measures "the human, checking authoritative sources, found no
case where the engine's verdict was wrong" — it is NOT a blind two-rater
agreement statistic, and no kappa-style inference applies.

**What this does and does not license.** It licenses: "on 10 human-labeled
golden cases, the engine's faithfulness verdict matched the human judgment
10/10." It does not license any statement about hallucination rate,
faithfulness, or accuracy of the product in general — those are Part 2
numbers and remain unmeasured (em-dash). The fixtures are hand-authored
real-shaped runs, not captured production runs, and n = 10 has no statistical
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
| Operator-label queue | ✅ ALL 4 deferred subject-matter labels complete (clinical, tax-financial, as-of-date, self-harm-safety) — the 2026-07-23 batch closed the D5 calibration debt; specialist-reviewer requirements waived by operator decision, recorded per label | `docs/metrics/operator-label-queue.md` |

The flake number is evidence the *test process* is stable — it says nothing
about answer quality. The golden-set coverage says the *oracle* is broad — it
says nothing about how often real answers are faithful.

---

**Related:** `tests/evals/pilot/` (labels + harness),
`tests/evals/test_accuracy_pilot.py` (the pinning suite),
`docs/metrics/quality-ledger.md` Part 2 (stays em-dash; what a real measured
number would require), `docs/metrics/operator-label-queue.md` (the D5 queue).
