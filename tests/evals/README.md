# LLM/AI Evals

AI-behaviour quality checks that drive the services directly (no HTTP).

| File | What it gates |
|---|---|
| `test_synthesis_eval_checks.py` | MVP synthesis quality checks. |
| `test_output_correctness_gate.py` | **OC-1 (blocking).** Runs the Layer-A evaluation engine over every case in `corpus/` and asserts the engine's structural verdicts equal the hand-authored human labels. Fails naming the case. |
| `test_trust_calibration.py` | **OC-2 (blocking).** The trust-vs-truth calibration gate: the count-only citation proxy cannot separate the adversarial corpus pair, the new `citation_marker_grounding` signal can, and no case is ever served a confidence figure without a real judge. |
| `corpus/` | The frozen labeled corpus and its loader. **Read `corpus/README.md` before adding a case** — the provenance rules there are binding. |

Everything here is hermetic: zero network, zero paid calls, no judge.
`StubEvalJudge` produces no measurable quality number, by design — numbers
from it are not eligible for `docs/metrics/quality-ledger.md`.
