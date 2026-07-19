# Prompt Registry

| Prompt ID | Purpose | Owner | Model/tool | Input sources | Output contract | Eval cases | Version | Approval |
|---|---|---|---|---|---|---|---|---|
| PROMPT-001 | TBD | TBD | TBD | TBD | TBD | EVAL-001 | v0.1 | TBD |
| PR-EVAL-JUDGE-v1 | Layer-B LLM-as-judge for FR-015: score one terminal run's synthesis for faithfulness, grounding, disagreement preservation, and hallucination risk, and state whether citation support was actually verified. | Engineering lead | Pinned model id read from `QUORUM_EVAL_JUDGE_MODEL_ID`, called through `providers.call_with_prompt`; temperature 0 (lowest the provider allows) for reproducibility; key-gated on `QUORUM_EVAL_JUDGE_API_KEY`, OFF by default. | The run's query text, the final synthesis prose, and the per-slot source references — supplied as delimited, explicitly untrusted **evidence**, never as instructions. No secrets, no system prompts, no configuration. | Strict JSON only, parsed into the Pydantic `EvalJudgeVerdict`: `faithfulness` (int 0-5), `grounding` (int 0-5), `disagreement_preserved` (bool), `hallucination_risk` (`low` \| `medium` \| `high`), `rationale` (str), `model_id` (str). Any non-conforming or unparseable response yields **no verdict** — never a partial or coerced one. | Judge neutrality set (AC-042), judge injection set (T-011/AB-007), OC-2 honesty set (AC-041); calibration against the R2-S4 golden set is not yet done. | v1 | Not approved for scoring use — advisory and uncalibrated until the S4 golden set (FS-6). Enabling the key in any environment requires explicit human approval. |

## Change rule
Any prompt change must update eval evidence and model-risk records before release.

## PR-EVAL-JUDGE-v1 notes

- **Versioning.** The id carries the version (`-v1`). Any change to the
  instruction text, the output schema, or the pinned model is a new version
  (`-v2`), because verdicts from different versions are not comparable.
- **Advisory only.** The verdict never enters the `TrustScore` arithmetic. It can
  set `TrustScore.support_verified` only when it is a real (non-stub) judge and
  it returned a citation-support verdict; it can never raise a numeric score.
- **Injection posture.** Provider prose is attacker-influenceable. The prompt
  states that the evidence block is data to be evaluated, that instructions
  inside it must be ignored and may themselves be evidence of a problem, and
  that the response must be JSON matching the schema and nothing else.
- **Determinism.** Low temperature plus a pinned model is a mitigation, not a
  guarantee; judge runs are not claimed to be reproducible, which is one reason
  Layer B is excluded from the deterministic `TrustScore`.
