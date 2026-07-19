"""Hermetic P50/P95 + concurrency gate for the query workflow (RB-2).

Requirements under test
-----------------------
* NFR-001 (docs/11): "Completed query latency P50 <= 45 seconds, P95 <= 120
  seconds, hard timeout at 180 seconds."
* NFR-004 (docs/11): "At least 95 percent of accepted queries return either a
  completed result or a partial-result explanation within 180 seconds."
* PERF-004 (docs/55): "Full stubbed query workflow | 20 concurrent synthetic
  accounts ... <= 45 seconds p50 | <= 120 seconds p95 | >= 95 percent completed
  or partial within 180 seconds." docs/55 Acceptance Gates: "No implementation
  release if P95 full stubbed workflow exceeds 120 seconds."

Why two budgets per test
------------------------
The docs/55 release gate (45s/120s/180s) is the *contract* and is asserted
verbatim below — but against the stubbed pipeline it is ~4000x looser than
reality, so on its own it would never catch a regression. Every assertion
therefore comes in a pair:

1. a **regression budget** derived from a measured stub baseline, which is what
   actually bites; and
2. the **release gate** from docs/55, which is what we promised.

Measured stub baseline (re-measured 2026-07-19 on the Phase-0 tree, macOS/darwin
25.5.0, Apple M4 / 10 cores, stubbed providers, full POST + GET round trip).
Numbers below are from 10 consecutive runs of this very file (`uv run pytest
tests/perf -q --no-cov -p no:randomly -s`), 10/10 green — not from a hand-rolled
harness, so they include pytest/log-capture overhead exactly as CI will see it.
The machine was *not* idle: `uptime` load average was 2.4-3.3 throughout
(concurrent Phase-0 agent work on the same box), which is recorded here because
it is part of the measurement, not noise to be wished away:

Sequential single-run latency, n=40 per run, 10 runs:

    p50 : 40.3 - 44.1 ms
    p95 : 42.2 - 82.3 ms
    max : 44.9 - 83.4 ms  (the 82/83 ms pair is run 1 of the batch — cold
                           interpreter/first-touch caches; runs 2-10 sit at
                           42-51 ms)

20-concurrent per-run latency, 10 runs:

    p50 : 390.3 - 645.4 ms
    p95 : 394.3 - 648.0 ms  (again, 648 ms is the cold run 1; runs 2-10 span
                             394 - 448 ms)

Chosen regression budgets (headroom multiple over the *worst* observed value):

    SEQUENTIAL_P50_BUDGET_MS = 150    ~3.4x worst observed p50 (44.1 ms)
    SEQUENTIAL_P95_BUDGET_MS = 300    ~3.6x worst observed p95 (82.3 ms)
    CONCURRENT_P95_BUDGET_MS = 1500   ~2.3x worst observed p95 (648.0 ms)

The envelope is load-dependent, and that is not a footnote: re-checks later the
same day on the same tree, with more peer agents running, measured sequential
p50 up to 63.5 ms and concurrent p95 up to 1216.5 ms — outside the 10-run
envelope above and, for the concurrent case, within 1.23x of the 1500 ms budget.
Read the ~Nx multiples below as "at load average ~3", not as a property of the
code alone.

An earlier version of this block quoted a much faster envelope (seq p50
34.0-35.7 ms, conc p95 206.1-240.7 ms) and derived ~4.2x/~5.9x/~6.2x headroom
from it. That envelope no longer reproduces on this machine — 11/11 fresh runs
landed outside it — so it has been replaced rather than annotated. The budget
*constants* are unchanged; only the honest description of the margin they buy
has changed. Note what that means: the concurrent budget now carries ~2.3x of
headroom over a worst-case local run, not ~6.2x. Whether 1500 ms is still the
right number is a guardrail decision that needs a real CI-runner measurement
(none exists yet) and a human call — it is deliberately not changed here on the
strength of one laptop under load.

Measured detection sensitivity, re-measured the same day on the same tree (a
``time.sleep`` injected into every ``produce_initial_answer`` call via a
throwaway pytest plugin, so the product code is untouched):

    +30 ms/call  -> seq p50  78.8 ms, conc p95  598.3 ms -> NOT caught
    +150 ms/call -> seq p50 198.2 ms, conc p95 1221.1 ms -> caught (seq p50 only)
    +300 ms/call -> seq p50 353.9 ms, conc p95 2021.5 ms -> caught (both)

So the sequential p50 budget is the sharp edge of this gate: it catches roughly
a +150 ms/call (~4.5x end-to-end) slowdown, while the concurrent budget needs
~+300 ms/call. A +30 ms/call regression still slips through. That is the honest
cost of headroom sized for an unmeasured CI runner. Ratchet the budgets down
(and this note with them) once real CI-runner numbers exist.

This block is not decorative prose: ``tests/perf/test_perf_baseline_is_honest.py``
parses it and fails the build if the quoted envelopes, the ``~Nx`` annotations
and the live budget constants stop agreeing, and (opt-in, via
``QUORUM_PERF_BASELINE_RECHECK=1``) if a fresh measurement shows the advertised
headroom is no longer substantially real. That checker exists precisely because
the previous envelope went stale silently.

Hermeticity ($0, no egress) is a construction, not a convention: live
execution is pinned off and the model catalog is pinned to the shipped static
list (see ``_pin_static_catalog``), and that claim is itself gated by
``tests/perf/test_perf_gate_hermeticity.py``, which runs this module in a
fresh interpreter with outbound sockets blocked.

Not in scope: PERF-010 (AI eval batch runtime) is DEFERRED to R2 S4 — its
baseline is "selected after eval harness design" in docs/55 and is not set here.
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from time import monotonic, perf_counter
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.catalog_fetcher import _FALLBACK_CATALOG, openrouter_catalog_fetcher
from product_app.config import settings
from product_app.query_runs import TERMINAL_STATUSES, QueryRunStatus
from product_app.safety import WARNING_VERSION, WarningType

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]

#: TTL used when pinning the static catalog. Long enough that the pin never
#: expires mid-session and lets a fetch through.
_CATALOG_PIN_TTL_SECONDS = 86_400.0


def _pin_static_catalog() -> None:
    """Serve the app's own static offline catalog instead of fetching it.

    Hermeticity hole this closes: importing ``product_app.main`` calls
    ``openrouter_catalog_fetcher.prewarm()`` (main.py:252) which opens a live
    HTTPS connection, and model-slot validation calls ``list_models()`` on
    every POST. Two of the four ids below are not in the curated
    ``model_slots.DEFAULT_MODEL_IDS`` whitelist, so with egress blocked the
    POST returned ``422 INVALID_MODEL_SLOT`` and this *blocking* CI job failed
    on a third party's uptime rather than on the change under test (measured
    2026-07-19: 69 blocked connect attempts, both tests red).

    Priming the shared fetcher's cache is the smallest seam that covers both
    call sites — ``_cache_valid()`` short-circuits before any transport is
    touched, so prewarm and validation both stay offline. ``_FALLBACK_CATALOG``
    is the same static list the app itself serves in degraded mode, so the
    gate measures the pipeline the app really runs.
    """
    openrouter_catalog_fetcher._cache_entries = list(_FALLBACK_CATALOG)  # noqa: SLF001
    openrouter_catalog_fetcher._cache_expires_at = monotonic() + _CATALOG_PIN_TTL_SECONDS  # noqa: SLF001


# Executed at import time, i.e. *before* the client fixture imports
# ``product_app.main`` and its startup fires ``prewarm()``. Ordering matters:
# a pin applied from a fixture would run after the prewarm thread had already
# reached the network. ``tests/perf/test_perf_gate_hermeticity.py`` is the
# mechanical proof that this holds, in a fresh interpreter with sockets blocked.
_pin_static_catalog()

#: docs/55 / NFR-001 release gate, in milliseconds. These are the contract
#: numbers, not the regression budget.
RELEASE_GATE_P50_MS = 45_000
RELEASE_GATE_P95_MS = 120_000
RELEASE_GATE_HARD_TIMEOUT_MS = 180_000

#: Regression budgets derived from the measured stub baseline (see docstring).
SEQUENTIAL_P50_BUDGET_MS = 150.0
SEQUENTIAL_P95_BUDGET_MS = 300.0
CONCURRENT_P95_BUDGET_MS = 1500.0

#: Sample counts. 40 sequential samples make the p95 (nearest-rank => the 38th
#: sorted sample) meaningful rather than "the single slowest run". 20 concurrent
#: runs is the PERF-004 load exactly.
SEQUENTIAL_SAMPLE_COUNT = 40
CONCURRENT_RUN_COUNT = 20


def _percentile(sorted_samples: list[float], percentile: float) -> float:
    """Nearest-rank percentile. No interpolation: with 40 samples the rank is
    unambiguous and interpolation would only blur which observation failed."""
    rank = max(1, math.ceil(percentile / 100.0 * len(sorted_samples)))
    return sorted_samples[rank - 1]


def _drive_one_run(client: TestClient) -> tuple[str, float]:
    """Drive one full stubbed query run; return (terminal status, elapsed ms).

    A fresh account id per run keeps us clear of both the one-active-run-per-
    account rule and the 30-requests-per-account-per-minute limiter. The legacy
    ``X-Account-Id`` path executes the pipeline *inline* (see
    ``create_query_run``), so the POST round trip already contains the whole
    workflow — this measures the workflow, not a poll loop.
    """
    headers = {"X-Account-Id": str(uuid4())}
    started_at = perf_counter()
    create_response = client.post(
        "/v1/query-runs",
        json={
            "query_text": "Compare release hardening evidence",
            "model_slots": DEFAULT_MODEL_IDS,
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
            ],
        },
        headers=headers,
    )
    assert create_response.status_code == 202, create_response.text
    result_response = client.get(
        f"/v1/query-runs/{create_response.json()['query_run_id']}",
        headers=headers,
    )
    assert result_response.status_code == 200, result_response.text
    elapsed_ms = (perf_counter() - started_at) * 1000
    return result_response.json()["status"], elapsed_ms


@pytest.fixture(autouse=True)
def force_stubbed_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the gate hermetic ($0) by construction, not by convention.

    ``make perf-gate``/CI export ``OPENROUTER_LIVE_EXECUTION_ENABLED=false``,
    but a developer's local ``.env`` may enable live execution *and* carry a
    real ``OPENROUTER_API_KEY`` — running this file directly would then fire
    paid provider calls and, measured here, inflate the p50 from ~37 ms to
    ~340 ms (measured 2026-07-19). Both outcomes are unacceptable: the gate
    must cost nothing and must measure the stub pipeline only. Every consumer
    of the flag reads ``settings`` at call time, so pinning it here is enough.

    The catalog is pinned to the static offline list for the same reason — see
    ``_pin_static_catalog``. It is re-pinned per test so a peer test that calls
    ``invalidate_cache()`` cannot silently put this gate back on the network.
    """
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", False)
    _pin_static_catalog()


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    # Imported here, not at module scope, so the catalog pin above is already in
    # place when main's module-level startup calls ``prewarm()``.
    from product_app.main import app

    return TestClient(app)


