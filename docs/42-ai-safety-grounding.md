# AI Safety And Grounding

## 2026-06-17 correction

- Source-backed answering still prefers OpenRouter first and must surface visible fallback usage when fallback evidence is used.
- Partial, failed, or timed-out stages must remain explicit in the final result rather than being collapsed into false certainty.

## Scope

Quorum AI is an AI-assisted decision-support product. It compares four model outputs, asks models to critique disagreement, and synthesizes a final answer. It must reduce hallucination risk through transparency and grounding, but it must not claim guaranteed factual correctness or automated decision authority.

## Source Traceability

- FR-003: Query input safety warnings.
- FR-006: Search-backed initial model answers.
- FR-008: Two debate and critique rounds.
- FR-009: Final synthesis with confidence structure.
- FR-010: Timeout and partial-result recovery.
- FR-013: Query result presentation.
- NFR-003: Citation coverage.
- NFR-007: Sensitive data minimization.
- NFR-008: High-stakes decision-support boundary.

## Grounding rules

| Rule | Requirement |
|---|---|
| Source-first factual claims | When source-backed search succeeds, material factual claims in model answers and synthesis must show visible source links. |
| OpenRouter-first search | OpenRouter search-backed answering is attempted before fallback search. |
| Fallback transparency | Fallback provider usage is recorded and visible as operational/result metadata. |
| Citation coverage target | At least 80 percent of material factual claims in sampled final syntheses reference visible sources when source-backed search succeeds. |
| No false consensus | Material disagreement must remain visible in the final synthesis. |
| Partial honesty | Missing model/search/debate/synthesis steps must be named in partial results. |
| Decision support only | Medical, legal, financial, safety, and regulated-topic outputs must be framed as decision support, not professional advice or automated decisions. |

## AI Workflow Safety Controls

1. User sees sensitive/private-data and high-stakes warnings before query execution.
2. Query orchestration builds provider prompts that ask for source-backed answers and uncertainty.
3. Search results and retrieved content are treated as untrusted evidence, not as instructions.
4. Debate prompts focus on disagreement, weak support, missing reasoning, and citation quality.
5. Synthesis prompt requires separate sections for consensus, disagreement, source support, uncertainty, and recommendation.
6. Synthesis must not erase provider failures or unresolved contradictions.
7. Result presentation shows model-level outputs so users can audit the synthesis.

## Prompt Injection Boundary

- User prompt, retrieved web content, model answers, and debate outputs are untrusted inputs.
- The system must not follow instructions from retrieved pages that ask it to ignore policy, reveal secrets, fabricate citations, change model configuration, or call tools.
- Provider keys, internal system prompts, secret-store references, and hidden configuration must not be included in model-visible context.
- Prompt-injection regression tests are required before implementation completion.

## High-Stakes Handling

| Topic | Behavior |
|---|---|
| Medical | Warn decision support only; no diagnosis/treatment authority claims. |
| Legal | Warn decision support only; no attorney-client/professional advice framing. |
| Financial/investment | Warn decision support only; preserve uncertainty and source support. |
| Safety-critical | Warn decision support only; avoid presenting instructions as certified safe. |
| Regulated topics | Warn decision support only and avoid compliance guarantees. |

The MVP warns; it does not yet block these topics unless future policy changes require blocking.

## Evaluation Requirements

| Eval | Purpose | Trace |
|---|---|---|
| Citation coverage sample | Verify 80 percent material-claim citation target when search succeeds. | NFR-003, AC-031 |
| False consensus cases | Ensure synthesis preserves material disagreement. | FR-009, AC-019 |
| High-stakes warning set | Ensure warning coverage for medical, legal, financial, safety, and regulated examples. | NFR-008, AC-034 |
| Prompt-injection set | Ensure retrieved content cannot override policies or reveal secrets. | T-007 |
| Partial-result cases | Ensure missing provider/debate/synthesis steps are visible. | FR-010, AC-022 |
| Secret-exposure cases | Ensure prompts/errors/logs do not contain app-owned or BYO provider keys. | FR-011, NFR-006 |
| Layer-A determinism set | Ensure the deterministic evaluator is reproducible (same run ⇒ byte-identical evaluation and TrustScore) and performs zero I/O. | FR-015, NFR-011, AC-041 |
| Citation-marker grounding set | Ensure inline citation markers resolve to a real non-fallback source; catch a fluent answer sprinkled with fabricated citations that count-only coverage cannot detect. | FR-015, NFR-003, AC-041 |
| Refusal-detection set | Ensure a provider refusal is classified rather than scored as a substantive answer. | FR-015, AC-041 |
| OC-2 honesty set | Ensure the numeric TrustScore is suppressed and the served band is `unverified` whenever citation SUPPORT was never verified by a real judge. | FR-015, NFR-011, AC-041 |
| Judge neutrality set | Ensure judge OFF makes zero seam calls and produces a TrustScore identical to `StubEvalJudge` ON. | NFR-012, AC-042 |
| Judge injection set | Ensure provider prose cannot instruct the judge to inflate its verdict or declare support verified. | T-011, AB-007 |
| Trust-surface honesty set | Ensure no digit and no advisory label word is rendered while `support_verified` is False, and an absent evaluation hides the surface rather than rendering a fabricated or ambiguous value. | FR-016, AC-044 |

