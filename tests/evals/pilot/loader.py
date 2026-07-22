"""P2 accuracy-pilot loader: operator labels + engine-derived agreement.

The pilot scores the real Layer-A engine against 7 OPERATOR-AUTHORED
subject-matter correctness labels (Rohit Agrawal, 2026-07-22), transcribed
verbatim into ``operator_labels.json`` next to this module. Three integrity
rules, all load-bearing:

1. **This module authors ZERO labels.** It loads, validates, and scores. A
   label that fails validation raises — it is never repaired, defaulted, or
   dropped. The loader rejects: an EMPTY label set (an unlabeled pilot must
   never silently report 100%), a ``correctness`` outside the engine's own
   three-value enum, a ``case_id`` with no golden case, a duplicate
   ``case_id``, and a missing/blank provenance field.

2. **Engine verdicts are RE-DERIVED through the real engine.** Agreement runs
   ``product_app.evaluation.evaluate_layer_a`` over the golden fixtures (loaded
   via the S4 golden loader — reused by path, not forked, exactly as the golden
   gate does). The fixture's own ``label`` field is deliberately never read
   here, so the pilot cannot quote a pre-recorded verdict.

3. **The agreement mapping was declared BEFORE computing** (see
   ``docs/metrics/accuracy-pilot.md``): engine ``faithfulness_label`` and
   operator ``correctness`` share the same three-value vocabulary — the
   operator queue defines ``correctness`` as ``faithful | unfaithful |
   partial`` in the engine's own terms — so agreement is the IDENTITY
   comparison, with no re-bucketing available to tune post-hoc.

Zero I/O beyond reading tracked files next to this module. No network, no
judge, no clock, no randomness.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

from product_app.evaluation import FaithfulnessLabel, evaluate_layer_a

# Reuse the S4 golden loader by path (the same pattern the golden gate uses);
# never fork its primitives.
_GOLDEN_LOADER_PATH = Path(__file__).resolve().parents[1] / "golden" / "loader.py"
_spec = importlib.util.spec_from_file_location("s4_golden_loader_for_pilot", _GOLDEN_LOADER_PATH)
assert _spec is not None and _spec.loader is not None
_golden = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("s4_golden_loader_for_pilot", _golden)
_spec.loader.exec_module(_golden)

OPERATOR_LABELS_PATH = Path(__file__).resolve().parent / "operator_labels.json"

#: The engine's faithfulness vocabulary — also the operator queue's
#: ``correctness`` enum. Derived from the engine's own type (not re-typed) so
#: the shared vocabulary that legitimises the identity mapping cannot drift.
CORRECTNESS_VALUES: tuple[str, ...] = get_args(FaithfulnessLabel)

_REQUIRED_FIELDS = ("case_id", "correctness", "error_if_any", "source", "reviewer", "note")


@dataclass(frozen=True)
class OperatorLabel:
    """One operator-authored subject-matter correctness label, verbatim."""

    case_id: str
    correctness: str
    error_if_any: str
    source: str
    reviewer: str
    note: str


@dataclass(frozen=True)
class PilotRow:
    """One scored case: the engine's re-derived verdict vs the human label."""

    case_id: str
    engine_verdict: str
    operator_correctness: str
    agree: bool


@dataclass(frozen=True)
class PilotResult:
    rows: tuple[PilotRow, ...]

    @property
    def n(self) -> int:
        return len(self.rows)

    @property
    def agreed(self) -> int:
        return sum(1 for row in self.rows if row.agree)


def load_operator_labels(path: Path = OPERATOR_LABELS_PATH) -> list[OperatorLabel]:
    """Load and validate the operator labels; raise on anything suspect."""
    raw: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    if not raw:
        raise ValueError(
            f"{path.name}: empty operator-label set — an unlabeled pilot must not "
            "silently report agreement over nothing"
        )
    golden_ids = {case.case_id for case in _golden.load_cases()}
    labels: list[OperatorLabel] = []
    for row in raw:
        # A field is present only if it is a non-blank STRING — JSON null must
        # not slip through as the truthy string "None".
        missing = [
            field
            for field in _REQUIRED_FIELDS
            if not isinstance(row.get(field), str) or not row[field].strip()
        ]
        if missing:
            raise ValueError(
                f"{path.name}: label {row.get('case_id', '<no case_id>')!r} is missing "
                f"required field(s) {missing} — every label must carry its full "
                "operator provenance"
            )
        if row["correctness"] not in CORRECTNESS_VALUES:
            raise ValueError(
                f"{path.name}: {row['case_id']!r} carries correctness "
                f"{row['correctness']!r}, not one of {CORRECTNESS_VALUES}"
            )
        if row["case_id"] not in golden_ids:
            raise ValueError(
                f"{path.name}: label case_id {row['case_id']!r} has no golden case; "
                f"known cases: {sorted(golden_ids)}"
            )
        labels.append(OperatorLabel(**{field: row[field] for field in _REQUIRED_FIELDS}))
    ids = [label.case_id for label in labels]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path.name}: duplicate case_id in {ids}")
    return labels


def compute_pilot(
    labels_path: Path = OPERATOR_LABELS_PATH,
    evaluate: Callable[..., Any] = evaluate_layer_a,
) -> PilotResult:
    """Score the engine against the operator labels through the REAL engine.

    ``evaluate`` is injectable only so a test can prove the harness actually
    calls the engine (a perturbed engine must change the result); production
    use is always the real ``evaluate_layer_a``.
    """
    labels = load_operator_labels(labels_path)
    cases = {case.case_id: case for case in _golden.load_cases()}
    rows = []
    for label in sorted(labels, key=lambda item: item.case_id):
        case = cases[label.case_id]
        evaluation = evaluate(
            initial_answers=case.initial_answers,
            final_synthesis=case.final_synthesis,
            agreement=case.agreement,
        )
        verdict = evaluation.faithfulness_label
        rows.append(
            PilotRow(
                case_id=label.case_id,
                engine_verdict=verdict,
                operator_correctness=label.correctness,
                # The pre-declared identity mapping — see the module docstring.
                agree=verdict == label.correctness,
            )
        )
    return PilotResult(rows=tuple(rows))