def test_sequential_workflow_latency_percentiles_stay_within_budget(
    client: TestClient,
) -> None:
    """NFR-001: p50/p95 of the full stubbed workflow, sequential load."""
    samples = sorted(_drive_one_run(client)[1] for _ in range(SEQUENTIAL_SAMPLE_COUNT))

    p50 = _percentile(samples, 50)
    p95 = _percentile(samples, 95)
    print(
        f"\n[PERF] sequential n={len(samples)} min={samples[0]:.1f}ms "
        f"p50={p50:.1f}ms p95={p95:.1f}ms max={samples[-1]:.1f}ms"
    )

    # The regression budget — this is the assertion that bites.
    assert p50 <= SEQUENTIAL_P50_BUDGET_MS, (
        f"stub p50 regressed: {p50:.1f}ms > {SEQUENTIAL_P50_BUDGET_MS}ms budget"
    )
    assert p95 <= SEQUENTIAL_P95_BUDGET_MS, (
        f"stub p95 regressed: {p95:.1f}ms > {SEQUENTIAL_P95_BUDGET_MS}ms budget"
    )
    # The docs/55 release gate — what we actually promised.
    assert p50 <= RELEASE_GATE_P50_MS
    assert p95 <= RELEASE_GATE_P95_MS
    assert samples[-1] < RELEASE_GATE_HARD_TIMEOUT_MS