## Release 2: Per-Run Evaluation (FR-015)

### Metric vocabulary

The evaluation engine borrows the DeepEval / RAGAS vocabulary so the R2-S4
golden-set harness can be wired to those libraries without renaming anything:

| Term | Meaning here | Layer |
|---|---|---|
| Faithfulness | Does the answer only assert what its cited evidence supports? | B (judge, 0-5) |
| Answer relevancy | Does the answer address the question asked? | B (judge) |
| Contextual/citation grounding | Do the answer's citation markers resolve to real retrieved sources? | A (`citation_marker_grounding`), corroborated by B (judge, 0-5) |
| Citation coverage | What fraction of material claims carry a citation at all? | A |
| Hallucination risk | Qualitative low/medium/high judgement of ungrounded assertion. | B (judge) |
| Disagreement preservation | Is material model disagreement still visible in the synthesis? | A (false-consensus check), corroborated by B |

### Layer A / Layer B split

- **Layer A is deterministic, always on, hermetic, and performs zero I/O.** It is
  the only input to the `TrustScore` arithmetic. Signals: citation coverage,
  agreement, false-consensus preservation, decision-support framing,
  high-stakes-warning presence, uncertainty surfaced, live ratio, completeness,
  refusal detection, and citation-marker grounding.
- **Layer B is an optional LLM-as-judge**, key-gated on
  `QUORUM_EVAL_JUDGE_API_KEY` and OFF by default, reusing the existing provider
  call seam. Its verdict is advisory metadata; it never enters the composite
  arithmetic, and it is uncalibrated until the S4 golden set exists.
- Count-based proxies are **not** quality measurements. A count says a citation
  is present; it says nothing about whether the citation supports the claim.

### What the trust surface claims — and does not claim

The served `unverified` band is a statement that citation SUPPORT was never
verified. It is not a low-confidence score, and the surface never renders it as
one: it renders **no digit at all**, so `layer_a_composite_unverified` and every
per-signal contribution are structurally unrenderable.

The advisory `faithfulness_label` and `hallucination_risk` are **not rendered as
words** in any branch. Two reasons, both measured. First, DEBT-012: one resolving
ordinal carries any number of fabricated URL citations to `faithful` / `low`, and
there is no dilution at any dose — a single fabricated link beside one good ordinal
already scores 1.0. Second, `layer_a_composite_unverified` is biased UPWARD exactly
on the runs that deserve least trust, because when grounding is unknown the largest
weight (0.30) is dropped and the remainder renormalised, so an un-checkable run is
scored purely on liveness, coverage, completeness and framing and can out-score a
run whose grounding was measured bad.

What closes the S3 exposure is the presentation guard, not a label change. The
engine serves `label_confidence`; a run carrying any unverifiable off-run URL marker
whose labels sit at the confident end is `indeterminate` and can never present a
confident verdict. The guard is cut-free (it chooses no constant) and
monotone-downward (it never suppresses a warning), so it can only under-claim.

Even on the reportable branch the surface qualifies itself — "Structural checks
passed — citations were not verified against their sources" — because a model that
invents plausible SOURCE ROWS and then cites `[1]`, `[2]` reaches grounding 1.0 with
zero unverifiable markers, and Layer A with zero I/O cannot detect that at all.

The Layer-B judge is not surfaced in S3 and has no client-visible field. The served
projection has no `judge` key at any depth, and that is asserted by
`tests/unit/test_evaluation_projection_has_no_judge.py`.

### Binding honesty rule (OC-2)

A numeric `TrustScore` is **suppressed** and qualified as `unverified` whenever
citation SUPPORT was never verified. Concretely:

- `TrustScore.support_verified` is False unless a **real** Layer-B judge returned
  a citation-support verdict.
- While `support_verified` is False, no numeric confidence figure is served — the
  band is `unverified`.
- `StubEvalJudge` deliberately does not set `support_verified`, because a stub
  verifies nothing. Judge-OFF and stub-ON are therefore byte-identical, and every
  hermetic CI run serves `unverified`.
- Numbers produced with `StubEvalJudge` are not eligible as measured quality
  evidence anywhere in the documentation set.

This rule is the concrete form of the existing "no hidden confidence as a single
unqualified truth score" commitment below.

## Refusal And Warning Behavior

- The MVP must warn for high-stakes and sensitive/private-data risk.
- The MVP must not claim outputs are guaranteed correct.
- The MVP must not execute decisions for users.
- The MVP must not provide hidden confidence as a single unqualified truth score; confidence should be explained through source support, agreement/disagreement, and uncertainty.

## Open AI Safety Questions

| ID | Question | Owner | Impact |
|---|---|---|---|
| OQ-011 | Should any high-stakes topic move from warning-only to block/limited mode before public launch? | Product owner | Impacts UX, policy, tests, and release scope. |
| OQ-012 | What exact citation evaluation rubric will count a material claim as supported? | Product owner | Required for NFR-003 validation. |
| OQ-013 | Which provider/model outputs may be retained for eval sampling, and for how long? | Product owner | Required for privacy and AI quality measurement. |
