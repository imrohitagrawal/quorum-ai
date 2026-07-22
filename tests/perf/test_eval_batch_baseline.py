"""PERF-010 eval-batch latency baseline (RB-2, ADVISORY).

`docs/55-performance-baseline.md` PERF-010 asks for a baseline on the "MVP eval
batch with synthetic provider outputs". This is it: run the deterministic
Layer-A engine (FR-015) over the whole S4 golden set (FR-017) and record the
batch runtime.

Why ADVISORY, not blocking
--------------------------
The measured envelope below is tiny and machine-dependent, and DEBT-009 is the
standing lesson that a machine-derived latency budget false-fails a slower CI
runner and strands deploys. So this test asserts only a DELIBERATELY GENEROUS
hermetic ceiling — large enough that no realistic CI runner trips it, small
enough to catch a catastrophic regression (accidental I/O, an O(n^2) blow-up, a
network call sneaking into a "pure" path). It runs on the advisory `eval.yml`
schedule, never on the deploy path, and never in the blocking suite's budget.

Measured baseline (2026-07-22, macOS/darwin 25.5.0, Apple M4, `uv run pytest
tests/perf/test_eval_batch_baseline.py -q --no-cov -s`, judge OFF, zero I/O).
Batch = one `evaluate_layer_a` + `build_trust_score` over each of the 10 golden
cases; 20 batches after a warm-up batch:

    batch p50 : ~2.0 ms
    batch p95 : ~2.2 ms
    batch max : ~2.6 ms

Chosen budget (headroom over the worst observed value):

    EVAL_BATCH_P95_BUDGET_MS = 200    ~77x the worst observed batch (2.6 ms)

The number is intentionally not tight: this is a smoke ceiling on a hermetic,
deterministic computation, not a calibrated SLO. Tightening it into a real
regression budget needs a CI-runner measurement (none exists yet) and a human
call — exactly the guardrail discipline DEBT-009 records. It is deliberately not
changed here on the strength of one laptop.
"""

from __future__ import annotations

import importlib.util
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from product_app.evaluation import build_trust_score, evaluate_layer_a

_LOADER_PATH = Path(__file__).resolve().parents[1] / "evals" / "golden" / "loader.py"
_spec = importlib.util.spec_from_file_location("s4_golden_loader_perf", _LOADER_PATH)
assert _spec is not None and _spec.loader is not None
_golden = importlib.util.module_from_spec(_spec)
sys.modules["s4_golden_loader_perf"] = _golden
_spec.loader.exec_module(_golden)

#: ~77x the worst locally observed batch (2.6 ms). Advisory smoke ceiling, not an
#: SLO — see the module docstring and DEBT-009.
EVAL_BATCH_P95_BUDGET_MS = 200.0

#: How many batches to time. Small — this is a smoke measurement, not a
#: statistical study; the blocking correctness gate is the golden set gate.
_BATCHES = 20


def _run_batch(cases: list[Any]) -> None:
    for case in cases:
        evaluation = evaluate_layer_a(
            initial_answers=case.initial_answers,
            final_synthesis=case.final_synthesis,
            agreement=case.agreement,
        )
        build_trust_score(evaluation)


def test_eval_batch_p95_is_within_the_advisory_ceiling() -> None:
    """The whole golden batch evaluates well under the advisory ceiling.

    Also a hermetic-purity smoke: if a future change introduces I/O or a
    network call into the "pure" Layer-A path, the per-batch time explodes and
    this trips — a cheap early warning even though it does not gate a merge.
    """
    cases = _golden.load_cases()
    assert cases, "golden set is empty; the baseline would measure nothing"

    _run_batch(cases)  # warm-up: JIT-free Python, but first-touch caches matter

    samples_ms: list[float] = []
    for _ in range(_BATCHES):
        start = time.perf_counter()
        _run_batch(cases)
        samples_ms.append((time.perf_counter() - start) * 1000.0)

    samples_ms.sort()
    p50 = statistics.median(samples_ms)
    p95 = samples_ms[max(0, int(0.95 * len(samples_ms)) - 1)]
    worst = samples_ms[-1]

    # Printed so the advisory eval.yml step summary carries the measured number
    # a human would transcribe into docs/55 if the baseline is ever re-measured.
    print(
        f"[PERF-010] eval-batch ({len(cases)} cases x {_BATCHES} batches): "
        f"p50={p50:.2f}ms p95={p95:.2f}ms max={worst:.2f}ms "
        f"budget={EVAL_BATCH_P95_BUDGET_MS:.0f}ms"
    )

    assert p95 < EVAL_BATCH_P95_BUDGET_MS, (
        f"eval-batch p95 {p95:.2f}ms exceeded the advisory ceiling "
        f"{EVAL_BATCH_P95_BUDGET_MS:.0f}ms. On a hermetic deterministic batch this "
        "usually means I/O or a network call entered a pure path, or an "
        "algorithmic blow-up — investigate before re-baselining."
    )
