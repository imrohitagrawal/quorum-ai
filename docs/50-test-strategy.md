# Test Strategy

## 2026-06-17 correction

- Primary regression coverage now includes browser-session issuance/expiry, CSRF protection, session-scoped BYO key ownership, estimate-confirm-block flow, live stage progress, cancellation, and ephemeral-result behavior.

## Test pyramid

Unit, integration, contract, e2e, security, performance, accessibility, resilience.

## Requirement mapping

See `docs/18-requirement-traceability-matrix.md`.

## Release 2: Evaluation testing (FR-015, NFR-011, NFR-012)

- Layer-A evaluation is a pure function with zero I/O, so it is tested as unit
  code: determinism (same run ⇒ byte-identical evaluation and TrustScore),
  `citation_marker_grounding` on a fabricated-citation fixture, `detect_refusal`,
  and the OC-2 suppression rule (`tests/unit/test_evaluation_layer_a.py`,
  `tests/evals/test_output_correctness_gate.py`).
- Layer B is never called for real in any test. The key gate, the strict-JSON
  `EvalJudgeVerdict` contract, and the malformed-response-yields-no-verdict path
  are exercised against `StubEvalJudge` and monkeypatched seams
  (`tests/unit/test_evaluation_judge.py`).
- Neutrality is proven with a seam spy: judge OFF makes zero
  `providers.call_with_prompt` invocations and yields a TrustScore identical to
  `StubEvalJudge` ON (`tests/unit/test_evaluation_neutrality.py`).
- The account boundary is tested at the API edge: unauthenticated 401 and
  cross-account 404, neither carrying an `evaluation` payload
  (`tests/unit/test_evaluation_auth_boundary.py`,
  `tests/integration/test_query_run_evaluation_endpoint.py`).
- Numbers produced with `StubEvalJudge` are not eligible as measured quality
  evidence; the quality-ledger output columns stay `—` until the S4 golden set.
