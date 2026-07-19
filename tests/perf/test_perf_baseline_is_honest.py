"""The perf gate's *documented* baseline must stay honest (RB-2 follow-up).

Why this file exists
--------------------
``tests/perf/test_workflow_latency_percentiles.py`` derives every regression
budget from a measured stub baseline printed in its module docstring, and
annotates each budget with the headroom multiple it buys ("~6.2x worst observed
p95 (240.7 ms)"). Reviewers read those multiples as the safety margin. Prose,
however, is not executable: the first 2026-07-19 envelope stopped reproducing
on the very machine it was taken on within the same day (concurrent p95 measured
394-648 ms against a documented 206.1-240.7 ms, i.e. the advertised 6.2x was
really 2.3-3.8x), and nothing failed. The percentile gate itself stayed green
the whole time, because a *looser-than-advertised* margin is invisible to it.

So this module makes the documentation itself checkable:

``test_baseline_annotations_are_internally_consistent``
    Pure text/arithmetic, no timing, always runs. Every ``~Nx worst observed``
    annotation must actually equal ``budget / worst-observed``, the quoted
    worst-observed value must be the top of the quoted envelope, and the budget
    numbers in the prose must equal the live module constants. This catches the
    common drift: someone re-measures, updates the ranges, and forgets the
    multiples (or vice versa).

``test_documented_headroom_still_reproduces``
    Opt-in (``QUORUM_PERF_BASELINE_RECHECK=1``), because it re-measures. It
    asserts the advertised headroom is *substantially real here and now*: the
    live headroom multiple must be at least ``MIN_HONESTY_RATIO`` of the
    documented one. It is deliberately NOT part of the blocking ``perf-gate``
    job: the envelope is machine-specific (macOS/M4 laptop) and has never been
    measured on a GitHub Linux runner, so running it there would assert a
    number nobody has measured — exactly the sin it exists to prevent. That
    exclusion is now MECHANICAL, not just prose: the ``perf-gate`` recipe
    deselects this nodeid (``PERF_GATE_DESELECT``) and floors the executed count
    one below the collected floor. It has to be, because for its whole life the
    sentence above was false — this file sits on ``PERF_TEST_PATHS``, so the
    skip below reached ``gate-min-executed``'s anti-skip guard and failed the
    blocking job on every clean tree. Run it
    when you touch the pipeline or the baseline block, and when it fails,
    re-measure and rewrite the docstring rather than widening the tolerance.
    It skips rather than judges above ``MAX_LOAD_AVERAGE``, because a busy box
    measures the box, not the pipeline.

``QUORUM_PERF_BASELINE_DOC_PATH`` overrides which file the baseline block is
read from; it exists so the checks can be proven RED against a copy of a
known-stale docstring without touching the working tree.
"""

from __future__ import annotations

import importlib.util
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

#: ``tests/perf`` is not a package, so the gate module is loaded by path rather
#: than by import name — deterministic, and independent of pytest's sys.path
#: insertion order.
_GATE_PATH = Path(__file__).with_name("test_workflow_latency_percentiles.py")
_spec = importlib.util.spec_from_file_location("_perf_gate_under_review", _GATE_PATH)
assert _spec is not None and _spec.loader is not None
perf_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(perf_gate)

#: Fraction of the documented headroom multiple that must still be observable.
#: 0.7 allows the live measurement to be ~43 percent worse than the documented
#: worst-of-10 before the claim counts as stale — wide enough to absorb the
#: run-to-run spread actually observed (concurrent p95 394-648 ms across 10
#: runs, a 1.64x spread driven by the cold first run), narrow enough that the
#: 6.2x-vs-2.3x drift this file was written for is caught.
MIN_HONESTY_RATIO = 0.7

#: The documented envelope was taken at a 1-minute load average of 2.4-3.3 on a
#: 10-core M4. Measured here: the *same* tree re-measured while peer agents were
#: hammering the box (load ~7) produced concurrent p95 1216.5 ms against 394-648
#: ms at load ~3 — a 1.9x machine effect that has nothing to do with the
#: pipeline. Comparing headroom across those two worlds would be comparing
#: nothing, so above this load the check declines to judge (skip) instead of
#: emitting a verdict it cannot support. 4.0 = 40 percent of the cores the
#: baseline was taken on, comfortably above the 3.3 the baseline itself saw.
#: ``QUORUM_PERF_BASELINE_MAX_LOAD`` overrides it, since "how busy is too busy"
#: is a property of the machine (core count) rather than of this repo.
MAX_LOAD_AVERAGE = float(os.environ.get("QUORUM_PERF_BASELINE_MAX_LOAD", "4.0"))

_SECTION_KEYS = {
    "Sequential single-run latency": "SEQUENTIAL",
    "20-concurrent per-run latency": "CONCURRENT",
}

#: ``    p95 : 394.3 - 648.0 ms``
_ENVELOPE_RE = re.compile(r"^\s{4}(p50|p95|max)\s*:\s*([\d.]+)\s*-\s*([\d.]+) ms", re.MULTILINE)

#: ``    CONCURRENT_P95_BUDGET_MS = 1500   ~2.3x worst observed p95 (648.0 ms)``
_BUDGET_RE = re.compile(
    r"^\s{4}([A-Z0-9_]+_BUDGET_MS)\s*=\s*([\d.]+)\s+~([\d.]+)x worst observed "
    r"(p50|p95) \(([\d.]+) ms\)",
    re.MULTILINE,
)


def _baseline_text() -> str:
    override = os.environ.get("QUORUM_PERF_BASELINE_DOC_PATH")
    if override:
        return Path(override).read_text(encoding="utf-8")
    module_file = perf_gate.__file__
    assert module_file is not None
    return Path(module_file).read_text(encoding="utf-8")


