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
that carries a `correctness` field. The deferred labels live in
`docs/metrics/operator-label-queue.md`, which the gate keeps in sync with these
files. A fabricated subject-matter label is indistinguishable from a real one
and would corrupt the eval forever — so it is documented, optional calibration
debt, no deadline, safety case first.

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

A `correctness` field is forbidden and rejected by the loader — subject-matter
labels belong only in the operator queue.
