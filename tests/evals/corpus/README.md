# S2 output-correctness corpus (OC-1)

## Provenance — read this first

**These cases are HAND-AUTHORED, real-SHAPED fixtures. They are NOT captured
real four-model runs, and they are NOT human-labeled production data.**

Every case in `cases/` was written by hand to look like genuine provider
output (headings, bold/italic, ordered lists, blockquotes, inline code
markers, hedging, multi-paragraph prose, inline citation markers). The
labels on each case are likewise hand-authored: they encode what the
*evaluation engine's structural verdict* must be, not an expert judgement
about the underlying subject matter.

Consequences, stated plainly:

- No number derived from this corpus is a measured quality metric. It is a
  regression oracle for the engine's own logic.
- Nothing here is eligible for `docs/metrics/quality-ledger.md` Part 2.
  That table needs the S4 golden set with real runs and human labels.
- The high-stakes case (`03-preserved-polar-disagreement`) is labeled for
  its *structure* — disagreement preserved, markers grounded, warning
  present. It is explicitly **not** a clinical judgement. Genuine
  medical/legal/financial correctness labels require a qualified human
  reviewer and real captured runs; that is an operator task, recorded as
  such and never faked here.

## What the corpus is for

`tests/evals/test_output_correctness_gate.py` is a blocking hermetic gate:
for each case it runs the Layer-A evaluation engine and asserts the engine's
verdicts (`faithfulness label`, `hallucination risk`, refusal,
false-consensus preservation, high-stakes warning) equal the hand-authored
labels. If the engine's behaviour drifts, the gate fails and names the case.

`tests/evals/test_trust_calibration.py` is the OC-2 gate: it proves the
count-only citation proxy cannot separate case 01 from case 02, and that
the served trust for the fluent-but-unfaithful case is never a
high-confidence figure.

## Case schema

One JSON object per file in `cases/`. Files are loaded in file-name order.

| Key | Type | Meaning |
|---|---|---|
| `case_id` | str | Stable id used in assertion messages. Unique across the corpus. |
| `label` | `faithful` \| `unfaithful` \| `partial` | Human label for the run as a whole. `partial` = neither trustworthy-as-written nor an outright fabrication (refusal, simulated/degraded run, grounding unknowable). |
| `expected_refusal` | bool | Every substantive slot declined. |
| `expected_false_consensus_preserved` | bool | Material disagreement is still visible in the synthesis. |
| `expected_high_stakes` | bool | A high-stakes warning is required and present. |
| `expected_hallucination_risk` | `low` \| `medium` \| `high` | Expected Layer-A risk band. |
| `notes` | str | Why this case exists and what it is meant to catch. |
| `run.initial_answers[]` | list | Per-slot answer, see below. |
| `run.final_synthesis` | object \| null | Synthesis sections + `quality_checks`. |

Per answer: `slot_number` (1-4), `model_id`, `display_name`, `answer_text`,
`sources[]` (`title`, `url`, optional `provider`, optional `is_fallback`),
optional `provider_path` (default `openrouter_search`), optional `status`
(default `completed`), optional `latency_ms`, `error_code`,
`provider_notice`.

Per synthesis: `status`, `consensus`, `disagreement`, `source_support`,
`uncertainty`, `recommendation`, `high_stakes_notice`, and
`quality_checks.{false_consensus_preserved, decision_support_framing_present,
high_stakes_warning_required}`.

**Citation coverage is never hand-written.** `loader.py` derives
`CitationCoverage` with the same production functions
(`providers.estimate_material_claim_count`,
`providers.calculate_citation_coverage`) and reproduces the synthesis-level
aggregation from `synthesis.py`, so a case cannot assert a coverage number
its own text does not earn. `citation_coverage_target_met` in
`quality_checks` is likewise derived, not declared.

## Adding a case

1. Write the JSON. Make the prose look like real provider output — if it
   reads like a fixture, it will not catch the bugs real output causes.
2. Add the labels. State in `notes` what the case is meant to catch.
3. Run the gate. If it passes immediately and you cannot make it fail by
   corrupting the engine, the case is not testing anything.
