# S4 Golden Set — README

## What this is (and is NOT)

These **78 cases are HAND-AUTHORED, REAL-SHAPED fixtures** for the S2 evaluation
engine (`src/product_app/evaluation.py`). They are **NOT captured production
runs.** No case is a recording of a live panel; every answer, source list, and
synthesis section was written by hand to exercise a specific engine code path.

- No case claims to be a real run.
- No human/operator label is fabricated. Where a case's subject-matter
  `expected` would need a genuine operator judgement (a high-stakes reference
  answer, a contested safety-policy verdict), the case is flagged
  `needs_human_label: true` with a one-line `needs_human_label_reason`, and only
  its **structural** signal expectations are asserted. See the END-review queue
  below.

The set is designed to be loaded by a hermetic runner with `judge=None`
(**zero I/O, zero paid calls** — the CI posture). With the judge off,
`TrustScore` is always `support_verified=False`, `band="unverified"`,
`score=None`; only Layer A structural signals are asserted.

## On-disk format

- Consolidated corpus: `golden-cases.json` — `{ "meta": {...}, "cases": [ ... ] }`.
- Authoring source: one JSON object per case under `cases/` (batched files),
  flattened by `flatten.py`. A production layout would place these one-per-file
  at `tests/evals/golden/cases/<id>.json` and load them with a `golden/loader.py`
  that **imports the `corpus/loader.py` case-building primitives** (`_answer`,
  `_source`, `_aggregate_coverage`, `_synthesis`) so per-answer
  `CitationCoverage` is still derived by production functions — a golden case
  cannot lie about its own coverage numbers. This is a **sibling** of
  `tests/evals/corpus/`, never inside `corpus/cases/`, because
  `corpus/loader.py` globs `cases/*.json` unconditionally and
  `tests/evals/test_trust_calibration.py` re-derives the S2 separation interval
  from `load_cases()`; adding files under `corpus/cases/` would move those
  measured numbers and redden a blocking gate.

### Per-case schema

| field | type | meaning |
|---|---|---|
| `id` | str, globally unique | `<category>-NN` |
| `query_text` | str | the (documented) user query; consumed only when a judge is on — `judge=None` never reads it |
| `category` | str | one of the 10 slices |
| `domain` | `general`\|`technical`\|`high_stakes` | balance axis |
| `tags` | list[str] | mechanic labels |
| `needs_human_label` | bool | true ⇒ subject-matter `expected` deferred to operator |
| `needs_human_label_reason` | str | required iff `needs_human_label` |
| `rationale` | str | **anti-OC-3 justification** + AUDIT note (see below) |
| `ground_truth` | str (optional) | reference answer / illustrative context |
| `expected_sources` | list[str] (optional) | reference URLs |
| `fixture` | obj | `{ initial_answers[], final_synthesis, agreement }` — the exact engine input shapes |
| `expected` | obj | the asserted Layer-A signals (labels, bands, flags) |

`fixture.initial_answers[*]` follow `InitialModelAnswer` (slot_number 1–4,
`answer_text`, `sources[]`, optional `provider_path`/`status`).
`fixture.final_synthesis` follows `FinalSynthesis` (`consensus`,
`disagreement`, `source_support`, `uncertainty`, `recommendation`,
`high_stakes_notice`, `quality_checks`). `fixture.agreement` = `{aligned,total}`.

## Anti-OC-3 rule (self-referential expectations are forbidden)

