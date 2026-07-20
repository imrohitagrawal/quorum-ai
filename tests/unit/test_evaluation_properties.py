"""Property tests for the two pieces with an unbounded input space.

* ``parse_judge_verdict`` reads attacker-influenceable provider output.
  Arbitrary junk must never crash it and must never yield a verdict.
* The TrustScore composite is arithmetic over Layer-A signals; it must stay
  bounded, its surfaced contributions must actually sum to the composite,
  and it must be monotonic in every weighted signal.

``deadline=None`` follows the existing repo convention (deadlines are a CI
flake source, see ``tests/contract/test_api_contract_schemathesis.py``).
"""

from __future__ import annotations

import json
import math
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from product_app.evaluation import (
    LAYER_A_WEIGHTS,
    EvalJudgeVerdict,
    LayerASignals,
    compute_composite,
    parse_judge_verdict,
)

_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

VALID_VERDICT: dict[str, Any] = {
    "faithfulness": 4,
    "grounding": 3,
    "disagreement_preserved": True,
    "hallucination_risk": "low",
    "rationale": "Claims track the cited sources.",
    "model_id": "vendor/judge-model",
}


@_SETTINGS
@given(st.text())
def test_arbitrary_text_never_crashes_the_verdict_parser(raw: str) -> None:
    result = parse_judge_verdict(raw)
    assert result is None or isinstance(result, EvalJudgeVerdict)


@_SETTINGS
@given(
    st.recursive(
        st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(),
        lambda children: (
            st.lists(children, max_size=4)
            | st.dictionaries(st.text(max_size=8), children, max_size=4)
        ),
        max_leaves=8,
    )
)
def test_arbitrary_json_never_yields_a_verdict_unless_it_conforms(payload: object) -> None:
    raw = json.dumps(payload)
    result = parse_judge_verdict(raw)
    if result is None:
        return
    # The only way through is a dict matching the schema exactly.
    assert isinstance(payload, dict)
    assert set(payload) == set(VALID_VERDICT)
    assert 0 <= result.faithfulness <= 5
    assert 0 <= result.grounding <= 5
    assert result.hallucination_risk in {"low", "medium", "high"}


@_SETTINGS
@given(
    st.dictionaries(
        st.sampled_from(sorted(VALID_VERDICT)),
        st.none() | st.booleans() | st.integers(-20, 20) | st.text(max_size=12),
        max_size=6,
    )
)
def test_mutated_verdict_payloads_are_accepted_only_when_fully_valid(
    overrides: dict[str, Any],
) -> None:
    payload = {**VALID_VERDICT, **overrides}
    result = parse_judge_verdict(json.dumps(payload))
    if result is None:
        return
    assert isinstance(payload["faithfulness"], int) and 0 <= payload["faithfulness"] <= 5
    assert isinstance(payload["grounding"], int) and 0 <= payload["grounding"] <= 5
    assert payload["hallucination_risk"] in {"low", "medium", "high"}


_UNIT = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


@st.composite
def _signals(draw: st.DrawFn, **overrides: Any) -> LayerASignals:
    values: dict[str, Any] = {
        "citation_coverage_ratio": draw(_UNIT),
        "citation_marker_grounding": draw(st.none() | _UNIT),
        "agreement_ratio": draw(_UNIT),
        "live_ratio": draw(_UNIT),
        "completeness": draw(_UNIT),
        "false_consensus_preserved": draw(st.booleans()),
        "polar_disagreement_detected": draw(st.booleans()),
        "disagreement_suppressed": draw(st.booleans()),
        "decision_support_framing_present": draw(st.booleans()),
        "high_stakes_warning_required": draw(st.booleans()),
        "high_stakes_warning_present": draw(st.booleans()),
        "uncertainty_surfaced": draw(st.booleans()),
        "refusal_detected": draw(st.booleans()),
        "run_wholly_refused": draw(st.booleans()),
    }
    values.update(overrides)
    return LayerASignals(**values)


@_SETTINGS
@given(_signals())
def test_composite_is_bounded_and_its_contributions_sum(signals: LayerASignals) -> None:
    composite, contributions = compute_composite(signals)
    assert 0.0 <= composite <= 100.0
    assert math.isclose(sum(c.contribution for c in contributions), composite, abs_tol=1e-6)
    for contribution in contributions:
        assert contribution.signal in LAYER_A_WEIGHTS
        assert 0.0 <= contribution.value <= 1.0
        assert contribution.contribution >= 0.0


@_SETTINGS
@given(_signals(), _UNIT, _UNIT)
def test_composite_is_monotonic_in_citation_marker_grounding(
    signals: LayerASignals, low: float, high: float
) -> None:
    lower, upper = sorted((low, high))
    worse, _ = compute_composite(signals.model_copy(update={"citation_marker_grounding": lower}))
    better, _ = compute_composite(signals.model_copy(update={"citation_marker_grounding": upper}))
    assert better >= worse - 1e-9


@_SETTINGS
@given(
    _signals(),
    _UNIT,
    _UNIT,
    st.sampled_from(["citation_coverage_ratio", "live_ratio", "completeness"]),
)
def test_composite_is_monotonic_in_every_weighted_ratio(
    signals: LayerASignals, low: float, high: float, field: str
) -> None:
    lower, upper = sorted((low, high))
    worse, _ = compute_composite(signals.model_copy(update={field: lower}))
    better, _ = compute_composite(signals.model_copy(update={field: upper}))
    assert better >= worse - 1e-9


@_SETTINGS
@given(_signals())
def test_suppressing_disagreement_never_helps_and_surfacing_uncertainty_never_hurts(
    signals: LayerASignals,
) -> None:
    suppressed, _ = compute_composite(signals.model_copy(update={"disagreement_suppressed": True}))
    preserved, _ = compute_composite(signals.model_copy(update={"disagreement_suppressed": False}))
    assert preserved >= suppressed - 1e-9

    silent, _ = compute_composite(signals.model_copy(update={"uncertainty_surfaced": False}))
    surfaced, _ = compute_composite(signals.model_copy(update={"uncertainty_surfaced": True}))
    assert surfaced >= silent - 1e-9
