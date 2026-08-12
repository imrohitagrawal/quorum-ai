# S4 golden evaluation set (OC-1 / OC-3 seed)

## Provenance — read this first

**These cases are HAND-AUTHORED, real-SHAPED fixtures. They are NOT captured
real four-model runs, and they are NOT human-labeled production data.** This is
the same discipline as the S2 corpus at `../corpus/`, and the same consequences
apply.

Every case in `cases/` was written by hand to look like genuine provider output
(headings, ordered lists, blockquotes, inline citation markers, hedging,
multi-paragraph prose). The `label`, `expected_hallucination_risk`,
`expected_refusal`, `expected_false_consensus_preserved`, and
`expected_high_stakes` fields on each case encode what the **evaluation engine's
STRUCTURAL verdict** must be — they were each MEASURED by running the real Layer-A
engine over the fixture and recorded, never guessed. They are a regression
oracle for the engine's own logic, not an expert judgement about the subject
matter.

Consequences, stated plainly:

- No number derived from this set is a measured product-quality metric. It is a
  regression oracle for the engine's structural logic.
- Nothing here is eligible for `docs/metrics/quality-ledger.md` Part 2. That
  table needs real captured runs with human labels.

## The D5 human-label boundary

Four cases carry `needs_human_label: true`, one per subject-matter domain
(`clinical`, `tax-financial`, `as-of-date`, `self-harm-safety`). For these, the
engine still derives structural signals and the gate asserts them — but whether
the answer is **subject-matter correct** (medically, legally, financially, or
against the self-harm safety policy) is a judgement only a qualified human may
make. That label is **never authored in the fixture**: the loader
(`loader.py`) and the gate (`../test_golden_set_gate.py`) both reject a fixture
that carries a `correctness` field. A fabricated subject-matter label is
indistinguishable from a real one and would corrupt the eval forever — so it
is kept structurally separate from the fixture by design.

**All four labels are complete.** `docs/metrics/operator-label-queue.md`
records a genuine human subject-matter review for all four domains, each
dated, sourced, and attributed — completed 2026-07-23.
`docs/metrics/accuracy-pilot.md` independently corroborates this: an n=10
comparison of the engine's structural verdict against these same operator
labels measured 10/10 agreement. This is real, completed human verification
of the four highest-stakes cases — separate from, and not to be confused
with, the threshold-calibration status below, which remains open.

## Calibration status (separate from the D5 labels above)

The advisory thresholds in `src/product_app/evaluation.py`
(`GROUNDING_FABRICATION_THRESHOLD`, `GROUNDING_GOOD_THRESHOLD`, the trust
bands, `LAYER_A_WEIGHTS`) **have not yet been calibrated against a measured
run.** `docs/evidence/s4-golden-calibration/CALIBRATION-NOTES.md` maps each
threshold to the specific golden cases that bound it — real methodology for
*how* to calibrate — but its own text is explicit that "no new threshold
values are proposed here — that requires the measurement run," and it ends
without a results section. `docs/metrics/quality-ledger.md` independently
confirms the thresholds "remain ADVISORY and uncalibrated." This is
documented, optional calibration debt, no deadline, safety case first — and
a distinct fact from the D5 labeling above, which is done.

## What the set is for

`../test_golden_set_gate.py` is a blocking hermetic gate: it runs the
deterministic engine over every case and fails, naming the case, if a structural
verdict drifts from its declared value. The set deliberately exercises all three
faithfulness labels, all three hallucination-risk bands, refusal,
false-consensus preservation, high-stakes presence, and the judge-OFF
suppression rule (band `unverified`, score `None`).

## Schema

Each `cases/NN-name.json` file:

| Field | Meaning |
|---|---|
| `case_id` | Stable id, unique across the set. |
| `needs_human_label` | `true` iff subject-matter correctness is deferred to the operator queue. |
| `domain` | `structural`, or one of the four human-label domains. |
| `question` | The question the panel was asked (surfaced verbatim in the operator queue). |
| `panel_summary` | App-authored one-line summary of what the panel answered. Never a correctness claim. |
| `label` | The engine's MEASURED structural faithfulness verdict (`faithful` / `unfaithful` / `partial`). |
| `expected_hallucination_risk` | The engine's MEASURED risk band (`low` / `medium` / `high`). |
| `expected_refusal` / `expected_false_consensus_preserved` / `expected_high_stakes` | MEASURED structural booleans. |
| `notes` | Why the case exists and what it exercises. |
| `run.initial_answers` / `run.final_synthesis` | The real-shaped run. Coverage and agreement are DERIVED by the loader (reusing the S2 corpus primitives), never hand-written. |

`run.final_synthesis.synthesis_mode` is **required** and validated against
`product_app.synthesis.SYNTHESIS_MODES` — the S2 corpus loader these cases reuse
enforces it (see `tests/evals/corpus/README.md` for why). All ten cases declare
`live`: every one takes the default `openrouter_search` path on at least one
answer, and each `final_synthesis` is hand-authored to read as model output.
Declaring it matters because since #171 finding 5 per-model alignment refuses to
compare an opening against a synthesis this product templated, so the field
feeds the `agreement` figure each case is evaluated with. Measured on
2026-07-30: declaring all ten `live` leaves every case's `agreement` and all ten
pilot verdicts byte-identical to `9c60bc3`.

A `correctness` field is forbidden and rejected by the loader — subject-matter
labels belong only in the operator queue.