Every `expected` band/label is justified in `rationale` by the **case content**
— the count of citation markers that positionally resolve within each slot's own
bibliography, whether every slot is `openrouter_search`+`completed`+non-empty,
whether ≥50% of substantive slots open with a refusal phrase, whether a
`_POLAR_PAIRS` word splits the completed texts — **never** by "whatever the
engine currently outputs". Each rationale states, e.g., "k of n markers I wrote
point at real rows in that slot's own bibliography ⇒ k/n vs the 0.5/0.8 cuts".
The engine run is used only to **corroborate** the content-derived expectation;
every rationale carries an `AUDIT:` note recording that corroboration (and any
correction made when the draft's hand-count disagreed with the measured value).

Two cases deliberately document engine limitations rather than endorse the
output, and pin BOTH numbers: `adversarial-injection-03`
(`hallucination_risk_engine_output: "low"` while content warrants `high` —
DEBT-012 laundering) and `fabrication-grounding-03` (majority-resolve masks two
fabricated ordinals).

## Balance matrix (measured, 78 cases)

### By domain (target ≈ 1/3 each)

| domain | count | share |
|---|---|---|
| general | 23 | 29.5% |
| technical | 27 | 34.6% |
| high_stakes | 28 | 35.9% |

`general` sits slightly under a third and `high_stakes` slightly over: the
dedicated **`high-stakes` category is single-domain by construction** (all 9
cases are genuinely high_stakes), which structurally lifts that axis. No domain
field was edited to hit the target, because every domain label is correct on the
case content and relabelling would contradict it. The distribution is within the
"~1/3" tolerance.

### Category × domain

| category | gen | tech | hi | total |
|---|---|---|---|---|
| adversarial-injection | 3 | 3 | 2 | 8 |
| ambiguous-multi-hop | 3 | 3 | 2 | 8 |
| fabrication-grounding | 3 | 3 | 2 | 8 |
| factual-consensus | 3 | 3 | 2 | 8 |
| high-stakes | 0 | 0 | 9 | 9 |
| low-citation-obscure | 2 | 3 | 2 | 7 |
| noise-sensitivity-pairs | 2 | 4 | 2 | 8 |
| polar-disagreement | 3 | 3 | 2 | 8 |
| refusal-expected | 2 | 2 | 3 | 7 |
| time-sensitive | 2 | 3 | 2 | 7 |

Every category except `high-stakes` (intentionally single-domain) spans ≥2
domains with ≥2 cases in each of ≥2 domains.

### References

**32 / 78 cases (41.0%)** carry a `ground_truth` and/or `expected_sources`
(target ≈ 40%). References cluster on the cases where a factual reference is
meaningful (consensus, high-stakes reference answers, clean pair-halves) and are
absent on structural-only cases (refusals, degraded runs, framing questions)
where asserting a reference would be dishonest.

## Dedupe decision

No cases were dropped (78 is within the 60–80 target). Reviewed overlaps:

- **`noise-sensitivity-pairs` twins share `query_text` within each pair**
  (01≈02, 03≈04, 05≈06, 07≈08). This is the category's entire purpose — a clean
  half and a junk/degraded half of the identical query with opposite labels, a
  regression guard. Dropping either destroys the pair. **Kept, intentional.**
- **`high-stakes-01` (ibuprofen+ramipril) vs `noise-sensitivity-pairs-05`
  (ibuprofen+lisinopril)** — thematically adjacent but different queries and
  different structural roles (standalone grounded-medical anchor vs
  robustness-pair clean anchor). **Both kept.**
- **`polar-disagreement-03` (screening for a 45-year-old) vs `time-sensitive-05`
  (screening age shift)** — different queries; the second adds a temporal
  guidance-shift mechanic the first does not. **Both kept.**

No two cases share a `query_text` across categories, and all 78 `id`s are
globally unique (asserted by `flatten.py`).

## END-review queue — `needs_human_label: true` (18 cases)

Each is flagged because a subject-matter part of its expectation needs a real
operator label; its **structural** signals remain content-derived and asserted.

| id | reason (short) |
|---|---|
| factual-consensus-04 | 401(k) catch-up figures / higher-earner rule are year-sensitive tax law |
| factual-consensus-07 | smoke-alarm interval + NFPA/USFA attribution is a high-stakes safety reference |
| polar-disagreement-03 | clinical direction of a screening-interval recommendation |
| polar-disagreement-06 | home-office deductibility turns on filing status/jurisdiction |
| high-stakes-01 | 'triple whammy' AKI risk + patient safety is a clinical judgement |
| high-stakes-03 | RMD excise rate / correction-window mechanics are year-specific tax |
| high-stakes-05 | whether to switch funds is investment advice on unseen facts |
| high-stakes-08 | weighing hormone therapy for an individual is clinical |
| low-citation-obscure-04 | Section 1202 QSBS holding-period/basis mechanics (tax law) |
| noise-sensitivity-pairs-05 | clinical correctness of ibuprofen/ACE-inhibitor interaction |
| noise-sensitivity-pairs-06 | whether the panel's abstention is clinically correct |
| ambiguous-multi-hop-05 | substantive part-year home-office tax statements |
| ambiguous-multi-hop-06 | is 'faithful' correct for a suppressed polar clinical split? |
| adversarial-injection-03 | DEBT-012 laundering — automated low-risk verdict not trustworthy |
| adversarial-injection-04 | 4,000 mg acetaminophen ceiling is a medical reference |
| refusal-expected-07 | self-harm safe-completion policy is contested/operator |
| time-sensitive-01 | standing men's marathon record must be re-verified as-of eval date |
| time-sensitive-02 | which Node.js line is current LTS must be confirmed as-of eval date |

A meta-test should assert every `needs_human_label: true` case carries a
non-empty `needs_human_label_reason` (already enforced in `flatten.py`), and the
golden gate should skip/xfail-report the subject-matter expectation for these
rather than asserting it.

## Determinism / hermeticity

Every case is hermetic (`judge=None`, no I/O). The gate must confirm two
evaluations are byte-identical and that no answer prose (first 40 chars of any
answer ≥40 chars, plus the consensus) leaks into `model_dump_json()`, matching
the corpus gate's `test_evaluation_is_deterministic_and_carries_no_prose`.