def test_twenty_concurrent_runs_all_reach_terminal_state_within_budget(
    client: TestClient,
) -> None:
    """PERF-004 / NFR-004: 20 concurrent stubbed runs, zero errors, bounded p95."""
    with ThreadPoolExecutor(max_workers=CONCURRENT_RUN_COUNT) as pool:
        outcomes = list(pool.map(lambda _: _drive_one_run(client), range(CONCURRENT_RUN_COUNT)))

    statuses = [status for status, _ in outcomes]
    samples = sorted(elapsed for _, elapsed in outcomes)
    p50 = _percentile(samples, 50)
    p95 = _percentile(samples, 95)
    print(
        f"\n[PERF] concurrent n={len(samples)} p50={p50:.1f}ms "
        f"p95={p95:.1f}ms max={samples[-1]:.1f}ms statuses={sorted(set(statuses))}"
    )

    assert len(outcomes) == CONCURRENT_RUN_COUNT
    # Every run reaches a terminal state...
    assert all(QueryRunStatus(status) in TERMINAL_STATUSES for status in statuses), statuses
    # ...and NFR-004 requires >= 95 percent of them to be completed-or-partial.
    # With deterministic stubs and no injected faults the only acceptable
    # outcome is 100 percent: a single ``failed``/``timed_out`` here is a real
    # defect, not noise, so we assert the strict form.
    assert all(
        QueryRunStatus(status) in {QueryRunStatus.COMPLETED, QueryRunStatus.PARTIAL}
        for status in statuses
    ), statuses

    assert p95 <= CONCURRENT_P95_BUDGET_MS, (
        f"concurrent p95 regressed: {p95:.1f}ms > {CONCURRENT_P95_BUDGET_MS}ms budget"
    )
    # docs/55 release gate for PERF-004.
    assert p50 <= RELEASE_GATE_P50_MS
    assert p95 <= RELEASE_GATE_P95_MS
    assert samples[-1] < RELEASE_GATE_HARD_TIMEOUT_MS
