"""W48 review: two trust-score evaluations for the "caution" and "refused" boxes.

``e2e/fixtures/evaluation-variants.json`` (pinned to exactly seven named
variants by ``tests/contract/test_golden_fixture_matches_served_schema.py``)
has no variant whose box renders the "caution" or the "refused" state line,
so the trust hint's claims were never read against those two boxes.

``e2e/fixtures/evaluation-trust-branches.json`` holds two evaluations built
HERE, with the server's own functions, the way
``query_run_orchestration._evaluation_projection`` builds one:
``classify_faithfulness``, ``classify_hallucination_risk``,
``presentation_confidence`` and ``build_trust_score`` (which calls
``compute_composite``), then ``QueryRunEvaluationProjection``. They start from
EVAL_CLEAN's signals, with every citation marker resolving and every
returned answer carrying a primary source (grounding and coverage 1.0, so the
box lists no citation or source shortfall), and change one thing each:

* ``EVAL_CAUTION_SLOT_MISSING`` -- ``completeness`` 0.75 (one of four model
  slots produced no usable answer): the run is classified ``partial``, so the
  box says "The structural checks did not clear this run ..." and "Not every
  model slot produced a usable answer.";
* ``EVAL_REFUSED`` -- ``refusal_detected`` and ``run_wholly_refused`` true:
  the box says "The panel declined. Nothing was asserted, and nothing was
  verified."

To regenerate the JSON after a server change, run
``PYTHONPATH=src uv run python -m tests.unit.test_trust_branch_fixtures``.
What turns each test red is stated on the test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from tests.repo_root import find_repo_root

from product_app.evaluation import (
    EVAL_SCHEMA_VERSION,
    LayerASignals,
    RunEvaluation,
    build_trust_score,
    classify_faithfulness,
    classify_hallucination_risk,
    presentation_confidence,
)
from product_app.query_runs import QueryRunEvaluationProjection

ROOT = find_repo_root(Path(__file__))
VARIANTS_JSON = ROOT / "e2e" / "fixtures" / "evaluation-variants.json"
BRANCHES_JSON = ROOT / "e2e" / "fixtures" / "evaluation-trust-branches.json"

#: What each built evaluation changes in EVAL_CLEAN's signals.
CHANGES: dict[str, dict[str, Any]] = {
    "EVAL_CAUTION_SLOT_MISSING": {
        "completeness": 0.75,
        "citation_marker_grounding": 1.0,
        "citation_coverage_ratio": 1.0,
    },
    "EVAL_REFUSED": {
        "refusal_detected": True,
        "run_wholly_refused": True,
        "citation_marker_grounding": 1.0,
        "citation_coverage_ratio": 1.0,
    },
}


def build_branch_fixtures() -> dict[str, dict[str, Any]]:
    """The two evaluations, built the way the server builds a served one."""
    clean = json.loads(VARIANTS_JSON.read_text(encoding="utf-8"))["EVAL_CLEAN"]
    built: dict[str, dict[str, Any]] = {}
    for name, change in CHANGES.items():
        signals = LayerASignals.model_validate({**clean["signals"], **change})
        faithfulness = classify_faithfulness(signals)
        risk = classify_hallucination_risk(signals)
        evaluation = RunEvaluation(
            schema_version=EVAL_SCHEMA_VERSION,
            signals=signals,
            faithfulness_label=faithfulness,
            hallucination_risk=risk,
        )
        projection = QueryRunEvaluationProjection(
            schema_version=evaluation.schema_version,
            signals=evaluation.signals,
            faithfulness_label=faithfulness,
            hallucination_risk=risk,
            label_confidence=presentation_confidence(
                signals, faithfulness_label=faithfulness, hallucination_risk=risk
            ),
            trust=build_trust_score(evaluation),
        )
        built[name] = projection.model_dump(mode="json")
    return built


def _box_state(ev: dict[str, Any]) -> str:
    """The state line ``renderTrustScore`` picks for an unverified evaluation
    (app.js, the D-2 priority table: first match wins)."""
    signals = ev["signals"]
    if ev["label_confidence"] != "reportable":
        return "indeterminate"
    if signals["citation_marker_grounding"] is None:
        return "no-marker"
    if signals["refusal_detected"] is True:
        return "refused"
    if ev["faithfulness_label"] != "faithful" or ev["hallucination_risk"] != "low":
        return "caution"
    return "passed"


def _committed() -> dict[str, dict[str, Any]]:
    data = json.loads(BRANCHES_JSON.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def test_the_committed_fixture_is_exactly_what_the_server_functions_build() -> None:
    """RED IF: the committed JSON is hand-edited, or a server change (a
    classifier, a weight, the projection's fields) means the server would now
    build something else. Regenerate with the module's ``__main__``."""
    assert _committed() == build_branch_fixtures()


@pytest.mark.parametrize("name", sorted(CHANGES))
def test_each_branch_fixture_validates_against_the_served_projection(name: str) -> None:
    """RED IF: a fixture is not a shape the server can serve, or carries a
    score on an unverified band (OC-2)."""
    projection = QueryRunEvaluationProjection.model_validate(_committed()[name])
    assert projection.trust.support_verified is False
    assert projection.trust.band == "unverified"
    assert projection.trust.score is None


def test_the_fixtures_render_the_caution_and_the_refused_boxes() -> None:
    """RED IF: either fixture stops reaching its box state, so the e2e loop
    that reads it would test a different box. Partner: EVAL_CLEAN, read by the
    same function, is "passed" -- the function can tell the states apart."""
    clean = json.loads(VARIANTS_JSON.read_text(encoding="utf-8"))["EVAL_CLEAN"]
    assert _box_state(clean) == "passed"
    committed = _committed()
    assert _box_state(committed["EVAL_CAUTION_SLOT_MISSING"]) == "caution"
    assert _box_state(committed["EVAL_REFUSED"]) == "refused"


if __name__ == "__main__":
    payload: dict[str, Any] = {
        "_comment": (
            "Built by tests/unit/test_trust_branch_fixtures.py with the server's own "
            "functions; do not edit by hand. EVAL_CAUTION_SLOT_MISSING renders the "
            "'caution' trust box, EVAL_REFUSED the 'refused' one (W48 review)."
        ),
        **build_branch_fixtures(),
    }
    BRANCHES_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(f"wrote {BRANCHES_JSON}\n")