def _documented_envelopes(text: str) -> dict[tuple[str, str], tuple[float, float]]:
    """Map (SEQUENTIAL|CONCURRENT, p50|p95|max) -> (min, max) from the prose."""
    envelopes: dict[tuple[str, str], tuple[float, float]] = {}
    for heading, load in _SECTION_KEYS.items():
        start = text.index(heading)
        section = text[start : start + 600]
        for metric, low, high in _ENVELOPE_RE.findall(section):
            envelopes.setdefault((load, metric), (float(low), float(high)))
    return envelopes


def _documented_budgets(text: str) -> dict[str, tuple[float, float, str, float]]:
    """Map constant name -> (budget, claimed multiple, metric, worst observed)."""
    return {
        name: (float(budget), float(multiple), metric, float(worst))
        for name, budget, multiple, metric, worst in _BUDGET_RE.findall(text)
    }


def test_baseline_annotations_are_internally_consistent() -> None:
    """The prose must agree with itself and with the live budget constants."""
    text = _baseline_text()
    envelopes = _documented_envelopes(text)
    budgets = _documented_budgets(text)

    assert set(envelopes) >= {
        ("SEQUENTIAL", "p50"),
        ("SEQUENTIAL", "p95"),
        ("CONCURRENT", "p50"),
        ("CONCURRENT", "p95"),
    }, f"baseline envelope block is missing rows: {sorted(envelopes)}"
    assert set(budgets) == {
        "SEQUENTIAL_P50_BUDGET_MS",
        "SEQUENTIAL_P95_BUDGET_MS",
        "CONCURRENT_P95_BUDGET_MS",
    }, f"budget annotations are missing or malformed: {sorted(budgets)}"

    for name, (budget, multiple, metric, worst) in budgets.items():
        load = name.split("_")[0]
        documented_worst = envelopes[(load, metric)][1]
        assert worst == documented_worst, (
            f"{name} claims worst observed {metric} = {worst} ms but the "
            f"{load.lower()} envelope tops out at {documented_worst} ms"
        )
        assert budget == getattr(perf_gate, name), (
            f"{name} is documented as {budget} ms but the constant is {getattr(perf_gate, name)} ms"
        )
        expected_multiple = round(budget / worst, 1)
        assert abs(multiple - expected_multiple) < 0.05, (
            f"{name} claims ~{multiple}x headroom but {budget}/{worst} = {expected_multiple}x"
        )


def _measure_now() -> dict[str, float]:
    """Re-measure the two gated percentiles exactly the way the gate does."""
    perf_gate._pin_static_catalog()  # noqa: SLF001 — same seam the gate uses
    from product_app.main import app

    client = TestClient(app)
    sequential = sorted(
        perf_gate._drive_one_run(client)[1]  # noqa: SLF001
        for _ in range(perf_gate.SEQUENTIAL_SAMPLE_COUNT)
    )
    with ThreadPoolExecutor(max_workers=perf_gate.CONCURRENT_RUN_COUNT) as pool:
        outcomes = list(
            pool.map(
                lambda _: perf_gate._drive_one_run(client),  # noqa: SLF001
                range(perf_gate.CONCURRENT_RUN_COUNT),
            )
        )
    concurrent = sorted(elapsed for _, elapsed in outcomes)
    return {
        "SEQUENTIAL_P50_BUDGET_MS": perf_gate._percentile(sequential, 50),  # noqa: SLF001
        "SEQUENTIAL_P95_BUDGET_MS": perf_gate._percentile(sequential, 95),  # noqa: SLF001
        "CONCURRENT_P95_BUDGET_MS": perf_gate._percentile(concurrent, 95),  # noqa: SLF001
    }


@pytest.mark.skipif(
    os.environ.get("QUORUM_PERF_BASELINE_RECHECK") != "1",
    reason="opt-in: re-measures the baseline; the envelope is laptop-specific "
    "and has never been measured on a CI runner (set QUORUM_PERF_BASELINE_RECHECK=1). "
    "The blocking perf-gate job deselects this nodeid via PERF_GATE_DESELECT, so "
    "this skip never reaches gate-min-executed's anti-skip guard.",
)
def test_documented_headroom_still_reproduces(monkeypatch: pytest.MonkeyPatch) -> None:
    """The advertised headroom multiples must still be substantially real."""
    from product_app.config import settings

    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", False)

    budgets = _documented_budgets(_baseline_text())
    load_before = os.getloadavg()[0]
    measured = _measure_now()
    load_after = os.getloadavg()[0]
    peak_load = max(load_before, load_after)
    if peak_load > MAX_LOAD_AVERAGE:
        pytest.skip(
            f"machine load average {peak_load:.1f} > {MAX_LOAD_AVERAGE} — the "
            "documented envelope was taken at 2.4-3.3; re-run on a quiet box"
        )

    stale: list[str] = []
    for name, (budget, claimed, metric, _worst) in budgets.items():
        observed = measured[name]
        live_multiple = budget / observed
        print(
            f"\n[PERF-DOC] {name}: documented ~{claimed}x, live "
            f"{live_multiple:.1f}x ({metric}={observed:.1f}ms, budget={budget:.0f}ms)"
        )
        if live_multiple < claimed * MIN_HONESTY_RATIO:
            stale.append(
                f"{name}: documented ~{claimed}x headroom, measured "
                f"{live_multiple:.1f}x ({metric}={observed:.1f}ms) — below the "
                f"{MIN_HONESTY_RATIO:.0%} honesty floor of {claimed * MIN_HONESTY_RATIO:.1f}x"
            )

    assert not stale, "documented perf baseline no longer reproduces:\n" + "\n".join(stale)
