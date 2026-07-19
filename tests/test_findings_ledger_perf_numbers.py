"""The findings ledger's RB-2 perf numbers must match the shipped gate (RB-2 follow-up).

Why this file exists
--------------------
``tests/perf/test_perf_baseline_is_honest.py`` keeps the perf gate's *own*
docstring honest, but it only ever reads
``tests/perf/test_workflow_latency_percentiles.py`` (``_GATE_PATH``). The
findings ledger restates the same envelope in its RB-2 status cell, and that
copy was unguarded: when the gate formally retracted its first 2026-07-19
envelope as non-reproducible (seq p50 34.0-35.7 ms, conc p95 206.1-240.7 ms,
advertised ~6.2x headroom) the ledger kept quoting the withdrawn numbers, and
all 47 ledger/plan/console consistency tests stayed green over it. A reviewer
reading the ledger — the brief's designated durable per-item status record —
would size the 1500 ms concurrent budget at ~6.2x headroom when the code says
~2.3x.

So this module makes the *restatement* checkable: every perf figure the ledger
quotes for RB-2 must equal the live envelope, budget constants and headroom
multiples parsed out of the gate. Re-measure once, edit the gate docstring, and
this test tells you the ledger still needs updating.

``QUORUM_FINDINGS_LEDGER_PATH`` overrides which file the RB-2 row is read from;
it exists so the check can be proven RED against a copy of a known-stale ledger
without touching the working tree.
"""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LEDGER_PATH = _REPO_ROOT / "docs" / "analysis" / "R2-plan-review-findings.md"

#: The honesty checker already knows how to parse the gate docstring; reuse it
#: rather than growing a second set of regexes that can drift from the first.
#: ``tests/perf`` is not a package, so load it by path like it loads the gate.
_HONESTY_PATH = _REPO_ROOT / "tests" / "perf" / "test_perf_baseline_is_honest.py"
_spec = importlib.util.spec_from_file_location("_perf_honesty_for_ledger", _HONESTY_PATH)
assert _spec is not None and _spec.loader is not None
perf_honesty = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(perf_honesty)

#: ``seq p50 40.3-44.1 ms, p95 42.2-82.3 ms; 20-concurrent p95 394.3-648.0 ms``
#: (the ledger renders the ranges with en dashes, hence the character class).
_LEDGER_ENVELOPE_RE = re.compile(
    r"seq p50 ([\d.]+)[-–]([\d.]+) ms, p95 ([\d.]+)[-–]([\d.]+) ms; "
    r"20-concurrent p95 ([\d.]+)[-–]([\d.]+) ms"
)

#: ``(150/300/1500 ms -> ~3.4x/~3.6x/~2.3x headroom ...)``
_LEDGER_BUDGET_RE = re.compile(
    r"\((\d+)/(\d+)/(\d+) ms[^)]*?~([\d.]+)[x×]/~([\d.]+)[x×]/~([\d.]+)[x×]"
)

#: Ledger order -> gate constant name, so the two triples line up positionally.
_BUDGET_ORDER = (
    "SEQUENTIAL_P50_BUDGET_MS",
    "SEQUENTIAL_P95_BUDGET_MS",
    "CONCURRENT_P95_BUDGET_MS",
)


def _rb2_row() -> str:
    path = Path(os.environ.get("QUORUM_FINDINGS_LEDGER_PATH", _LEDGER_PATH))
    rows = [
        line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("| RB-2 ")
    ]
    assert len(rows) == 1, f"expected exactly one RB-2 row in {path}, found {len(rows)}"
    return rows[0]


def test_ledger_rb2_quotes_the_live_perf_envelope() -> None:
    """The envelope restated in RB-2 must be the one the gate currently documents."""
    row = _rb2_row()
    gate_text = Path(perf_honesty.perf_gate.__file__).read_text(encoding="utf-8")
    envelopes = perf_honesty._documented_envelopes(gate_text)  # noqa: SLF001

    match = _LEDGER_ENVELOPE_RE.search(row)
    assert match, (
        "RB-2 does not quote a parseable perf envelope; expected "
        "'seq p50 A-B ms, p95 C-D ms; 20-concurrent p95 E-F ms'"
    )
    quoted = [float(value) for value in match.groups()]
    expected = [
        *envelopes[("SEQUENTIAL", "p50")],
        *envelopes[("SEQUENTIAL", "p95")],
        *envelopes[("CONCURRENT", "p95")],
    ]
    assert quoted == expected, (
        f"RB-2 quotes the envelope {quoted} but the shipped gate documents "
        f"{expected} — re-sync the ledger with the gate docstring"
    )


def test_ledger_rb2_quotes_the_live_budgets_and_headroom() -> None:
    """The budgets and headroom multiples in RB-2 must match the gate constants."""
    row = _rb2_row()
    gate_text = Path(perf_honesty.perf_gate.__file__).read_text(encoding="utf-8")
    budgets = perf_honesty._documented_budgets(gate_text)  # noqa: SLF001

    match = _LEDGER_BUDGET_RE.search(row)
    assert match, (
        "RB-2 does not quote parseable budgets + headroom; expected "
        "'(150/300/1500 ms ... ~Ax/~Bx/~Cx'"
    )
    quoted_budgets = [float(value) for value in match.groups()[:3]]
    quoted_multiples = [float(value) for value in match.groups()[3:]]

    for name, quoted_budget, quoted_multiple in zip(
        _BUDGET_ORDER, quoted_budgets, quoted_multiples, strict=True
    ):
        live_budget = getattr(perf_honesty.perf_gate, name)
        assert quoted_budget == live_budget, (
            f"RB-2 quotes {name} = {quoted_budget:.0f} ms but the constant is {live_budget} ms"
        )
        documented_multiple = budgets[name][1]
        assert quoted_multiple == documented_multiple, (
            f"RB-2 claims ~{quoted_multiple}x headroom for {name} but the gate "
            f"documents ~{documented_multiple}x"
        )
