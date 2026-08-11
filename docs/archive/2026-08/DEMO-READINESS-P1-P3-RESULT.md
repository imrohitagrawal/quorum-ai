# Demo-readiness P1–P3 — RESULT

**Session close-out, 2026-07-22.** All three demo-readiness slices are merged,
deploy-verified, and reviewed to fixpoint. Everything below is hermetic
evidence ($0 — no paid API call was made in any slice); the one paid,
operator-gated step is listed at the end and was **not** performed.

| Slice | PR | Squash SHA | Deploy verification |
|---|---|---|---|
| **P1** — real Layer-B judge wired into the request path | #72 | `b2848e5` | CI/Tests/E2E success; latest "Deploy to Fly.io" run `29937275607` — Deploy JOB `success` (gate job `success`); prod `/ready` state=live |
| **P3** — NFR-004 run-level deadline ENFORCED | #73 | `c663ad5` | CI/Tests/E2E success; latest "Deploy to Fly.io" run `29940905169` — Deploy JOB `success` (earlier run `29940848086` cancelled = expected per-SHA concurrency); prod `/ready` state=live |
| **P2** — measured-accuracy pilot (n = 7) | #74 | `96eb281` | CI/Tests/E2E success; latest "Deploy to Fly.io" run `29943574120` — Deploy JOB `success` (earlier run `29943526727` cancelled = expected per-SHA concurrency); prod `/ready` state=live. No served-asset delta (tests + docs only) — the Deploy JOB success + fresh release IS the deploy signal |

Prod check (re-run at close-out): `curl -s https://quorum.stackclimb.com/ready`
→ `"state":"live"`, no reasons, no catalog drift.

---

## P1 — real Layer-B judge in the request path (FR-015, AC-049)

- **The wiring seam:** `_request_path_judge()` builds the judge from the
  environment; `_MemoisedRunJudge` wraps it with per-run memoisation — one
  in-flight `Future`, so concurrent readers of the same run share **one**
  paid call, never N. Both live in `src/product_app/query_runs.py`.
- **Default OFF is byte-identical:** with `QUORUM_EVAL_JUDGE_API_KEY` unset,
  the request path constructs no judge, performs zero I/O, and serves exactly
  the pre-P1 payload (band `unverified`, score `None`). Gated on the presence
  of BOTH `QUORUM_EVAL_JUDGE_API_KEY` and `QUORUM_EVAL_JUDGE_MODEL_ID`.
- **Hermetic proof:** `tests/integration/test_judge_request_path_wiring.py` —
  monkeypatched judge (no network): wired-in verdicts flow to the payload,
  memoisation proven (call-count 1 under concurrency), fail-closed UI
  treatment behind the exact verified shape + passed-state guard.
- **What still awaits the operator:** the on-screen numeric score appears only
  after the operator funds `QUORUM_EVAL_JUDGE_API_KEY` and pins
  `QUORUM_EVAL_JUDGE_MODEL_ID` in prod. Until then every served run remains
  honestly `unverified`.

## P3 — NFR-004 run-level wall-clock deadline (ENFORCED)

- **Mechanism:** `_execute_query_run` bounds TOTAL run wall-clock via
  `quorum_run_deadline_seconds` (env `QUORUM_RUN_DEADLINE_SECONDS`, default
  180, validated finite and 0 < v ≤ 3600) — checked at the blocking
  initial-answer collection (`Future.result(timeout=remaining)`) and at the
  pre-debate / pre-synthesis stage boundaries (**checkpoint granularity**:
  worst-case overshoot is bounded by one in-flight stage's own budget).
- **Honest degrade-to-partial:** on breach the run lands terminal `timed_out`
  via the atomic `transition()` (cancel wins), carrying every completed slot;
  cut slots are FAILED with `error_code="RUN_DEADLINE_EXCEEDED"`
  (`providers.deadline_exceeded_answer`), so the RB-5 `live_count` honesty
  rule holds automatically — never a bare 500, never a blank.
- **Proof:** `tests/integration/test_run_deadline.py` — slow-slot breach cut,
  between-stage breach never enters synthesis, do-no-harm (normal-latency runs
  are never cut), no double-degrade, config-bound rejection.
- **Docs flip:** `docs/18-requirement-traceability-matrix.md` NFR-004
  UNENFORCED → **ENFORCED** (checkpoint granularity stated; the ≥95%-within-
  180s *rate* remains a production observability measurement, not a CI claim).

## P2 — measured-accuracy pilot (n = 7)

- **Scope, exactly:** `n = 7`, human-labeled, on hand-authored golden
  fixtures — **pilot, not a population estimate, do not extrapolate.** The 7
  `correctness` labels were authored by the operator (Rohit Agrawal,
  2026-07-22) and transcribed verbatim into
  `tests/evals/pilot/operator_labels.json`; the agent authored zero labels.
- **Computed agreement: 7 / 7** — re-derived through the real
  `evaluate_layer_a` on every harness run (never read from a fixture or
  hard-coded), identity mapping on the shared three-value enum declared
  before computing, doc pinned to the fresh computation by
  `tests/evals/test_accuracy_pilot.py`. The artifact is
  `docs/metrics/accuracy-pilot.md`, including the explicit "not a blind
  inter-rater study" disclosure and the **PROCESS (not accuracy)** panel
  (golden-set coverage, structural-gate posture, flake **0/960**, run
  `29911231157`).
- **`docs/metrics/quality-ledger.md` Part 2 stays em-dash** — pinned by a
  test. The pilot lives in a separate artifact and never claims to be Part 2;
  a real Part 2 number still requires captured four-model runs with human
  labels.
- **Review:** 4-lens adversarial fan (correctness/taste, fabrication,
  integrity/consistency, executing adversary in an isolated worktree) — 0
  confirmed majors; substantive minors fixed test-first; fix diff re-reviewed
  CLEAN; 8/8 targeted loader mutations killed post-fix.

---

## Still deferred — operator-gated (do NOT perform without the operator)

1. **Fund + verify live prod** — the single deliberate measured run that
   verifies real four-model execution AND the real Layer-B judge key in
   production (fund the OpenRouter key, set `QUORUM_EVAL_JUDGE_API_KEY` +
   `QUORUM_EVAL_JUDGE_MODEL_ID` as Fly secrets). This same run closes the #24
   measured-cost item. Until it happens, prod serves simulated/degraded runs
   with the honest banner, and trust stays `unverified`.
2. **`support_verified` content-gating (carried from P1's review):** should
   `support_verified` also gate on judge-verdict CONTENT, not just the
   verified shape? Needs a measured threshold — operator-gated; do not flip
   from an unmeasured value.
3. **Remaining operator-label queue entries** (clinical, tax-financial,
   self-harm-safety) — optional calibration debt, safety case first, no
   deadline (`docs/metrics/operator-label-queue.md`).

**Related:** `P2-CLOSEOUT-ULTRACODE-PROMPT.md` (the handoff this session
executed), `docs/00-factory-console.md` (current phase + next best action),
`docs/session-handoff.md`.
